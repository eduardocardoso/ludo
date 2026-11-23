"""A Profile adopts an Emulator user that already carries its name.

Players who made one Eden or Lichii user per family member by hand keep
those users (and their saves) instead of getting a duplicate: a Profile with
no stored user adopts the one whose name is exactly its name or username.

Run with `python3 engine/tests/test_adopt_emulator_user.py`. Every test runs
under a fake HOME, since this machine may have a real Eden or Lichii.
"""

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
def emulator_with_users(variant, *names):
    """A fake HOME with profiles in use, ``variant`` closed, and its user list
    holding the emulator's first user followed by ``names``. Yields the data
    folder."""
    with tempfile.TemporaryDirectory() as tmp, \
            patch.dict(os.environ, {'HOME': tmp, 'XDG_CONFIG_HOME': f'{tmp}/.config'}), \
            patch.object(E, 'eden_is_running', lambda variant=EDEN, proc_root=None: False):
        os.environ.pop('EDEN_DATA_DIR', None)
        os.environ.pop('LICHII_DATA_DIR', None)
        paths._locked, paths._profile_locked, paths._profile = False, False, P.DEFAULT
        paths.set_app_id('ludo')
        paths.set_library_dir_name('Ludo')
        P.launch = {'id': P.DEFAULT, 'steam': None, 'ask': False}
        try:
            data = Path(tmp) / '.local/share' / variant.key
            U.create_default(data, **({} if variant is EDEN else {'variant': variant}))
            for name in names:
                U.add(data, name)
            yield data
        finally:
            P.launch = None
            paths._locked, paths._profile_locked, paths._profile = False, False, P.DEFAULT


def use(profile_id):
    paths._locked, paths._profile_locked, paths._profile = False, False, P.DEFAULT
    paths.set_profile(profile_id)


def names(data):
    return [u['name'] for u in U.users(data)]


def uuid_of(data, name):
    return next(u['uuid'] for u in U.users(data) if u['name'] == name)


def user(variant, create=True):
    kw = {} if variant is EDEN else {'variant': variant}
    return P.eden_user(create=create, **kw)


def test_exact_name_is_adopted(variant):
    first = variant.name
    with emulator_with_users(variant, 'covin', 'Mia') as data:
        mia = P.create('Mia')
        use(mia)
        got = user(variant)
        check('adopted Mia', got.get('uuid'), uuid_of(data, 'Mia'))
        check('no user added', names(data), [first, 'covin', 'Mia'])
        check('stored', P.get(P.load(), mia).get(variant.profile_key), uuid_of(data, 'Mia'))
        check('save dir', got.get('save_dir'), U.save_dir_name(uuid_of(data, 'Mia')))


def test_username_is_adopted(variant):
    first = variant.name
    with emulator_with_users(variant, 'covin', 'mia_r') as data:
        mia = P.create('Mia')
        P.set_identity(mia, 'mia_r')
        use(mia)
        check('adopted by username', user(variant).get('uuid'), uuid_of(data, 'mia_r'))
        check('no user added', names(data), [first, 'covin', 'mia_r'])


def test_adopted_without_writing_the_user_list(variant):
    """Adoption only touches profiles.json, so it also settles a read."""
    with emulator_with_users(variant, 'Mia') as data:
        before = U.profiles_file(data).read_bytes()
        mia = P.create('Mia')
        use(mia)
        check('read adopts', user(variant, create=False).get('uuid'), uuid_of(data, 'Mia'))
        check('user list untouched', U.profiles_file(data).read_bytes(), before)


def test_near_match_is_not_adopted(variant):
    first = variant.name
    for near in ('mia', 'Mia ', ' Mia', 'MIA'):
        with emulator_with_users(variant, near) as data:
            mia = P.create('Mia')
            use(mia)
            got = user(variant)
            check(f'{near!r} not adopted', got.get('uuid') != uuid_of(data, near), True)
            check(f'{near!r}: Mia added', names(data), [first, near, 'Mia'])
            check(f'{near!r}: own user stored', P.get(P.load(), mia).get(variant.profile_key),
                  uuid_of(data, 'Mia'))


