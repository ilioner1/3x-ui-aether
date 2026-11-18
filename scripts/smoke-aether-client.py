"""Exercise the installed panel, exported VLESS link, and live Aether route."""

import json
import os
import pathlib
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


AETHER_URI = os.environ.get("XUI_AETHER_TEST_URI") or (
    "aether://162.159.198.223:443"
    "?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2"
)
TEST_MULTIPLE = os.environ.get("XUI_AETHER_MULTIPLE") == "1"
REQUESTED_REGION = urllib.parse.parse_qs(urllib.parse.urlsplit(AETHER_URI).query).get("region", [""])[0]
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
XRAY_BIN = pathlib.Path("/usr/local/x-ui/bin")
BASE = (
    f"http://127.0.0.1:{os.environ['XUI_PANEL_PORT']}/"
    f"{os.environ['XUI_WEB_BASE_PATH'].strip('/')}/panel/api"
).replace("//panel/api", "/panel/api")
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, method="POST", body=None, *, form=False):
    headers = {"Authorization": "Bearer " + os.environ["XUI_API_TOKEN"]}
    data = None
    if body is not None and form:
        data = urllib.parse.urlencode(body).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data, headers, method=method)
    try:
        with HTTP.open(request, timeout=320 if REQUESTED_REGION else 40) as response:
            message = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {path}: HTTP {error.code}") from None
    if not message["success"]:
        raise RuntimeError(f"{method} {path}: {message.get('msg')}")
    return message.get("obj")


def wait_for_panel():
    last_error = None
    for _ in range(30):
        try:
            api("/server/status", "GET")
            return
        except (urllib.error.URLError, RuntimeError) as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError("The installed panel API did not become ready") from last_error


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def exported_links(value):
    if isinstance(value, str) and value.startswith("vless://"):
        yield urllib.parse.urlsplit(value)
    elif isinstance(value, list):
        for item in value:
            yield from exported_links(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from exported_links(item)


def start_client(link, directory):
    proxy_port = free_port()
    options = urllib.parse.parse_qs(link.query)
    network = options.get("type", ["tcp"])[0]
    security = options.get("security", ["none"])[0]
    if network not in {"raw", "tcp"} or security != "none":
        raise RuntimeError("Unexpected transport in the exported VLESS link")
    config = {
        "inbounds": [
            {"listen": "127.0.0.1", "port": proxy_port, "protocol": "socks"}
        ],
        "outbounds": [{
            "protocol": "vless",
            "settings": {"vnext": [{
                "address": link.hostname,
                "port": link.port,
                "users": [{"id": link.username, "encryption": "none"}],
            }]},
            "streamSettings": {"network": network, "security": security},
        }],
    }
    config_path = directory / "client.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return proxy_port, subprocess.Popen([
        str(XRAY_BIN / "xray-linux-amd64"), "run", "-config", str(config_path)
    ])


def verify_route(tag, inbound_tag):
    config = json.loads((XRAY_BIN / "config.json").read_text(encoding="utf-8"))
    outbound = next(entry for entry in config["outbounds"] if entry["tag"] == tag)
    if outbound["protocol"] != "socks":
        raise RuntimeError("The installed Xray config did not activate the Aether bridge")
    if not any(
        rule.get("outboundTag") == tag and inbound_tag in rule.get("inboundTag", [])
        for rule in config["routing"]["rules"]
    ):
        raise RuntimeError("The installed Xray config did not route the VLESS inbound")


