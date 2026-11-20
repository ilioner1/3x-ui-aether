#!/usr/bin/env bash
set -euo pipefail
destination=${1:-bin}
version=v2.4.0
case "$(uname -m)" in
  x86_64|amd64) archive=aether-linux-x86_64-musl.tar.gz; checksum=44763e765050806b91d10ee2e1a662eac61fd8251f133c3ac241ca3bd80fac4d ;;
  aarch64|arm64) archive=aether-linux-aarch64-musl.tar.gz; checksum=728d1433f08fb3155ebc042299a17fc0ee1afb8ec59f87616991da0f5a24afac ;;
  armv7l) archive=aether-linux-armv7-musl.tar.gz; checksum=a89bfaf5a25b6705243460c0b491ecdf216bf6f024a2ec39f9189cd4ee5eaf5b ;;
  *) printf 'Unsupported Aether architecture: %s\n' "$(uname -m)" >&2; exit 1 ;;
esac
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
curl --fail --location --retry 3 "https://github.com/CluvexStudio/Aether/releases/download/$version/$archive" -o "$temporary/$archive"
printf '%s  %s\n' "$checksum" "$temporary/$archive" | sha256sum --check --status
tar -xzf "$temporary/$archive" -C "$temporary"
binary=$(find "$temporary" -type f -name aether -print -quit)
test -n "$binary"
mkdir -p "$destination"
install -m 0755 "$binary" "$destination/aether"
psiphon=$(find "$temporary" -type f -name psiphon-tunnel-core -print -quit)
test -n "$psiphon"
install -d "$destination/pt"
install -m 0755 "$psiphon" "$destination/pt/psiphon-tunnel-core"
cp -R "$(dirname "$binary")/LICENSES" "$destination/aether-licenses"
printf 'Installed Aether %s in %s\n' "$version" "$destination"
