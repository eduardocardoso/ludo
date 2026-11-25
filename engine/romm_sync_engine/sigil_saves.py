"""Sigil's save sync: collect, restore and the layout table, over ctypes.

argosy-sigil turns one game's saves, as a given emulator keeps them, into a
"unit" (the file that travels to RomM) and puts a unit back for any emulator
whose layout it knows. That is what lets a save made in one emulator load in
another: collect under the layout it was made with, restore under the one
about to run. Argosy converts the same way at launch, so the two clients
agree on every unit.

This mirrors upstream's own Python package (bindings/python/sigil in
argosy-sigil): the same functions, arguments and results. Upstream builds
with cffi, which needs a compiler per target; Ludo loads the prebuilt library
title_ids already loads, on the Deck's Python and on Windows alike, so these
are hand-kept ctypes mirrors of include/sigil.h. test_sigil_saves checks
their sizes against the header whenever a C compiler is around.
"""
import ctypes
import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .title_ids import _Sigil, _SigilResult

# ---- include/sigil.h -------------------------------------------------------

SAVE_PATH_MAX = 512
SAVE_ENTRY_MAX = 256
PROFILE_ID_MAX = 64
PROFILE_NAME_MAX = 64
CARD_NAME_MAX = 64
LAYOUT_OPTION_VALUES = 8
LAYOUT_OPTIONS = 16

RESULT_V4 = 4
SAVE_REQUEST_V1 = 1
SYNC_REQUEST_V1 = 1

SYNC_MANAGED = 0
SYNC_UNMANAGED = 1

_SHAPES = {0: 'none', 1: 'single', 2: 'multi', 3: 'folder'}

# Mirrors upstream's walk limits, so both list the same files.
_SUBDIR_LIST_DEPTH = 12
_SUBDIR_CAP = 16
_BASE_SEARCH_DEPTH = 5
_PATH_CAP = 4096

_c_p = ctypes.c_char_p
_size = ctypes.c_size_t
_u8p = ctypes.POINTER(ctypes.c_uint8)

# sigil_io is opaque: pointers to it travel as void*.
_OPEN_FN = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, _c_p)
_WRITE_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, _c_p, _u8p, _size)
_REMOVE_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, _c_p)


class _SaveOption(ctypes.Structure):
    _fields_ = [('key', _c_p), ('value', _c_p)]


class _SaveProfile(ctypes.Structure):
    _fields_ = [('id', ctypes.c_char * PROFILE_ID_MAX),
                ('name', ctypes.c_char * PROFILE_NAME_MAX)]


class _SaveAlternate(ctypes.Structure):
    _fields_ = [('path', ctypes.c_char * SAVE_PATH_MAX),
                ('shared', ctypes.c_int),
                ('options', _SaveOption * 2),
                ('option_count', _size)]


class _SaveRequest(ctypes.Structure):
    _fields_ = [('struct_version', ctypes.c_uint32),
                ('layout', _c_p),
                ('platform', _c_p),
                ('content_path', _c_p),
                ('result', ctypes.POINTER(_SigilResult)),
                ('features', ctypes.c_uint32),
                ('options', ctypes.POINTER(_SaveOption)),
                ('option_count', _size),
                ('listing', ctypes.POINTER(_c_p)),
                ('listing_count', _size),
                ('open', _OPEN_FN),
                ('open_ctx', ctypes.c_void_p),
                ('root_path', _c_p),
                ('profile', _c_p)]


class _SyncCompanion(ctypes.Structure):
    _fields_ = [('game_ids', ctypes.POINTER(_c_p)),
                ('game_id_count', _size),
                ('unit', _u8p),
                ('unit_len', _size)]


class _SyncCompanionResult(ctypes.Structure):
    _fields_ = [('data', _u8p),
                ('len', _size),
                ('content_hash', ctypes.c_char * 33),
                ('identity_hash', ctypes.c_char * 33),
                ('changed', ctypes.c_int)]


