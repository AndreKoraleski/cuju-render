// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Freezes the built in objects of the page's AudioWorklet scope after the renderer's own
// processors loaded, so nothing that loads after them changes what its meters and limiters read.
// A team's module loads into an audio context of the team's own, teamaudio.js, and never into
// this scope.

for (const value of [Math, Number, Object, Array, Float32Array, Float64Array, Int32Array, Uint8Array, Symbol, Reflect, JSON]) {
    Object.freeze(value);
    if (value.prototype) {
        Object.freeze(value.prototype);
    }
}
Object.freeze(Object.getPrototypeOf(Float32Array));
Object.freeze(Object.getPrototypeOf(Float32Array).prototype);
for (const name of ['registerProcessor', 'AudioWorkletProcessor', 'currentTime', 'sampleRate']) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
    if (descriptor && descriptor.configurable) {
        Object.defineProperty(globalThis, name, { ...descriptor, configurable: false, ...('value' in descriptor ? { writable: false } : {}) });
    }
}
