"""Ultimate AH logo - final (polished "monogram").

A struck-gold AH ligature on a midnight-indigo tile. The A shares its right
stem with the H, the two crossbars climb like a stair, and the right stem of
the H carries on upwards into an arrow in a hotter, paler gold: a rising price.

The whole mark is laid out on a 64-unit grid (1 unit = 8 px at 512), so stems,
bars, bevels and the frame land on whole pixels in the 64 px thumbnail.

Everything is drawn from signed distance fields in numpy, supersampled and
downsampled with LANCZOS. No fonts, no external assets.

Run:  python media/make_logo.py
Writes logo.png (512), logo_64.png (a separately rendered 64 px master) and the addon's own copy,
UltimateAH/logo.tga: the game reads TGA (32-bit, uncompressed, sides a power of two), not PNG.
"""
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
U = 8.0                                   # one grid unit in 512-space

# ------------------------------------------------------------ design (units)
BADGE_R = 11.5                            # outer corner radius
RIM = 3.0                                 # gold frame thickness
RIM_BEV = 1.0

CAP, BASE = 15.0, 57.0                    # cap line and baseline
LEG_X, LEG_W = 8.0, 6.5                   # A's leaning leg: left foot, width
S1 = (28.0, 35.0)                         # shared stem (A right leg = H left)
S2 = (45.0, 52.0)                         # H right stem = arrow shaft
ABAR = (46.0, 52.0)                       # A crossbar (low)
HBAR = (34.0, 40.0)                       # H crossbar, one bar-height higher
HEAD_CX = 48.5
HEAD_TIP, HEAD_BARB, HEAD_NOTCH = 7.0, 20.5, 17.5
HEAD_HW = 8.5
FLARE, FLARE_H = 1.0, 6.0                 # chiselled feet: spread, height

BEV = 8.0                                 # bevel width, 512-space


def mark_parts():
    """Convex pieces of the mark, in grid units. Their union has no seams."""
    run = S1[0] - LEG_X
    leg = [(LEG_X, BASE), (LEG_X + LEG_W, BASE), (LEG_X + LEG_W + run, CAP), (S1[0], CAP)]
    stem1 = [(S1[0], CAP), (S1[1], CAP), (S1[1], BASE), (S1[0], BASE)]
    stem2 = [(S2[0], HEAD_NOTCH - 1.5), (S2[1], HEAD_NOTCH - 1.5), (S2[1], BASE), (S2[0], BASE)]
    abar = [(LEG_X + LEG_W + 0.5, ABAR[0]), (S1[0] + 2, ABAR[0]), (S1[0] + 2, ABAR[1]), (LEG_X + LEG_W + 0.5, ABAR[1])]
    hbar = [(S1[1] - 2, HBAR[0]), (S2[0] + 2, HBAR[0]), (S2[0] + 2, HBAR[1]), (S1[1] - 2, HBAR[1])]
    # arrowhead: a triangle down to the notch line plus two swept barbs
    a = HEAD_HW * (HEAD_NOTCH - HEAD_TIP) / (HEAD_BARB - HEAD_TIP)
    tip = (HEAD_CX, HEAD_TIP)
    head_c = [tip, (HEAD_CX + a, HEAD_NOTCH), (HEAD_CX - a, HEAD_NOTCH)]
    parts = [leg, stem1, stem2, abar, hbar, head_c]
    for sgn in (1.0, -1.0):
        barb = (HEAD_CX + sgn * HEAD_HW, HEAD_BARB)
        root = (HEAD_CX + sgn * (S2[1] - S2[0]) / 2, HEAD_NOTCH)
        inner = (barb[0] + 1.8 * (root[0] - barb[0]), barb[1] + 1.8 * (root[1] - barb[1]))
        parts.append([tip, barb, inner])
    if FLARE > 0:
        # chiselled feet: two stacked wedges approximate a bracketed flare
        slope = run / (BASE - CAP)
        feet = [(LEG_X, LEG_X + LEG_W, slope), (S1[0], S1[1], 0.0), (S2[0], S2[1], 0.0)]
        for x0, x1, sl in feet:
            for f, fh in ((FLARE, FLARE_H * 0.4), (FLARE * 0.45, FLARE_H)):
                parts.append([(x0 - f, BASE), (x1 + f, BASE),
                              (x1 + sl * fh, BASE - fh), (x0 + sl * fh, BASE - fh)])
    return parts


LETTER_GOLD = [
    (0.00, (78, 36, 6)),
    (0.20, (126, 68, 10)),
    (0.40, (180, 108, 16)),
    (0.60, (232, 162, 34)),
    (0.80, (250, 204, 82)),
    (0.92, (255, 232, 150)),
    (1.00, (255, 248, 220)),
]
ARROW_GOLD = [                            # hotter and paler than the letters
    (0.00, (124, 70, 6)),
    (0.20, (180, 110, 10)),
    (0.40, (232, 168, 30)),
    (0.60, (255, 212, 64)),
    (0.80, (255, 232, 118)),
    (0.92, (255, 245, 184)),
    (1.00, (255, 253, 232)),
]


