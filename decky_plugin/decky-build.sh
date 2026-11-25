#!/bin/bash
# Build and package the Ludo Decky plugin as a ZIP for installation
# via Decky Loader → gear icon → "Install plugin from ZIP".
set -e

PLUGIN_NAME="ludo"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_ZIP="${SCRIPT_DIR}/../${PLUGIN_NAME}.zip"

# ── Vendored Python dependencies ─────────────────────────────────────────────
# Decky Loader is a PyInstaller AppImage running its own Python — 3.11 up to
# v3.2, 3.14 from v3.3 — NOT the system Python — and it exposes none of these to plugins, so every one of them has to
# ride along in py_modules/ (main.py puts that directory on sys.path).
#
# This used to refresh Pillow alone and take the rest on faith from whatever the
# build machine happened to have lying around in py_modules/. Those directories
# are gitignored, so a clean checkout — which is exactly what CI builds from —
# had none of them: v1.0.0-beta.1 shipped with PIL and the backend and nothing
# else. sync_core imports requests, psutil and watchdog at module scope, so the
# whole engine failed to import on device and the plugin fell back to its
# "sync_core not available" path. Vendoring them here, from a pinned list rather
# than from the working tree, is what makes the zip reproducible.
#
# Binary wheels (Pillow, cffi, charset_normalizer) must match the interpreter or
# they silently fail to import; --only-binary :all: with an explicit
# --python-version is what pins that. Their extension filenames carry the Python
# version, so both sets unpack side by side and each Decky loads its own. The
# versions are resolved once and pinned for the second set, so one package
# never mixes files from two releases. Transitive deps are resolved
# rather than listed by hand — qrcode's typing_extensions is the kind of thing
# --no-deps drops and nobody notices until a QR code fails to draw.
# typing_extensions is named because pip judges a dependency's Python-version
# marker by the Python running pip, not by --python-version: qrcode needs it on
# 3.11 and a newer build machine would leave it out.
DEPS=(requests watchdog psutil qrcode Pillow cryptography typing_extensions "python-socketio[client]")

PY_VERSIONS=(3.14 3.11)
# Decky Loader ships for x86_64 (Steam Deck) and aarch64 (ARM handhelds running
# SteamOS derivatives), and one zip serves both. Pure-Python wheels unpack into
# py_modules/ and are shared; platform wheels unpack into py_modules/_native/<arch>/
# and main.py puts the one matching the running Decky on sys.path. They cannot
# share one directory: abi3 extensions (cryptography's _rust.abi3.so, psutil's)
# carry no architecture in their filename, so one arch would overwrite the other.
#
# A single zip rather than one per arch because the updater selects its asset
# by suffix: an "-aarch64-decky.zip" would also match every x86 install's
# "-decky.zip" and could be handed to the wrong machine.
ARCHES=(x86_64 aarch64)
NATIVE_DIR="${SCRIPT_DIR}/py_modules/_native"
echo "==> Vendoring Python deps for Decky's Python ${PY_VERSIONS[*]} on ${ARCHES[*]}: ${DEPS[*]}"
WHEEL_TMP=$(mktemp -d)
trap 'rm -rf "$WHEEL_TMP"' EXIT
# --platform matches wheel tags literally: it does not imply the older
# manylinux tags the way a real installer's compatibility check does. Pillow
# publishes manylinux_2_28, watchdog only manylinux2014, psutil a compound tag
# carrying manylinux2014 — so all three spellings have to be offered or the
# resolver reports the package as simply not existing. Pure-Python wheels
# (py3-none-any) match regardless.
wheel_tags() {
    echo --platform "manylinux_2_28_$1" --platform "manylinux_2_17_$1" \
         --platform "manylinux2014_$1" --only-binary :all:
}
# Newest Python on the first arch resolves the versions: it has the shortest
# list of releases with wheels, so every other Python/arch pair can match the
# versions it picks, and no package mixes files from two releases.
mkdir -p "$WHEEL_TMP/${ARCHES[0]}"
# shellcheck disable=SC2046  # wheel_tags is meant to word-split
pip download "${DEPS[@]}" --python-version 3.14 $(wheel_tags "${ARCHES[0]}") \
    -d "$WHEEL_TMP/${ARCHES[0]}" --quiet
