"""Eden and Lichii saves are found where the emulator really keeps them.

Each Eden-family emulator names two folders in [Data Storage] of its own
qt-config.ini: save_directory (the root of every game save) and
nand_directory (the NAND root, which holds the user list). Both default to
<data dir>/nand/. A yuzu import, or a move in the emulator's settings, points
them elsewhere.

Run with `python3 engine/tests/test_emulator_save_folders.py`. Every test runs
under a fake HOME: this machine may have a real Eden or Lichii.
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
from romm_sync_engine.eden_family import EDEN, LICHII  # noqa: E402
from romm_sync_engine.sync_core import AutoSyncManager  # noqa: E402

FAILURES = []

SWITCH2 = '0400486024DEC000'
SWITCH1 = '0100000000010000'
USER = 'A' * 32  # an Emulator user's save folder
PROFILES = Path('system/save/8000000000000010/su/avators/profiles.dat')


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")


@contextmanager
def fake_home():
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


def data_dir(home, emulator):
    return home / '.local' / 'share' / emulator


def write_config(home, emulator, storage, config_dir=None):
    """qt-config.ini laid out as the emulator writes it: a percent-escaped
    section, and a ``\\default`` shadow beside each key."""
    folder = config_dir or home / '.config' / emulator
    folder.mkdir(parents=True, exist_ok=True)
    lines = ['[UI]', 'theme=default', '', '[Data%20Storage]',
             'dump_directory=' + str(home / f'.local/share/{emulator}/dump/'),
             'dump_directory\\default=false']
    for key, (value, default) in storage.items():
        lines.append(f'{key}={value}')
        lines.append(f'{key}\\default={"true" if default else "false"}')
    lines += ['ext_content_from_game_dirs\\default=true', '', '[System]',
              'current_user=0', '']
    (folder / 'qt-config.ini').write_text('\n'.join(lines))


def real_case(home, emulator):
    """The machine this was found on: a yuzu import moved save_directory to
    yuzu's NAND, and nand_directory stayed in the emulator's own data dir."""
    yuzu = home / '.local/share/yuzu/nand'
    own = data_dir(home, emulator) / 'nand'
    yuzu.mkdir(parents=True)
    own.mkdir(parents=True)
    write_config(home, emulator, {
        'nand_directory': (f'{own}/', False),
        'save_directory': (f'{yuzu}/', False),
    })
    return yuzu


def save_in(root, title_id, data=b'LOCAL', user=USER):
    d = root / 'user' / 'save' / ('0' * 16) / user / title_id
    d.mkdir(parents=True)
    (d / 'Autosave.save').write_bytes(data)
    return d


def read(directory):
    try:
        return (directory / 'Autosave.save').read_bytes()
    except OSError:
        return None


def saves(variant):
    found = E.find_eden_saves() if variant is EDEN else E.find_eden_saves(variant=variant)
    return {s['title_id']: s['path'] for s in found}


def test_inventory_finds_the_save_in_the_save_directory():
    for variant, title in ((EDEN, SWITCH1), (LICHII, SWITCH2)):
        with fake_home() as home:
            yuzu = real_case(home, variant.key)
            stale = save_in(data_dir(home, variant.key) / 'nand', SWITCH1 if title == SWITCH2
                            else '0100000000020000', b'STALE')
            real = save_in(yuzu, title)
            found = saves(variant)
            check(f'{variant.name}: the save in save_directory is found',
                  found.get(title), real)
            check(f'{variant.name}: the stale <data dir>/nand tree is not read',
                  stale.name in found, False)


def kw(variant):
    return {} if variant is EDEN else {'variant': variant}


def test_users_are_read_from_the_nand_directory():
    for variant in (EDEN, LICHII):
        with fake_home() as home:
            moved = home / 'Games' / f'{variant.key} nand'
            moved.mkdir(parents=True)
            data = data_dir(home, variant.key)
            (data / 'nand').mkdir(parents=True)
            write_config(home, variant.key, {'nand_directory': (f'{moved}/', False)})
            check(f'{variant.name}: the user list is written to nand_directory',
                  U.create_default(data, **kw(variant)), True)
            check(f'{variant.name}: ...at profiles.dat under it',
                  (moved / 'system/save/8000000000000010/su/avators/profiles.dat').is_file(),
                  True)
            check(f'{variant.name}: ...not under <data dir>/nand',
                  (data / 'nand/system').exists(), False)
            check(f'{variant.name}: and read back from there',
                  [u['name'] for u in U.users(data, **kw(variant))],
                  [variant.default_user_name])


def test_profile_user_and_restore_follow_the_config():
    for variant, title in ((EDEN, SWITCH1), (LICHII, SWITCH2)):
        with fake_home() as home, profiles_in_use():
            yuzu = real_case(home, variant.key)
            data = data_dir(home, variant.key)
            U.create_default(data, **kw(variant))
            U.add(data, 'Mia', **kw(variant))
            mia = P.create('Mia')
            use(mia)
            user = P.eden_user(create=True, **kw(variant))
            check(f'{variant.name}: the profile adopts the user named after it',
                  [u['name'] for u in U.users(data, **kw(variant))
                   if u['save_dir'] == user.get('save_dir')], ['Mia'])
            check(f'{variant.name}: -u picks that user from nand_directory',
                  P.eden_launch_index(data, **kw(variant)), 1)
            target = E.eden_restore_dir(title, **kw(variant))
            check(f'{variant.name}: a restore targets save_directory',
                  target, yuzu / 'user/save' / ('0' * 16) / user['save_dir'] / title)


def manager(home, games, pack):
    m = AutoSyncManager.__new__(AutoSyncManager)
    m.get_games = lambda: games
    m.settings = type('S', (), {'get': lambda self, *a: ''})()
    m.log = lambda *a, **k: None

    class Client:
        base_url = 'http://romm'
        confirmed = []

        def download_save_by_id(self, save_id, kind, dest, device_id=None,
                                session_id=None):
            dest.write_bytes(Path(pack).read_bytes())
            return True

        def confirm_save_downloaded(self, save_id, kind, device_id, content_hash=None):
            self.confirmed.append(save_id)
            return True
    m.romm_client = Client()
    m.romm_client.session = m.romm_client
    return m


def test_sync_restores_and_backs_up_in_the_save_directory():
    for variant, slug, title in ((EDEN, 'switch', SWITCH1), (LICHII, 'switch-2', SWITCH2)):
        with fake_home() as home:
            yuzu = real_case(home, variant.key)
            mine = save_in(yuzu, title, b'MINE')
            pack = home / 'server.zip'
            with zipfile.ZipFile(pack, 'w') as z:
                z.writestr('Autosave.save', 'SERVER')
            m = manager(home, [{'rom_id': 2, 'platform_slug': slug}], pack)
            op = {'save_id': 41, 'rom_id': 2, 'file_name': f'{title}.zip',
                  'emulator': variant.name}
            check(f'{variant.name}: the sync restores',
                  m._restore_standalone_save(op, 'dev', None), True)
            check(f'{variant.name}: ...into save_directory', read(mine), b'SERVER')
            check(f'{variant.name}: ...nothing under <data dir>/nand/user',
                  (data_dir(home, variant.key) / 'nand/user').exists(), False)
            # Eden's backups keep their original folder; Lichii's have their own.
            folder = home / 'cache' / 'save_backups'
            if variant is not EDEN:
                folder = folder / variant.key
            backups = list(folder.glob(f'{title}-*.zip'))
            check(f'{variant.name}: the replaced save is backed up', len(backups), 1)


def test_inventory_uploads_the_save_from_the_save_directory():
    for variant, slug, title in ((EDEN, 'switch', SWITCH1), (LICHII, 'switch-2', SWITCH2)):
        with fake_home() as home:
            yuzu = real_case(home, variant.key)
            save_in(yuzu, title, b'MINE')
            m = manager(home, [{'rom_id': 2, 'platform_slug': slug}], home / 'none')
            m._rom_id_for_title_id = lambda t: 2
            m._title_id_index = {}
            m._title_id_candidates = {}
            rows = m._eden_inventory_entries()
            check(f'{variant.name}: the inventory lists the save',
                  [(r['emulator'], r['rom_id']) for r in rows], [(variant.name, 2)])


def test_defaults_are_unchanged_without_the_keys():
    for variant, title in ((EDEN, SWITCH1), (LICHII, SWITCH2)):
        for label in ('no config', 'no keys', 'keys at their default', 'empty values'):
            with fake_home() as home:
                data = data_dir(home, variant.key)
                elsewhere = home / 'elsewhere'
                elsewhere.mkdir()
                storage = {
                    'no config': None,
                    'no keys': {},
                    'keys at their default': {'save_directory': (f'{elsewhere}/', True),
                                              'nand_directory': (f'{elsewhere}/', True)},
                    'empty values': {'save_directory': ('', False),
                                     'nand_directory': ('', False)},
                }[label]
                if storage is not None:
                    write_config(home, variant.key, storage)
                save = save_in(data / 'nand', title)
                U.create_default(data, **kw(variant))
                check(f'{variant.name}, {label}: saves from <data dir>/nand',
                      saves(variant).get(title), save)
                check(f'{variant.name}, {label}: users in <data dir>/nand',
                      (data / 'nand' / PROFILES).is_file(), True)


def test_qt_value_forms():
    for variant, title in ((EDEN, SWITCH1), (LICHII, SWITCH2)):
        for label, value in (('~ and a trailing slash', '~/My Saves/'),
                             ('no trailing slash', '{home}/My Saves'),
                             ('quoted', '"{home}/My Saves/"'),
                             ('Qt-escaped', '{home}/My\\x20Saves/')):
            with fake_home() as home:
                root = home / 'My Saves'
                root.mkdir()
                (data_dir(home, variant.key) / 'nand').mkdir(parents=True)
                write_config(home, variant.key,
                             {'save_directory': (value.format(home=home), False)})
                save = save_in(root, title)
                check(f'{variant.name}, {label}: the save is found',
                      saves(variant).get(title), save)


def test_missing_folder_falls_back_with_a_warning():
    for variant, title in ((EDEN, SWITCH1), (LICHII, SWITCH2)):
        with fake_home() as home:
            data = data_dir(home, variant.key)
            write_config(home, variant.key, {
                'save_directory': (f'{home}/gone/', False),
                'nand_directory': (f'{home}/gone too/', False)})
            save = save_in(data / 'nand', title)
            with patch.object(E.eden_storage.log, 'warning') as warned:
                found = saves(variant).get(title)
                U.create_default(data, **kw(variant))
            logged = ' '.join(str(c) for c in warned.call_args_list)
            check(f'{variant.name}: a missing save_directory falls back', found, save)
            check(f'{variant.name}: ...and so does a missing nand_directory',
                  (data / 'nand' / PROFILES).is_file(), True)
            check(f'{variant.name}: ...each logged',
                  ('gone/' in logged or "gone'" in logged, 'gone too' in logged),
                  (True, True))


def test_eden_flatpak_reads_its_own_config():
    with fake_home() as home:
        flatpak = home / '.var/app/dev.eden_emu.eden'
        (flatpak / 'data/eden/nand').mkdir(parents=True)
        moved = home / 'flatpak saves'
        moved.mkdir()
        write_config(home, 'eden', {'save_directory': (f'{moved}/', False)},
                     config_dir=flatpak / 'config/eden')
        # The native config names another folder; it is not the flatpak's.
        native = home / 'native saves'
        native.mkdir()
        write_config(home, 'eden', {'save_directory': (f'{native}/', False)})
        save = save_in(moved, SWITCH1)
        save_in(native, '0100000000020000')
        found = saves(EDEN)
        check("the flatpak Eden's save comes from the flatpak config's folder",
              found.get(SWITCH1), save)
        check("...not from the native config's", '0100000000020000' in found, False)


def test_data_folder_setting_and_env_keep_their_meaning():
    with fake_home() as home:
        # The env var moves the native data dir; the native config still
        # belongs to it, so its save_directory still wins.
        custom = home / 'lichii data'
        (custom / 'nand').mkdir(parents=True)
        yuzu = home / '.local/share/yuzu/nand'
        yuzu.mkdir(parents=True)
        write_config(home, 'lichii', {'save_directory': (f'{yuzu}/', False)})
        save = save_in(yuzu, SWITCH2)
        stale = save_in(custom / 'nand', '0400000000010000')
        with patch.dict(os.environ, {'LICHII_DATA_DIR': str(custom)}):
            found = saves(LICHII)
        check('with the env var, save_directory still wins', found.get(SWITCH2), save)
        check('...over <env dir>/nand', stale.name in found, False)

        # Ludo's setting naming the install's own data dir: the same answer.
        native = data_dir(home, 'lichii')
        (native / 'nand').mkdir(parents=True)
        found = {s['title_id']: s['path']
                 for s in E.find_eden_saves(str(native), variant=LICHII)}
        check("with the setting on the install's data dir, save_directory wins",
              found.get(SWITCH2), save)

        # A setting naming a folder no install owns has no config to read.
        found = {s['title_id']: s['path']
                 for s in E.find_eden_saves(str(custom), variant=LICHII)}
        check('a folder no install owns keeps <folder>/nand',
              found.get('0400000000010000'), stale)


def main():
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    print('\nall passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
