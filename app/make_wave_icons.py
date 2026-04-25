#!/usr/bin/env python3
"""
Generates waveform overlay and processing animation PNGs.

Apple-style glassmorphism: bars have a frosted-glass look with white
surrounds (visible on dark backgrounds) and indigo fill that intensifies
with volume. Level 0 = ghost glass bars (no indigo, just faint outlines).

22 thin bars (double the previous 11) for a denser, sleeker waveform.

Outputs (in assets/):
  wave_mask_0..5.png / @2x     — alpha mask for blur (shape silhouettes)
  wave_edge_0..5.png / @2x     — edge highlights (light bg variant)
  wave_edge_dark_0..5.png / @2x — edge highlights (dark bg variant)
  proc_mask_0..11.png / @2x    — processing dot masks
  proc_edge_0..11.png / @2x    — processing dot edge highlights
"""

import struct, zlib, math
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)

# Blue-violet — punchy, saturated
IND_R, IND_G, IND_B = 90, 40, 255

# ── Minimal PNG writer ─────────────────────────────────────────────────────

def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

def write_png(path, pixels, w, h):
    raw = bytearray()
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            r, g, b, a = pixels[y * w + x]
            raw += bytes([r, g, b, a])
    ihdr = struct.pack(">II", w, h) + bytes([8, 6, 0, 0, 0])
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )
    Path(path).write_bytes(data)
    print(f"  {path}")

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


# ── Bar geometry ──────────────────────────────────────────────────────────

# 22 bars — smooth symmetric bell curve peaking at center
BAR_HEIGHTS_MAX = [
    0.22, 0.30, 0.38, 0.46, 0.54, 0.62, 0.70, 0.78, 0.86, 0.94, 1.0,
    1.0, 0.94, 0.86, 0.78, 0.70, 0.62, 0.54, 0.46, 0.38, 0.30, 0.22,
]
NUM_BARS = len(BAR_HEIGHTS_MAX)  # 22
BAR_W_FRAC = 0.035   # thin bars — half the width, double the count
GAP_FRAC = 0.008     # tight gaps between bars
TOTAL_W = NUM_BARS * BAR_W_FRAC + (NUM_BARS - 1) * GAP_FRAC
START_X = (1.0 - TOTAL_W) / 2.0

# Per-level height scales — bars GROW with volume
LEVEL_SCALES = [0.18, 0.35, 0.55, 0.72, 0.88, 1.0]

_active_bar_heights = list(BAR_HEIGHTS_MAX)


def set_level_scale(level):
    """Set bar heights for a given volume level (0-5)."""
    global _active_bar_heights
    scale = LEVEL_SCALES[min(level, len(LEVEL_SCALES) - 1)]
    min_h = 0.10  # minimum stub height
    _active_bar_heights = [max(min_h, h * scale) for h in BAR_HEIGHTS_MAX]


def bar_sdf(nx, ny, bar_idx):
    """Signed distance to a bar in normalized coords. Negative = inside."""
    bh = _active_bar_heights[bar_idx]
    bx = START_X + bar_idx * (BAR_W_FRAC + GAP_FRAC)
    bw = BAR_W_FRAC

    bar_top = 0.5 - bh * 0.45
    bar_bot = 0.5 + bh * 0.45
    bar_cx = bx + bw / 2.0
    bar_cy = (bar_top + bar_bot) / 2.0
    bar_hw = bw / 2.0
    bar_hh = (bar_bot - bar_top) / 2.0

    rx = bw * 0.45  # pill rounding
    ry = rx

    dx = abs(nx - bar_cx) - (bar_hw - rx)
    dy = abs(ny - bar_cy) - (bar_hh - ry)

    if dx <= 0 and dy <= 0:
        return min(dx, dy)
    elif dx > 0 and dy > 0:
        return math.sqrt(dx * dx + dy * dy)
    else:
        return max(dx, dy)


# ── Wave mask (white silhouette for blur masking) ─────────────────────────

def draw_wave_mask(w, h, fill_level, level=0):
    set_level_scale(level)
    pixels = []
    for py in range(h):
        for px in range(w):
            nx = (px + 0.5) / w
            ny = (py + 0.5) / h
            best_alpha = 0.0
            for i in range(NUM_BARS):
                d = bar_sdf(nx, ny, i)
                aa = clamp(0.5 - d * w)
                if aa > best_alpha:
                    best_alpha = aa
            if best_alpha > 0.001:
                a = int(clamp(best_alpha) * 255)
                pixels.append((255, 255, 255, a))
            else:
                pixels.append((0, 0, 0, 0))
    return pixels


# ── Wave edge highlights ─────────────────────────────────────────────────

