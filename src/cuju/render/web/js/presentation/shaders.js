// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Custom shaders of team packages, the features shader.custom and shader.sceneColor.
//
// A package's .glsl file passed the server's static checks, _glsl.py, and the page runs the same
// main rules again before it compiles anything. The renderer writes every uniform a shader may
// read in front of its text, so a file declares none of its own.
//
// In the mode chunks a shader extends the renderer's standard material through hook functions,
// cujuVertex, cujuColor, cujuEmissive, cujuRoughness and cujuMetalness, which the page calls at
// their places, so skinning, lights, fog and tone mapping stay the renderer's. The same chunk
// adds the team's local lights, which light the team's own materials alone. In the mode material
// a shader is a whole ShaderMaterial for the package's own objects, a vertex section and a
// fragment section. Each distinct file and mode is one program of the team's shader budget, and a
// shader that fails to compile falls back to the standard material with a notice.

import * as THREE from 'three';
import { HOOKS, MODES, checkShader } from './glsl.js';

export const LOCAL_LIGHTS = 8;
// The uniforms the renderer gives every shader, with their GLSL types.
export const UNIFORMS = {
    uTime: 'float', uSim: 'float', uCeremony: 'float', uSeed: 'float', uTeamColor: 'vec3', uTeamColor2: 'vec3',
    uPulse: 'float', uSpeed: 'float', uExcitement: 'float', uBall: 'vec3', uResolution: 'vec2', uIntensity: 'float',
    uSceneColor: 'sampler2D', uLayer: 'sampler2D',
};

// The one include a package may name, value noise and a hash by seed.
export const NOISE = `
float cujuHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
float cujuNoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(cujuHash(i), cujuHash(i + vec2(1.0, 0.0)), u.x), mix(cujuHash(i + vec2(0.0, 1.0)), cujuHash(i + vec2(1.0, 1.0)), u.x), u.y);
}
`;

// The vertex and fragment sections of a material shader, with what comes before the vertex
// section shared by both.
export function sections(text) {
    const code = String(text).replace(/#\s*include\s*<cuju_noise>/g, NOISE);
    const v = code.indexOf('#pragma cuju vertex');
    const f = code.indexOf('#pragma cuju fragment');
    const shared = code.slice(0, v);
    return { vertex: shared + code.slice(v + 19, f), fragment: shared + code.slice(f + 21) };
}

const BLACK = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
BLACK.needsUpdate = true;

// The uniforms one team shares across its shaders, and those of each instance, its seed.
export function teamUniforms() {
    return {
        uTime: { value: 0 }, uSim: { value: 0 }, uCeremony: { value: 0 }, uTeamColor: { value: new THREE.Color(1, 1, 1) },
        uTeamColor2: { value: new THREE.Color(0.2, 0.2, 0.2) }, uPulse: { value: 0 }, uExcitement: { value: 0 },
        uBall: { value: new THREE.Vector3() }, uResolution: { value: new THREE.Vector2(1, 1) }, uIntensity: { value: 1 },
        uSceneColor: { value: BLACK }, uLayer: { value: BLACK },
        cujuLocalPos: { value: Array.from({ length: LOCAL_LIGHTS }, () => new THREE.Vector3()) },
        cujuLocalColor: { value: Array.from({ length: LOCAL_LIGHTS }, () => new THREE.Vector3()) },
        cujuLocalRange: { value: new Array(LOCAL_LIGHTS).fill(1) },
    };
}

function ownUniforms(spec, seeds, textures) {
    const out = {};
    for (const [name, value] of Object.entries((spec && spec.uniforms) || {})) {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
            out[name] = { value: ((seeds && seeds[value.seed]) >>> 0) / 4294967296 };
        } else if (Array.isArray(value)) {
            out[name] = { value: value.length === 2 ? new THREE.Vector2(...value) : value.length === 3 ? new THREE.Vector3(...value) : new THREE.Vector4(...value) };
        } else {
            out[name] = { value: Number(value) || 0 };
        }
    }
    for (const [name, texture] of Object.entries(textures || {})) {
        out[name] = { value: texture };
    }
    return out;
}

function glslType(u) {
    const v = u.value;
    return v && v.isTexture ? 'sampler2D' : v && v.isVector4 ? 'vec4' : v && v.isVector3 ? 'vec3' : v && v.isVector2 ? 'vec2' : 'float';
}

function uniformBlock(shared, own) {
    const lines = Object.entries(UNIFORMS).map(([name, type]) => `uniform ${type} ${name};`);
    for (const [name, u] of Object.entries(own)) {
        lines.push(`uniform ${glslType(u)} ${name};`);
    }
    return lines.join('\n');
}

const LOCAL_CHUNK = `
uniform vec3 cujuLocalPos[${LOCAL_LIGHTS}];
uniform vec3 cujuLocalColor[${LOCAL_LIGHTS}];
uniform float cujuLocalRange[${LOCAL_LIGHTS}];
vec3 cujuLocalLight(vec3 viewPosition, vec3 viewNormal, vec3 albedo) {
    vec3 sum = vec3(0.0);
    for (int i = 0; i < ${LOCAL_LIGHTS}; i++) {
        vec3 d = cujuLocalPos[i] - viewPosition;
        float r = max(cujuLocalRange[i], 0.01);
        float fall = clamp(1.0 - dot(d, d) / (r * r), 0.0, 1.0);
        sum += cujuLocalColor[i] * albedo * fall * fall * max(dot(normalize(d), viewNormal), 0.0);
    }
    return sum;
}
`;

