"""Lichii saves upload to the Profile's RomM user; the save's owner follows routing.

Run with `python3 engine/tests/test_lichii_saves.py`. No emulator required:
every inventory test runs under a fake HOME (this machine may have a real
Lichii) with NAND trees built in a temp directory.
"""

import logging
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import emulator_saves as E  # noqa: E402
from romm_sync_engine import switch_content, sync_core  # noqa: E402
from romm_sync_engine import title_ids as T  # noqa: E402
from romm_sync_engine.sync_core import AutoSyncManager  # noqa: E402

FAILURES = []

# A Switch 2 exclusive (an "04" ID), a Switch 1 game, and a Switch 2 Edition
# that kept its Switch 1 ("01") ID but sits on a switch-2 ROM.
SWITCH2_ONLY = '0400486024DEC000'
SWITCH1 = '0100000000010000'
EDITION = '01000000000A0000'


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")


@contextmanager
def fake_home():
    """HOME and XDG_CONFIG_HOME in a temp dir: this machine may have a real
    Eden or Lichii, and a failing add-on check would write Ludo's manifest."""
    with tempfile.TemporaryDirectory() as tmp, \
            patch.dict(os.environ, {'HOME': tmp, 'XDG_CONFIG_HOME': f'{tmp}/.config'}):
        os.environ.pop('EDEN_DATA_DIR', None)
        os.environ.pop('LICHII_DATA_DIR', None)
        yield Path(tmp)


def test_title_ids():
    check('04 base is a save title', T.is_switch_title_id(SWITCH2_ONLY), True)
    check('04 update is not a save title',
          T.is_switch_title_id('0400486024DEC800'), False)
    check('04 update kind', T.switch_kind('0400486024DEC800'), 'update')
    check('04 update folds to its base',
          T.base_switch_title_id('0400486024DEC800'), SWITCH2_ONLY)
    check('04 tag in a name', T.title_id_from_name(
        f'Some Game [{SWITCH2_ONLY}][v0].nsp'), SWITCH2_ONLY)
    check('other prefixes stay out', T.is_switch_title_id('0200000000010000'), False)
    check('01 unchanged', T.is_switch_title_id(SWITCH1), True)


def test_add_ons_stay_switch_only():
    # Every downloaded .nsp/.xci goes through install_switch_add_on with no
    # Platform check, so a Switch 2 update must never read as a Switch add-on:
    # it would be installed into Eden's NAND.
    update2 = 'Some Game [0400486024DEC800][v65536].nsp'
    dlc2 = 'Some Game [0400486024DED001].nsp'
    update1 = '[0100000000010800][v65536].nsp'
    check('Switch 2 update is not an add-on by name',
          T.switch_content_from_name(update2), None)
    check('Switch 2 DLC is not an add-on by name',
          T.switch_content_from_name(dlc2), None)
    check('Switch 1 update still is',
          (T.switch_content_from_name(update1) or {}).get('kind'), 'update')
    check('Switch 2 content is not grouped as Switch add-ons',
          T.group_switch_content([update2, dlc2]), {})
    with fake_home() as home:
        tmp = home / 'roms'
        tmp.mkdir()
        f = tmp / update2
        f.write_bytes(b'')
        check('Switch 2 update is not Switch content', T.switch_content(f), None)
        check('a Switch 2 update is not installed as an add-on',
              switch_content.install(f).get('status'), 'not-switch')
        check('...nor placed in the add-on folder',
              switch_content.install_external(f, tmp).get('status'), 'not-switch')


USER = 'A' * 32  # an Emulator user's save folder (byte-reversed uuid hex)


def nand_save(home, emulator, title_id, data=b'progress'):
    """A save as Eden or Lichii writes it, under ``home``."""
    d = (home / '.local' / 'share' / emulator / 'nand' / 'user' / 'save'
         / ('0' * 16) / USER / title_id)
    d.mkdir(parents=True)
    (d / 'save.bin').write_bytes(data)
    return d