def _render_wave_edge(w, h, fill_level, mode="dark", level=0):
    """Render glass wave bars.

    mode="dark"  → white surround + indigo fill (visible on dark wallpapers)
    mode="light" → indigo outlines + indigo fill (visible on light bg)

    Level 0 = ghost glass bars (faint outline, no indigo fill — just shows
    that the mic is listening). Level 1+ = indigo fills the bars.
    """
    set_level_scale(level)

    # Level 1+ always fully filled — height IS the feedback
    if level >= 1:
        fill_level = 1.0

    is_ghost = (level == 0)

    pixels = []

    if mode == "dark":
        # ── Dark background parameters ──
        stroke_w = 3.0 / w
        white_glow_w = 14.0 / w      # white halo around bars
        inner_glow_w = 6.0 / w

        if is_ghost:
            # Ghost: faint white outlines, no fill
            edge_r, edge_g, edge_b = 255, 255, 255
            edge_opacity = 0.45
            body_opacity = 0.08       # barely-there glass body
            body_r, body_g, body_b = 255, 255, 255
            glow_opacity = 0.15
            glow_r, glow_g, glow_b = 200, 200, 255  # hint of blue
        else:
            # Active: white surround + indigo fill
            edge_r, edge_g, edge_b = 255, 255, 255
            edge_opacity = 0.95
            body_r, body_g, body_b = IND_R, IND_G, IND_B
            body_opacity = 0.95
            glow_r, glow_g, glow_b = 255, 255, 255
            glow_opacity = 0.55
    else:
        # ── Light background parameters ──
        stroke_w = 3.0 / w
        white_glow_w = 10.0 / w
        inner_glow_w = 5.0 / w

        if is_ghost:
            # Ghost: faint indigo outlines
            edge_r, edge_g, edge_b = IND_R, IND_G, IND_B
            edge_opacity = 0.30
            body_opacity = 0.06
            body_r, body_g, body_b = IND_R, IND_G, IND_B
            glow_opacity = 0.10
            glow_r, glow_g, glow_b = IND_R, IND_G, IND_B
        else:
            # Active: deep indigo
            edge_r, edge_g, edge_b = IND_R, IND_G, IND_B
            edge_opacity = 0.95
            body_r, body_g, body_b = IND_R, IND_G, IND_B
            body_opacity = 0.90
            glow_r, glow_g, glow_b = IND_R, IND_G, IND_B
            glow_opacity = 0.45

    for py in range(h):
        for px in range(w):
            nx = (px + 0.5) / w
            ny = (py + 0.5) / h

            best_edge = 0.0
            best_inside = 0.0
            best_glow = 0.0
            best_inner_glow = 0.0

            for i in range(NUM_BARS):
                d = bar_sdf(nx, ny, i)

                edge_alpha = clamp(1.0 - abs(d) / stroke_w)
                inside_alpha = clamp(0.5 - d * w)
                glow_alpha = 0.0
                if d > 0:
                    glow_alpha = clamp(1.0 - d / white_glow_w) ** 1.5 * 0.6
                inner_glow = 0.0
                if d < 0:
                    inner_glow = clamp(1.0 - (-d) / inner_glow_w)

                if edge_alpha > best_edge:
                    best_edge = edge_alpha
                if inside_alpha > best_inside:
                    best_inside = inside_alpha
                if glow_alpha > best_glow:
                    best_glow = glow_alpha
                if inner_glow > best_inner_glow:
                    best_inner_glow = inner_glow

            r, g, b, a = 0, 0, 0, 0

            if best_edge > 0.01:
                # Edge stroke
                brightness = 1.0
                r, g, b = edge_r, edge_g, edge_b
                # Inner glow brightens edge slightly
                boost = 0.15 * best_inner_glow
                r = min(255, int(r + boost * 255))
                g = min(255, int(g + boost * 255))
                b = min(255, int(b + boost * 255))
                a = int(clamp(best_edge * edge_opacity) * 255)

            elif best_inside > 0.01:
                # Body fill
                glow_boost = 0.2 * best_inner_glow
                r = min(255, int(body_r + glow_boost * 255))
                g = min(255, int(body_g + glow_boost * 255))
                b = min(255, int(body_b + glow_boost * 255))
                a = int(clamp(best_inside * body_opacity) * 255)

            elif best_glow > 0.01:
                # Outer glow halo
                r, g, b = glow_r, glow_g, glow_b
                a = int(clamp(best_glow * glow_opacity) * 255)

            pixels.append((r, g, b, a))
    return pixels


def draw_wave_edge(w, h, fill_level, level=0):
    """Light-background variant."""
    return _render_wave_edge(w, h, fill_level, mode="light", level=level)


def draw_wave_edge_dark(w, h, fill_level, level=0):
    """Dark-background variant — white surround + indigo glass."""
    return _render_wave_edge(w, h, fill_level, mode="dark", level=level)


# ── Processing dots ───────────────────────────────────────────────────────

