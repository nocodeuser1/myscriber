#!/usr/bin/env python3
"""
Generates waveform overlay and processing animation PNGs.

Each volume level gets a white frosted-glass PANEL (rounded pill) behind
the bars. The panel is always visible — even on pitch-black wallpapers —
and grows taller with volume. Indigo bars sit inside the panel.

Level 0: panel with faint ghost bars (no indigo) — shows mic is listening.
Level 1-5: panel grows, indigo bars fill and grow with volume.

22 thin bars for a dense, sleek equalizer look.

Outputs (in assets/):
  wave_mask_0..5.png / @2x     — alpha mask for blur
  wave_edge_0..5.png / @2x     — light-bg variant
  wave_edge_dark_0..5.png / @2x — dark-bg variant (white glass panel)
  proc_mask_0..11.png / @2x    — processing dot masks
  proc_edge_0..11.png / @2x    — processing dot edge highlights
"""

import struct, zlib, math
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)

# Bluer indigo — more blue, less purple
IND_R, IND_G, IND_B = 55, 50, 255

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

# 22 bars — smooth symmetric bell curve
BAR_HEIGHTS_MAX = [
    0.22, 0.30, 0.38, 0.46, 0.54, 0.62, 0.70, 0.78, 0.86, 0.94, 1.0,
    1.0, 0.94, 0.86, 0.78, 0.70, 0.62, 0.54, 0.46, 0.38, 0.30, 0.22,
]
NUM_BARS = len(BAR_HEIGHTS_MAX)
BAR_W_FRAC = 0.035
GAP_FRAC = 0.008
TOTAL_W = NUM_BARS * BAR_W_FRAC + (NUM_BARS - 1) * GAP_FRAC
START_X = (1.0 - TOTAL_W) / 2.0

LEVEL_SCALES = [0.18, 0.35, 0.55, 0.72, 0.88, 1.0]

_active_bar_heights = list(BAR_HEIGHTS_MAX)


def set_level_scale(level):
    global _active_bar_heights
    scale = LEVEL_SCALES[min(level, len(LEVEL_SCALES) - 1)]
    min_h = 0.10
    _active_bar_heights = [max(min_h, h * scale) for h in BAR_HEIGHTS_MAX]


def bar_sdf(nx, ny, bar_idx):
    bh = _active_bar_heights[bar_idx]
    bx = START_X + bar_idx * (BAR_W_FRAC + GAP_FRAC)
    bw = BAR_W_FRAC
    bar_top = 0.5 - bh * 0.45
    bar_bot = 0.5 + bh * 0.45
    bar_cx = bx + bw / 2.0
    bar_cy = (bar_top + bar_bot) / 2.0
    bar_hw = bw / 2.0
    bar_hh = (bar_bot - bar_top) / 2.0
    rx = bw * 0.45
    ry = rx
    dx = abs(nx - bar_cx) - (bar_hw - rx)
    dy = abs(ny - bar_cy) - (bar_hh - ry)
    if dx <= 0 and dy <= 0:
        return min(dx, dy)
    elif dx > 0 and dy > 0:
        return math.sqrt(dx * dx + dy * dy)
    else:
        return max(dx, dy)


# ── Glass panel SDF ──────────────────────────────────────────────────────

def panel_sdf(nx, ny, level):
    """Signed distance to the glass panel — a rounded pill that encompasses
    all bars at the current level, with padding. Grows taller with volume."""
    # Horizontal: spans all bars with padding
    pad_x = 0.025
    panel_left = START_X - pad_x
    panel_right = START_X + TOTAL_W + pad_x

    # Vertical: grows with volume level
    # Find the tallest bar at this level to set panel height
    max_bh = max(_active_bar_heights)
    pad_y = 0.06
    panel_top = 0.5 - max_bh * 0.45 - pad_y
    panel_bot = 0.5 + max_bh * 0.45 + pad_y

    panel_cx = (panel_left + panel_right) / 2.0
    panel_cy = (panel_top + panel_bot) / 2.0
    panel_hw = (panel_right - panel_left) / 2.0
    panel_hh = (panel_bot - panel_top) / 2.0

    # Rounded rect with generous corner radius
    corner_r = min(panel_hw, panel_hh) * 0.6

    dx = abs(nx - panel_cx) - (panel_hw - corner_r)
    dy = abs(ny - panel_cy) - (panel_hh - corner_r)

    if dx <= 0 and dy <= 0:
        return min(dx, dy)
    elif dx > 0 and dy > 0:
        return math.sqrt(dx * dx + dy * dy)
    else:
        return max(dx, dy)


# ── Wave mask ────────────────────────────────────────────────────────────

def draw_wave_mask(w, h, fill_level, level=0):
    """White panel + bar silhouettes for blur mask."""
    set_level_scale(level)
    pixels = []
    for py in range(h):
        for px in range(w):
            nx = (px + 0.5) / w
            ny = (py + 0.5) / h

            # Panel shape
            pd = panel_sdf(nx, ny, level)
            panel_alpha = clamp(0.5 - pd * w)

            # Bar shapes
            bar_alpha = 0.0
            for i in range(NUM_BARS):
                d = bar_sdf(nx, ny, i)
                aa = clamp(0.5 - d * w)
                if aa > bar_alpha:
                    bar_alpha = aa

            # Combine: panel at lower opacity + bars at full
            combined = max(panel_alpha * 0.5, bar_alpha)

            if combined > 0.001:
                a = int(clamp(combined) * 255)
                pixels.append((255, 255, 255, a))
            else:
                pixels.append((0, 0, 0, 0))
    return pixels


