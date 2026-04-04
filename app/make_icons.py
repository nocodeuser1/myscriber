#!/usr/bin/env python3
"""
Generates all myScriber icon assets using only stdlib.
Uses SDF (signed distance fields) + 4x supersampling for smooth anti-aliased edges.

Outputs:
  assets/mic_template.png       (18x18  menubar icon)
  assets/mic_template@2x.png    (36x36  menubar icon retina)
  assets/AppIcon.iconset/       (app icon, converted to .icns by iconutil)
"""

import struct, zlib, math, os, subprocess, shutil
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)

# ── Minimal PNG writer (stdlib only) ────────────────────────────────────────

def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

def write_png(path, pixels, w, h):
    """pixels: flat list of (r,g,b,a) tuples."""
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

# ── SDF helpers ─────────────────────────────────────────────────────────────

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

def dist(ax, ay, bx, by):
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)

def sdf_capsule(px, py, cx, cy, w, h):
    """Signed distance to a vertical capsule (pill shape)."""
    r = w / 2.0
    top = cy + r
    bot = cy + h - r
    if py < top:
        return dist(px, py, cx + r, top) - r
    elif py > bot:
        return dist(px, py, cx + r, bot) - r
    else:
        return abs(px - (cx + r)) - r

def sdf_circle_arc(px, py, cx, cy, radius, thickness, min_angle_deg=0, max_angle_deg=180):
    """Signed distance to a circular arc (portion of a ring)."""
    d = dist(px, py, cx, cy)
    ring_dist = abs(d - radius) - thickness / 2.0
    angle = math.degrees(math.atan2(py - cy, px - cx))
    if angle < 0:
        angle += 360
    if min_angle_deg <= angle <= max_angle_deg:
        return ring_dist
    a1 = math.radians(min_angle_deg)
    a2 = math.radians(max_angle_deg)
    d1 = dist(px, py, cx + radius * math.cos(a1), cy + radius * math.sin(a1)) - thickness / 2
    d2 = dist(px, py, cx + radius * math.cos(a2), cy + radius * math.sin(a2)) - thickness / 2
    return min(d1, d2)

def sdf_rect(px, py, rx, ry, rw, rh):
    """Signed distance to an axis-aligned rectangle."""
    dx = max(rx - px, px - (rx + rw))
    dy = max(ry - py, py - (ry + rh))
    return max(dx, dy)

def sdf_rounded_rect(px, py, rx, ry, rw, rh, cr):
    """Signed distance to a rounded rectangle."""
    cx = max(rx + cr, min(px, rx + rw - cr))
    cy = max(ry + cr, min(py, ry + rh - cr))
    d = dist(px, py, cx, cy) - cr
    inner_d = sdf_rect(px, py, rx, ry, rw, rh)
    if inner_d < 0 and not (
        (px < rx + cr or px > rx + rw - cr) and
        (py < ry + cr or py > ry + rh - cr)
    ):
        return inner_d
    return d

# ── Draw menubar template icon (anti-aliased, 4x supersampled) ─────────────

def draw_menubar(size):
    S = size
    SS = 8  # 8x supersampling for crisp edges on retina
    HR = S * SS
    pixels_hr = []

    # Filled capsule body (solid, not outline)
    MW  = HR * 0.32
    MH  = HR * 0.44
    MX  = HR * 0.5 - MW / 2.0
    MY  = HR * 0.04

    ARC_CX = HR * 0.5
    ARC_CY = MY + MH - HR * 0.02
    ARC_R  = HR * 0.28
    ARC_T  = max(3.0, HR * 0.11)   # thicker strokes for clarity

    POLE_CX = HR * 0.5
    POLE_Y1 = ARC_CY + ARC_R
    POLE_Y2 = POLE_Y1 + HR * 0.13
    POLE_T  = ARC_T

    BASE_Y  = POLE_Y2
    BASE_X1 = HR * 0.5 - HR * 0.20
    BASE_X2 = HR * 0.5 + HR * 0.20
    BASE_T  = ARC_T

    for py_hr in range(HR):
        for px_hr in range(HR):
            px = px_hr + 0.5
            py = py_hr + 0.5

            # Capsule is FILLED (solid body)
            d_capsule = sdf_capsule(px, py, MX, MY, MW, MH)
            d_arc = sdf_circle_arc(px, py, ARC_CX, ARC_CY, ARC_R, ARC_T, 0, 180)
            d_pole = sdf_rect(px, py, POLE_CX - POLE_T / 2, POLE_Y1, POLE_T, POLE_Y2 - POLE_Y1)
            d_base = sdf_rect(px, py, BASE_X1, BASE_Y - BASE_T / 2, BASE_X2 - BASE_X1, BASE_T)

            d = min(d_capsule, d_arc, d_pole, d_base)
            alpha = clamp(0.5 - d)
            pixels_hr.append(alpha)

    pixels = []
    for y in range(S):
        for x in range(S):
            total = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    total += pixels_hr[(y * SS + sy) * HR + (x * SS + sx)]
            avg = total / (SS * SS)
            a = int(clamp(avg) * 255)
            pixels.append((0, 0, 0, a))

    return pixels