def draw_proc_mask(w, h, frame, total_frames=12):
    """White dot silhouettes for blur mask."""
    pixels = []
    num_dots = 5
    dot_radius = min(w, h) * 0.20
    dot_spacing = w * 0.16
    start_x = w / 2.0 - (num_dots - 1) * dot_spacing / 2.0
    cy = h / 2.0
    phase_offset = [0, 0.2, 0.4, 0.6, 0.8]

    for py in range(h):
        for px in range(w):
            best_a = 0.0
            for i in range(num_dots):
                cx = start_x + i * dot_spacing
                t = (frame / total_frames + phase_offset[i]) % 1.0
                pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi)
                r = dot_radius * (0.7 + 0.3 * pulse)
                dist = math.sqrt((px + 0.5 - cx) ** 2 + (py + 0.5 - cy) ** 2)
                a = clamp(r - dist + 0.5) * (0.5 + 0.5 * pulse)
                if a > best_a:
                    best_a = a
            if best_a > 0.01:
                pixels.append((255, 255, 255, int(clamp(best_a) * 255)))
            else:
                pixels.append((0, 0, 0, 0))
    return pixels


def draw_proc_edge(w, h, frame, total_frames=12):
    """Glass processing dots with edge highlights and indigo fill."""
    pixels = []
    num_dots = 5
    dot_radius = min(w, h) * 0.20
    dot_spacing = w * 0.16
    start_x = w / 2.0 - (num_dots - 1) * dot_spacing / 2.0
    cy = h / 2.0
    phase_offset = [0, 0.2, 0.4, 0.6, 0.8]
    stroke_w = 2.6

    for py in range(h):
        for px in range(w):
            best_edge = 0.0
            best_fill = 0.0
            best_glow = 0.0
            best_top = False

            for i in range(num_dots):
                cx = start_x + i * dot_spacing
                t = (frame / total_frames + phase_offset[i]) % 1.0
                pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi)
                r = dot_radius * (0.7 + 0.3 * pulse)
                opacity = 0.5 + 0.5 * pulse

                dist = math.sqrt((px + 0.5 - cx) ** 2 + (py + 0.5 - cy) ** 2)
                edge = clamp(1.0 - abs(dist - r) / stroke_w) * opacity
                fill = clamp(r - dist + 0.5) * opacity
                glow = clamp(1.0 - max(0, dist - r) / 4.0) * 0.35 * opacity

                if edge > best_edge:
                    best_edge = edge
                    best_top = (py + 0.5) < cy
                if fill > best_fill:
                    best_fill = fill
                if glow > best_glow:
                    best_glow = glow

            if best_edge > 0.01:
                brightness = 1.0 if best_top else 0.7
                rv = int(255 * brightness)
                a = int(clamp(best_edge * brightness) * 255)
                pixels.append((rv, rv, rv, a))
            elif best_fill > 0.01:
                a = int(clamp(best_fill * 0.60) * 255)
                pixels.append((IND_R, IND_G, IND_B, a))
            elif best_glow > 0.01:
                a = int(clamp(best_glow) * 255)
                pixels.append((IND_R, IND_G, IND_B, a))
            else:
                pixels.append((0, 0, 0, 0))
    return pixels


# ── Generate ──────────────────────────────────────────────────────────────

print("Generating glassmorphic waveform assets (light + dark, 22 bars)...")

WAVE_W, WAVE_H = 96, 32
for lvl in range(6):
    fill = lvl / 5.0
    for scale, suffix in [(1, ""), (2, "@2x")]:
        sw, sh = WAVE_W * scale, WAVE_H * scale
        px = draw_wave_mask(sw, sh, fill, level=lvl)
        write_png(ASSETS / f"wave_mask_{lvl}{suffix}.png", px, sw, sh)
        px = draw_wave_edge(sw, sh, fill, level=lvl)
        write_png(ASSETS / f"wave_edge_{lvl}{suffix}.png", px, sw, sh)
        px = draw_wave_edge_dark(sw, sh, fill, level=lvl)
        write_png(ASSETS / f"wave_edge_dark_{lvl}{suffix}.png", px, sw, sh)

# 30% larger than 42x18, wider for 5 dots
PROC_W, PROC_H = 55, 23
PROC_FRAMES = 12
for frame in range(PROC_FRAMES):
    for scale, suffix in [(1, ""), (2, "@2x")]:
        sw, sh = PROC_W * scale, PROC_H * scale
        px = draw_proc_mask(sw, sh, frame, PROC_FRAMES)
        write_png(ASSETS / f"proc_mask_{frame}{suffix}.png", px, sw, sh)
        px = draw_proc_edge(sw, sh, frame, PROC_FRAMES)
        write_png(ASSETS / f"proc_edge_{frame}{suffix}.png", px, sw, sh)

print("Glassmorphic assets done.")
