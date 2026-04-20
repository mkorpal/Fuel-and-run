#!/usr/bin/env python3
"""Generate PWA icons for Fuel & Run — ⚡FR on Dark Slate background."""

from PIL import Image, ImageDraw, ImageFont
import os

DIR = os.path.dirname(os.path.abspath(__file__))

BG = (18, 19, 24)        # #121318 Dark Slate bg
ACCENT = (110, 198, 160)  # #6ec6a0 green accent
BOLT = (240, 169, 70)     # #f0a946 warm amber for the bolt

SIZES = [192, 512]

for size in SIZES:
    img = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(img)

    # Rounded-rect background (approx - fill full, then round corners)
    # Actually iOS clips to rounded rect automatically, just fill solid
    
    # Draw ⚡ bolt as a polygon
    cx, cy = size / 2, size / 2
    s = size / 512  # scale factor

    # Lightning bolt polygon points (hand-tuned for good look)
    bolt_pts = [
        (cx - 20*s, cy - 140*s),  # top-left of upper
        (cx + 70*s, cy - 140*s),  # top-right of upper
        (cx + 10*s, cy - 20*s),   # right notch
        (cx + 80*s, cy - 20*s),   # right of middle
        (cx - 30*s, cy + 160*s),  # bottom point
        (cx + 10*s, cy + 20*s),   # left notch
        (cx - 60*s, cy + 20*s),   # left of middle
    ]
    draw.polygon(bolt_pts, fill=BOLT)

    # Draw "FR" text below/around bolt — actually overlay at bottom
    # Use a clean font
    try:
        # Try system fonts
        for fname in [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNSDisplay.ttf",
            "/System/Library/Fonts/SFCompact.ttf",
            "/Library/Fonts/Arial.ttf",
        ]:
            if os.path.exists(fname):
                font = ImageFont.truetype(fname, int(90 * s))
                break
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    text = "FR"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = cx - tw / 2
    ty = cy + 90 * s
    draw.text((tx, ty), text, fill=ACCENT, font=font)

    out = os.path.join(DIR, f"icon-{size}.png")
    img.save(out, "PNG")
    print(f"Created {out}")

# Also create apple-touch-icon (180x180)
size = 180
img = Image.new("RGBA", (size, size), BG)
draw = ImageDraw.Draw(img)
s = size / 512
cx, cy = size / 2, size / 2

bolt_pts = [
    (cx - 20*s, cy - 140*s),
    (cx + 70*s, cy - 140*s),
    (cx + 10*s, cy - 20*s),
    (cx + 80*s, cy - 20*s),
    (cx - 30*s, cy + 160*s),
    (cx + 10*s, cy + 20*s),
    (cx - 60*s, cy + 20*s),
]
draw.polygon(bolt_pts, fill=BOLT)

try:
    for fname in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/System/Library/Fonts/SFCompact.ttf",
        "/Library/Fonts/Arial.ttf",
    ]:
        if os.path.exists(fname):
            font = ImageFont.truetype(fname, int(90 * s))
            break
    else:
        font = ImageFont.load_default()
except Exception:
    font = ImageFont.load_default()

bbox = draw.textbbox((0, 0), "FR", font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text((cx - tw/2, cy + 90*s), "FR", fill=ACCENT, font=font)

out = os.path.join(DIR, "apple-touch-icon.png")
img.save(out, "PNG")
print(f"Created {out}")
