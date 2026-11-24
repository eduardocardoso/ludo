r"""Eden's "select user on boot" must not override the Profile's user.
`python3 engine/tests/test_eden_select_user.py`.

With ``[UI] select_user_on_boot=true`` Eden shows its user picker even when
Ludo passes ``-u <n>``, so the Profile's Emulator user can be swapped for
another one at boot. Before a per-profile launch Ludo turns the setting off,
unless the emulator is running (it would write its in-memory config back over
ours on exit).
"""

import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import eden_config as E  # noqa: E402
from romm_sync_engine.eden_family import EDEN, EdenVariant  # noqa: E402

FAILURES = []

ON = """[Data%20Storage]
nand_directory=/home/u/.local/share/eden/nand

[UI]
Paths\\gamedirs\\size=1
select_user_on_boot\\default=false
select_user_on_boot=true
confirmClose=true

[Debugging]
record_frame_times=false
"""

OFF = (ON.replace('select_user_on_boot\\default=false', 'select_user_on_boot\\default=true')
         .replace('select_user_on_boot=true', 'select_user_on_boot=false'))


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def run(tmp, text, running, variant=EDEN, extra=True):
    """Write ``text`` as the config, call the function, and report back."""
    path = Path(tmp) / 'qt-config.ini'
    path.write_text(text)
    before = path.stat().st_mtime_ns
    calls = []

    def fake_running(*args):
        calls.append(args)
        return running
    E.eden_is_running = fake_running
    handler = Records()
    E.log.addHandler(handler)
    old_level = E.log.level
    E.log.setLevel(logging.DEBUG)
    try:
        if variant is EDEN:
            status = E.disable_select_user_on_boot(tmp if extra else None)
        else:
            status = E.disable_select_user_on_boot(tmp if extra else None, variant)
    finally:
        E.log.removeHandler(handler)
        E.log.setLevel(old_level)
    messages = [r.levelno for r in handler.records
                if 'select_user_on_boot' in r.getMessage()]
    return status, path, before, messages, calls


def main():
    # On, not running: rewritten to off (both lines, as Eden writes them), and
    # nothing else in the file moves. A log line says so.
    with tempfile.TemporaryDirectory() as tmp:
        status, path, _, logged, _ = run(tmp, ON, running=False)
        check('on, idle: status', status, 'ok')
        check('on, idle: file is the off file', path.read_text(), OFF)
        check('on, idle: logged at info', logged, [logging.INFO])
        check('on, idle: backup kept',
              (Path(tmp) / 'qt-config.ini.ludo-bak').read_text(), ON)

    # Running: the emulator would overwrite us on exit, so the file is left as
    # it is and a warning says the picker may still show.
    with tempfile.TemporaryDirectory() as tmp:
        status, path, before, logged, _ = run(tmp, ON, running=True)
        check('running: status', status, 'running')
        check('running: file untouched', path.read_text(), ON)
        check('running: not rewritten', path.stat().st_mtime_ns, before)
        check('running: warned', logged, [logging.WARNING])

    # Already off: the file is not rewritten at all, running or not.
    with tempfile.TemporaryDirectory() as tmp:
        status, path, before, logged, _ = run(tmp, OFF, running=False)
        check('off: status', status, 'already')
        check('off: not rewritten', path.stat().st_mtime_ns, before)
        check('off: no backup', (Path(tmp) / 'qt-config.ini.ludo-bak').exists(), False)
        check('off: nothing logged above debug', [l for l in logged if l > logging.DEBUG], [])
    with tempfile.TemporaryDirectory() as tmp:
        status, _, _, logged, _ = run(tmp, OFF, running=True)
        check('off, running: status', status, 'already')
        check('off, running: no warning', logged, [])

    # Absent setting is Eden's default, which is off.
    with tempfile.TemporaryDirectory() as tmp:
        text = (ON.replace('select_user_on_boot\\default=false\n', '')
                  .replace('select_user_on_boot=true\n', ''))
        status, path, before, _, _ = run(tmp, text, running=False)
        check('absent: status', status, 'already')
        check('absent: not rewritten', path.stat().st_mtime_ns, before)

    # No config: the emulator has never run, so there is no picker to turn off.
    with tempfile.TemporaryDirectory() as tmp:
        E.eden_is_running = lambda: False
        check('no config', E.disable_select_user_on_boot(tmp), 'no-config')

    # Another Eden-family emulator (Lichii, once it lands): its own config dir
    # and its own running check.
    with tempfile.TemporaryDirectory() as tmp:
        other = EdenVariant(
            key='other', name='Other', data_dirs=(), config_dirs=(tmp,),
            data_dir_env='OTHER_DATA_DIR', settings_key='other_data_dir',
            profile_key='other_user', process_names=('other',),
            default_user_name='Other')
        status, path, _, _, calls = run(tmp, ON, running=False, variant=other, extra=False)
        check('variant: status', status, 'ok')
        check('variant: rewritten', path.read_text(), OFF)
        check('variant: asked about its own process', calls, [(other,)])

    # Eden keeps today's no-argument running check (tests stub it that way).
    with tempfile.TemporaryDirectory() as tmp:
        _, _, _, _, calls = run(tmp, ON, running=False)
        check('eden: running check takes no arguments', calls, [()])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failed: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
