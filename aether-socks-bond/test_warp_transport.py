import argparse
import asyncio
import contextlib
import os
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import bond
from aether_transport import open_socks_socket


class WarpTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_socks_connect_encodes_the_gateway_not_the_peer(self):
        received = asyncio.Future()

        async def fake_aether(reader, writer):
            assert await reader.readexactly(3) == b"\x05\x01\x00"
            writer.write(b"\x05\x00")
            await writer.drain()
            assert await reader.readexactly(4) == b"\x05\x01\x00\x03"
            size = (await reader.readexactly(1))[0]
            received.set_result(await reader.readexactly(size + 2))
            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            writer.close()

        async with await asyncio.start_server(fake_aether, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with await open_socks_socket(port, "gateway.example", 443):
                self.assertEqual(await received, b"gateway.example\x01\xbb")

    async def test_core_failure_cannot_open_a_direct_websocket(self):
        with tempfile.TemporaryDirectory() as state:
            args = argparse.Namespace(
                url="wss://127.0.0.1/bond", secret="test-only-key" * 3,
                aether_bin=sys.executable, aether_state=state, aether_mode="masque",
                aether_port=443, aether_transport="h2", max_paths=2,
            )
            session = bond.Session()
            # Python isn't an Aether core and exits on --masque.
            # The connection must surface that failure instead of calling connect.
            from unittest.mock import patch
            with patch.object(bond, "connect") as connect:
                with self.assertRaisesRegex(OSError, "Aether stopped"):
                    await bond.connect_lane(
                        args, urlsplit(args.url), "162.159.199.230", "fixture",
                        session, {}, asyncio.Lock(), ssl.create_default_context(),
                    )
                connect.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Executable fixture uses a Linux shebang")
    async def test_both_aether_modes_delegate_tls_connection_to_socks(self):
        from test_bond_integration import certificates
        from websockets.asyncio.server import serve

        with tempfile.TemporaryDirectory() as state:
            root = Path(state)
            cert, key = certificates(root)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(cert, key)
            observed = asyncio.Event()

            async def gateway(ws):
                await ws.send("ready")
                self.assertEqual(await ws.recv(), "join")
                await ws.send("joined")
                observed.set()
                await ws.wait_closed()

            fake = root / "aether"
            fake.write_text(
                "#!" + sys.executable + "\n"
                + Path(__file__).with_name("test_warp_core_fixture.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            fake.chmod(0o700)
            async with serve(gateway, "127.0.0.1", 0, ssl=tls) as server:
                url = f"wss://localhost:{server.sockets[0].getsockname()[1]}/bond"
                for mode, port in (("masque", 443), ("wireguard", 2408)):
                    with self.subTest(mode=mode):
                        observed.clear()
                        session = bond.Session()
                        args = argparse.Namespace(
                            url=url, secret="test-only-key" * 3, aether_bin=str(fake),
                            aether_state=state, aether_mode=mode, aether_port=port,
                            aether_transport="h2", max_paths=2,
                        )
                        task = asyncio.create_task(bond.connect_lane(
                            args, urlsplit(url), "162.159.199.230", "fixture",
                            session, {}, asyncio.Lock(), ssl.create_default_context(cafile=cert),
                        ))
                        try:
                            await asyncio.wait_for(observed.wait(), 12)
                            async with asyncio.timeout(3):
                                while not session.pool.lanes:
                                    await asyncio.sleep(0.02)
                        finally:
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
                            session.close()


if __name__ == "__main__":
    unittest.main()
