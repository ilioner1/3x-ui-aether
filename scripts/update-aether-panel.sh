#!/usr/bin/env bash
# Update the panel and its Psiphon companion on an existing native Aether installation.
set -euo pipefail
release=v3.11.0-aether.8
panel=/usr/local/x-ui/x-ui
psiphon=/usr/local/x-ui/bin/pt/psiphon-tunnel-core
notices=/usr/local/x-ui/bin/aether-licenses

if [[ $EUID != 0 ]]; then
    echo "Run this update as root." >&2
    exit 1
fi
if [[ ! -x $panel || ! -x /usr/local/x-ui/bin/aether ]] ||
    ! systemctl show x-ui -p Environment --value | grep -Fq 'XUI_AETHER_NATIVE=1'; then
    echo "This update requires a native 3x-ui Aether installation." >&2
    exit 1
fi

case "$(uname -m)" in
    x86_64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) echo "Unsupported CPU architecture." >&2; exit 1 ;;
esac

exec 9>/usr/local/x-ui/.aether-update.lock
flock -n 9 || { echo "Another Aether update is running." >&2; exit 1; }
stage=$(mktemp -d /usr/local/x-ui/.aether-update.XXXXXXXX)
rollback=false
cleanup() {
    local code=$?
    if [[ $rollback == true ]]; then
        echo "Restoring the previous panel and companion." >&2
        systemctl stop x-ui || true
        if [[ -e $stage/previous-psiphon ]]; then
            mv -f -- "$stage/previous-psiphon" "$psiphon" || exit 1
        else
            rm -f -- "$psiphon" || exit 1
        fi
        if ! mv -f -- "$stage/previous" "$panel" || ! systemctl start x-ui; then
            echo "Rollback failed. Inspect $stage and x-ui.service." >&2
            exit 1
        fi
    fi
    rm -rf -- "$stage"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

archive="x-ui-linux-$arch.tar.gz"
if [[ -n ${XUI_AETHER_PACKAGE_DIR:-} ]]; then
    cp -- "$XUI_AETHER_PACKAGE_DIR/$archive" "$XUI_AETHER_PACKAGE_DIR/$archive.sha256" "$stage/"
else
    url="https://github.com/ilioner1/3x-ui-aether/releases/download/$release/$archive"
    curl -fsSL --retry 3 "$url" -o "$stage/$archive"
    curl -fsSL --retry 3 "$url.sha256" -o "$stage/$archive.sha256"
fi
checksum=$(awk 'NR == 1 {print $1}' "$stage/$archive.sha256")
if [[ ! $checksum =~ ^[0-9a-f]{64}$ ]] ||
    ! printf '%s  %s\n' "$checksum" "$stage/$archive" | sha256sum --check --status; then
    echo "Aether package checksum verification failed." >&2
    exit 1
fi
tar -xOf "$stage/$archive" x-ui/x-ui > "$stage/next"
tar -xOf "$stage/$archive" x-ui/bin/pt/psiphon-tunnel-core > "$stage/next-psiphon"
tar -xf "$stage/$archive" -C "$stage" x-ui/bin/aether-licenses
test -s "$stage/next"
test -s "$stage/next-psiphon"
chmod 0755 "$stage/next" "$stage/next-psiphon"
install -d "${psiphon%/*}"
if [[ -e $psiphon ]]; then
    cp -p -- "$psiphon" "$stage/previous-psiphon"
fi
install -d "$notices"
cp -R "$stage/x-ui/bin/aether-licenses/." "$notices/"
cp -p -- "$panel" "$stage/previous"
systemctl stop x-ui
rollback=true
mv -f -- "$stage/next" "$panel"
mv -f -- "$stage/next-psiphon" "$psiphon"
systemctl start x-ui
sleep 3
systemctl is-active --quiet x-ui
rollback=false
echo "Updated the native Aether panel to $release."
