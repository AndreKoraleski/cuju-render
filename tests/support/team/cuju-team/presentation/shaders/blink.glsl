// The blink of the test package, a chunks shader over the standard material. Each player blinks
// by his own seed, and each half of the figure on its own, as independent eyes would. The uniform
// wake, which a behaviour drives by speed, keeps the eyes open longer at a run.

#include <cuju_noise>

float blinkOf(float seed, float side) {
    float period = 2.5 + 2.0 * cujuHash(vec2(seed * 91.7, side));
    float phase = fract(uTime / period + seed + side * 0.37);
    float shut = smoothstep(0.0, 0.04, phase) * (1.0 - smoothstep(0.04, 0.09, phase));
    return shut * (1.0 - 0.6 * wake);
}

vec4 cujuColor(vec4 color, vec2 uv) {
    float side = step(0.5, uv.x);
    return vec4(color.rgb * (1.0 - 0.7 * blinkOf(blinkSeed, side)), color.a);
}

vec3 cujuEmissive(vec3 emissive, vec2 uv) {
    float side = step(0.5, uv.x);
    return emissive * (1.0 - blinkOf(blinkSeed, side)) + uTeamColor * 0.25 * uPulse * uIntensity;
}
