#!/usr/bin/env python3
"""
Generates waveform overlay and processing animation PNGs.

Apple-style glassmorphism: shapes are transparent with bright luminous
edge highlights. The background refracts through the shapes (handled by
NSVisualEffectView mask in the app). These PNGs provide:
  1. An alpha mask image (white shapes on transparent) for the blur mask
  2. An edge highlight overlay (bright strokes defining the glass edges)

Outputs (in assets/):
  wave_mask_0..5.png / @2x     — alpha mask for blur (shape silhouettes)
  wave_edge_0..5.png / @2x     — bright edge highlights overlay
  proc_mask_0..11.png / @2x    — processing dot masks
  proc_edge_0..11.png / @2x    — processing dot edge highlights
"""

import struct, zlib, math
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)

IND_R, IND_G, IND_B = 90, 70, 215

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


# ── Bar geometry (shared by mask and edge) ─────────────────────────────────

# 11 bars with varying heights for waveform shape
BAR_HEIGHTS = [0.30, 0.45, 0.55, 0.70, 0.85, 1.0, 0.85, 0.70, 0.55, 0.45, 0.30]
NUM_BARS = len(BAR_HEIGHTS)
BAR_W_FRAC = 0.045
GAP_FRAC = 0.025
TOTAL_W = NUM_BARS * BAR_W_FRAC + (NUM_BARS - 1) * GAP_FRAC
START_X = (1.0 - TOTAL_W) / 2.0


def bar_sdf(nx, ny, bar_idx):
    """Returns signed distance to a bar in normalized coords.
    Negative = inside, positive = outside."""
    bh = BAR_HEIGHTS[bar_idx]
    bx = START_X + bar_idx * (BAR_W_FRAC + GAP_FRAC)
    bw = BAR_W_FRAC

    bar_top = 0.5 - bh * 0.45
    bar_bot = 0.5 + bh * 0.45
    bar_cx = bx + bw / 2.0
    bar_cy = (bar_top + bar_bot) / 2.0
    bar_hw = bw / 2.0
    bar_hh = (bar_bot - bar_top) / 2.0

    # Rounded rect radius (normalized)
    rx = bw * 0.42  # pill-shaped rounding
    ry = rx

    dx = abs(nx - bar_cx) - (bar_hw - rx)
    dy = abs(ny - bar_cy) - (bar_hh - ry)

    if dx <= 0 and dy <= 0:
        return min(dx, dy)  # inside
    elif dx > 0 and dy > 0:
        return math.sqrt(dx * dx + dy * dy)  # corner
    else:
        return max(dx, dy)  # edge


def closest_bar_info(nx, ny, w):
    """Returns (sdf_distance_normalized, bar_index, bar_top, bar_bot) for closest bar."""
    best_d = 999.0
    best_i = 0
    best_top = 0.5
    best_bot = 0.5
    for i in range(NUM_BARS):
        d = bar_sdf(nx, ny, i)
        if d < best_d:
            best_d = d
            best_i = i
            bh = BAR_HEIGHTS[i]
            best_top = 0.5 - bh * 0.45
            best_bot = 0.5 + bh * 0.45
    return best_d, best_i, best_top, best_bot


# ── Wave mask (solid white silhouette for blur masking) ────────────────────

def draw_wave_mask(w, h, fill_level):
    """White filled bars on transparent background. Used as mask for blur layer."""
    pixels = []
    for py in range(h):
        for px in range(w):
            nx = (px + 0.5) / w
            ny = (py + 0.5) / h

            best_alpha = 0.0
            for i in range(NUM_BARS):
                d = bar_sdf(nx, ny, i)
                # Anti-aliased fill
                aa = clamp(0.5 - d * w)  # scale to pixels for AA
                if aa > best_alpha:
                    best_alpha = aa

            if best_alpha > 0.001:
                a = int(clamp(best_alpha) * 255)
                pixels.append((255, 255, 255, a))
            else:
                pixels.append((0, 0, 0, 0))
    return pixels


# ── Wave edge highlights ──────────────────────────────────────────────────

