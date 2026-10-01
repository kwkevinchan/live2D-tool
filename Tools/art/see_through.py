"""Anime layer decomposition with See-through (shitagaki-lab/see-through, SIGGRAPH 2026; ComfyUI node
jtydhr88/ComfyUI-See-through). Code Apache-2.0, weights openrail++ (commercial use allowed). Needs ComfyUI.

    python Tools/art/see_through.py <hero> <series> [--res 1280] [--seed 42]

One picture -> about 23 RGBA layers with the hidden parts painted in (front / back hair, face, irides, eye whites,
lashes, brows, mouth, nose, ears, neck, topwear, handwear, bottomwear, legwear, footwear, accessories, objects),
each with a depth map, in drawing order. Input: the plate (full.png) of <plates>/<hero>[/skins/<series>] (live2d.toml) or a
key-pose folder; output: art_work/live/<hero>/<series>/st/ with st_<tag>.png, st_<tag>_depth.png, st_layers.json.
"""
import argparse
import glob
import json
import os
import shutil
import sys
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import comfy_gen as cg      # noqa: E402
import live_layers as L     # noqa: E402
import workflows as W       # noqa: E402

COMFY_OUT = L.COMFY_OUT


def decompose(hero, series, res=1280, seed=42):
    src = Image.open(os.path.join(L.src_dir(hero, series), "full.png")).convert("RGBA")
    bg = Image.new("RGB", src.size, (255, 255, 255))   # the model was trained on illustrations; white behind the figure
    bg.paste(src, (0, 0), src)
    # the figure fills the picture (a small figure in a wide frame put the face parts on the chin)
    crop = crop_box(src)
    bg = bg.crop(crop)
    tmp = L._tmp(bg)
    prefix = "st_%s_%s_%d" % (hero, series.replace("-", "main"), int(time.time()))
    wf = W.fill(W.load("see_through"), {"輸入圖": {"image": cg.upload(tmp)}, "分層": {"seed": seed, "resolution": res},
                                         "深度": {"seed": seed}, "存 PSD": {"filename_prefix": prefix}})
    t0 = time.time()
    pid = cg.post("/prompt", {"prompt": wf, "client_id": "seethrough"})["prompt_id"]
    while True:
        h = json.loads(cg.get("/history/%s" % pid))
        if pid in h:
            break
        time.sleep(3)
        print("分層中… %d 秒" % (time.time() - t0), flush=True)
    status = h[pid].get("status", {})
    if status.get("status_str") == "error":
        raise RuntimeError("See-through failed: %s" % json.dumps(status.get("messages", []))[:1500])
    info = sorted(glob.glob(os.path.join(COMFY_OUT, prefix + "*_layers.json")))
    if not info:
        raise RuntimeError("no layers written")
    meta = json.load(open(info[-1], encoding="utf-8"))
    out = os.path.join(L.out_dir(hero, series), "st")
    os.makedirs(out, exist_ok=True)
    n = 0
    for f in glob.glob(os.path.join(COMFY_OUT, prefix + "_*.png")):
        tag = os.path.basename(f)[len(prefix) + 1:].split("_", 2)[-1]   # <ts>_<uid>_<tag>.png -> <tag>.png
        shutil.copy(f, os.path.join(out, "st_" + tag))
        n += 1
    meta["input"] = {"crop": list(crop), "resolution": res}   # how to map the layers back (to_plate)
    json.dump(meta, open(os.path.join(out, "st_layers.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%d files -> %s (%.0f s)" % (n, out, time.time() - t0), flush=True)
    to_plate(meta, src, out)
    fix_grip(hero, series, out)
    refine_leftover(hero, series, out)
    return out


def fix_grip(hero, series, out):
    """key-pose plates (pose.json next to full.png) were drawn from a known skeleton; when the skeleton detector
    missed the hands (a big hat or staff confuses it) or found no weapon, the drawn wrists are used, and the grip is
    the point of the held-object layer nearest to one of them (2026-10-01, live2d places skill effects there)"""
    import numpy as np
    d = L.src_dir(hero, series)
    pj, fj, obj = (os.path.join(d, "pose.json"), os.path.join(L.out_dir(hero, series), "fig_joints.json"),
                   os.path.join(out, "part_objects.png"))
    if not (os.path.exists(pj) and os.path.exists(fj)):
        return
    import key_poses as K
    info = json.load(open(pj))
    pts = K.POSES.get(info["action"], {}).get(info["pose"])
    if not pts:
        return
    j = json.load(open(fj))
    at = lambda i: (pts[i][0] * K.W_, pts[i][1] * K.H_)
    drawn = {"wrist_r": at(4), "wrist_l": at(7), "elbow_r": at(3), "elbow_l": at(6), "neck": at(1),
             "shoulder_r": at(2), "shoulder_l": at(5), "hip_r": at(8), "hip_l": at(11)}
    for k, v in drawn.items():   # missing, or the detector is off by more than a hand: take the drawn joint
        if not j.get(k) or np.hypot(j[k][0] - v[0], j[k][1] - v[1]) > 0.09 * K.H_:
            j[k] = [float(v[0]), float(v[1])]
    # the face from the split's own eyes (the face finder once landed on an outstretched sleeve)
    eyes = [os.path.join(out, "part_eyewhite-%s.png" % s) for s in "lr"]
    if all(os.path.exists(e) for e in eyes):
        cs = []
        for e in eyes:
            ys, xs = np.nonzero(np.asarray(Image.open(e))[..., 3] > 128)
            if len(xs):
                cs.append((xs.mean(), ys.mean()))
        if len(cs) == 2:
            ex, ey = (cs[0][0] + cs[1][0]) / 2, (cs[0][1] + cs[1][1]) / 2
            size = float(j["face"][2]) if j.get("face") else 3.2 * abs(cs[0][0] - cs[1][0])
            if not j.get("face") or np.hypot(j["face"][0] - ex, j["face"][1] - ey) > 0.5 * size:
                j["face"] = [float(ex), float(ey + 0.1 * size), size]
    if j.get("face") and j.get("neck") and j["neck"][1] < j["face"][1] + 0.3 * j["face"][2]:
        j["neck"] = [float(drawn["neck"][0]), float(drawn["neck"][1])]   # a neck at face height is the detector's slip
    if not os.path.exists(obj):   # no held-object layer: the model left the weapon to the leftover layer
        obj = os.path.join(out, "part_leftover.png")
    grip = j.get("weapon_grip")
    if (not grip or "from" in grip) and os.path.exists(obj):   # ours (not the detector's): redo it on a new split
        a = np.asarray(Image.open(obj))[..., 3] > 128
        ys, xs = np.nonzero(a)
        if len(xs) > 200:
            best = None
            for hand, w in (("arm_r", j["wrist_r"]), ("arm_l", j["wrist_l"])):
                i = int(np.argmin(np.hypot(xs - w[0], ys - w[1])))
                dist = float(np.hypot(xs[i] - w[0], ys[i] - w[1]))
                if best is None or dist < best[0]:
                    best = (dist, hand, [float(xs[i]), float(ys[i])])
            j["weapon_grip"] = {"hand": best[1], "point": best[2], "from": os.path.basename(obj)}
    json.dump(j, open(fj, "w"))
    print("joints / grip:", j.get("weapon_grip"), flush=True)


def refine_leftover(hero, series, out):
    """See-through can't name some designs (freya's wide witch hat, staff and long train ended in 'leftover', 50-60%
    of her figure). A big leftover is cut up again with SAM2 on the plate: the piece above the face is the hat, the
    piece at the weapon grip is the weapon, what is left below the hips is the skirt (2026-10-01)"""
    import numpy as np
    parts_json = os.path.join(out, "parts.json")
    lo_file = os.path.join(out, "part_leftover.png")
    fj = os.path.join(L.out_dir(hero, series), "fig_joints.json")
    if not (os.path.exists(lo_file) and os.path.exists(fj)):
        return
    src = Image.open(os.path.join(L.src_dir(hero, series), "full.png")).convert("RGBA")
    fig = np.asarray(src)[..., 3] > 40
    lo_img = np.asarray(Image.open(lo_file)).copy()
    lo = lo_img[..., 3] > 128
    if lo.sum() < 0.08 * fig.sum():
        return
    j = json.load(open(fj))
    meta = json.load(open(parts_json))
    have = {p["name"] for p in meta["order_back_to_front"]}
    flat, _ = L.flat(src)
    fx, fy, fs = j["face"]
    taken = np.zeros_like(lo)
    new = []

    def add(name, mask):
        nonlocal taken
        mask = mask & lo & ~taken
        if mask.sum() < 0.01 * fig.sum():
            return
        taken |= mask
        arr = np.zeros_like(lo_img)
        arr[mask] = lo_img[mask]
        f = os.path.join(out, "part_%s.png" % name)
        if name in have and os.path.exists(f):   # add to the part the model already made
            old = np.asarray(Image.open(f)).copy()
            old[mask] = lo_img[mask]
            arr = old
        Image.fromarray(arr).save(f)
        if name not in have:
            new.append({"name": name, "file": "part_%s.png" % name, "depth": 0.0, "from": "leftover"})
        print("leftover -> %s: %d px" % (name, mask.sum()), flush=True)

    neg_face = [(fx, fy)]
    rows = np.arange(lo.shape[0])[:, None]
    cols = np.arange(lo.shape[1])[None, :]
    if "objects" not in have:
        # the weapon first (else the hat or the skirt take pieces of it): what a wide brush opening wipes out of the
        # leftover is its thin parts; the longest thin piece near a hand seeds SAM2 at its ends and middle
        import cv2
        k = max(9, int(0.45 * fs)) | 1   # wider than a staff (about 0.25 of a face)
        wide = cv2.morphologyEx(lo.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
        thin = (lo & ~wide).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(thin, connectivity=8)
        best = None
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if max(w, h) < 1.5 * fs or area < 300:
                continue
            my, mx = np.nonzero(lab == i)
            near = min(np.min(np.hypot(mx - wx, my - wy)) for wx, wy in (j["wrist_r"], j["wrist_l"]))
            if near < 1.2 * fs and (best is None or max(w, h) > best[0]):
                best = (max(w, h), mx, my)
        if not best:   # a thick weapon (rena's wrench) survives the brush: the long leftover pieces at a hand or a
            # shoulder (a wrench over the shoulders is cut in two by the body)
            n, lab, stats, _ = cv2.connectedComponentsWithStats(lo.astype(np.uint8), connectivity=8)
            anchors = [j[k] for k in ("wrist_r", "wrist_l", "shoulder_r", "shoulder_l") if j.get(k)]
            keep = np.zeros_like(lo)
            for i in range(1, n):
                x, y, w, h, area = stats[i]
                if max(w, h) < 1.5 * fs or area < 0.01 * fig.sum():
                    continue
                my, mx = np.nonzero(lab == i)
                if min(np.min(np.hypot(mx - ax, my - ay)) for ax, ay in anchors) < 1.2 * fs:
                    keep |= lab == i
            if keep.any():
                my, mx = np.nonzero(keep)
                best = (0, mx, my)
        if best:
            _, mx, my = best
            piece = np.zeros_like(lo)
            piece[my, mx] = True   # the thin piece itself (SAM2 from its points took the whole skirt with it)
            add("objects", cv2.dilate(piece.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
            hands = [("arm_r", j["wrist_r"]), ("arm_l", j["wrist_l"])]
            hand, wpt = min(hands, key=lambda h: np.min(np.hypot(mx - h[1][0], my - h[1][1])))
            i = int(np.argmin(np.hypot(mx - wpt[0], my - wpt[1])))
            j["weapon_grip"] = {"hand": hand, "point": [float(mx[i]), float(my[i])], "from": "leftover, thin piece"}
            json.dump(j, open(fj, "w"))
    band = lo & ~taken & (rows < fy - 0.2 * fs) & (np.abs(cols - fx) < 2.5 * fs)
    ys, xs = np.nonzero(band)
    hat_f = os.path.join(out, "part_headwear.png")
    small_hat = "headwear" not in have or (np.asarray(Image.open(hat_f))[..., 3] > 128).sum() < 0.03 * fig.sum()
    if len(xs) and small_hat:   # no hat, or only a scrap of it (a hat the model did find whole is left alone)
        # the hat: the leftover above the face (crown nearest the middle, brim at both ends)
        i = int(np.argmin(np.hypot(xs - fx, ys - (fy - 0.8 * fs))))
        pos = [(xs[i], ys[i]), (xs.min() + 3, ys[np.argmin(xs)]), (xs.max() - 3, ys[np.argmax(xs)])]
        add("headwear", L.sam2_mask(flat, pos, neg_face))
    hip_y = max(j["hip_l"][1], j["hip_r"][1]) if j.get("hip_l") and j.get("hip_r") else fy + 3 * fs
    rest = lo & ~taken & (np.arange(lo.shape[0])[:, None] > hip_y - 0.5 * fs)
    add("bottomwear", rest)
    left = lo & ~taken
    lo_img[~left, 3] = 0
    Image.fromarray(lo_img).save(lo_file)
    order = meta["order_back_to_front"]
    lo_i = next(i for i, p in enumerate(order) if p["name"] == "leftover")
    meta["order_back_to_front"] = order[:lo_i] + new + order[lo_i:]
    json.dump(meta, open(parts_json, "w"), indent=1)
    print("leftover now %.0f%% of the figure" % (100.0 * left.sum() / fig.sum()), flush=True)


def raw_layers(meta, src):
    """the model's own layers placed on the plate canvas, before the plate's colours go over them: {name: RGBA array}.
    A body layer here still has what the model painted behind an arm (the cloth under it), which the rig needs when
    the arm moves (rig_parts.py, 2026-10-01)"""
    import numpy as np
    inp = meta.get("input", {})
    crop = inp.get("crop") or (0, 0, src.width, src.height)
    res = inp.get("resolution", 1280)
    cw, ch = crop[2] - crop[0], crop[3] - crop[1]
    s = res / float(max(cw, ch))
    pad_x, pad_y = (res - cw * s) / 2.0, (res - ch * s) / 2.0
    out = {}
    for l in meta["layers"]:
        f = os.path.join(COMFY_OUT, l["filename"])
        if not os.path.exists(f):
            continue
        im = Image.open(f).convert("RGBA")
        w, h = max(1, round(im.width / s)), max(1, round(im.height / s))
        canvas = Image.new("RGBA", src.size, (0, 0, 0, 0))
        canvas.paste(im.resize((w, h), Image.LANCZOS), (round(crop[0] + (l["left"] - pad_x) / s), round(crop[1] + (l["top"] - pad_y) / s)))
        out[l["name"].replace(" ", "_")] = np.asarray(canvas).copy()
    return out


def crop_box(src):
    x0, y0, x1, y1 = src.split()[3].getbbox()
    m = int(0.04 * max(x1 - x0, y1 - y0))
    return (max(0, x0 - m), max(0, y0 - m), min(src.width, x1 + m), min(src.height, y1 + m))


def to_plate(meta, src, out, crop=None, res=None):
    """put every layer back on the plate's own canvas. The model fits its input into a res x res square (longer side
    = res, centred), so a layer box maps back exactly from the input crop (2026-09-30: fitting the union of the layer
    boxes to the figure went wrong as soon as the model invented a part, e.g. wings). Parts that mostly lie where the
    plate is empty are invented and dropped. Writes part_<name>.png (plate size) and parts.json (back to front)"""
    import numpy as np
    layers = meta["layers"]
    inp = meta.get("input", {})
    crop = crop or inp.get("crop") or (0, 0, src.width, src.height)
    res = res or inp.get("resolution", 1280)
    cw, ch = crop[2] - crop[0], crop[3] - crop[1]
    s = res / float(max(cw, ch))
    pad_x, pad_y = (res - cw * s) / 2.0, (res - ch * s) / 2.0
    plate_a = np.asarray(src.split()[3]) > 128
    import cv2
    near_fig = cv2.dilate((np.asarray(src.split()[3]) > 10).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0   # +2 px
    order = sorted(layers, key=lambda l: -l["depth_median"])   # far (large depth) first
    parts = []
    for l in order:
        f = os.path.join(COMFY_OUT, l["filename"])
        if not os.path.exists(f):
            continue
        im = Image.open(f).convert("RGBA")
        w, h = max(1, round(im.width / s)), max(1, round(im.height / s))
        canvas = Image.new("RGBA", src.size, (0, 0, 0, 0))
        canvas.paste(im.resize((w, h), Image.LANCZOS), (round(crop[0] + (l["left"] - pad_x) / s), round(crop[1] + (l["top"] - pad_y) / s)))
        a = np.asarray(canvas.split()[3]) > 128
        if a.sum() == 0 or (a & plate_a).sum() < 0.35 * a.sum():
            print("dropped %s: %d%% of it lies outside the figure" % (l["name"], 100 - 100 * (a & plate_a).sum() // max(1, a.sum())), flush=True)
            continue
        # nothing can hide outside the figure: whatever a part has there (a hank of hair beside the body, an arc
        # over the head) would always show, so it goes (live2d's rig check, 2026-10-01)
        ca = np.asarray(canvas).copy()
        ca[..., 3] = np.where(near_fig, ca[..., 3], 0)
        canvas = Image.fromarray(ca)
        name = l["name"].replace(" ", "_")
        canvas.save(os.path.join(out, "part_%s.png" % name))
        parts.append({"name": name, "file": "part_%s.png" % name, "depth": l["depth_median"]})
    plate = np.asarray(src).astype(np.float32)
    # front hair is drawn in front of everything, so it can't have hidden areas: where the model painted hair and the
    # plate shows something else (yukino's long hair painted over her whole hakama), the pixel is taken out of the
    # front hair; the part that really is there (or the leftover and its refinement) gets it (2026-10-01)
    names = [p["name"] for p in parts]
    if "front_hair" in names:
        fp = os.path.join(out, "part_front_hair.png")
        fh = np.asarray(Image.open(fp)).copy()
        wrong = (fh[..., 3] > 128) & (plate[..., 3] > 128) & (np.abs(fh[..., :3].astype(np.float32) - plate[..., :3]).sum(2) > 90)
        if wrong.sum() > 0.002 * (plate[..., 3] > 128).sum():
            fh[wrong, 3] = 0
            Image.fromarray(fh).save(fp)
            print("front hair: %d px that the plate shows as something else taken out" % wrong.sum(), flush=True)
    # the plate's own pixels win wherever a part is the one you see: the model's repaint is kept only where the
    # plate shows something else in front (hidden parts); anything the plate has that no part covers (a hair ribbon
    # the model dropped) becomes part_leftover.png on top
    covered = np.zeros(src.size[::-1], bool)
    for p in reversed(parts):   # front to back
        path = os.path.join(out, p["file"])
        arr = np.asarray(Image.open(path)).copy()
        # half-transparent edges too: a mouth layer's soft skin patch kept its own colour and hid the mouth
        vis = (arr[..., 3] > 0) & ~covered & (plate[..., 3] > 128)
        # the part is the one you'd see here, but the model painted something else than the plate shows: it isn't
        # really this part (back hair painted where the plate shows a hakama). Out of the part; the leftover and its
        # refinement take the pixel (2026-10-01)
        alien = vis & (arr[..., 3] > 128) & (np.abs(arr[..., :3].astype(np.float32) - plate[..., :3]).sum(2) > 150)
        if alien.any():   # only whole areas; thin line-art edges (the model's lines differ a little) stay
            import cv2
            n_, lab_, st_, _ = cv2.connectedComponentsWithStats(alien.astype(np.uint8), connectivity=8)
            big = np.zeros(n_, bool)
            big[1:] = st_[1:, cv2.CC_STAT_AREA] >= 0.005 * (plate[..., 3] > 128).sum()
            alien = big[lab_]
        if p["name"] not in ("face",) and alien.sum() > 0:
            arr[alien, 3] = 0
            vis &= ~alien
            print("%s: %d px the plate shows as something else taken out" % (p["name"], alien.sum()), flush=True)
        arr[vis, :3] = plate[vis, :3].astype(np.uint8)
        arr[vis, 3] = np.maximum(arr[vis, 3], plate[vis, 3].astype(np.uint8))
        if p["name"] in ("objects",):   # a held object keeps only its visible silhouette plus a small margin: the
            import cv2                  # model paints hidden bowstrings as thick bars across the body
            keep = cv2.dilate(vis.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
            arr[..., 3] = np.where(keep, arr[..., 3], 0)
        covered |= arr[..., 3] > 128
        Image.fromarray(arr).save(path)
    left = (plate[..., 3] > 128) & ~covered
    if left.sum() > 50:
        lo = np.asarray(src).copy()
        lo[..., 3] = np.where(left, lo[..., 3], 0)
        Image.fromarray(lo).save(os.path.join(out, "part_leftover.png"))
        parts.append({"name": "leftover", "file": "part_leftover.png", "depth": 0.0})
    json.dump({"size": list(src.size), "order_back_to_front": parts}, open(os.path.join(out, "parts.json"), "w"), indent=1)
    # a check picture: all parts stacked, next to the plate
    stack = Image.new("RGBA", src.size, (200, 200, 205, 255))
    for p in parts:
        stack.alpha_composite(Image.open(os.path.join(out, p["file"])))
    both = Image.new("RGBA", (src.width * 2, src.height), (200, 200, 205, 255))
    both.alpha_composite(src, (0, 0))
    both.alpha_composite(stack, (src.width, 0))
    both.convert("RGB").save(os.path.join(out, "_stack_vs_plate.jpg"), quality=85)
    d3 = np.abs(np.asarray(stack.convert("RGB")).astype(int) - np.asarray(Image.alpha_composite(
        Image.new("RGBA", src.size, (200, 200, 205, 255)), src).convert("RGB")).astype(int))
    figm = plate[..., 3] > 128   # over the figure only (the empty canvas around it hid gaps in the average)
    diff = d3[figm].mean()
    wrong = int((d3.sum(2) > 90)[figm].sum())
    print("parts on the plate canvas: %d, stacked in parts.json order: mean difference %.1f / 255 over the figure, "
          "%d figure px off" % (len(parts), diff, wrong), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("series")
    ap.add_argument("--res", type=int, default=1280)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--rebuild", action="store_true",
                    help="no ComfyUI: lay the saved split (st_layers.json) back on the plate again, as it was before "
                         "rig_parts.py or any fix touched the parts (their versions are overwritten)")
    a = ap.parse_args()
    if a.rebuild:
        out = os.path.join(L.WORK, "live", a.hero, a.series, "st")
        meta = json.load(open(os.path.join(out, "st_layers.json"), encoding="utf-8"))
        src = Image.open(os.path.join(L.src_dir(a.hero, a.series), "full.png")).convert("RGBA")
        crop = meta.get("input", {}).get("crop")
        to_plate(meta, src, out, tuple(crop) if crop else None, meta.get("input", {}).get("resolution"))
        fix_grip(a.hero, a.series, out)
        refine_leftover(a.hero, a.series, out)
        print("rebuilt ->", out, flush=True)
        sys.exit(0)
    out = decompose(a.hero, a.series, a.res, a.seed)
    names = [p["name"] for p in json.load(open(os.path.join(out, "parts.json")))["order_back_to_front"]]
    if "face" not in names:   # the model sometimes leaves the face out (it ends in the leftover layer): once more
        print("no face layer, trying another seed", flush=True)
        decompose(a.hero, a.series, a.res, a.seed + 7)
