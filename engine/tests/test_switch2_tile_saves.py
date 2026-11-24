#!/usr/bin/env python3
"""A Switch 2 title's base, update and DLC ROMs share one save, as on Switch.

RomM stores a Switch 2 game's base dump, update and DLC as separate ROMs that
the library groups into one tile. They are one game with one save: a save
matched through a sibling belongs to the main entry, writes go to the ROM
played here, and reading takes the newest save on any ROM of the tile.

Run with `python3 engine/tests/test_switch2_tile_saves.py`. Runs under a fake
HOME (this machine may have a real Lichii).
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine.sync_core import AutoSyncManager  # noqa: E402

FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(label)


def matcher(games):
    m = AutoSyncManager.__new__(AutoSyncManager)
    m.get_games = lambda: games
    m._rom_match_cache = {}
    m._rom_match_games = None
    m._rom_id_for_launch_alias = lambda a, b: None
    m._rom_id_for_title_id = lambda t: None
    return m


def test_sibling_saves_attribute_to_the_main_entry():
    game = {
        'rom_id': 500, 'name': 'Mario Kart World', 'platform_slug': 'switch-2',
        'romm_data': {'fs_name_no_ext': 'Mario Kart World', 'platform_slug': 'switch-2'},
        '_sibling_files': [
            {'id': 501, 'name': 'Mario Kart World',
             'fs_name': 'Mario Kart World v65536', 'fs_name_no_ext': 'Mario Kart World v65536',
             'fs_extension': 'nsp'},
        ],
    }
    check('switch 2 sibling save attributes to the main entry',
          matcher([game]).find_rom_id_for_save_file(
              Path('/s/Mario Kart World v65536.srm')), 500)

    region = {
        'rom_id': 600, 'name': 'Region Switch 2', 'platform_slug': 'switch-2',
        'romm_data': {'fs_name_no_ext': 'Region Switch 2', 'platform_slug': 'switch-2'},
        '_sibling_files': [
            {'id': 601, 'name': 'Region Switch 2 (Europe)',
             'fs_name': 'Region Switch 2 (Europe)',
             'fs_name_no_ext': 'Region Switch 2 (Europe)', 'fs_extension': 'xci'},
        ],
    }
    check('switch 2 region-tagged sibling attributes to the main entry',
          matcher([game, region]).find_rom_id_for_save_file(
              Path('/s/Region Switch 2 (Europe).srm')), 600)


def tile_manager(home, platform, last=''):
    """A tile whose main ROM (7) is not on disk and whose update (8) is."""
    dump = home / 'roms/switch2/Game.nsp'
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_bytes(b'x')
    tile = {'rom_id': 7, 'platform_slug': platform, 'is_downloaded': True,
            'local_path': str(dump),
            '_sibling_files': [{'id': 8, 'fs_name': 'Game.nsp'}, {'id': 11}],
            '_variant_downloads': {'8': {'local_path': str(dump)}}}
    other = {'rom_id': 9, 'platform_slug': 'snes', 'is_downloaded': True,
             '_sibling_files': [{'id': 10}]}
    m = AutoSyncManager.__new__(AutoSyncManager)
    m.get_games = lambda: [tile, other]
    m.log = lambda *a, **k: None
    m.settings = type('S', (), {'get': lambda self, sec, key, d='': (
        last if (sec, key) == ('LastVersion', '7') else d)})()
    return m


def op(rom, action, when=None, h=None):
    o = {'rom_id': rom, 'slot': 'autosave', 'action': action}
    if when:
        o.update(server_updated_at=when, server_content_hash=h)
    return o


def test_tile_saves(home):
    for platform in ('switch-2', 'switch'):
        m = tile_manager(home, platform)
        check(f'{platform}: save is filed under the ROM played here',
              m._save_rom_id(7), 8)
        check(f'{platform}: a one-game sync covers the whole tile',
              m._tile_scope(8), {7, 8, 11})
        check(f'{platform}: other platforms keep their own rom', m._save_rom_id(9), 9)

        local = {'rom_id': 8, 'slot': 'autosave', 'content_hash': 'L',
                 'updated_at': '2026-11-16T12:00:00+00:00'}
        up = op(8, 'upload')
        old = op(7, 'download', '2026-11-15T10:00:00+00:00', 'O')
        dlc = op(11, 'download', '2026-11-14T10:00:00+00:00', 'D')
        check(f'{platform}: one save goes up, older sibling saves stay put',
              m._pick_tile_saves([up, old, dlc], [local]), [up])
        new = op(11, 'conflict', '2026-11-17T10:00:00+00:00', 'N')
        check(f'{platform}: a newer save on any sibling ROM is read instead',
              m._pick_tile_saves([up, old, new], [local]), [new])
        a = op(7, 'download', '2026-11-10T10:00:00+00:00', 'A')
        b = op(11, 'download', '2026-11-12T10:00:00+00:00', 'B')
        check(f'{platform}: nothing local, the newest of the tile wins',
              m._pick_tile_saves([a, b], []), [b])


def main():
    with tempfile.TemporaryDirectory() as tmp, \
            patch.dict(os.environ, {'HOME': tmp, 'XDG_CONFIG_HOME': f'{tmp}/.config'}):
        test_sibling_saves_attribute_to_the_main_entry()
        test_tile_saves(Path(tmp))
    print('\n' + ('FAIL: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'))
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
