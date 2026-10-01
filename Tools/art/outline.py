"""An object's outline first, its colours after (Docs/Design/22b, how an object is taken apart; the owner's order,
2026-10-01: cut it out, pull its outline, complete the lines and drop what lies outside them, colour in what is
missing against the cut-out, check it is whole). This tool does the lines and the check; object_fix.py --outline
colours in.

    python Tools/art/outline.py <hero> <series> <part> [--src orig] [--drop 2,3] [--erase x0,y0,x1,y1;...]
    python Tools/art/outline.py <hero> <series> <part> --check [--file st/fix/<part>_<seed>.png]   (is it whole?)

1. the part (st/part_<part>.png; --src orig takes the one kept in st/_orig/ before any fix).
2. its lines: anime art draws its outline dark. An edge pixel with a dark line within 2 px is a drawn edge; one
   without is a cut edge (hidden behind something, or cut off by the split).
3. complete the lines: at both ends of a cut the drawn outline goes on in its own direction; limbs and the weapon
   go on to the end of their skeleton reach (as in object_fix) and close there, other parts close where the two
   lines meet (or straight across the cut when they don't). What is outside the lines goes: specks not joined to
   the object, and, told with --drop, regions a drawn line cuts off from it (a cape stuck to an arm: the sheet
   numbers them, a program can't tell a cape from a glove).
5. --check: the outline is closed, nothing lies outside it, how much inside it still has no colour.

Writes st/outline/<part>_lines.png (the completed outline, black on clear: the line art for colouring),
<part>_shape.png (inside the outline), <part>_fill.png (inside but not coloured yet), <part>.jpg (the sheet) and
<part>.json (numbers).
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inx_rig import WORK, load_joints   # noqa: E402
import object_fix as F                  # noqa: E402

LINE_Y = 80        # darker than this (luma) is line
PLATE_LINE = 70    # brighter than this in the plate's line art (white on black) is line
NEAR_LINE = 2      # px: an edge this close to a line is drawn
TANGENT_R = 16     # px of drawn edge that give a line's direction at a cut
MIN_CUT = 12       # px: shorter cuts are just gaps in the line, closed straight (too short to tell a direction)
REGION_MIN = 80    # px: smaller regions cut off by lines aren't listed


def luma(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def edges(on):
    return on & ~ndimage.binary_erosion(on)


def far_pair(pts):
    """the two points of a set furthest apart"""
    if len(pts) > 400:
        pts = pts[:: len(pts) // 400 + 1]
    d = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
    i, j = np.unravel_index(int(np.argmax(d)), d.shape)
    return pts[i], pts[j]


def tangent(end, drawn_pts):
    """the direction the drawn edge runs in as it reaches a cut's end (y, x), pointing on past the end"""
    near = drawn_pts[((drawn_pts - end) ** 2).sum(-1) <= TANGENT_R ** 2]
    if len(near) < 4:
        return None
    c = near.mean(0)
    u, s, vt = np.linalg.svd(near - c, full_matrices=False)
    t = vt[0]
    if (end - c) @ t < 0:
        t = -t
    return t


def ray_until(p, t, inside, limit):
    """walk from p along t while inside the mask (or up to limit px when no mask); the last point"""
    q = p.astype(float)
    for _ in range(int(limit)):
        n = q + t
        y, x = int(round(n[0])), int(round(n[1]))
        if not (0 <= y < inside.shape[0] and 0 <= x < inside.shape[1]) or not inside[y, x]:
            break
        q = n
    return q


def intersect(p1, t1, p2, t2, limit):
    """where two rays meet, if ahead of both within limit"""
    a = np.array([[t1[0], -t2[0]], [t1[1], -t2[1]]])
    if abs(np.linalg.det(a)) < 1e-3:
        return None
    s, u = np.linalg.solve(a, p2 - p1)
    if 0 < s < limit and 0 < u < limit:
        return p1 + s * t1
    return None


def poly_mask(pts, shape):
    img = Image.new("L", (shape[1], shape[0]), 0)
    ImageDraw.Draw(img).polygon([(float(p[1]), float(p[0])) for p in pts], fill=255)
    return np.asarray(img) > 0


