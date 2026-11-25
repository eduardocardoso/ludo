"""Turn a downloaded save into the target RetroArch core's own file.

Other clients (Argosy, standalone emulators) upload saves Ludo's cores can't
read as-is: an N64 sigil unit is a zip of eeprom/pak/sram, a DuckStation card
is a ``.mcd``. When a download isn't already the core's ``.srm``, sigil
restores it under the core's layout. Anything sigil refuses, or any platform
it doesn't sync, keeps the raw placement the caller already does.
"""
import re
import shutil
import tempfile
from pathlib import Path

from . import sigil_saves

# Platforms sigil can sync whose RetroArch cores keep a single <stem>.srm.
PLATFORMS = {'n64', 'psx', 'ps1', 'ps', 'saturn', 'segacd', 'dreamcast', 'gb', 'gbc'}

# Emulator tags whose files are never a RetroArch .srm, even when the
# extension says so.
_FOREIGN = {'duckstation', 'project64', 'm64plus_fz', 'mupen64plus_standalone',
            'vita_pops', 'flycast_standalone'}


def needs_conversion(file_name, emulator_tag, platform, core):
    """Whether a save named ``file_name`` (tagged ``emulator_tag`` by the
    server) needs sigil before ``core`` can read it."""
    core = _core_id(core)
    if (platform or '').lower() not in PLATFORMS or not core:
        return False
    tag = (emulator_tag or '').lower().replace('_libretro', '')
    if tag and tag != core and (tag in _FOREIGN or tag.endswith('_standalone')):
        return True
    return Path(file_name or '').suffix.lower() != '.srm'


_PS1_CARD = 128 * 1024


def core_save_name(file_name, content_path=None):
    """The file a RetroArch core reads for this game: <content stem>.srm,
    or, without local content, the server's name less its upload timestamp
    and DuckStation's slot suffix."""
    if content_path:
        return Path(content_path).stem + '.srm'
    stem = re.sub(r'\s*\[[\d\-\s:_]+\]', '', Path(file_name or 'save').stem).strip() or 'save'
    if Path(file_name or '').suffix.lower() == '.mcd' and re.search(r'_\d$', stem):
        stem = stem[:-2]
    return stem + '.srm'


def _core_id(core):
    return str(core or '').lower().replace('_libretro', '').rsplit('.', 1)[0] \
        if str(core or '').endswith(('.so', '.dll', '.dylib')) \
        else str(core or '').lower().replace('_libretro', '')


def _layout_for(platform, core):
    core = _core_id(core)
    try:
        ids = {row.id for row in sigil_saves.layouts(platform)}
    except Exception:
        return 'libretro'
    return core if core in ids else 'libretro'


def convert_into_core(unit_path, final_path, platform, core, content_path, log=print):
    """Restore the save at ``unit_path`` as ``core`` keeps it, at ``final_path``.

    True when ``final_path`` now holds the converted file (``unit_path`` is
    then removed); False when sigil is missing or refused, leaving both
    paths untouched so the caller places the raw file.
    """
    if not sigil_saves.available():
        return False
    unit_path, final_path = Path(unit_path), Path(final_path)
    platform = (platform or '').lower()
    game = sigil_saves.Game(platform=platform)
    game_ids = ()
    try:
        from .title_ids import _Sigil
        if content_path and Path(content_path).exists():
            game = sigil_saves.Game.from_result(
                platform, _Sigil.get().extract(Path(content_path), platform=platform))
            if game.title_id:
                game_ids = (game.title_id,)
    except Exception:
        pass
    layout = _layout_for(platform, core)
    stem = final_path.stem
    content = str(Path(content_path).with_name(stem + Path(content_path).suffix)
                  if content_path else stem)
    with tempfile.TemporaryDirectory(dir=final_path.parent, prefix='.sigil-') as d:
        try:
            sigil_saves.restore(unit_path.read_bytes(), game, layout, content, Path(d),
                                game_ids=game_ids, overwrite_local=True)
        except sigil_saves.SigilError as e:
            if platform in ('psx', 'ps1', 'ps') and unit_path.stat().st_size == _PS1_CARD:
                # A raw card is already what every PS1 core keeps in its .srm;
                # sigil only declines to pick this game's saves out of it.
                shutil.move(str(unit_path), str(final_path))
                log(f"  🔄 Placed PS1 card {unit_path.name} as {final_path.name}")
                return True
            log(f"  ℹ️ sigil left {unit_path.name} as-is ({e})")
            return False
        except Exception as e:
            log(f"  ⚠️ sigil conversion failed for {unit_path.name}: {e}")
            return False
        written = [p for p in Path(d).rglob('*') if p.is_file()]
        if len(written) != 1:
            log(f"  ℹ️ sigil wrote {len(written)} files for {layout}; placing raw")
            return False
        shutil.move(str(written[0]), str(final_path))
    if unit_path != final_path:
        unit_path.unlink(missing_ok=True)
    log(f"  🔄 Converted {unit_path.name} for {core}")
    return True
