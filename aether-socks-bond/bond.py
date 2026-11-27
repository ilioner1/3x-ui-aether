"""Bond TCP streams over authenticated WebSocket paths."""
import argparse
import asyncio
import contextlib
import hmac
import ipaddress
import json
import os
import socket
import ssl
import struct
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, InvalidHandshake

OPEN, OK, FAIL, DATA, FIN, ACK, RESET = range(7)
HEADER = struct.Struct("!B16sI")
CHUNK = 16 * 1024
WINDOW = 32
RETRY = 1.0
MAX_STREAMS = 256
SESSION_GRACE = 45


def frame(kind, stream_id, sequence=0, payload=b""):
    return HEADER.pack(kind, stream_id, sequence) + payload


@dataclass(eq=False)
class Lane:
    websocket: object
    latency: float
    sent: int = 0


class Pool:
    def __init__(self):
        self.lanes = []
        self.positions = {True: 0, False: 0}
        self.available = asyncio.Event()
        self.last_online = time.monotonic()
        self.closed = False

    def add(self, lane):
        self.lanes.append(lane)
        self.available.set()

    def remove(self, lane):
        if lane in self.lanes:
            self.lanes.remove(lane)
        if not self.lanes:
            self.available.clear()
            self.last_online = time.monotonic()

    async def send(self, message):
        while not self.closed:
            await asyncio.wait_for(self.available.wait(), SESSION_GRACE)
            if self.closed:
                break
            if not self.lanes:
                continue
            is_data = message[0] == DATA
            lane = self.lanes[self.positions[is_data] % len(self.lanes)]
            self.positions[is_data] += 1
            try:
                await lane.websocket.send(message)
                if is_data:
                    lane.sent += len(message) - HEADER.size
                return
            except ConnectionClosed:
                self.remove(lane)
        raise ConnectionError("Tunnel closed")


class Stream:
    def __init__(self, session, stream_id):
        self.session = session
        self.id = stream_id
        self.receive_next = 0
        self.send_next = 0
        self.acked = 0
        self.pending = {}
        self.incoming = {}
        self.received = asyncio.Event()
        self.credit = asyncio.Event()
        self.credit.set()
        self.open_result = asyncio.Event()
        self.ready = False
        self.remote_finished = False
        self.writer = None
        self.task = None

    async def send(self, kind, sequence=0, payload=b""):
        await self.session.pool.send(frame(kind, self.id, sequence, payload))

    async def upload(self, reader):
        while True:
            await self.credit.wait()
            payload = await reader.read(CHUNK)
            sequence = self.send_next
            self.send_next += 1
            kind = DATA if payload else FIN
            message = frame(kind, self.id, sequence, payload)
            self.pending[sequence] = (message, time.monotonic())
            if len(self.pending) >= WINDOW:
                self.credit.clear()
            await self.session.pool.send(message)
            if kind == FIN:
                return

    async def download(self, writer):
        while not self.remote_finished:
            await self.received.wait()
            while self.receive_next in self.incoming:
                kind, payload = self.incoming.pop(self.receive_next)
                if kind == FIN:
                    writer.write_eof()
                    await writer.drain()
                    self.remote_finished = True
                else:
                    writer.write(payload)
                    await writer.drain()
                self.receive_next += 1
                if self.remote_finished:
                    break
            self.received.clear()
            await self.send(ACK, self.receive_next)

    async def relay(self, reader, writer):
        self.writer = writer
        async with asyncio.TaskGroup() as group:
            group.create_task(self.upload(reader))
            group.create_task(self.download(writer))
        async with asyncio.timeout(SESSION_GRACE):
            while self.pending:
                await asyncio.sleep(0.05)

    def accept(self, kind, sequence, data):
        if kind == ACK:
            if self.acked < sequence <= self.send_next:
                for index in range(self.acked, sequence):
                    self.pending.pop(index, None)
                self.acked = sequence
                self.credit.set()
        elif kind in (DATA, FIN):
            if not self.remote_finished and self.receive_next <= sequence < self.receive_next + WINDOW:
                self.incoming.setdefault(sequence, (kind, data))
                self.received.set()
            elif sequence < self.receive_next:
                self.session.repeat_ack(self)
        elif kind in (OK, FAIL):
            self.ready = kind == OK
            self.open_result.set()
        elif kind == RESET and self.task:
            self.task.cancel()


