"""Local-only stand-in for the Aether executable."""
import asyncio
import os
import sys


async def pump(reader, writer):
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()


async def forward(reader, writer):
    upstream_writer = None
    try:
        assert await reader.readexactly(3) == b"\x05\x01\x00"
        writer.write(b"\x05\x00")
        await writer.drain()
        assert await reader.readexactly(4) == b"\x05\x01\x00\x03"
        size = (await reader.readexactly(1))[0]
        assert await reader.readexactly(size) == b"localhost"
        port = int.from_bytes(await reader.readexactly(2), "big")
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()
        await asyncio.gather(pump(reader, upstream_writer), pump(upstream_reader, writer))
    finally:
        writer.close()
        if upstream_writer:
            upstream_writer.close()


async def main():
    flags = sys.argv[1:]
    assert ("--masque" in flags) != ("--wg" in flags)
    expected = ":443" if "--masque" in flags else ":2408"
    assert flags[flags.index("--peer") + 1] == "162.159.199.230" + expected
    host, port = os.environ["AETHER_SOCKS"].rsplit(":", 1)
    assert host == "127.0.0.1"
    async with await asyncio.start_server(forward, host, int(port)) as server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
