// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Post passes of team packages, the features post.layer and post.fullscreen.
//
// A team's layer pass works on the team's own objects alone. The page draws the whole scene into a
// small target writing depth only, then the team's players and effects with their own materials,
// so the target holds what of the team the camera sees, and a pass of the team draws from it onto
// the finished picture, a glow, an outline, pixels, a tint, a colour split, a blur or the team's
// own shader. A full screen pass works on the whole picture, only during the team's own moment,
// at most three seconds, at high quality, and never under reduced motion. Every pass's strength
// goes through the flash governor. The degrade ladder drops a team's passes at its rung noPasses.

import * as THREE from 'three';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';

export const TEAM_LAYERS = [10, 11];
export const PASSES = ['glow', 'outline', 'pixelate', 'tint', 'chromatic', 'blur', 'custom'];
// The passes that move the picture, which reduced motion leaves out.
export const DISTORTING = ['pixelate', 'chromatic'];
export const FULLSCREEN_SECONDS = 3;
// The events that make a team's own moment, when a full screen pass may play.
export const MOMENTS = ['goal', 'celebration.begin', 'winner.reveal', 'mvp.reveal', 'save', 'woodwork', 'reaction.begin', 'lineup.begin'];

const PASS_INDEX = { glow: 0, outline: 1, pixelate: 2, tint: 3, chromatic: 4, blur: 5 };

const VERTEX = `
varying vec2 vUv;
void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
}`;

const FRAGMENT = `
uniform sampler2D tSource;
uniform vec2 uTexel;
uniform int uPass;
uniform vec3 uColor;
uniform float uStrength;
uniform float uLayer;
varying vec2 vUv;
vec4 at(vec2 uv) { return texture2D(tSource, uv); }
vec4 blur(vec2 uv, float r) {
    vec4 s = vec4(0.0);
    float w = 0.0;
    for (int x = -2; x <= 2; x++) {
        for (int y = -2; y <= 2; y++) {
            float k = exp(-float(x * x + y * y) / 4.0);
            s += at(uv + vec2(float(x), float(y)) * uTexel * r) * k;
            w += k;
        }
    }
    return s / w;
}
void main() {
    vec4 c = at(vUv);
    vec4 o = vec4(0.0);
    if (uPass == 0) {
        vec4 b = blur(vUv, 2.5);
        o = vec4(uColor * b.a * uStrength, 0.0);
    } else if (uPass == 1) {
        float edge = 0.0;
        for (int i = 0; i < 8; i++) {
            float a = float(i) * 0.785398;
            edge = max(edge, at(vUv + vec2(cos(a), sin(a)) * uTexel * 1.5).a);
        }
        edge = clamp(edge - c.a, 0.0, 1.0);
        o = vec4(uColor * edge * uStrength, 0.0);
    } else if (uPass == 2) {
        vec2 cell = uTexel * (4.0 + 6.0 * uStrength);
        vec4 p = at((floor(vUv / cell) + 0.5) * cell);
        o = vec4(p.rgb, p.a * (uLayer > 0.5 ? 1.0 : clamp(uStrength, 0.0, 1.0)));
    } else if (uPass == 3) {
        o = vec4(mix(c.rgb, c.rgb * uColor * 1.6, clamp(uStrength, 0.0, 1.0)), c.a);
    } else if (uPass == 4) {
        vec2 d = uTexel * 3.0 * uStrength;
        vec4 r = at(vUv + d);
        vec4 b = at(vUv - d);
        o = uLayer > 0.5 ? vec4(r.r * r.a, 0.0, b.b * b.a, 0.0) : vec4(r.r, c.g, b.b, 1.0);
    } else {
        vec4 b = blur(vUv, 1.0 + 2.0 * uStrength);
        o = vec4(b.rgb, b.a);
    }
    // The layer target holds linear light without tone mapping, the picture is in sRGB.
    if (uLayer > 0.5 && (uPass == 2 || uPass == 3 || uPass == 5)) {
        o.rgb = pow(max(o.rgb, 0.0), vec3(0.4545));
    }
    gl_FragColor = o;
}`;

function passMaterial(blending) {
    return new THREE.ShaderMaterial({
        uniforms: {
            tSource: { value: null }, uTexel: { value: new THREE.Vector2() }, uPass: { value: 0 },
            uColor: { value: new THREE.Color(1, 1, 1) }, uStrength: { value: 1 }, uLayer: { value: 1 },
        },
        vertexShader: VERTEX, fragmentShader: FRAGMENT, depthTest: false, depthWrite: false, transparent: true,
        blending,
    });
}

