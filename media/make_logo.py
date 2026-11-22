"""Draws the project logo (media/logo.png, 512x512): a gold coin over rising price bars."""
import os
from PIL import Image, ImageDraw, ImageFont

S = 4                      # supersample
N = 512 * S
img = Image.new("RGB", (N, N), (17, 20, 27))
d = ImageDraw.Draw(img)


def r(x0, y0, x1, y1, fill, rad=0):
    d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=rad * S, fill=fill)


# panel with a thin border, like the addon's window
r(24, 24, 488, 488, (41, 48, 62), 56)
r(30, 30, 482, 482, (24, 28, 37), 50)

# faint grid lines
for y in (150, 230, 310, 390):
    r(70, y, 442, y + 2, (38, 44, 57))

# rising bars
bars = [(86, 330), (156, 286), (226, 306), (296, 232), (366, 170)]
for i, (x, top) in enumerate(bars):
    col = (51, 204, 255) if i < 4 else (255, 200, 60)
    r(x, top, x + 54, 420, col, 8)
r(70, 420, 442, 426, (90, 100, 120), 3)

# coin
cx, cy, cr = 176, 170, 92
d.ellipse([(cx - cr) * S, (cy - cr) * S, (cx + cr) * S, (cy + cr) * S], fill=(120, 82, 12))
d.ellipse([(cx - cr + 8) * S, (cy - cr + 8) * S, (cx + cr - 8) * S, (cy + cr - 8) * S], fill=(255, 200, 60))
d.ellipse([(cx - cr + 22) * S, (cy - cr + 22) * S, (cx + cr - 22) * S, (cy + cr - 22) * S],
          outline=(170, 118, 20), width=5 * S)
font = None
for name in ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"):
    try:
        font = ImageFont.truetype(name, 84 * S)
        break
    except OSError:
        pass
box = d.textbbox((0, 0), "UA", font=font)
d.text((cx * S - (box[0] + box[2]) / 2, cy * S - (box[1] + box[3]) / 2), "UA", font=font, fill=(96, 62, 6))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
img.resize((512, 512), Image.LANCZOS).save(out)
print("wrote", out)
