"""Parts for a bone rig from ONE plate (2026-10-01, the owner's pipeline: plate -> split and label -> check each
object is complete -> complete it -> reassemble and check -> motion test). Skill poses come from turning these
parts in the rig (live2d branch: inx_rig.py, rig_stress.py) instead of separate AI plates.

    python Tools/art/rig_parts.py <hero> <series> [--weapon x,y;x,y;... --not x,y;...]

Works on art_work/live/<hero>/<series>/st (a See-through split, Tools/art/see_through.py) and writes, in place:
  - objects: the weapon, cut from the plate with SAM2 (points along it, or given), taken out of whatever layer had
    it, and completed where the hand covers it by carrying its cross-section across the gap (no AI guess)
  - upperarm-/forearm-/hand- l|r: each arm cut by the distance walked from the shoulder along the arm (elbow at
    about half, wrist at about 0.8), each piece with a round cap past its joint so a turn opens no crack
  - the body under the arms and the weapon painted in (the hidden areas a moving arm or staff uncovers)
  - parts.json "pivots": shoulder / elbow / wrist l|r and grip {hand, point, tip}, pieces listed where the arm was
The live2d session's contract (2026-10-01) defines the names.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import live_layers as L     # noqa: E402

import config as _C   # live2d.toml
WORK = _C.WORK


def load(folder):
    st = os.path.join(folder, "st")
    meta = json.load(open(os.path.join(st, "parts.json")))
    src = Image.open(os.path.join(folder, "full.png")).convert("RGBA")
    arrs = {p["name"]: np.asarray(Image.open(os.path.join(st, p["file"])).convert("RGBA")).copy()
            for p in meta["order_back_to_front"]}
    return st, meta, src, arrs


def front_to_plate(meta, arrs, src):
    """wherever layers show on the figure, their colours are the plate's: from the front-most layer (parts.json order)
    back to the first opaque one, since soft edges blend with what lies behind them. Pixels moved between layers (an
    upper arm cut at the shoulder line hands its cap to the top) must not show the other layer's painted-in guess"""
    plate = np.asarray(src)
    fig = plate[..., 3] > 128
    names = [q["name"] for q in meta["order_back_to_front"] if q["name"] in arrs]
    covered = np.zeros(fig.shape, bool)   # an opaque layer in front already hides what's behind
    fixed = 0
    for n in reversed(names):
        a = arrs[n]
        m = fig & ~covered & (a[..., 3] > 0) & (np.abs(a[..., :3].astype(int) - plate[..., :3].astype(int)).sum(-1) > 30)
        a[m, :3] = plate[m, :3]
        fixed += int(m.sum())
        covered |= a[..., 3] >= 250
    print("pixels that show given the plate's colours: %d px" % fixed, flush=True)


def save(st, meta, arrs):
    for name, a in arrs.items():
        Image.fromarray(a).save(os.path.join(st, "part_%s.png" % name))
    json.dump(meta, open(os.path.join(st, "parts.json"), "w"), indent=1)


def geodesic(mask, start):
    """walking distance inside mask from start (4-neighbour BFS)"""
    from collections import deque
    h, w = mask.shape
    d = np.full(mask.shape, -1, np.int32)
    ys, xs = np.nonzero(mask)
    i = int(np.argmin(np.hypot(xs - start[0], ys - start[1])))
    q = deque([(ys[i], xs[i])])
    d[ys[i], xs[i]] = 0
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and d[ny, nx] < 0:
                d[ny, nx] = d[y, x] + 1
                q.append((ny, nx))
    return d