# ── Draw app icon (purple bg, white mic) ────────────────────────────────────

def draw_app_icon(size):
    S = size
    pixels = []

    cr = S * 0.225
    BR, BG, BB = 74, 63, 199

    MW = S * 0.22;  MH = S * 0.35
    MX = S * 0.5 - MW / 2;  MY = S * 0.18

    ARC_CX = S * 0.5;  ARC_CY = MY + MH
    ARC_R  = S * 0.215; ARC_T  = max(2, S * 0.028)

    POLE_X  = S * 0.5
    POLE_Y1 = ARC_CY + ARC_R; POLE_Y2 = POLE_Y1 + S * 0.09
    POLE_T  = ARC_T

    BASE_Y  = POLE_Y2
    BASE_X1 = S * 0.5 - S * 0.115; BASE_X2 = S * 0.5 + S * 0.115
    BASE_T  = ARC_T

    NK_W = S * 0.065; NK_H = S * 0.055
    NK_X = S * 0.5 - NK_W / 2; NK_Y = MY + MH

    for py in range(S):
        for px in range(S):
            d_bg = sdf_rounded_rect(px, py, 0, 0, S - 1, S - 1, cr)
            if d_bg > 0.5:
                pixels.append((0, 0, 0, 0))
                continue

            bg_alpha = clamp(0.5 - d_bg)

            d_capsule = sdf_capsule(px, py, MX, MY, MW, MH)
            d_neck = sdf_rect(px, py, NK_X, NK_Y, NK_W, NK_H)
            d_arc = sdf_circle_arc(px, py, ARC_CX, ARC_CY, ARC_R, ARC_T, 0, 180)
            d_pole = sdf_rect(px, py, POLE_X - POLE_T / 2, POLE_Y1, POLE_T, POLE_Y2 - POLE_Y1)
            d_base = sdf_rect(px, py, BASE_X1, BASE_Y - BASE_T / 2, BASE_X2 - BASE_X1, BASE_T)

            d = min(d_capsule, d_neck, d_arc, d_pole, d_base)
            white_alpha = clamp(0.5 - d)

            r = int(BR * (1 - white_alpha) + 255 * white_alpha)
            g = int(BG * (1 - white_alpha) + 255 * white_alpha)
            b = int(BB * (1 - white_alpha) + 255 * white_alpha)
            a = int(bg_alpha * 255)

            pixels.append((r, g, b, a))

    return pixels

# ── Draw menubar volume icon (blue mic with fill level) ─────────────────────

