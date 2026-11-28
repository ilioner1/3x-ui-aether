import argparse
import asyncio
import contextlib
import datetime
import os
from pathlib import Path
import socket
import ssl
import tempfile
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import bond


def certificates(path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certfile = path / "cert.pem"
    keyfile = path / "key.pem"
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return str(certfile), str(keyfile)


async def echo(reader, writer):
    while data := await reader.read(8192):
        writer.write(data)
        await writer.drain()
    writer.close()
    await writer.wait_closed()


async def wait_for(predicate):
    async with asyncio.timeout(9):
        while not predicate():
            await asyncio.sleep(0.02)


async def verify_500_paths():
    class RecordingSocket:
        def __init__(self):
            self.transport = self
            self.buffered = 0
            self.frames = []

        def get_write_buffer_size(self):
            return self.buffered

        async def send(self, message):
            self.frames.append(message)

    session = bond.Session()
    lanes = [bond.Lane(RecordingSocket(), 0.01) for _ in range(500)]
    for lane in lanes:
        session.pool.add(lane)
    stream = bond.Stream(session, bytes(16))
    reader = asyncio.StreamReader()
    reader.feed_data(b"x" * bond.CHUNK * len(lanes))
    reader.feed_eof()
    await asyncio.wait_for(stream.upload(reader), 5)
    for sequence, lane in enumerate(lanes):
        first = lane.websocket.frames[0]
        assert bond.HEADER.unpack_from(first) == (bond.DATA, stream.id, sequence)
        assert lane.sent == bond.CHUNK
    assert len(stream.pending) == 501
    stream.accept(bond.ACK, 501, b"")
    assert not stream.pending

    lanes[0].websocket.buffered = 2 * bond.CHUNK
    session.pool.positions[True] = 0
    await stream.send(bond.DATA, 501, b"ready")
    assert lanes[0].sent == bond.CHUNK
    assert lanes[1].sent == bond.CHUNK + len(b"ready")
    print("PASS: one upload carried data across all 500 simulated paths")

    dual_stack = bond.Pool()
    ipv4 = [bond.Lane(RecordingSocket(), 0.01, family=4) for _ in range(3)]
    ipv6 = bond.Lane(RecordingSocket(), 0.01, family=6)
    for lane in [*ipv4, ipv6]:
        dual_stack.add(lane)
    for sequence in range(6):
        await dual_stack.send(bond.frame(bond.DATA, stream.id, sequence, b"x"))
    assert [lane.sent for lane in ipv4] == [1, 1, 1]
    assert ipv6.sent == 3
    ipv6.websocket.buffered = 2 * bond.CHUNK
    for sequence in range(6, 10):
        await dual_stack.send(bond.frame(bond.DATA, stream.id, sequence, b"x"))
    assert sum(lane.sent for lane in ipv4) == 7
    assert ipv6.sent == 3
    ipv6.websocket.buffered = 0
    await dual_stack.send(bond.frame(bond.DATA, stream.id, 10, b"x"))
    assert ipv6.sent == 4
    dual_stack.remove(ipv6)
    await dual_stack.send(bond.frame(bond.DATA, stream.id, 11, b"x"))
    assert sum(lane.sent for lane in ipv4) == 8
    print("PASS: MASQUE data alternates IP families and skips a backed-up family")


async def verify():
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        cert, key = certificates(directory)
        endpoints = directory / "peers.txt"
        endpoints.write_text("127.0.0.1\n127.0.0.2\n127.0.0.2\n", encoding="utf-8")
        assert bond.load_endpoints(endpoints) == ["127.0.0.1", "127.0.0.2"]
        with socket.socket() as probe:
            probe.bind(("0.0.0.0", 0))
            port = probe.getsockname()[1]
        args = argparse.Namespace(bind="0.0.0.0", port=port, path="/bond", cert=cert,
                                  key=key, max_paths=2, allow_private_destinations=True,
                                  url=f"wss://localhost:{port}/bond", ca_file=cert,
                                  endpoints=str(endpoints), probe_rate=20, secret="example_" * 8)
        session = bond.Session()
        gateway = asyncio.create_task(bond.gateway(args))
        jobs = [session.start(session.maintain())]
        jobs.append(session.start(bond.discovery(args, urlsplit(args.url), session)))
        try:
            await wait_for(lambda: len(session.pool.lanes) == 2)
            async with bond.connect(args.url, ssl=ssl.create_default_context(cafile=cert), proxy=None) as denied:
                try:
                    await denied.recv()
                except bond.ConnectionClosed as error:
                    assert error.rcvd.code == 1008
                else:
                    raise AssertionError("Unauthenticated path was accepted")
            async with await asyncio.start_server(echo, "127.0.0.1", 0) as target:
                async with await asyncio.start_server(lambda r,w: bond.socks_client(r,w,session), "127.0.0.1", 0) as socks:
                    reader, writer = await asyncio.open_connection("127.0.0.1", socks.sockets[0].getsockname()[1])
                    writer.write(b"\x05\x01\x00")
                    await writer.drain()
                    assert await reader.readexactly(2) == b"\x05\x00"
                    writer.write(b"\x05\x01\x00\x01\x7f\x00\x00\x01" + target.sockets[0].getsockname()[1].to_bytes(2,"big"))
                    await writer.drain()
                    assert (await reader.readexactly(10))[1] == 0
                    lane1, lane2 = session.pool.lanes
                    data = os.urandom(280000)
                    writer.write(data)
                    await writer.drain()
                    assert await asyncio.wait_for(reader.readexactly(len(data)), 10) == data
                    assert lane1.sent > 0 and lane2.sent > 0
                    writer.write(data)
                    await lane1.websocket.close()
                    await wait_for(lambda: len(session.pool.lanes) == 1)
                    await writer.drain()
                    assert await asyncio.wait_for(reader.readexactly(len(data)), 10) == data
                    writer.write_eof()
                    await writer.drain()
                    assert await asyncio.wait_for(reader.read(), 10) == b""
                    writer.close()
                    await writer.wait_closed()
            async with await asyncio.start_server(echo, "127.0.0.1", 0) as private_target:
                with contextlib.suppress(OSError):
                    _, socket_writer = await bond.open_target("127.0.0.1", private_target.sockets[0].getsockname()[1], False)
                    socket_writer.close()
                    raise AssertionError("Private destination accepted")
            print("PASS: verified two data paths, custom IP overrides, ordered traffic, and failover")
        finally:
            session.close()
            gateway.cancel()
            await asyncio.gather(gateway, *jobs, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(verify_500_paths())
    asyncio.run(verify())