def ramp(t, stops):
    t = np.clip(t, 0.0, 1.0)
    xs = [s[0] for s in stops]
    out = np.empty(t.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(t, xs, [s[1][c] for s in stops])
    return out


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def over(rgb, color, a):
    a3 = a[..., None]
    if not isinstance(color, np.ndarray):
        color = np.asarray(color, np.float32)
    return rgb * (1.0 - a3) + color * a3


def inside_distance(mask, cap):
    """Exact Euclidean distance (pixels) from inside pixels to the outline, capped."""
    n = mask.shape[1]
    idx = np.arange(n, dtype=np.int32)[None, :]
    zero = ~mask
    left = np.maximum.accumulate(np.where(zero, idx, -10 ** 6), axis=1)
    right = np.minimum.accumulate(np.where(zero, idx, 10 ** 6)[:, ::-1], axis=1)[:, ::-1]
    g = np.minimum(np.minimum(idx - left, right - idx), cap).astype(np.float32)
    g2 = g * g
    best = g2.copy()
    for k in range(1, cap + 1):
        kk = np.float32(k * k)
        np.minimum(best[k:], g2[:-k] + kk, out=best[k:])
        np.minimum(best[:-k], g2[k:] + kk, out=best[:-k])
    return np.clip(np.sqrt(best) - 0.5, 0.0, None)


# light comes from the upper left, slightly in front
L = np.array([-0.46, -0.70, 0.58], np.float32)
L /= np.linalg.norm(L)
Hv = L + np.array([0.0, 0.0, 1.0], np.float32)
Hv /= np.linalg.norm(Hv)


def render(size, ps, small):
    """Render the logo. ps = supersampled pixels per 512-space unit.

    small=True is the thumbnail master: same geometry, but no keyline and no
    sub-pixel detail, a tighter shadow and a little more contrast.
    """
    n = int(round(512 * ps))
    yy, xx = np.mgrid[0:n, 0:n]
    X = ((xx + 0.5) / ps).astype(np.float32)
    Y = ((yy + 0.5) / ps).astype(np.float32)
    del xx, yy

    def gblur(a, sigma):
        s = sigma * ps
        fy = np.fft.fftfreq(n).astype(np.float32)[:, None]
        fx = np.fft.rfftfreq(n).astype(np.float32)[None, :]
        kern = np.exp(-2.0 * (np.pi ** 2) * (s ** 2) * (fx * fx + fy * fy))
        return np.fft.irfft2(np.fft.rfft2(a) * kern, s=a.shape).astype(np.float32)

    def shift(a, dx, dy):
        return np.roll(np.roll(a, int(round(dy * ps)), axis=0), int(round(dx * ps)), axis=1)

    def aa(sd):
        return np.clip(0.5 - sd * ps, 0.0, 1.0)

    def sd_convex(pts):
        pts = np.asarray(pts, np.float32)
        m = len(pts)
        area = 0.0
        for i in range(m):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % m]
            area += x1 * y2 - x2 * y1
        sign = 1.0 if area > 0 else -1.0
        dmin = np.full(X.shape, 1e9, np.float32)
        inside = np.ones(X.shape, bool)
        for i in range(m):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % m]
            ex, ey = bx - ax, by - ay
            px, py = X - ax, Y - ay
            t = np.clip((px * ex + py * ey) / (ex * ex + ey * ey), 0.0, 1.0)
            d = np.hypot(px - ex * t, py - ey * t)
            dmin = np.minimum(dmin, d)
            inside &= (sign * (ex * py - ey * px)) >= 0
        return np.where(inside, -dmin, dmin).astype(np.float32)

    def sd_round_rect(cx, cy, hw, hh, r):
        qx = np.abs(X - cx) - (hw - r)
        qy = np.abs(Y - cy) - (hh - r)
        outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
        inside = np.minimum(np.maximum(qx, qy), 0.0)
        return (outside + inside - r).astype(np.float32)

    def light(h, steep=1.0):
        gy, gx = np.gradient(h, 1.0 / ps)
        nx, ny = -gx * steep, -gy * steep
        inv = 1.0 / np.sqrt(nx * nx + ny * ny + 1.0)
        nx, ny, nz = nx * inv, ny * inv, inv
        diff = nx * L[0] + ny * L[1] + nz * L[2]
        spec = np.clip(nx * Hv[0] + ny * Hv[1] + nz * Hv[2], 0.0, 1.0)
        return diff, spec, ny

    # ------------------------------------------------------------- the tile
    rim_w = RIM * U
    sd_badge = sd_round_rect(256.0, 256.0, 256.0, 256.0, BADGE_R * U)
    badge_a = aa(sd_badge)
    d_in = -sd_badge

    # midnight indigo, lifted behind the letters
    r = np.hypot(X - 256.0, Y - 250.0)
    field = ramp(smooth(0.0, 320.0, r), [
        (0.00, (58, 52, 150)),
        (0.30, (43, 38, 116)),
        (0.62, (26, 23, 76)),
        (1.00, (14, 12, 42)),
    ])
    rgb = field
    # shadow the frame casts on to the field
    ins = np.exp(-np.clip(d_in - rim_w, 0.0, None) / (6.0 if small else 9.0)) * 0.55
    rgb = over(rgb, (4, 3, 14), ins)

    # ------------------------------------------------------------- the mark
    sd_mark = None
    for p in mark_parts():
        s = sd_convex([(x * U, y * U) for x, y in p])
        sd_mark = s if sd_mark is None else np.minimum(sd_mark, s)
    mark_a = aa(sd_mark)

    # the arrow tint: the shaft heats up from the H crossbar to the head
    Xd, Yd = X / U, Y / U
    arrow_w = smooth(HBAR[0], HEAD_BARB + 4.0, Yd) * (Xd > (S1[1] + S2[0]) / 2 - 2.0)

    # cool glow behind the metal, a warm bloom round the arrow, a cast shadow
    glow = gblur(mark_a, 30.0)
    rgb = over(rgb, (112, 104, 240), np.clip(glow * 0.30, 0.0, 1.0))
    bloom = gblur(mark_a * arrow_w, 14.0)
    rgb = over(rgb, (255, 214, 120), np.clip(bloom * 0.22, 0.0, 1.0))
    if small:
        shadow = gblur(shift(mark_a, 4.0, 7.0), 4.0)
        rgb = over(rgb, (3, 2, 12), np.clip(shadow * 0.85, 0.0, 1.0))
    else:
        shadow = gblur(shift(mark_a, 5.0, 9.0), 6.0)
        rgb = over(rgb, (3, 2, 12), np.clip(shadow * 0.78, 0.0, 1.0))
        # thin bronze keyline; it vanishes at thumbnail size instead of going muddy
        rgb = over(rgb, (46, 20, 6), aa(sd_mark - 1.8) * 0.9)

    # struck metal: flat face, hard 45 degree chamfers
    depth = inside_distance(sd_mark < 0.0, int(BEV * ps) + 8) / ps
    depth = np.maximum(-sd_mark, depth - 0.22)
    h = gblur(np.clip(depth, 0.0, BEV), 0.35)
    diff, spec, ny = light(h, steep=1.3)
    flat = smooth(BEV - 1.6, BEV - 0.2, depth)

    v = np.clip((Yd - HEAD_TIP) / (BASE - HEAD_TIP), 0.0, 1.0)
    t = 0.21 + 0.75 * diff + np.clip(ny, 0.0, 1.0) * 0.06
    t += flat * (0.11 - 0.20 * v)
    if not small:
        diag_c = X + Y * 0.80
        t += flat * (np.exp(-((diag_c - 330.0) / 60.0) ** 2) * 0.08)
        hs = gblur(h, 0.8)
        lap = (np.roll(hs, 1, 0) + np.roll(hs, -1, 0) + np.roll(hs, 1, 1) + np.roll(hs, -1, 1) - 4.0 * hs) * (ps * ps)
        t += np.clip(-lap * 0.55, 0.0, 1.0) * 0.16 * smooth(2.0, 5.0, depth)
    gold = ramp(t, LETTER_GOLD)
    hot = ramp(t + 0.04 * flat, ARROW_GOLD)
    gold = gold + (hot - gold) * arrow_w[..., None]
    gold += (np.asarray((255, 248, 222), np.float32) - gold) * (np.power(spec, 40.0) * 0.40 * (1.0 - flat))[..., None]
    rgb = over(rgb, gold, mark_a)

    # ------------------------------------------------------------ the frame
    rim_a = aa(-d_in) * aa(d_in - rim_w)
    rb = RIM_BEV * U
    h_rim = gblur(np.clip(np.minimum(d_in, rim_w - d_in), 0.0, rb), 0.35)
    diff_r, spec_r, ny_r = light(h_rim, steep=1.3)
    flat_r = smooth(rb - 1.6, rb - 0.2, np.minimum(d_in, rim_w - d_in))
    tr = 0.21 + 0.75 * diff_r + np.clip(ny_r, 0.0, 1.0) * 0.06
    tr += flat_r * (0.08 - 0.18 * np.clip(Y / 512.0, 0.0, 1.0))
    rim = ramp(tr, LETTER_GOLD)
    rim += (np.asarray((255, 248, 222), np.float32) - rim) * (np.power(spec_r, 40.0) * 0.35 * (1.0 - flat_r))[..., None]
    # crisp dark seat where the frame meets the field
    rgb = over(rgb, (6, 4, 14), aa(d_in - rim_w - 2.5) * aa(-(d_in - rim_w + 1.0)) * 0.9)
    rgb = over(rgb, rim, rim_a)

    out = np.dstack([np.clip(rgb, 0, 255), badge_a * 255.0]).astype(np.uint8)
    return Image.fromarray(out, "RGBA").resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    render(512, 4.0, small=False).save(os.path.join(HERE, "logo.png"))
    small = render(64, 2.0, small=True)
    small.save(os.path.join(HERE, "logo_64.png"))
    small.save(os.path.join(HERE, "..", "UltimateAH", "logo.tga"))
    print("wrote logo.png and logo_64.png")