// Gives a material of a team's player the team's chunk, the hooks of a chunks shader when it has
// one and the local lights, on a copy the caller owns. shared holds the team's uniforms, seed the
// instance's seed, source the shader text or null, key the program's cache key. Returns the
// copy, whose userData.cuju lists its uniforms.
export function extendMaterial(material, { shared, seed = 0, source = null, spec = null, textures = null, key = 'local' }) {
    const copy = material.clone();
    const own = ownUniforms(spec, spec && spec.seeds, textures);
    const code = source ? String(source).replace(/#\s*include\s*<cuju_noise>/g, NOISE) : '';
    const has = (name) => new RegExp(`\\b${name}\\s*\\(`).test(code);
    const instance = { uSeed: { value: (seed >>> 0) / 4294967296 }, uSpeed: { value: 0 } };
    copy.userData.cuju = { shared, instance, own, key };
    if (code) {
        // The hooks read the texture coordinates, which three.js passes when USE_UV is defined.
        copy.defines = { ...(copy.defines || {}), USE_UV: '' };
    }
    copy.onBeforeCompile = (shader) => {
        Object.assign(shader.uniforms, shared, instance, own);
        const head = `${uniformBlock(shared, own)}\n${LOCAL_CHUNK}\n${code}\n`;
        shader.vertexShader = shader.vertexShader.replace('#include <common>', `#include <common>\n${uniformBlock(shared, own)}\n${has('cujuVertex') ? code : ''}`);
        if (has('cujuVertex')) {
            shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\ntransformed = cujuVertex(transformed, objectNormal);');
        }
        let fs = shader.fragmentShader.replace('#include <common>', `#include <common>\n${head}`);
        const uv = /\bvUv\b/.test(fs) ? 'vUv' : 'vec2(0.0)';
        if (has('cujuColor')) {
            fs = fs.replace('#include <color_fragment>', `#include <color_fragment>\ndiffuseColor = cujuColor(diffuseColor, ${uv});`);
        }
        if (has('cujuRoughness')) {
            fs = fs.replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>\nroughnessFactor = cujuRoughness(roughnessFactor, ${uv});`);
        }
        if (has('cujuMetalness')) {
            fs = fs.replace('#include <metalnessmap_fragment>', `#include <metalnessmap_fragment>\nmetalnessFactor = cujuMetalness(metalnessFactor, ${uv});`);
        }
        const emissive = has('cujuEmissive') ? `totalEmissiveRadiance = cujuEmissive(totalEmissiveRadiance, ${uv});\n` : '';
        fs = fs.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>\n${emissive}totalEmissiveRadiance += cujuLocalLight(-vViewPosition, normal, diffuseColor.rgb);`);
        shader.fragmentShader = fs;
    };
    // Players sharing a shader share its program, each with uniforms of its own.
    copy.customProgramCacheKey = () => `cuju:${key}:${has('cujuVertex') ? 'v' : ''}`;
    copy.needsUpdate = true;
    return copy;
}

// A whole ShaderMaterial of a material mode shader, for the package's own objects.
export function shaderMaterial(source, { shared, seed = 0, spec = null, textures = null, transparent = true, blending = 'normal', side = 'front', depthWrite = false } = {}) {
    const { vertex, fragment } = sections(source);
    const own = ownUniforms(spec, spec && spec.seeds, textures);
    const uniforms = { ...shared, uSeed: { value: (seed >>> 0) / 4294967296 }, uSpeed: { value: 0 }, ...own };
    const block = uniformBlock(shared, own);
    const material = new THREE.ShaderMaterial({
        uniforms,
        vertexShader: `${block}\n${vertex}`,
        fragmentShader: `${block}\n${fragment}`,
        transparent,
        depthWrite,
        blending: blending === 'additive' ? THREE.AdditiveBlending : THREE.NormalBlending,
        side: side === 'double' ? THREE.DoubleSide : side === 'back' ? THREE.BackSide : THREE.FrontSide,
    });
    material.userData.cuju = { shared, own };
    return material;
}

// Whether a material compiled, after renderer.compile, by the diagnostics three.js keeps.
export function compiled(renderer, material) {
    const props = renderer.properties.get(material);
    const program = props && props.currentProgram;
    if (!program) {
        return true;
    }
    return !(program.diagnostics && program.diagnostics.runnable === false);
}

// Compiles a material on a throwaway mesh, and returns whether it compiled. A WebGL context lost
// on the way, or a renderer without compile, counts as compiled, and the page tries again later.
export function tryCompile(renderer, material, camera, skinned = null) {
    if (!renderer || typeof renderer.compile !== 'function') {
        return true;
    }
    const scene = new THREE.Scene();
    const mesh = skinned || new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material);
    if (skinned) {
        mesh.material = material;
    }
    scene.add(mesh);
    const checks = renderer.debug.checkShaderErrors;
    renderer.debug.checkShaderErrors = true;
    let ok = true;
    const report = renderer.debug.onShaderError;
    renderer.debug.onShaderError = () => {
        ok = false;
    };
    try {
        renderer.compile(scene, camera);
        // three.js checks a program for errors on its first use, so the check asks for its
        // uniforms here, while this function hears the errors.
        const props = renderer.properties.get(material);
        const program = props && props.currentProgram;
        if (program && typeof program.getUniforms === 'function') {
            program.getUniforms();
        }
        ok = ok && compiled(renderer, material);
    } catch {
        ok = false;
    } finally {
        renderer.debug.onShaderError = report;
        renderer.debug.checkShaderErrors = checks;
        scene.remove(mesh);
        if (!skinned) {
            mesh.geometry.dispose();
        }
    }
    return ok;
}

export { HOOKS, MODES, checkShader };
