"""Exercise fail-closed routing and recovery across 24 Xray bridge tags."""
import http.server
import json
import pathlib
import runpy
import subprocess
import tempfile
import threading
import time
import uuid

helpers = runpy.run_path(str(pathlib.Path(__file__).with_name("smoke-aether-client.py")))
api = helpers["api"]
helpers["wait_for_panel"]()
client_id = str(uuid.uuid4())
port = helpers["free_port"]()
inbound = api("/inbounds/add", body={
    "remark": "Aether stress", "enable": True, "listen": "127.0.0.1", "port": port,
    "protocol": "vless",
    "settings": json.dumps({"decryption": "none", "clients": [
        {"id": client_id, "email": f"aether-stress-{client_id}", "enable": True}
    ]}),
    "streamSettings": json.dumps({"network": "tcp", "security": "none"}),
    "sniffing": "{}",
})
link = next(
    link for link in helpers["exported_links"](api("/inbounds/allLinks", "GET"))
    if link.username == client_id
)
response = api("/xray/")
config = (json.loads(response) if isinstance(response, str) else response)["xraySetting"]
if isinstance(config, str):
    config = json.loads(config)

for index in range(1, 25):
    tag = f"aether-stress-{index}"
    config["outbounds"].append({"protocol": "aether", "tag": tag, "settings": {
        "uri": f"aether://198.51.100.{index}:443?transport=h2&psiphon=chain#{tag}",
    }})

rule = {"type": "field", "inboundTag": [inbound["tag"]], "outboundTag": "aether-stress-1"}
config.setdefault("routing", {}).setdefault("rules", []).insert(0, rule)

def save():
    start = time.monotonic()
    api("/xray/update", body={
        "xraySetting": json.dumps(config), "outboundTestUrl": "https://example.com/",
    }, form=True)
    elapsed = time.monotonic() - start
    if elapsed > 12:
        raise RuntimeError(f"Save stalled for {elapsed:.2f} seconds")

class DirectEgress(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"direct-leak")

with http.server.ThreadingHTTPServer(("127.0.0.1", 0), DirectEgress) as direct:
    threading.Thread(target=direct.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as directory:
        save()
        proxy_port, client = helpers["start_client"](link, pathlib.Path(directory))
        try:
            def fetch():
                return subprocess.run([
                    "curl", "-fsS", "--max-time", "2", "--noproxy", "",
                    "--proxy", f"socks5h://127.0.0.1:{proxy_port}",
                    f"http://127.0.0.1:{direct.server_port}/",
                ], capture_output=True, text=True, check=False)

            def check(index, blocked=False):
                tag = f"aether-stress-{index}"
                rule["outboundTag"] = tag
                save()
                helpers["verify_route"](tag, inbound["tag"], "blackhole" if blocked else "socks")
                for _ in range(10):
                    result = fetch()
                    if result.stdout == "direct-leak":
                        raise RuntimeError(f"{tag} leaked to the direct exit")
                    if blocked and result.returncode != 0:
                        return
                    if result.returncode == 0 and result.stdout == f"outegress-{index}":
                        return
                    time.sleep(0.15)
                raise RuntimeError(f"{tag} did not reach its assigned route")

            for index in range(1, 25):
                check(index, blocked=index in {18, 21})
            print("Verified all 24 VLESS routes, including blocked 18 and 21", flush=True)

            pathlib.Path("/run/aether-stress-recover").touch()
            config_path = helpers["XRAY_BIN"] / "config.json"
            for _ in range(60):
                running = json.loads(config_path.read_text(encoding="utf-8"))
                target = next(row for row in running["outbounds"] if row["tag"] == "aether-stress-21")
                if target["protocol"] == "socks":
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("Watchdog did not restore the recovered SOCKS route")
            check(18)
            check(21)
            print("Both failed routes recovered without restarting Xray manually")
        finally:
            client.terminate()
            client.wait(timeout=10)
            direct.shutdown()