def main():
    wait_for_panel()
    inbound_port = free_port()
    client_id = str(uuid.uuid4())
    tag = urllib.parse.urlsplit(AETHER_URI).fragment
    inbound = api("/inbounds/add", body={
        "remark": "Aether client smoke test",
        "enable": True,
        "listen": "127.0.0.1",
        "port": inbound_port,
        "protocol": "vless",
        "settings": json.dumps({
            "decryption": "none",
            "clients": [{"id": client_id, "email": f"aether-smoke-{client_id}", "enable": True}],
        }),
        "streamSettings": json.dumps({"network": "tcp", "security": "none"}),
        "sniffing": "{}",
    })
    inbound_tag = inbound["tag"]
    print(f"Panel created VLESS inbound {inbound_tag}", flush=True)

    links = api("/inbounds/allLinks", "GET")
    link = next(
        (link for link in exported_links(links) if link.username == client_id), None
    )
    if link is None:
        raise RuntimeError("The panel did not export a VLESS link for the new client")
    if link.hostname not in {"localhost", "127.0.0.1"} or link.port != inbound_port:
        raise RuntimeError("The exported VLESS link points to an unexpected endpoint")
    print("The panel exported a VLESS link for the new client", flush=True)

    response = api("/xray/")
    if isinstance(response, str):
        response = json.loads(response)
    config = response["xraySetting"]
    if isinstance(config, str):
        config = json.loads(config)
    if TEST_MULTIPLE:
        # Four deliberately unresponsive Psiphon exits before the working
        # fifth outbound and another after it. A pending exit must not stall
        # Save or make Xray dispatch through its direct default.
        unavailable_uri = (
            "aether://192.0.2.44:443?protocol=masque&transport=h2"
            "&psiphon=chain&psiphon_mode=auto"
        )
        for index in range(1, 7):
            if index != 5:
                filler_tag = f"aether-pending-{index}"
                config["outbounds"].append({
                    "protocol": "aether", "tag": filler_tag,
                    "settings": {"uri": f"{unavailable_uri}#{filler_tag}"},
                })
    expected_outbound = {"protocol": "aether", "tag": tag, "settings": {"uri": AETHER_URI}}
    if os.environ.get("XUI_AETHER_REQUIRE_IMPORTED") == "1":
        if expected_outbound not in config["outbounds"]:
            raise RuntimeError("The browser-imported Aether outbound was not saved")
    else:
        if TEST_MULTIPLE:
            config["outbounds"].insert(len(config["outbounds"]) - 1, expected_outbound)
        else:
            config["outbounds"].append(expected_outbound)
    rule = {"type": "field", "inboundTag": [inbound_tag], "outboundTag": tag}
    config.setdefault("routing", {}).setdefault("rules", []).insert(0, rule)

    def save_config():
        started = time.monotonic()
        api("/xray/update", body={
            "xraySetting": json.dumps(config), "outboundTestUrl": TRACE_URL,
        }, form=True)
        elapsed = time.monotonic() - started
        print(f"Xray configuration saved and applied in {elapsed:.2f} s", flush=True)
        if TEST_MULTIPLE and elapsed >= 12:
            raise RuntimeError("Saving waited for remote tunnel readiness")

    save_config()
    if not TEST_MULTIPLE:
        api("/server/restartXrayService")
    verify_route(tag, inbound_tag)
    print("The running Xray configuration routes the inbound to Aether", flush=True)

    with tempfile.TemporaryDirectory() as scratch:
        port, client = start_client(link, pathlib.Path(scratch))
        try:
            def request_trace(timeout):
                return subprocess.run([
                    "curl", "--silent", "--show-error", "--fail", "--max-time", str(timeout),
                    "--noproxy", "", "--proxy", f"socks5h://127.0.0.1:{port}",
                    "--write-out", "\n%{http_code} %{time_total}", TRACE_URL,
                ], capture_output=True, text=True, check=False)

            for _ in range(10):
                if client.poll() is not None:
                    raise RuntimeError("The VLESS client process exited")
                result = request_trace(12)
                if result.returncode == 0:
                    body, metrics = result.stdout.rsplit("\n", 1)
                    status, seconds = metrics.split()
                    trace = dict(line.split("=", 1) for line in body.splitlines() if "=" in line)
                    warp = trace.get("warp")
                    location = trace.get("loc")
                    verified = location == REQUESTED_REGION if REQUESTED_REGION else warp in {"on", "plus"}
                    if status == "200" and verified:
                        print(f"VLESS via Aether: HTTP {status}, {float(seconds) * 1000:.0f} ms, WARP {warp}, region {location}")
                        if TEST_MULTIPLE:
                            rule["outboundTag"] = "aether-pending-6"
                            save_config()
                            verify_route("aether-pending-6", inbound_tag)
                            if request_trace(5).returncode == 0:
                                raise RuntimeError("Unavailable sixth Aether outbound returned traffic")
                            print("Sixth outbound failed closed instead of using the VPS exit")
                        return
                    print(f"Unexpected tunnel response: HTTP {status}, WARP {warp}, region {location}", flush=True)
                else:
                    print(result.stderr.strip(), flush=True)
                time.sleep(2)
            raise RuntimeError("No successful response with the expected egress through the exported VLESS link")
        finally:
            client.terminate()
            client.wait(timeout=10)


if __name__ == "__main__":
    main()
