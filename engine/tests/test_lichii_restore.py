"""Lichii saves restore on another machine; the target follows routing.

Run with `python3 engine/tests/test_lichii_restore.py`. No emulator required:
every test runs under a fake HOME (this machine may have a real Eden or
Lichii), with NAND trees built in a temp directory and RomM stubbed.
"""

import os
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import eden_users as U  # noqa: E402
from romm_sync_engine import emulator_saves as E  # noqa: E402
from romm_sync_engine import paths, sync_core  # noqa: E402
from romm_sync_engine import profiles as P  # noqa: E402
from romm_sync_engine.eden_family import LICHII  # noqa: E402
from romm_sync_engine.sync_core import AutoSyncManager  # noqa: E402

FAILURES = []

SWITCH2 = '0400486024DEC000'
SWITCH1 = '0100000000010000'
USER = 'A' * 32  # an Emulator user's save folder


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")


@contextmanager
def fake_home():
    """HOME and XDG_CONFIG_HOME in a temp dir, neither emulator running, and
    Ludo's cache inside it."""
    with tempfile.TemporaryDirectory() as tmp, \
            patch.dict(os.environ, {'HOME': tmp, 'XDG_CONFIG_HOME': f'{tmp}/.config'}), \
            patch.object(sync_core, 'cache_dir', lambda: Path(tmp) / 'cache'), \
            patch.object(E, 'eden_is_running', lambda *a, **k: False), \
            patch.object(E, 'lichii_is_running', lambda *a, **k: False):
        os.environ.pop('EDEN_DATA_DIR', None)
        os.environ.pop('LICHII_DATA_DIR', None)
        yield Path(tmp)


@contextmanager
def profiles_in_use():
    paths._locked, paths._profile_locked, paths._profile = False, False, P.DEFAULT
    paths.set_app_id('ludo')
    paths.set_library_dir_name('Ludo')
    P.launch = {'id': P.DEFAULT, 'steam': None, 'ask': False}
    try:
        yield
    finally:
        P.launch = None
        paths._locked, paths._profile_locked, paths._profile = False, False, P.DEFAULT


def use(profile_id):
    paths._locked, paths._profile_locked, paths._profile = False, False, P.DEFAULT
    paths.set_profile(profile_id)


class FakeClient:
    """RomM with one save to hand out."""
    base_url = 'http://romm'

    def __init__(self, pack):
        self.pack, self.confirmed = pack, []
        self.session = self

    def download_save_by_id(self, save_id, kind, dest, device_id=None, session_id=None):
        dest.write_bytes(Path(self.pack).read_bytes())
        return True

    def confirm_save_downloaded(self, save_id, kind, device_id, content_hash=None):
        self.confirmed.append(save_id)
        return True


def server_pack(home, data=b'SERVER'):
    pack = home / 'server.zip'
    with zipfile.ZipFile(pack, 'w') as z:
        z.writestr('Autosave.save', data)
    return pack


def manager(home, games, pack=None):
    """The sync manager without its constructor: just what restore reads."""
    m = AutoSyncManager.__new__(AutoSyncManager)
    m.get_games = lambda: games
    m.settings = type('S', (), {'get': lambda self, *a: ''})()
    m.log = lambda *a, **k: None
    m.romm_client = FakeClient(pack or server_pack(home))
    return m


def game(rom_id, slug):
    return {'rom_id': rom_id, 'platform_slug': slug}


def op(rom_id, title_id, label):
    return {'save_id': 41, 'rom_id': rom_id, 'file_name': f'{title_id}.zip',
            'emulator': label}


def save_dir(home, emulator, title_id, user=USER):
    return (home / '.local' / 'share' / emulator / 'nand' / 'user' / 'save'
            / ('0' * 16) / user / title_id)


def read(directory):
    """The restored save's contents, or None when nothing is there."""
    try:
        return (directory / 'Autosave.save').read_bytes()
    except OSError:
        return None


def nand_save(home, emulator, title_id, data=b'LOCAL', user=USER):
    d = save_dir(home, emulator, title_id, user)
    d.mkdir(parents=True)
    (d / 'Autosave.save').write_bytes(data)
    return d


