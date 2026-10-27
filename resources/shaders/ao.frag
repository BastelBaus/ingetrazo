#version 330 core
// Screen-space ambient occlusion (#954): how much of the hemisphere above
// each visible point is taken by the model's own nearby surfaces, read from
// the depth the face passes just wrote. A corner where a wall meets its slab
// sees half its sky hidden and comes out darker; an open face stays 1.0.
//
// Works in view space, rebuilt from depth with the inverse projection, so
// perspective and parallel views share one path and the radius is in model
// units (the view matrix is rigid).
uniform sampler2D u_depth;      // the scene's resolved depth, full size
uniform mat4 u_proj;
uniform mat4 u_inv_proj;
uniform vec2 u_texel;           // 1 / depth texture size
uniform float u_radius;         // model units
uniform float u_bias;           // model units, against self-occlusion
uniform int u_samples;

in vec2 v_uv;
out vec4 fragColor;

vec3 view_pos(vec2 uv, float d) {
    vec4 p = u_inv_proj * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return p.xyz / p.w;
}

vec3 view_at(vec2 uv) {
    return view_pos(uv, texture(u_depth, uv).r);
}

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    float d = texture(u_depth, v_uv).r;
    if (d >= 1.0) {             // sky / background: nothing to occlude
        fragColor = vec4(1.0);
        return;
    }
    vec3 p = view_pos(v_uv, d);
    // The depth buffer's own step at this distance (24 bits, so centimetres
    // at a couple of hundred metres in perspective): below it a flat face
    // reads as a staircase, and the stairs as corners — far walls seen
    // square on came out black. The bias never drops under four steps.
    float step = abs(view_pos(v_uv, min(d + 4.0 / 16777216.0, 1.0)).z - p.z);
    float bias = max(u_bias, step);
    // Normal from the neighbour on the side with the smaller depth step, so
    // a silhouette does not bend the normal of the face in front.
    vec3 r = view_at(v_uv + vec2(u_texel.x, 0.0)) - p;
    vec3 l = p - view_at(v_uv - vec2(u_texel.x, 0.0));
    vec3 t = view_at(v_uv + vec2(0.0, u_texel.y)) - p;
    vec3 b = p - view_at(v_uv - vec2(0.0, u_texel.y));
    vec3 dx = abs(r.z) < abs(l.z) ? r : l;
    vec3 dy = abs(t.z) < abs(b.z) ? t : b;
    vec3 n = normalize(cross(dx, dy));
    // Towards the eye: along the ray in perspective, straight back in a
    // parallel view (u_proj[2][3] is -1 in perspective, 0 in parallel).
    vec3 to_eye = u_proj[2][3] < -0.5 ? normalize(-p) : vec3(0.0, 0.0, 1.0);
    if (dot(n, to_eye) < 0.0) n = -n;     // face the camera

    // A per-pixel rotation of the sample set (the blur removes the noise).
    float a = hash(gl_FragCoord.xy) * 6.2831853;
    vec3 rnd = vec3(cos(a), sin(a), 0.0);
    vec3 tg = normalize(rnd - n * dot(rnd, n));
    if (any(isnan(tg))) tg = normalize(cross(n, vec3(0.0, 1.0, 0.0)));
    vec3 bt = cross(n, tg);

    float occ = 0.0;
    float golden = 2.39996323;
    for (int i = 0; i < u_samples; ++i) {
        float fi = float(i) + 0.5;
        float k = fi / float(u_samples);
        // Spiral over the hemisphere, denser near the point.
        float cz = sqrt(1.0 - k);
        float rr = sqrt(k);
        vec3 h = vec3(cos(fi * golden) * rr, sin(fi * golden) * rr, cz);
        float scale = mix(0.1, 1.0, k * k);
        vec3 s = p + (tg * h.x + bt * h.y + n * h.z) * u_radius * scale;
        vec4 c = u_proj * vec4(s, 1.0);
        vec2 suv = (c.xy / c.w) * 0.5 + 0.5;
        if (suv.x < 0.0 || suv.x > 1.0 || suv.y < 0.0 || suv.y > 1.0) continue;
        float sd = texture(u_depth, suv).r;
        if (sd >= 1.0) continue;
        vec3 q = view_pos(suv, sd);
        float sz = q.z;
        // Occluded when the surface seen there is in front of the sample;
        // a surface farther in front than the radius (a separate object
        // between us and this point) is no corner at all: its weight is gone
        // by twice the radius, or the far face behind a roof's silhouette
        // gets a dark halo along it.
        float range = 1.0 - smoothstep(u_radius, 2.0 * u_radius, abs(p.z - sz));
        // ...and only a surface standing out of this one's plane occludes:
        // the plane itself, however noisy its depth, never does.
        float above = dot(n, q - p);
        occ += (sz >= s.z + bias && above > bias ? 1.0 : 0.0) * range;
    }
    // A face seen nearly edge on: its normal, read off a depth that jumps
    // from pixel to pixel, is noise, and the noise reads as occlusion (a
    // roof's far slope came out black). Fade the term out there.
    float facing = dot(n, to_eye);
    occ *= smoothstep(0.08, 0.3, facing);
    fragColor = vec4(vec3(1.0 - occ / float(u_samples)), 1.0);
}
