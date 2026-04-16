#!/usr/bin/env python3
"""
Generates waveform overlay and processing animation PNGs.
Transparent backgrounds — the glassmorphic backdrop is handled by NSVisualEffectView.

Outputs (in assets/):
  wave_vol_0..5.png       (96x32  soundwave at different volumes)
  wave_vol_0..5@2x.png    (192x64 retina)
  proc_0..11.png          (32x14  processing dots animation)
  proc_0..11@2x.png       (64x28  retina)
"""

import struct, zlib, math
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)

# Indigo color for active elements
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

# ── Wave volume images ─────────────────────────────────────────────────────

def draw_wave(w, h, fill_level):
    """Draw soundwave bars on a transparent background.

    fill_level: 0.0 (silent/white) to 1.0 (full indigo).
    Bars are white when silent, indigo fills from bottom as volume increases.
    """
    pixels = []

    # Bar configuration — 11 bars with varying heights for a waveform look
    num_bars = 11
    bar_heights = [0.30, 0.45, 0.55, 0.70, 0.85, 1.0, 0.85, 0.70, 0.55, 0.45, 0.30]
    bar_width_frac = 0.045  # fraction of total width per bar
    gap_frac = 0.025  # gap between bars
    total_bars_width = num_bars * bar_width_frac + (num_bars - 1) * gap_frac
    start_x = (1.0 - total_bars_width) / 2.0  # center bars

    bar_rounding = min(w, h) * 0.06  # radius for rounded bar ends

    for py in range(h):
        for px in range(w):
            nx = px / float(w)
            ny = py / float(h)

            alpha = 0.0
            is_filled = False  # whether this pixel is in the filled (indigo) zone

            for i, bh in enumerate(bar_heights):
                bx = start_x + i * (bar_width_frac + gap_frac)
                bw = bar_width_frac

                # Vertical extent of bar (centered vertically)
                bar_top = 0.5 - bh * 0.45
                bar_bot = 0.5 + bh * 0.45

                # Check if pixel is within bar x range
                if bx <= nx <= bx + bw:
                    # Distance from bar edges for rounding
                    rx = bar_rounding / w
                    ry = bar_rounding / h

                    # Simple rounded rectangle SDF in normalized coords
                    bar_cy = (bar_top + bar_bot) / 2.0
                    bar_hw = bw / 2.0
                    bar_hh = (bar_bot - bar_top) / 2.0

                    dx = abs(nx - (bx + bar_hw)) - (bar_hw - rx)
                    dy = abs(ny - bar_cy) - (bar_hh - ry)

                    if dx <= 0 and dy <= 0:
                        # Inside the rectangle body
                        alpha = 1.0
                    elif dx > 0 and dy > 0:
                        # Corner region
                        corner_dist = math.sqrt(dx * dx + dy * dy)
                        # Anti-alias at the edge (in pixel coords)
                        edge_px = corner_dist * w  # approximate pixel distance
                        alpha = clamp(rx * w - edge_px + 0.5)
                    elif dx > 0:
                        alpha = clamp(rx * w - dx * w + 0.5)
                    else:
                        alpha = clamp(ry * h - dy * h + 0.5)

                    if alpha > 0:
                        # Fill from bottom: calculate how much of bar is filled
                        fill_threshold = bar_bot - (bar_bot - bar_top) * fill_level
                        if ny >= fill_threshold:
                            is_filled = True
                        break

            if alpha > 0:
                a = int(clamp(alpha) * 255)
                if is_filled:
                    pixels.append((IND_R, IND_G, IND_B, a))
                else:
                    # White with slight transparency for unfilled bars
                    pixels.append((255, 255, 255, int(a * 0.9)))
            else:
                pixels.append((0, 0, 0, 0))

    return pixels


# ── Processing animation frames ────────────────────────────────────────────

def draw_proc_frame(w, h, frame, total_frames=12):
    """Draw 3 pulsing dots for processing animation.

    Each dot pulses with a phase offset. Transparent background.
    """
    pixels = []

    num_dots = 3
    dot_radius = min(w, h) * 0.18
    dot_spacing = w * 0.22
    start_x = w / 2.0 - (num_dots - 1) * dot_spacing / 2.0
    cy = h / 2.0

    # Phase offset for each dot
    phase_offset = [0, 0.33, 0.66]

    for py in range(h):
        for px in range(w):
            best_alpha = 0.0
            best_r, best_g, best_b = 0, 0, 0

            for i in range(num_dots):
                cx = start_x + i * dot_spacing
                dist = math.sqrt((px + 0.5 - cx) ** 2 + (py + 0.5 - cy) ** 2)

                # Pulse: varies radius and opacity
                t = (frame / total_frames + phase_offset[i]) % 1.0
                pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi)

                current_radius = dot_radius * (0.7 + 0.3 * pulse)
                current_opacity = 0.5 + 0.5 * pulse

                # Anti-aliased circle
                circle_alpha = clamp(current_radius - dist + 0.5)
                dot_alpha = circle_alpha * current_opacity

                if dot_alpha > best_alpha:
                    best_alpha = dot_alpha
                    best_r, best_g, best_b = IND_R, IND_G, IND_B

            if best_alpha > 0.01:
                a = int(clamp(best_alpha) * 255)
                pixels.append((best_r, best_g, best_b, a))
            else:
                pixels.append((0, 0, 0, 0))

    return pixels


# ── Generate all assets ────────────────────────────────────────────────────

print("Generating waveform overlay icons...")

# Wave volume: 96x32 pt (192x64 @2x)
WAVE_W, WAVE_H = 96, 32
for lvl in range(6):
    fill = lvl / 5.0
    for scale, suffix in [(1, ""), (2, "@2x")]:
        sw, sh = WAVE_W * scale, WAVE_H * scale
        px = draw_wave(sw, sh, fill)
        write_png(ASSETS / f"wave_vol_{lvl}{suffix}.png", px, sw, sh)

# Processing animation: 32x14 pt (64x28 @2x), 12 frames
PROC_W, PROC_H = 32, 14
PROC_FRAMES = 12
for frame in range(PROC_FRAMES):
    for scale, suffix in [(1, ""), (2, "@2x")]:
        sw, sh = PROC_W * scale, PROC_H * scale
        px = draw_proc_frame(sw, sh, frame, PROC_FRAMES)
        write_png(ASSETS / f"proc_{frame}{suffix}.png", px, sw, sh)

print("Waveform icons done.")
