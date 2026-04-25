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

# Blue-violet — vivid, saturated, luminous on any background
IND_R, IND_G, IND_B = 100, 60, 255

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

# 11 bars with varying max heights for waveform shape
BAR_HEIGHTS_MAX = [0.30, 0.45, 0.55, 0.70, 0.85, 1.0, 0.85, 0.70, 0.55, 0.45, 0.30]
NUM_BARS = len(BAR_HEIGHTS_MAX)
BAR_W_FRAC = 0.078   # wide glass bars — visible even on light backgrounds
GAP_FRAC = 0.016     # tight gaps
TOTAL_W = NUM_BARS * BAR_W_FRAC + (NUM_BARS - 1) * GAP_FRAC
START_X = (1.0 - TOTAL_W) / 2.0

# Per-level height scales — bars GROW with volume for obvious visual feedback
# Level 0 = silent (tiny stubs), Level 5 = loud (full dramatic waveform)
LEVEL_SCALES = [0.18, 0.35, 0.55, 0.72, 0.88, 1.0]

# Module-level state for current bar heights (set before each render pass)
_active_bar_heights = list(BAR_HEIGHTS_MAX)


def set_level_scale(level):
    """Set bar heights for a given volume level (0-5)."""
    global _active_bar_heights
    scale = LEVEL_SCALES[min(level, len(LEVEL_SCALES) - 1)]
    # Minimum bar height so they're always visible as stubs
    min_h = 0.12
    _active_bar_heights = [max(min_h, h * scale) for h in BAR_HEIGHTS_MAX]


def bar_sdf(nx, ny, bar_idx):
    """Returns signed distance to a bar in normalized coords.
    Negative = inside, positive = outside."""
    bh = _active_bar_heights[bar_idx]
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
            bh = _active_bar_heights[i]
            best_top = 0.5 - bh * 0.45
            best_bot = 0.5 + bh * 0.45
    return best_d, best_i, best_top, best_bot


# ── Wave mask (solid white silhouette for blur masking) ────────────────────

def draw_wave_mask(w, h, fill_level, level=0):
    """White filled bars on transparent background. Used as mask for blur layer."""
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


# ── Wave edge highlights ──────────────────────────────────────────────────

