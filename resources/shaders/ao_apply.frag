#version 330 core
// Multiplies the occlusion onto the scene (#954), drawn with the blend
// (GL_ZERO, GL_SRC_COLOR) over the opaque faces only — edges, dimensions,
// text and guides come after and stay as they were. The raw occlusion is
// physically faint (a floor 20 cm from a wall loses ~15 % of its sky), so the
// intensity is a contrast curve: ao^(2.5·intensity). Intensity 0 leaves the
// picture untouched.
uniform sampler2D u_ao;
uniform float u_intensity;

in vec2 v_uv;
out vec4 fragColor;

void main() {
    float ao = texture(u_ao, v_uv).r;
    float k = pow(clamp(ao, 0.0, 1.0), 2.5 * clamp(u_intensity, 0.0, 2.0));
    // Never pure black: the slot under a bench seat keeps a third of its
    // light, so what is in there still reads.
    fragColor = vec4(vec3(max(k, 0.3)), 1.0);
}
