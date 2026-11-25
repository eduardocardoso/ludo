"""sigil_saves: the ctypes mirrors match sigil.h, and units convert.

The layout check compiles a tiny C program against tests/sigil.h (copied
there by scripts/build_sigil.sh with the bundled library) and compares every
struct's size and field offsets with ctypes'. A mismatch is a silent memory
bug, not an exception, so this is the test that catches a sigil bump that
grew a struct. It skips without a C compiler.
"""
import ctypes
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romm_sync_engine import sigil_saves as S  # noqa: E402

HERE = Path(__file__).resolve().parent
failures = []


def check(name, got, want):
    if got != want:
        failures.append(name)
        print(f'FAIL {name}: got={got!r} want={want!r}')


def layouts_match_header():
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc or not (HERE / 'sigil.h').exists():
        print('skip: no C compiler or tests/sigil.h')
        return
    lines = ['#include <stdio.h>', '#include <stddef.h>', '#include "sigil.h"',
             'int main(void) {']
    for cname, struct in S.STRUCTS.items():
        lines.append(f'printf("{cname} %zu\\n", sizeof({cname}));')
        for field, _ in struct._fields_:
            lines.append(f'printf("{cname}.{field} %zu\\n", offsetof({cname}, {field}));')
    lines.append('return 0; }')
    with tempfile.TemporaryDirectory() as d:
        src, exe = Path(d) / 'l.c', Path(d) / 'l'
        src.write_text('\n'.join(lines))
        subprocess.run([cc, '-I', str(HERE), str(src), '-o', str(exe)], check=True)
        want = dict(line.rsplit(' ', 1) for line in
                    subprocess.run([str(exe)], capture_output=True, text=True,
                                   check=True).stdout.splitlines())
    for cname, struct in S.STRUCTS.items():
        check(f'sizeof {cname}', ctypes.sizeof(struct), int(want[cname]))
        for field, _ in struct._fields_:
            check(f'{cname}.{field}', getattr(struct, field).offset,
                  int(want[f'{cname}.{field}']))


def layouts_table():
    rows = S.layouts('n64')
    ids = [r.id for r in rows]
    check('libretro default first', ids[0], 'libretro')
    check('mupen listed for n64', 'mupen64plus_next' in ids, True)
    check('every row typed', all(isinstance(r, S.Layout) for r in rows), True)


def single_file_roundtrip():
    """A cartridge save, collected and restored under the libretro layout."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / 'saves'
        root.mkdir()
        (root / 'Game.srm').write_bytes(b'\x11' * 8192)
        game = S.Game(platform='gb')
        got = S.collect(game, 'gambatte', '/roms/Game.gb', root)
        check('collect found the save', got.data, b'\x11' * 8192)
        check('collect names the artifact', got.artifact, 'Game.srm')
        check('state blob returned', bool(got.state), True)

        other = Path(d) / 'other'
        other.mkdir()
        back = S.restore(got.data, game, 'gambatte', '/roms/Game.gb', other)
        check('restore wrote it', (other / 'Game.srm').read_bytes(), b'\x11' * 8192)
        check('no .part left', [p.name for p in other.iterdir()], ['Game.srm'])
        again = S.collect(game, 'gambatte', '/roms/Game.gb', other, state=back.state)
        check('unchanged after restore', again.changed, False)


def conflict_refuses():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / 'Game.srm').write_bytes(b'a' * 8192)
        game = S.Game(platform='gb')
        first = S.collect(game, 'gambatte', '/roms/Game.gb', root)
        (root / 'Game.srm').write_bytes(b'b' * 8192)
        try:
            S.restore(b'c' * 8192, game, 'gambatte', '/roms/Game.gb', root, state=first.state)
            check('conflict raised', False, True)
        except S.SigilError as e:
            check('conflict code', e.code, S.ERR_CONFLICT)
        check('conflict wrote nothing', (root / 'Game.srm').read_bytes(), b'b' * 8192)


def _ps1_card(saves):
    """A raw PS1 card holding ``saves`` (directory name, blocks), as
    upstream's bindings/python/test_sigil.py builds one."""
    card = bytearray(128 * 1024)
    card[0:2] = b'MC'
    for frame in range(1, 16):
        card[frame * 128] = 0xA0
        card[frame * 128 + 8:frame * 128 + 10] = b'\xff\xff'
    block = 1
    for name, blocks in saves:
        for i in range(blocks):
            frame = (block + i) * 128
            state = 0x51 if i == 0 else (0x53 if i == blocks - 1 else 0x52)
            link = 0xFFFF if i == blocks - 1 else block + i
            card[frame:frame + 4] = struct.pack('<I', state)
            card[frame + 4:frame + 8] = struct.pack('<I', blocks * 8192 if i == 0 else 0)
            card[frame + 8:frame + 10] = struct.pack('<H', link)
            if i == 0:
                card[frame + 10:frame + 10 + len(name)] = name.encode('ascii')
        block += blocks
    return bytes(card)


