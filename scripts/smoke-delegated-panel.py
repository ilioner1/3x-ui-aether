"""Exercise a delegated client against a real installed Xray."""
import base64
import http.cookiejar
import json
import os
import pathlib
import re
import runpy
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

helpers = runpy.run_path(str(pathlib.Path(__file__).with_name("smoke-aether-client.py")))
api = helpers["api"]
helpers["wait_for_panel"]()
root = helpers["BASE"].removesuffix("/panel/api")
password = "integration-delegate-only"
def add_inbound(remark):
    return api("/inbounds/add", body={
        "remark": remark, "enable": True, "listen": "127.0.0.1",
        "port": helpers["free_port"](), "protocol": "vless",
        "settings": '{"clients":[],"decryption":"none"}',
        "streamSettings": '{"network":"tcp","security":"none"}',
        "sniffing": "{}",
    })

inbound = add_inbound("Delegated smoke VLESS")
second_inbound = add_inbound("Delegated smoke VLESS 2")
ungranted = add_inbound("Unassigned smoke VLESS")
port = inbound["port"]
assigned = [inbound["id"], second_inbound["id"]]

def browser():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))

def get(web, path):
    with web.open(root + path, timeout=30) as response:
        return response.read().decode()

def post(web, path, csrf_page, fields):
    csrf = re.search(r'name="_csrf" value="([^"]+)"|name="csrf-token" content="([^"]+)"', csrf_page)
    token = csrf.group(1) or csrf.group(2)
    values = urllib.parse.urlencode({**fields, "_csrf": token}, doseq=True).encode()
    request = urllib.request.Request(root + path, data=values, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with web.open(request, timeout=40) as response:
        return response.read().decode()

master = browser()
logged_in = post(master, "/login", get(master, "/delegate/"), {
    "username": os.environ["XUI_USERNAME"], "password": os.environ["XUI_PASSWORD"],
})
if not json.loads(logged_in)["success"]:
    raise RuntimeError("Master login failed")
admin_page = get(master, "/panel/delegated-admins")
admin_page = post(master, "/panel/delegated-admins/group", admin_page, {
    "name": "Smoke group", "inbound": assigned,
})
with sqlite3.connect("/etc/x-ui/x-ui.db", timeout=10) as db:
    group = db.execute("SELECT id FROM delegated_groups WHERE name = 'Smoke group'").fetchone()[0]
admin_page = post(master, "/panel/delegated-admins/account", admin_page, {
    "username": "smoke-delegate", "password": password, "group": group, "quota": 1, "enable": 1,
})

delegate = browser()
match = re.search(r'href="([^"]*/delegate/\?account=smoke-delegate)"', admin_page)
if not match:
    raise RuntimeError("New admin has no personal login link")
with delegate.open(urllib.parse.urljoin(root + "/", match.group(1)), timeout=30) as response:
    login_page = response.read().decode()
if 'name="x-ui-role" content="delegate"' not in login_page:
    raise RuntimeError("Personal login link did not serve the delegated x-ui login")
login = post(delegate, "/delegate/login", login_page, {"username": "smoke-delegate", "password": password})
if not json.loads(login)["success"]:
    raise RuntimeError("Delegate login failed")
shell = get(delegate, "/delegate/panel/clients")
if 'name="x-ui-role" content="delegate"' not in shell:
    raise RuntimeError("Delegate clients did not serve the restricted x-ui shell")
token = json.loads(get(delegate, "/delegate/api/csrf-token"))["obj"]

def client_write(path, fields):
    request = urllib.request.Request(root + "/delegate/api/clients/" + path, data=json.dumps(fields).encode(), headers={
        "Content-Type": "application/json", "X-CSRF-Token": token,
    })
    with delegate.open(request, timeout=40) as response:
        return json.load(response)

rejected = client_write("add", {
    "client": {"comment": "ungranted-client", "enable": True},
    "inboundIds": [inbound["id"], ungranted["id"]],
})
if rejected["success"]:
    raise RuntimeError("Mixed granted and ungranted inbounds were accepted")

created = client_write("add", {
    "client": {"comment": "delegated-live-client", "enable": True},
    "inboundIds": assigned,
})
if not created["success"] or not created["obj"].get("subscriptionUrl"):
    raise RuntimeError("Delegate could not create a multi-inbound client with a subscription")
request = urllib.request.Request(created["obj"]["subscriptionUrl"], headers={"User-Agent": "v2rayNG/1.10"})
with browser().open(request, timeout=30) as response:
    subscription = response.read().decode().strip()
if "vless://" not in subscription:
    subscription = base64.b64decode(subscription + "=" * (-len(subscription) % 4)).decode()
ports = {urllib.parse.urlsplit(line).port for line in subscription.splitlines() if line.startswith("vless://")}
if ports != {port, second_inbound["port"]}:
    raise RuntimeError("Subscription did not contain exactly the two granted inbounds")
print("Delegated subscription loaded with both granted inbounds", flush=True)
with sqlite3.connect("/etc/x-ui/x-ui.db", timeout=10) as db:
    owner = db.execute("SELECT id FROM delegated_admins WHERE username = 'smoke-delegate'").fetchone()[0]
    (email,) = db.execute(
        "SELECT c.email FROM delegated_clients d JOIN clients c ON c.id = d.client_id WHERE d.admin_id = ?",
        (owner,),
    ).fetchone()
if not client_write("update/" + email, {"totalGB": 1 << 29})["success"]:
    raise RuntimeError("Delegate client quota write failed")
with sqlite3.connect("/etc/x-ui/x-ui.db", timeout=10) as db:
    client_quota = db.execute("SELECT total_gb FROM clients WHERE email = ?", (email,)).fetchone()[0]
    if client_quota != 1 << 29:
        raise RuntimeError("Delegate could not edit its own client's quota")
exported = next(
    link for link in helpers["exported_links"](api("/inbounds/allLinks", "GET"))
    if link.port == port
)
if "delegated-live-client" not in get(master, f"/panel/delegated-reports?admin={owner}"):
    raise RuntimeError("Client missing from master report")

def wait_for(check, message, timeout=45):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if check():
            return
        time.sleep(1)
    raise RuntimeError(message)

with tempfile.TemporaryDirectory() as temporary:
    proxy_port, proc = helpers["start_client"](exported, pathlib.Path(temporary))
    try:
        def connected():
            return subprocess.run([
                "curl", "-fsS", "--max-time", "5", "--noproxy", "",
                "--proxy", f"socks5h://127.0.0.1:{proxy_port}", "https://www.cloudflare.com/cdn-cgi/trace",
            ], capture_output=True, check=False).returncode == 0

        wait_for(connected, "Delegate-created VLESS connection did not work")
        print("Delegate created a live VLESS client on the granted inbound", flush=True)
        def ledger():
            with sqlite3.connect("/etc/x-ui/x-ui.db", timeout=10) as db:
                return db.execute("SELECT used_bytes, quota_bytes FROM delegated_admins WHERE id = ?", (owner,)).fetchone()

        def sampled():
            if ledger()[0] > 0:
                return True
            connected()
            return False

        # The first Xray stats sample establishes the baseline. Keep sending
        # traffic until a subsequent sample is recorded in the real ledger.
        wait_for(sampled, "Live VLESS did not add usage after the stats baseline", timeout=80)
        print("Xray recorded live VLESS traffic in the account ledger", flush=True)

        with sqlite3.connect("/etc/x-ui/x-ui.db", timeout=10) as db:
            db.execute("UPDATE delegated_admins SET quota_bytes = used_bytes + 1 WHERE id = ?", (owner,))

        def exhausted():
            used, cap = ledger()
            if used >= cap:
                return True
            connected()
            return False

        wait_for(exhausted, "Live traffic did not reach the lowered account cap", timeout=60)
        def removed_from_xray():
            live = json.loads((helpers["XRAY_BIN"] / "config.json").read_text(encoding="utf-8"))
            active = next((row for row in live["inbounds"] if row["tag"] == inbound["tag"]), None)
            return active is not None and all(row.get("email") != email for row in active["settings"].get("clients", []))

        wait_for(removed_from_xray, "Exhausted client remained in the running configuration", timeout=75)
        if connected():
            raise RuntimeError("VLESS still worked with an exhausted delegated account")
        print("Live traffic exhausted the account cap and disconnected VLESS", flush=True)
        admin_page = get(master, f"/panel/delegated-admins?admin={owner}")
        post(master, "/panel/delegated-admins/account", admin_page, {
            "id": owner, "username": "smoke-delegate", "group": group, "quota": 2, "enable": 1,
        })
        wait_for(connected, "VLESS did not recover after a master top-up", timeout=75)
        print("Master top-up restored the existing VLESS client", flush=True)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