class _SyncRequest(ctypes.Structure):
    _fields_ = [('struct_version', ctypes.c_uint32),
                ('save', _SaveRequest),
                ('game_ids', ctypes.POINTER(_c_p)),
                ('game_id_count', _size),
                ('mode', ctypes.c_int),
                ('state', _u8p),
                ('state_len', _size),
                ('overwrite_local', ctypes.c_int),
                ('write', _WRITE_FN),
                ('write_ctx', ctypes.c_void_p),
                ('claimed', ctypes.POINTER(_c_p)),
                ('claimed_count', _size),
                ('remove', _REMOVE_FN),
                ('companions', ctypes.POINTER(_SyncCompanion)),
                ('companion_count', _size),
                ('repair', ctypes.c_int)]


class _SyncResult(ctypes.Structure):
    _fields_ = [('struct_version', ctypes.c_uint32),
                ('artifact', ctypes.c_char * SAVE_ENTRY_MAX),
                ('shape', ctypes.c_int),
                ('data', _u8p),
                ('len', _size),
                ('content_hash', ctypes.c_char * 33),
                ('identity_hash', ctypes.c_char * 33),
                ('changed', ctypes.c_int),
                ('conflict', ctypes.c_int),
                ('state', _u8p),
                ('state_len', _size),
                ('holding', _u8p),
                ('holding_len', _size),
                ('unowned', ctypes.POINTER(ctypes.c_char * CARD_NAME_MAX)),
                ('unowned_count', _size),
                ('restore_again', ctypes.c_int),
                ('companions', ctypes.POINTER(_SyncCompanionResult)),
                ('companion_count', _size),
                ('problem', ctypes.c_char * SAVE_PATH_MAX),
                ('blocks_short', ctypes.c_uint32),
                ('profiles', ctypes.POINTER(_SaveProfile)),
                ('profile_count', _size),
                ('profile', ctypes.c_char * PROFILE_ID_MAX),
                ('alternates', ctypes.POINTER(_SaveAlternate)),
                ('alternate_count', _size),
                ('hardcore_marker', ctypes.c_int),
                ('unowned_changed', _size)]


class _LayoutOption(ctypes.Structure):
    _fields_ = [('key', ctypes.c_char * 64),
                ('values', (ctypes.c_char * 32) * LAYOUT_OPTION_VALUES),
                ('value_count', _size),
                ('default_value', ctypes.c_char * 32)]


class _LayoutInfo(ctypes.Structure):
    _fields_ = [('id', ctypes.c_char * 64),
                ('platform', ctypes.c_char * 16),
                ('options', _LayoutOption * LAYOUT_OPTIONS),
                ('option_count', _size),
                ('region_option', ctypes.c_char * 64),
                ('profiles', ctypes.c_int),
                ('needs_existing', ctypes.c_int)]


# Every struct mirrored above, by its C name, for the layout test.
STRUCTS = {
    'sigil_result': _SigilResult,
    'sigil_save_option': _SaveOption,
    'sigil_save_profile': _SaveProfile,
    'sigil_save_alternate': _SaveAlternate,
    'sigil_save_request': _SaveRequest,
    'sigil_sync_companion': _SyncCompanion,
    'sigil_sync_companion_result': _SyncCompanionResult,
    'sigil_sync_request': _SyncRequest,
    'sigil_sync_result': _SyncResult,
    'sigil_layout_option': _LayoutOption,
    'sigil_layout_info': _LayoutInfo,
}

# ---- errors ----------------------------------------------------------------

ERR_CONFLICT = -9
ERR_NO_SPACE = -11
ERR_UNCOLLECTED = -12
ERR_DAMAGED = -13
ERR_REGION = -14
ERR_NO_TARGET = -15
ERR_AMBIGUOUS = -16