def draw_menubar_volume(size, fill_level):
    """Draw a blue mic icon with interior fill from bottom to top.

    fill_level: 0.0 (outline only) to 1.0 (fully filled).
    Used during recording to show speech volume.
    """
    S = size
    SS = 8  # match template quality
    HR = S * SS

    # Same geometry as draw_menubar
    MW  = HR * 0.32
    MH  = HR * 0.44
    MX  = HR * 0.5 - MW / 2.0
    MY  = HR * 0.04

    ARC_CX = HR * 0.5
    ARC_CY = MY + MH - HR * 0.02
    ARC_R  = HR * 0.28
    ARC_T  = max(3.0, HR * 0.11)

    POLE_CX = HR * 0.5
    POLE_Y1 = ARC_CY + ARC_R
    POLE_Y2 = POLE_Y1 + HR * 0.13
    POLE_T  = ARC_T

    BASE_Y  = POLE_Y2
    BASE_X1 = HR * 0.5 - HR * 0.20
    BASE_X2 = HR * 0.5 + HR * 0.20
    BASE_T  = ARC_T

    # Capsule outline stroke width (in HR-space)
    STROKE_W = max(3.0, HR * 0.11)

    # Fill threshold Y: capsule fills from bottom (MY+MH) to top (MY)
    fill_y_top = MY + MH * (1.0 - fill_level)

    pixels_hr = []
    for py_hr in range(HR):
        for px_hr in range(HR):
            px = px_hr + 0.5
            py = py_hr + 0.5

            d_capsule = sdf_capsule(px, py, MX, MY, MW, MH)
            d_arc = sdf_circle_arc(px, py, ARC_CX, ARC_CY, ARC_R, ARC_T, 0, 180)
            d_pole = sdf_rect(px, py, POLE_CX - POLE_T / 2, POLE_Y1, POLE_T, POLE_Y2 - POLE_Y1)
            d_base = sdf_rect(px, py, BASE_X1, BASE_Y - BASE_T / 2, BASE_X2 - BASE_X1, BASE_T)

            # Arc/pole/base: always solid
            d_other = min(d_arc, d_pole, d_base)
            alpha_other = clamp(0.5 - d_other)

            # Capsule outline ring
            alpha_ring = clamp(0.5 - (abs(d_capsule) - STROKE_W / 2.0))

            # Capsule fill: inside capsule AND below fill line
            alpha_inside = clamp(0.5 - d_capsule)          # smooth at capsule edge
            alpha_below  = clamp(0.5 - (fill_y_top - py))  # smooth at fill line
            alpha_fill   = alpha_inside * alpha_below

            alpha = max(alpha_other, alpha_ring, alpha_fill)
            pixels_hr.append(alpha)

    # Downsample with blue color
    BLUE_R, BLUE_G, BLUE_B = 30, 144, 255

    pixels = []
    for y in range(S):
        for x in range(S):
            total = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    total += pixels_hr[(y * SS + sy) * HR + (x * SS + sx)]
            avg = total / (SS * SS)
            a = int(clamp(avg) * 255)
            pixels.append((BLUE_R, BLUE_G, BLUE_B, a))

    return pixels


# ── Generate all assets ──────────────────────────────────────────────────────

print("Generating myScriber icons...")

for sz, suffix in [(18, ""), (36, "@2x")]:
    px = draw_menubar(sz)
    write_png(ASSETS / f"mic_template{suffix}.png", px, sz, sz)

iconset = ASSETS / "AppIcon.iconset"
iconset.mkdir(exist_ok=True)

for sz in [16, 32, 128, 256, 512]:
    px = draw_app_icon(sz)
    write_png(iconset / f"icon_{sz}x{sz}.png", px, sz, sz)
    if sz <= 512:
        px2 = draw_app_icon(sz * 2)
        write_png(iconset / f"icon_{sz}x{sz}@2x.png", px2, sz * 2, sz * 2)

icns_path = ASSETS / "AppIcon.icns"
if shutil.which("iconutil"):
    r = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
        capture_output=True,
    )
    if r.returncode == 0:
        print(f"  {icns_path}")
    else:
        print(f"  iconutil error: {r.stderr.decode().strip()}")
else:
    print("  (iconutil not available here — runs on Mac during install)")

# Volume-level menubar icons (blue, 6 levels: 0=outline, 5=full fill)
print("Generating volume icons...")
VOL_LEVELS = 6
for lvl in range(VOL_LEVELS):
    fill = lvl / (VOL_LEVELS - 1)
    for sz, suffix in [(18, ""), (36, "@2x")]:
        px = draw_menubar_volume(sz, fill)
        write_png(ASSETS / f"mic_vol_{lvl}{suffix}.png", px, sz, sz)

print("Icons done.")
