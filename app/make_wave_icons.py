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
    """Bright edge highlights that define the glass shape.

    - Top/upper edges are brightest (catching light from above)
    - Sides have moderate brightness
    - Bottom edges are dimmer
    - When volume increases, indigo fills from bottom inside the bars
    """
    pixels = []
    # Edge stroke width in normalized coords
    stroke_w = 1.4 / w  # ~1.4 pixels

    for py in range(h):
        for px in range(w):
            nx = (px + 0.5) / w
            ny = (py + 0.5) / h

            best_edge = 0.0
            best_fill = 0.0
            best_is_top = False
            best_ny_ratio = 0.5  # where in bar vertically (0=top, 1=bottom)

            for i in range(NUM_BARS):
                d = bar_sdf(nx, ny, i)
                bh = BAR_HEIGHTS[i]
                bar_top = 0.5 - bh * 0.45
                bar_bot = 0.5 + bh * 0.45

                # Edge highlight: bright at the boundary
                edge_alpha = clamp(1.0 - abs(d) / stroke_w)

                # Interior fill (very subtle glass tint)
                interior = clamp(0.5 - d * w) * 0.06  # 6% opacity fill

                if edge_alpha > best_edge:
                    best_edge = edge_alpha
                    # How far down in the bar (0=top, 1=bottom)
                    if bar_bot > bar_top:
                        best_ny_ratio = clamp((ny - bar_top) / (bar_bot - bar_top))
                    best_is_top = ny < (bar_top + bar_bot) / 2.0

                if interior > best_fill:
                    best_fill = interior
                    # Volume fill: indigo from bottom
                    fill_threshold = 1.0 - fill_level
                    if bar_bot > bar_top:
                        bar_ratio = clamp((ny - bar_top) / (bar_bot - bar_top))
                    else:
                        bar_ratio = 0.5

            r, g, b, a = 0, 0, 0, 0

            if best_edge > 0.01:
                # Directional lighting: top edges bright, bottom dimmer
                # This gives the "catching light" effect from the reference
                if best_is_top:
                    brightness = 0.95 - best_ny_ratio * 0.3  # bright at top
                else:
                    brightness = 0.65 - (best_ny_ratio - 0.5) * 0.3  # dimmer at bottom

                brightness = clamp(brightness, 0.3, 1.0)
                edge_opacity = best_edge * brightness

                r = int(255 * brightness)
                g = int(255 * brightness)
                b = int(255 * brightness)
                a = int(clamp(edge_opacity) * 255)

            elif best_fill > 0.01:
                # Subtle interior: check if volume-filled
                for i in range(NUM_BARS):
                    d = bar_sdf(nx, ny, i)
                    if d < 0:  # inside bar
                        bh = BAR_HEIGHTS[i]
                        bar_top = 0.5 - bh * 0.45
                        bar_bot = 0.5 + bh * 0.45
                        fill_threshold_y = bar_bot - (bar_bot - bar_top) * fill_level
                        if ny >= fill_threshold_y and fill_level > 0:
                            # Indigo fill zone
                            r, g, b = IND_R, IND_G, IND_B
                            a = int(clamp(best_fill * 4) * 255)  # stronger in fill zone
                        else:
                            # Subtle white glass tint
                            r, g, b = 255, 255, 255
                            a = int(clamp(best_fill) * 255)
                        break

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
    """Bright edge highlights for processing dots."""
    pixels = []
    num_dots = 3
    dot_radius = min(w, h) * 0.22
    dot_spacing = w * 0.22
    start_x = w / 2.0 - (num_dots - 1) * dot_spacing / 2.0
    cy = h / 2.0
    phase_offset = [0, 0.33, 0.66]
    stroke_w = 1.2  # pixels

    for py in range(h):
        for px in range(w):
            best_edge = 0.0
            best_fill = 0.0
            best_top = False

            for i in range(num_dots):
                cx = start_x + i * dot_spacing
                t = (frame / total_frames + phase_offset[i]) % 1.0
                pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi)
                r = dot_radius * (0.7 + 0.3 * pulse)
                opacity = 0.5 + 0.5 * pulse

                dist = math.sqrt((px + 0.5 - cx) ** 2 + (py + 0.5 - cy) ** 2)
                edge = clamp(1.0 - abs(dist - r) / stroke_w) * opacity
                fill = clamp(r - dist + 0.5) * 0.06 * opacity

                if edge > best_edge:
                    best_edge = edge
                    best_top = (py + 0.5) < cy
                if fill > best_fill:
                    best_fill = fill

            if best_edge > 0.01:
                brightness = 0.9 if best_top else 0.55
                rv = int(255 * brightness)
                a = int(clamp(best_edge * brightness) * 255)
                pixels.append((rv, rv, rv, a))
            elif best_fill > 0.01:
                # Subtle indigo tint for dots
                a = int(clamp(best_fill) * 255)
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