PINS=()
for whl in "$WHEEL_TMP/${ARCHES[0]}"/*.whl; do
    base=$(basename "$whl"); PINS+=("${base%%-*}==$(echo "$base" | cut -d- -f2)")
done
for arch in "${ARCHES[@]}"; do
    mkdir -p "$WHEEL_TMP/$arch"
    for py in "${PY_VERSIONS[@]}"; do
        [ "$arch" = "${ARCHES[0]}" ] && [ "$py" = 3.14 ] && continue
        # shellcheck disable=SC2046
        pip download "${PINS[@]}" --python-version "$py" $(wheel_tags "$arch") \
            -d "$WHEEL_TMP/$arch" --quiet
    done
done

# Rebuilt from scratch: a package dropped from DEPS must not linger in the zip.
rm -rf "$NATIVE_DIR"
shopt -s nullglob
for arch in "${ARCHES[@]}"; do
    WHEELS=("$WHEEL_TMP/$arch"/*.whl)
    [ ${#WHEELS[@]} -gt 0 ] || { echo "ERROR: pip downloaded no $arch wheels" >&2; exit 1; }
    for whl in "${WHEELS[@]}"; do
        # The platform tag is the wheel filename's last field.
        plat=$(basename "$whl" .whl); plat=${plat##*-}
        if [ "$plat" = any ]; then dest="${SCRIPT_DIR}/py_modules"; else dest="$NATIVE_DIR/$arch"; fi
        mkdir -p "$dest"   # unzip creates only the last path component
        # -o: the same pure wheel arrives once per arch, and re-running the build
        # over an existing py_modules must overwrite rather than prompt.
        unzip -q -o "$whl" -d "$dest" -x '*.dist-info/RECORD'
        echo "    $arch: $(basename "$whl")"
    done
done
# Builds before _native/ existed unpacked platform packages straight into
# py_modules/. A leftover copy there would ride along in the zip as dead
# weight, so clear anything _native/ now owns.
for entry in "$NATIVE_DIR"/*/*; do
    rm -rf "${SCRIPT_DIR}/py_modules/$(basename "$entry")"
done
shopt -u nullglob

# A Decky whose Python has no matching extension runs without covers and stores
# credentials in plain text, and nothing fails loudly — and on an arch with no
# psutil at all, the sync engine fails to import. So fail here, for every
# Python on every arch.
for arch in "${ARCHES[@]}"; do
    for d in PIL pillow.libs psutil cryptography; do
        [ -e "$NATIVE_DIR/$arch/$d" ] || {
            echo "ERROR: py_modules/_native/$arch/$d missing after vendoring" >&2; exit 1; }
    done
    for py in 311 314; do
        for pattern in "PIL/_imaging.cpython-$py-$arch-*" "_cffi_backend.cpython-$py-$arch-*"; do
            compgen -G "$NATIVE_DIR/$arch/$pattern" >/dev/null || {
                echo "ERROR: py_modules/_native/$arch has no $pattern" >&2; exit 1; }
        done
    done
done

# Prove the vendored tree is complete before it is packaged. The pure-Python
# packages are imported for real, which is what catches a missing transitive
# dependency. The binary wheels can only be imported when the build machine
# matches one of the targets — Python 3.11 or 3.14 (CI pins 3.11 deliberately)
# on one of ARCHES; everything else was checked as files above.
HOST_ARCH=$(uname -m)
NATIVE_HOST="$NATIVE_DIR/$HOST_ARCH" \
PYTHONPATH="${SCRIPT_DIR}/py_modules:$NATIVE_DIR/$HOST_ARCH" python3 - <<'PYCHECK'
import os, sys
missing = []
# watchdog publishes per-platform wheels, so it lives in _native/ too.
mods = ["requests", "qrcode", "socketio", "websocket"]
native_here = os.path.isdir(os.environ["NATIVE_HOST"])
if native_here:
    mods.append("watchdog.observers")
if native_here and sys.version_info[:2] in ((3, 11), (3, 14)):
    mods += ["PIL.Image", "psutil", "cryptography.fernet"]
for mod in mods:
    try:
        __import__(mod)
    except Exception as e:                      # noqa: BLE001 - report, don't raise
        missing.append(f"{mod}: {e}")