// The blending each pass of a layer takes over the picture, additive for light it adds, normal
// for a look that covers the team's own.
function blendingOf(pass) {
    return pass === 'glow' || pass === 'outline' || pass === 'chromatic' ? THREE.AdditiveBlending : THREE.NormalBlending;
}

export class Post {
    constructor(presentation) {
        this.presentation = presentation;
        this.layers = [null, null];
        this.moments = [];
        this.target = null;
        this.frame = null;
        this.quad = null;
        this.depthOnly = new THREE.MeshBasicMaterial({ colorWrite: false });
        this.materials = { additive: passMaterial(THREE.AdditiveBlending), normal: passMaterial(THREE.NormalBlending), opaque: passMaterial(THREE.NoBlending) };
        this.drawn = 0;
        this.refused = [];
    }

    // The persistent layer passes of the packages on screen.
    attach(packages) {
        this.layers = [null, null];
        this.moments = [];
        for (const pkg of packages) {
            if (pkg && pkg.manifest.post && pkg.manifest.post.layer) {
                this.layers[pkg.side] = { pkg, spec: pkg.manifest.post.layer, transient: false };
            }
        }
    }

    allowed(pkg, scope, pass) {
        const p = this.presentation;
        const quality = pkg.budget.quality;
        if (pkg.budget.past('noPasses') || quality === 'low') {
            return 'the team is at a rung without passes or at low quality';
        }
        if (p.app.reducedMotion && (scope === 'fullscreen' || DISTORTING.includes(pass))) {
            return 'reduced motion';
        }
        if (scope === 'fullscreen' && (quality !== 'high' || !(pkg.budget.limits.fullscreen > 0))) {
            return 'a full screen pass needs high quality';
        }
        return null;
    }

    // A pass an effect of type post starts, from a reflex or a worker. A full screen pass plays on
    // the team's own moment alone, one at a time. Returns whether it was taken.
    spawn(pkg, spec, c, event) {
        const scope = spec.scope || 'layer';
        const refusal = this.allowed(pkg, scope, spec.pass);
        const own = event && event.team === pkg.side && MOMENTS.includes(event.kind);
        if (refusal || (scope === 'fullscreen' && (!own || this.moments.some((m) => m.scope === 'fullscreen')))) {
            this.refused.push(refusal || 'a full screen pass plays on the team’s own moment, one at a time');
            this.refused = this.refused.slice(-8);
            return false;
        }
        const now = this.presentation.clocks.cosmetic;
        const duration = Math.min(spec.duration || 1.5, scope === 'fullscreen' ? FULLSCREEN_SECONDS : 30);
        this.moments.push({ pkg, spec, scope, from: now, to: now + duration, id: c.id });
        return true;
    }

    endTransient() {
        this.moments = [];
    }

    active() {
        return this.layers.some(Boolean) || this.moments.length > 0;
    }

    ensure(renderer) {
        const size = renderer.getDrawingBufferSize(new THREE.Vector2());
        const w = Math.max(1, Math.floor(size.x / 2));
        const h = Math.max(1, Math.floor(size.y / 2));
        if (!this.target || this.target.width !== w || this.target.height !== h) {
            if (this.target) {
                this.target.dispose();
            }
            this.target = new THREE.WebGLRenderTarget(w, h, { depthBuffer: true });
        }
        if (!this.frame || this.frame.image.width !== size.x || this.frame.image.height !== size.y) {
            if (this.frame) {
                this.frame.dispose();
            }
            this.frame = new THREE.FramebufferTexture(size.x, size.y);
        }
        if (!this.quad) {
            this.quad = new FullScreenQuad(null);
        }
        return size;
    }

    // Lights light every layer, so the team's own objects keep their light in their own pass.
    lightLayers(scene) {
        const now = this.presentation.clocks.cosmetic;
        if (this.lit && now - this.lit < 2) {
            return;
        }
        this.lit = now;
        scene.traverse((o) => {
            if (o.isLight) {
                o.layers.enable(TEAM_LAYERS[0]);
                o.layers.enable(TEAM_LAYERS[1]);
            }
        });
    }