class SigilError(Exception):
    """A sigil call refused. ``code`` is the SIGIL_ERR_* value; ``problem``
    names the save, member or files at fault where sigil says (see
    sigil_restore in include/sigil.h)."""

    def __init__(self, code, message, problem='', profiles=(), blocks_short=0):
        super().__init__(f'{message} ({code})' + (f': {problem}' if problem else ''))
        self.code = code
        self.problem = problem
        self.profiles = profiles
        self.blocks_short = blocks_short


class SigilUnavailable(SigilError):
    def __init__(self):
        super().__init__(0, 'sigil library not loaded')


# ---- results ---------------------------------------------------------------

@dataclass(frozen=True)
class Game:
    """The game a unit belongs to, as title_ids' extraction read it. Fields
    left empty make sigil name saves after the content file, which is what
    most cartridge layouts do anyway."""
    platform: str = ''
    title_id: str = ''
    raw_serial: str = ''
    save_id: str = ''
    features: int = 0
    n64_header: str = ''
    n64_md5: str = ''
    n64_md5_n64: str = ''

    @classmethod
    def from_result(cls, platform, result):
        """From a sigil_result title_ids.extract returned (or None)."""
        if result is None:
            return cls(platform=platform or '')
        text = lambda b: b.decode('utf-8', 'replace')
        return cls(platform=platform or '', title_id=text(result.title_id),
                   raw_serial=text(result.raw_serial), save_id=text(result.save_id),
                   features=result.features, n64_header=text(result.n64_header),
                   n64_md5=text(result.n64_md5), n64_md5_n64=text(result.n64_md5_n64))


@dataclass(frozen=True)
class Profile:
    id: str
    name: str


@dataclass(frozen=True)
class LayoutOption:
    key: str
    values: tuple
    default: str


@dataclass(frozen=True)
class Layout:
    id: str
    platform: str
    options: tuple
    region_option: str
    profiles: bool
    needs_existing: bool


@dataclass(frozen=True)
class SyncResult:
    """What collect or restore produced. Keep ``state`` per game and layout
    and pass it back next time; it is how sigil tells a local change."""
    artifact: str
    shape: str
    data: Optional[bytes]
    content_hash: str
    identity_hash: str
    changed: bool
    state: bytes
    holding: Optional[bytes]
    unowned: tuple
    restore_again: bool
    profiles: tuple = ()
    profile: str = ''
    hardcore_marker: bool = False


# ---- the library -----------------------------------------------------------

_bound = None


def _lib():
    """The loaded library with the save functions typed, or None."""
    global _bound
    if _bound is not None:
        return _bound or None
    lib = _Sigil.get()._lib
    try:
        if lib is None:
            raise AttributeError
        lib.sigil_collect.argtypes = [ctypes.POINTER(_SyncRequest),
                                      ctypes.POINTER(ctypes.POINTER(_SyncResult))]
        lib.sigil_collect.restype = ctypes.c_int
        lib.sigil_restore.argtypes = [ctypes.POINTER(_SyncRequest), _u8p, _size,
                                      ctypes.POINTER(ctypes.POINTER(_SyncResult))]
        lib.sigil_restore.restype = ctypes.c_int
        lib.sigil_sync_result_free.argtypes = [ctypes.POINTER(_SyncResult)]
        lib.sigil_sync_result_free.restype = None
        lib.sigil_layouts.argtypes = [_c_p, ctypes.POINTER(ctypes.POINTER(_LayoutInfo)),
                                      ctypes.POINTER(_size)]
        lib.sigil_layouts.restype = ctypes.c_int
        lib.sigil_layouts_free.argtypes = [ctypes.POINTER(_LayoutInfo)]
        lib.sigil_layouts_free.restype = None
        lib.sigil_save_layout_subdirs.argtypes = [_c_p, ctypes.POINTER(_c_p), _size]
        lib.sigil_save_layout_subdirs.restype = _size
        lib.sigil_save_layout_top.argtypes = [_c_p]
        lib.sigil_save_layout_top.restype = _c_p
        lib.sigil_save_base.argtypes = [_c_p, _c_p, ctypes.c_char_p, _size,
                                        ctypes.c_char_p, _size]
        lib.sigil_save_base.restype = ctypes.c_int
        lib.sigil_io_open_file.argtypes = [_c_p]
        lib.sigil_io_open_file.restype = ctypes.c_void_p
        lib.sigil_platform_from_slug.argtypes = [_c_p]
        lib.sigil_platform_from_slug.restype = ctypes.c_int
    except AttributeError:
        # Not loaded, or a build older than sigil_collect (Oct 2026).
        _bound = False
        return None
    _bound = lib
    return lib