# Encoding something is the only proof qrcode arrived complete: qr_matrix()
# swallows an ImportError and returns None, which would ship as a pairing screen
# with no code on it rather than as a crash.
try:
    import qrcode
    qr = qrcode.QRCode(box_size=1, border=0)
    qr.add_data("https://example.com/pair/device?user_code=TEST1234")
    qr.make(fit=True)
    assert qr.get_matrix()
except Exception as e:                          # noqa: BLE001
    missing.append(f"qrcode encode: {e}")
if missing:
    print("ERROR: vendored py_modules is incomplete:", file=sys.stderr)
    for m in missing:
        print(f"  - {m}", file=sys.stderr)
    sys.exit(1)
print("    vendored deps import OK")
PYCHECK

echo "==> Building frontend..."
cd "$SCRIPT_DIR"
pnpm run build

echo "==> Packaging zip..."
TMP_DIR=$(mktemp -d)
mkdir -p "${TMP_DIR}/${PLUGIN_NAME}/dist"
mkdir -p "${TMP_DIR}/${PLUGIN_NAME}/py_modules"
mkdir -p "${TMP_DIR}/${PLUGIN_NAME}/assets"
mkdir -p "${TMP_DIR}/${PLUGIN_NAME}/bin"

cp "${SCRIPT_DIR}/plugin.json"             "${TMP_DIR}/${PLUGIN_NAME}/"
cp "${SCRIPT_DIR}/package.json"            "${TMP_DIR}/${PLUGIN_NAME}/"
cp "${SCRIPT_DIR}/LICENSE"                 "${TMP_DIR}/${PLUGIN_NAME}/"
cp "${SCRIPT_DIR}/main.py"                 "${TMP_DIR}/${PLUGIN_NAME}/"
cp "${SCRIPT_DIR}/dist/index.js"           "${TMP_DIR}/${PLUGIN_NAME}/dist/"
cp "${SCRIPT_DIR}/dist/index.js.map"       "${TMP_DIR}/${PLUGIN_NAME}/dist/"
# Copy all py_modules (the ludo_app backend, the romm_sync_engine sync core, and
# bundled dependencies like requests and watchdog). -L dereferences the
# ludo_app and romm_sync_engine dev symlinks, vendoring both into the zip — the
# Deck has no pip install step, so main.py finds them on sys.path instead.
cp -rL "${SCRIPT_DIR}/py_modules/"* "${TMP_DIR}/${PLUGIN_NAME}/py_modules/"
# Remove unnecessary files
rm -rf "${TMP_DIR}/${PLUGIN_NAME}/py_modules/__pycache__" "${TMP_DIR}/${PLUGIN_NAME}/py_modules/bin" "${TMP_DIR}/${PLUGIN_NAME}/py_modules/"*.dist-info \
    "${TMP_DIR}/${PLUGIN_NAME}/py_modules/_native/"*/*.dist-info \
    "${TMP_DIR}/${PLUGIN_NAME}/py_modules/romm_sync_engine/__pycache__" \
    "${TMP_DIR}/${PLUGIN_NAME}/py_modules/ludo_app/__pycache__"
# The artwork is package data of ludo_app now, so the `cp -rL py_modules/*`
# above already vendored it at py_modules/ludo_app/assets/ — which is where
# backend.py looks. This copy is only for the plugin-root logo Decky Loader
# shows in its plugin list.
cp "${SCRIPT_DIR}/py_modules/ludo_app/assets/logo.png" "${TMP_DIR}/${PLUGIN_NAME}/assets/"

# The exe behind the "RomM" Steam tile. Steam launches this as a tracked game so
# the overlay opens, and it execs the resolved emulator argv in place. Without it
# in the zip, backend.get_session_host_path() finds nothing and Play falls back
# to a direct launch with no working overlay -- which is what every release
# before this shipped, because nothing copied bin/ at all.
cp "${SCRIPT_DIR}/bin/romm-session-host" "${TMP_DIR}/${PLUGIN_NAME}/bin/"
chmod +x "${TMP_DIR}/${PLUGIN_NAME}/bin/romm-session-host"

rm -f "$OUT_ZIP"
(cd "$TMP_DIR" && zip -r "$OUT_ZIP" "${PLUGIN_NAME}/")
rm -rf "$TMP_DIR"

echo "==> Done: ${OUT_ZIP}"
