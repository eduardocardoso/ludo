"""The Eden-family emulator descriptor, as Eden uses it.

Run with `python3 engine/tests/test_eden_family.py`. No emulator required:
homes and /proc trees are synthesised in temp directories.

Eden's record must hold exactly the values Eden used before the descriptor
existed: paths, Profile key, settings key and the `Eden` label are what
existing installs and profiles.json files already depend on.
"""

import dataclasses
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import eden_family  # noqa: E402
from romm_sync_engine import eden_config as C  # noqa: E402
from romm_sync_engine import eden_users as U  # noqa: E402
from romm_sync_engine import emulator_saves as E  # noqa: E402
from romm_sync_engine import paths, profiles as P  # noqa: E402
from romm_sync_engine.eden_family import EDEN, EdenVariant  # noqa: E402

FAILURES = []

# A second Eden-family emulator that exists only in this test, so the
# emulator parameter can be seen steering each lookup away from Eden.
OTHER = dataclasses.replace(
    EDEN,
    key='otheremu',
    name='OtherEmu',
    data_dirs=('~/.local/share/otheremu',),
    config_dirs=('~/.config/otheremu',),
    data_dir_env='OTHEREMU_DATA_DIR',
    settings_key='otheremu_data_dir',
    profile_key='otheremu_user',
    process_names=('otheremu',),
    default_user_name='OtherEmu',
)


@contextmanager
def fake_home():
    with tempfile.TemporaryDirectory() as tmp, \
            patch.dict(os.environ, {'HOME': tmp, 'XDG_CONFIG_HOME': f'{tmp}/.config'}):
        os.environ.pop('EDEN_DATA_DIR', None)
        os.environ.pop('OTHEREMU_DATA_DIR', None)
        yield Path(tmp)


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")


def test_eden_record_holds_todays_values():
    check('key', EDEN.key, 'eden')
    check('name (Emulator label)', EDEN.name, 'Eden')
    check('data dirs', EDEN.data_dirs, (
        '~/.var/app/dev.eden_emu.eden/data/eden',
        '~/.local/share/eden',
    ))
    check('config dirs', EDEN.config_dirs, (
        '~/.var/app/dev.eden_emu.eden/config/eden',
        '~/.config/eden',
    ))
    check('data dir env', EDEN.data_dir_env, 'EDEN_DATA_DIR')
    check('settings key', EDEN.settings_key, 'eden_data_dir')
    check('profile key', EDEN.profile_key, 'eden_user')
    check('process names', EDEN.process_names, ('eden',))
    check('default user name', EDEN.default_user_name, 'Eden')


def test_module_constants_are_edens_record():
    check('EDEN_DATA_DIRS', E.EDEN_DATA_DIRS, EDEN.data_dirs)
    check('EDEN_CONFIG_DIRS', C.EDEN_CONFIG_DIRS, EDEN.config_dirs)


def test_eden_is_the_first_variant():
    check('eden first', eden_family.VARIANTS[0], EDEN)


def test_descriptor_is_immutable():
    try:
        EDEN.name = 'Other'
        frozen = False
    except dataclasses.FrozenInstanceError:
        frozen = True
    check('frozen', frozen, True)
    check('is EdenVariant', isinstance(EDEN, EdenVariant), True)


def _fake_proc(root, processes):
    """A /proc tree: {pid: (comm, state letter)}."""
    for pid, (comm, state) in processes.items():
        entry = root / str(pid)
        entry.mkdir(parents=True)
        (entry / 'comm').write_text(comm + '\n')
        (entry / 'status').write_text(f"Name:\t{comm}\nState:\t{state} (x)\n")


def test_process_scan_finds_eden_in_a_fake_proc_tree():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_proc(root, {
            101: ('eden', 'S'),
            102: ('eden.appimage', 'R'),
            103: ('eden', 'Z'),       # quit, not yet reaped: not running
            104: ('Cemu', 'S'),
            105: ('bash', 'S'),
        })
        (root / 'self').mkdir()      # non-pid entries are skipped
        (root / 'self' / 'comm').write_text('eden\n')
        check('eden pids', sorted(E.eden_pids(proc_root=root)), [101, 102])
        check('eden running', E.eden_is_running(proc_root=root), True)
        check('scan by prefix', sorted(E._pids_named('cemu', proc_root=root)), [104])


def test_process_scan_with_no_eden():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_proc(root, {201: ('eden', 'Z'), 202: ('bash', 'S')})
        check('no eden pids', E.eden_pids(proc_root=root), [])
        check('eden not running', E.eden_is_running(proc_root=root), False)
        check('missing proc root', E.eden_pids(proc_root=root / 'absent'), [])


