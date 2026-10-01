"""Complete one object on its own (Docs/Design/22b, how an object is taken apart: cut it out, check it is whole,
regenerate what is missing or hidden with AI, check it matches its description). Needs ComfyUI.

    python Tools/art/object_fix.py <hero> <series> <part> [--erase x0,y0,x1,y1;...] [--grow auto|none]
                                   [--seeds 1,2,3] [--denoise 1.0] [--apply <seed>]

1. clean: the part's main piece and the pieces near it stay; far specks and --erase boxes (plate pixels: a pouch caught
   with an arm) go.
2. what to fill: for limbs and the weapon the whole reach comes from the skeleton (an upper arm from the shoulder to
   the elbow, a hand past the wrist, the staff from the grip to the tip; pivots in st/parts.json), anything inside that
   reach the part doesn't cover is filled; for other parts, where a layer in front hides them near their own edge.
   --grow none only closes holes inside the outline; --grow hull fills between its own pieces (a hand split by the
   staff it holds); --grow grey repaints grey or washed-out smudges inside it. --mirror starts from the other side's piece flipped onto this side's bone, and paints lightly.
3. fill it alone: the object by itself on a plain grey canvas, enlarged for the model, only the missing area
   inpainted, with the plate's model and the hero's character LoRA (key_poses.LORA), then cut out from the grey.
4. writes st/fix/<part>_<seed>.png (candidates) and st/fix/<part>.jpg (before / what is filled / each candidate) to
   judge "does it match its name"; --apply <seed> puts that candidate in st/part_<part>.png (the original is kept in
   st/_orig/ the first time).
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inx_rig import WORK, load_joints   # noqa: E402
import part_names as P               # noqa: E402

GREY = (200, 200, 205)
MODEL_SIDE = 1024      # the longer side of what the model paints
MARGIN = 48
# what each part is, for the prompt: part_names.py "desc" (the hero's look and outfit come from her character LoRA)
# the skeleton reach of a limb piece: (from pivot, to pivot, how far past "to" it goes, as a share of the bone)
REACH = {"upperarm": ("shoulder", "elbow", 0.12), "forearm": ("elbow", "wrist", 0.1), "hand": ("wrist", None, 0.0),
         "thigh": ("hip", "knee", 0.1), "shin": ("knee", "ankle", 0.08), "foot": ("ankle", "foot", 0.1)}


def kind_of(part):
    base = part.rsplit("-", 1)[0] if part[-2:] in ("-l", "-r") else part
    return base


def seg_t(pts, a, b):
    """where each point falls along a -> b (0 at a, 1 at b, not clipped)"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    return ((pts - a) @ d) / max(1e-6, d @ d)


