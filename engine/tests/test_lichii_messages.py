#!/usr/bin/env python3
"""Errors and logs about Lichii name Lichii; Eden's read exactly as before.

Run with `python3 engine/tests/test_lichii_messages.py`. Runs under a fake
HOME (this machine may have a real Eden or Lichii).
"""
import logging
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import eden_users as U  # noqa: E402
from romm_sync_engine import emulator_saves as E  # noqa: E402
from romm_sync_engine import sync_core  # noqa: E402
from romm_sync_engine.eden_family import EDEN, LICHII  # noqa: E402
from romm_sync_engine.sync_core import AutoSyncManager  # noqa: E402

FAILURES = []
SWITCH1 = '0100000000010000'


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")


@contextmanager
def fake_home():
    with tempfile.TemporaryDirectory() as tmp, \
            patch.dict(os.environ, {'HOME': tmp, 'XDG_CONFIG_HOME': f'{tmp}/.config'}):
        os.environ.pop('EDEN_DATA_DIR', None)
        os.environ.pop('LICHII_DATA_DIR', None)
        yield Path(tmp)


@contextmanager
def captured_logs():
    records = []
    handler = logging.Handler(logging.DEBUG)
    handler.emit = records.append
    root = logging.getLogger()
    old_level, old_e = root.level, E.log.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    E.log.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
        E.log.setLevel(old_e)


def add_error(data_dir, **kw):
    try:
        U.add(data_dir, 'Mia', **kw)
    except U.EdenUsersError as e:
        return str(e)
    return None


def test_no_user_list_names_the_emulator():
    with fake_home() as home:
        check('eden: unchanged', add_error(home / 'eden'),
              'Eden has no user list yet; start Eden once first')
        check('lichii: names Lichii', add_error(home / 'lichii', variant=LICHII),
              'Lichii has no user list yet; start Lichii once first')


def save_tree_logs(variant):
    with fake_home() as home, captured_logs() as records:
        (home / '.local/share' / variant.key).mkdir(parents=True)
        kw = {} if variant is EDEN else {'variant': variant}
        E.find_eden_saves(**kw)
        return [r.getMessage().split(' at ')[0] for r in records
                if 'save tree' in r.getMessage()]


def test_missing_save_tree_names_the_emulator():
    check('eden: unchanged', save_tree_logs(EDEN), ['no Eden save tree'])
    check('lichii: names Lichii', save_tree_logs(LICHII), ['no Lichii save tree'])


def test_skipped_save_names_its_owner_readably():
    with fake_home() as home, captured_logs() as records, \
            patch.object(sync_core, 'cache_dir', lambda: home / 'cache'), \
            patch.object(E, 'eden_is_running', lambda: False), \
            patch.object(E, 'lichii_is_running', lambda: False):
        d = (home / '.local/share/lichii/nand/user/save' / ('0' * 16)
             / ('A' * 32) / SWITCH1)
        d.mkdir(parents=True)
        (d / 'save.bin').write_bytes(b'progress')
        m = AutoSyncManager.__new__(AutoSyncManager)
        m.get_games = lambda: [
            {'rom_id': 1, 'platform_slug': 'switch', 'romm_data': {'title_id': SWITCH1}},
            {'rom_id': 2, 'platform_slug': 'switch-2', 'romm_data': {}}]
        m.settings = type('S', (), {'get': lambda self, *a: ''})()
        m.log = lambda *a, **k: None
        m._title_id_index = None
        m._eden_inventory_entries()
        said = ' '.join(r.getMessage() for r in records if SWITCH1 in r.getMessage())
        check('skipped Switch 1 save says who owns it',
              f'{SWITCH1} (owned by Eden)' in said, True)
        check('...without "a Eden"', 'a Eden' in said, False)


def main():
    test_no_user_list_names_the_emulator()
    test_missing_save_tree_names_the_emulator()
    test_skipped_save_names_its_owner_readably()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all Lichii message checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
