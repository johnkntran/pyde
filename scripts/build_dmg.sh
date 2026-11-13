#!/usr/bin/env bash
# Build dist/Pyde.app with PyInstaller and wrap it in dist/Pyde-<version>-arm64.dmg.
set -euo pipefail

cd "$(dirname "$0")/.."

version=$(uv version --short)
dmg="dist/Pyde-$version-arm64.dmg"

# Clear out earlier builds. The dist folder itself is left in place: with it
# open in Finder, removing it fails because Finder keeps writing into it.
rm -rf build dist/Pyde dist/Pyde.app dist/Pyde-*.dmg
uv run pyinstaller pyde.spec --noconfirm

# The disk image shows the app next to an Applications shortcut to drag it onto.
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
ditto dist/Pyde.app "$staging/Pyde.app"
ln -s /Applications "$staging/Applications"

# diskutil replaces hdiutil, which macOS 27 deprecates.
diskutil image create from --format UDZO --volumeName "Pyde $version" \
  "$staging" "$dmg"

echo "Built $dmg"
