"""Create one local Aether SOCKS client per selected MASQUE peer."""

import asyncio
import contextlib
import ipaddress
import os
import socket
import struct
from pathlib import Path


async def read_exact(loop, sock, size):
    data = bytearray()
    while len(data) < size:
        part = await loop.sock_recv(sock, size - len(data))
        if not part:
            raise OSError("Aether closed the SOCKS connection")
        data.extend(part)
    return bytes(data)


async def open_socks_socket(local_port, host, port):
    """Return the connected raw socket for the WebSocket TLS handshake."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        await loop.sock_connect(sock, ("127.0.0.1", local_port))
        await loop.sock_sendall(sock, b"\x05\x01\x00")
        if await read_exact(loop, sock, 2) != b"\x05\x00":
            raise OSError("Aether SOCKS negotiation failed")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            domain = host.encode("idna")
            if not 1 <= len(domain) <= 255:
                raise ValueError("Invalid gateway hostname")
            destination = b"\x03" + bytes([len(domain)]) + domain
        else:
            destination = (b"\x01" if ip.version == 4 else b"\x04") + ip.packed
        await loop.sock_sendall(sock, b"\x05\x01\x00" + destination + struct.pack("!H", port))
        version, status, _, bound_type = await read_exact(loop, sock, 4)
        if version != 5 or status:
            raise OSError(f"Aether could not reach the private gateway (SOCKS status {status})")
        length = {1: 4, 4: 16}.get(bound_type)
        if bound_type == 3:
            length = (await read_exact(loop, sock, 1))[0]
        if length is None:
            raise OSError("Invalid Aether SOCKS response")
        await read_exact(loop, sock, length + 2)
        return sock
    except BaseException:
        sock.close()
        raise


@contextlib.asynccontextmanager
async def warp_socket(args, peer, host, port):
    ip = ipaddress.ip_address(peer)
    if not ip.is_global or ip.is_multicast:
        raise ValueError("A WARP peer must be a public address")
    peer_address = f"[{ip}]:{args.aether_port}" if ip.version == 6 else f"{ip}:{args.aether_port}"
    state = Path(args.aether_state).resolve()
    peer_state = state / args.aether_mode / ip.packed.hex()
    peer_state.mkdir(parents=True, mode=0o700, exist_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        local_port = listener.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("AETHER_")}
    env.update(AETHER_SOCKS=f"127.0.0.1:{local_port}", HOME=str(state))
    transport = (
        ["--wg"] if args.aether_mode == "wireguard"
        else ["--masque", "--" + args.aether_transport, "--noize", "firewall"]
    )
    with (peer_state / "core.log").open("wb") as log:
        proc = await asyncio.create_subprocess_exec(
            args.aether_bin, *transport, "--peer", peer_address, "--ip",
            "v4" if ip.version == 4 else "v6",
            "--no-quick-reconnect",
            "--config", str(peer_state / "identity.toml"),
            cwd=peer_state, env=env, stdout=log, stderr=log,
        )
    upstream = None
    try:
        async with asyncio.timeout(45):
            while proc.returncode is None:
                try:
                    upstream = await open_socks_socket(local_port, host, port)
                except ConnectionRefusedError:
                    await asyncio.sleep(0.2)
                else:
                    break
        if upstream is None:
            raise OSError(f"Aether stopped before becoming ready; see {peer_state / 'core.log'}")
        yield upstream
    finally:
        if upstream is not None:
            upstream.close()
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()


@contextlib.asynccontextmanager
async def lane_dial_options(args, peer, host, port):
    if getattr(args, "aether_bin", None):
        async with warp_socket(args, peer, host, port) as sock:
            yield {"sock": sock}
    else:
        yield {"host": peer, "port": port}
