// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Freezes the built in objects of the page's AudioWorklet scope after the renderer's own
// processors loaded and before a team's module loads, so a package's processors share the scope
// with the renderer's meters and limiters and change none of what those read.

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
