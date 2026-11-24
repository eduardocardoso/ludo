"""Lichii plays as the Profile's own Emulator user, as Eden does.

Run with `python3 engine/tests/test_lichii_users.py`. No emulator required:
every test runs under a fake HOME (this machine may have a real Lichii) and
/proc trees are synthesised in temp directories.
"""

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
from romm_sync_engine.eden_family import EDEN, LICHII  # noqa: E402

FAILURES = []


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


def test_lichii_record():
    check('key', LICHII.key, 'lichii')
    check('name (Emulator label)', LICHII.name, 'Lichii')
    check('data dirs', LICHII.data_dirs, ('~/.local/share/lichii',))
    check('config dirs', LICHII.config_dirs, ('~/.config/lichii',))
    check('data dir env', LICHII.data_dir_env, 'LICHII_DATA_DIR')
    check('settings key', LICHII.settings_key, 'lichii_data_dir')
    check('profile key', LICHII.profile_key, 'lichii_user')
    check('process names', LICHII.process_names, ('lichii',))
    check('variants', eden_family.VARIANTS, (EDEN, LICHII))
    check('variant for lichii', eden_family.variant_for_key('lichii'), LICHII)
    check('variant for eden', eden_family.variant_for_key('eden'), EDEN)
    check('cemu is not Eden-family', eden_family.variant_for_key('cemu'), None)


def _fake_proc(root, processes):
    """A /proc tree: {pid: (comm, state letter)}."""
    for pid, (comm, state) in processes.items():
        entry = root / str(pid)
        entry.mkdir(parents=True)
        (entry / 'comm').write_text(comm + '\n')
        (entry / 'status').write_text(f"Name:\t{comm}\nState:\t{state} (x)\n")


