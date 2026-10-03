"""The weapon and the other objects checked on their own, before they join the character (the owner's order,
2026-10-01: the character passes its standard motions without them, the objects pass here, then the two are put
together). Docs/Flow/13_Objects.md.

    python Tools/art/object_check.py <hero> <series>

Objects: the weapon (objects + objects-back as one thing, turned at its grip) and each part of the "other" pack
(leftover below the neck, anything See-through found that belongs to no pack; each separate thing in them is an
object of its own, turned at its centre). For each:
  - whole: how many pieces it falls into (a weapon must be one) and the holes inside its outline;
  - turned: a full turn in 30 degree steps as a GIF, the tiles in objects_check.jpg.
Writes <work>/live/<hero>/<series>/st/groups/objects/ (object_<name>.gif, objects_check.jpg, objects.json).
Run split_groups.py first (it sorts the packs).
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inx_rig import WORK, load_joints   # noqa: E402
from split_groups import checker, label   # noqa: E402

TILE = 200
HOLE_SHARE = 0.01     # holes inside the outline, of the object's area (and at least HOLE_MIN px)
HOLE_MIN = 40
MIN_PIECE = 60        # px: smaller specks don't count as pieces
OTHER_MIN = 300       # px: smaller bits of a grab-bag layer aren't objects to check


def whole(alpha):
    """(pieces, hole px, floating) of an object's alpha. A piece whose middle lies inside the biggest piece's outline
    (its convex hull: an orb held in a staff's curl) is part of the same thing, counted in floating, not in pieces"""
    on = alpha > 128
    lab, n = ndimage.label(on)
    sizes = ndimage.sum(on, lab, range(1, n + 1)) if n else []
    big = [i + 1 for i, v in enumerate(sizes) if v >= MIN_PIECE]
    floating = 0
    if len(big) > 1:
        from scipy.spatial import Delaunay
        main = max(big, key=lambda i: sizes[i - 1])
        hull = Delaunay(np.argwhere(lab == main)[::5])
        for i in big:
            if i != main and hull.find_simplex(np.argwhere(lab == i).mean(0)) >= 0:
                floating += 1
    holes = ndimage.binary_fill_holes(ndimage.binary_closing(on, iterations=2)) & ~on
    holes = ndimage.binary_opening(holes, iterations=1)
    if floating:   # the opening a floating piece sits in (the ring around a staff's orb) is the design, not a hole
        hl, hn = ndimage.label(ndimage.binary_fill_holes(holes | on) & ~(lab == main))
        around = np.unique(hl[ndimage.binary_dilation(on & (lab != main), iterations=2) & (hl > 0)])
        holes &= ~np.isin(hl, around)
    return len(big) - floating, int(holes.sum()), floating


def main(hero, series):
    ld = os.path.join(WORK, "live", hero, series)
    gd = os.path.join(ld, "st", "groups")
    rep = json.load(open(os.path.join(gd, "groups.json"), encoding="utf-8"))
    parts = {e["pack"]: e["parts"] for e in rep["packs"]}
    meta = json.load(open(os.path.join(ld, "st", "parts.json")))
    pv = meta.get("pivots") or {}
    joints = load_joints(os.path.join(ld, "fig_joints.json")) if os.path.exists(os.path.join(ld, "fig_joints.json")) else {}
    grip = (pv.get("grip") or {}).get("point") or (joints.get("weapon_grip") or {}).get("point")
    objs = []
    weapon = [n for n in parts.get("weapon", [])]
    if weapon:   # the weapon is one thing: its visible part and the stretch the figure hides
        a = None
        for n in weapon:
            im = np.asarray(Image.open(os.path.join(gd, "5_weapon", "part_%s.png" % n)).convert("RGBA"))
            a = im.copy() if a is None else np.asarray(Image.alpha_composite(Image.fromarray(im), Image.fromarray(a)))
        objs.append(("weapon", "武器", a, grip, True))
    for n in parts.get("other", []):   # a grab-bag layer: each separate thing in it is an object of its own
        im = np.asarray(Image.open(os.path.join(gd, "6_other", "part_%s.png" % n)).convert("RGBA"))
        lab, cnt = ndimage.label(im[..., 3] > 128)
        k = 0
        for i in range(1, cnt + 1):
            m = ndimage.binary_dilation(lab == i, iterations=2) & (im[..., 3] > 0)
            if (lab == i).sum() < OTHER_MIN:
                continue
            k += 1
            one = im.copy()
            one[~m, 3] = 0
            objs.append(("%s_%d" % (n, k), "其他：%s 第 %d 件" % (n, k), one, None, False))
    out = os.path.join(gd, "objects")
    os.makedirs(out, exist_ok=True)
    report, rows = {"objects": [], "passed": True}, []
    if not weapon:   # every hero holds one
        report["passed"] = False
        report["objects"].append({"key": "weapon", "title": "武器", "warnings": ["沒有武器（拆層沒分出 objects，可能在「其他」裡）"], "passed": False})
        print("weapon     FAIL  none: See-through gave no objects layer (it may be in leftover)", flush=True)
    for key, title, a, pivot, one_piece in objs:
        ys, xs = np.nonzero(a[..., 3] > 8)
        if not len(xs):
            continue
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        pieces, holes, floating = whole(a[..., 3])
        area = int((a[..., 3] > 128).sum())
        warn = []
        if one_piece and pieces != 1:
            warn.append("斷成 %d 塊（要一整塊）" % pieces)
        if holes > max(HOLE_MIN, HOLE_SHARE * area):
            warn.append("中間有 %d px 的洞" % holes)
        if one_piece and pivot is None:
            warn.append("沒有握點（轉不了）")
        # turned: around its grip, or its centre; the canvas big enough for any turn
        cx, cy = (pivot if pivot else ((x0 + x1) / 2.0, (y0 + y1) / 2.0))
        r = int(max(np.hypot(xs - cx, ys - cy).max(), 10)) + 4
        canvas = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
        canvas.paste(Image.fromarray(a), (int(r - cx), int(r - cy)), Image.fromarray(a))
        frames, tiles = [], []
        for deg in range(0, 360, 15):
            f = canvas.rotate(-deg, resample=Image.BICUBIC, center=(r, r))
            bg = checker(2 * r, 2 * r)
            bg.alpha_composite(f)
            ImageDraw.Draw(bg).ellipse([r - 5, r - 5, r + 5, r + 5], outline=(255, 0, 0, 255), width=2)
            frames.append(bg.convert("RGB").resize((300, 300)))
            if deg % 30 == 0 and deg < 360:
                t = bg.convert("RGBA").resize((TILE, TILE))
                label(t, "%d°" % deg)
                tiles.append(t)
        frames[0].save(os.path.join(out, "object_%s.gif" % key), save_all=True, append_images=frames[1:], duration=90, loop=0)
        row = Image.new("RGBA", (TILE * len(tiles), TILE + 22), (40, 40, 48, 255))
        label(row, "%s  %d px, %d piece(s)%s, holes %d px%s" % (key, area, pieces, (" + %d floating" % floating) if floating else "", holes, ("  !! " + "; ".join(warn)) if warn else "  ok"),
              (255, 120, 120) if warn else (255, 255, 255))
        for i, t in enumerate(tiles):
            row.alpha_composite(t, (i * TILE, 22))
        rows.append(row)
        ok = not warn
        report["passed"] &= ok
        report["objects"].append({"key": key, "title": title, "area": area, "pieces": pieces, "floating": floating, "holes": holes,
                                  "pivot": [float(cx), float(cy)], "warnings": warn, "passed": ok})
        print("%-10s %s  %d px, %d piece(s)%s, holes %d px%s" % (key, "ok  " if ok else "FAIL", area, pieces,
                                                             (" + %d floating" % floating) if floating else "", holes,
                                                          ("  " + "; ".join(warn)) if warn else ""), flush=True)
    if rows:
        sheet = Image.new("RGBA", (max(r.width for r in rows), sum(r.height for r in rows)), (40, 40, 48, 255))
        y = 0
        for r_ in rows:
            sheet.alpha_composite(r_, (0, y))
            y += r_.height
        sheet.convert("RGB").save(os.path.join(out, "objects_check.jpg"), quality=86)
    json.dump(report, open(os.path.join(out, "objects.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("objects %s -> %s" % ("passed" if report["passed"] else "NOT passed", out), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
