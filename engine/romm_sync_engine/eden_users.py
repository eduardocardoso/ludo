"""Eden's Switch users, read and added the way Eden itself stores them.

Eden keeps up to eight users in one fixed-size file (source:
src/core/hle/service/acc/profile_manager.cpp):

    <NAND root>/system/save/8000000000000010/su/avators/profiles.dat
    0x10 bytes header (unused), then 8 slots of 0xC8:
      +0x00 uuid (16 bytes)   +0x10 uuid again   +0x20 u64 timestamp
      +0x28 username (32 bytes UTF-8, NUL padded)   +0x48 0x80 bytes extra

An all-zero uuid is an empty slot. Eden lists the valid slots in file order,
and its ``-u <n>`` launch option picks the n-th of those.

The NAND root is the emulator's configured nand_directory, else
<data dir>/nand (see eden_storage). Each user's saves live under the save
root, likewise its save_directory or <data dir>/nand, in
<save root>/user/save/0000000000000000/<id>/<TITLE_ID>,
where <id> is the uuid's 16 bytes in reverse order as upper-case hex
(savedata_factory.cpp prints the two little-endian u64 halves high first).
"""
import os
import secrets
import struct
import tempfile
from pathlib import Path

from . import eden_storage
from .eden_family import EDEN

# Relative to the NAND root (eden_storage.nand_dir), which is <data dir>/nand
# unless the emulator's config moves it.
PROFILES_PATH = ('system', 'save', '8000000000000010', 'su', 'avators', 'profiles.dat')
_HEADER = 0x10
_SLOT = 0xC8
MAX_USERS = 8
_SIZE = _HEADER + _SLOT * MAX_USERS
_NAME_AT = 0x28
_NAME_LEN = 32


class EdenUsersError(Exception):
    pass


def profiles_file(data_dir, variant=EDEN):
    """profiles.dat of the install at ``data_dir``, under the NAND root its
    config names."""
    return eden_storage.nand_dir(data_dir, variant).joinpath(*PROFILES_PATH)


def _read(data_dir, variant=EDEN):
    path = profiles_file(data_dir, variant)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < _SIZE:
        return None
    return bytearray(data[:_SIZE])


def users(data_dir, variant=EDEN):
    """Valid users in Eden's order: [{'index', 'uuid' (hex), 'name', 'save_dir'}].
    None when Eden has no readable user file (it has never run)."""
    data = _read(data_dir, variant)
    if data is None:
        return None
    out = []
    for slot in range(MAX_USERS):
        base = _HEADER + slot * _SLOT
        raw = bytes(data[base:base + 16])
        if not any(raw):
            continue
        name = bytes(data[base + _NAME_AT:base + _NAME_AT + _NAME_LEN]).split(b'\0', 1)[0]
        out.append({'index': len(out), 'uuid': raw.hex(),
                    'name': name.decode('utf-8', errors='replace'),
                    'save_dir': save_dir_name(raw.hex())})
    return out


def create_default(data_dir, variant=EDEN):
    """Write the user list Eden makes on its first start, when there is none.

    Eden creates one user named "Eden" with a random id the first time it
    runs (profile_manager.cpp). Writing that same file ahead of it lets a
    profile get its own user before Eden has ever been opened; Eden reads it
    as if it had made it, and its default user stays the first profile's.
    An existing file is never touched. Returns True when the file was written.
    ``variant`` picks the Eden-family emulator, whose default user name is
    written; Eden by default.
    """
    path = profiles_file(data_dir, variant)
    if path.exists():
        return False
    data = bytearray(_SIZE)
    raw = secrets.token_bytes(16)
    data[_HEADER:_HEADER + 16] = raw
    data[_HEADER + 16:_HEADER + 32] = raw
    data[_HEADER + _NAME_AT:_HEADER + _NAME_AT + _NAME_LEN] = _encode_name(variant.default_user_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, data)
    return True


def _write(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.profiles-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(bytes(data))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_dir_name(uuid_hex):
    """The folder Eden keeps this user's saves in."""
    return bytes.fromhex(uuid_hex)[::-1].hex().upper()


def find(data_dir, uuid_hex, variant=EDEN):
    for user in users(data_dir, variant) or []:
        if user['uuid'] == uuid_hex:
            return user
    return None


def _encode_name(name):
    raw = (name or 'Player').encode('utf-8')[:_NAME_LEN]
    # Never cut a character in half.
    while raw:
        try:
            raw.decode('utf-8')
            break
        except UnicodeDecodeError:
            raw = raw[:-1]
    return raw.ljust(_NAME_LEN, b'\0')


def add(data_dir, name, uuid_hex=None, variant=EDEN):
    """Add a user in the first free slot and return its uuid (hex).

    ``uuid_hex`` reuses an id, so one Ludo profile is the same Eden user in
    every Eden install on the machine. Eden must be closed: it rewrites the
    file from memory when it saves its own changes. ``variant`` names the
    Eden-family emulator in errors; Eden by default.
    """
    path = profiles_file(data_dir, variant)
    data = _read(data_dir, variant)
    if data is None:
        raise EdenUsersError(f'{variant.name} has no user list yet; '
                             f'start {variant.name} once first')
    raw = bytes.fromhex(uuid_hex) if uuid_hex else secrets.token_bytes(16)
    if len(raw) != 16 or not any(raw):
        raise EdenUsersError('Invalid user id')
    for slot in range(MAX_USERS):
        base = _HEADER + slot * _SLOT
        if bytes(data[base:base + 16]) == raw:
            return raw.hex()
    for slot in range(MAX_USERS):
        base = _HEADER + slot * _SLOT
        if any(data[base:base + 16]):
            continue
        data[base:base + _SLOT] = bytes(_SLOT)
        data[base:base + 16] = raw
        data[base + 16:base + 32] = raw
        struct.pack_into('<Q', data, base + 0x20, 0)
        data[base + _NAME_AT:base + _NAME_AT + _NAME_LEN] = _encode_name(name)
        _write(path, data)
        return raw.hex()
    raise EdenUsersError(f'Eden already has {MAX_USERS} users')