def available():
    """True when the loaded sigil can collect and restore."""
    return _lib() is not None


def _need():
    lib = _lib()
    if lib is None:
        raise SigilUnavailable()
    return lib


def _text(chars):
    return bytes(chars).split(b'\0', 1)[0].decode('utf-8', 'replace')


def _path_text(chars):
    return os.fsdecode(bytes(chars).split(b'\0', 1)[0])


def _bytes(ptr, length):
    return ctypes.string_at(ptr, length) if ptr and length else None


def _raise(lib, code, result=None):
    message = (lib.sigil_strerror(code) or b'').decode('utf-8', 'replace')
    problem, profiles, short = '', (), 0
    if result:
        r = result.contents
        problem = bytes(r.problem).split(b'\0', 1)[0].decode('utf-8', 'surrogateescape')
        profiles = _profiles(r)
        short = int(r.blocks_short)
        lib.sigil_sync_result_free(result)
    raise SigilError(code, message, problem, profiles, short)


def _profiles(r):
    return tuple(Profile(_text(r.profiles[i].id), _text(r.profiles[i].name))
                 for i in range(r.profile_count))


def layouts(platform=None):
    """The layout rows for ``platform`` (a RomM slug, aliases accepted), or
    every row: the libretro default first, then each row for that platform
    and each row that applies to any."""
    lib = _need()
    out = ctypes.POINTER(_LayoutInfo)()
    count = _size()
    code = lib.sigil_layouts(platform.encode('utf-8') if platform else None,
                             ctypes.byref(out), ctypes.byref(count))
    if code != 0:
        _raise(lib, code)
    try:
        rows = []
        for i in range(count.value):
            info = out[i]
            options = tuple(
                LayoutOption(_text(o.key),
                             tuple(_text(o.values[j]) for j in range(o.value_count)),
                             _text(o.default_value))
                for o in (info.options[k] for k in range(info.option_count)))
            rows.append(Layout(_text(info.id), _text(info.platform), options,
                               _text(info.region_option), bool(info.profiles),
                               bool(info.needs_existing)))
        return tuple(rows)
    finally:
        lib.sigil_layouts_free(out)


def layout_subdirs(layout):
    """Subfolders under the save root a layout writes into."""
    lib = _need()
    out = (_c_p * _SUBDIR_CAP)()
    n = lib.sigil_save_layout_subdirs(layout.encode('utf-8'), out, _SUBDIR_CAP)
    return [out[i].decode('utf-8') for i in range(min(n, _SUBDIR_CAP))]


def _layout_top(layout):
    top = _need().sigil_save_layout_top(layout.encode('utf-8'))
    return top.decode('utf-8') if top else None


def save_base(layout, path):
    """On a layout with profiles, the emulator's base folder for ``path`` and
    the profile folder ``path`` lies in ('' for none). Otherwise ``path``, ''."""
    lib = _need()
    base = ctypes.create_string_buffer(_PATH_CAP)
    profile = ctypes.create_string_buffer(PROFILE_ID_MAX)
    code = lib.sigil_save_base(layout.encode('utf-8'), os.fsencode(path), base, _PATH_CAP,
                               profile, PROFILE_ID_MAX)
    if code != 0:
        _raise(lib, code)
    return os.fsdecode(base.value), profile.value.decode('utf-8', 'replace')