def manager(games):
    """The sync manager without its constructor: just what the inventory reads."""
    m = AutoSyncManager.__new__(AutoSyncManager)
    m.get_games = lambda: games
    m.settings = type('S', (), {'get': lambda self, *a: ''})()
    m.log = lambda *a, **k: None
    m._title_id_index = None
    return m


def game(rom_id, slug, title_id):
    return {'rom_id': rom_id, 'platform_slug': slug,
            'romm_data': {'title_id': title_id}}


@contextmanager
def inventory_env():
    """A fake home with neither emulator running, and the logs captured."""
    with fake_home() as home, \
            patch.object(sync_core, 'cache_dir', lambda: home / 'cache'), \
            patch.object(E, 'eden_is_running', lambda: False), \
            patch.object(E, 'lichii_is_running', lambda: False):
        records = []
        handler = logging.Handler(logging.INFO)
        handler.emit = records.append
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            yield home, records
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)


def by_label(rows):
    return {(r['emulator'], r['rom_id']) for r in rows}


def mentions(records, text):
    return [r for r in records if text in r.getMessage()]


def test_inventory_follows_routing():
    with inventory_env() as (home, records):
        nand_save(home, 'eden', SWITCH1)
        nand_save(home, 'lichii', SWITCH2_ONLY)
        nand_save(home, 'lichii', EDITION)
        nand_save(home, 'lichii', SWITCH1)  # a Switch 1 game played in Lichii
        m = manager([game(1, 'switch', SWITCH1),
                     game(2, 'switch-2', SWITCH2_ONLY),
                     game(3, 'switch-2', EDITION)])
        rows = m._eden_inventory_entries()
        check('each save goes to the emulator its ROM routes to', by_label(rows),
              {('Eden', 1), ('Lichii', 2), ('Lichii', 3)})
        lichii = [r for r in rows if r['emulator'] == 'Lichii']
        check('Lichii saves upload as the autosave',
              {r['_upload_name'] for r in lichii}, {'autosave.zip'})
        check('...with their own title inside the pack',
              sorted(E.pack_title_id(r['_path']) for r in lichii),
              sorted([SWITCH2_ONLY, EDITION]))
        check("...packed apart from Eden's",
              {Path(r['_path']).parent for r in lichii},
              {home / 'cache' / 'packed_saves' / 'lichii'})
        eden = [r for r in rows if r['emulator'] == 'Eden']
        check("Eden's pack path is unchanged", [r['_path'] for r in eden],
              [str(home / 'cache' / 'packed_saves' / f'{SWITCH1}.zip')])
        check('the Switch 1 save in Lichii is logged once, at info',
              [r.levelno for r in mentions(records, SWITCH1)], [logging.INFO])

        records.clear()
        m._eden_inventory_entries()
        check('...and once again on the next sync',
              len(mentions(records, SWITCH1)), 1)


def test_same_title_on_both_platforms():
    # A Switch 2 Edition can keep its Switch 1 ID, and a library can hold both
    # ROMs. Each emulator's inventory finds its own, whichever is listed first.
    for games in ([game(4, 'switch', EDITION), game(5, 'switch-2', EDITION)],
                  [game(5, 'switch-2', EDITION), game(4, 'switch', EDITION)]):
        with inventory_env() as (home, _records):
            nand_save(home, 'eden', EDITION)
            nand_save(home, 'lichii', EDITION)
            rows = manager(games)._eden_inventory_entries()
            check(f'one ID on two ROMs, rom {games[0]["rom_id"]} listed first',
                  by_label(rows), {('Eden', 4), ('Lichii', 5)})


def test_unmatched_lichii_save_is_skipped():
    with inventory_env() as (home, records):
        nand_save(home, 'lichii', '0400000000BEE000')
        rows = manager([game(2, 'switch-2', SWITCH2_ONLY)])._eden_inventory_entries()
        check('a Lichii save matching no ROM is not uploaded', rows, [])
        check('...and is logged once',
              len(mentions(records, '0400000000BEE000')), 1)