def _render_wave_edge(w, h, fill_level, mode="dark", level=0):
    """Render glass wave bars optimized for a specific background.

    mode="dark"  → bars sit on dark backgrounds (bright edges, vivid glow)
    mode="light" → bars sit on light backgrounds (darker outlines, visible body)

    Bar heights now SCALE with volume level — the shape itself is the
    volume indicator. fill_level controls the indigo fill intensity:
    level 0 = subtle glass stubs, level 5 = tall vivid glowing bars.
    """
    set_level_scale(level)

    # At higher levels, bars are always filled with indigo (height = volume)
    # At level 0, bars are unfilled glass stubs
    if level >= 1:
        fill_level = 1.0  # full indigo fill — the height IS the feedback

    pixels = []

    if mode == "dark":
        # Dark bg: VERY bright luminous bars — must pop against dark wallpapers
        stroke_w = 4.0 / w
        glow_w = 16.0 / w          # wider glow halo
        inner_glow_w = 9.0 / w
        # Edges: bright vivid indigo
        edge_fill_hot = 0.35        # mostly indigo with some white-hot
        edge_glass_indigo = 0.3     # bright indigo on unfilled edges
        edge_brightness_min = 0.85
        # Body
        fill_body_opacity = 0.97    # nearly opaque fill
        fill_edge_boost = 0.15
        glass_body_tint = 0.6       # 60% indigo tint on unfilled glass
        glass_body_opacity = 0.55   # much more visible glass body
        glass_edge_boost = 0.22
        # Outer glow
        fill_glow_opacity = 0.95
        glass_glow_opacity = 0.65
    else:
        # Light bg: bold indigo outlines, vivid body against white
        stroke_w = 4.0 / w
        glow_w = 12.0 / w
        inner_glow_w = 7.0 / w
        # Edges: rich indigo (not white — white on white is invisible)
        edge_fill_hot = 0.15        # mostly indigo, little white
        edge_glass_indigo = 0.8     # strong indigo on unfilled edges
        edge_brightness_min = 0.6
        # Body
        fill_body_opacity = 0.95
        fill_edge_boost = 0.12
        glass_body_tint = 0.65      # 65% indigo on unfilled glass
        glass_body_opacity = 0.45   # more visible body
        glass_edge_boost = 0.18
        # Outer glow
        fill_glow_opacity = 0.85
        glass_glow_opacity = 0.5

    for py in range(h):
        for px in range(w):
            nx = (px + 0.5) / w
            ny = (py + 0.5) / h

            best_edge = 0.0
            best_glow = 0.0
            best_inside = 0.0
            best_inner_glow = 0.0
            best_is_top = False
            best_ny_ratio = 0.5
            best_in_fill_zone = False

            for i in range(NUM_BARS):
                d = bar_sdf(nx, ny, i)
                bh = _active_bar_heights[i]
                bar_top = 0.5 - bh * 0.45
                bar_bot = 0.5 + bh * 0.45

                edge_alpha = clamp(1.0 - abs(d) / stroke_w)

                glow_alpha = 0.0
                if d > 0:
                    glow_alpha = clamp(1.0 - d / glow_w) ** 1.5 * 0.6

                inside_alpha = clamp(0.5 - d * w)

                inner_glow = 0.0
                if d < 0:
                    inner_glow = clamp(1.0 - (-d) / inner_glow_w)

                if edge_alpha > best_edge:
                    best_edge = edge_alpha
                    if bar_bot > bar_top:
                        best_ny_ratio = clamp((ny - bar_top) / (bar_bot - bar_top))
                    best_is_top = ny < (bar_top + bar_bot) / 2.0

                if glow_alpha > best_glow:
                    best_glow = glow_alpha

                if inside_alpha > best_inside:
                    best_inside = inside_alpha
                    fill_threshold_y = bar_bot - (bar_bot - bar_top) * fill_level
                    best_in_fill_zone = (ny >= fill_threshold_y and fill_level > 0)

                if inner_glow > best_inner_glow:
                    best_inner_glow = inner_glow

            r, g, b, a = 0, 0, 0, 0

            if best_edge > 0.01:
                if best_is_top:
                    brightness = 1.0 - best_ny_ratio * 0.15
                else:
                    brightness = 0.85 - (best_ny_ratio - 0.5) * 0.15
                brightness = clamp(brightness, edge_brightness_min, 1.0)

                if best_in_fill_zone:
                    hot = edge_fill_hot
                    r = int(clamp(IND_R / 255 * (1 - hot) + hot) * brightness * 255)
                    g = int(clamp(IND_G / 255 * (1 - hot) + hot) * brightness * 255)
                    b = int(clamp(IND_B / 255 * (1 - hot) + hot) * brightness * 255)
                else:
                    mix = edge_glass_indigo
                    r = int((IND_R * mix + 255 * (1 - mix)) * brightness)
                    g = int((IND_G * mix + 255 * (1 - mix)) * brightness)
                    b = int((IND_B * mix + 255 * (1 - mix)) * brightness)
                a = int(clamp(best_edge * brightness) * 255)

            elif best_inside > 0.01:
                if best_in_fill_zone:
                    glow_boost = 0.3 * best_inner_glow
                    r = int(clamp(IND_R / 255 + glow_boost) * 255)
                    g = int(clamp(IND_G / 255 + glow_boost) * 255)
                    b = int(clamp(IND_B / 255 + glow_boost) * 255)
                    a = int(clamp(best_inside * (fill_body_opacity + fill_edge_boost * best_inner_glow)) * 255)
                else:
                    tint = glass_body_tint
                    r = int(IND_R * tint + 255 * (1 - tint))
                    g = int(IND_G * tint + 255 * (1 - tint))
                    b = int(IND_B * tint + 255 * (1 - tint))
                    a = int(clamp(best_inside * (glass_body_opacity + glass_edge_boost * best_inner_glow)) * 255)

            elif best_glow > 0.01:
                if best_in_fill_zone:
                    r, g, b = IND_R, IND_G, IND_B
                    a = int(clamp(best_glow * fill_glow_opacity) * 255)
                else:
                    r = int(IND_R * 0.6 + 255 * 0.4)
                    g = int(IND_G * 0.6 + 255 * 0.4)
                    b = int(IND_B * 0.6 + 255 * 0.4)
                    a = int(clamp(best_glow * glass_glow_opacity) * 255)

            pixels.append((r, g, b, a))
    return pixels


def draw_wave_edge(w, h, fill_level, level=0):
    """Light-background variant (default / backward compat)."""
    return _render_wave_edge(w, h, fill_level, mode="light", level=level)


def draw_wave_edge_dark(w, h, fill_level, level=0):
    """Dark-background variant — bright glowing indigo glass."""
    return _render_wave_edge(w, h, fill_level, mode="dark", level=level)


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

print("Generating glassmorphic waveform assets (light + dark variants)...")

WAVE_W, WAVE_H = 96, 32
for lvl in range(6):
    fill = lvl / 5.0
    for scale, suffix in [(1, ""), (2, "@2x")]:
        sw, sh = WAVE_W * scale, WAVE_H * scale
        # Mask (bar shapes scale with level)
        px = draw_wave_mask(sw, sh, fill, level=lvl)
        write_png(ASSETS / f"wave_mask_{lvl}{suffix}.png", px, sw, sh)
        # Light-bg edge highlights
        px = draw_wave_edge(sw, sh, fill, level=lvl)
        write_png(ASSETS / f"wave_edge_{lvl}{suffix}.png", px, sw, sh)
        # Dark-bg edge highlights
        px = draw_wave_edge_dark(sw, sh, fill, level=lvl)
        write_png(ASSETS / f"wave_edge_dark_{lvl}{suffix}.png", px, sw, sh)

PROC_W, PROC_H = 42, 18  # ~30% larger than original 32x14
PROC_FRAMES = 12
for frame in range(PROC_FRAMES):
    for scale, suffix in [(1, ""), (2, "@2x")]:
        sw, sh = PROC_W * scale, PROC_H * scale
        px = draw_proc_mask(sw, sh, frame, PROC_FRAMES)
        write_png(ASSETS / f"proc_mask_{frame}{suffix}.png", px, sw, sh)
        px = draw_proc_edge(sw, sh, frame, PROC_FRAMES)
        write_png(ASSETS / f"proc_edge_{frame}{suffix}.png", px, sw, sh)

print("Glassmorphic assets done.")
