// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the offer to install the page as an app, run from the repository root with
// `node tests/web/install_offer.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-install-offer-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/help/install-state.js', import.meta.url)), join(folder, 'help/install-state.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));

// A window of the page as boot.js leaves it, and the events it sends.
const sent = [];
globalThis.window = {
    cujuInstall: { prompt: null, installed: false },
    dispatchEvent: (event) => sent.push(event.type),
    addEventListener: () => {},
    matchMedia: () => ({ matches: false }),
    navigator: {},
};
const {
    QUIET_VISITS, countVisit, dismissOffer, heldPrompt, installRoute, installedNow, offerShown, offerState,
    promptInstall, runsAsApp,
} = await import(pathToFileURL(join(folder, 'help/install-state.js')).href);
// installedNow reads the page itself, which here is a page in a tab.
globalThis.matchMedia = () => ({ matches: false });

const offer = { prompt: async () => {}, userChoice: Promise.resolve({ outcome: 'accepted' }) };
const shown = (over = {}) => offerShown({
    state: { visits: QUIET_VISITS + 1 }, prompt: offer, installed: false, page: 'home', busy: false, ...over,
});

test('the offer shows on Home from the second visit, once the browser offers to install', () => {
    assert.equal(QUIET_VISITS, 1);
    assert.equal(shown(), true);
    assert.equal(shown({ state: countVisit(null) }), false);
    assert.equal(shown({ state: countVisit(countVisit(null)) }), true);
    assert.equal(shown({ prompt: null }), false);
    assert.equal(shown({ page: 'watch' }), false);
    assert.equal(shown({ busy: true }), false);
});

test('a dismissed offer stays away for good, and an installed page shows none', () => {
    const dismissed = dismissOffer({ visits: 5 });
    assert.deepEqual(dismissed, { dismissed: true, visits: 5 });
    assert.equal(shown({ state: dismissed }), false);
    assert.equal(shown({ state: countVisit(dismissed) }), false);
    assert.equal(shown({ installed: true }), false);
});

test('a stored state keeps only what it should', () => {
    assert.deepEqual(offerState(null), { dismissed: false, visits: 0 });
    assert.deepEqual(offerState('yes'), { dismissed: false, visits: 0 });
    assert.deepEqual(offerState({ dismissed: 'yes', visits: -3 }), { dismissed: false, visits: 0 });
    assert.deepEqual(offerState({ dismissed: true, visits: 2.5 }), { dismissed: true, visits: 0 });
    assert.deepEqual(offerState({ visits: 1e9 }), { dismissed: false, visits: 1000 });
    assert.deepEqual(countVisit({ visits: 1000 }), { dismissed: false, visits: 1000 });
});

test('each browser has its route, its own offer, the Dock of Safari or the command', () => {
    const mac = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15';
    const chrome = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
    const firefox = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0';
    const ios = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
    assert.equal(installRoute({ hasEvent: true, userAgent: chrome, vendor: 'Google Inc.' }), 'browser');
    assert.equal(installRoute({ hasEvent: false, userAgent: mac, vendor: 'Apple Computer, Inc.' }), 'safari');
    assert.equal(installRoute({ hasEvent: false, userAgent: firefox, vendor: '' }), 'command');
    assert.equal(installRoute({ hasEvent: false, userAgent: ios, vendor: 'Apple Computer, Inc.' }), 'command');
    assert.equal(installRoute({ hasEvent: false, userAgent: mac.replace('Version/17.5', 'Chrome/131.0'), vendor: 'Apple Computer, Inc.' }), 'command');
});

test('a page runs as an app when installed, added to the Dock or in the system web view', () => {
    assert.equal(runsAsApp({ matchMedia: () => ({ matches: false }), navigator: {} }), false);
    assert.equal(runsAsApp({ matchMedia: (q) => ({ matches: q === '(display-mode: standalone)' }), navigator: {} }), true);
    assert.equal(runsAsApp({ navigator: { standalone: true } }), true);
    assert.equal(runsAsApp({ navigator: {}, pywebview: {} }), true);
});

test('the browser offer shows once, and a second ask finds none', async () => {
    assert.deepEqual(await promptInstall(), { outcome: 'unavailable' });
    let asked = 0;
    window.cujuInstall.prompt = { prompt: async () => asked++, userChoice: Promise.resolve({ outcome: 'dismissed' }) };
    assert.ok(heldPrompt());
    assert.deepEqual(await promptInstall(), { outcome: 'dismissed' });
    assert.equal(asked, 1);
    assert.equal(heldPrompt(), null);
    assert.deepEqual(sent, ['cuju-install']);
    assert.deepEqual(await promptInstall(), { outcome: 'unavailable' });
    assert.equal(installedNow(), false);
    window.cujuInstall.installed = true;
    assert.equal(installedNow(), true);
});