def test_stored_user_is_never_repointed(variant):
    with emulator_with_users(variant, 'covin') as data:
        mia = P.create('Mia')
        use(mia)
        own = user(variant)['uuid']
        # Someone later adds a user carrying the Profile's name by hand.
        U.add(data, 'Mia')
        other = [u['uuid'] for u in U.users(data) if u['name'] == 'Mia' and u['uuid'] != own]
        check('second Mia exists', len(other), 1)
        check('still its own user', user(variant)['uuid'], own)
        check('stored unchanged', P.get(P.load(), mia).get(variant.profile_key), own)


def test_stored_user_missing_from_the_list_is_not_swapped(variant):
    """A stored user gone from the list is added back, never swapped for a
    name match."""
    with emulator_with_users(variant, 'Mia') as data:
        mia = P.create('Mia')
        use(mia)
        stored = 'ab' * 16
        entry_data = P.load()
        P.get(entry_data, mia)[variant.profile_key] = stored
        P.save(entry_data)
        check('stored id kept', user(variant)['uuid'], stored)
        check('stored id re-added', U.find(data, stored) is not None, True)


def test_default_profile_keeps_the_selected_user(variant):
    """The default Profile follows the emulator's selected user, even when
    another user carries its name."""
    with emulator_with_users(variant, 'Default') as data:
        P.create('Mia')
        default_name = P.get(P.load(), P.DEFAULT).get('name')
        if default_name != 'Default':
            data_ = P.load()
            P.get(data_, P.DEFAULT)['name'] = 'Default'
            P.save(data_)
        check('selected user kept', user(variant)['uuid'], U.users(data)[0]['uuid'])


def test_user_held_by_another_profile_is_not_adopted(variant):
    """Two Profiles never share an Emulator user, even with the same name."""
    first = variant.name
    with emulator_with_users(variant, 'Mia') as data:
        one = P.create('Mia')
        use(one)
        check('first adopts', user(variant)['uuid'], uuid_of(data, 'Mia'))
        two = P.create('Mia')
        use(two)
        got = user(variant)['uuid']
        check('second gets its own', got != uuid_of(data, 'Mia') and U.find(data, got) is not None, True)
        check('one more user', len(names(data)), len([first, 'Mia', 'Mia']))


def test_eden_and_lichii_adopt_separately():
    """Adopting a Lichii user leaves the Eden one alone, and the reverse."""
    with emulator_with_users(LICHII, 'Mia') as lichii:
        home = lichii.parents[2]
        eden = home / '.local/share/eden'
        U.create_default(eden)
        U.add(eden, 'Mia')
        mia = P.create('Mia')
        use(mia)
        check('lichii adopted', user(LICHII)['uuid'], uuid_of(lichii, 'Mia'))
        check('eden not set yet', P.get(P.load(), mia).get('eden_user'), None)
        check('eden adopted', user(EDEN)['uuid'], uuid_of(eden, 'Mia'))
        entry = P.get(P.load(), mia)
        check('both stored', (entry.get('eden_user'), entry.get('lichii_user')),
              (uuid_of(eden, 'Mia'), uuid_of(lichii, 'Mia')))


def main():
    for variant in (EDEN, LICHII):
        for test in (
            test_exact_name_is_adopted,
            test_username_is_adopted,
            test_adopted_without_writing_the_user_list,
            test_near_match_is_not_adopted,
            test_stored_user_is_never_repointed,
            test_stored_user_missing_from_the_list_is_not_swapped,
            test_default_profile_keeps_the_selected_user,
            test_user_held_by_another_profile_is_not_adopted,
        ):
            print(f"-- {test.__name__} [{variant.key}]")
            test(variant)
    print("-- test_eden_and_lichii_adopt_separately")
    test_eden_and_lichii_adopt_separately()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s): {FAILURES}")
        return 1
    print("\nall passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