def test_no_switch2_library_leaves_lichii_alone():
    with inventory_env() as (home, _records):
        nand_save(home, 'eden', SWITCH1)
        nand_save(home, 'lichii', SWITCH1)
        read = []
        real_find = E.find_eden_saves

        def find(*a, **kw):
            read.append(kw.get('variant', E.EDEN).name)
            return real_find(*a, **kw)
        with patch.object(E, 'find_eden_saves', find):
            rows = manager([game(1, 'switch', SWITCH1)])._eden_inventory_entries()
        check('with no Switch 2 ROM, only Eden uploads', by_label(rows), {('Eden', 1)})
        check("...and Lichii's tree is not read", read, ['Eden'])


def test_lichii_running_defers_only_lichii():
    with inventory_env() as (home, _records), \
            patch.object(E, 'lichii_is_running', lambda: True):
        nand_save(home, 'eden', SWITCH1)
        nand_save(home, 'lichii', SWITCH2_ONLY)
        rows = manager([game(1, 'switch', SWITCH1),
                        game(2, 'switch-2', SWITCH2_ONLY)])._eden_inventory_entries()
        check('a running Lichii defers only its own saves', by_label(rows),
              {('Eden', 1)})


def test_lichii_data_dir_setting():
    with inventory_env() as (home, _records):
        elsewhere = home / 'elsewhere'
        nand_save(elsewhere, 'lichii', SWITCH2_ONLY)
        m = manager([game(2, 'switch-2', SWITCH2_ONLY)])
        folder = str(elsewhere / '.local' / 'share' / 'lichii')
        m.settings = type('S', (), {'get': lambda self, section, key, *a: (
            folder if (section, key) == ('Emulators', 'lichii_data_dir') else '')})()
        check('[Emulators] lichii_data_dir is where Lichii saves are read',
              by_label(m._eden_inventory_entries()), {('Lichii', 2)})


def named_game(rom_id, slug, stem):
    """A library row known only by its filename: no server title ID."""
    return {'rom_id': rom_id, 'platform_slug': slug, 'name': stem,
            'file_name': f'{stem}.nsp',
            'romm_data': {'fs_name': f'{stem}.nsp', 'fs_name_no_ext': stem,
                          'platform_slug': slug}}


def test_plainly_named_edition_rom_is_found_by_its_container():
    """A Switch 2 Edition ROM named plainly is identified only by reading the
    local container. It must still be a candidate for its title, whether or
    not another ROM claimed the title first."""
    cases = {
        'switch ROM claimed by the server': (
            [game(4, 'switch', EDITION), named_game(5, 'switch-2', 'Zelda NS2 Edition')],
            ['switch-2/Zelda NS2 Edition.nsp']),
        'both ROMs local and plainly named': (
            [named_game(4, 'switch', 'Zelda'), named_game(5, 'switch-2', 'Zelda NS2 Edition')],
            ['switch/Zelda.nsp', 'switch-2/Zelda NS2 Edition.nsp']),
    }
    for label, (games, files) in cases.items():
        with inventory_env() as (home, _records), \
                patch.object(T, 'title_id_from_rom', lambda path, **kw: EDITION):
            roms = home / 'roms'
            for f in files:
                (roms / f).parent.mkdir(parents=True, exist_ok=True)
                (roms / f).write_bytes(b'')
            nand_save(home, 'eden', EDITION)
            nand_save(home, 'lichii', EDITION)
            m = manager(games)
            # What the filename tiers read, beyond the inventory's needs.
            m._rom_match_cache, m._rom_match_games = {}, None
            m._rom_id_for_launch_alias = lambda *a: None
            m.settings = type('S', (), {'get': lambda self, section, key, *a: (
                str(roms) if (section, key) == ('Download', 'rom_directory') else '')})()
            check(f'{label}: each emulator uploads its own ROM',
                  by_label(m._eden_inventory_entries()), {('Eden', 4), ('Lichii', 5)})


def main():
    test_title_ids()
    test_add_ons_stay_switch_only()
    test_inventory_follows_routing()
    test_same_title_on_both_platforms()
    test_unmatched_lichii_save_is_skipped()
    test_no_switch2_library_leaves_lichii_alone()
    test_lichii_running_defers_only_lichii()
    test_lichii_data_dir_setting()
    test_plainly_named_edition_rom_is_found_by_its_container()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all Lichii save checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