def _bases_below(root, top):
    found = []

    def walk(directory, relative, depth):
        if depth == 0:
            return
        try:
            with os.scandir(directory) as it:
                entries = [e for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            return
        for entry in entries:
            if entry.name == top and relative:
                found.append(relative)
            elif entry.name != top:
                walk(entry.path, f'{relative}/{entry.name}' if relative else entry.name,
                     depth - 1)

    walk(root, '', _BASE_SEARCH_DEPTH)
    return found


def _list_recursive(directory, relative, depth, out):
    if depth == 0 or not os.path.isdir(directory):
        return
    with os.scandir(directory) as it:
        for entry in it:
            rel = f'{relative}/{entry.name}'
            if entry.is_file():
                out.append(rel)
            elif entry.is_dir():
                _list_recursive(entry.path, rel, depth - 1, out)


def list_save_root(root, layout):
    """Root-relative paths of the files in ``root`` and under the layout's
    subfolders: the listing collect and restore read. As upstream lists it."""
    root = os.fspath(root)
    out = []
    if os.path.isdir(root):
        with os.scandir(root) as it:
            out.extend(e.name for e in it if e.is_file())
    subdirs = layout_subdirs(layout)
    top = _layout_top(layout)
    bases = ['']
    if top and not os.path.isdir(os.path.join(root, top)):
        bases = _bases_below(root, top) or ['']
    for base in bases:
        for subdir in subdirs:
            relative = f'{base}/{subdir}' if base else subdir
            _list_recursive(os.path.join(root, relative), relative, _SUBDIR_LIST_DEPTH, out)
    return out


def _strings(keep, values):
    bufs = [ctypes.create_string_buffer(v) for v in values]
    keep.extend(bufs)
    arr = (_c_p * max(len(bufs), 1))(*[ctypes.cast(b, _c_p) for b in bufs])
    keep.append(arr)
    return arr, len(bufs)


def _sync(unit, game, layout, content_path, save_root, *, listing, options, game_ids,
          state, mode, overwrite_local, claimed, repair, profile):
    lib = _need()
    keep = []
    base, implied = save_base(layout, save_root)
    profile = profile or implied or None
    root_b = os.fsencode(base)
    if listing is None:
        listing = list_save_root(base, layout)

    def c(value):
        buf = ctypes.create_string_buffer(value if isinstance(value, bytes)
                                          else value.encode('utf-8'))
        keep.append(buf)
        return ctypes.cast(buf, _c_p)

    res = _SigilResult(struct_version=RESULT_V4)
    res.title_id = game.title_id.encode('utf-8')
    res.raw_serial = game.raw_serial.encode('utf-8')
    res.save_id = game.save_id.encode('utf-8')
    res.platform = lib.sigil_platform_from_slug(game.platform.encode('utf-8')) if game.platform else 0
    res.features = game.features
    res.n64_header = game.n64_header.encode('utf-8')
    res.n64_md5 = game.n64_md5.encode('utf-8')
    res.n64_md5_n64 = game.n64_md5_n64.encode('utf-8')
    keep.append(res)

    req = _SyncRequest(struct_version=SYNC_REQUEST_V1)
    s = req.save
    s.struct_version = SAVE_REQUEST_V1
    s.layout = c(layout)
    s.platform = c(game.platform) if game.platform else None
    s.content_path = c(os.fsencode(content_path))
    s.result = ctypes.pointer(res)
    s.features = game.features
    items = list((options or {}).items())
    opts = (_SaveOption * max(len(items), 1))()
    for i, (k, v) in enumerate(items):
        opts[i].key = c(k)
        opts[i].value = c(v)
    keep.append(opts)
    s.options = opts
    s.option_count = len(items)
    s.listing, s.listing_count = _strings(keep, [os.fsencode(p) for p in listing])
    s.root_path = c(root_b)
    if profile:
        s.profile = c(profile)

    req.game_ids, req.game_id_count = _strings(keep, [g.encode('utf-8') for g in game_ids])
    req.claimed, req.claimed_count = _strings(
        keep, [n.encode('utf-8', 'surrogateescape') for n in claimed])
    req.mode = SYNC_UNMANAGED if mode == 'unmanaged' else SYNC_MANAGED
    req.overwrite_local = 1 if overwrite_local else 0
    req.repair = 1 if repair else 0
    if state:
        sbuf = (ctypes.c_uint8 * len(state)).from_buffer_copy(state)
        keep.append(sbuf)
        req.state = sbuf
        req.state_len = len(state)

    def open_member(_ctx, rel):
        return lib.sigil_io_open_file(os.path.join(root_b, rel)) or None

    def write_member(_ctx, rel, data, length):
        path = os.path.join(root_b, rel)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + b'.part'
            with open(tmp, 'wb') as f:
                f.write(ctypes.string_at(data, length) if length else b'')
            os.replace(tmp, path)
        except OSError:
            return -1
        return 0

    def remove_member(_ctx, rel):
        try:
            if rel.endswith(b'/'):
                os.rmdir(os.path.join(root_b, rel))
            else:
                os.remove(os.path.join(root_b, rel))
        except OSError:
            return -1
        return 0

    callbacks = (_OPEN_FN(open_member), _WRITE_FN(write_member), _REMOVE_FN(remove_member))
    keep.extend(callbacks)
    s.open, req.write, req.remove = callbacks

    out = ctypes.POINTER(_SyncResult)()
    if unit is None:
        code = lib.sigil_collect(ctypes.byref(req), ctypes.byref(out))
    else:
        ubuf = (ctypes.c_uint8 * max(len(unit), 1)).from_buffer_copy(unit or b'\0')
        code = lib.sigil_restore(ctypes.byref(req), ubuf, len(unit), ctypes.byref(out))
    if code != 0:
        _raise(lib, code, out if out else None)
    r = out.contents
    try:
        return SyncResult(
            artifact=_path_text(r.artifact),
            shape=_SHAPES.get(r.shape, 'none'),
            data=_bytes(r.data, r.len),
            content_hash=_text(r.content_hash),
            identity_hash=_text(r.identity_hash),
            changed=bool(r.changed),
            state=_bytes(r.state, r.state_len) or b'',
            holding=_bytes(r.holding, r.holding_len),
            unowned=tuple(bytes(r.unowned[i]).split(b'\0', 1)[0].decode('utf-8', 'surrogateescape')
                          for i in range(r.unowned_count)),
            restore_again=bool(r.restore_again),
            profiles=_profiles(r),
            profile=_text(r.profile),
            hardcore_marker=bool(r.hardcore_marker),
        )
    finally:
        lib.sigil_sync_result_free(out)


def collect(game, layout, content_path, save_root, *, listing=None, options=None,
            game_ids=(), state=None, mode='managed', claimed=(), repair=False,
            profile=None):
    """``game``'s saves under ``save_root``, as ``layout`` keeps them, gathered
    into one unit (``data`` is None when there are none). Raises SigilError."""
    return _sync(None, game, layout, content_path, save_root, listing=listing,
                 options=options, game_ids=game_ids, state=state, mode=mode,
                 overwrite_local=False, claimed=claimed, repair=repair, profile=profile)


def restore(unit, game, layout, content_path, save_root, *, listing=None, options=None,
            game_ids=(), state=None, mode='managed', overwrite_local=False, claimed=(),
            repair=False, profile=None):
    """Write ``unit`` under ``save_root`` as ``layout`` keeps saves, then read
    it back. Every refusal (conflict, no space, no target, ambiguous...)
    writes nothing and raises SigilError naming the problem."""
    return _sync(bytes(unit), game, layout, content_path, save_root, listing=listing,
                 options=options, game_ids=game_ids, state=state, mode=mode,
                 overwrite_local=overwrite_local, claimed=claimed, repair=repair,
                 profile=profile)
