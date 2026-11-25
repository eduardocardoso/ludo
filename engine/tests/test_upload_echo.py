"""An upload RomM stored is accepted, whatever timezone the server runs in.

Run with `python3 engine/tests/test_upload_echo.py`.

RomM answers a slotted save upload with the record it stored, its name tagged
"[YYYY-MM-DD_HH-MM-SS]" (5.5 adds "-mmm") in the server's LOCAL time. When it
dedupes into an older record it answers 200 too, but echoes that old record,
and only the record's age gives it away. Asserted through
RomMClient.upload_save against a fake HTTP session:

  * a fresh upload stamped in UTC-3, UTC+5:30 or UTC is accepted;
  * an echoed record that is days old is still a conflict;
  * a response whose name carries no stamp is still a success;
  * a timezone-aware created_at decides over the file-name stamp.
"""
import datetime
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine.sync_core import RomMClient  # noqa: E402

FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(label)


class FakeResponse:
    status_code = 200

    def __init__(self, body):
        self._body = body
        self.text = repr(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, body):
        self.body = body

    def post(self, *a, **k):
        return FakeResponse(self.body)


def upload(tmp, body, overwrite=False):
    """What upload_save returns when the server answers ``body``."""
    save = Path(tmp) / 'Game.srm'
    save.write_bytes(b'save bytes')
    client = RomMClient.__new__(RomMClient)
    client.base_url = 'http://romm.test'
    client.ensure_authenticated = lambda: True
    client.compute_content_hash = lambda path: 'abc'
    client.session = FakeSession(body)
    return client.upload_save(1, 'saves', save, slot='autosave',
                              upload_name='autosave.srm', overwrite=overwrite)


def stamped(offset, ago=datetime.timedelta(0), millis=False):
    """The name RomM gives a version stored ``ago`` on a server at UTC ``offset``."""
    at = datetime.datetime.now(datetime.timezone(offset)) - ago
    fmt = '%Y-%m-%d_%H-%M-%S-%f' if millis else '%Y-%m-%d_%H-%M-%S'
    tag = at.strftime(fmt)[:-3] if millis else at.strftime(fmt)
    return f'autosave [{tag}].srm'


def main():
    h = datetime.timedelta(hours=1)
    with tempfile.TemporaryDirectory() as tmp:
        check('a fresh upload stamped in UTC-3 is accepted',
              upload(tmp, {'id': 6, 'file_name': stamped(-3 * h)}), True)
        check('a fresh upload stamped in UTC+5:30 is accepted',
              upload(tmp, {'id': 6, 'file_name': stamped(5.5 * h)}), True)
        check('a fresh upload stamped in UTC is accepted',
              upload(tmp, {'id': 6, 'file_name': stamped(0 * h)}), True)
        check('a fresh upload stamped with milliseconds (RomM 5.5) is accepted',
              upload(tmp, {'id': 6, 'file_name': stamped(-3 * h, millis=True)}), True)

        days = datetime.timedelta(days=3)
        check('an echoed record from days ago is a conflict',
              upload(tmp, {'id': 2, 'file_name': stamped(-3 * h, ago=days)}), 'conflict')
        check('an echoed record from days ago fails an overwrite',
              upload(tmp, {'id': 2, 'file_name': stamped(-3 * h, ago=days)},
                     overwrite=True), False)
        check('an echoed record stamped with milliseconds is a conflict',
              upload(tmp, {'id': 2, 'file_name': stamped(
                  -3 * h, ago=days, millis=True)}), 'conflict')

        check('a name with no stamp still counts as uploaded',
              upload(tmp, {'id': 6, 'file_name': 'autosave.srm'}), True)

        # created_at as RomM serialises it: ISO 8601 with its UTC offset.
        def created(ago):
            return (datetime.datetime.now(datetime.timezone.utc) - ago).isoformat()
        # A record made 5h30m ago, its stamp in UTC+5:30: the stamp alone
        # reads as "now", the timestamp says otherwise.
        old = 5.5 * h
        check('an old tz-aware created_at is a conflict despite a fresh-looking stamp',
              upload(tmp, {'id': 2, 'file_name': stamped(0 * h, ago=old),
                           'created_at': created(old)}), 'conflict')
        check('a fresh tz-aware created_at is accepted despite an old stamp',
              upload(tmp, {'id': 6, 'file_name': stamped(0 * h, ago=days),
                           'created_at': created(datetime.timedelta(0))}), True)
        check('a created_at with a Z suffix is read as UTC',
              upload(tmp, {'id': 2, 'file_name': stamped(0 * h, ago=old),
                           'created_at': created(old).replace('+00:00', 'Z')}),
              'conflict')
        check('a created_at with no zone falls back to the stamp',
              upload(tmp, {'id': 6, 'file_name': stamped(-3 * h),
                           'created_at': created(days).replace('+00:00', '')}), True)
        check('an unstamped name stays a success whatever created_at says',
              upload(tmp, {'id': 6, 'file_name': 'autosave.srm',
                           'created_at': created(days)}), True)

    if FAILURES:
        print(f'\n{len(FAILURES)} failure(s): {FAILURES}')
        return 1
    print('\nall upload echo checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