# ── Wave edge highlights ─────────────────────────────────────────────────

def _render_wave_edge(w, h, fill_level, mode="dark", level=0):
    """Render glass panel + wave bars.

    Dark mode: white frosted-glass panel behind bars, white bar outlines,
    indigo fill. The panel ensures visibility on any dark wallpaper.

    Light mode: subtle panel tint, indigo bar outlines and fill.

    Level 0 = ghost (panel visible, bars faint, no indigo).
    """
    set_level_scale(level)

    if level >= 1:
        fill_level = 1.0

    is_ghost = (level == 0)

    pixels = []

    # Panel rendering params
    if mode == "dark":
        panel_stroke_w = 3.5 / w
        if is_ghost:
            # LISTENING STATE: glowing white glass pill — unmistakable
            panel_body_opacity = 0.45   # clearly visible frosted glass
            panel_edge_opacity = 0.90   # bright white border
            panel_glow_w = 28.0 / w     # wide bloom around the pill
            panel_glow_opacity = 0.50   # strong white glow
        else:
            panel_body_opacity = 0.18 + 0.08 * min(level, 5)
            panel_edge_opacity = 0.45 + 0.10 * min(level, 5)
            panel_glow_w = 8.0 / w
            panel_glow_opacity = 0.15 + 0.08 * min(level, 5)
        pr, pg, pb = 255, 255, 255
    else:
        panel_stroke_w = 2.0 / w
        if is_ghost:
            # LISTENING STATE on light bg: visible indigo-tinted pill
            panel_body_opacity = 0.12
            panel_edge_opacity = 0.35
            panel_glow_w = 6.0 / w
            panel_glow_opacity = 0.10
        else:
            panel_body_opacity = 0.04 + 0.03 * min(level, 5)
            panel_edge_opacity = 0.12 + 0.06 * min(level, 5)
            panel_glow_w = 5.0 / w
            panel_glow_opacity = 0.05
        pr, pg, pb = IND_R, IND_G, IND_B

    # Bar rendering params
    bar_stroke_w = 2.5 / w

    for py in range(h):
        for px in range(w):
            nx = (px + 0.5) / w
            ny = (py + 0.5) / h

            # ── Panel layer ──
            pd = panel_sdf(nx, ny, level)
            p_edge = clamp(1.0 - abs(pd) / panel_stroke_w)
            p_inside = clamp(0.5 - pd * w)
            p_glow = 0.0
            if pd > 0:
                # Softer falloff for ghost mode → wider visible bloom
                exp = 1.3 if is_ghost else 2.0
                p_glow = clamp(1.0 - pd / panel_glow_w) ** exp * 0.7

            # ── Bar layer ──
            best_bar_edge = 0.0
            best_bar_inside = 0.0

            for i in range(NUM_BARS):
                d = bar_sdf(nx, ny, i)
                be = clamp(1.0 - abs(d) / bar_stroke_w)
                bi = clamp(0.5 - d * w)
                if be > best_bar_edge:
                    best_bar_edge = be
                if bi > best_bar_inside:
                    best_bar_inside = bi

            # ── Composite: bars on top of panel ──
            r, g, b, a = 0, 0, 0, 0

            if best_bar_edge > 0.01:
                if is_ghost:
                    # Listening: visible bar outlines inside the glass pill
                    if mode == "dark":
                        r, g, b = 255, 255, 255
                        a = int(clamp(best_bar_edge * 0.60) * 255)
                    else:
                        r, g, b = IND_R, IND_G, IND_B
                        a = int(clamp(best_bar_edge * 0.40) * 255)
                else:
                    # Active: indigo edges with a bright highlight
                    # Mix indigo with a white highlight on top half
                    bright = 0.3  # 30% white highlight
                    r = min(255, int(IND_R * (1 - bright) + 255 * bright))
                    g = min(255, int(IND_G * (1 - bright) + 255 * bright))
                    b = min(255, int(IND_B * (1 - bright) + 255 * bright))
                    a = int(clamp(best_bar_edge * 0.95) * 255)

            elif best_bar_inside > 0.01 and not is_ghost:
                # Bar body fill — solid indigo
                r, g, b = IND_R, IND_G, IND_B
                a = int(clamp(best_bar_inside * 0.95) * 255)

            elif p_edge > 0.01:
                # Panel edge
                r, g, b = pr, pg, pb
                a = int(clamp(p_edge * panel_edge_opacity) * 255)

            elif p_inside > 0.01:
                # Panel body
                r, g, b = pr, pg, pb
                a = int(clamp(p_inside * panel_body_opacity) * 255)

            elif p_glow > 0.01:
                # Panel outer glow
                r, g, b = pr, pg, pb
                a = int(clamp(p_glow * panel_glow_opacity) * 255)

            pixels.append((r, g, b, a))
    return pixels


def draw_wave_edge(w, h, fill_level, level=0):
    return _render_wave_edge(w, h, fill_level, mode="light", level=level)


def draw_wave_edge_dark(w, h, fill_level, level=0):
    return _render_wave_edge(w, h, fill_level, mode="dark", level=level)


# ── Processing dots ───────────────────────────────────────────────────────

def draw_proc_mask(w, h, frame, total_frames=12):
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

print("Generating glassmorphic waveform assets (panel + 22 bars)...")

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
