"""Put an object the AI drew (object_edit.py, st/gen/<part>_<tag><seed>.png) into a plate's split as a part
(Docs/Design/22c, step 4: assemble). What the plate shows stays the plate's own pixels; the AI's drawing fills what
is hidden or empty. The part's earlier version is kept in st/_orig/ the first time.

    python Tools/art/object_place.py <hero> <series> <gen.png> --as <part>[,<part>...] [options]

  --merge            the plate's pixels where the part already shows the plate (it matches full.png), the AI's
                     everywhere else (default: the AI's drawing alone)
  --bones            split the drawing between limb pieces (--as upperarm-r,forearm-r[,hand-r]): each pixel goes to
                     the nearest bone (st/parts.json pivots)
  --front <layers>   a thing passing through the character: what of it the plate shows over these layers
                     (default face,front_hair) becomes <part>-front, listed after the front hair; the rest stays
  --fit [layers]     move and scale the drawing onto where the plate draws the thing first (default: the --as
                     parts' own layers): the shift and scale that cover most of it (±40 px, 0.85-1.15)
  --box x0,y0,x1,y1  put the drawing's own box onto this one (one scale, middles matched): the edit model drew the
                     thing bigger or off its place and the plate's split of it is too broken for --fit to go by
                     (the box read off the plate by whoever checks it)
  --clear <layers>   clear where these layers show the plate (the face, the eyes): a hat brim or bangs drawn lower
                     than the plate has them would hide the eyes the plate shows (nothing of the plate is pasted)
  --clip-above Y     drop what lies above row Y (a skirt drawn with a bit of the top it hangs from)
  --no-skin          drop skin-coloured pixels (legs seen through a skirt's slit)
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inx_rig import WORK          # noqa: E402
import object_fix as F            # noqa: E402


def keep(st, name):
    p = os.path.join(st, "part_%s.png" % name)
    o = os.path.join(st, "_orig")
    os.makedirs(o, exist_ok=True)
    if os.path.exists(p) and not os.path.exists(os.path.join(o, "part_%s.png" % name)):
        shutil.copy(p, os.path.join(o, "part_%s.png" % name))


def fit(gen, target, turns=(-12, -8, -4, 0, 4, 8, 12), shift=40):
    """the shift and scale (about the drawing's middle) that put the drawing's shape most onto the target shape
    (overlap / union), searched coarse then fine; returns the moved drawing and what was found"""
    on = gen[..., 3] > 0
    ys, xs = np.nonzero(on)
    cy, cx = ys.mean(), xs.mean()
    tgt = target
    h, w = on.shape

    def moved(sc, dx, dy, rot=0.0, img=None):
        img = on if img is None else img
        # output (x, y) takes input c + R(-rot) ((x, y) - c - d) / sc  (about the drawing's middle c)
        a = np.radians(rot)
        ca, sa = np.cos(a) / sc, np.sin(a) / sc
        ox, oy = cx + dx, cy + dy
        coef = (ca, sa, cx - ca * ox - sa * oy, -sa, ca, cy + sa * ox - ca * oy)
        im = Image.fromarray(img.astype(np.uint8) * 255 if img.dtype == bool else img)
        return np.asarray(im.transform((w, h), Image.AFFINE, coef, Image.NEAREST if img.dtype == bool else Image.BICUBIC))

    def score(sc, dx, dy, rot):
        m = moved(sc, dx, dy, rot) > 128
        return (m & tgt).sum() / max(1, (m | tgt).sum())
    best = (score(1.0, 0, 0, 0.0), 1.0, 0, 0, 0.0)
    for rot in turns:
        for sc in (0.85, 0.95, 1.05, 1.15):
            for dx in range(-shift, shift + 1, max(10, shift // 4)):
                for dy in range(-shift, shift + 1, max(10, shift // 4)):
                    v = score(sc, dx, dy, rot)
                    if v > best[0]:
                        best = (v, sc, dx, dy, rot)
    _, sc0, dx0, dy0, r0 = best
    for rot in (r0 - 2, r0, r0 + 2):
        for sc in (sc0 - 0.03, sc0, sc0 + 0.03):
            for dx in range(dx0 - 8, dx0 + 9, 2):
                for dy in range(dy0 - 8, dy0 + 9, 2):
                    v = score(sc, dx, dy, rot)
                    if v > best[0]:
                        best = (v, sc, dx, dy, rot)
    v, sc, dx, dy, rot = best
    out = moved(sc, dx, dy, rot, gen)
    return out.copy(), (round(float(v), 3), round(float(score(1.0, 0, 0, 0.0)), 3), sc, dx, dy, rot)


def to_box(gen, box):
    """the drawing scaled (one scale: the mean of across and down) and moved so its box sits on box"""
    ys, xs = np.nonzero(gen[..., 3] > 0)
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    sc = ((box[2] - box[0]) / (x1 - x0) + (box[3] - box[1]) / (y1 - y0)) / 2.0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    ox, oy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    h, w = gen.shape[:2]
    coef = (1 / sc, 0, cx - ox / sc, 0, 1 / sc, cy - oy / sc)
    out = np.asarray(Image.fromarray(gen).transform((w, h), Image.AFFINE, coef, Image.BICUBIC)).copy()
    print("  box: scale %.2f, middle (%d,%d) -> (%d,%d)" % (sc, cx, cy, ox, oy), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("series")
    ap.add_argument("gen")
    ap.add_argument("--as", dest="parts", required=True)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--bones", action="store_true")
    ap.add_argument("--front", default=None, nargs="?", const="face,front_hair")
    ap.add_argument("--clip-above", type=int, default=None)
    ap.add_argument("--fit", default=None, nargs="?", const="")
    ap.add_argument("--wide", action="store_true", help="--fit: turns up to ±40 degrees, shifts up to ±100 px, and the "
                                                         "drawing mirrored too (a bow drawn curving the other way)")
    ap.add_argument("--no-skin", action="store_true")
    ap.add_argument("--box", default="", help="x0,y0,x1,y1: the drawing's box goes onto this one")
    ap.add_argument("--clear", default="", help="layers: this part stays clear where they show the plate")
    a = ap.parse_args()
    ld = os.path.join(WORK, "live", a.hero, a.series)
    st = os.path.join(ld, "st")
    full = np.asarray(Image.open(os.path.join(ld, "full.png")).convert("RGBA")).astype(int)
    gen = np.asarray(Image.open(a.gen).convert("RGBA")).copy()
    if a.clip_above is not None:
        gen[:a.clip_above, :, 3] = 0
    if a.no_skin:
        r, g, b = gen[..., 0].astype(int), gen[..., 1].astype(int), gen[..., 2].astype(int)
        skin = (r > 190) & (g > 140) & (b > 130) & (r - b > 15)
        gen[ndimage.binary_dilation(skin, iterations=1), 3] = 0
    parts = a.parts.split(",")
    if a.fit is not None:
        target = np.zeros(gen.shape[:2], bool)
        for n in (a.fit or a.parts).split(","):
            f = os.path.join(st, "part_%s.png" % n)
            if os.path.exists(f):
                target |= np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 128
        if a.wide:
            turns = tuple(range(-40, 41, 5))
            best_ = None
            for flip in (False, True):
                g_ = gen[:, ::-1].copy() if flip else gen
                # mirror about the drawing's own middle, not the picture's
                if flip:
                    xs_ = np.nonzero(gen[..., 3] > 0)[1]
                    shift_x = int(round(xs_.min() + xs_.max() - (gen.shape[1] - 1)))
                    g_ = np.roll(g_, shift_x, axis=1)
                r_ = fit(g_, target, turns, 100)
                if best_ is None or r_[1][0] > best_[1][1][0]:
                    best_ = (flip, r_)
            flip, (gen, (v, v0, sc, dx, dy, rot)) = best_
            print("  mirrored: %s" % flip, flush=True)
        else:
            gen, (v, v0, sc, dx, dy, rot) = fit(gen, target)
        print("  fit: overlap %.2f -> %.2f (scale %.2f, shift %+d,%+d, turn %+.0f deg)" % (v0, v, sc, dx, dy, rot), flush=True)
    if a.box:
        gen = to_box(gen, [float(v) for v in a.box.split(",")])
    if a.clear:
        shown = np.zeros(gen.shape[:2], bool)
        for n in a.clear.split(","):
            f = os.path.join(st, "part_%s.png" % n)
            if os.path.exists(f):
                o = np.asarray(Image.open(f).convert("RGBA")).astype(int)
                shown |= (o[..., 3] > 128) & (np.abs(o[..., :3] - full[..., :3]).max(-1) < 30)
        gen = gen.copy()
        print("  clear: %d px over what the plate shows of %s" % (int((shown & (gen[..., 3] > 0)).sum()), a.clear), flush=True)
        gen[shown, 3] = 0
    meta = json.load(open(os.path.join(st, "parts.json")))
    pv = dict(meta.get("pivots") or {})

    pieces = {}
    if a.bones:   # each pixel to the nearest bone of the limb
        on = gen[..., 3] > 0
        ys, xs = np.nonzero(on)
        pts = np.stack([xs, ys], -1).astype(float)
        d = []
        for p in parts:
            b = F.bone(p, pv)
            if b is None:
                raise SystemExit("no bone for %s" % p)
            d.append(F.seg_dist(pts, b[0], b[1]))
        best = np.argmin(np.stack(d, 0), 0)
        for k, p in enumerate(parts):
            m = np.zeros_like(gen)
            sel = best == k
            m[ys[sel], xs[sel]] = gen[ys[sel], xs[sel]]
            pieces[p] = m
    else:
        pieces[parts[0]] = gen

    for p, img in pieces.items():
        path = os.path.join(st, "part_%s.png" % p)
        if a.merge and os.path.exists(path):   # the plate where the part shows it, the AI elsewhere
            img = img.copy()
            names = [q["name"] for q in meta["order_back_to_front"]]
            for src in (os.path.join(st, "_orig", "part_%s.png" % p), path, os.path.join(st, "_orig", "part_%s-front.png" % p),
                        os.path.join(st, "part_%s-front.png" % p)):
                if not os.path.exists(src):
                    continue
                cur = np.asarray(Image.open(src).convert("RGBA")).astype(int)
                shows = (cur[..., 3] > 128) & (np.abs(cur[..., :3] - full[..., :3]).max(-1) < 30)
                img[shows] = cur[shows].astype(np.uint8)
            # where a layer behind this one shows the plate (legs through a skirt's slit), this one stays clear
            behind = np.zeros(img.shape[:2], bool)
            for n in names[:names.index(p)] if p in names else []:
                f = os.path.join(st, "part_%s.png" % n)
                if os.path.exists(f) and n not in (p, p + "-front"):
                    o = np.asarray(Image.open(f).convert("RGBA")).astype(int)
                    behind |= (o[..., 3] > 128) & (np.abs(o[..., :3] - full[..., :3]).max(-1) < 30)
            mine = np.zeros(img.shape[:2], bool)
            for src in (os.path.join(st, "_orig", "part_%s.png" % p), path):
                if os.path.exists(src):
                    cur = np.asarray(Image.open(src).convert("RGBA")).astype(int)
                    mine |= (cur[..., 3] > 128) & (np.abs(cur[..., :3] - full[..., :3]).max(-1) < 30)
            img[behind & ~mine, 3] = 0
        keep(st, p)
        if a.front is not None:   # what the plate shows over these layers goes in front of the bangs
            over = np.zeros(img.shape[:2], bool)
            for n in a.front.split(","):
                f = os.path.join(st, "_orig", "part_%s.png" % n) if os.path.exists(os.path.join(st, "_orig", "part_%s.png" % n)) \
                    else os.path.join(st, "part_%s.png" % n)
                if os.path.exists(f):
                    over |= np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 128
            plate_part = np.zeros(img.shape[:2], bool)   # where the plate draws this thing (its split layers)
            for n in (p, p + "-front"):
                f = os.path.join(st, "_orig", "part_%s.png" % n)
                f = f if os.path.exists(f) else os.path.join(st, "part_%s.png" % n)
                if os.path.exists(f):
                    o = np.asarray(Image.open(f).convert("RGBA")).astype(int)
                    plate_part |= (o[..., 3] > 128) & (np.abs(o[..., :3] - full[..., :3]).max(-1) < 30)   # shown, not filled
            front = (img[..., 3] > 0) & ndimage.binary_dilation(over, iterations=2) & ndimage.binary_dilation(plate_part, iterations=2)
            fr = np.zeros_like(img)
            fr[front] = img[front]
            img = img.copy()
            img[front, 3] = 0
            keep(st, p + "-front")
            Image.fromarray(fr).save(os.path.join(st, "part_%s-front.png" % p))
            names = [q["name"] for q in meta["order_back_to_front"]]
            if p + "-front" not in names:
                at = names.index("front_hair") + 1 if "front_hair" in names else len(names)
                meta["order_back_to_front"].insert(at, {"name": p + "-front", "file": "part_%s-front.png" % p, "depth": 0.0,
                                                        "from": "AI-drawn %s: over the face and the bangs" % p})
                json.dump(meta, open(os.path.join(st, "parts.json"), "w"))
            print("  %s-front: %d px" % (p, int(front.sum())), flush=True)
        Image.fromarray(img).save(path)
        meta = json.load(open(os.path.join(st, "parts.json")))   # marked as drawn: the rig keeps its own colours
        for q in meta["order_back_to_front"]:
            if q["name"] == p:
                q["drawn"] = os.path.basename(a.gen) if not a.merge else ""
        json.dump(meta, open(os.path.join(st, "parts.json"), "w"))
        print("%s <- %s: %d px%s" % (p, os.path.basename(a.gen), int((img[..., 3] > 0).sum()),
                                     " (plate pixels kept where it shows)" if a.merge else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
