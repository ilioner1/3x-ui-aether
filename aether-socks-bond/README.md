# Multi-Path SOCKS Gateway

Two processes carry a local SOCKS5 TCP connection over multiple authenticated
WebSocket connections. The gateway performs outbound TCP connections. Each
logical stream has a sequence number space, a receive window, cumulative
acknowledgements and retransmission if a path drops.

## Install as systemd services

The installer is for Linux hosts running systemd 247+ with Python 3.11+,
venv, OpenSSL and iproute2 installed. It installs each role under
`/opt/aether-bond`, starts it immediately and enables it at boot.
The services continue running after SSH disconnects or Ctrl+C in your shell.
The installer prompts for a shared token on first setup and retains it on updates.

Download the ZIP from GitHub and extract it on both hosts:

    curl -fL https://github.com/ilioner1/3x-ui-aether/raw/refs/heads/aether-socks-bond/downloads/aether-socks-bond.zip -o aether-socks-bond.zip
    unzip -o aether-socks-bond.zip
    cd aether-socks-bond

On the foreign gateway, use your existing certificate and private key:

    sudo bash install-service.sh gateway gateway-cert.pem gateway-key.pem

Behind an existing reverse proxy, use `sudo bash install-service.sh gateway --behind-proxy`
and forward the HTTPS WebSocket path as described below.

On the Iran host, enter the same token and trust the copied public certificate
if you are using the self-signed certificate from setup:

    sudo bash install-service.sh client-masque wss://YOUR_FOREIGN_IP/bond gateway-cert.pem

For publicly trusted TLS, omit the certificate argument. Pass an optional
endpoint list as the fourth argument, using `-` when no CA file is needed.
The installer copies the certificate and key. After renewing them, rerun the
gateway installer with the renewed files.

Stop any foreground Bond instance using the same port before installing its
service. To inspect or control a service, use the name for that host:

    sudo systemctl status aether-bond-gateway
    sudo journalctl -u aether-bond-gateway -f
    sudo systemctl stop aether-bond-gateway

On the Iran host use `aether-bond-client`. The SOCKS5 outbound remains
`127.0.0.1:1080`.

## Route the Iran connector through Cloudflare WARP

The foreign gateway and its certificate stay the same. Install the client on
the Iran host using the Aether v2.4.0 binary bundled with the native X-UI fork:

    sudo bash install-service.sh client-masque wss://YOUR_FOREIGN_IP/bond gateway-cert.pem

To replace an existing peer list with the packaged MASQUE defaults, add
`peers-masque.txt` as the fourth argument. An update with no fourth argument
keeps the installed list. The packaged defaults include the existing sample
peer and the 254 host addresses in Cloudflare One's documented MASQUE IPv4
range, `162.159.197.0/24`. Availability depends on the Aether client and
the Iran host's network.

This uses Cloudflare WARP over MASQUE HTTP/2 on TCP 443. The client starts a
local Aether instance for each admitted peer. Bond opens its authenticated
WebSocket to your VPS inside Aether's SOCKS connection. If all WARP paths fail,
SOCKS requests fail. They never switch to a direct connection to the VPS.

To use WARP over WireGuard, install the same client service in WireGuard mode
with its own set of WARP WireGuard peers on UDP 2408:

    sudo bash install-service.sh client-wireguard wss://YOUR_FOREIGN_IP/bond gateway-cert.pem

Pass a custom peer file after the certificate argument. Use an IP per line and
only include verified candidates for the selected protocol. The service
keeps its copy in `/opt/aether-bond/client/peers-masque.txt` or
`/opt/aether-bond/client/peers-wireguard.txt` and reloads it on each discovery
pass. The starter lists are examples and haven't been verified from your host.
The list can hold up to 10,000 unique IPs. With traffic available, Bond rotates
data frames across up to 500 online paths in each direction and skips sockets
whose write buffers are backed up when another socket is ready. One stream
can have 512 unacknowledged frames in flight, and the session bounds its
retransmission and reordering buffers. IPs may share a Cloudflare edge or
network link, so throughput depends on the capacity, latency and loss of the
actual paths. Update the gateway and the client together to use the new window.
If the Aether binary is elsewhere, pass its path through `XUI_AETHER_BINARY`
using `sudo env XUI_AETHER_BINARY=/absolute/path/to/aether bash install-service.sh ...`.

