"""A downloaded Switch 2 game never goes through Eden's add-on install.

A Switch 2 Edition upgrade is a switch-2 ROM whose container carries a Switch
("01") ID, so nothing in the content readers keeps it out of Eden's NAND. Its
Platform routes to Lichii, and that is what skips the Eden add-on handling.

Run with:  pytest app/tests
"""
import asyncio
from pathlib import Path

import pytest

from ludo_app import backend as backend_mod
from ludo_app.backend import LudoBackend
from ludo_app.host import HostProfile

DESKTOP = HostProfile("1.0.0", "-x86_64.AppImage", Path("/tmp/desk-rt"), "desktop")
ROM = 77


class StubClient:
    authenticated = True

    def download_rom(self, rom_id, name, dest, progress_callback=None,
                     cancellation_checker=None, file_ids=None):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b'x' * 64)
        return True, "Download successful"


def _backend(monkeypatch, tmp_path, slug):
    monkeypatch.setenv("HOME", str(tmp_path))
    b = LudoBackend(host=DESKTOP)
    b._download_progress = {}
    b._download_cancels = set()
    b._romm_client = StubClient()
    monkeypatch.setattr(b, "_games_index", lambda: {ROM: {
        'name': 'Zelda TOTK NS2 Edition', 'platform_slug': slug,
        'file_name': 'Zelda TOTK NS2 Edition [0100F2C0115B6800].nsp'}})
    b._settings = type("S", (), {"get": lambda self, *a: str(tmp_path / "roms")})()
    monkeypatch.setattr(b, "_rom_exists_on_server", lambda rid: True)
    monkeypatch.setattr(backend_mod, "_record_activity", lambda *a, **k: None)
    b._maybe_unzip_download = lambda dest, rid, slug=None: dest
    b._maybe_decompress_switch = lambda p, rid: p
    b._persist_snapshot_throttled = lambda: None
    b.handled = []
    b._handle_switch_add_ons = lambda rid, path, *a: b.handled.append(Path(path).name)
    return b


async def _settle(b, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        state = (await b.get_download_progress(ROM))['state']
        if state not in ('downloading', 'extracting'):
            return state
        await asyncio.sleep(0.02)
    raise AssertionError("download never finished")


@pytest.mark.parametrize('slug, handled', [
    ('switch-2', []),
    ('switch', ['Zelda TOTK NS2 Edition [0100F2C0115B6800].nsp']),
])
async def test_only_a_game_routed_to_eden_gets_eden_add_on_handling(
        monkeypatch, tmp_path, slug, handled):
    b = _backend(monkeypatch, tmp_path, slug)
    assert (await b.download_game(ROM))['success']
    assert await _settle(b) == 'done'
    assert b.handled == handled
