#!/usr/bin/env python3
"""A Switch 2 game's base dump leads, over its update and DLC.

Switch 2 ("04") IDs are kept out of add-on install, which installs into Eden.
Ranking which ROM is the base game is a different question, and it has to see
those IDs: in the library tile, and in the local ROM index that save matching
reads.

Run with `python3 engine/tests/test_switch2_ranking.py`.
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import title_ids as T  # noqa: E402
from romm_sync_engine.sync_core import RomMClient  # noqa: E402

FAILURES = []

BASE = '0400ABCD12340000'
UPDATE = '0400ABCD12340800'
DLC = '0400ABCD12341001'


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(label)


def row(rom_id, fs_name, siblings, size=0):
    return {'id': rom_id, 'name': fs_name.rsplit('.', 1)[0],
            'fs_name': fs_name, 'fs_extension': '.nsp',
            'fs_size_bytes': size, 'platform_slug': 'switch-2',
            'files': [{'file_name': fs_name}],
            'sibling_roms': [{'id': s} for s in siblings], 'rom_user': {}}


def test_switch2_tile_leads_with_the_base_game():
    rows = {1: row(1, f'Kirby Air Riders [{UPDATE}][v65536].nsp', [2, 3]),
            2: row(2, f'Kirby Air Riders [{BASE}][v0].nsp', [1, 3]),
            3: row(3, f'Kirby Air Riders [{DLC}].nsp', [1, 2])}
    for order in ([1, 3, 2], [3, 1, 2], [2, 1, 3]):
        grouped = RomMClient._group_sibling_roms(None, [rows[i] for i in order])
        check(f'switch 2 base game wins the tile (API order {order})',
              grouped[0]['id'], 2)

    # Scene names carry no ID: the slug alone gates the Switch ranking, and
    # the big file (the base dump) leads.
    scene = {1: row(1, 'kar-update_v65536.nsp', [2], size=100),
             2: row(2, 'kar-base_nsw2.nsp', [1], size=9000)}
    for order in ([1, 2], [2, 1]):
        grouped = RomMClient._group_sibling_roms(None, [scene[i] for i in order])
        check(f'untagged switch 2 group leads with the big file ({order})',
              grouped[0]['id'], 2)


def test_switch2_add_ons_stay_out_of_install():
    # Install still rejects "04": the ranking fix must not reopen this.
    check('switch_content_from_name still answers None for a 04 update',
          T.switch_content_from_name(f'Game [{UPDATE}][v65536].nsp'), None)


class _FakeSigil:
    """Answers a CNMT read: the kind comes from the container, not the name."""

    def __init__(self, ids):
        self.ids = ids

    def extract(self, path, prod_keys=None, platform=None):
        tid = self.ids[Path(path).name]
        return SimpleNamespace(
            platform=T._SIGIL_PLATFORM_SWITCH, title_id=tid.encode(),
            switch_content_type={'base': 1, 'update': 2}[T.switch_kind(tid)],
            source=0, title_version=0)


def test_untagged_switch2_base_beats_its_update_in_the_index():
    with tempfile.TemporaryDirectory() as tmp:
        roms = Path(tmp)
        base_rom = roms / 'Kirby Air Riders.nsp'
        patch_rom = roms / 'Kirby Air Riders Update.nsp'
        for f in (base_rom, patch_rom):
            f.write_bytes(b'')
        ids = {base_rom.name: BASE, patch_rom.name: UPDATE}
        real_get, real_tid = T._Sigil.get, T.title_id_from_rom
        T._Sigil.get = classmethod(lambda cls: _FakeSigil(ids))
        T.title_id_from_rom = lambda path, **kw: BASE
        try:
            check('switch 2 base dump ranks as a base game',
                  T._content_rank(base_rom), 0)
            check('switch 2 update ranks below the base game',
                  T._content_rank(patch_rom), 1)
            check('switch 2 base dump wins the index entry',
                  T.index_roms([roms])[BASE].name, base_rom.name)
        finally:
            T._Sigil.get, T.title_id_from_rom = real_get, real_tid


def main():
    test_switch2_tile_leads_with_the_base_game()
    test_switch2_add_ons_stay_out_of_install()
    test_untagged_switch2_base_beats_its_update_in_the_index()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all switch 2 ranking checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
