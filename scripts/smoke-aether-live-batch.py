"""Verify every route in 24 live Aether/Psiphon chains on a disposable runner."""
import concurrent.futures
import json
import pathlib
import runpy
import socket
import subprocess
import tempfile
import time
import uuid

helpers = runpy.run_path(str(pathlib.Path(__file__).with_name("smoke-aether-client.py")))
api = helpers["api"]
helpers["wait_for_panel"]()
endpoint = "aether://162.159.199.111:1701?protocol=masque&transport=h2&psiphon=chain&psiphon_mode=auto&region=IN"
belgium = "aether://162.159.199.169:443?protocol=masque&scan=balanced&ip=v4&transport=h2&psiphon=chain&psiphon_mode=direct&region=BE#bel"
trace_url = "https://www.cloudflare.com/cdn-cgi/trace"

# All ports remain reserved until the client config is ready.
reservations = []
for index in range(24):
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reservation.bind(("127.0.0.1", 0))
    reservations.append(reservation)

try:
    clients = []
    for index in range(1, 25):
        client_id = str(uuid.uuid4())
        tag = "bel" if index == 20 else f"aether-live-{index}"
        inbound = api("/inbounds/add", body={
            "remark": f"Aether live {index}", "enable": True, "listen": "127.0.0.1",
            "port": helpers["free_port"](), "protocol": "vless",
            "settings": json.dumps({"decryption": "none", "clients": [
                {"id": client_id, "email": f"aether-live-{client_id}", "enable": True},
            ]}),
            "streamSettings": json.dumps({"network": "tcp", "security": "none"}),
            "sniffing": "{}",
        })
        clients.append((inbound["tag"], tag, client_id))

    links = {link.username: link for link in helpers["exported_links"](api("/inbounds/allLinks", "GET"))}
    response = api("/xray/")
    config = (json.loads(response) if isinstance(response, str) else response)["xraySetting"]
    if isinstance(config, str):
        config = json.loads(config)
    rules = []
    client_config = {"inbounds": [], "outbounds": [], "routing": {"rules": []}}
    proxy_ports = []
    for (inbound_tag, tag, client_id), reservation in zip(clients, reservations):
        config["outbounds"].append({
            "protocol": "aether", "tag": tag, "settings": {"uri": belgium if tag == "bel" else f"{endpoint}#{tag}"},
        })
        rules.append({"type": "field", "inboundTag": [inbound_tag], "outboundTag": tag})
        proxy_port = reservation.getsockname()[1]
        proxy_ports.append(proxy_port)
        link = links[client_id]
        client_config["inbounds"].append({
            "protocol": "socks", "tag": tag, "listen": "127.0.0.1", "port": proxy_port,
        })
        client_config["outbounds"].append({
            "protocol": "vless", "tag": tag, "settings": {"vnext": [{
                "address": link.hostname, "port": link.port,
                "users": [{"id": client_id, "encryption": "none"}],
            }]},
        })
        client_config["routing"]["rules"].append({
            "type": "field", "inboundTag": [tag], "outboundTag": tag,
        })

    config.setdefault("routing", {}).setdefault("rules", [])[:0] = rules
    start = time.monotonic()
    api("/xray/update", body={"xraySetting": json.dumps(config), "outboundTestUrl": trace_url}, form=True)
    print(f"Saved 24 simultaneous live Psiphon outbounds in {time.monotonic() - start:.2f}s", flush=True)
finally:
    for reservation in reservations:
        reservation.close()

with tempfile.TemporaryDirectory() as directory:
    client_path = pathlib.Path(directory) / "client.json"
    client_path.write_text(json.dumps(client_config), encoding="utf-8")
    client = subprocess.Popen([str(helpers["XRAY_BIN"] / "xray-linux-amd64"), "run", "-config", str(client_path)])
    try:
        def verify(index_port):
            index, port = index_port
            region = "BE" if index == 20 else "IN"
            detail = ""
            for _ in range(6):
                result = subprocess.run([
                    "curl", "-fsS", "--max-time", "12", "--noproxy", "",
                    "--proxy", f"socks5h://127.0.0.1:{port}", trace_url,
                ], capture_output=True, text=True, check=False)
                if result.returncode == 0 and f"loc={region}" in result.stdout.splitlines():
                    return index, True, f"HTTP 200, loc={region}"
                detail = next((line for line in result.stdout.splitlines() if line.startswith("loc=")), "")
                detail = detail or result.stderr.strip() or "No valid response"
                time.sleep(1)
            return index, False, detail

        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
            results = list(executor.map(verify, enumerate(proxy_ports, 1)))
        for index, success, detail in results:
            print(f"Outbound {index}: {detail}", flush=True)
        unavailable = [index for index, success, _ in results if not success]
        if unavailable:
            raise RuntimeError(f"Unverified Psiphon routes: {unavailable}")
        print("All 24 VLESS outbounds reached their requested regions over live Psiphon")
    finally:
        client.terminate()
        client.wait(timeout=10)