def make_lineart(ld, st):
    """the plate's line art on white, white lines on black (workflow lineart), saved as st/lineart.png"""
    import heroine_j3 as j3
    import comfy_gen as cg
    import workflows as W
    full = Image.open(os.path.join(ld, "full.png")).convert("RGBA")
    bg = Image.new("RGBA", full.size, (255, 255, 255, 255))
    bg.alpha_composite(full)
    tmp = os.path.join(os.environ.get("TEMP", "."), "outline_lineart_in.png")
    bg.convert("RGB").save(tmp)
    wf = W.fill(W.load("lineart"), {"輸入圖": {"image": cg.upload(tmp)}})
    out = j3.run_wf(wf).convert("L").resize(full.size, Image.LANCZOS)
    os.remove(tmp)
    out.save(os.path.join(st, "lineart.png"))
    print("line art ->", os.path.join(st, "lineart.png"), flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("series")
    ap.add_argument("part", help="a part, or 'lineart' to pull the plate's line art once (needs ComfyUI)")
    ap.add_argument("--no-plate-lines", action="store_true", help="only the part's own dark pixels as lines")
    ap.add_argument("--erase-poly", default="", help="'x,y x,y x,y|...': erase inside these polygons (not the object)")
    ap.add_argument("--erase-rgb", default="", help="'r,g,b:tol[:all];...': erase this colour within 6 px of the edge (a fringe of hair), or anywhere with :all")
    ap.add_argument("--no-grow", action="store_true", help="the shape is already whole (a face oval): only close holes")
    ap.add_argument("--line", default="", help="'x,y x,y ...|...': outline strokes to add (a hidden edge, drawn by hand)")
    ap.add_argument("--src", default="current", choices=["current", "orig"])
    ap.add_argument("--drop", default="", help="numbers of regions (from the sheet) that don't belong to the object")
    ap.add_argument("--erase", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--file", default="", help="--check this picture (a candidate in st/fix/) instead of the part")
    a = ap.parse_args()
    ld = os.path.join(WORK, "live", a.hero, a.series)
    st = os.path.join(ld, "st")
    od = os.path.join(st, "outline")
    os.makedirs(od, exist_ok=True)
    src = os.path.join(st, "_orig", "part_%s.png" % a.part) if a.src == "orig" else os.path.join(st, "part_%s.png" % a.part)
    if not os.path.exists(src):
        src = os.path.join(st, "part_%s.png" % a.part)
    if a.part == "lineart":
        return make_lineart(ld, st)
    part = np.asarray(Image.open(src).convert("RGBA")).copy()

    if a.check:   # 5. whole? against the shape the outline closed
        if a.file:
            part = np.asarray(Image.open(a.file).convert("RGBA")).copy()
        shape = np.asarray(Image.open(os.path.join(od, "%s_shape.png" % a.part)))[..., 3] > 128
        on = part[..., 3] > 128
        outside = int((on & ~ndimage.binary_dilation(shape, iterations=2)).sum())
        empty = int((shape & ~on).sum())
        from object_check import whole
        pieces, holes, floating = whole(part[..., 3])   # one piece (pieces held inside its outline count as floating)
        ok = bool(pieces == 1 and outside == 0 and empty <= 0.02 * shape.sum())
        rep = {"part": a.part, "pieces": pieces, "floating": floating, "outside_px": outside, "empty_px": empty,
               "empty_share": round(empty / max(1, int(shape.sum())), 4), "passed": ok}
        json.dump(rep, open(os.path.join(od, "%s_check.json" % a.part), "w"), indent=1)
        print("%s: %d piece(s)%s, %d px outside the outline, %d px inside without colour (%.1f%%) -> %s" % (
            a.part, pieces, (" + %d floating" % floating) if floating else "", outside, empty, 100 * rep["empty_share"],
            "whole" if ok else "not whole"), flush=True)
        return 0 if ok else 1

    # marks made by looking (erase polygons, hand strokes, regions to drop, erase boxes) are kept per part in
    # st/outline/marks.json: given here they are saved, left out they are read back
    mp = os.path.join(od, "marks.json")
    marks = json.load(open(mp)) if os.path.exists(mp) else {}
    mine = marks.get(a.part, {})
    given = {k: getattr(a, k) for k in ("erase_poly", "erase_rgb", "line", "drop", "erase", "no_grow") if getattr(a, k)}
    if given:
        mine.update(given)
        marks[a.part] = mine
        json.dump(marks, open(mp, "w"), indent=1)
    for k, v in mine.items():
        setattr(a, k, v)
    meta = json.load(open(os.path.join(st, "parts.json")))
    pv = dict(meta.get("pivots") or {})
    if os.path.exists(os.path.join(ld, "fig_joints.json")):
        for k, v in load_joints(os.path.join(ld, "fig_joints.json")).items():
            if isinstance(v, list) and k not in pv:
                pv[k] = v
    erase = [tuple(int(v) for v in b.split(",")) for b in a.erase.split(";") if b]
    for poly in [q for q in a.erase_poly.split("|") if q.strip()]:
        pts = [tuple(float(v) for v in xy.split(",")) for xy in poly.split()]
        part[poly_mask([(y, x) for x, y in pts], part.shape[:2])] = 0
    for spec in [q for q in a.erase_rgb.split(";") if q.strip()]:   # a fringe: that colour within 6 px of the edge
        col, _, rest = spec.partition(":")
        tol, _, where = rest.partition(":")   # "...:tol:all" anywhere in the part, not only near its edge
        c = np.array([float(v) for v in col.split(",")])
        on0 = part[..., 3] > 128
        band = on0 if where == "all" else on0 & ~ndimage.binary_erosion(on0, iterations=6)
        near = np.abs(part[..., :3].astype(float) - c).max(-1) <= float(tol or 60)
        part[band & near, 3] = 0
    part = F.clean(part, erase)   # 1. cut out: far specks and erase boxes go
    on = part[..., 3] > 128
    rgb = part[..., :3].astype(float)

    # 2. lines: the plate's line art (st/lineart.png, "outline.py <hero> <series> lineart") where the part is, and
    # its own dark pixels (a black glove is a fill, not a line: its edge still counts as drawn). Only lines 1 px in
    # from the part's edge are its own: where it is hidden, the line on the plate is the thing in front's
    dark = on & (luma(rgb) < LINE_Y)
    la_path = os.path.join(st, "lineart.png")
    if os.path.exists(la_path) and not a.no_plate_lines:
        la = np.asarray(Image.open(la_path).convert("L")) > PLATE_LINE
        dark |= la & ndimage.binary_erosion(on, iterations=1)
    lab, n = ndimage.label(dark)
    if n:
        sz = ndimage.sum(dark, lab, range(1, n + 1))
        dark = np.isin(lab, [i + 1 for i, v in enumerate(sz) if v >= 8])
    near_dark = ndimage.binary_dilation(dark, iterations=NEAR_LINE)
    rim = edges(on)
    drawn = rim & near_dark
    cut = rim & ~near_dark

    # regions a drawn line cuts off from the object's main body (numbered for --drop)
    body = on & ~dark
    rl, rn = ndimage.label(body)
    rs = ndimage.sum(body, rl, range(1, rn + 1)) if rn else []
    main_r = 1 + int(np.argmax(rs)) if rn else 0
    regions = [i + 1 for i, v in enumerate(rs) if v >= REGION_MIN and i + 1 != main_r]
    drop = [int(v) for v in a.drop.split(",") if v]
    dropped = np.zeros_like(on)
    for k, r in enumerate(regions, 1):
        if k in drop:
            dropped |= rl == r   # the line between stays: it is the object's own edge
    if dropped.any():
        on = on & ~dropped
        part[dropped, 3] = 0
        rim = edges(on)
        drawn = rim & near_dark
        cut = rim & ~near_dark

    # 3. complete the lines at every cut
    guide = F.reach_mask(a.part, part[..., 3], pv, on.shape)
    size = float(max(np.ptp(np.nonzero(on)[0]), np.ptp(np.nonzero(on)[1]))) if on.any() else 0.0
    drawn_pts = np.argwhere(drawn)
    add = np.zeros_like(on)
    cl, cn = ndimage.label(ndimage.binary_dilation(cut, iterations=1) & ~drawn | cut)
    closes = []
    for i in range(1, 0 if a.no_grow else cn + 1):
        seg = np.argwhere((cl == i) & cut)
        if len(seg) < MIN_CUT:
            continue
        touch = seg[ndimage.binary_dilation(drawn, iterations=2)[seg[:, 0], seg[:, 1]]]
        if len(touch) < 2:
            continue
        e1, e2 = far_pair(touch)
        e1, e2 = e1.astype(float), e2.astype(float)
        t1, t2 = tangent(e1, drawn_pts), tangent(e2, drawn_pts)
        if t1 is None or t2 is None:
            continue
        if guide is not None:   # on to the end of the skeleton reach, then across
            f1 = ray_until(e1, t1, guide, size)
            f2 = ray_until(e2, t2, guide, size)
            ln = min(np.linalg.norm(f1 - e1), np.linalg.norm(f2 - e2))   # both sides go on as far: no lopsided point
            f1, f2 = e1 + t1 * ln, e2 + t2 * ln
            poly = [e1, f1, f2, e2]
            how = "reach"
            if ln < 3 or np.linalg.norm(f1 - f2) < 0.6 * np.linalg.norm(e1 - e2):   # the lines lean in: a point, not a limb
                poly, how = [e1, e2], "straight"
        else:
            x = intersect(e1, t1, e2, t2, 0.5 * size)
            poly, how = ([e1, x, e2], "meet") if x is not None else ([e1, e2], "straight")
        if len(poly) > 2:
            add |= poly_mask(poly, on.shape) & ~on
        closes.append({"from": [int(e1[1]), int(e1[0])], "to": [int(e2[1]), int(e2[0])], "how": how, "cut_px": int(len(seg))})
    strokes = np.zeros_like(on)
    if a.line.strip():   # hand-drawn outline strokes: the edge of what is hidden, joined to the part at both ends
        img = Image.new("L", (on.shape[1], on.shape[0]), 0)
        dr = ImageDraw.Draw(img)
        for pl in [q for q in a.line.split("|") if q.strip()]:
            pts = [tuple(float(v) for v in xy.split(",")) for xy in pl.split()]
            dr.line(pts, fill=255, width=3)
        strokes = np.asarray(img) > 0
        closed = ndimage.binary_fill_holes(on | strokes)
        add |= closed & ~on
    if F.kind_of(a.part) in ("objects", "objects-back"):
        add |= guide   # a weapon's pieces joined by lines as thick as it (object_fix.bridges)
    elif guide is not None and not strokes.any():
        add &= guide   # a limb doesn't grow past its skeleton reach (strokes drawn by hand are followed as drawn)
    shape = ndimage.binary_fill_holes(ndimage.binary_closing(on | add, iterations=2))
    sl, sn = ndimage.label(shape)   # one object: the biggest closed shape; what lies outside it is noise
    if sn > 1:   # ...and pieces held inside its outline (an orb in a staff's curl), as object_check counts them
        ss = ndimage.sum(shape, sl, range(1, sn + 1))
        mainl = 1 + int(np.argmax(ss))
        from scipy.spatial import Delaunay
        hull = Delaunay(np.argwhere(sl == mainl)[::5])
        keep = [mainl] + [i for i in range(1, sn + 1) if i != mainl and ss[i - 1] >= 60
                          and hull.find_simplex(np.argwhere(sl == i).mean(0)) >= 0]
        shape = np.isin(sl, keep)
    noise = on & ~shape
    part[noise, 3] = 0
    on = on & shape
    outline = edges(shape)
    new_line = outline & ~ndimage.binary_dilation(drawn, iterations=1)
    lines = (outline | dark) & shape
    fill = shape & ~on
    warn = []
    side = a.part[-2:] if a.part[-2:] in ("-l", "-r") else ""
    other = a.part[:-1] + ("l" if side == "-r" else "r") if side else ""
    if other and F.kind_of(a.part) in F.REACH and F.kind_of(a.part) != "hand" and os.path.exists(os.path.join(st, "part_%s.png" % other)):
        # a pair: this side's shape against the other side's piece flipped onto this bone; much outside it means
        # another thing's outline (a cape stuck to the arm) came with the cut
        import contextlib
        import io as _io
        with contextlib.redirect_stdout(_io.StringIO()):
            twin = F.mirrored(a.part, st, pv, (on.shape[1], on.shape[0]))[..., 3] > 128
        near_twin = ndimage.binary_dilation(twin, iterations=10)
        out_share = float((shape & ~near_twin).sum()) / max(1, int(shape.sum()))
        if out_share > 0.3:
            warn.append("%d%% of its shape lies outside the other side's (flipped onto this bone): another thing's "
                        "outline (a cape?) came with it; take the other side's (object_fix --mirror) or --drop / --erase it"
                        % int(100 * out_share))

    # outputs
    blk = np.zeros(on.shape + (4,), np.uint8)
    blk[lines] = (0, 0, 0, 255)
    Image.fromarray(blk).save(os.path.join(od, "%s_lines.png" % a.part))
    m = np.zeros(on.shape + (4,), np.uint8)
    m[shape] = (255, 255, 255, 255)
    Image.fromarray(m).save(os.path.join(od, "%s_shape.png" % a.part))
    m = np.zeros(on.shape + (4,), np.uint8)
    m[fill] = (255, 255, 255, 255)
    Image.fromarray(m).save(os.path.join(od, "%s_fill.png" % a.part))
    Image.fromarray(part).save(os.path.join(od, "%s_cut.png" % a.part))   # the cut-out after erase / drop
    rep = {"part": a.part, "src": a.src, "drawn_edge_px": int(drawn.sum()), "cut_edge_px": int(cut.sum()),
           "drawn_share": round(int(drawn.sum()) / max(1, int((drawn | cut).sum())), 3), "closes": closes,
           "regions": [{"n": k, "px": int(rs[r - 1]), "dropped": k in drop} for k, r in enumerate(regions, 1)],
           "fill_px": int(fill.sum()), "shape_px": int(shape.sum()),
           "noise_px": int(noise.sum()), "warnings": warn}
    json.dump(rep, open(os.path.join(od, "%s.json" % a.part), "w"), indent=1)

    # the sheet: cut-out | lines (green drawn edge, red cut edge, numbered regions) | completed (blue new line,
    # magenta to colour) | the line art alone
    ys, xs = np.nonzero(shape | dropped | noise)
    x0, y0 = max(0, xs.min() - 20), max(0, ys.min() - 20)
    x1, y1 = min(on.shape[1], xs.max() + 20), min(on.shape[0], ys.max() + 20)
    grey = np.array(F.GREY, float)

    def view(img):
        return img[y0:y1, x0:x1]
    base = np.where(on[..., None], rgb, grey)
    t1_ = base.copy()
    t2_ = base * 0.35 + grey * 0.65
    t2_[dark] = (0, 0, 0)
    t2_[ndimage.binary_dilation(drawn)] = (40, 200, 60)
    t2_[ndimage.binary_dilation(cut)] = (230, 40, 40)
    t2_[dropped | noise] = (240, 200, 0)
    t3_ = base.copy()
    t3_[fill] = t3_[fill] * 0.3 + np.array([255, 0, 255]) * 0.7
    t3_[ndimage.binary_dilation(new_line)] = (40, 90, 255)
    t4_ = np.full(on.shape + (3,), 255.0)
    t4_[lines] = 0
    tiles = [(t1_, "cut-out"), (t2_, "lines: green drawn, red cut"), (t3_, "completed: blue new line, magenta to colour"),
             (t4_, "line art")]
    tiles[1] = (t2_, "lines: green drawn, red cut, yellow dropped")
    ims = []
    for t, cap in tiles:
        im = Image.fromarray(view(t).astype(np.uint8))
        k = 360.0 / im.height
        im = im.resize((max(1, int(im.width * k)), 360), Image.NEAREST if k > 1 else Image.LANCZOS)
        if cap.startswith("lines"):
            d = ImageDraw.Draw(im)
            for n_, r in enumerate(regions, 1):
                cy_, cx_ = np.argwhere(rl == r).mean(0)
                d.text(((cx_ - x0) * k, (cy_ - y0) * k), str(n_), fill=(255, 255, 0) if n_ not in drop else (120, 120, 0))
        ims.append((im, cap))
    sheet = Image.new("RGB", (sum(i.width for i, _ in ims) + 6 * len(ims), 382), (40, 40, 48))
    x = 0
    for im, cap in ims:
        sheet.paste(im, (x, 22))
        ImageDraw.Draw(sheet).text((x + 4, 4), cap, fill=(255, 255, 255))
        x += im.width + 6
    sheet.save(os.path.join(od, "%s.jpg" % a.part), quality=88)
    print("%s: edge %d%% drawn, %d cut(s) closed (%s), %d region(s) cut off by lines%s, %d px to colour -> %s" % (
        a.part, int(100 * rep["drawn_share"]), len(closes), ", ".join(c["how"] for c in closes) or "-", len(regions),
        (" (dropped %s)" % a.drop) if drop else "", rep["fill_px"], os.path.join(od, "%s.jpg" % a.part)), flush=True)
    for w in warn:
        print("  !! " + w, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