def test_eden_and_lichii_are_never_mistaken_for_each_other():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # comm is cut to 15 characters, hence 'lichii-linux-x8'.
        _fake_proc(root, {
            1: ('eden', 'S'), 2: ('eden.appimage', 'S'),
            3: ('lichii', 'S'), 4: ('lichii.appimage', 'R'), 5: ('lichii-linux-x8', 'S'),
            6: ('lichii', 'Z'), 7: ('bash', 'S'),
        })
        check('eden pids', sorted(E.eden_pids(EDEN, root)), [1, 2])
        check('lichii pids', sorted(E.eden_pids(LICHII, root)), [3, 4, 5])
        check('lichii running', E.lichii_is_running(proc_root=root), True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_proc(root, {1: ('eden', 'S'), 2: ('eden.appimage', 'S')})
        check('eden alone is not lichii', E.eden_is_running(LICHII, root), False)
        check('eden alone: lichii_is_running', E.lichii_is_running(proc_root=root), False)
        check('eden alone is eden', E.eden_is_running(EDEN, root), True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_proc(root, {3: ('lichii', 'S'), 4: ('lichii.appimage', 'S')})
        check('lichii alone is not eden', E.eden_is_running(EDEN, root), False)
        check('lichii alone is lichii', E.eden_is_running(LICHII, root), True)


def test_lichii_check_survives_narrow_eden_stubs():
    """Tests stub eden_is_running / eden_pids with no-argument lambdas; the
    Lichii check must not go through them."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_proc(root, {3: ('lichii', 'S')})
        with patch.object(E, 'eden_is_running', lambda: False), \
                patch.object(E, 'eden_pids', lambda: []):
            check('lichii seen', E.lichii_is_running(proc_root=root), True)


class _Settings:
    def __init__(self, emulators=None):
        self.emulators = emulators

    def get(self, section, key, default=None):
        if section != 'Emulators' or self.emulators is None:
            raise KeyError(section)      # a config without the section
        return self.emulators.get(key, default)


def test_data_folder_resolves_setting_then_env_then_default():
    with fake_home() as home:
        default = home / '.local/share/lichii'
        env = home / 'env-lichii'
        chosen = home / 'chosen-lichii'
        for d in (default, env, chosen):
            d.mkdir(parents=True)
        (home / '.local/share/eden').mkdir(parents=True)

        def resolve(settings):
            return E.eden_data_dirs(E.data_dir_setting(settings, LICHII), variant=LICHII)

        check('default', resolve(_Settings({})), [default])
        check('no [Emulators] section', resolve(_Settings()), [default])
        check('eden setting ignored', resolve(_Settings({'eden_data_dir': str(env)})), [default])
        os.environ['LICHII_DATA_DIR'] = str(env)
        check('env before default', resolve(_Settings({})), [env, default])
        check('setting wins', resolve(_Settings({'lichii_data_dir': f' {chosen} '})), [chosen])
        check('eden reads its own key',
              E.data_dir_setting(_Settings({'eden_data_dir': 'x', 'lichii_data_dir': 'y'})), 'x')
        check('blank setting is none', E.data_dir_setting(_Settings({'lichii_data_dir': ' '}), LICHII), None)


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


def running(*variants):
    """An eden_is_running stand-in: True only for ``variants``."""
    return lambda variant=EDEN, proc_root=None: variant in variants


def write_config(home, folder, text):
    ini = home / '.config' / folder / 'qt-config.ini'
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text(text)
    return ini


def test_user_list_round_trip_in_a_fake_lichii_folder():
    with fake_home() as home:
        data = home / '.local/share/lichii'
        check('created', U.create_default(data, variant=LICHII), True)
        check('kept', U.create_default(data, variant=LICHII), False)
        uuid = U.add(data, 'Mia')
        listed = U.users(data)
        check('names', [u['name'] for u in listed], ['Lichii', 'Mia'])
        check('found', U.find(data, uuid)['index'], 1)
        check('nothing under eden', (home / '.local/share/eden').exists(), False)


def test_default_profile_keeps_lichiis_selected_user():
    with fake_home() as home, profiles_in_use(), \
            patch.object(E, 'eden_is_running', running()):
        eden, lichii = home / '.local/share/eden', home / '.local/share/lichii'
        U.create_default(eden)
        U.create_default(lichii, variant=LICHII)
        U.add(eden, 'eden second')
        U.add(lichii, 'lichii second')
        # Each emulator has a different user selected: the default Profile
        # must follow Lichii's own config, not Eden's.
        write_config(home, 'eden', '[System]\ncurrent_user=0\n')
        write_config(home, 'lichii', '[System]\ncurrent_user=1\n')
        P.create('Mia')
        user = P.eden_user(variant=LICHII)
        check('lichii selected user', user['uuid'], U.users(lichii)[1]['uuid'])
        entry = P.get(P.load(), P.DEFAULT)
        check('stored under lichii_user', entry.get('lichii_user'), user['uuid'])
        check('eden_user untouched', entry.get('eden_user'), None)


def test_profile_gets_its_own_lichii_user_on_first_play():
    with fake_home() as home, profiles_in_use(), \
            patch.object(E, 'eden_is_running', running()):
        eden, lichii = home / '.local/share/eden', home / '.local/share/lichii'
        U.create_default(eden)
        write_config(home, 'lichii', '[System]\ncurrent_user=0\n')
        mia = P.create('Mia')
        use(mia)
        # Lichii never started: Ludo writes its user list itself.
        index = P.eden_launch_index(lichii, variant=LICHII)
        check('lichii users', [u['name'] for u in U.users(lichii)], ['Lichii', 'Mia'])
        check('launch index', index, 1)
        entry = P.get(P.load(), mia)
        check('lichii_user stored', entry.get('lichii_user'), U.users(lichii)[1]['uuid'])
        check('eden_user untouched', entry.get('eden_user'), None)
        check('eden list untouched', [u['name'] for u in U.users(eden)], ['Eden'])


def test_no_user_list_write_while_lichii_runs():
    with fake_home() as home, profiles_in_use():
        lichii = home / '.local/share/lichii'
        mia = P.create('Mia')
        use(mia)
        with patch.object(E, 'eden_is_running', running(LICHII)):
            # No user list yet, and Lichii running: none is created.
            check('no first list', P.eden_launch_index(lichii, variant=LICHII), None)
            check('file absent', U.profiles_file(lichii).exists(), False)
            U.create_default(lichii, variant=LICHII)
            before = U.profiles_file(lichii).read_bytes()
            check('refused', P.eden_user(create=True, variant=LICHII),
                  {'error': 'Close Lichii so Ludo can add this profile as a Lichii user'})
            check('list unchanged', U.profiles_file(lichii).read_bytes(), before)
        # A running Eden does not block Lichii.
        with patch.object(E, 'eden_is_running', running(EDEN)):
            check('added once lichii is closed',
                  [u['name'] for u in U.users(lichii)] if P.eden_user(create=True, variant=LICHII) else None,
                  ['Lichii', 'Mia'])


def test_lichii_launch_passes_the_profile_user():
    from romm_sync_engine.sync_core import RetroArchInterface, STANDALONE_EMULATORS
    with fake_home() as home, profiles_in_use(), \
            patch.object(E, 'eden_is_running', running()), \
            patch.object(C, 'eden_is_running', running()):
        lichii = home / '.local/share/lichii'
        U.create_default(lichii, variant=LICHII)
        on = '[System]\ncurrent_user=0\n[UI]\nselect_user_on_boot\\default=false\nselect_user_on_boot=true\n'
        lichii_ini = write_config(home, 'lichii', on)
        eden_ini = write_config(home, 'eden', on)
        mia = P.create('Mia')
        use(mia)
        ra = RetroArchInterface.__new__(RetroArchInterface)
        exe = str(home / 'AppImages/lichii.appimage')
        rom = str(home / 'roms/game.nsp')
        argv = ra.build_standalone_launch_command(rom, 'lichii', STANDALONE_EMULATORS['lichii'], exe)
        check('argv', argv, [exe, '-u', '1', '-f', '-g', rom])
        check('lichii picker off', 'select_user_on_boot=false' in lichii_ini.read_text().splitlines(), True)
        check('eden config untouched', eden_ini.read_text(), on)
        check('lichii_user stored', bool(P.get(P.load(), mia).get('lichii_user')), True)
        check('eden_user untouched', P.get(P.load(), mia).get('eden_user'), None)


def test_lichii_launch_without_profiles_is_unchanged():
    from romm_sync_engine.sync_core import RetroArchInterface, STANDALONE_EMULATORS
    with fake_home() as home:
        ra = RetroArchInterface.__new__(RetroArchInterface)
        argv = ra.build_standalone_launch_command('/r/g.nsp', 'lichii', STANDALONE_EMULATORS['lichii'], '/x/lichii')
        check('argv', argv, ['/x/lichii', '-f', '-g', '/r/g.nsp'])
        check('nothing written', list(home.iterdir()), [])


def _manager():
    from romm_sync_engine import sync_core
    m = sync_core.AutoSyncManager.__new__(sync_core.AutoSyncManager)
    m.logged, m.synced = [], []
    m.log = m.logged.append
    m.trigger_session_save_sync = m.synced.append
    return m


def test_lichii_is_watched_like_eden():
    with patch.object(E, 'eden_is_running', lambda: False), \
            patch.object(E, 'cemu_is_running', lambda: False), \
            patch.object(E, 'lichii_is_running', lambda: True):
        m = _manager()
        now = m._standalone_emulators_running()
    check('lichii running, eden not', (now.get('Lichii'), now.get('Eden')), (True, False))
    check('counts as a game running', any(now.values()), True)

    m = _manager()
    idle = {'Eden': False, 'Lichii': False, 'Cemu': False}
    was = m._note_standalone_transitions(idle, dict(idle, Lichii=True))
    check('launch logged', m.logged, ['\U0001f3ae Lichii launched'])
    check('no sync on launch', m.synced, [])
    m._note_standalone_transitions(was, idle)
    check('close logged', m.logged[-1], '\U0001f3ae Lichii closed')
    check('close -> sync', m.synced, ['Lichii closed'])

    m = _manager()
    m._note_standalone_transitions(dict(idle, Eden=True), idle)
    check('eden close still syncs as Eden', m.synced, ['Eden closed'])


def test_play_watch_sees_lichii():
    import time
    seen = []
    m = _manager()
    m.play_sessions = type('P', (), {'observe': lambda self, r: seen.append(r)})()
    m._monitor_beat = 0.0
    m._play_watch = None
    m.is_retroarch_running = lambda: False
    with patch.object(E, 'eden_is_running', lambda: False), \
            patch.object(E, 'cemu_is_running', lambda: False), \
            patch.object(E, 'lichii_is_running', lambda: True):
        m.start_play_watch()
        time.sleep(1.5)
        m._monitor_beat = time.time() + 600   # park the watcher
    check('observed lichii as running', bool(seen) and all(seen), True)


def main():
    for test in (
        test_lichii_record,
        test_eden_and_lichii_are_never_mistaken_for_each_other,
        test_lichii_check_survives_narrow_eden_stubs,
        test_data_folder_resolves_setting_then_env_then_default,
        test_user_list_round_trip_in_a_fake_lichii_folder,
        test_default_profile_keeps_lichiis_selected_user,
        test_profile_gets_its_own_lichii_user_on_first_play,
        test_no_user_list_write_while_lichii_runs,
        test_lichii_launch_passes_the_profile_user,
        test_lichii_launch_without_profiles_is_unchanged,
        test_lichii_is_watched_like_eden,
        test_play_watch_sees_lichii,
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