def seg_dist(pts, a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    t = np.clip(seg_t(pts, a, b), 0.0, 1.0)
    return np.linalg.norm(pts - (a + t[..., None] * (b - a)), axis=-1)


def reach_mask(part, alpha, pv, shape):
    """the area a complete limb piece or weapon covers, from the skeleton: a band along its bone as wide as the part
    usually is (the median, so a cape edge or the staff's crook doesn't widen it); None when the pivots aren't there"""
    k = kind_of(part)
    side = part[-1] if part[-2:] in ("-l", "-r") else ""
    ys, xs = np.mgrid[0:shape[0], 0:shape[1]]
    pts = np.stack([xs, ys], -1).astype(float)
    on = alpha > 128
    if not on.any():
        return None
    if k in ("objects", "objects-back"):   # a weapon: the gaps between its pieces are bridged
        return bridges(on)
    if k not in REACH:
        return None
    f, t_, past = REACH[k]
    a = pv.get("%s_%s" % (f, side))
    if not a:
        return None
    if t_ is None:   # a hand: from the wrist on along the forearm's line, about 0.45 forearm long
        e = pv.get("elbow_%s" % side)
        if not e:
            return None
        b = list(np.asarray(a, float) + (np.asarray(a, float) - np.asarray(e, float)) * 0.45)
    else:
        b = pv.get("%s_%s" % (t_, side))
        if not b:
            return None
        b = list(np.asarray(b, float) + (np.asarray(b, float) - np.asarray(a, float)) * past)
    d = seg_dist(pts, a, b)
    width = float(np.median(d[on])) * 1.6
    return d <= max(width, 6.0)


def bridges(on):
    """lines joining each separate piece to the rest at their closest points, as thick as the object usually is"""
    lab, n = ndimage.label(on)
    sizes = ndimage.sum(on, lab, range(1, n + 1)) if n else []
    keep = [i + 1 for i, v in enumerate(sizes) if v >= 60]
    out = np.zeros(on.shape, bool)
    if len(keep) < 2:
        return out
    thick = max(3, int(round(2 * np.percentile(ndimage.distance_transform_edt(on)[on], 75))))
    img = Image.new("L", (on.shape[1], on.shape[0]), 0)
    dr = ImageDraw.Draw(img)
    joined = {keep[0]}
    while len(joined) < len(keep):   # join the closest free piece to what is joined (a spanning tree)
        pj = np.argwhere(np.isin(lab, list(joined)))[::7]
        best = None
        for i in keep:
            if i in joined:
                continue
            pi = np.argwhere(lab == i)[::7]
            dd = ((pi[:, None, :] - pj[None, :, :]) ** 2).sum(-1)
            q = np.unravel_index(int(np.argmin(dd)), dd.shape)
            if best is None or dd[q] < best[0]:
                best = (dd[q], i, pi[q[0]], pj[q[1]])
        _, i, p1, p2 = best
        dr.line([(int(p1[1]), int(p1[0])), (int(p2[1]), int(p2[0]))], fill=255, width=thick)
        dr.ellipse([p1[1] - thick / 2, p1[0] - thick / 2, p1[1] + thick / 2, p1[0] + thick / 2], fill=255)
        dr.ellipse([p2[1] - thick / 2, p2[0] - thick / 2, p2[1] + thick / 2, p2[0] + thick / 2], fill=255)
        joined.add(i)
    return np.asarray(img) > 0


def bone(part, pv):
    """(from, to) points of a limb piece's bone, or None"""
    k = kind_of(part)
    side = part[-1] if part[-2:] in ("-l", "-r") else ""
    if k not in REACH or not side:
        return None
    f, t, _ = REACH[k]
    a = pv.get("%s_%s" % (f, side))
    if not a:
        return None
    if t is None:
        e = pv.get("elbow_%s" % side)
        return (a, list(np.asarray(a, float) + (np.asarray(a, float) - np.asarray(e, float)) * 0.45)) if e else None
    b = pv.get("%s_%s" % (t, side))
    return (a, b) if b else None


def mirrored(part, st, pv, size):
    """the other side's piece flipped and laid on this side's bone (turned and scaled so its bone lands on this
    one): the base for a side the plate hides or botched (22b: a missing side is drawn from the other)"""
    other = part[:-1] + ("l" if part[-1] == "r" else "r")
    src = Image.open(os.path.join(st, "part_%s.png" % other)).convert("RGBA")
    b_src, b_dst = bone(other, pv), bone(part, pv)
    if not (b_src and b_dst):
        raise SystemExit("no bone for %s / %s in parts.json pivots" % (part, other))
    W = src.width
    src = src.transpose(Image.FLIP_LEFT_RIGHT)
    p0, p1 = (np.array([W - 1 - q[0], q[1]], float) for q in b_src)   # the flipped bone
    q0, q1 = (np.array(q, float) for q in b_dst)
    ds, dd = p1 - p0, q1 - q0
    along = np.linalg.norm(dd) / max(1e-6, np.linalg.norm(ds))   # stretched along the bone only: the width stays
    u = ds / max(1e-6, np.linalg.norm(ds))
    v = np.array([-u[1], u[0]])
    turn = np.arctan2(dd[1], dd[0]) - np.arctan2(ds[1], ds[0])
    R = np.array([[np.cos(turn), -np.sin(turn)], [np.sin(turn), np.cos(turn)]])
    M = R @ (along * np.outer(u, u) + np.outer(v, v))   # dst = M (src - p0) + q0
    Mi = np.linalg.inv(M)                               # src = Mi (dst - q0) + p0
    c = p0 - Mi @ q0
    out = src.transform(size, Image.AFFINE, (Mi[0, 0], Mi[0, 1], c[0], Mi[1, 0], Mi[1, 1], c[1]), Image.BICUBIC)
    print("mirrored %s onto %s (stretched %.2f along the bone, turn %.0f deg)" % (other, part, along, np.degrees(turn)), flush=True)
    return np.asarray(out).copy()


def hull(on):
    """the convex hull of a mask's pieces (specks under 60 px left out)"""
    lab, n = ndimage.label(on)
    sizes = ndimage.sum(on, lab, range(1, n + 1)) if n else []
    big = np.isin(lab, [i + 1 for i, v in enumerate(sizes) if v >= 60])
    from scipy.spatial import Delaunay
    pts = np.argwhere(big)
    tri = Delaunay(pts[::3])
    ys, xs = np.mgrid[0:on.shape[0], 0:on.shape[1]]
    y0, x0 = pts.min(0)
    y1, x1 = pts.max(0) + 1
    out = np.zeros(on.shape, bool)
    sub = np.stack([ys[y0:y1, x0:x1].ravel(), xs[y0:y1, x0:x1].ravel()], -1)
    out[y0:y1, x0:x1] = (tri.find_simplex(sub) >= 0).reshape(y1 - y0, x1 - x0)
    return out


def _new_layer(st, meta, src_name, name, img, front):
    """write part_<name>.png and list it right behind (or in front of) src_name in parts.json"""
    Image.fromarray(img).save(os.path.join(st, "part_%s.png" % name))
    order = meta["order_back_to_front"]
    names = [q["name"] for q in order]
    if name not in names:
        i = names.index(src_name) if src_name in names else len(order)
        order.insert(i + 1 if front else i, {"name": name, "file": "part_%s.png" % name,
                                             "depth": order[i].get("depth", 0.0) if i < len(order) else 0.0,
                                             "from": "carved out of %s" % src_name})


def carve_ops(a, ld, st, meta):
    """--carve: a piece of a part into a layer of its own (by colour, box or polygon); --split-hair: the hair in
    pieces that swing on their own (bangs, side locks, the ends of the back hair)"""
    orig = os.path.join(st, "_orig")
    os.makedirs(orig, exist_ok=True)
    pjp = os.path.join(st, "parts.json")
    if not os.path.exists(os.path.join(orig, "parts.json")):
        shutil.copy(pjp, os.path.join(orig, "parts.json"))

    def load_keep(n):
        p_ = os.path.join(st, "part_%s.png" % n)
        if not os.path.exists(os.path.join(orig, "part_%s.png" % n)):
            shutil.copy(p_, os.path.join(orig, "part_%s.png" % n))
        return np.asarray(Image.open(p_).convert("RGBA")).copy()

    if a.carve:
        img = load_keep(a.part)
        on = img[..., 3] > 0
        sel = np.zeros(on.shape, bool)
        any_rule = False
        if a.carve_rgb:
            col, _, tol = a.carve_rgb.partition(":")
            c = np.array([float(v) for v in col.split(",")])
            sel |= np.abs(img[..., :3].astype(float) - c).max(-1) <= float(tol or 60)
            any_rule = True
        area = np.ones(on.shape, bool)
        if a.carve_box:
            x0, y0, x1, y1 = (int(v) for v in a.carve_box.split(","))
            area = np.zeros(on.shape, bool)
            area[y0:y1, x0:x1] = True
        if a.carve_poly:
            from outline import poly_mask
            pts = [tuple(float(v) for v in xy.split(",")) for xy in a.carve_poly.split()]
            area = poly_mask([(y, x) for x, y in pts], on.shape) & area
        sel = (sel if any_rule else np.ones(on.shape, bool)) & area & on
        if any_rule:   # a colour pick: its own line art and specks around it come along
            sel = ndimage.binary_closing(sel, iterations=2) & on & area
        piece = np.zeros_like(img)
        piece[sel] = img[sel]
        if not a.carve_copy:
            img[sel, 3] = 0
        Image.fromarray(img).save(os.path.join(st, "part_%s.png" % a.part))
        _new_layer(st, meta, a.part, a.carve, piece, a.carve_front)
        json.dump(meta, open(pjp, "w"))
        print("%s: %d px -> %s (%s %s)" % (a.part, int(sel.sum()), a.carve, "in front of" if a.carve_front else "behind", a.part), flush=True)
        return 0

    # --split-hair
    joints = load_joints(os.path.join(ld, "fig_joints.json"))
    cx, cy, fh = joints["face"]
    neck = joints.get("neck") or [cx, cy + 0.6 * fh]
    names = [q["name"] for q in meta["order_back_to_front"]]
    if "front_hair" in names:
        img = load_keep("front_hair")
        on = img[..., 3] > 0
        yy, xx = np.mgrid[0:on.shape[0], 0:on.shape[1]]
        # a lock beside the face: below the eyes and out past the face's sides
        side = on & (yy > cy) & (np.abs(xx - cx) > 0.3 * fh)
        side = ndimage.binary_opening(side, iterations=2) & on
        for sd, m in (("r", side & (xx < cx)), ("l", side & (xx >= cx))):   # the character's right is the picture's left
            if m.sum() < 150:
                continue
            piece = np.zeros_like(img)
            piece[m] = img[m]
            img[m, 3] = 0
            _new_layer(st, meta, "front_hair", "side_lock-%s" % sd, piece, False)
            print("front_hair: %d px -> side_lock-%s" % (int(m.sum()), sd), flush=True)
        Image.fromarray(img).save(os.path.join(st, "part_front_hair.png"))
    if "back_hair" in names:
        img = load_keep("back_hair")
        on = img[..., 3] > 0
        line = int(neck[1] + 0.35 * fh)   # below the shoulders the long hair swings on its own
        m = on.copy()
        m[:line] = False
        if m.sum() > 300:
            piece = np.zeros_like(img)
            piece[m] = img[m]
            img[m, 3] = 0
            _new_layer(st, meta, "back_hair", "hair_ends", piece, True)
            Image.fromarray(img).save(os.path.join(st, "part_back_hair.png"))
            print("back_hair: %d px below row %d -> hair_ends" % (int(m.sum()), line), flush=True)
    json.dump(meta, open(pjp, "w"))
    return 0


def face_ops(a, ld, st, meta):
    """--make-face / --split-lr / --drop-part: repairs for a split that left the face out, gave both eye whites one
    layer, or invented a part the plate doesn't have"""
    order = meta["order_back_to_front"]
    names = [q["name"] for q in order]
    pjp = os.path.join(st, "parts.json")
    orig = os.path.join(st, "_orig")
    os.makedirs(orig, exist_ok=True)
    if not os.path.exists(os.path.join(orig, "parts.json")):
        shutil.copy(pjp, os.path.join(orig, "parts.json"))
    joints = load_joints(os.path.join(ld, "fig_joints.json"))
    cx, cy, fh = joints["face"]
    if a.drop_part:
        path = os.path.join(st, "part_%s.png" % a.part)
        if os.path.exists(path):
            shutil.copy(path, os.path.join(orig, "part_%s.png" % a.part))
            os.remove(path)
        meta["order_back_to_front"] = [q for q in order if q["name"] != a.part]
        json.dump(meta, open(pjp, "w"))
        print("%s dropped (kept in st/_orig/)" % a.part, flush=True)
        return 0
    if a.split_lr:
        path = os.path.join(st, "part_%s.png" % a.part)
        img = np.asarray(Image.open(path).convert("RGBA"))
        shutil.copy(path, os.path.join(orig, "part_%s.png" % a.part))
        xs = np.arange(img.shape[1])[None, :]
        i = names.index(a.part)
        new = []
        for side, keep in (("r", xs < cx), ("l", xs >= cx)):   # the character's right is the picture's left
            half = img.copy()
            half[~np.broadcast_to(keep, half.shape[:2]), 3] = 0
            if (half[..., 3] > 128).sum() < 10:
                continue
            Image.fromarray(half).save(os.path.join(st, "part_%s-%s.png" % (a.part, side)))
            new.append({"name": "%s-%s" % (a.part, side), "file": "part_%s-%s.png" % (a.part, side), "depth": order[i].get("depth", 0.0)})
        if len(new) == 1:   # one eye only: the other is the same flipped across the middle between the irises
            have = new[0]["name"][-1]
            miss = "l" if have == "r" else "r"
            mid = cx
            ir = [np.nonzero(np.asarray(Image.open(os.path.join(st, "part_irides-%s.png" % s_)).convert("RGBA"))[..., 3] > 128)[1].mean()
                  for s_ in ("l", "r") if os.path.exists(os.path.join(st, "part_irides-%s.png" % s_))]
            if len(ir) == 2:
                mid = (ir[0] + ir[1]) / 2.0
            one = np.asarray(Image.open(os.path.join(st, "part_%s-%s.png" % (a.part, have))).convert("RGBA"))
            w = one.shape[1]
            flip = np.zeros_like(one)
            src_x = np.round(2 * mid - np.arange(w)).astype(int)   # x' = 2 mid - x
            okx = (src_x >= 0) & (src_x < w)
            flip[:, okx] = one[:, src_x[okx]]
            Image.fromarray(flip).save(os.path.join(st, "part_%s-%s.png" % (a.part, miss)))
            new.append({"name": "%s-%s" % (a.part, miss), "file": "part_%s-%s.png" % (a.part, miss), "depth": new[0]["depth"]})
            print("  %s-%s: flipped from the %s side across x=%.0f" % (a.part, miss, have, mid), flush=True)
        order[i:i + 1] = new
        os.remove(path)
        json.dump(meta, open(pjp, "w"))
        print("%s -> %s" % (a.part, ", ".join(q["name"] for q in new)), flush=True)
        return 0
    # --make-face: the plate's skin inside the face oval, the eyes and mouth closed over
    full = np.asarray(Image.open(os.path.join(ld, "full.png")).convert("RGBA")).astype(int)
    yy, xx = np.mgrid[0:full.shape[0], 0:full.shape[1]]
    oval = ((xx - cx) / (0.42 * fh)) ** 2 + ((yy - (cy + 0.05 * fh)) / (0.58 * fh)) ** 2 <= 1.0
    r, g, b = full[..., 0], full[..., 1], full[..., 2]
    skin = oval & (full[..., 3] > 128) & (r > 190) & (g > 140) & (b > 120) & (r >= g) & (r - b < 90)
    lab, n = ndimage.label(skin)
    if not n:
        raise SystemExit("no skin found in the face oval")
    main_ = lab == 1 + int(np.argmax(ndimage.sum(skin, lab, range(1, n + 1))))
    jaw = np.nonzero(main_)[0].max()   # the chin: the lowest skin seen
    face = (ndimage.binary_fill_holes(ndimage.binary_closing(main_, iterations=6)) | (oval & (full[..., 3] > 128))) & oval
    face[jaw + 1:] = False   # the whole face, hair or not over it, down to the chin
    top = np.nonzero(main_)[0].min()
    for y in range(int(jaw - 0.3 * (jaw - top)), jaw + 1):   # toward the chin, no wider than the skin seen there
        row = np.nonzero(main_[y])[0]
        if len(row):
            face[y, :max(0, row.min() - 2)] = False
            face[y, row.max() + 3:] = False
    out = np.zeros_like(full, dtype=np.uint8)
    out[face] = full[face].astype(np.uint8)
    col = np.median(full[main_][:, :3], 0).astype(np.uint8)
    out[face & ~main_, :3] = col   # under the eyes and mouth: the face's own skin
    out[face, 3] = 255
    Image.fromarray(out).save(os.path.join(st, "part_face.png"))
    if "face" not in names:
        at = min([names.index(q) for q in names if q.startswith(("eyewhite", "irides", "eyelash", "eyebrow", "mouth", "nose"))] or [len(names)])
        order.insert(at, {"name": "face", "file": "part_face.png", "depth": 0.0, "from": "made from the plate's skin (the split left it out)"})
        json.dump(meta, open(pjp, "w"))
    print("face: %d px from the plate's skin (colour %s), listed before the eyes" % (int(face.sum()), tuple(int(v) for v in col)), flush=True)
    return 0


def move_hair(a, ld, st, meta):
    """--move-hair: in a layer that took over hair lying on something of the same colour, the blocks between the
    plate's lines (st/lineart.png) that have the hair's grey shading within 15 px and sit above --ycut are hair: they
    go onto part_side_hair.png (with their own lines and shading); the holes take the nearest colour (only from
    --palette when given) or stay empty with --keep-holes"""
    path = os.path.join(st, "part_%s.png" % a.part)
    part = np.asarray(Image.open(path).convert("RGBA")).copy()
    on = part[..., 3] > 128
    rgb = part[..., :3].astype(int)
    sat, v = rgb.max(-1) - rgb.min(-1), rgb.max(-1)
    accent = on & (sat < 45) & (v > 45) & (v < 150)
    red = on & (rgb[..., 0] > 150) & (rgb[..., 1] < 90)
    la = np.asarray(Image.open(os.path.join(st, "lineart.png")).convert("L")) > 70
    reg = red & ~la
    lab, n = ndimage.label(reg)
    sz = ndimage.sum(reg, lab, range(1, n + 1)) if n else []
    near_acc = ndimage.binary_dilation(accent, iterations=15)
    hair = np.zeros_like(on)
    for i in range(1, n + 1):
        if sz[i - 1] < 15 or sz[i - 1] > 20000:   # the cape itself is one big block
            continue
        m = lab == i
        if np.nonzero(m)[0].mean() < a.ycut and (m & near_acc).any():
            hair |= m
    hair |= ndimage.binary_dilation(hair, iterations=2) & on & (la | accent)
    orig = os.path.join(st, "_orig")
    os.makedirs(orig, exist_ok=True)
    if not os.path.exists(os.path.join(orig, "part_%s.png" % a.part)):
        shutil.copy(path, os.path.join(orig, "part_%s.png" % a.part))
    sp = os.path.join(st, "part_side_hair.png")
    side = np.asarray(Image.open(sp).convert("RGBA")).copy() if os.path.exists(sp) else np.zeros_like(part)
    side[hair & (side[..., 3] < 128)] = part[hair & (side[..., 3] < 128)]
    Image.fromarray(side).save(sp)
    rest = part.copy()
    if a.keep_holes:
        rest[hair, 3] = 0
        left = rest[..., 3] > 128   # the bits of the hair's lines and shading left beside the holes
        lab2, n2 = ndimage.label(left)
        if n2:
            sz2 = ndimage.sum(left, lab2, range(1, n2 + 1))
            rest[np.isin(lab2, [i + 1 for i, v in enumerate(sz2) if v < 80]), 3] = 0
    else:
        src = on & ~hair
        _, (iy, ix) = ndimage.distance_transform_edt(~src, return_indices=True)
        rest[hair, :3] = part[iy[hair], ix[hair], :3]
        if a.palette:
            pal = np.array([[float(c) for c in q.split(",")] for q in a.palette.split(";")])
            got = rest[hair, :3].astype(float)
            rest[hair, :3] = pal[np.argmin(((got[:, None, :] - pal[None, :, :]) ** 2).sum(-1), 1)].astype(np.uint8)
    Image.fromarray(rest).save(path)
    print("%s: %d px of hair -> part_side_hair.png; holes %s" % (a.part, int(hair.sum()),
          "left empty" if a.keep_holes else "filled from the nearest colour"), flush=True)
    return 0


def sort_hair(a, ld, st, meta):
    """--sort-hair: each separate piece of the grab-bag layer is hair when most of it is near the hair's own colour
    (the front hair's median), or a good part of it is and it touches a hair layer; those go to part_side_hair.png"""
    path = os.path.join(st, "part_%s.png" % a.part)
    part = np.asarray(Image.open(path).convert("RGBA")).copy()
    fh = np.asarray(Image.open(os.path.join(st, "part_front_hair.png")).convert("RGBA")).astype(int)
    hair_col = np.median(fh[fh[..., 3] > 128][:, :3], 0)
    hairs = np.zeros(part.shape[:2], bool)
    for n in ("front_hair", "back_hair"):
        f = os.path.join(st, "part_%s.png" % n)
        if os.path.exists(f):
            hairs |= np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 128
    near_hairs = ndimage.binary_dilation(hairs, iterations=3)
    on = part[..., 3] > 128
    like = np.abs(part[..., :3].astype(int) - hair_col).max(-1) < 80
    lab, n = ndimage.label(ndimage.binary_dilation(on, iterations=1) & on)
    hair = np.zeros_like(on)
    kept = 0
    for i in range(1, n + 1):
        m = lab == i
        sz = int(m.sum())
        if sz < 20:
            continue
        share = float((m & like).sum()) / sz
        if share > 0.5 or (share > 0.3 and (m & near_hairs).any()):
            hair |= m
        else:
            kept += 1
    hair = ndimage.binary_dilation(hair, iterations=1) & (part[..., 3] > 0)
    orig = os.path.join(st, "_orig")
    os.makedirs(orig, exist_ok=True)
    if not os.path.exists(os.path.join(orig, "part_%s.png" % a.part)):
        shutil.copy(path, os.path.join(orig, "part_%s.png" % a.part))
    sp = os.path.join(st, "part_side_hair.png")   # added to the hair sorted out before (another layer's), not over it
    out = np.asarray(Image.open(sp).convert("RGBA")).copy() if os.path.exists(sp) else np.zeros_like(part)
    out[hair & (out[..., 3] < 128)] = part[hair & (out[..., 3] < 128)]
    rest = part.copy()
    rest[hair, 3] = 0
    Image.fromarray(out).save(sp)
    Image.fromarray(rest).save(path)
    order = meta["order_back_to_front"]
    names = [q["name"] for q in order]
    if "side_hair" not in names:
        order.insert(names.index(a.part) if a.part in names else len(order),
                     {"name": "side_hair", "file": "part_side_hair.png", "depth": 0.0, "from": "hair sorted out of %s" % a.part})
        json.dump(meta, open(os.path.join(st, "parts.json"), "w"))
    print("%s: %d px of hair -> part_side_hair.png; %d piece(s), %d px stay" % (
        a.part, int(hair.sum()), kept, int((rest[..., 3] > 128).sum())), flush=True)
    return 0


def split_front(a, ld, st, meta):
    """--split-front: the part's pixels that show the plate where the face or the front hair is (plus what --flat took
    out of the face for it, fix/face_moved.png) become st/part_<part>-front.png, listed right after the front hair;
    the rest stays where it was in the order (a brim behind the head)"""
    path = os.path.join(st, "part_%s.png" % a.part)
    part = np.asarray(Image.open(path).convert("RGBA")).copy()
    full = np.asarray(Image.open(os.path.join(ld, "full.png")).convert("RGBA")).astype(int)
    over = np.zeros(part.shape[:2], bool)
    for n in ("face", "front_hair"):
        f = os.path.join(st, "part_%s.png" % n)
        if os.path.exists(f):
            over |= np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 128
    on = part[..., 3] > 128
    shows = np.abs(part[..., :3].astype(int) - full[..., :3]).max(-1) < 30
    front = on & shows & ndimage.binary_dilation(over, iterations=2)
    mv = os.path.join(st, "fix", "face_moved.png")
    moved = np.asarray(Image.open(mv).convert("RGBA")) if os.path.exists(mv) else None
    front = ndimage.binary_closing(front, iterations=1) & on
    if moved is not None:   # what --flat took out of the face (the band on the forehead), even where this layer is
        took = moved[..., 3] > 128   # empty: the split painted it into the face only (2026-10-02)
        part = part.copy()
        part[took] = moved[took]
        on = on | took
        front |= took
    orig = os.path.join(st, "_orig")
    os.makedirs(orig, exist_ok=True)
    if not os.path.exists(os.path.join(orig, "part_%s.png" % a.part)):
        shutil.copy(path, os.path.join(orig, "part_%s.png" % a.part))
    fr = np.zeros_like(part)
    fr[front] = part[front]
    back = part.copy()
    back[front, 3] = 0
    Image.fromarray(fr).save(os.path.join(st, "part_%s-front.png" % a.part))
    Image.fromarray(back).save(path)
    order = meta["order_back_to_front"]
    names = [q["name"] for q in order]
    name = "%s-front" % a.part
    if name not in names:
        at = names.index("front_hair") + 1 if "front_hair" in names else len(order)
        order.insert(at, {"name": name, "file": "part_%s.png" % name, "depth": 0.0, "from": "split off %s: over the face and the bangs" % a.part})
        pjp = os.path.join(st, "parts.json")
        if not os.path.exists(os.path.join(orig, "parts.json")):
            shutil.copy(pjp, os.path.join(orig, "parts.json"))
        json.dump(meta, open(pjp, "w"))
    print("%s: %d px over the face and the bangs -> part_%s.png (after the front hair); %d px stay" % (
        a.part, int(front.sum()), name, int((on & ~front).sum())), flush=True)
    return 0


def flat_fill(a, ld, st, meta):
    """--flat: inside outline.py's shape, the pixels a layer in front covers, the ones that don't match the plate and
    the empty ones take the median colour of what shows (dark line pixels left out); saved as candidate 8"""
    od = os.path.join(st, "outline")
    part = np.asarray(Image.open(os.path.join(od, "%s_cut.png" % a.part)).convert("RGBA")).copy()
    shape = np.asarray(Image.open(os.path.join(od, "%s_shape.png" % a.part)))[..., 3] > 128
    full = np.asarray(Image.open(os.path.join(ld, "full.png")).convert("RGBA")).astype(int)
    order = [q["name"] for q in meta["order_back_to_front"]]
    front = np.zeros(shape.shape, bool)
    for n in order[order.index(a.part) + 1:] if a.part in order else []:
        f = os.path.join(st, "part_%s.png" % n)
        if os.path.exists(f):
            front |= np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 128
    on = part[..., 3] > 128
    rgb = part[..., :3].astype(int)
    plate_ok = np.abs(rgb - full[..., :3]).max(-1) < 30
    claimed = np.zeros(shape.shape, bool)   # another layer shows the plate here too: the pixel is that one's (a hat
    for n in order:                         # listed behind the face whose colours the face layer copied)
        f = os.path.join(st, "part_%s.png" % n)
        if n == a.part or not os.path.exists(f):
            continue
        o = np.asarray(Image.open(f).convert("RGBA")).astype(int)
        claimed |= (o[..., 3] > 128) & (np.abs(o[..., :3] - full[..., :3]).max(-1) < 30)
    fill = shape & (front | ~plate_ok | ~on | claimed)
    if a.nearest:   # the outline already cleaned what shows: only the empty inside is filled, from its nearest colour
        fill = shape & ~on
    shows = shape & ~fill & (rgb.max(-1) > 60)   # not the near-black lines (bright red hair is dark by luma)
    if shows.sum() < 20:
        raise SystemExit("too little of %s shows to take its colour from" % a.part)
    col = np.median(rgb[shows], 0).astype(np.uint8)
    # thick blocks far from the part's own colour are another thing the split gave it (the hat's band on Freya's
    # forehead): taken out, and kept in st/fix/<part>_moved.png for the layer they belong to
    far = shape & on & (np.abs(rgb - col.astype(int)).max(-1) > 90)
    thick = ndimage.binary_dilation(ndimage.binary_opening(far, iterations=2), iterations=2) & far
    lab, n = ndimage.label(thick)
    if n:
        sz = ndimage.sum(thick, lab, range(1, n + 1))
        thick = np.isin(lab, [i + 1 for i, v in enumerate(sz) if v >= 150])
    rim = shape & ~ndimage.binary_erosion(shape, iterations=3)   # its own outline (dark red-brown) stays
    thick |= far & (rgb.max(-1) > 120) & ~rim
    if a.nearest:
        thick[:] = False   # coloured specks (hair) too; near-black thin bits are its own lines
    moved = np.zeros_like(part)
    moved[thick] = part[thick]
    fill |= thick
    res = part.copy()
    if a.from_view:
        vpath, how = (a.from_view[:-5], "flip") if a.from_view.endswith(":flip") else (a.from_view, "")
        fig = Image.open(a.figure or os.path.join(os.path.dirname(vpath), "figure.png")).convert("RGBA")
        view = np.asarray(Image.open(vpath).convert("RGB")).astype(int)
        size = view.shape[0]
        bx0, by0, bx1, by1 = fig.split()[3].getbbox()   # multiview.square(): the figure's box, 90% of the square
        k = size * 0.9 / max(bx1 - bx0, by1 - by0)
        ox = (size - round((bx1 - bx0) * k)) // 2
        oy = (size - round((by1 - by0) * k)) // 2
        ys, xs = np.nonzero(fill)
        sx = np.clip(((xs - bx0) * k + ox).astype(int), 0, size - 1)
        sy = np.clip(((ys - by0) * k + oy).astype(int), 0, size - 1)
        if how == "flip":
            sx = size - 1 - sx
        got = view[sy, sx]
        own = np.median(rgb[shows], 0)
        like = np.abs(view - own).max(-1) < 90   # the view shows this part here (not the dress behind, not backdrop)
        dark = view.max(-1) < 90
        dark &= ~ndimage.binary_dilation(ndimage.binary_opening(dark, iterations=2), iterations=2)   # thin only: a
        lines = dark & ndimage.binary_dilation(like, iterations=3)   # strand line, not a hat's underside or a dress
        ok = (like | lines)[sy, sx]
        src = shape & ~fill & on & (rgb.max(-1) > 60)   # not its dark outline: that would smear black inwards
        _, (iy, ix) = ndimage.distance_transform_edt(~src, return_indices=True)
        near = part[iy[ys, xs], ix[ys, xs], :3].astype(int)
        res[ys, xs, :3] = np.where(ok[:, None], got, near).astype(np.uint8)
        print("  from the view: %d of %d px (the rest from the nearest colour that shows)" % (int(ok.sum()), len(ok)), flush=True)
    elif a.nearest:
        pale = (rgb.min(-1) > 110) & (rgb.max(-1) - rgb.min(-1) < 60)   # ghost grey / white: not a source
        src = shape & ~fill & on & ~pale
        fill |= shape & on & pale
        _, (iy, ix) = ndimage.distance_transform_edt(~src, return_indices=True)
        res[fill, :3] = part[iy[fill], ix[fill], :3]
        if a.palette:
            pal = np.array([[float(v) for v in c.split(",")] for c in a.palette.split(";")])
            got = res[fill, :3].astype(float)
            pick = np.argmin(((got[:, None, :] - pal[None, :, :]) ** 2).sum(-1), 1)
            res[fill, :3] = pal[pick].astype(np.uint8)
    else:
        res[fill, :3] = col
    res[fill, 3] = 255
    res[~shape, 3] = 0
    fixd = os.path.join(st, "fix")
    os.makedirs(fixd, exist_ok=True)
    Image.fromarray(res).save(os.path.join(fixd, "%s_8.png" % a.part))
    if thick.any():
        Image.fromarray(moved).save(os.path.join(fixd, "%s_moved.png" % a.part))
        print("  %d px of another thing taken out -> fix/%s_moved.png" % (int(thick.sum()), a.part), flush=True)
    print("%s: %d px of %d inside the outline flattened to %s (from %d px that show) -> candidate 8" % (
        a.part, int(fill.sum()), int(shape.sum()), tuple(int(v) for v in col), int(shows.sum())), flush=True)
    return 0


def recolor_grey(a, ld, st, meta):
    """--recolor-grey <layer>: the grey or washed-out pixels of the part (what the split painted in where the part is
    hidden: back hair behind the body came out pale grey) take the colours another layer shows (front hair), matched
    by brightness rank, so the part keeps its own shading and strands and only its colour changes. No AI (an AI
    repaint of a large grey area drew eyes and faces, 2026-10-02); the shape stays as it is. Candidate 9"""
    part = np.asarray(Image.open(os.path.join(st, "part_%s.png" % a.part)).convert("RGBA")).copy()
    ref = np.asarray(Image.open(os.path.join(st, "part_%s.png" % a.recolor_grey)).convert("RGBA")).astype(int)
    full = np.asarray(Image.open(os.path.join(ld, "full.png")).convert("RGBA")).astype(int)
    rgb = part[..., :3].astype(int)
    on = part[..., 3] > 128
    sat = rgb.max(-1) - rgb.min(-1)
    grey = on & (sat < a.grey_sat) & (rgb.max(-1) > 55)
    # the reference's own colours: where it shows the plate (not what the split guessed), lines left out
    rs = (ref[..., 3] > 128) & (np.abs(ref[..., :3] - full[..., :3]).max(-1) < 30)
    cols = ref[rs][:, :3]
    cols = cols[cols.max(-1) > 40]
    if len(grey) == 0 or len(cols) < 50:
        raise SystemExit("nothing grey in %s, or too little of %s shows" % (a.part, a.recolor_grey))
    luma = lambda c: c[..., 0] * 0.299 + c[..., 1] * 0.587 + c[..., 2] * 0.114
    cols = cols[np.argsort(luma(cols))]
    g = luma(rgb[grey].astype(float))
    rank = np.argsort(np.argsort(g)) / max(1, len(g) - 1)   # 0 darkest .. 1 brightest of the grey pixels
    res = part.copy()
    res[grey, :3] = cols[(rank * (len(cols) - 1)).astype(int)].astype(np.uint8)
    fixd = os.path.join(st, "fix")
    os.makedirs(fixd, exist_ok=True)
    Image.fromarray(res).save(os.path.join(fixd, "%s_9.png" % a.part))
    tiles = []
    for im in (part, res):
        bg = Image.new("RGBA", (im.shape[1], im.shape[0]), GREY + (255,))
        bg.alpha_composite(Image.fromarray(im))
        ys, xs = np.nonzero(on)
        tiles.append(bg.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)))
    sheet = Image.new("RGB", (tiles[0].width * 2 + 8, tiles[0].height), (40, 40, 48))
    sheet.paste(tiles[0].convert("RGB"), (0, 0))
    sheet.paste(tiles[1].convert("RGB"), (tiles[0].width + 8, 0))
    sheet.save(os.path.join(fixd, "%s.jpg" % a.part), quality=88)
    print("%s: %d grey px recoloured from %s's %d showing colours -> candidate 9" % (a.part, int(grey.sum()), a.recolor_grey, len(cols)), flush=True)
    return 0


