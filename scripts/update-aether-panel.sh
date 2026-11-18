#!/usr/bin/env bash
# Replace only the panel binary on an existing native Aether installation.
set -euo pipefail
release=v3.11.0-aether.2
panel=/usr/local/x-ui/x-ui

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

stage=$(mktemp -d /usr/local/x-ui/.aether-update.XXXXXXXX)
rollback=false
cleanup() {
    local code=$?
    if [[ $rollback == true ]]; then
        echo "Restoring the previous panel binary." >&2
        systemctl stop x-ui || true
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
test -s "$stage/next"
chmod 0755 "$stage/next"
cp -p -- "$panel" "$stage/previous"
systemctl stop x-ui
rollback=true
mv -f -- "$stage/next" "$panel"
systemctl start x-ui
sleep 3
systemctl is-active --quiet x-ui
rollback=false
echo "Updated the native Aether panel to $release."
