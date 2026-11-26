// Herdr focused pane neon bloom shader for Ghostty (macOS Metal / GLSL 430)
// Selectively adds a crisp inner aura + soft outer bloom around Herdr's accent
// color (#18ecff) so focused split-pane borders glow without blurring terminal text.
//
// Perf: ~57 texture fetches per pixel (was ~201). Glow samples sit on half-pixel
// offsets with a 2px stride, so each bilinear fetch covers TWO texels; the sample
// mask accepts a 50/50 accent/background blend as a full hit, so even 1px-thin
// borders are never skipped between samples.
// If you ever see striped/banded glow, your build is sampling iChannel0 with
// nearest filtering: restore the .bak copy of this file (1px stride).

// --- Tunable parameters ---
const vec3  ACCENT_COLOR    = vec3(0.0941, 0.9255, 1.0000); // #18ecff (must match herdr config.toml)
const vec3  BG_REF_COLOR    = vec3(0.1412, 0.1529, 0.2275); // #24273a (Catppuccin Macchiato base)
const float INNER_SIGMA     = 3.5;                          // Tight neon aura radius (px)
const float INNER_STRENGTH  = 0.34;                         // Tight neon aura intensity (was 0.42)
const float OUTER_SIGMA     = 10.5;                         // Wide soft bloom radius (px)
const float OUTER_STRENGTH  = 0.22;                         // Wide soft bloom intensity (was 0.28)
const float CORE_HOT_BOOST  = 0.12;                         // Bright core lift on the stroke itself (was 0.22); keeps the active tab from glaring

// Returns [0, 1] for colors matching ACCENT_COLOR or lying on the BG→ACCENT blend line.
// coverageLo/Hi gate how much accent coverage (t) a blended color needs to count.
float accentMaskT(vec3 c, float coverageLo, float coverageHi, float perpLo, float perpHi) {
    float d = length(c - ACCENT_COLOR);
    float mDirect = 1.0 - smoothstep(0.03, 0.09, d);

    vec3 ab = ACCENT_COLOR - BG_REF_COLOR;
    vec3 cb = c - BG_REF_COLOR;
    float t = clamp(dot(cb, ab) / dot(ab, ab), 0.0, 1.0);
    float perpD = length(cb - t * ab);
    float mAA = (1.0 - smoothstep(perpLo, perpHi, perpD)) * smoothstep(coverageLo, coverageHi, t);

    return max(mDirect, mAA);
}

// Center pixel: strict (only real accent strokes and their anti-aliased core).
float accentMaskCenter(vec3 c) {
    return accentMaskT(c, 0.45, 0.85, 0.02, 0.065);
}

// Glow sample: a bilinear fetch straddling 2 texels sees a 1px accent line as ~50% coverage.
float accentMaskSample(vec3 c) {
    return accentMaskT(c, 0.30, 0.50, 0.03, 0.08);
}

float glowFalloff(float distPx) {
    float d2 = distPx * distPx;
    float inner = exp(-d2 / (2.0 * INNER_SIGMA * INNER_SIGMA)) * INNER_STRENGTH;
    float outer = exp(-d2 / (2.0 * OUTER_SIGMA * OUTER_SIGMA)) * OUTER_STRENGTH;
    return inner + outer;
}

float sampleGlow(vec2 uv, vec2 offsetPx, vec2 texel) {
    vec2 sUv = uv + offsetPx * texel;
    if (sUv.x < 0.0 || sUv.x > 1.0 || sUv.y < 0.0 || sUv.y > 1.0) {
        return 0.0;
    }
    float m = accentMaskSample(texture(iChannel0, sUv).rgb);
    if (m <= 0.001) {
        return 0.0;
    }
    // Evaluate falloff at the nearer of the two covered texels for a tighter aura.
    return m * glowFalloff(max(length(offsetPx) - 0.5, 0.0));
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 texel = 1.0 / iResolution.xy;
    vec2 uv = fragCoord * texel;
    vec4 orig = texture(iChannel0, uv);
    vec3 col = orig.rgb;

    float centerMask = accentMaskCenter(col);
    float glow = 0.0;

    // 1. Cardinal axes: offsets 1.5, 3.5 ... 19.5 px (10 steps x 4 = 40 fetches).
    //    Each fetch covers texels [d-0.5, d+0.5], so the full 1..20px range is contiguous.
    for (int i = 0; i < 10; i++) {
        float d = 1.5 + 2.0 * float(i);
        glow = max(glow, sampleGlow(uv, vec2( d, 0.0), texel));
        glow = max(glow, sampleGlow(uv, vec2(-d, 0.0), texel));
        glow = max(glow, sampleGlow(uv, vec2(0.0,  d), texel));
        glow = max(glow, sampleGlow(uv, vec2(0.0, -d), texel));
    }

    // 2. 45-degree diagonals for rounded pane corners: 1.5, 5.5, 9.5, 13.5 px
    //    (4 steps x 4 = 16 fetches; reaches ~19px radius like the original).
    for (int i = 0; i < 4; i++) {
        float d = 1.5 + 4.0 * float(i);
        glow = max(glow, sampleGlow(uv, vec2( d,  d), texel));
        glow = max(glow, sampleGlow(uv, vec2(-d,  d), texel));
        glow = max(glow, sampleGlow(uv, vec2( d, -d), texel));
        glow = max(glow, sampleGlow(uv, vec2(-d, -d), texel));
    }

    // Screen-blend the neon glow so dark areas illuminate cleanly while nearby white text stays crisp
    vec3 glowRgb = clamp(ACCENT_COLOR * glow, 0.0, 1.0);
    col = 1.0 - (1.0 - col) * (1.0 - glowRgb);

    // Subtle hot-core lift right on the focused border stroke itself
    if (centerMask > 0.01) {
        col = mix(col, vec3(0.78, 0.99, 1.0), centerMask * CORE_HOT_BOOST);
    }

    fragColor = vec4(col, orig.a);
}
