"""Where an Eden-family emulator keeps its saves and its user list.

Eden and Lichii each name two folders in the ``[Data Storage]`` section of
their own qt-config.ini (Lichii source: filesystem.cpp's
CreateSaveDataFactory uses SaveDir, profile_manager.cpp reads profiles.dat
from NANDDir):

  * ``save_directory``: the root of every game save. Saves live under
    ``<save_directory>/user/save/0000000000000000/<user>/<title id>``.
  * ``nand_directory``: the NAND root. The user list is
    ``<nand_directory>/system/save/8000000000000010/su/avators/profiles.dat``.

Both default to ``<data dir>/nand/``. Importing yuzu's data, or moving the
folders in the emulator's settings, points them elsewhere, and only these
settings say where.

Precedence, for one install:

  1. The data dir (the data root) is what it always was: Ludo's
     ``[Emulators] <x>_data_dir`` setting, else the variant's data-folder
     environment variable, else the detected install (flatpak or native).
  2. The emulator's own config is the one belonging to that data dir: the
     flatpak config for the flatpak data dir, the native config for the
     native one (the environment variable's folder included). A data dir
     that is neither, such as a setting naming some other folder, has no
     config Ludo can tie to it.
  3. In that config, ``save_directory`` and ``nand_directory`` win over the
     data dir, each only when its ``\\default`` shadow is ``false``, the
     value is non-empty and the folder exists. Otherwise
     ``<data dir>/nand`` is used, as before.

This module imports nothing from the rest of the engine but eden_family, so
emulator_saves and eden_users can both import it without a cycle.
"""

import logging
import os
from pathlib import Path

from .eden_family import EDEN

log = logging.getLogger(__name__)

_SECTION = '[Data%20Storage]'
_SAVE_KEY = 'save_directory'
_NAND_KEY = 'nand_directory'

# Relative to a save_directory, which is a NAND root of its own.
SAVE_TREE = ('user', 'save')


def _is_flatpak(directory):
    return '/.var/app/' in str(directory)


def _same(a, b):
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return False


def config_dir_for(data_dir, variant=EDEN):
    """The config folder of the install whose data dir is ``data_dir``, or
    None when ``data_dir`` is no install's.

    Data and config folders are paired by kind, as eden_config_dir_for pairs
    them for an executable: flatpak with flatpak, native with native.
    """
    flatpak_data = [d for d in variant.data_dirs if _is_flatpak(d)]
    flatpak_config = [d for d in variant.config_dirs if _is_flatpak(d)]
    for data, config in zip(flatpak_data, flatpak_config):
        if _same(data_dir, data):
            return Path(config).expanduser()
    native = os.environ.get(variant.data_dir_env) or variant.data_dirs[-1]
    if _same(data_dir, native):
        return Path(variant.config_dirs[-1]).expanduser()
    return None


_ESCAPES = {'\\': '\\', '"': '"', "'": "'", '0': '\0', 'a': '\a', 'b': '\b',
            'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v', '?': '?'}


def _unescape(raw):
    """A QSettings ini value as the string QSettings reads.

    QSettings quotes a value with leading or trailing spaces, or one holding a
    comma or semicolon, escapes backslashes, quotes and control characters
    with a backslash, writes other characters as ``\\x<hex>``, and doubles a
    leading ``@``. A plain path, the usual case, has none of these.
    """
    out, i = [], 0
    text = raw.strip()
    while i < len(text):
        ch = text[i]
        if ch == '"':
            pass  # quotes only delimit
        elif ch == '\\' and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == 'x':
                j = i + 2
                while j < len(text) and j < i + 6 and text[j] in '0123456789abcdefABCDEF':
                    j += 1
                if j > i + 2:
                    out.append(chr(int(text[i + 2:j], 16)))
                    i = j
                    continue
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        else:
            out.append(ch)
        i += 1
    value = ''.join(out)
    if value.startswith('@@'):
        value = value[1:]
    return value


def _storage_settings(config_dir):
    """{key: raw value} of [Data Storage], '' values for keys whose
    ``\\default`` shadow is not false. {} without a readable config."""
    try:
        lines = (Path(config_dir) / 'qt-config.ini').read_text(
            encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return {}
    values, defaults, inside = {}, {}, False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            inside = stripped == _SECTION
            continue
        if not inside:
            continue
        key, sep, value = line.partition('=')
        if not sep:
            continue
        key = key.strip()
        if key.endswith('\\default'):
            defaults[key[:-len('\\default')]] = value.strip().lower()
        else:
            values[key] = value
    return {k: v for k, v in values.items() if defaults.get(k) == 'false'}


def _configured(data_dir, key, variant):
    """The folder ``key`` names in the install's config, or None to use the
    default. A set folder that does not exist is logged and ignored."""
    config_dir = config_dir_for(data_dir, variant)
    if config_dir is None:
        return None
    raw = _storage_settings(config_dir).get(key)
    value = _unescape(raw) if raw is not None else ''
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_dir():
        log.warning("%s's %s %s does not exist; using %s", variant.name, key,
                    path, Path(data_dir) / 'nand')
        return None
    return path


def nand_dir(data_dir, variant=EDEN):
    """The NAND root of the install at ``data_dir``: its configured
    nand_directory, else ``<data dir>/nand``. Holds the user list."""
    return _configured(data_dir, _NAND_KEY, variant) or Path(data_dir) / 'nand'


def save_dir(data_dir, variant=EDEN):
    """The root of all save data for the install at ``data_dir``: its
    configured save_directory, else ``<data dir>/nand``."""
    return _configured(data_dir, _SAVE_KEY, variant) or Path(data_dir) / 'nand'


def save_tree(data_dir, variant=EDEN):
    """The save tree, ``<save root>/user/save``, existing or not."""
    return save_dir(data_dir, variant).joinpath(*SAVE_TREE)
