"""Deterministic Aether stand-in for Xray routing tests, used only on CI."""
import pathlib
import socketserver
import sys

index = int(sys.argv[sys.argv.index("--peer") + 1].split(":")[0].split(".")[-1])
if index in {18, 21} and not pathlib.Path("/run/aether-stress-recover").exists():
    raise SystemExit("Deliberate startup failure")
argument = sys.argv.index("--psiphon-bind") + 1
host, port = sys.argv[argument].split(":")

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        greeting = self.rfile.read(2)
        if len(greeting) != 2:
            return
        self.rfile.read(greeting[1])
        self.wfile.write(b"\x05\x00")
        request = self.rfile.read(4)
        if len(request) != 4:
            return
        address_type = request[3]
        if address_type == 3:
            size = self.rfile.read(1)[0]
        else:
            size = {1: 4, 4: 16}[address_type]
        self.rfile.read(size + 2)
        self.wfile.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        if not self.rfile.readline():
            return
        body = f"outegress-{index}".encode()
        self.wfile.write(
            f"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
        )

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

with Server((host, int(port)), Handler) as server:
    server.serve_forever()
