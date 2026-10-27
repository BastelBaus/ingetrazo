#version 330 core
// Edge-aware blur of the occlusion (#954): averages a 4x4 block, but only
// texels whose depth is close to this one's, so the dark band of a corner
// never bleeds across the silhouette onto the object in front or the sky.
uniform sampler2D u_ao;
uniform sampler2D u_depth;
uniform vec2 u_texel;           // 1 / occlusion texture size
uniform mat4 u_inv_proj;
uniform float u_radius;

in vec2 v_uv;
out vec4 fragColor;

float view_z(vec2 uv) {
    float d = texture(u_depth, uv).r;
    vec4 p = u_inv_proj * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return p.z / p.w;
}

void main() {
    float z0 = view_z(v_uv);
    float sum = 0.0;
    float wsum = 0.0;
    for (int y = -2; y < 2; ++y) {
        for (int x = -2; x < 2; ++x) {
            vec2 uv = v_uv + (vec2(float(x), float(y)) + 0.5) * u_texel;
            float w = abs(view_z(uv) - z0) < u_radius * 0.5 ? 1.0 : 0.0;
            sum += texture(u_ao, uv).r * w;
            wsum += w;
        }
    }
    float ao = wsum > 0.0 ? sum / wsum : texture(u_ao, v_uv).r;
    fragColor = vec4(vec3(ao), 1.0);
}