def _files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())


def ps1_converts_between_cores():
    """A PCSX ReARMed card restores for the other PS1 cores; each collects
    back to the very same unit, which is what makes the switch lossless."""
    cross = S.Game(platform='psx', title_id='SLUS-01041', save_id='SLUS-01041')
    ids = ['SLUS-01041']
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src = d / 'pcsx'
        src.mkdir()
        (src / 'Chrono Cross.srm').write_bytes(
            _ps1_card([('BASLUSP01041CROSS', 2), ('BASCUS-94426SLOTS', 1)]))
        unit = S.collect(cross, 'pcsx_rearmed', 'Chrono Cross.cue', src, game_ids=ids)
        check('ps1 unit is one card', (unit.shape, len(unit.data)), ('single', 128 * 1024))
        for layout, written in (('swanstation', ['Chrono Cross.srm']),
                                ('mednafen_psx_hw', ['Chrono Cross.srm']),
                                ('duckstation', ['memcards/Chrono Cross_1.mcd'])):
            dst = d / layout
            dst.mkdir()
            got = S.restore(unit.data, cross, layout, 'Chrono Cross.cue', dst, game_ids=ids)
            check(f'ps1 -> {layout} file', _files(dst), written)
            back = S.collect(cross, layout, 'Chrono Cross.cue', dst, game_ids=ids,
                             state=got.state)
            check(f'ps1 -> {layout} round trip', back.data, unit.data)
            check(f'ps1 -> {layout} unchanged', back.changed, False)


def n64_converts_between_cores():
    game = S.Game(platform='n64')
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src = d / 'mupen'
        src.mkdir()
        srm = bytearray(b'\xff' * 0x48800)
        srm[0:0x800] = bytes(0x800)
        srm[0:16] = b'EEPROMDATA123456'
        (src / 'Mario.srm').write_bytes(bytes(srm))
        unit = S.collect(game, 'mupen64plus_next', 'Mario.z64', src)
        check('n64 unit is a zip', (unit.shape, unit.artifact), ('multi', 'Mario.zip'))
        dst = d / 'parallel'
        dst.mkdir()
        S.restore(unit.data, game, 'parallel_n64', 'Mario.z64', dst)
        check('n64 -> parallel file', _files(dst), ['Mario.srm'])
        check('n64 -> parallel eeprom', (dst / 'Mario.srm').read_bytes()[:16],
              b'EEPROMDATA123456')
        check('n64 -> parallel round trip',
              S.collect(game, 'parallel_n64', 'Mario.z64', dst).data, unit.data)
        # Standalone emulators name saves after the cart header; without the
        # ROM's identity (Game.n64_*) sigil can't spell the file and says so.
        pj = d / 'pj64'
        pj.mkdir()
        try:
            S.restore(unit.data, game, 'project64', 'Mario.z64', pj)
            check('project64 without header refused', False, True)
        except S.SigilError as e:
            check('project64 without header: no target', (e.code, e.problem),
                  (S.ERR_NO_TARGET, 'eeprom'))
        check('project64 refusal wrote nothing', _files(pj), [])


if __name__ == '__main__':
    if not S.available():
        print('skip: sigil without collect/restore')
        sys.exit(0)
    layouts_match_header()
    layouts_table()
    single_file_roundtrip()
    conflict_refuses()
    ps1_converts_between_cores()
    n64_converts_between_cores()
    if failures:
        print(f'{len(failures)} failure(s)')
        sys.exit(1)
    print('ok')