def draw_wave_edge(w, h, fill_level):
    """Glass bar rendering with bright edges and visible interior.

    Each bar has:
    - Bold bright edge stroke (top-lit, brighter on top half)
    - Semi-transparent white interior fill (glass body, ~20%)
    - Indigo fill rising from bottom when volume > 0
    - Outer glow for visibility on any background
    """
    pixels = []
    stroke_w = 3.0 / w   # extra bold edge stroke (~3 pixels)
    glow_w = 7.0 / w     # wider outer glow radius

    for py in range(h):
        for px in range(w):
            nx = (px + 0.5) / w
            ny = (py + 0.5) / h

            best_edge = 0.0
            best_glow = 0.0
            best_inside = 0.0
            best_is_top = False
            best_ny_ratio = 0.5
            best_in_fill_zone = False

            for i in range(NUM_BARS):
                d = bar_sdf(nx, ny, i)
                bh = BAR_HEIGHTS[i]
                bar_top = 0.5 - bh * 0.45
                bar_bot = 0.5 + bh * 0.45

                # Bold edge stroke
                edge_alpha = clamp(1.0 - abs(d) / stroke_w)

                # Outer glow (soft falloff outside the bar)
                if d > 0:
                    glow_alpha = clamp(1.0 - d / glow_w) * 0.5
                else:
                    glow_alpha = 0.0

                # Inside fill
                inside_alpha = clamp(0.5 - d * w)

                if edge_alpha > best_edge:
                    best_edge = edge_alpha
                    if bar_bot > bar_top:
                        best_ny_ratio = clamp((ny - bar_top) / (bar_bot - bar_top))
                    best_is_top = ny < (bar_top + bar_bot) / 2.0

                if glow_alpha > best_glow:
                    best_glow = glow_alpha

                if inside_alpha > best_inside:
                    best_inside = inside_alpha
                    # Check if in volume fill zone
                    fill_threshold_y = bar_bot - (bar_bot - bar_top) * fill_level
                    best_in_fill_zone = (ny >= fill_threshold_y and fill_level > 0)

            r, g, b, a = 0, 0, 0, 0

            if best_edge > 0.01:
                # Top-lit directional lighting
                if best_is_top:
                    brightness = 1.0 - best_ny_ratio * 0.25
                else:
                    brightness = 0.75 - (best_ny_ratio - 0.5) * 0.25

                brightness = clamp(brightness, 0.45, 1.0)

                if best_in_fill_zone:
                    # Edge in fill zone: vivid indigo edge
                    mix = 0.65  # 65% indigo tint for punchy color
                    r = int((IND_R * mix + 255 * (1 - mix)) * brightness)
                    g = int((IND_G * mix + 255 * (1 - mix)) * brightness)
                    b = int((IND_B * mix + 255 * (1 - mix)) * brightness)
                else:
                    r = int(255 * brightness)
                    g = int(255 * brightness)
                    b = int(255 * brightness)
                a = int(clamp(best_edge * brightness) * 255)

            elif best_inside > 0.01:
                if best_in_fill_zone:
                    # Strong indigo fill inside bars — pops on any background
                    r, g, b = IND_R, IND_G, IND_B
                    a = int(clamp(best_inside * 0.85) * 255)
                else:
                    # Glass body: semi-transparent white
                    r, g, b = 255, 255, 255
                    a = int(clamp(best_inside * 0.22) * 255)

            elif best_glow > 0.01:
                # Outer glow: indigo-tinted when volume active, white otherwise
                if best_in_fill_zone:
                    r, g, b = IND_R, IND_G, IND_B
                    a = int(clamp(best_glow * 0.7) * 255)
                else:
                    r, g, b = 220, 220, 240
                    a = int(clamp(best_glow) * 255)

            pixels.append((r, g, b, a))
    return pixels


# ── Processing dots ────────────────────────────────────────────────────────

def draw_proc_mask(w, h, frame, total_frames=12):
    """White dot silhouettes for blur mask."""
    pixels = []
    num_dots = 3
    dot_radius = min(w, h) * 0.22
    dot_spacing = w * 0.22
    start_x = w / 2.0 - (num_dots - 1) * dot_spacing / 2.0
    cy = h / 2.0
    phase_offset = [0, 0.33, 0.66]

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
    """Bold glass processing dots with edge highlights and indigo fill."""
    pixels = []
    num_dots = 3
    dot_radius = min(w, h) * 0.22
    dot_spacing = w * 0.22
    start_x = w / 2.0 - (num_dots - 1) * dot_spacing / 2.0
    cy = h / 2.0
    phase_offset = [0, 0.33, 0.66]
    stroke_w = 2.0  # pixels — bold edge

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
                glow = clamp(1.0 - max(0, dist - r) / 3.0) * 0.25 * opacity

                if edge > best_edge:
                    best_edge = edge
                    best_top = (py + 0.5) < cy
                if fill > best_fill:
                    best_fill = fill
                if glow > best_glow:
                    best_glow = glow

            if best_edge > 0.01:
                brightness = 1.0 if best_top else 0.65
                rv = int(255 * brightness)
                a = int(clamp(best_edge * brightness) * 255)
                pixels.append((rv, rv, rv, a))
            elif best_fill > 0.01:
                # Indigo glass fill
                a = int(clamp(best_fill * 0.45) * 255)
                pixels.append((IND_R, IND_G, IND_B, a))
            elif best_glow > 0.01:
                a = int(clamp(best_glow) * 255)
                pixels.append((IND_R, IND_G, IND_B, a))
            else:
                pixels.append((0, 0, 0, 0))
    return pixels


# ── Generate ───────────────────────────────────────────────────────────────

print("Generating glassmorphic waveform assets...")

WAVE_W, WAVE_H = 96, 32
for lvl in range(6):
    fill = lvl / 5.0
    for scale, suffix in [(1, ""), (2, "@2x")]:
        sw, sh = WAVE_W * scale, WAVE_H * scale
        # Mask
        px = draw_wave_mask(sw, sh, fill)
        write_png(ASSETS / f"wave_mask_{lvl}{suffix}.png", px, sw, sh)
        # Edge highlights
        px = draw_wave_edge(sw, sh, fill)
        write_png(ASSETS / f"wave_edge_{lvl}{suffix}.png", px, sw, sh)

PROC_W, PROC_H = 32, 14
PROC_FRAMES = 12
for frame in range(PROC_FRAMES):
    for scale, suffix in [(1, ""), (2, "@2x")]:
        sw, sh = PROC_W * scale, PROC_H * scale
        px = draw_proc_mask(sw, sh, frame, PROC_FRAMES)
        write_png(ASSETS / f"proc_mask_{frame}{suffix}.png", px, sw, sh)
        px = draw_proc_edge(sw, sh, frame, PROC_FRAMES)
        write_png(ASSETS / f"proc_edge_{frame}{suffix}.png", px, sw, sh)

print("Glassmorphic assets done.")
