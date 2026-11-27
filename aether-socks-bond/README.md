# Multi-Path SOCKS Gateway

Two processes carry a local SOCKS5 TCP connection over multiple authenticated
WebSocket connections. The gateway performs outbound TCP connections. Each
logical stream has a sequence number space, a receive window, cumulative
acknowledgements and retransmission if a path drops.

## Install

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
