"""The desktop updater keeps each architecture on its own AppImage.

The AppImage is built for x86_64 and for aarch64, and one release carries
both. Two things keep a machine on the right one: the asset suffix it selects
(each suffix is never the tail of the other) and an ELF check before the swap,
so a wrong-arch download can't replace a working install with one that won't
start.

Run with:  pytest app/tests
"""
import asyncio
import struct

import pytest

from ludo_app import backend

RELEASE = {"tag_name": "v1.1.0", "prerelease": False, "assets": [
    {"name": "Ludo-v1.1.0-decky.zip"},
    {"name": "Ludo-v1.1.0-x86_64.AppImage"},
    {"name": "Ludo-v1.1.0-aarch64.AppImage"},
]}


@pytest.mark.parametrize("suffix, expected", [
    ("-x86_64.AppImage", "Ludo-v1.1.0-x86_64.AppImage"),
    ("-aarch64.AppImage", "Ludo-v1.1.0-aarch64.AppImage"),
    ("-decky.zip", "Ludo-v1.1.0-decky.zip"),
])
def test_each_suffix_selects_only_its_own_asset(suffix, expected):
    assert backend._release_asset(RELEASE, suffix)["name"] == expected


def elf(machine, little=True):
    """The first 20 bytes of an ELF64 executable for `machine`."""
    order = "<" if little else ">"
    return (b"\x7fELF" + bytes([2, 1 if little else 2, 1]) + bytes(9)
            + struct.pack(order + "HH", 2, machine))


X86_64, AARCH64 = 0x3E, 0xB7


@pytest.mark.parametrize("here, built_for, ok", [
    ("x86_64", X86_64, True),
    ("aarch64", AARCH64, True),
    ("AMD64", X86_64, True),        # the spelling Windows-built Pythons report
    ("arm64", AARCH64, True),       # ...and macOS's
    ("x86_64", AARCH64, False),
    ("aarch64", X86_64, False),
    ("riscv64", X86_64, True),      # no AppImage for this machine: not judged
    ("aarch64", 0xF3, True),        # unknown e_machine: not judged
])
def test_elf_arch_mismatch(monkeypatch, here, built_for, ok):
    monkeypatch.setattr("platform.machine", lambda: here)
    assert (backend._elf_arch_mismatch(elf(built_for)) is None) == ok


def test_big_endian_header_is_read_in_its_own_byte_order(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "aarch64")
    assert backend._elf_arch_mismatch(elf(AARCH64, little=False)) is None
    assert backend._elf_arch_mismatch(elf(X86_64, little=False))


def test_wrong_arch_update_leaves_the_install_alone(monkeypatch, tmp_path):
    installed = tmp_path / "Ludo.AppImage"
    installed.write_bytes(elf(AARCH64) + b"current build")
    download = tmp_path / "update.AppImage"
    download.write_bytes(elf(X86_64) + b"wrong arch")
    monkeypatch.setenv("APPIMAGE", str(installed))
    monkeypatch.setattr("platform.machine", lambda: "aarch64")

    be = backend.LudoBackend.__new__(backend.LudoBackend)
    result = asyncio.run(be.apply_appimage_update(str(download)))

    assert result["success"] is False
    assert "x86_64" in result["message"] and "aarch64" in result["message"]
    assert installed.read_bytes().endswith(b"current build")
    assert download.exists()