    // Draws the passes after the picture, called by the view once it rendered.
    render(renderer, scene, camera) {
        const p = this.presentation;
        const now = p.clocks.cosmetic;
        this.moments = this.moments.filter((m) => m.to > now);
        if (!this.active()) {
            return;
        }
        const size = this.ensure(renderer);
        const governor = p.flashFactor();
        const passes = [];
        for (const layer of this.layers) {
            if (layer && !this.allowed(layer.pkg, 'layer', layer.spec.pass)) {
                passes.push({ ...layer, scope: 'layer', fade: 1 });
            }
        }
        for (const m of this.moments) {
            const fade = Math.min(1, (now - m.from) / 0.3, (m.to - now) / 0.3);
            passes.push({ ...m, fade: Math.max(0, fade) });
        }
        const autoClear = renderer.autoClear;
        const clear = renderer.getClearColor(new THREE.Color());
        const alpha = renderer.getClearAlpha();
        const mask = camera.layers.mask;
        const background = scene.background;
        renderer.autoClear = false;
        try {
            for (const pass of passes) {
                const env = p.flash.envelope(`${pass.pkg.side}:post:${pass.scope}`);
                const strength = (pass.spec.strength ?? 1) * env.apply(now, pass.fade) * governor;
                if (strength <= 0.001) {
                    continue;
                }
                if (pass.scope === 'layer') {
                    this.lightLayers(scene);
                    scene.background = null;
                    renderer.setRenderTarget(this.target);
                    renderer.setClearColor(0x000000, 0);
                    renderer.clear();
                    scene.overrideMaterial = this.depthOnly;
                    renderer.render(scene, camera);
                    scene.overrideMaterial = null;
                    camera.layers.set(TEAM_LAYERS[pass.pkg.side]);
                    renderer.render(scene, camera);
                    camera.layers.mask = mask;
                    scene.background = background;
                    renderer.setRenderTarget(null);
                    this.draw(renderer, pass, this.target.texture, 1 / this.target.width, 1 / this.target.height, strength, true);
                } else {
                    renderer.setRenderTarget(null);
                    renderer.copyFramebufferToTexture(this.frame);
                    this.draw(renderer, pass, this.frame, 1 / size.x, 1 / size.y, strength, false);
                }
                this.drawn += 1;
            }
        } finally {
            scene.overrideMaterial = null;
            camera.layers.mask = mask;
            scene.background = background;
            renderer.setRenderTarget(null);
            renderer.setClearColor(clear, alpha);
            renderer.autoClear = autoClear;
        }
    }

    draw(renderer, pass, texture, tx, ty, strength, layer) {
        const spec = pass.spec;
        let material;
        if (spec.pass === 'custom') {
            material = this.presentation.customMaterial(pass.pkg, spec.shader, { blending: layer ? 'normal' : 'normal', depthWrite: false });
            if (!material) {
                return;
            }
            material.depthTest = false;
            material.uniforms.uLayer.value = layer ? texture : material.uniforms.uLayer.value;
            material.uniforms.uSceneColor.value = layer ? material.uniforms.uSceneColor.value : texture;
            material.uniforms.uIntensity.value = strength;
            if (!layer) {
                material.blending = THREE.NoBlending;
            }
        } else {
            material = layer ? (blendingOf(spec.pass) === THREE.AdditiveBlending ? this.materials.additive : this.materials.normal) : this.materials.opaque;
            const u = material.uniforms;
            u.tSource.value = texture;
            u.uTexel.value.set(tx, ty);
            u.uPass.value = PASS_INDEX[spec.pass] ?? 0;
            const c = Array.isArray(spec.color) && Array.isArray(spec.color[0]) ? spec.color[0] : spec.color || [255, 255, 255];
            u.uColor.value.setRGB(c[0] / 255, c[1] / 255, c[2] / 255, THREE.SRGBColorSpace);
            u.uStrength.value = layer ? strength : Math.min(1, strength);
            u.uLayer.value = layer ? 1 : 0;
        }
        this.quad.material = material;
        this.quad.render(renderer);
    }

    snapshot() {
        return {
            layers: this.layers.map((l) => (l ? l.spec.pass : null)),
            moments: this.moments.map((m) => ({ side: m.pkg.side, pass: m.spec.pass, scope: m.scope, left: m.to - this.presentation.clocks.cosmetic })),
            drawn: this.drawn, refused: this.refused.slice(),
        };
    }

    dispose() {
        if (this.target) {
            this.target.dispose();
        }
        if (this.frame) {
            this.frame.dispose();
        }
        if (this.quad) {
            this.quad.dispose();
        }
        this.target = null;
        this.frame = null;
        this.quad = null;
    }
}