def inpaint_lines(j3, canvas, mask, line_img, pos, neg, seed, denoise):
    """heroine_j3.img2img's inpaint, held to line art (workflow inpaint_lines: the union ControlNet)"""
    import uuid
    import comfy_gen as cg
    import workflows as W
    tmp = os.path.join(os.environ.get("TEMP", "."), "of_%s" % uuid.uuid4().hex)
    canvas.save(tmp + ".png")
    Image.merge("RGB", (mask, mask, mask)).save(tmp + "_m.png")
    line_img.save(tmp + "_l.png")
    wf = j3._wf_common(pos, neg + j3.hero_neg(pos), None, seed, 30, 6.0, denoise, "ofl", "inpaint_lines")
    W.fill(wf, {"輸入圖": {"image": cg.upload(tmp + ".png")}, "遮罩": {"image": cg.upload(tmp + "_m.png")},
                "線稿圖": {"image": cg.upload(tmp + "_l.png")}})
    try:
        return j3.run_wf(wf)
    finally:
        for f in (".png", "_m.png", "_l.png"):
            os.remove(tmp + f)


def clean(a, erase):
    """the main piece and pieces close to it; far specks and erase boxes go"""
    out = a.copy()
    for x0, y0, x1, y1 in erase:
        out[y0:y1, x0:x1, 3] = 0
    on = out[..., 3] > 128
    lab, n = ndimage.label(on)
    if n > 1:
        sizes = ndimage.sum(on, lab, range(1, n + 1))
        main = lab == (1 + int(np.argmax(sizes)))
        near = ndimage.binary_dilation(main, iterations=12)
        keep = np.zeros_like(on)
        for i in range(1, n + 1):
            piece = lab == i
            if (piece & near).any() or sizes[i - 1] > 0.05 * sizes.max():
                keep |= piece
        out[~ndimage.binary_dilation(keep, iterations=2), 3] = 0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("series")
    ap.add_argument("part")
    ap.add_argument("--erase", default="")
    ap.add_argument("--grow", default="auto", choices=["auto", "none", "hull", "grey"])
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--denoise", type=float, default=None, help="default 0.8 (the gap is first filled with the nearest colour); 0.4 with --mirror; 1.0 paints from nothing")
    ap.add_argument("--apply", type=int, default=None)
    ap.add_argument("--grey-sat", type=int, default=60, help="--grow grey: colours less saturated than this count as smudge")
    ap.add_argument("--only", default="", help="x0,y0,x1,y1: fill only inside this box")
    ap.add_argument("--desc", default="", help="what the part is, for the prompt, when the default doesn't fit")
    ap.add_argument("--outline", action="store_true",
                    help="colour inside the outline outline.py completed, held to it as line art (22b step 4)")
    ap.add_argument("--flat", action="store_true",
                    help="inside the outline, what a layer in front hides or the plate doesn't show becomes the part's "
                         "own visible colour (a forehead under bangs is flat skin); no ComfyUI; candidate 8")
    ap.add_argument("--nearest", action="store_true",
                    help="with --flat: each pixel takes the nearest colour that shows instead of one median colour "
                         "(a hat brim: red from the brim beside it, black from the crown above)")
    ap.add_argument("--palette", default="",
                    help="with --flat --nearest: 'r,g,b;r,g,b' the only colours to fill with (each pixel takes the one "
                         "nearest to its nearest showing colour: two clean areas, no streaks)")
    ap.add_argument("--split-front", action="store_true",
                    help="split off <part>-front: what of it the plate shows over the face and the bangs (a hat's crown "
                         "and band, when its brim goes behind the head), listed after the front hair")
    ap.add_argument("--sort-hair", action="store_true",
                    help="split the hair out of a grab-bag layer (See-through's leftover: long locks it couldn't call front "
                         "or back hair) into part_side_hair.png, listed where the grab-bag is")
    ap.add_argument("--from-view", default="",
                    help="'<view.png>[:flip]' with --flat: the colours come from another view angle (multiview.py, made "
                         "from <figure>, default views folder's figure.png) laid back on the plate; a back view is "
                         "flipped (hair behind the body seen from the front is the back view mirrored)")
    ap.add_argument("--figure", default="", help="the picture multiview.py was given (to lay its views back on the plate)")
    ap.add_argument("--recolor-grey", default="",
                    help="<layer>: the part's grey / washed-out pixels take that layer's showing colours by brightness "
                         "(hidden back hair painted grey, recoloured like the front hair); no AI; candidate 9")
    ap.add_argument("--move-hair", action="store_true",
                    help="hair a clothes layer took over (locks lying on a cape of the same red): blocks between the "
                         "plate's lines that hold the hair's grey shading, above --ycut, move to part_side_hair.png; "
                         "the holes take the nearest colour from --palette (what the hair lay on)")
    ap.add_argument("--ycut", type=int, default=100000, help="--move-hair: only blocks whose middle is above this row")
    ap.add_argument("--keep-holes", action="store_true", help="--move-hair: leave the holes empty (a layer painted in under the arms)")
    ap.add_argument("--drop-specks", type=int, default=0, help="remove separate specks smaller than this (px), in place")
    ap.add_argument("--carve", default="",
                    help="cut a piece out of the part into a new layer of this name (cape, chest, ponytail, ahoge, "
                         "ribbon, earring, sleeve-l/-r, tassel...: the rig swings each by its name); what is cut: "
                         "--carve-rgb 'r,g,b:tol' and/or --carve-box x0,y0,x1,y1 / --carve-poly 'x,y x,y ...'")
    ap.add_argument("--carve-rgb", default="")
    ap.add_argument("--carve-box", default="")
    ap.add_argument("--carve-poly", default="")
    ap.add_argument("--carve-front", action="store_true", help="list the new layer in front of the part (default behind)")
    ap.add_argument("--carve-copy", action="store_true",
                    help="copy, don't cut: the part keeps its pixels under the new layer (a chest bounces on a top "
                         "that stays whole, so no seam opens at the cut's edge)")
    ap.add_argument("--split-hair", action="store_true",
                    help="front_hair -> bangs + side_lock-l/-r (locks hanging beside the face); back_hair -> back_hair "
                         "+ hair_ends (below the shoulders): each piece swings on its own")
    ap.add_argument("--make-face", action="store_true",
                    help="the split left the face out: part_face.png from the plate's skin inside the face oval "
                         "(fig_joints.json face), holes for the eyes and mouth closed; listed before the eyes")
    ap.add_argument("--split-lr", action="store_true",
                    help="one layer for both sides (eyewhite): <part>-l / <part>-r, cut at the face's middle")
    ap.add_argument("--drop-part", action="store_true", help="take an invented layer out of parts.json (kept in st/_orig/)")
    ap.add_argument("--mirror", action="store_true", help="start from the other side's piece, flipped onto this bone")
    ap.add_argument("--dry", action="store_true", help="only the sheet of what would be filled, no ComfyUI")
    a = ap.parse_args()
    if a.denoise is None:
        a.denoise = 0.4 if a.mirror else 0.8
    ld = os.path.join(WORK, "live", a.hero, a.series)
    st = os.path.join(ld, "st")
    fixd = os.path.join(st, "fix")
    path = os.path.join(st, "part_%s.png" % a.part)
    if a.apply is not None:   # put a candidate in place of the part, keeping the original once
        cand = os.path.join(fixd, "%s_%d.png" % (a.part, a.apply))
        orig = os.path.join(st, "_orig")
        os.makedirs(orig, exist_ok=True)
        if not os.path.exists(os.path.join(orig, "part_%s.png" % a.part)):
            shutil.copy(path, os.path.join(orig, "part_%s.png" % a.part))
        shutil.copy(cand, path)
        print("applied %s -> %s (original in st/_orig/)" % (os.path.basename(cand), path), flush=True)
        return 0

    meta = json.load(open(os.path.join(st, "parts.json")))
    pv = dict(meta.get("pivots") or {})
    if os.path.exists(os.path.join(ld, "fig_joints.json")):
        for k, v in load_joints(os.path.join(ld, "fig_joints.json")).items():
            if isinstance(v, list) and k not in pv:
                pv[k] = v
    if a.make_face or a.split_lr or a.drop_part:   # these work on parts.json, the part may not exist yet
        return face_ops(a, ld, st, meta)
    if a.carve or a.split_hair:
        return carve_ops(a, ld, st, meta)
    part = np.asarray(Image.open(path).convert("RGBA"))
    erase = [tuple(int(v) for v in b.split(",")) for b in a.erase.split(";") if b]
    part = clean(part, erase)
    if a.mirror:
        part = mirrored(a.part, st, pv, (part.shape[1], part.shape[0]))
    shape = lines = None
    if a.recolor_grey:
        return recolor_grey(a, ld, st, meta)
    if a.flat:
        return flat_fill(a, ld, st, meta)
    if a.split_front:
        return split_front(a, ld, st, meta)
    if a.sort_hair:
        return sort_hair(a, ld, st, meta)
    if a.move_hair:
        return move_hair(a, ld, st, meta)
    if a.drop_specks:
        part = np.asarray(Image.open(path).convert("RGBA")).copy()
        on = part[..., 3] > 128
        lab, n = ndimage.label(on)
        sz = ndimage.sum(on, lab, range(1, n + 1)) if n else []
        small = np.isin(lab, [i + 1 for i, v in enumerate(sz) if v < a.drop_specks])
        small = ndimage.binary_dilation(small, iterations=1) & ~np.isin(lab, [i + 1 for i, v in enumerate(sz) if v >= a.drop_specks])
        orig = os.path.join(st, "_orig")
        os.makedirs(orig, exist_ok=True)
        if not os.path.exists(os.path.join(orig, "part_%s.png" % a.part)):
            shutil.copy(path, os.path.join(orig, "part_%s.png" % a.part))
        part[small, 3] = 0
        Image.fromarray(part).save(path)
        print("%s: %d speck(s) under %d px removed (%d px)" % (a.part, int(sum(1 for v in sz if v < a.drop_specks)),
                                                             a.drop_specks, int(small.sum())), flush=True)
        return 0
    if a.outline:   # outline.py's cut-out (noise dropped), its closed shape, what is inside it without colour
        od = os.path.join(st, "outline")
        if not os.path.exists(os.path.join(od, "%s_fill.png" % a.part)):
            raise SystemExit("run outline.py %s %s %s first" % (a.hero, a.series, a.part))
        part = np.asarray(Image.open(os.path.join(od, "%s_cut.png" % a.part)).convert("RGBA")).copy()
        shape = np.asarray(Image.open(os.path.join(od, "%s_shape.png" % a.part)))[..., 3] > 128
        lines = np.asarray(Image.open(os.path.join(od, "%s_lines.png" % a.part)))[..., 3] > 128
    on = part[..., 3] > 128

    # what to fill
    order = [q["name"] for q in meta["order_back_to_front"]]
    if a.outline:
        fill = shape & ~on
    elif a.mirror:   # a light pass over the whole flipped piece and a thin ring around it, to settle it on this side
        fill = ndimage.binary_dilation(on, iterations=6)
    elif a.grow == "grey":   # grey or washed-out smudges inside the part (a fill that kept the backdrop): repainted
        rgb = part[..., :3].astype(int)
        sat = rgb.max(-1) - rgb.min(-1)
        fill = on & (sat < a.grey_sat) & (rgb.mean(-1) > 55)   # not the dark outlines
        fill = ndimage.binary_dilation(ndimage.binary_opening(fill, iterations=1), iterations=3) & on
    elif a.grow == "hull":   # between its own pieces only (a hand split by the staff it grips)
        fill = hull(on) & ~on
    elif a.grow == "none":
        fill = ndimage.binary_fill_holes(ndimage.binary_closing(on, iterations=3)) & ~on
    else:
        reach = reach_mask(a.part, part[..., 3], pv, on.shape)
        if reach is not None:
            fill = reach & ~on
        else:   # where a layer in front hides it, near its own edge
            front = np.zeros(on.shape, bool)
            i = order.index(a.part) if a.part in order else len(order)
            for n in order[i + 1:]:
                f = os.path.join(st, "part_%s.png" % n)
                if os.path.exists(f):
                    front |= np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 128
            fill = ndimage.binary_dilation(on, iterations=25) & front & ~on
        fill |= ndimage.binary_fill_holes(ndimage.binary_closing(on, iterations=3)) & ~on
    if not a.outline:
        fill = ndimage.binary_opening(fill, iterations=1)
    if a.only:
        bx0, by0, bx1, by1 = (int(v) for v in a.only.split(","))
        box = np.zeros_like(fill)
        box[by0:by1, bx0:bx1] = True
        fill &= box
    if a.mirror:
        os.makedirs(fixd, exist_ok=True)
        Image.fromarray(part).save(os.path.join(fixd, "%s_0.png" % a.part))   # candidate 0: the plain flip
    if fill.sum() < 30:
        print("nothing to fill in %s (%d px)" % (a.part, int(fill.sum())), flush=True)
        return 0

    # the object alone on grey, cropped and enlarged for the model
    ys, xs = np.nonzero(on | fill)
    x0, y0 = max(0, xs.min() - MARGIN), max(0, ys.min() - MARGIN)
    x1, y1 = min(on.shape[1], xs.max() + MARGIN), min(on.shape[0], ys.max() + MARGIN)
    crop = Image.fromarray(part[y0:y1, x0:x1])
    w, h = crop.size
    k = MODEL_SIDE / max(w, h)
    W_, H_ = max(64, int(round(w * k / 8)) * 8), max(64, int(round(h * k / 8)) * 8)
    canvas = Image.new("RGB", (w, h), GREY)
    canvas.paste(crop, (0, 0), crop)
    if a.denoise < 0.95 and not a.mirror:   # the gap starts as the object's nearest colour, not the grey backdrop
        cv = np.asarray(canvas).copy()
        con = (on & ~fill)[y0:y1, x0:x1]
        _, (iy, ix) = ndimage.distance_transform_edt(~con, return_indices=True)
        fm_ = fill[y0:y1, x0:x1]
        cv[fm_] = cv[iy[fm_], ix[fm_]]
        canvas = Image.fromarray(cv)
    canvas = canvas.resize((W_, H_), Image.LANCZOS)
    m = Image.fromarray((fill[y0:y1, x0:x1] * 255).astype(np.uint8)).resize((W_, H_), Image.NEAREST)
    m = m.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
    line_img = None
    if lines is not None:   # white lines on black, as the union ControlNet's line-art mode takes them
        la = (lines[y0:y1, x0:x1] * 255).astype(np.uint8)
        line_img = Image.fromarray(la).resize((W_, H_), Image.NEAREST).filter(ImageFilter.MaxFilter(3)).convert("RGB")

    # the plate's model and the hero's character LoRA
    import key_poses as K
    os.environ.setdefault("ART_CKPT", "waiIllustriousSDXL_v170.safetensors")
    if a.hero in K.LORA:
        os.environ["ART_LORA"] = "%s:0.8" % K.LORA[a.hero]
        os.environ["ART_LORA_TRIGGER"] = K.TRIGGER[a.hero]
    import heroine_j3 as j3
    desc = P.desc(a.part, kind_of(a.part).replace("_", " "))
    if kind_of(a.part) in ("objects", "objects-back"):
        desc = K.HOLD.get(a.hero, "a weapon").replace("holding ", "")
    desc = a.desc or desc
    pos = "close-up of a single %s, one piece only, anime style, flat simple grey background, nothing else" % desc
    neg = ", background, scenery, other objects, extra limbs, multiple, person, text, watermark"

    os.makedirs(fixd, exist_ok=True)
    tiles = []
    before = Image.new("RGB", (w, h), GREY)
    before.paste(crop, (0, 0), crop)
    mark = np.asarray(before).copy()
    fm = fill[y0:y1, x0:x1]
    mark[fm] = (mark[fm] * 0.4 + np.array([255, 0, 255]) * 0.6).astype(np.uint8)
    tiles += [(before, "flip (0)" if a.mirror else "before"), (Image.fromarray(mark), "to fill (magenta)")]
    seeds = [] if a.dry else [int(s) for s in a.seeds.split(",") if s]
    for sd in seeds:
        if line_img is not None:
            out = inpaint_lines(j3, canvas, m, line_img, pos, neg, sd, a.denoise).resize((W_, H_))
        else:
            out = j3.img2img(canvas, pos, neg, sd, a.denoise, mask=m).resize((W_, H_))
        out = np.asarray(out.resize((w, h), Image.LANCZOS)).astype(int)
        if shape is not None:   # the outline says where the object is: all of it inside gets the new colour
            painted = fm.copy()
        else:
            painted = fm & (np.abs(out - np.array(GREY)).sum(-1) > 40)   # what came out as the grey backdrop stays empty
        res = part.copy()
        sub = res[y0:y1, x0:x1]
        sub[painted, :3] = out[painted]
        sub[painted, 3] = 255
        if shape is not None:
            res[~shape, 3] = 0
        Image.fromarray(res).save(os.path.join(fixd, "%s_%d.png" % (a.part, sd)))
        view = Image.new("RGB", (w, h), GREY)
        view.paste(Image.fromarray(sub), (0, 0), Image.fromarray(sub))
        tiles.append((view, "seed %d (+%d px)" % (sd, int(painted.sum()))))
        print("seed %d: %d px painted of %d to fill" % (sd, int(painted.sum()), int(fm.sum())), flush=True)
    th = 360
    ims = [(t.resize((max(1, t.width * th // t.height), th)), c) for t, c in tiles]
    sheet = Image.new("RGB", (sum(i.width for i, _ in ims), th + 20), (40, 40, 48))
    x = 0
    for i, c in ims:
        sheet.paste(i, (x, 20))
        ImageDraw.Draw(sheet).text((x + 4, 4), c, fill=(255, 255, 255))
        x += i.width
    sheet.save(os.path.join(fixd, "%s.jpg" % a.part), quality=88)
    print("sheet -> %s; apply one with --apply <seed>" % os.path.join(fixd, "%s.jpg" % a.part), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
