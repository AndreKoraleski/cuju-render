// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of web/js/boot.js, which reloads the page once when a module of the page fails to load, run
// from the repository root with `node tests/web/boot.mjs`.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../src/cuju/render/web/js/boot.js', import.meta.url), 'utf8');

// Runs boot.js in a window of its own and returns a way to fail a script and the reloads it made.
function page({ storage = true, now = () => 1e12 } = {}) {
    const listeners = [];
    const store = new Map();
    const reloads = [];
    const timers = [];
    const window = {
        addEventListener: (type, fn, capture) => listeners.push({ type, fn, capture }),
    };
    const context = {
        window,
        console: { warn() {} },
        location: { reload: () => reloads.push(now()) },
        setTimeout: (fn, ms) => timers.push({ fn, ms }),
        Date: { now },
        Number,
        String,
        sessionStorage: storage ? {
            getItem: (key) => (store.has(key) ? store.get(key) : null),
            setItem: (key, value) => store.set(key, String(value)),
        } : {
            getItem: () => {
                throw new Error('no storage');
            },
            setItem: () => {
                throw new Error('no storage');
            },
        },
    };
    vm.runInNewContext(source, context);
    const fail = (target) => {
        for (const l of listeners.filter((x) => x.type === 'error')) {
            l.fn({ target });
        }
        for (const timer of timers.splice(0)) {
            timer.fn();
        }
    };
    return { listeners, fail, reloads, window, store };
}

const moduleScript = { tagName: 'SCRIPT', type: 'module' };

test('a module that fails to load reloads the page once, after a moment', () => {
    const { listeners, fail, reloads, store } = page();
    assert.equal(listeners.length, 1);
    assert.equal(listeners[0].capture, true);
    fail(moduleScript);
    assert.equal(reloads.length, 1);
    assert.ok(store.has('cuju.bootRetry'));
    // A second failure within the minute, as from a server that is gone, leaves the page.
    fail(moduleScript);
    assert.equal(reloads.length, 1);
});

test('other errors, a started page and a page without storage stay as they are', () => {
    const { fail, reloads, window } = page();
    fail({ tagName: 'IMG' });
    fail({ tagName: 'SCRIPT', type: '' });
    fail(null);
    window.cuju = {};
    fail(moduleScript);
    assert.equal(reloads.length, 0);
    const bare = page({ storage: false });
    bare.fail(moduleScript);
    assert.equal(bare.reloads.length, 0);
});