def test_restores_under_the_profiles_lichii_user():
    with fake_home() as home, profiles_in_use():
        lichii = home / '.local/share/lichii'
        U.create_default(lichii, variant=LICHII)
        mia = P.create('Mia')
        use(mia)
        user = P.eden_user(create=True, variant=LICHII)
        m = manager(home, [game(2, 'switch-2')])
        check("a switch-2 ROM's save restores",
              m._restore_standalone_save(op(2, SWITCH2, 'Lichii'), 'dev', None), True)
        check("...into Lichii's tree, under the Profile's Lichii user",
              read(save_dir(home, 'lichii', SWITCH2, user['save_dir'])), b'SERVER')
        check("...and Eden's tree is untouched", (home / '.local/share/eden').exists(), False)
        check('...and the sync is recorded', m.romm_client.confirmed, [41])


def test_routing_not_the_label_picks_the_tree():
    with fake_home() as home:
        eden_save = nand_save(home, 'eden', SWITCH1)
        lichii_save = nand_save(home, 'lichii', SWITCH2)
        m = manager(home, [game(1, 'switch'), game(2, 'switch-2')])
        check("an 'Eden' save on a switch-2 ROM restores",
              m._restore_standalone_save(op(2, SWITCH2, 'Eden'), 'dev', None), True)
        check('...into Lichii', read(lichii_save), b'SERVER')
        check('...and not into Eden', read(save_dir(home, 'eden', SWITCH2)), None)

        check("a 'Lichii' save on a switch ROM restores",
              m._restore_standalone_save(op(1, SWITCH1, 'Lichii'), 'dev', None), True)
        check('...into Eden', read(eden_save), b'SERVER')
        check('...and never into Lichii', read(save_dir(home, 'lichii', SWITCH1)), None)


def test_switch2_saves_never_take_the_retroarch_path():
    with fake_home() as home:
        m = manager(home, [game(2, 'switch-2')])
        for label in ('Lichii', 'Eden', 'switch-2', ''):
            check(f"a switch-2 save labelled {label!r} goes to the standalone restore",
                  m._resolve_download_target(op(2, SWITCH2, label), home / 'saves'), None)


def test_rom_not_in_the_library_restores_into_eden():
    with fake_home() as home:
        eden_save = nand_save(home, 'eden', SWITCH2)
        lichii_save = nand_save(home, 'lichii', SWITCH2)
        m = manager(home, [])
        check('an unlisted ROM restores as before',
              m._restore_standalone_save(op(9, SWITCH2, 'Lichii'), 'dev', None), True)
        check('...into Eden', read(eden_save), b'SERVER')
        check('...leaving Lichii alone', read(lichii_save), b'LOCAL')


def test_awaiting_restore_is_kept_per_emulator():
    with fake_home() as home:
        # Neither emulator has booted the game, and neither has a user yet.
        (home / '.local/share/eden/nand/user/save').mkdir(parents=True)
        (home / '.local/share/lichii/nand/user/save').mkdir(parents=True)
        m = manager(home, [game(1, 'switch'), game(2, 'switch-2')])
        check('Eden refuses before first boot',
              m._restore_standalone_save(op(1, SWITCH1, 'Eden'), 'dev', None), False)
        check('Lichii refuses before first boot',
              m._restore_standalone_save(op(2, SWITCH1, 'Lichii'), 'dev', None), False)
        check('Eden owes its own', m._eden_awaiting_restore()[SWITCH1]['rom_id'], 1)
        check('Lichii owes its own',
              m._eden_awaiting_restore(LICHII)[SWITCH1]['rom_id'], 2)
        check("Eden's file keeps its name",
              (home / 'cache' / 'eden_awaiting_restore.json').is_file(), True)

        # First boot in Lichii: the restore lands and clears only Lichii's key.
        lichii_save = nand_save(home, 'lichii', SWITCH1, b'FIRST BOOT')
        check('Lichii restores after first boot',
              m._restore_standalone_save(op(2, SWITCH1, 'Lichii'), 'dev', None), True)
        check('...over the first-boot save', read(lichii_save), b'SERVER')
        check('...clearing only its own key',
              (SWITCH1 in m._eden_awaiting_restore(),
               SWITCH1 in m._eden_awaiting_restore(LICHII)), (True, False))