Review the tunnel log on the Iran host:

    sudo journalctl -u aether-bond-client -n 40 --no-pager

Look for `transport=WARP/masque` or `transport=WARP/wireguard` in a
`Path online` message. The result of an IP check through SOCKS should still
be your foreign VPS address. To enforce that the VPS cannot be reached directly
from a given source, apply an ingress rule on the foreign VPS separately.
Determine its actual observed WARP source before narrowing any firewall rule.

## Run manually for direct-mode testing

On both hosts, use Python 3.11+.

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

Generate a shared secret once using `openssl rand -hex 32`. Supply the same
secret as `BOND_TOKEN` on both hosts. In Bash, this reads the value without
echoing it or writing it into a command:

    read -rsp 'Bond token: ' BOND_TOKEN
    echo
    export BOND_TOKEN

## Foreign gateway

Publish `wss://bond.example.com/bond` on HTTPS TCP 443. Either run the gateway
behind a reverse proxy or give it the full TLS chain and key. The certificate
must match the hostname. For a reverse proxy listening on 443, run:

    .venv/bin/python bond.py gateway --max-paths 500

The gateway listens on `127.0.0.1:8443` by default. Forward only `/bond` to it.
For an existing Nginx HTTPS virtual host, the location is:

    location = /bond {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Bond-Session $http_x_bond_session;
        proxy_read_timeout 75s;
        proxy_send_timeout 75s;
        proxy_buffering off;
    }

If using Cloudflare's proxy for your domain, point the DNS record at your own
gateway and use Full (strict) with a valid origin certificate. Keep WebSockets
enabled. Verify the upgrade from the Iran host before putting traffic on it.
Use the hostname rather than a bare CDN IP in the WebSocket URL.

For direct TLS instead of a reverse proxy, run with permissions to bind 443
and read the certificate and key:

    .venv/bin/python bond.py gateway --bind 0.0.0.0 --port 443 \
      --cert /path/to/fullchain.pem --key /path/to/privkey.pem --max-paths 500

The gateway requires the shared token and permits public destinations by
default. `--allow-private-destinations` is intended for an isolated test lab.

## Iran connector and X-UI

Start with automatic hostname resolution:

    .venv/bin/python bond.py client --url wss://bond.example.com/bond

Optional: pass a custom list containing IPs that actually serve your hostname
or explicitly forward it to your gateway. Lists support as many as 10,000 IP
literals. The certificate and HTTP hostname still come from the WebSocket URL.
The connector authenticates to this exact service before it admits a path.

    .venv/bin/python bond.py client --url wss://bond.example.com/bond \
      --endpoints endpoints.txt --probe-rate 50 --max-paths 500 --socks-port 1080

The connector reloads the list on each discovery pass. An empty list uses DNS.
Remove a path from the file to retire it at the next reload. Disconnected paths
are removed and retried. When the pool is full, a substantially lower RTT can
replace its slowest recorded lane. Size the deployment gradually; the ceilings
are settings, not throughput guarantees.

In X-UI, add a SOCKS outbound to `127.0.0.1:1080` and route a test inbound to it.
This socket is on the Iran host. If Xray runs in a separate network namespace,
loopback must refer to the same namespace for both processes.

    curl --max-time 20 --proxy socks5h://127.0.0.1:1080 https://api.ipify.org

The expected result is the public egress IP of the foreign gateway.

## Limits

- This is a standalone WSS gateway. It uses a `wss://` service URL rather than
  the existing Aether Cloudflare WARP/MASQUE peer format.
- Generic Cloudflare ranges are not bundled. An IP's presence in a published
  CDN range does not establish forwarding to your service.
- SOCKS5 CONNECT carries TCP. UDP ASSOCIATE is unsupported.
- Data frames rotate through the live paths; streams share a bounded send
  window. The process does not have X-UI account IDs to enforce per-user rates.
- Distinct endpoint addresses may share one network bottleneck. There is no
  promise that all configured paths are available or give additive capacity.