def test_data_dirs_default_to_eden():
    with fake_home() as home:
        eden = home / '.local/share/eden'
        other = home / '.local/share/otheremu'
        eden.mkdir(parents=True)
        other.mkdir(parents=True)
        check('default', E.eden_data_dirs(), [eden])
        check('other', E.eden_data_dirs(variant=OTHER), [other])
        check('extra stays exclusive', E.eden_data_dirs(home / 'nope', variant=OTHER), [])
        env = home / 'elsewhere'
        env.mkdir()
        os.environ['OTHEREMU_DATA_DIR'] = str(env)
        check('other env first', E.eden_data_dirs(variant=OTHER), [env, other])
        check('eden ignores other env', E.eden_data_dirs(), [eden])


def test_launch_data_dir_defaults_to_eden():
    with fake_home() as home:
        check('eden native', E.eden_data_dir_for('/usr/bin/eden'),
              home / '.local/share/eden')
        check('eden flatpak', E.eden_data_dir_for('flatpak:dev.eden_emu.eden'),
              home / '.var/app/dev.eden_emu.eden/data/eden')
        check('other native', E.eden_data_dir_for('/opt/otheremu', variant=OTHER),
              home / '.local/share/otheremu')
        os.environ['OTHEREMU_DATA_DIR'] = str(home / 'env')
        check('other env', E.eden_data_dir_for('/opt/otheremu', variant=OTHER),
              home / 'env')


def test_config_reading_defaults_to_eden():
    with fake_home() as home:
        for folder, user in (('eden', '1'), ('otheremu', '3')):
            ini = home / '.config' / folder / 'qt-config.ini'
            ini.parent.mkdir(parents=True)
            ini.write_text(f'[System]\ncurrent_user={user}\n')
        check('eden config', C.config_path(), home / '.config/eden/qt-config.ini')
        check('other config', C.config_path(variant=OTHER),
              home / '.config/otheremu/qt-config.ini')
        check('eden setting', C._setting('[System]', 'current_user'), '1')
        check('other setting',
              C._setting('[System]', 'current_user', variant=OTHER), '3')


def test_new_user_list_is_named_after_the_emulator():
    with fake_home() as home:
        eden, other = home / 'eden', home / 'other'
        check('eden written', U.create_default(eden), True)
        check('other written', U.create_default(other, variant=OTHER), True)
        check('eden user', [u['name'] for u in U.users(eden)], ['Eden'])
        check('other user', [u['name'] for u in U.users(other)], ['OtherEmu'])


@contextmanager
def profiles_in_use(home):
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


def test_profile_users_default_to_eden():
    with fake_home() as home, profiles_in_use(home), \
            patch.object(E, 'eden_is_running', return_value=False):
        eden = home / '.local/share/eden'
        other = home / '.local/share/otheremu'
        U.create_default(eden)
        U.create_default(other, variant=OTHER)
        ini = home / '.config/otheremu/qt-config.ini'
        ini.parent.mkdir(parents=True)
        ini.write_text('[System]\ncurrent_user=0\n')
        mia = P.create('Mia')

        # The default Profile keeps each emulator's selected user, stored
        # under that emulator's own Profile key.
        eden_first = U.users(eden)[0]['uuid']
        other_first = U.users(other)[0]['uuid']
        check('default eden user', P.eden_user()['uuid'], eden_first)
        check('default other user', P.eden_user(variant=OTHER)['uuid'], other_first)
        entry = P.get(P.load(), P.DEFAULT)
        check('stored keys', (entry.get('eden_user'), entry.get('otheremu_user')),
              (eden_first, other_first))

        # Another Profile gets its own user in the emulator asked for only.
        use(mia)
        mine = P.eden_user(create=True, variant=OTHER)
        check('mia added to other', [u['name'] for u in U.users(other)],
              ['OtherEmu', 'Mia'])
        check('eden list untouched', [u['name'] for u in U.users(eden)], ['Eden'])
        check('mia stored under other key',
              P.get(P.load(), mia).get('otheremu_user'), mine['uuid'])
        check('mia has no eden user yet', P.get(P.load(), mia).get('eden_user'), None)
        check('launch index', P.eden_launch_index(other, variant=OTHER), 1)


def test_profile_errors_name_the_emulator():
    with fake_home() as home, profiles_in_use(home):
        P.create('Mia')
        check('eden', P.eden_user(),
              {'error': 'Start Eden once so it creates its user list'})
        check('other', P.eden_user(variant=OTHER),
              {'error': 'Start OtherEmu once so it creates its user list'})


def main():
    for test in (
        test_eden_record_holds_todays_values,
        test_module_constants_are_edens_record,
        test_eden_is_the_first_variant,
        test_descriptor_is_immutable,
        test_process_scan_finds_eden_in_a_fake_proc_tree,
        test_process_scan_with_no_eden,
        test_data_dirs_default_to_eden,
        test_launch_data_dir_defaults_to_eden,
        test_config_reading_defaults_to_eden,
        test_new_user_list_is_named_after_the_emulator,
        test_profile_users_default_to_eden,
        test_profile_errors_name_the_emulator,
    ):
        print(f"-- {test.__name__}")
        test()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s): {FAILURES}")
        return 1
    print("\nall passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