def cut_arm(arm_rgba, shoulder, wrist_hint, elbow_hint=None):
    """upper arm, forearm, hand and the joints. The walk starts at the shoulder; the hand's end is the farthest point
    of the piece that holds the wrist (a drape can hang lower than the hand). The elbow and the wrist are the detected
    ones (fig_joints.json, checked at L1) when they lie on the arm in walking order; else the elbow sits at half the
    walk to the hand's end and the wrist at 0.8 (a long sleeve or a jacket put those too far down, 2026-10-02). Each
    pixel goes to the bone it is nearest to (a drape by the upper arm moves with the upper arm), and each piece gets a
    round cap past its joint so a turn opens no crack"""
    import cv2
    m = arm_rgba[..., 3] > 128
    # a sleeve can cut the arm into pieces (freya's left arm: drape above, forearm below); join them before walking
    joined = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8)) > 0
    d = geodesic(joined, shoulder)
    start = tuple(int(v) for v in np.argwhere(d == 0)[0][::-1])
    n, lab, _, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    ys, xs = np.nonzero(m)
    k = int(np.argmin(np.hypot(xs - wrist_hint[0], ys - wrist_hint[1])))
    piece = lab == lab[ys[k], xs[k]]
    yy_, xx_ = np.mgrid[:m.shape[0], :m.shape[1]]
    near = np.hypot(xx_ - wrist_hint[0], yy_ - wrist_hint[1]) < 110   # a drape joined to the forearm hangs lower
    dd = np.where(piece & near & (d >= 0), d, -1)
    end_i = np.unravel_index(np.argmax(dd), dd.shape)
    dmax = dd.max()
    path = [end_i]   # walk back from the hand's end to the shoulder along the distance map
    while d[path[-1]] > 0:
        y, x = path[-1]
        nxt = min(((y + dy, x + dx) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))
                   if 0 <= y + dy < d.shape[0] and 0 <= x + dx < d.shape[1] and d[y + dy, x + dx] >= 0),
                  key=lambda q: d[q], default=None)
        if nxt is None or d[nxt] >= d[path[-1]]:
            break
        path.append(nxt)
    path = path[::-1]   # shoulder -> hand
    at = lambda f: (int(path[int(f * (len(path) - 1))][1]), int(path[int(f * (len(path) - 1))][0]))
    elbow, wrist, end = at(0.5), at(0.8), (int(end_i[1]), int(end_i[0]))
    d = np.where(joined, geodesic(joined, shoulder), -1)   # the unmasked walk (the path above needs the joins)
    # the detected joints, when they lie on the arm (within a few px of it) and in order along the walk
    jy, jx = np.nonzero(joined)

    def on_arm(p):
        if p is None:
            return None
        k = int(np.argmin(np.hypot(jx - p[0], jy - p[1])))
        return (int(jx[k]), int(jy[k])) if np.hypot(jx[k] - p[0], jy[k] - p[1]) <= 20 else None
    de, dw = on_arm(elbow_hint), on_arm(wrist_hint)
    walk = lambda q: d[q[1], q[0]]
    if de and dw and 0.2 * dmax < walk(de) < walk(dw) < walk(end) + 1:
        elbow, wrist = de, dw
        print("arm: detected elbow %s and wrist %s" % (elbow, wrist), flush=True)
    else:
        print("arm: elbow %s and wrist %s from the walk (detected ones off the arm or out of order: %s, %s)"
              % (elbow, wrist, elbow_hint, wrist_hint), flush=True)

    def seg_dist(p, q):
        yy, xx = np.mgrid[:m.shape[0], :m.shape[1]]
        px, py, qx, qy = float(p[0]), float(p[1]), float(q[0]), float(q[1])
        vx, vy = qx - px, qy - py
        t = np.clip(((xx - px) * vx + (yy - py) * vy) / max(1e-6, vx * vx + vy * vy), 0, 1)
        return np.hypot(xx - (px + t * vx), yy - (py + t * vy))
    dist = np.stack([seg_dist(start, elbow), seg_dist(elbow, wrist), seg_dist(wrist, end)])
    owner = np.argmin(dist, axis=0)
    width = max(6, int(np.sqrt(m.sum() / max(1, dmax))))
    yy, xx = np.mgrid[:m.shape[0], :m.shape[1]]
    cap = lambda j: np.hypot(xx - j[0], yy - j[1]) <= width + 3
    base = arm_rgba[..., 3] > 0
    # nothing of the upper arm lies past the shoulder towards the body: that bit would swing across the neck when the
    # shoulder turns (live2d's stress test, freya's left arm); it stays with the body
    ux, uy = elbow[0] - start[0], elbow[1] - start[1]
    past = ((xx - start[0]) * ux + (yy - start[1]) * uy) < -0.15 * width * np.hypot(ux, uy)
    upper = base & ((owner == 0) | cap(elbow)) & ~past
    fore = base & ((owner == 1) | cap(elbow) | cap(wrist))
    hand = base & ((owner == 2) | cap(wrist))
    pieces = {"_past": base & past & (owner == 0)}
    for name, mm in (("upperarm", upper), ("forearm", fore), ("hand", hand)):
        a2 = arm_rgba.copy()
        a2[~mm, 3] = 0
        pieces[name] = a2
    return pieces, {"shoulder": start, "elbow": elbow, "wrist": wrist, "end": end}


def carry_across(weapon, gap):
    """fill the weapon where something covered it: each covered row / column takes the cross-section of the
    nearest uncovered one along the weapon, shifted along its line (the drawing itself, not a guess)"""
    ys, xs = np.nonzero(weapon[..., 3] > 128)
    vertical = np.ptp(ys) >= np.ptp(xs)
    out = weapon.copy()
    idx = np.nonzero(gap.any(axis=1 if vertical else 0))[0]
    if not len(idx):
        return out
    have = weapon[..., 3] > 128
    lines = [i for i in range(have.shape[0 if vertical else 1]) if (have[i].any() if vertical else have[:, i].any())]
    for i in idx:
        src = min((j for j in lines if j not in set(idx)), key=lambda j: abs(j - i), default=None)
        if src is None:
            continue
        # the weapon's centre line moves between the rows above and below: interpolate the offset
        before = max((j for j in lines if j < i and j not in set(idx)), default=src)
        after = min((j for j in lines if j > i and j not in set(idx)), default=src)
        cen = lambda j: (np.nonzero(have[j])[0].mean() if vertical else np.nonzero(have[:, j])[0].mean())
        t = 0.5 if after == before else (i - before) / float(after - before)
        target = cen(before) * (1 - t) + cen(after) * t
        shift = int(round(target - cen(src)))
        if vertical:
            row = np.roll(weapon[src], shift, axis=0)
            fill = gap[i] & (row[..., 3] > 128)
            out[i][fill] = row[fill]
        else:
            col = np.roll(weapon[:, src], shift, axis=0)
            fill = gap[:, i] & (col[..., 3] > 128)
            out[:, i][fill] = col[fill]
    return out


def give_to_body(arrs, piece, skip):
    """each opaque pixel of piece to the nearest non-moving part (by distance to its opaque pixels)"""
    import cv2
    ys, xs = np.nonzero(piece[..., 3] > 128)
    names = [n for n in arrs if not moving(n) and n not in ("leftover", "hidden") and n in skip]
    if not len(xs) or not names:
        return
    dist = [cv2.distanceTransform((~(arrs[n][..., 3] > 128)).astype(np.uint8), cv2.DIST_L2, 3)[ys, xs] for n in names]
    owner = np.argmin(np.stack(dist), axis=0)
    for k, n in enumerate(names):
        sel = owner == k
        arrs[n][ys[sel], xs[sel]] = piece[ys[sel], xs[sel]]


