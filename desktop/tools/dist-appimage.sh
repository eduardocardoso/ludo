#!/usr/bin/env bash
# Package the AppImage for the machine this runs on.
#
# Runs after prepare-runtime.sh, whose interpreter is this machine's arch, so
# the Electron binary has to match it. The arch is passed explicitly rather
# than left to electron-builder's default.
#
# The asset name is the updater's contract (HostProfile.asset_suffix, built
# from the same arch in backend/server.py). x86_64 keeps artifactName from
# package.json, the name every existing install already looks for. aarch64
# overrides it here instead of using electron-builder's ${arch} macro, which
# would say "arm64" where the updater and the release workflow say "aarch64".
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

case "$(uname -m)" in
    x86_64)  exec npx electron-builder --linux AppImage --x64 ;;
    aarch64) exec npx electron-builder --linux AppImage --arm64 \
                 '-c.artifactName=Ludo-v${version}-aarch64.AppImage' ;;
    *)       echo "❌ no AppImage build for $(uname -m)"; exit 1 ;;
esac