class Session:
    def __init__(self, gateway=False, allow_private=False):
        self.pool = Pool()
        self.streams = {}
        self.retired = {}
        self.gateway = gateway
        self.allow_private = allow_private
        self.background = set()

    def start(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return task

    def repeat_ack(self, stream):
        async def reply():
            with contextlib.suppress(ConnectionError, TimeoutError):
                await stream.send(ACK, stream.receive_next)
        self.start(reply())

    def retire(self, stream):
        self.streams.pop(stream.id, None)
        self.retired[stream.id] = (time.monotonic(), stream.receive_next)
        if stream.writer:
            stream.writer.close()

    async def receive(self, websocket):
        async for message in websocket:
            if not isinstance(message, bytes) or len(message) < HEADER.size:
                await websocket.close(code=1002)
                return
            kind, stream_id, sequence = HEADER.unpack_from(message)
            payload = message[HEADER.size:]
            if kind == OPEN and self.gateway and len(payload) <= 512:
                stream = self.streams.get(stream_id)
                if stream is not None:
                    if stream.ready:
                        await stream.send(OK)
                elif stream_id in self.retired or len(self.streams) >= MAX_STREAMS:
                    await self.pool.send(frame(FAIL, stream_id))
                else:
                    stream = Stream(self, stream_id)
                    self.streams[stream_id] = stream
                    stream.task = self.start(self.dial(stream, payload))
            elif stream := self.streams.get(stream_id):
                stream.accept(kind, sequence, payload)
            elif kind in (DATA, FIN) and stream_id in self.retired:
                _, received = self.retired[stream_id]
                await self.pool.send(frame(ACK, stream_id, received))

    async def dial(self, stream, payload):
        try:
            host, port = json.loads(payload)
            if not isinstance(host, str) or type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("Invalid target")
            async with asyncio.timeout(10):
                reader, writer = await open_target(host, port, self.allow_private)
            stream.writer = writer
            stream.ready = True
            await stream.send(OK)
            await stream.relay(reader, writer)
        except (ValueError, TypeError, OSError, TimeoutError, ExceptionGroup):
            with contextlib.suppress(ConnectionError, TimeoutError):
                await stream.send(RESET if stream.ready else FAIL)
        finally:
            self.retire(stream)

    async def maintain(self):
        while True:
            await asyncio.sleep(RETRY / 2)
            now = time.monotonic()
            self.retired = {
                key: value for key, value in self.retired.items() if now - value[0] < 2 * SESSION_GRACE
            }
            if not self.pool.lanes:
                if now - self.pool.last_online > SESSION_GRACE:
                    for stream in list(self.streams.values()):
                        if stream.task:
                            stream.task.cancel()
                continue
            # Alternate streams while retransmitting so one flow can't take the entire pool.
            for stream in list(self.streams.values()):
                expired = [
                    (index, message) for index, (message, sent) in stream.pending.items()
                    if now - sent >= RETRY
                ]
                for index, message in expired[:4]:
                    if index in stream.pending:
                        stream.pending[index] = (message, now)
                        with contextlib.suppress(ConnectionError, TimeoutError):
                            await self.pool.send(message)

    def close(self):
        self.pool.closed = True
        self.pool.available.set()
        for task in list(self.background):
            task.cancel()


async def open_target(host, port, allow_private):
    addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for _, _, _, _, endpoint in addresses:
        address = ipaddress.ip_address(endpoint[0].split("%")[0])
        if not allow_private and not address.is_global:
            continue
        try:
            return await asyncio.open_connection(str(address), port)
        except OSError:
            continue
    raise OSError("No reachable permitted destination")


async def socks_client(reader, writer, session):
    stream = None
    try:
        async with asyncio.timeout(15):
            version, count = await reader.readexactly(2)
            if version != 5:
                return
            methods = await reader.readexactly(count)
            writer.write(b"\x05\x00" if 0 in methods else b"\x05\xff")
            await writer.drain()
            if 0 not in methods:
                return
            version, command, reserved, address_type = await reader.readexactly(4)
            if version != 5 or reserved != 0 or command != 1:
                await socks_reply(writer, 7)
                return
            if address_type in (1, 4):
                host = str(ipaddress.ip_address(await reader.readexactly(4 if address_type == 1 else 16)))
            elif address_type == 3:
                size = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(size)).decode("ascii")
            else:
                await socks_reply(writer, 8)
                return
            port = int.from_bytes(await reader.readexactly(2), "big")
            if len(session.streams) >= MAX_STREAMS or not session.pool.lanes:
                await socks_reply(writer, 1)
                return
            stream = Stream(session, uuid.uuid4().bytes)
            stream.writer = writer
            stream.task = asyncio.current_task()
            session.streams[stream.id] = stream
            request = json.dumps([host, port]).encode()
            while not stream.open_result.is_set():
                await stream.send(OPEN, payload=request)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stream.open_result.wait(), RETRY)
            await socks_reply(writer, 0 if stream.ready else 5)
        if stream.ready:
            await stream.relay(reader, writer)
    except (OSError, TimeoutError, ValueError, asyncio.IncompleteReadError, ExceptionGroup):
        if stream is not None and session.pool.lanes:
            with contextlib.suppress(ConnectionError, TimeoutError):
                await stream.send(RESET)
    finally:
        if stream is not None:
            session.retire(stream)
        writer.close()