def adopt_crumbs(arrs):
    """small bits of body layers stuck to a moving piece (fingers the split left in the dress, a strip of upper arm
    along the body) move with that piece"""
    import cv2
    for pn in [n for n in arrs if moving(n) and n != "objects"]:
        ring = cv2.dilate((arrs[pn][..., 3] > 128).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        for bn in [n for n in arrs if not moving(n) and n != "hidden"]:
            m = (arrs[bn][..., 3] > 128).astype(np.uint8)
            n_, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
            for i in range(1, n_):
                comp = lab == i
                if st[i, cv2.CC_STAT_AREA] < 800 and (comp & ring).sum() > 0.3 * comp.sum():
                    arrs[pn][comp] = arrs[bn][comp]
                    arrs[bn][comp, 3] = 0


def in_palette(raw, layer, under, tol=110):
    """the raw pixels whose colour is close to one the layer shows on the plate (freya's back hair was painted grey
    behind her arms: not hair)"""
    vis = (layer[..., 3] > 128) & ~under
    cols = layer[vis][:, :3].astype(np.float32)
    if len(cols) < 50:
        return np.ones(under.shape, bool)
    rng = np.random.default_rng(0)
    pal = cols[rng.choice(len(cols), size=min(400, len(cols)), replace=False)]   # a sample of the visible colours
    ys, xs = np.nonzero(under)
    q = raw[ys, xs, :3].astype(np.float32)
    ok = np.zeros(len(q), bool)
    for i in range(0, len(q), 4000):
        d = np.abs(q[i:i + 4000, None, :] - pal[None, :, :]).sum(2).min(1)
        ok[i:i + 4000] = d < tol
    out = np.zeros(under.shape, bool)
    out[ys, xs] = ok
    return out


IN_FRONT_OF_ARMS = ("front_hair",)   # the only body layers drawn over the arms and the weapon


def order_for_motion(src, arrs, meta, raw=None):
    """moving pieces must be the front-most layer over whatever they cover, or the body layers keep their picture and
    it stays behind as a ghost when they move (live2d's stress test, 2026-10-01). Order: body layers, "hidden", the
    moving pieces, then the few layers really in front of arms (front hair). Body layers lose their pixels under the
    pieces (the "hidden" paint takes that place), and the pieces take the plate's colours wherever they are the
    front-most, so the rest pose still equals the plate"""
    plate = np.asarray(src)
    order = meta["order_back_to_front"]
    legs = [p for p in order if is_leg(p["name"])]
    mov = [p for p in order if moving(p["name"]) and not is_leg(p["name"])]
    front = [p for p in order if p["name"] in IN_FRONT_OF_ARMS]
    skirt = [p for p in order if legs and p["name"] in SKIRT]   # only split out when the legs are
    back = [p for p in order if p["name"] == "objects-back"]
    body = [p for p in order if p not in mov + legs + front + skirt and p["name"] not in ("hidden", "objects-back")]
    hid = [p for p in order if p["name"] == "hidden"]
    meta["order_back_to_front"] = back + body + hid + legs + skirt + mov + front
    mask = lambda ps: np.any([arrs[p["name"]][..., 3] > 128 for p in ps], axis=0) if ps else np.zeros(plate.shape[:2], bool)
    front_m = mask(front)
    arm_front = front_m
    leg_front = front_m | mask(skirt) | mask(mov)   # the skirt, the arms and the weapon are in front of the legs
    under = np.zeros(plate.shape[:2], bool)
    for group, over in ((mov, arm_front), (legs, leg_front)):
        for p in group:
            a = arrs[p["name"]]
            own = (a[..., 3] > 128) & ~over & (plate[..., 3] > 128)
            a[own, :3] = plate[own, :3]   # at rest the piece shows what the plate shows there
            under |= own
    under_skirt = mask(mov) & ~front_m   # the skirt steps back only under the arms and the weapon (legs are behind it)
    was_body = np.zeros(plate.shape[:2], bool)   # where the split had body behind the pieces (its own hidden paint)
    for p in body + skirt:
        a = arrs[p["name"]]
        under_here = under_skirt if p in skirt else under
        was_body |= a[..., 3] > 128
        # hair behind an arm came out grey in the model's own paint (and hair has grey shadows, so a colour check
        # passes it): hair is left to the "hidden" paint; clothes keep the model's paint, which reads well
        r = raw.get(p["name"]) if raw and "hair" not in p["name"] else None
        if r is not None:   # under a piece: what the model itself painted for this layer there (the cloth behind the arm)
            keep = under_here & (r[..., 3] > 128) & in_palette(r, a, under_here)
            a[keep] = r[keep]
            a[under_here & ~keep, 3] = 0
        else:
            a[under_here, 3] = 0   # nothing known: the "hidden" paint fills it
    return was_body


def paint_hidden(src, arrs, meta, holes, hero, series):
    """paint the body in where moving pieces uncover it: the non-moving parts composited, the holes inpainted with
    the heroine's LoRA. The paint goes to its own layer "hidden", placed before the first moving piece: the later body
    layers are see-through where the pieces are, so the pieces still show at rest and the paint only when they move"""
    import cv2
    import heroine_j3 as j3
    body = Image.new("RGBA", src.size, (0, 0, 0, 0))
    for p in meta["order_back_to_front"]:
        if not moving(p["name"]) and p["name"] in arrs:
            body.alpha_composite(Image.fromarray(arrs[p["name"]]))
    flat, _ = L.flat(body)
    grown = cv2.dilate(holes.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    pos = j3.prompt_for(hero, series if series in j3.OUTFITS[hero] else "-", "no arms visible, clothes and body only")
    out = np.asarray(L.inpaint(flat, grown, pos, "arm, arms, hand, hands, fingers, skin strip, staff, stick, wooden pole, weapon", seed=11,
                               denoise=0.9).convert("RGB"))
    # where the model painted the backdrop (a gap between arm and body shows the background), nothing is behind
    backdrop = np.abs(out.astype(int) - np.array(L.GREY)).sum(2) < 40
    keep = holes & ~backdrop
    hid = np.zeros_like(np.asarray(src))
    hid[keep, :3] = out[keep]
    hid[keep, 3] = 255
    arrs["hidden"] = hid
    order = meta["order_back_to_front"]
    first = next(k for k, p in enumerate(order) if moving(p["name"]))
    order.insert(first, {"name": "hidden", "file": "part_hidden.png", "depth": order[first]["depth"],
                         "from": "painted in under the moving pieces"})
    print("painted in under the moving pieces: %d px" % holes.sum(), flush=True)


LEG = ("thigh", "shin", "foot")
SKIRT = ("bottomwear",)   # stays on the pelvis, in front of the legs and behind the arms


def is_leg(name):
    return name.split("-")[0] in LEG


def moving(name):
    """pieces the rig turns ("objects-back" turns with the weapon too, but stays at the back of the order: it is what
    the body hides)"""
    return name == "objects" or is_leg(name) or name.split("-")[0] in ("upperarm", "forearm", "hand", "handwear")


def weapon_tip(wm, grip):
    """the weapon's working end: of its two far ends, the one with more weapon around it (orb, wrench head)"""
    ys, xs = np.nonzero(wm)
    a = int(np.argmax(np.hypot(xs - grip[0], ys - grip[1])))
    b = int(np.argmax(np.hypot(xs - xs[a], ys - ys[a])))
    mass = lambda i: int((np.hypot(xs - xs[i], ys - ys[i]) < 60).sum())
    k = a if mass(a) >= mass(b) else b
    return [int(xs[k]), int(ys[k])]


def weapon_corridor(lines, half, fig):
    """where the whole weapon lies: its traced lines at its width, the longest one carried on to the feet"""
    import cv2
    ys = np.nonzero(fig.any(axis=1))[0]
    foot = int(ys.max()) - 10 if len(ys) else fig.shape[0] - 1
    m = np.zeros(fig.shape, np.uint8)
    main = max(lines, key=len)
    for ln in lines:
        pts = [tuple(int(v) for v in q) for q in ln]
        if ln is main and len(pts) >= 2:
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            if y1 > y0 and y1 < foot:   # heading down: carry it on to the feet
                t = (foot - y1) / float(y1 - y0)
                pts.append((int(x1 + (x1 - x0) * t), foot))
        if len(pts) == 1:
            cv2.circle(m, pts[0], int(half * 1.2) + 4, 1, -1)
        else:
            cv2.polylines(m, [np.array(pts, np.int32)], False, 1, thickness=int(2 * half) + 4)
    return m > 0


def extend_down(front, back, corridor, sample=40):
    """a straight weapon that ends above the feet (the plate hides its foot behind the dress) is carried on down its
    corridor by repeating its own lowest stretch, row by row along its slope (the AI paint left it empty)"""
    have = (front[..., 3] > 128) | (back[..., 3] > 128)
    crow = np.nonzero(corridor.any(axis=1))[0]
    wide = (have & corridor).sum(axis=1) >= 3
    rows = np.nonzero(wide)[0]
    if not len(rows) or not len(crow):
        return
    # the weapon runs down without a break to here (stray painted chips further down don't count)
    last = int(rows[0])
    for y in rows[1:]:
        if y - last > 6:
            break
        last = int(y)
    if last >= crow.max() - 2:
        return
    have[last + 1:] = False   # below the break everything is redone
    both = np.where((front[..., 3] > 128)[..., None], front, back)
    cen = lambda y: np.nonzero(have[y])[0].mean() if have[y].any() else None
    # a well-formed stretch above the very end (the tip fades out and makes a thin copy)
    ys = [y for y in range(max(0, last - 3 * sample), last - sample) if (have[y] & corridor[y]).sum() >= 6]
    if len(ys) < 5:
        return
    xs = [cen(y) for y in ys]
    slope = np.polyfit(ys, xs, 1)[0]   # x per row along the lowest stretch
    added = 0
    for i, y in enumerate(range(last + 1, int(crow.max()) + 1)):
        src_y = ys[-1 - (i % len(ys))]   # walk back up the stretch and repeat it
        target_c = cen(ys[-1]) + slope * (y - ys[-1])
        row = np.roll(both[src_y], int(round(target_c - cen(src_y))), axis=0)
        fill = corridor[y] & (row[..., 3] > 128) & ~(front[y][..., 3] > 128)
        back[y][corridor[y] & ~(front[y][..., 3] > 128)] = 0   # stray chips here give way to the repeated stretch
        back[y][fill] = row[fill]
        added += int(fill.sum())
    print("weapon carried down to the feet: %d px" % added, flush=True)


def paint_weapon(weapon, missing, hero, size):
    """paint the weapon in where the plate hides it, on a canvas that holds only the weapon (so the model continues
    the weapon, not the dress in front of it); returns the painted pixels as an RGBA layer"""
    import cv2
    import workflows as W
    import comfy_gen as cg
    import key_poses as K
    from PIL import ImageFilter
    out = np.zeros((size[1], size[0], 4), np.uint8)
    if missing.sum() < 30:
        return out
    canvas = Image.new("RGBA", size, L.GREY + (255,))
    canvas.alpha_composite(Image.fromarray(weapon))
    m = Image.fromarray((cv2.dilate(missing.astype(np.uint8), np.ones((5, 5), np.uint8)) * 255).astype(np.uint8))
    desc = K.HOLD.get(hero, "a weapon").replace("holding ", "")
    wf = W.fill(W.load("inpaint"), {
        "正面提示詞": {"text": "game asset, anime style, a single %s, simple grey background, no humans" % desc},
        "排除詞": {"text": "person, hand, arm, dress, cloth, hair, hat, text, watermark, blurry"},
        "採樣": {"seed": 5, "steps": 30, "cfg": 6.0, "denoise": 1.0}, "存圖": {"filename_prefix": "weapon_fill"},
        "輸入圖": {"image": cg.upload(L._tmp(canvas.convert("RGB")))},
        "遮罩": {"image": cg.upload(L._tmp(Image.merge("RGB", (m, m, m)).filter(ImageFilter.GaussianBlur(2))))}})
    import heroine_j3 as j3
    painted = np.asarray(j3.run_wf(wf).resize(size).convert("RGB")).astype(int)
    solid = missing & (np.abs(painted - np.array(L.GREY)).sum(2) > 40)   # what came out as backdrop stays empty
    out[solid, :3] = painted[solid]
    out[solid, 3] = 255
    print("weapon painted in where the plate hides it: %d px" % solid.sum(), flush=True)
    return out


def split_legs(folder, arrs, meta, j, pivots):
    """legwear (both legs, one layer in See-through) and footwear become thigh / shin / foot, left and right: each
    pixel goes to the leg bone it is nearest to, with round caps past the knee and the ankle. Joints: the hips found
    on the plate, knees and ankles from the skeleton the plate was drawn from. The waist pivot sits between the hips;
    the top is carried a little way down behind the skirt so a lean opens no gap"""
    import cv2
    import key_poses as K
    pj = os.path.join(folder, "pose.json")
    if "legwear" not in arrs:
        return
    pts = None
    if os.path.exists(pj):   # a key pose: the skeleton it was drawn from
        info = json.load(open(pj))
        pts = K.POSES.get(info["action"], {}).get(info["pose"])
    h, w = arrs["legwear"].shape[:2]
    if not pts:   # a main design or an outfit: the knees and ankles found on the plate (live_layers.py parts)
        if not all(j.get(k) for k in ("knee_r", "ankle_r", "knee_l", "ankle_l")):
            print("legs: no knees / ankles (pose.json or fig_joints.json), left whole", flush=True)
            return
        idx = {9: "knee_r", 10: "ankle_r", 12: "knee_l", 13: "ankle_l", 8: "hip_r", 11: "hip_l"}
        pts = {i: (j[k][0] / w, j[k][1] / h) for i, k in idx.items() if j.get(k)}
    at = lambda i: (pts[i][0] * w, pts[i][1] * h)
    J = {"hip_r": tuple(j.get("hip_r") or at(8)), "knee_r": at(9), "ankle_r": at(10),
         "hip_l": tuple(j.get("hip_l") or at(11)), "knee_l": at(12), "ankle_l": at(13)}
    yy, xx = np.mgrid[:h, :w]

    def seg(p, q):
        vx, vy = q[0] - p[0], q[1] - p[1]
        t = np.clip(((xx - p[0]) * vx + (yy - p[1]) * vy) / max(1e-6, vx * vx + vy * vy), 0, 1)
        return np.hypot(xx - (p[0] + t * vx), yy - (p[1] + t * vy))
    bones = [("thigh", "r", seg(J["hip_r"], J["knee_r"])), ("shin", "r", seg(J["knee_r"], J["ankle_r"])),
             ("thigh", "l", seg(J["hip_l"], J["knee_l"])), ("shin", "l", seg(J["knee_l"], J["ankle_l"]))]
    owner = np.argmin(np.stack([b[2] for b in bones]), axis=0)
    leg = arrs.pop("legwear")
    lb = leg[..., 3] > 0
    width = max(6, int(np.sqrt((leg[..., 3] > 128).sum() / 4.0 / max(1.0, np.hypot(J["hip_r"][0] - J["ankle_r"][0],
                                                                               J["hip_r"][1] - J["ankle_r"][1])))))
    cap = lambda p: np.hypot(xx - p[0], yy - p[1]) <= width + 3
    pieces = {}
    for i, (name, side, _) in enumerate(bones):
        m = lb & ((owner == i) | cap(J["knee_" + side]))   # both pieces overlap round the knee
        if name == "shin":
            m |= lb & cap(J["ankle_" + side])
        a = leg.copy()
        a[~m, 3] = 0
        pieces["%s-%s" % (name, side)] = a
    if "footwear" not in arrs:   # the shoe drawn into the leg: what lies past the ankle along the shin is the foot
        for side in ("r", "l"):
            k, a_ = J["knee_" + side], J["ankle_" + side]
            vx, vy = a_[0] - k[0], a_[1] - k[1]
            t = ((xx - k[0]) * vx + (yy - k[1]) * vy) / max(1e-6, vx * vx + vy * vy)
            shin = pieces["shin-" + side]
            past = (shin[..., 3] > 0) & (t > 1.0)
            if past.sum() > 50:
                f = shin.copy()
                f[~(past | ((shin[..., 3] > 0) & cap(a_))), 3] = 0
                pieces["foot-" + side] = f
                shin[past & ~cap(a_), 3] = 0
    if "footwear" in arrs:   # each shoe to the nearer ankle
        foot = arrs.pop("footwear")
        near_r = np.hypot(xx - J["ankle_r"][0], yy - J["ankle_r"][1]) <= np.hypot(xx - J["ankle_l"][0], yy - J["ankle_l"][1])
        for side, sel in (("r", near_r), ("l", ~near_r)):
            a = foot.copy()
            a[~sel, 3] = 0
            pieces["foot-%s" % side] = a
    order = meta["order_back_to_front"]
    i = next(k for k, p in enumerate(order) if p["name"] == "legwear")
    depth = order[i]["depth"]
    order[:] = [p for p in order if p["name"] not in ("legwear", "footwear")]
    order[i:i] = [{"name": n, "file": "part_%s.png" % n, "depth": depth} for n in
                  ("thigh-r", "shin-r", "foot-r", "thigh-l", "shin-l", "foot-l") if n in pieces]
    arrs.update(pieces)
    for k, v in J.items():
        pivots[k] = (int(v[0]), int(v[1]))
    for side in ("r", "l"):   # the toe: the foot's point farthest from its ankle
        f = pieces.get("foot-" + side)
        if f is not None and (f[..., 3] > 128).any():
            fy, fx = np.nonzero(f[..., 3] > 128)
            a_ = J["ankle_" + side]
            k = int(np.argmax(np.hypot(fx - a_[0], fy - a_[1])))
            pivots["foot_" + side] = (int(fx[k]), int(fy[k]))
    pivots["waist"] = (int((J["hip_r"][0] + J["hip_l"][0]) / 2), int((J["hip_r"][1] + J["hip_l"][1]) / 2))
    # the top carried ~25 px down behind the skirt (hidden at rest: the skirt is in front of it)
    if "topwear" in arrs and "bottomwear" in arrs:
        top = arrs["topwear"]
        tm = top[..., 3] > 128
        down = np.zeros_like(tm)
        for dy in range(1, 26):
            down[dy:] |= tm[:-dy]
        band = down & ~tm & (arrs["bottomwear"][..., 3] > 128)
        if band.any():
            rgb = cv2.cvtColor(top[..., :3].copy(), cv2.COLOR_RGB2BGR)
            fill = cv2.cvtColor(cv2.inpaint(rgb, (~tm).astype(np.uint8) * 255, 7, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)
            top[band, :3] = fill[band]
            top[band, 3] = 255
            print("waist: the top carried down behind the skirt: %d px" % band.sum(), flush=True)
    # the pelvis side behind the top's lower edge: when the upper body leans, what the top's lower part covered
    # shows; "hidden-pelvis" (stays with the pelvis, behind the top) continues the skirt up into it
    if "topwear" in arrs and "bottomwear" in arrs:
        top_m = arrs["topwear"][..., 3] > 128
        ys_, xs_ = np.nonzero(top_m)
        if len(ys_):
            bottom_edge = np.zeros_like(top_m)
            for x in np.unique(xs_):
                col = ys_[xs_ == x]
                bottom_edge[max(0, col.max() - 45):col.max() + 1, x] = True
            band = bottom_edge & top_m
            skirt = arrs["bottomwear"]
            rgb = cv2.cvtColor(skirt[..., :3].copy(), cv2.COLOR_RGB2BGR)
            fill = cv2.cvtColor(cv2.inpaint(rgb, (~(skirt[..., 3] > 128)).astype(np.uint8) * 255, 9, cv2.INPAINT_TELEA),
                                cv2.COLOR_BGR2RGB)
            hp = np.zeros_like(skirt)
            hp[band, :3] = fill[band]
            hp[band, 3] = 255
            arrs["hidden-pelvis"] = hp
            ti = next(k for k, p in enumerate(meta["order_back_to_front"]) if p["name"] == "topwear")
            meta["order_back_to_front"].insert(ti, {"name": "hidden-pelvis", "file": "part_hidden-pelvis.png",
                                                    "depth": 0.0, "from": "painted in: the waist behind the top"})
            print("waist: the pelvis side behind the top's lower edge: %d px" % band.sum(), flush=True)
    for fn in ("part_legwear.png", "part_footwear.png"):   # the rig reads the folder: no stale whole legs
        f = os.path.join(folder, "st", fn)
        if os.path.exists(f):
            os.remove(f)
    print("legs:", ", ".join("%s %d px" % (n, (a[..., 3] > 128).sum()) for n, a in pieces.items()), flush=True)


def run(hero, series, weapon_pts=None, not_pts=None, weapon_lines=None, match_plate=False):
    import cv2
    folder = os.path.join(WORK, "live", hero, series)
    st, meta, src, arrs = load(folder)
    fig = np.asarray(src)[..., 3] > 40
    j = json.load(open(os.path.join(folder, "fig_joints.json")))
    names = [p["name"] for p in meta["order_back_to_front"]]

    # 1. the weapon: SAM2 on the plate along it, taken out of every other layer
    if weapon_pts:
        flat, _ = L.flat(src)
        w = L.sam2_mask(flat, weapon_pts, not_pts or []) & fig
        # the points trace the weapon: keep what lies along that line (SAM2 bled into a dark train of the same tone)
        lines = weapon_lines or [weapon_pts]   # several traced lines: a staff and the orb floating in its crook
        lane = np.zeros(fig.shape, np.uint8)
        for ln in lines:
            if len(ln) == 1:   # a lone point (an orb floating in the crook): a disc around it
                cv2.circle(lane, tuple(int(v) for v in ln[0]), 45, 1, -1)
            else:
                cv2.polylines(lane, [np.array(ln, np.int32)], False, 1, thickness=64)
        w &= lane > 0
        dist = cv2.distanceTransform(w.astype(np.uint8), cv2.DIST_L2, 3)
        half = max(4.0, float(np.median(dist[dist > 0])) * 1.6) if (dist > 0).any() else 10.0
        # where SAM2 lost it against a dark cloth of the same tone, the plate along the traced line at the weapon's
        # width is the weapon (without this those pixels ended in no layer at all)
        core = np.zeros(fig.shape, np.uint8)
        for ln in lines:
            if len(ln) > 1:
                cv2.polylines(core, [np.array(ln, np.int32)], False, 1, thickness=int(2 * half))
        w |= (core > 0) & fig
        w = (cv2.dilate(w.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & fig & (lane > 0)   # its line art too
        wa = np.zeros_like(np.asarray(src))
        wa[w] = np.asarray(src)[w]
        # the whole weapon: its traced line, the longest one carried down to the feet (the plate hides the foot of
        # a staff behind the dress), at its own width; what the plate doesn't show there is painted in on its own
        corridor = weapon_corridor(lines, half, fig)
        hidden_w = paint_weapon(wa, corridor & ~w, hero, src.size)
        extend_down(wa, hidden_w, corridor)
        # only what the figure hides: outside it the painted stretch would show at rest where the plate has none
        # (a staff carried to the floor beside the train), so the weapon keeps the plate's own length there
        hidden_w[~(np.asarray(src)[..., 3] > 128), 3] = 0
        # and only the stretches that join the weapon: a piece cut off by the figure's edge would stay behind as an
        # island when the weapon turns (live2d, freya's staff by her feet)
        both = (hidden_w[..., 3] > 128) | (wa[..., 3] > 128)
        n_, lab_, _, _ = cv2.connectedComponentsWithStats(cv2.dilate(both.astype(np.uint8), np.ones((9, 9), np.uint8)), connectivity=8)
        keep_ids = set(np.unique(lab_[wa[..., 3] > 128])) - {0}
        hidden_w[~np.isin(lab_, list(keep_ids)), 3] = 0
        if "objects" in arrs:   # what the old weapon layer held that isn't this weapon (a sleeve taken for one)
            old_o = arrs["objects"].copy()
            old_o[w, 3] = 0
            om = old_o[..., 3] > 128
            arm = next((k for k in ("handwear-l", "handwear-r") if k in arrs and
                        ((cv2.dilate((arrs[k][..., 3] > 128).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0) & om).sum()
                        > 0.05 * max(1, om.sum())), None)
            if arm:   # a sleeve drape hanging from that arm: it moves with the arm
                arrs[arm][om] = old_o[om]
            else:
                give_to_body(arrs, old_o, names)
        edge = cv2.dilate(w.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        for n in names:
            if n != "objects":
                arrs[n][edge & ~(arrs[n][..., 3] > 128) | w, 3] = 0   # the weapon's pixels and its soft rim
        arrs["objects"] = wa
        if "objects" not in names:
            meta["order_back_to_front"].insert(len(names) - 1, {"name": "objects", "file": "part_objects.png", "depth": 0.0})
        # the painted-in stretches go to "objects-back", behind every layer: at rest the hat or the dress covers them
        # as on the plate; when the weapon moves they show (the rig turns it with "objects")
        arrs["objects-back"] = hidden_w
        meta["order_back_to_front"].insert(0, {"name": "objects-back", "file": "part_objects-back.png", "depth": 1.0,
                                               "from": "painted in: the weapon where the plate hides it"})
    # 2. the arms
    pivots = {}
    order = meta["order_back_to_front"]
    for side in ("l", "r"):
        key = "handwear-%s" % side
        if key not in arrs:
            continue
        pieces, joints = cut_arm(arrs[key], j["shoulder_%s" % side], j["wrist_%s" % side], j.get("elbow_%s" % side))
        i = next(k for k, p in enumerate(order) if p["name"] == key)
        new = [{"name": "%s-%s" % (n, side), "file": "part_%s-%s.png" % (n, side), "depth": order[i]["depth"]}
               for n in ("upperarm", "forearm", "hand")]
        order[i:i + 1] = new   # where the whole arm was, so the rest pose doesn't change
        past = pieces.pop("_past")
        if past.any():   # the bit past the shoulder goes back to the body
            rest = arrs[key].copy()
            rest[~past, 3] = 0
            give_to_body(arrs, rest, names)
        del arrs[key]
        for n, a in pieces.items():
            arrs["%s-%s" % (n, side)] = a
        pivots.update({"shoulder_%s" % side: joints["shoulder"], "elbow_%s" % side: joints["elbow"],
                       "wrist_%s" % side: joints["wrist"], "_end_%s" % side: joints["end"]})
    # 2b. the legs and the waist (the owner, 2026-10-01: body and legs move too)
    split_legs(folder, arrs, meta, j, pivots)
    adopt_crumbs(arrs)
    # 3. the grip: the hand whose piece touches the weapon most, the point where they meet, the far tip
    if "objects" in arrs and pivots:
        wm = arrs["objects"][..., 3] > 128
        best = None
        for side in ("l", "r"):
            if "hand-%s" % side not in arrs:
                continue
            hm = cv2.dilate((arrs["hand-%s" % side][..., 3] > 128).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
            touch = (hm & wm).sum()
            if best is None or touch > best[0]:
                best = (touch, side, hm)
        _, side, hm = best
        yy, xx = np.nonzero(hm & wm) if (hm & wm).any() else np.nonzero(hm)
        point = (int(xx.mean()), int(yy.mean()))
        # complete the weapon where the hand covers it
        gap = hm & ~wm
        arrs["objects"] = carry_across(arrs["objects"], gap)
        pivots["grip"] = {"hand": side, "point": list(point), "tip": weapon_tip(arrs["objects"][..., 3] > 128, point)}
        # the weapon just behind its hand
        o = meta["order_back_to_front"]
        wi = next(k for k, p in enumerate(o) if p["name"] == "objects")
        we = o.pop(wi)
        hi = next(k for k, p in enumerate(o) if p["name"] == "hand-%s" % side)
        o.insert(hi, we)
    # 4. the body under what moves: body layers step back behind the pieces, and what the figure had there and no
    # body part covers now is painted in
    import see_through as ST
    raw = ST.raw_layers(json.load(open(os.path.join(st, "st_layers.json"), encoding="utf-8")), src)
    was_body = order_for_motion(src, arrs, meta, raw)
    body_cov = np.zeros(fig.shape, bool)
    for n, a in arrs.items():
        if not moving(n):
            body_cov |= a[..., 3] > 128
    under = np.zeros(fig.shape, bool)
    for n, a in arrs.items():
        if moving(n):
            under |= a[..., 3] > 128
    # the body's outline with only small gaps closed: a wide close took the gap between a hanging arm and the body
    # for body, and the paint put a pale strip of skin there (live2d's ghost check)
    closed = cv2.morphologyEx(body_cov.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8)) > 0
    # a hole is where the split had body behind a piece (See-through paints hidden areas) or a small gap in the body;
    # a gap between a hanging arm and the body had none and stays see-through
    holes = under & (was_body | closed) & ~body_cov & fig
    # behind a leg standing in a dress slit is the inside of the skirt, which the split never painted: under a leg,
    # whatever lies within the body's wide outline is painted in (between the legs of an A-pose is outside it)
    leg_under = np.zeros(fig.shape, bool)
    for n, a in arrs.items():
        if is_leg(n):
            leg_under |= a[..., 3] > 128
    wide = cv2.morphologyEx(body_cov.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((61, 61), np.uint8)) > 0
    holes |= leg_under & wide & ~body_cov & fig
    if holes.sum() > 50:
        paint_hidden(src, arrs, meta, holes, hero, series)
    # the band where an upper arm lay against the body: continue the body from right beside it (no AI: next to skin the
    # paint echoed the arm, live2d's ghost check), and fill the armpit gap next to the body the same way
    body_img = Image.new("RGBA", src.size, (0, 0, 0, 0))
    for p in meta["order_back_to_front"]:
        if not moving(p["name"]):
            body_img.alpha_composite(Image.fromarray(arrs[p["name"]]))
    ba = np.asarray(body_img)
    has = ba[..., 3] > 128
    ua = np.zeros(fig.shape, bool)
    for side in ("l", "r"):
        if "upperarm-%s" % side in arrs:
            ua |= arrs["upperarm-%s" % side][..., 3] > 128
    near_body = cv2.dilate(has.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
    band = cv2.dilate(ua.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    band &= fig & near_body & (was_body | closed | ~has)
    band &= ~(cv2.erode(has.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) | (arrs.get("hidden", np.zeros_like(ba))[..., 3] > 128)
    if band.sum() > 30:
        rgb = cv2.cvtColor(ba[..., :3].copy(), cv2.COLOR_RGB2BGR)
        filled = cv2.cvtColor(cv2.inpaint(rgb, (band | ~has).astype(np.uint8) * 255, 9, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)
        if "hidden" not in arrs:
            arrs["hidden"] = np.zeros_like(ba)
            first = next(k for k, p in enumerate(meta["order_back_to_front"]) if moving(p["name"]))
            meta["order_back_to_front"].insert(first, {"name": "hidden", "file": "part_hidden.png", "depth": 0.0})
        arrs["hidden"][band, :3] = filled[band]
        arrs["hidden"][band, 3] = 255
        print("upper-arm contact bands continued from the body beside them: %d px" % band.sum(), flush=True)
    # what is still open under a piece right next to the body (a hand resting on the dress): the dress continued
    # from beside it. A-pose arms stand further off than this, so the gap between arm and body stays open
    cov = np.zeros(fig.shape, bool)
    for n, a in arrs.items():
        if not moving(n) and n != "objects-back":
            cov |= a[..., 3] > 128
    under_all = np.zeros(fig.shape, bool)
    for n, a in arrs.items():
        if moving(n):
            under_all |= a[..., 3] > 128
    near = cv2.morphologyEx(cov.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8)) > 0
    rest = under_all & near & ~cov & fig
    if rest.sum() > 20:
        base = Image.new("RGBA", src.size, (0, 0, 0, 0))
        for p in meta["order_back_to_front"]:
            if not moving(p["name"]) and p["name"] != "objects-back":
                base.alpha_composite(Image.fromarray(arrs[p["name"]]))
        ba = np.asarray(base)
        rgb = cv2.cvtColor(ba[..., :3].copy(), cv2.COLOR_RGB2BGR)
        fill = cv2.cvtColor(cv2.inpaint(rgb, (rest | ~(ba[..., 3] > 128)).astype(np.uint8) * 255, 9, cv2.INPAINT_TELEA),
                            cv2.COLOR_BGR2RGB)
        if "hidden" not in arrs:
            arrs["hidden"] = np.zeros_like(ba)
            first = next(k for k, p in enumerate(meta["order_back_to_front"]) if moving(p["name"]))
            meta["order_back_to_front"].insert(first, {"name": "hidden", "file": "part_hidden.png", "depth": 0.0})
        arrs["hidden"][rest, :3] = fill[rest]
        arrs["hidden"][rest, 3] = 255
        print("small holes next to the body closed: %d px" % rest.sum(), flush=True)
    meta["pivots"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in pivots.items() if not k.startswith("_")}
    if match_plate:   # off by default: the plate is material, whole parts matter more than matching it (the owner)
        front_to_plate(meta, arrs, src)
    save(st, meta, arrs)
    for side in ("l", "r"):   # the rig reads the folder too: no stale whole arms
        f = os.path.join(st, "part_handwear-%s.png" % side)
        if os.path.exists(f) and not any(p["name"] == "handwear-%s" % side for p in meta["order_back_to_front"]):
            os.remove(f)
    print("pivots:", json.dumps(meta["pivots"]), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("series")
    ap.add_argument("--weapon", default="")
    ap.add_argument("--not", dest="nots", default="")
    ap.add_argument("--match-plate", action="store_true", help="give the layers that show the plate's colours")
    a = ap.parse_args()
    pts = lambda s: [tuple(int(v) for v in p.split(",")) for p in s.split(";") if p]
    lines = [pts(part) for part in a.weapon.split("|") if part]   # "x,y;x,y|x,y": separate traced lines
    run(a.hero, a.series, [q for ln in lines for q in ln], pts(a.nots), lines, a.match_plate)
