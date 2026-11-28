#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
    echo "Usage: sudo bash install-service.sh gateway CERT KEY"
    echo "       sudo bash install-service.sh gateway --behind-proxy"
    echo "       sudo bash install-service.sh client WSS_URL [CA_FILE|-] [ENDPOINTS_FILE]"
    echo "       sudo bash install-service.sh client-masque WSS_URL CA_FILE|- [PEER_FILE]"
    echo "       sudo bash install-service.sh client-wireguard WSS_URL CA_FILE|- [PEER_FILE]"
}

if (( EUID != 0 )) || [[ ! -d /run/systemd/system ]]; then
    echo "Run with sudo on a host running systemd." >&2
    exit 1
fi

role=${1:-}
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
cert= key= ca= endpoints= capabilities= warp_mode= aether_binary=
case "$role" in
    gateway)
        if [[ $# -eq 2 && $2 == --behind-proxy ]]; then
            listen_port=8443
            args='gateway --max-paths 500'
        elif [[ $# -eq 3 && -r $2 && -r $3 ]]; then
            listen_port=443
            cert=$2
            key=$3
            openssl x509 -in "$cert" -noout -checkend 0
            cert_key=$(openssl x509 -in "$cert" -pubkey -noout)
            private_key=$(openssl pkey -in "$key" -passin pass: -pubout)
            if [[ $cert_key != "$private_key" ]]; then
                echo "The TLS certificate and key do not match." >&2
                exit 1
            fi
            capabilities=$'AmbientCapabilities=CAP_NET_BIND_SERVICE\nCapabilityBoundingSet=CAP_NET_BIND_SERVICE'
            args='gateway --bind 0.0.0.0 --port 443 --cert %d/gateway-cert --key %d/gateway-key --max-paths 500'
        else
            usage
            exit 2
        fi
        ;;
    client|client-masque|client-wireguard)
        case "$role" in
            client-masque) warp_mode=masque ;;
            client-wireguard) warp_mode=wireguard ;;
        esac
        role=client
        if (( $# < 2 || $# > 4 )) || [[ ! $2 =~ ^wss://[A-Za-z0-9.:-]+/[A-Za-z0-9/_-]+$ ]]; then
            usage
            exit 2
        fi
        listen_port=1080
        args="client --url $2 --socks-port 1080 --max-paths 500"
        if [[ -n ${3:-} && $3 != - ]]; then
            openssl x509 -in "$3" -noout
            ca=$3
            args+=' --ca-file %d/gateway-ca'
        fi
        if [[ -n ${4:-} ]]; then
            test -r "$4"
            endpoints=$4
        fi
        if [[ -n $warp_mode ]]; then
            aether_binary=${XUI_AETHER_BINARY:-/usr/local/x-ui/bin/aether}
            if [[ ! -x $aether_binary ]]; then
                echo "Aether core not found. Set XUI_AETHER_BINARY to the executable from your x-ui Aether installation." >&2
                exit 1
            fi
            args+=" --aether-bin /opt/aether-bond/client/aether --aether-mode $warp_mode --aether-state /var/lib/aether-bond-client"
        fi
        ;;
    *)
        usage
        exit 2
        ;;
esac

private_dir="/etc/aether-bond/$role"
service_dir="/opt/aether-bond/$role"
unit="aether-bond-$role.service"
credentials="LoadCredential=bond-token:$private_dir/token"
if ! systemctl is-active --quiet "$unit" && [[ -n $(ss -Hltn "sport = :$listen_port") ]]; then
    echo "TCP $listen_port is occupied. Stop the old foreground Bond process before installing." >&2
    exit 1
fi
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || {
    echo "Python 3.11 or later is required." >&2
    exit 1
}

install -d -m 0700 "$private_dir"
install -d -m 0755 "$service_dir"
if [[ -n ${BOND_TOKEN_FILE:-} || ! -s $private_dir/token ]]; then
    if [[ -n ${BOND_TOKEN_FILE:-} ]]; then
        token=$(<"$BOND_TOKEN_FILE")
    else
        read -rsp 'Bond token: ' token </dev/tty
        echo >&2
    fi
    if [[ ! $token =~ ^[A-Za-z0-9_-]{32,}$ ]]; then
        echo "The token must contain at least 32 URL-safe characters." >&2
        exit 2
    fi
    printf '%s\n' "$token" > "$private_dir/token"
    chmod 0600 "$private_dir/token"
    unset token
fi

if [[ -n $cert ]]; then
    install -m 0600 "$cert" "$private_dir/gateway-cert.pem"
    install -m 0600 "$key" "$private_dir/gateway-key.pem"
    credentials+=$'\n'"LoadCredential=gateway-cert:$private_dir/gateway-cert.pem"
    credentials+=$'\n'"LoadCredential=gateway-key:$private_dir/gateway-key.pem"
fi
if [[ -n $ca ]]; then
    install -m 0600 "$ca" "$private_dir/gateway-ca.pem"
    credentials+=$'\n'"LoadCredential=gateway-ca:$private_dir/gateway-ca.pem"
fi
if [[ -n $warp_mode ]]; then
    peer_file="$service_dir/peers-$warp_mode.txt"
    if [[ -n $endpoints ]]; then
        install -m 0644 "$endpoints" "$peer_file"
    elif [[ ! -s $peer_file ]]; then
        install -m 0644 "$source_dir/peers-$warp_mode.txt" "$peer_file"
    fi
    install -m 0755 "$aether_binary" "$service_dir/aether"
    args+=" --endpoints $peer_file --probe-rate 4"
elif [[ -n $endpoints ]]; then
    install -m 0644 "$endpoints" "$service_dir/endpoints.txt"
    args+=" --endpoints $service_dir/endpoints.txt --probe-rate 50"
fi
install -m 0644 "$source_dir/bond.py" "$source_dir/aether_transport.py" "$source_dir/requirements.txt" "$service_dir/"
(
    umask 022
    python3 -m venv "$service_dir/.venv"
    "$service_dir/.venv/bin/python" -m pip install -r "$service_dir/requirements.txt"
)

cat > "/etc/systemd/system/$unit" <<EOF
[Unit]
Description=Aether Bond ($role)
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=exec
DynamicUser=yes
StateDirectory=aether-bond-$role
StateDirectoryMode=0700
WorkingDirectory=$service_dir
$credentials
$capabilities
ExecStart=$service_dir/.venv/bin/python -u $service_dir/bond.py $args
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "/etc/systemd/system/$unit"

systemctl daemon-reload
systemctl enable "$unit"
systemctl restart "$unit"
for ((attempt=0; attempt<30; attempt++)); do
    if systemctl is-active --quiet "$unit" &&
        [[ -n $(ss -Hltnp "sport = :$listen_port" | grep -F "pid=$(systemctl show -p MainPID --value "$unit"),") ]]; then
        echo "$unit is active and listening on TCP $listen_port."
        exit 0
    fi
    sleep 0.3
done
echo "The service did not begin listening. Inspect: sudo journalctl -u $unit -n 40 --no-pager" >&2
exit 1
