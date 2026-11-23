#!/usr/bin/env python3
"""A downloaded Switch 2 ROM is never installed into Eden's NAND.

A Switch 2 Edition upgrade is a switch-2 ROM whose container carries a Switch
("01") ID, so the "04" filter in the content readers does not catch it. The
Platform does: a ROM routed to an emulator other than Eden skips Eden's add-on
install.

Run with `python3 engine/tests/test_switch2_add_on_install.py`. Runs under a
fake HOME.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import sync_core  # noqa: E402

FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(label)


class _Settings:
    def __init__(self, roms):
        self.values = {('Download', 'rom_directory'): str(roms)}

    def get(self, section, key, default=None):
        return self.values.get((section, key), default)


class _Client:
    def download_rom(self, rom_id, name, path, progress_callback=None,
                     cancellation_checker=None):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b'x' * 64)
        return True, 'ok'


def rom(rom_id, slug, fs_name):
    return {'id': rom_id, 'name': fs_name.rsplit('.', 1)[0], 'fs_name': fs_name,
            'fs_extension': 'nsp', 'platform_slug': slug}


def test_only_rom_routed_to_eden_installs_add_ons():
    with tempfile.TemporaryDirectory() as tmp, \
            patch.dict(os.environ, {'HOME': tmp, 'XDG_CONFIG_HOME': f'{tmp}/.config'}):
        m = sync_core.CollectionSyncManager.__new__(sync_core.CollectionSyncManager)
        m.settings = _Settings(Path(tmp) / 'roms')
        m.romm_client = _Client()
        m.log = lambda *a: None
        m.running = True
        m.selected_collections = {'Mine'}
        m.download_progress = {}
        m.available_games = []
        m.push_notification = lambda *a, **k: None
        m._sync_steam_if_enabled = lambda *a: None
        m._count_rom_files = lambda roms: len(roms)
        installed = []
        m.install_switch_add_on = lambda path, **kw: installed.append(Path(path).name)
        roms = [
            # A Switch 2 Edition upgrade: a switch-2 ROM with a Switch 1 ID.
            rom(1, 'switch-2', 'Zelda TOTK NS2 Edition [0100F2C0115B6800][v0].nsp'),
            rom(2, 'switch', 'Zelda TOTK [0100F2C0115B6800][v65536].nsp'),
        ]
        m.handle_added_games(roms, {1, 2}, 'Mine')
        check('only the switch ROM reaches the Eden add-on install', installed,
              ['Zelda TOTK [0100F2C0115B6800][v65536].nsp'])


def main():
    test_only_rom_routed_to_eden_installs_add_ons()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all switch 2 add-on install checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