async def socks_reply(writer, code):
    writer.write(bytes((5, code, 0, 1, 0, 0, 0, 0, 0, 0)))
    await writer.drain()


def token():
    secret = os.environ.get("BOND_TOKEN", "")
    if not secret and (directory := os.environ.get("CREDENTIALS_DIRECTORY")):
        secret = (Path(directory) / "bond-token").read_text(encoding="ascii").strip()
    if len(secret) < 32 or not secret.isascii() or any(not c.isalnum() and c not in "-_" for c in secret):
        raise SystemExit("Set BOND_TOKEN to a random URL-safe token of at least 32 characters.")
    return secret


def load_endpoints(filename):
    if not filename:
        return []
    values = []
    for entry in Path(filename).read_text(encoding="utf-8").splitlines():
        entry = entry.split("#", 1)[0].strip()
        if entry:
            values.append(str(ipaddress.ip_address(entry)))
    if len(values) > 10000:
        raise ValueError("Endpoint list cannot exceed 10,000 addresses")
    return list(dict.fromkeys(values))


async def connect_lane(args, authority, address, instance, session, active, selection, tls_context):
    port = authority.port or 443
    async with connect(
        args.url,
        additional_headers={"Authorization": "Bearer " + args.secret, "X-Bond-Session": instance},
        host=address,
        port=port,
        server_hostname=authority.hostname,
        ssl=tls_context,
        proxy=None,
        open_timeout=6,
        ping_interval=10,
        ping_timeout=6,
        close_timeout=1,
        compression=None,
        max_size=HEADER.size + CHUNK,
    ) as websocket:
        if await asyncio.wait_for(websocket.recv(), 5) != "ready":
            return
        pong = await websocket.ping()
        latency = await asyncio.wait_for(pong, 5)
        async with selection:
            if len(active) >= args.max_paths:
                worst_address, worst = max(active.items(), key=lambda item: item[1].latency)
                if latency >= worst.latency * 0.8:
                    return
                session.pool.remove(worst)
                active.pop(worst_address, None)
                await worst.websocket.close()
            await websocket.send("join")
            if await asyncio.wait_for(websocket.recv(), 5) != "joined":
                return
            lane = Lane(websocket, latency)
            active[address] = lane
            session.pool.add(lane)
        print(f"Path online {address} RTT={latency*1000:.0f}ms active={len(active)}", flush=True)
        try:
            await session.receive(websocket)
        finally:
            if active.get(address) is lane:
                active.pop(address)
                session.pool.remove(lane)
            print(f"Path offline {address} active={len(active)}", flush=True)


async def discovery(args, authority, session):
    instance = uuid.uuid4().hex
    active = {}
    probes = {}
    selection = asyncio.Lock()
    tls_context = ssl.create_default_context(cafile=args.ca_file)
    while True:
        try:
            addresses = load_endpoints(args.endpoints)
            if not addresses:
                resolved = await asyncio.get_running_loop().getaddrinfo(
                    authority.hostname, authority.port or 443, type=socket.SOCK_STREAM
                )
                addresses = list(dict.fromkeys(item[4][0] for item in resolved))
        except (OSError, ValueError) as error:
            print(f"Endpoint list unavailable: {error}", flush=True)
            await asyncio.sleep(5)
            continue
        selected_addresses = set(addresses)
        for address, task in list(probes.items()):
            if address not in selected_addresses:
                if lane := active.get(address):
                    session.pool.remove(lane)
                task.cancel()
                del probes[address]
        for address in addresses:
            for finished in [key for key, task in probes.items() if task.done()]:
                with contextlib.suppress(OSError, ValueError, TimeoutError, ConnectionClosed, InvalidHandshake):
                    probes.pop(finished).result()
            if address not in probes and len(probes) < args.max_paths + 64:
                probes[address] = session.start(
                    connect_lane(args, authority, address, instance, session, active, selection, tls_context)
                )
            await asyncio.sleep(1 / args.probe_rate)
        await asyncio.sleep(5)


