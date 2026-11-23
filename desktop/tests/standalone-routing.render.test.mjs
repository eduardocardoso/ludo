// A Switch 2 game is Lichii's, never Eden's, in the UI as in the launch.
//
// The UI used to match platform names by substring, so "Nintendo Switch 2"
// looked like a Switch game and Play said Eden (installed) would run it. It
// now reads the backend's routing table. Here Eden is installed and Lichii is
// not: a Switch 2 game must dim Play and name Lichii, and a Switch game must
// stay playable.
//
// Needs `npm run build` first, like routes.render.test.mjs.
import test, { before, after, describe } from "node:test";
import assert from "node:assert/strict";

import { distIsBuilt, launchBrowser, openRoute, startServer } from "./support/render-harness.mjs";
import { POPULATED_FIXTURES } from "./support/fixtures.mjs";

let playwright = null;
try {
  playwright = await import("playwright");
} catch {
  console.warn("[standalone-routing.render] playwright not installed — skipping");
}
const SKIP = !playwright ? "playwright is not installed"
  : !distIsBuilt() ? "no build — run `npm run build`" : false;

function fixturesFor(name, platform, slug) {
  const game = { rom_id: 42, name, platform, platform_slug: slug,
                 is_downloaded: true, has_cover: false };
  const group = { key: platform, label: platform, count: 1, downloaded: 1 };
  return {
    ...POPULATED_FIXTURES,
    get_library_groups: { success: true, mode: "platform", groups: [group] },
    get_library_games: { success: true, games: [game] },
    get_home_data: { success: true, continue_playing: [], recently_added: [game],
                     collections: [], platforms: [group] },
    get_game_detail: { ...POPULATED_FIXTURES.get_game_detail, name,
                       platform, platform_slug: slug },
  };
}

async function playHint(browser, origin, name, platform) {
  const r = await openRoute(browser, origin, "/romm-sync-library");
  try {
    await r.activateText("Platforms");
    await r.activateText(platform);
    await r.activateText(name, { key: "Shift+Enter" });
    await r.page.waitForTimeout(400);
    const p = await r.probe();
    assert.deepEqual(r.errors, [], "console errors");
    return p.text;
  } finally {
    await r.close();
  }
}

for (const [label, name, platform, slug, want, not] of [
  ["Switch 2 needs Lichii", "Switch Two Game", "Nintendo Switch 2", "switch-2",
   "Lichii is not installed — Nintendo Switch 2 needs it to play.", "Eden"],
  ["Switch stays with Eden", "Switch One Game", "Nintendo Switch", "switch",
   null, "is not installed"],
]) {
  describe(label, { skip: SKIP }, () => {
    let srv, browser;
    before(async () => {
      srv = await startServer({ fixtures: fixturesFor(name, platform, slug) });
      browser = await launchBrowser(playwright);
    });
    after(async () => {
      await browser?.close();
      await srv?.close();
    });

    test(`${platform} game page`, async () => {
      const text = await playHint(browser, srv.origin, name, platform);
      assert.ok(text.includes(name), `game page not open: ${text.slice(0, 300)}`);
      if (want) assert.ok(text.includes(want), `no Lichii hint: ${text.slice(0, 600)}`);
      assert.ok(!text.includes(not), `found ${JSON.stringify(not)}: ${text.slice(0, 600)}`);
    });
  });
}
