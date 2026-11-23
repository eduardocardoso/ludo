"""Lichii (Nintendo Switch 2) as a standalone emulator, next to Eden (Switch).

Run with `python3 engine/tests/test_lichii_standalone.py`.

Routing used to match platform tokens by substring, so "Nintendo Switch 2"
and `switch-2` both contained "switch" and went to Eden, which can't run them.
Routing is now an exact lookup the backend owns and ships to the UI.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import sync_core  # noqa: E402
from romm_sync_engine.sync_core import (  # noqa: E402
    RetroArchInterface, STANDALONE_EMULATORS, find_standalone_builds,
    find_standalone_executable, standalone_emulator_for_platform,
    standalone_routes)

FAILED = []


def check(name, got, want):
    ok = got == want
    print('ok  ' if ok else 'FAIL', name, '' if ok else f'\n   got  {got!r}\n   want {want!r}')
    if not ok:
        FAILED.append(name)


def touch(path, exec_=False, size=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)
    if exec_:
        path.chmod(0o755)
    return path


def routed(name, slug=None):
    got = standalone_emulator_for_platform(name, slug)
    return got and got[0]


def test_routing():
    # Switch stays Eden's, whatever RomM calls it.
    for name, slug in (('Nintendo Switch', 'switch'), ('Nintendo - Switch', None),
                       ('nintendo switch', None), ('Switch', None),
                       (None, 'switch'), (None, 'nintendo-switch'),
                       ('x', 'switch'), ('switch', None)):
        check(f'{name!r}/{slug!r} -> eden', routed(name, slug), 'eden')
    # Switch 2 is Lichii's, and never Eden's.
    for name, slug in (('Nintendo Switch 2', 'switch-2'), ('Nintendo Switch 2', None),
                       ('Nintendo - Switch 2', None), ('NINTENDO SWITCH 2', None),
                       ('Switch 2', None), (None, 'switch-2'), ('x', 'switch-2'),
                       # Two callers pass a slug in the name position.
                       ('switch-2', None), ('Nintendo Switch', 'switch-2')):
        check(f'{name!r}/{slug!r} -> lichii', routed(name, slug), 'lichii')
    # Exact means exact: nothing that merely contains "switch" is routed.
    for name, slug in (('Nintendo Switch 3', None), ('Switch Online', None),
                       ('Nintendo Switch 2 Demo', None), (None, 'switch-3'),
                       ('', ''), (None, None)):
        check(f'{name!r}/{slug!r} -> nothing', routed(name, slug), None)


def test_install_and_launch(home):
    spec = STANDALONE_EMULATORS['lichii']
    ra = RetroArchInterface.__new__(RetroArchInterface)
    ra.settings = None
    nsp = touch(home / 'Ludo' / 'roms' / 'switch-2' / 'Game.nsp')

    # --- nothing installed: say so, and never fall back to Eden -------------
    eden = touch(home / 'AppImages' / 'eden.appimage', exec_=True)
    check('lichii missing', find_standalone_executable('lichii', spec), '')
    for name, slug in (('Nintendo Switch 2', 'switch-2'), ('Nintendo Switch 2', None)):
        check(f'missing lichii error ({name!r}/{slug!r})',
              ra.build_launch_command(str(nsp), name, platform_slug=slug),
              (None, 'Lichii is not installed — Nintendo Switch 2 needs it, '
                     'no core can run it'))
    check('switch still launches in eden',
          ra.build_launch_command(str(nsp), 'Nintendo - Switch',
                                  platform_slug='switch')[0][0], str(eden))

    # --- Gear Lever's copy in ~/AppImages ------------------------------------
    gear = touch(home / 'AppImages' / 'lichii.appimage', exec_=True)
    check('gear lever appimage found',
          find_standalone_executable('lichii', spec), str(gear))
    check('launch argv',
          ra.build_launch_command(str(nsp), 'Nintendo Switch 2', platform_slug='switch-2'),
          ([str(gear), '-f', '-g', str(nsp)], None))
    gear.unlink()

    # --- release builds in ~/Applications, both offered in the picker -------
    reg = touch(home / 'Applications' / 'lichii-linux-x86_64.AppImage', exec_=True)
    pgo = touch(home / 'Applications' / 'lichii-linux-x86_64-pgo.AppImage', exec_=True)
    check('release appimage found',
          find_standalone_executable('lichii', spec) in (str(reg), str(pgo)), True)
    builds = find_standalone_builds('lichii', spec)
    check('both builds listed', sorted(b['path'] for b in builds),
          sorted([str(reg), str(pgo)]))
    labels = [b['label'] for b in builds]
    check('builds tell apart in the picker', len(set(labels)), 2)
    check('pgo build labelled', sorted(labels), ['Lichii', 'Lichii PGO'])

    class S:
        def get(self, sec, key, default=''):
            return str(pgo) if (sec, key) == ('Emulators', 'lichii_path') else default
    check('picked build launches', find_standalone_executable('lichii', spec, S()),
          str(pgo))
    check('argv for picked build',
          ra.build_standalone_launch_command(str(nsp), 'lichii', spec, str(pgo)),
          [str(pgo), '-f', '-g', str(nsp)])


def test_status_routes():
    ra = RetroArchInterface.__new__(RetroArchInterface)
    ra.settings = None
    rows = {r['key']: r for r in ra.standalone_emulators_status()}
    check('lichii row', {k: rows['lichii'][k] for k in ('key', 'name')},
          {'key': 'lichii', 'name': 'Lichii'})
    # The status RPC (backend.get_emulator_status spreads emulator_status())
    # ships the routing table, so the UI needs no matching of its own.
    class Settings:
        def get(self, sec, key, default=''):
            return default
    ra.settings = Settings()
    ra.retroarch_executable, ra.cores_dir, ra.save_dirs, ra.bios_manager = '', None, {}, None
    ra.get_available_cores = lambda: []
    ra.find_retroarch_config_dir = lambda: None
    ra._retroarch_cfg_value = lambda key: ''
    ra.stale_emulator_paths = lambda: []
    ra._suggested_path = lambda kind: ''
    status = ra.emulator_status()
    routes = status['standalone_routes']
    check('status lists lichii', 'lichii' in {r['key'] for r in status['standalone']}, True)
    for platform, key in (('switch', 'eden'), ('nintendo switch', 'eden'),
                          ('nintendo - switch', 'eden'), ('switch-2', 'lichii'),
                          ('nintendo switch 2', 'lichii'), ('wiiu', 'cemu'),
                          ('nintendo wii u', 'cemu')):
        check(f'route {platform!r}', routes.get(platform), key)
    check('routes are lowercase', all(k == k.lower() for k in routes), True)
    # The table the UI reads agrees with the backend's own routing.
    for platform, key in routes.items():
        check(f'routes agree on {platform!r}', routed(platform), key)


def main():
    test_routing()
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / 'home'
        home.mkdir()
        os.environ['HOME'] = str(home)
        os.environ['XDG_CONFIG_HOME'] = str(home / '.config')
        sync_core.flatpak_app_installed = lambda app: False
        sync_core.shutil.which = lambda n: None
        test_status_routes()
        test_install_and_launch(home)
    print()
    print('FAILED: ' + ', '.join(FAILED) if FAILED else 'all passed')
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main())
