"""Eden-family emulators: what differs between them, and nothing else.

An Eden-family emulator shares Eden's data layout (nand/user/save, keys/,
load/), its qt-config.ini format, its profiles.dat user list and its command
line. Only the values below differ between members, so the Eden code in
emulator_saves, eden_config, eden_users and profiles takes one of these
records instead of hard-coding Eden's.

This module imports nothing from the rest of the engine, so any of those
modules can import it without a cycle.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EdenVariant:
    # STANDALONE_EMULATORS key.
    key: str
    # Shown in the UI, and the Emulator label saves are uploaded with.
    name: str
    # Most specific first. Listed in full, never derived from `key`.
    data_dirs: tuple
    config_dirs: tuple
    # Environment variable that overrides the data directory.
    data_dir_env: str
    # [Emulators] setting naming the data directory.
    settings_key: str
    # profiles.json key holding the Profile's Emulator user uuid.
    profile_key: str
    # /proc comm prefixes. Listed explicitly: names are never derived.
    process_names: tuple
    # Name of the user written when Ludo creates the user list itself.
    default_user_name: str


EDEN = EdenVariant(
    key='eden',
    name='Eden',
    data_dirs=(
        # Flatpak (dev.eden_emu.eden) redirects XDG_DATA_HOME into its sandbox.
        '~/.var/app/dev.eden_emu.eden/data/eden',
        # Native, AppImage, and anything else honouring XDG_DATA_HOME.
        '~/.local/share/eden',
    ),
    config_dirs=(
        '~/.var/app/dev.eden_emu.eden/config/eden',
        '~/.config/eden',
    ),
    data_dir_env='EDEN_DATA_DIR',
    settings_key='eden_data_dir',
    profile_key='eden_user',
    process_names=('eden',),
    default_user_name='Eden',
)

# The Eden fork that runs Switch 2 games. AppImage only, so no flatpak folders.
LICHII = EdenVariant(
    key='lichii',
    name='Lichii',
    data_dirs=('~/.local/share/lichii',),
    config_dirs=('~/.config/lichii',),
    data_dir_env='LICHII_DATA_DIR',
    settings_key='lichii_data_dir',
    profile_key='lichii_user',
    # Prefixes, so 'lichii.appimage' and the release's 'lichii-linux-x86_64'
    # match too. Neither name is a prefix of the other's, so a running Eden is
    # never taken for Lichii, nor the reverse.
    process_names=('lichii',),
    default_user_name='Lichii',
)

VARIANTS = (EDEN, LICHII)


def variant_for_key(key):
    """The Eden-family emulator launched under STANDALONE_EMULATORS ``key``,
    or None when ``key`` is not one."""
    return next((v for v in VARIANTS if v.key == key), None)
