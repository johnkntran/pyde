#!/usr/bin/env bash
# Build dist/Pyde.app with PyInstaller and wrap it in dist/Pyde-<version>-arm64.dmg.
set -euo pipefail

cd "$(dirname "$0")/.."

version=$(uv version --short)
dmg="dist/Pyde-$version-arm64.dmg"

rm -rf build dist
uv run pyinstaller pyde.spec --noconfirm

# The disk image shows the app next to an Applications shortcut to drag it onto.
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
ditto dist/Pyde.app "$staging/Pyde.app"
ln -s /Applications "$staging/Applications"

hdiutil create -volname "Pyde $version" -srcfolder "$staging" -format UDZO "$dmg"

echo "Built $dmg"