async def gateway(args):
    sessions = {}
    expected = "Bearer " + args.secret

    async def handler(websocket):
        headers = websocket.request.headers
        try:
            provided = headers.get("Authorization", "")
            instance = uuid.UUID(hex=headers.get("X-Bond-Session", "")).hex
        except (ValueError, KeyError):
            await websocket.close(code=1008)
            return
        if websocket.request.path != args.path or not provided.isascii() or not hmac.compare_digest(provided, expected):
            await websocket.close(code=1008)
            return
        try:
            await websocket.send("ready")
            if await asyncio.wait_for(websocket.recv(), 10) != "join":
                return
        except (TimeoutError, ConnectionClosed):
            return
        if instance not in sessions:
            if len(sessions) >= 64:
                await websocket.close(code=1013)
                return
            sessions[instance] = Session(gateway=True, allow_private=args.allow_private_destinations)
            sessions[instance].start(sessions[instance].maintain())
        session = sessions[instance]
        if len(session.pool.lanes) >= args.max_paths:
            await websocket.close(code=1013)
            return
        lane = Lane(websocket, 0)
        session.pool.add(lane)
        try:
            await websocket.send("joined")
            await session.receive(websocket)
        except ConnectionClosed:
            pass
        finally:
            session.pool.remove(lane)

    tls = None
    if args.cert and args.key:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(args.cert, args.key)
    elif args.cert or args.key or args.bind != "127.0.0.1":
        raise SystemExit("Provide both TLS files or bind to 127.0.0.1 behind a TLS reverse proxy.")

    async with serve(
        handler,
        args.bind,
        args.port,
        ssl=tls,
        compression=None,
        max_size=HEADER.size + CHUNK,
        ping_interval=10,
        ping_timeout=6,
    ):
        print(f"Gateway listening on {args.bind}:{args.port}", flush=True)
        while True:
            await asyncio.sleep(5)
            for identifier, session in list(sessions.items()):
                if not session.pool.lanes and time.monotonic() - session.pool.last_online > SESSION_GRACE:
                    session.close()
                    del sessions[identifier]


async def client(args):
    authority = urlsplit(args.url)
    if authority.scheme != "wss" or not authority.hostname or authority.username or authority.password:
        raise SystemExit("A wss:// URL with a certificate matching the hostname is required.")
    session = Session()
    session.start(discovery(args, authority, session))
    session.start(session.maintain())
    try:
        async with await asyncio.start_server(
            lambda reader, writer: socks_client(reader, writer, session), "127.0.0.1", args.socks_port
        ) as listener:
            print(f"SOCKS5 listening on 127.0.0.1:{args.socks_port}", flush=True)
            await listener.serve_forever()
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    remote = modes.add_parser("gateway")
    remote.add_argument("--bind", default="127.0.0.1")
    remote.add_argument("--port", type=int, default=8443)
    remote.add_argument("--path", default="/bond")
    remote.add_argument("--cert")
    remote.add_argument("--key")
    remote.add_argument("--allow-private-destinations", action="store_true")
    local = modes.add_parser("client")
    local.add_argument("--url", required=True)
    local.add_argument("--socks-port", type=int, default=1080)
    local.add_argument("--endpoints")
    local.add_argument("--ca-file")
    local.add_argument("--probe-rate", type=int, default=10, choices=range(1, 51), metavar="1..50")
    for mode in (remote, local):
        mode.add_argument("--max-paths", type=int, default=8, choices=range(1, 501), metavar="1..500")
    args = parser.parse_args()
    args.secret = token()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(gateway(args) if args.mode == "gateway" else client(args))


if __name__ == "__main__":
    main()