def test_lichii_upload_honours_its_awaiting_restore():
    with fake_home() as home:
        m = manager(home, [game(2, 'switch-2')])
        m._rom_id_for_title_id = lambda t: 2
        m._title_id_index = {}
        m._title_id_candidates = {}
        nand_save(home, 'lichii', SWITCH2, b'FIRST BOOT')
        m._set_eden_awaiting_restore(SWITCH2, op(2, SWITCH2, 'Lichii'), variant=LICHII)
        m._eden_restore_still_owed = (
            lambda title, entry, variant=None: True)
        check('a first-boot Lichii save is held back', m._eden_inventory_entries(), [])
        m._set_eden_awaiting_restore(SWITCH2, variant=LICHII)
        check('...and uploads once nothing is owed',
              [r['emulator'] for r in m._eden_inventory_entries()], ['Lichii'])

        # An Eden hold on the same title does not hold Lichii's save back.
        m._set_eden_awaiting_restore(SWITCH2, op(2, SWITCH2, 'Eden'))
        check("...nor does Eden's hold on the same title",
              [r['emulator'] for r in m._eden_inventory_entries()], ['Lichii'])


def test_previous_save_is_backed_up():
    with fake_home() as home:
        lichii_save = nand_save(home, 'lichii', SWITCH2, b'MINE')
        m = manager(home, [game(2, 'switch-2')])
        check('restores', m._restore_standalone_save(op(2, SWITCH2, 'Lichii'), 'dev', None),
              True)
        backups = list((home / 'cache' / 'save_backups' / 'lichii').glob(f'{SWITCH2}-*.zip'))
        check('the previous save is backed up', len(backups), 1)
        with zipfile.ZipFile(backups[0]) as z:
            check('...with its contents', z.read(f'{SWITCH2}/Autosave.save'), b'MINE')
        check('the new save is in place', read(lichii_save), b'SERVER')


def test_failed_restore_leaves_the_original():
    with fake_home() as home:
        lichii_save = nand_save(home, 'lichii', SWITCH2, b'MINE')
        empty = home / 'empty.zip'
        with zipfile.ZipFile(empty, 'w'):
            pass
        m = manager(home, [game(2, 'switch-2')], pack=empty)
        check('an empty pack does not restore',
              m._restore_standalone_save(op(2, SWITCH2, 'Lichii'), 'dev', None), False)
        check('...the original is in place', read(lichii_save), b'MINE')
        check('...with nothing left beside it',
              sorted(p.name for p in lichii_save.parent.iterdir()), [SWITCH2])
        check('...and nothing recorded', m.romm_client.confirmed, [])


def test_running_lichii_refuses_only_lichii():
    with fake_home() as home, patch.object(E, 'lichii_is_running', lambda *a, **k: True):
        lichii_save = nand_save(home, 'lichii', SWITCH2, b'MINE')
        eden_save = nand_save(home, 'eden', SWITCH1, b'MINE')
        m = manager(home, [game(1, 'switch'), game(2, 'switch-2')])
        check('a running Lichii refuses',
              m._restore_standalone_save(op(2, SWITCH2, 'Lichii'), 'dev', None), False)
        check('...leaving its save', read(lichii_save), b'MINE')
        check('Eden still restores',
              m._restore_standalone_save(op(1, SWITCH1, 'Eden'), 'dev', None), True)
        check('...into Eden', read(eden_save), b'SERVER')


def main():
    test_restores_under_the_profiles_lichii_user()
    test_routing_not_the_label_picks_the_tree()
    test_switch2_saves_never_take_the_retroarch_path()
    test_rom_not_in_the_library_restores_into_eden()
    test_awaiting_restore_is_kept_per_emulator()
    test_lichii_upload_honours_its_awaiting_restore()
    test_previous_save_is_backed_up()
    test_failed_restore_leaves_the_original()
    test_running_lichii_refuses_only_lichii()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all Lichii restore checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
