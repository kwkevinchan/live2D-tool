"""Live 2D sources for a heroine outfit (art studio, tab "Live 2D"). Needs the local ComfyUI server.

    python Tools/art/live_layers.py parts   <hero> <series>     the standing figure cut into parts by its skeleton
    python Tools/art/live_layers.py joints  <hero> <series>     fig_joints.jpg: the joints of fig_joints.json on the plate, named
    python Tools/art/live_layers.py mouths  <hero> <series>     mouth shapes for talking (inpaint of the mouth only)
    python Tools/art/live_layers.py scene   <hero> <series> [n] the scene: character cut out and cut into parts, the
                                                                background painted in behind her and split into n depth layers
    python Tools/art/live_layers.py preview <hero> <series>     animated previews: preview_figure.gif, preview_scene.gif

Parts (2026-09-29, owner: "let the limbs and the face move"): the DWPose skeleton gives shoulders, elbows, wrists,
hips, knees, ankles and the face; SAM2 cuts hair, face, both arms and both legs from those points, the torso is the
rest, and what the arms hide on the torso is painted in so an arm can swing without leaving a hole. The preview turns
each part around its joint (arms at the shoulders, legs at the hips, the head at the neck), with blinks, the mouth
shapes, breathing, hair sway, parallax and falling leaves. The real animation will be rigged in Inochi2D (Docs/Design/22);
these parts are its source art.

Reads the plates (live2d.toml [paths] plates: <plates>/<hero>[/skins/<series>]/full.png, full_blink.png, scene.jpg) and writes
into <work>/live/<hero>/<series>/ (live2d.toml [paths] work, or ART_WORK).
"""
import glob
import json
import math
import os
import random
import sys
import time
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
import comfy_gen as cg      # noqa: E402
import heroine_j3 as j3     # noqa: E402
import workflows as W       # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
import config as _C   # live2d.toml
WORK = _C.WORK
COMFY_OUT = _C.COMFY_OUT
GREY = (200, 200, 205)
PARTS = ("leg_l", "leg_r", "torso", "weapon", "arm_l", "arm_r", "hair", "face")   # drawing order, back to front
MOUTHS = {   # name: (prompt, negative) — the mouth shapes a talking animation cycles through
    "mouth_closed": ("(closed mouth:1.3), light smile", ", open mouth, teeth"),
    "mouth_a": ("(wide open mouth:1.5), :o, surprised", ", closed mouth, smile"),
    "mouth_i": ("(open mouth:1.3), (grin:1.3), showing teeth, clenched teeth", ", closed mouth"),
    "mouth_o": ("(small round open mouth:1.4), :o, pout", ", closed mouth, smile, teeth"),
}


def src_dir(hero, series):
    if series.startswith("pose_"):   # key-pose plates (Tools/art/key_poses.py) live in their own work folder
        return os.path.join(WORK, "live", hero, series)
    return _C.plate_dir(hero, series)   # live2d.toml [paths] plates


def outfit_of(series):
    """the outfit a folder shows: key poses are drawn in the main design"""
    return "-" if series.startswith("pose_") else series


def face_of(plate):
    """(box, (cx, cy, h)) like heroine_j3.face_box; side views the anime face finder misses fall back to the
    skeleton (nose, eyes, neck)"""
    try:
        return j3.face_box(plate)
    except RuntimeError:
        k = skeleton(plate)
        if 0 not in k:
            raise
        eyes = [k[i] for i in (14, 15) if i in k]
        cx = (k[0][0] + sum(e[0] for e in eyes)) / (1 + len(eyes))
        cy = (k[0][1] + sum(e[1] for e in eyes)) / (1 + len(eyes))
        hh = max(40.0, abs(k[1][1] - k[0][1]) * 1.2) if 1 in k else plate.height * 0.1
        side = int(max(192, hh * 2.4))
        x0 = int(np.clip(cx - side / 2, 0, plate.width - side))
        y0 = int(np.clip(cy - side * 0.5, 0, plate.height - side))
        return (x0, y0, x0 + side, y0 + side), (cx, cy, hh)


def out_dir(hero, series):
    d = os.path.join(WORK, "live", hero, series)
    os.makedirs(d, exist_ok=True)
    return d


def flat(rgba):
    """RGBA figure on a flat grey plate (what the models expect), plus its alpha"""
    bg = Image.new("RGB", rgba.size, GREY)
    bg.paste(rgba, (0, 0), rgba)
    return bg, rgba.split()[3]


def _tmp(img):
    p = os.path.join(os.environ.get("TEMP", "."), "live_%s.png" % uuid.uuid4().hex[:8])
    img.save(p)
    return p


# ------------------------------------------------------------------ ComfyUI helpers
def sam2_mask(img, pos, neg):
    pts = lambda ps: json.dumps([{"x": int(x), "y": int(y)} for x, y in ps])
    wf = W.fill(W.load("sam2"), {"輸入圖": {"image": cg.upload(_tmp(img))},
                                 "分割": {"coordinates_positive": pts(pos), "coordinates_negative": pts(neg)}})
    return np.asarray(j3.run_wf(wf).convert("L").resize(img.size)) > 128


def skeleton(img):
    """COCO-18 body keypoints in picture pixels: {index: (x, y)} for the confident ones. The person finder misses
    some anime figures; then the whole picture is taken as the person"""
    try:
        return _skeleton(img, None)
    except RuntimeError:
        return _skeleton(img, "None")


def _skeleton(img, bbox):
    prefix = "art_pose_" + uuid.uuid4().hex[:8]
    wf = W.fill(W.load("pose"), {"輸入圖": {"image": cg.upload(_tmp(img))}, "存關節": {"filename_prefix": prefix}})
    if bbox:
        W.fill(wf, {"骨架": {"bbox_detector": bbox}})
    pid = cg.post("/prompt", {"prompt": wf, "client_id": "live"})["prompt_id"]
    while pid not in json.loads(cg.get("/history/%s" % pid)):
        time.sleep(1)
    f = sorted(glob.glob(os.path.join(COMFY_OUT, prefix + "*.json")))
    if not f:
        raise RuntimeError("no skeleton found")
    data = json.load(open(f[-1]))[0]
    people = data.get("people") or []
    if not people:
        raise RuntimeError("no person found by the skeleton detector")
    kp = people[0]["pose_keypoints_2d"]
    w, h = data["canvas_width"], data["canvas_height"]
    sx, sy = img.width / w, img.height / h
    norm = max(kp[0::3] + [0]) <= 1.5   # some versions give 0..1 coordinates
    out = {}
    for i in range(18):
        x, y, c = kp[3 * i: 3 * i + 3]
        if c > 0.3:
            out[i] = (x * img.width, y * img.height) if norm else (x * sx, y * sy)
    return out


def inpaint(img, mask, pos, neg, seed=5, denoise=0.95):
    """repaint the masked area of img (PIL RGB, mask bool array) with the current checkpoint"""
    m = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(4))
    out = j3.img2img(img, pos, neg, seed, denoise, mask=m)
    return Image.composite(out.resize(img.size), img, m)


# ------------------------------------------------------------------ cutting a figure into parts
def clean_mask(m, min_px=400):
    """largest connected piece plus any piece bigger than min_px, holes filled, edges smoothed"""
    import cv2
    u = m.astype(np.uint8) * 255
    u = cv2.morphologyEx(u, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    u = cv2.morphologyEx(u, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(u, 8)
    if n <= 1:
        return u > 0
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    keep = np.zeros(u.shape, bool)
    for i in range(1, n):
        if i == big or stats[i, cv2.CC_STAT_AREA] >= min_px:
            keep |= lab == i
    filled = keep.astype(np.uint8) * 255
    cnts, _ = cv2.findContours(filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(filled, cnts, -1, 255, -1)
    return filled > 0


def _mid(a, b, t=0.5):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def split_figure(rgba, pos_prompt, d, tag):
    """rgba: the figure (transparent elsewhere). Writes <tag>_<part>.png, <tag>_overview.png, returns joints"""
    plate, alpha = flat(rgba)
    a = np.asarray(alpha) > 128
    k = skeleton(plate)
    inside = lambda ps: [(x, y) for x, y in ps if 0 <= int(y) < a.shape[0] and 0 <= int(x) < a.shape[1] and a[int(y), int(x)]]
    have = lambda *ix: all(i in k for i in ix)
    masks = {}
    # face and hair from the face box (anime cascade), as before; fall back to the skeleton's nose
    _, (cx, cy, hh) = face_of(plate)
    body_pt = inside([_mid(k[1], k[8] if 8 in k else k[1], 0.5)]) if 1 in k else inside([(cx, cy + 2.5 * hh)])
    face_pts = inside([(cx, cy), (cx, cy + 0.2 * hh)])
    hair_pts = inside([(cx, cy - 0.75 * hh), (cx - 0.55 * hh, cy - 0.3 * hh), (cx + 0.55 * hh, cy - 0.3 * hh),
                       (cx - 0.7 * hh, cy + 0.4 * hh), (cx + 0.7 * hh, cy + 0.4 * hh)])
    masks["face"] = sam2_mask(plate, face_pts, hair_pts[:1] + body_pt) & a
    masks["hair"] = sam2_mask(plate, hair_pts, face_pts + body_pt) & a
    others = face_pts + body_pt
    for side, (s, e, w) in {"r": (2, 3, 4), "l": (5, 6, 7)}.items():
        if have(s, e, w):   # upper arm and forearm + hand separately (one call stopped at the elbow: the glove stayed behind)
            hand = (k[w][0] + 0.3 * (k[w][0] - k[e][0]), k[w][1] + 0.3 * (k[w][1] - k[e][1]))
            upper = inside([_mid(k[s], k[e], 0.6), k[e]])
            lower = inside([_mid(k[e], k[w]), k[w], hand])
            m = np.zeros_like(a)
            for pts in (upper, lower):
                if pts:
                    m |= sam2_mask(plate, pts, others)
            if m.any():
                masks["arm_" + side] = m & a
    for side, (hp, kn, an) in {"r": (8, 9, 10), "l": (11, 12, 13)}.items():
        if have(hp, kn):
            pts = inside([_mid(k[hp], k[kn], 0.6), k[kn]] + ([_mid(k[kn], k[an]), k[an]] if an in k else []))
            if pts:
                masks["leg_" + side] = sam2_mask(plate, pts, others) & a
    # the torso proper (chest to hips); whatever big piece is left over is something held: the weapon
    core_pts = inside([_mid(k[1], k[8] if 8 in k else k[1], t) for t in (0.3, 0.6, 0.9)] if 1 in k else body_pt)
    hands = [k[i] for i in (4, 7) if i in k]
    core = sam2_mask(plate, core_pts, face_pts + hands) & a if core_pts else np.zeros_like(a)
    for name in list(masks):   # SAM2 masks come speckled: keep the main piece, fill its holes
        masks[name] = clean_mask(masks[name]) & a
    legs = np.zeros_like(a)
    for n in ("leg_r", "leg_l"):
        if n in masks:
            legs |= masks[n]
    for n in ("arm_r", "arm_l"):   # arms own their outline too (but never grow into the legs)
        if n in masks:
            masks[n] = ((np.asarray(Image.fromarray(masks[n].astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(7))) > 0) & a & ~legs) | masks[n]
    held = a & ~core
    for n in masks:
        held &= ~masks[n]
    # only what reaches well outside the body counts as held (cape and skirt stay on the torso): the body grown by
    # half a head height is the envelope, the weapon is the leftover outside it plus what joins it
    body = core.copy()
    for n in masks:
        body |= masks[n]
    import cv2
    r = max(15, int(0.5 * hh))
    env = cv2.dilate(body.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
    outer = clean_mask(held & ~env, int(a.sum() * 0.005)) if (held & ~env).any() else np.zeros_like(a)
    held = np.zeros_like(a)
    if outer.any():   # the weapon's own mask: SAM2 from points on the part outside the body, never the body or legs
        ys, xs = np.nonzero(outer)
        pick = np.linspace(0, len(xs) - 1, 5).astype(int)
        wpos = [(xs[i], ys[i]) for i in pick]
        wneg = inside([_mid(k[8], k[9]) if have(8, 9) else (0, 0), _mid(k[11], k[12]) if have(11, 12) else (0, 0)]) + core_pts[:2]
        held = sam2_mask(plate, wpos, wneg) & a & ~core & ~legs
        held = clean_mask(held | outer, int(a.sum() * 0.005)) & ~legs
    grip = None
    if held.sum() > a.sum() * 0.02 and hands:
        ys, xs = np.nonzero(held)
        pts = np.stack([xs, ys], 1)
        dist = [(np.min(np.hypot(pts[:, 0] - hx, pts[:, 1] - hy)), i) for i, (hx, hy) in zip((4, 7), [k.get(4, (1e9, 1e9)), k.get(7, (1e9, 1e9))])]
        dmin, wi = min(dist)
        if dmin < 0.6 * hh * 2:
            masks["weapon"] = held
            grip = {"hand": "arm_r" if wi == 4 else "arm_l", "point": list(k[wi])}
    # one owner per pixel, front parts first; the torso is what is left
    taken = np.zeros_like(a)
    for name in ("face", "hair", "arm_r", "arm_l", "weapon", "leg_r", "leg_l"):
        if name in masks:
            masks[name] = masks[name] & ~taken
            taken |= masks[name]
    masks["torso"] = a & ~taken
    arr = np.asarray(rgba).copy()
    # paint in the torso behind the arms, so a swinging arm leaves no hole
    torso_img = plate
    limbs = np.zeros_like(a)
    for n in ("arm_r", "arm_l"):   # legs are left out: painting behind them made a second, grey leg (2026-09-30)
        if n in masks:
            limbs |= masks[n]
    near = np.asarray(Image.fromarray(masks["torso"].astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(41))) > 0
    fill = limbs & near   # what the arms hide on the body, painted in so a swinging arm leaves no hole
    if fill.sum() > 200:
        torso_img = inpaint(plate, fill, pos_prompt + ", arms at sides", ", arms")
    # arms reach a little into the body, so their joints stay covered while they turn (legs stay put: an overlap
    # there showed as a straight seam on the thighs)
    for n in ("arm_r", "arm_l"):
        if n in masks:
            grown = np.asarray(Image.fromarray(masks[n].astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))) > 0
            masks[n] = masks[n] | (grown & masks["torso"])
    for name in PARTS:
        if name not in masks:
            continue
        m = masks[name] | (fill if name == "torso" else False)
        src = np.asarray(torso_img.convert("RGBA")) if name == "torso" else arr
        layer = src.copy()
        layer[..., 3] = np.where(m, np.maximum(arr[..., 3], 255 * (name == "torso") * fill.astype(np.uint8)), 0)
        Image.fromarray(layer).save(os.path.join(d, "%s_%s.png" % (tag, name)))
    over = np.asarray(plate).astype(float)
    colours = {"face": (90, 220, 120), "hair": (80, 140, 255), "arm_r": (255, 200, 60), "arm_l": (255, 150, 40),
               "leg_r": (200, 90, 255), "leg_l": (150, 60, 220), "torso": (255, 110, 110), "weapon": (60, 220, 230)}
    for name, m in masks.items():
        over[m] = over[m] * 0.5 + np.array(colours[name]) * 0.5
    ov = Image.fromarray(over.astype(np.uint8))
    dr = ImageDraw.Draw(ov)
    for x, y in k.values():
        dr.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(255, 255, 255))
    ov.save(os.path.join(d, "%s_overview.png" % tag))
    joints = {"shoulder_r": k.get(2), "shoulder_l": k.get(5), "elbow_r": k.get(3), "elbow_l": k.get(6), "wrist_r": k.get(4),
              "wrist_l": k.get(7), "hip_r": k.get(8), "hip_l": k.get(11), "neck": k.get(1),
              "knee_r": k.get(9), "ankle_r": k.get(10), "knee_l": k.get(12), "ankle_l": k.get(13),   # the leg pieces
              "face": [cx, cy, hh], "weapon_grip": grip, "parts": [n for n in PARTS if n in masks]}
    json.dump(joints, open(os.path.join(d, "%s_joints.json" % tag), "w"))
    return joints


def parts(hero, series):
    src = Image.open(os.path.join(src_dir(hero, series), "full.png")).convert("RGBA")
    d = out_dir(hero, series)
    j = split_figure(src, j3.prompt_for(hero, outfit_of(series), "full body, standing"), d, "fig")
    legacy_layers(d, j, src)
    eye_patch(hero, series, d, src)
    print("parts ->", d, flush=True)


def joints_view(hero, series):
    """fig_joints.jpg: the plate with the joints of fig_joints.json as they are now, named (fig_overview.png keeps the
    detected ones; after a hand correction this is the picture to check)"""
    d = out_dir(hero, series)
    j = json.load(open(os.path.join(d, "fig_joints.json")))
    src = Image.open(os.path.join(src_dir(hero, series), "full.png")).convert("RGBA")
    im = Image.new("RGBA", src.size, (200, 200, 206, 255))
    im.alpha_composite(src)
    im = im.convert("RGB")
    dr = ImageDraw.Draw(im)
    for n, v in j.items():
        if n in ("face", "parts") or not isinstance(v, list) or len(v) < 2:
            continue
        x, y = v[0], v[1]
        dr.ellipse((x - 7, y - 7, x + 7, y + 7), outline=(255, 0, 255), width=3)
        dr.text((x + 9, y - 7), n, fill=(255, 0, 255))
    g = (j.get("weapon_grip") or {}).get("point")
    if g:
        dr.rectangle((g[0] - 9, g[1] - 9, g[0] + 9, g[1] + 9), outline=(0, 160, 255), width=3)
    missing = [n for n, v in j.items() if v is None]
    if missing:
        dr.text((8, 8), "missing: " + ", ".join(missing), fill=(255, 0, 0))
    im.save(os.path.join(d, "fig_joints.jpg"), quality=90)
    print("joints ->", os.path.join(d, "fig_joints.jpg"), "missing:", missing or "none", flush=True)


def legacy_layers(d, joints, src):
    """layer_hair / layer_face / layer_body.png: the three-layer set Tools/art/inx_rig.py (branch live2d, the Inochi2D
    auto-rig) reads; body = torso + arms + legs"""
    size = src.size
    body = Image.new("RGBA", size, (0, 0, 0, 0))
    for n in ("leg_l", "leg_r", "torso", "weapon", "arm_l", "arm_r"):
        p = os.path.join(d, "fig_%s.png" % n)
        if os.path.exists(p):
            body.alpha_composite(Image.open(p).convert("RGBA"))
    body.save(os.path.join(d, "layer_body.png"))
    for n in ("hair", "face"):
        p = os.path.join(d, "fig_%s.png" % n)
        if os.path.exists(p):
            Image.open(p).save(os.path.join(d, "layer_%s.png" % n))


def eye_patch(hero, series, d, src):
    """eyes_closed.png: only the pixels where full_blink.png differs from full.png (the closed eyes), plus eyes.json"""
    bp = os.path.join(src_dir(hero, series), "full_blink.png")
    if not os.path.exists(bp):
        return
    a = np.asarray(src).astype(int)
    b = np.asarray(Image.open(bp).convert("RGBA")).astype(int)
    diff = np.abs(a[..., :3] - b[..., :3]).sum(-1) > 30
    diff = clean_mask(diff, 40)
    diff = np.asarray(Image.fromarray(diff.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))) > 0
    patch = b.astype(np.uint8).copy()
    patch[..., 3] = np.where(diff, b[..., 3], 0).astype(np.uint8)
    Image.fromarray(patch).save(os.path.join(d, "eyes_closed.png"))
    ys, xs = np.nonzero(diff)
    if len(xs):
        json.dump({"eye_box": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]}, open(os.path.join(d, "eyes.json"), "w"))


# ------------------------------------------------------------------ mouths (inpaint)
def mouths(hero, series, seed=301):
    src = Image.open(os.path.join(src_dir(hero, series), "full.png")).convert("RGBA")
    plate, alpha = flat(src)
    box, (cx, cy, hh) = face_of(plate)
    side = box[2] - box[0]
    kk = 768.0 / side
    crop = plate.crop(box).resize((768, 768), Image.LANCZOS)
    mc = ((cx - box[0]) * kk, (cy + 0.3 * hh - box[1]) * kk)   # the mouth sits in the lower third of the face
    m = j3._ellipse_mask((768, 768), mc, (0.26 * hh * kk, 0.17 * hh * kk), 6)
    pos = j3.prompt_for(hero, outfit_of(series), "portrait, face focus")
    d = out_dir(hero, series)
    for i, (name, (extra, neg)) in enumerate(MOUTHS.items()):
        out = j3.img2img(crop, pos + ", " + extra, neg, seed + i, 0.92, mask=m)
        out = Image.composite(out, crop, m).resize((side, side), Image.LANCZOS)
        res = plate.copy()
        res.paste(out, box[:2], m.resize((side, side), Image.LANCZOS))
        res = res.convert("RGBA")
        res.putalpha(alpha)
        res.save(os.path.join(d, "%s.png" % name))
        print(name, "done", flush=True)
    json.dump({"face": [cx, cy, hh], "mouth_box": [int(cx - 0.35 * hh), int(cy + 0.08 * hh), int(cx + 0.35 * hh), int(cy + 0.55 * hh)]},
              open(os.path.join(d, "mouth.json"), "w"))
    print("mouths ->", d, flush=True)


# ------------------------------------------------------------------ the scene: character, clean background, depth layers
def scene(hero, series, n=4):
    import cv2
    import cutout as hp
    img = Image.open(os.path.join(src_dir(hero, series), "scene.jpg")).convert("RGB")
    d = out_dir(hero, series)
    _, alpha, rgba = hp.cutout(img)   # the character (and what she holds) as one piece
    alpha = np.asarray(alpha)
    ch = np.asarray(rgba).copy()
    ch[..., 3] = alpha
    Image.fromarray(ch).save(os.path.join(d, "scene_char.png"))
    print("character cut out", flush=True)
    _, bg_desc, _ = j3.OUTFITS[hero][series]
    bg = inpaint(img, alpha > 40, "scenery, %s, no humans, detailed background" % bg_desc, ", 1girl, person, human", seed=11, denoise=1.0)
    bg.save(os.path.join(d, "scene_bg.png"))
    print("background painted in behind her", flush=True)
    wf = W.fill(W.load("depth"), {"輸入圖": {"image": cg.upload(_tmp(bg))}})
    dep = np.asarray(j3.run_wf(wf).convert("L").resize(bg.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(3))).astype(float)
    Image.fromarray(dep.astype(np.uint8)).save(os.path.join(d, "depth.png"))
    edges = np.quantile(dep, np.linspace(0, 1, n + 1))
    rgb = np.asarray(bg)
    covered = np.zeros(dep.shape, bool)
    for i in range(n - 1, -1, -1):   # nearest first; farther layers are painted in where nearer ones cover them
        band = (dep >= edges[i]) & (dep <= edges[i + 1] + (1 if i == n - 1 else 0))
        if i == 0:
            fillm = covered.astype(np.uint8) * 255
            layer = np.dstack([cv2.inpaint(rgb, fillm, 15, cv2.INPAINT_TELEA) if covered.any() else rgb, np.full(dep.shape, 255, np.uint8)])
        else:
            soft = np.asarray(Image.fromarray(band.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(2)))
            fillm = (covered & ~band).astype(np.uint8) * 255
            base = cv2.inpaint(rgb, fillm, 9, cv2.INPAINT_TELEA) if fillm.any() else rgb
            layer = np.dstack([base, soft])
        Image.fromarray(layer).save(os.path.join(d, "scene_layer%d.png" % i))
        covered |= band
    json.dump({"layers": n}, open(os.path.join(d, "scene_layers.json"), "w"))
    print("background in %d depth layers" % n, flush=True)
    split_figure(Image.fromarray(ch), j3.prompt_for(hero, outfit_of(series), "sitting"), d, "sc")
    print("scene ->", d, flush=True)


# ------------------------------------------------------------------ previews
def _rot(img, deg, center):
    return img.rotate(deg, resample=Image.BICUBIC, center=center) if center else img


def animate_figure(d, tag, size, t, blink=None, mouth=None, info=None):
    """one frame of a figure cut into parts: each part turns around its joint"""
    j = json.load(open(os.path.join(d, "%s_joints.json" % tag)))
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    s = math.sin(t * 2 * math.pi)
    lay = {n: Image.open(os.path.join(d, "%s_%s.png" % (tag, n))).convert("RGBA") for n in j["parts"]}
    breath = int(-2 * s)
    neck = j.get("neck")
    for n in PARTS:
        if n not in lay:
            continue
        im = lay[n]
        if n in ("face", "hair"):
            if n == "face" and blink is not None:   # blink / mouth frames replace the face pixels
                im = Image.composite(blink, Image.new("RGBA", size), im.split()[3].point(lambda v: 255 if v > 0 else 0))
            if n == "face" and mouth is not None and info:
                mb = info["mouth_box"]
                im = im.copy()
                im.paste(mouth.crop(mb), mb[:2], mouth.crop(mb))
            deg = 2.0 * math.sin(t * 2 * math.pi + 0.6)
            if n == "hair":
                deg += 1.2 * math.sin(t * 4 * math.pi)
            im = _rot(im, deg, neck)
        elif n.startswith("arm") or n == "weapon":
            arm = (j.get("weapon_grip") or {}).get("hand", "arm_r") if n == "weapon" else n
            sh = j.get("shoulder_" + arm[-1])
            im = _rot(im, (5.0 if arm.endswith("r") else -5.0) * math.sin(t * 2 * math.pi + (0 if arm.endswith("r") else math.pi)), sh)
        elif n.startswith("leg"):
            hip = j.get("hip_" + n[-1])
            im = _rot(im, 1.5 * math.sin(t * 2 * math.pi + (0 if n.endswith("r") else math.pi)), hip)
        canvas.alpha_composite(im, (0, breath if n not in ("leg_l", "leg_r") else 0))
    return canvas


def preview(hero, series):
    d = out_dir(hero, series)
    sd = src_dir(hero, series)
    info = json.load(open(os.path.join(d, "mouth.json"))) if os.path.exists(os.path.join(d, "mouth.json")) else None
    mouths_im = [Image.open(os.path.join(d, n + ".png")).convert("RGBA") for n in MOUTHS if os.path.exists(os.path.join(d, n + ".png"))]
    blink = Image.open(os.path.join(sd, "full_blink.png")).convert("RGBA") if os.path.exists(os.path.join(sd, "full_blink.png")) else None
    N = 60
    if os.path.exists(os.path.join(d, "fig_joints.json")):
        full = Image.open(os.path.join(sd, "full.png"))
        W_, H_ = full.size
        frames = []
        for f in range(N):
            t = f / N
            b = blink if f in (24, 25, 26) else None
            m = mouths_im[(f // 3) % len(mouths_im)] if mouths_im and 36 <= f < 54 else None
            fr = animate_figure(d, "fig", (W_, H_), t, b, m, info)
            bg = Image.new("RGBA", (W_, H_), GREY + (255,))
            bg.alpha_composite(fr)
            frames.append(bg.convert("RGB").resize((int(W_ * 520 / H_), 520), Image.LANCZOS))
        frames[0].save(os.path.join(d, "preview_figure.gif"), save_all=True, append_images=frames[1:], duration=60, loop=0)
    if os.path.exists(os.path.join(d, "scene_layers.json")):
        n = json.load(open(os.path.join(d, "scene_layers.json")))["layers"]
        layers = [Image.open(os.path.join(d, "scene_layer%d.png" % i)).convert("RGBA") for i in range(n)]
        sw, sh = layers[0].size
        rnd = random.Random(7)
        leaves = [[rnd.uniform(0, sw), rnd.uniform(-sh, sh), rnd.uniform(3, 7), rnd.uniform(0, 6.28)] for _ in range(26)]
        frames = []
        for f in range(N):
            t = f / N
            s = math.sin(t * 2 * math.pi)
            c = Image.new("RGBA", (sw, sh))
            for i, lay in enumerate(layers):   # nearer layers move more
                big = lay.resize((int(sw * 1.06), int(sh * 1.06)), Image.BILINEAR)
                c.alpha_composite(big, (int(-sw * 0.03 + s * 4 * (i + 1)), int(-sh * 0.03)))
            if os.path.exists(os.path.join(d, "sc_joints.json")):
                c.alpha_composite(animate_figure(d, "sc", (sw, sh), t), (int(s * 4 * (n + 1)), 0))
            else:
                c.alpha_composite(Image.open(os.path.join(d, "scene_char.png")).convert("RGBA"), (int(s * 4 * (n + 1)), 0))
            dr = ImageDraw.Draw(c)
            for lf in leaves:   # falling leaves in front of everything
                x = lf[0] + 18 * math.sin(t * 6.28 * 2 + lf[3])
                y = (lf[1] + t * sh * 1.2) % (sh + 40) - 20
                dr.ellipse((x - lf[2], y - lf[2] / 2, x + lf[2], y + lf[2] / 2), fill=(170, 200, 90, 220))
            frames.append(c.convert("RGB").resize((sw // 2, sh // 2), Image.LANCZOS))
        frames[0].save(os.path.join(d, "preview_scene.gif"), save_all=True, append_images=frames[1:], duration=60, loop=0)
    print("previews ->", d, flush=True)


if __name__ == "__main__":
    cmd, hero, series = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == "scene":
        scene(hero, series, int(sys.argv[4]) if len(sys.argv) > 4 else 4)
    else:
        {"parts": parts, "mouths": mouths, "preview": preview, "joints": joints_view}[cmd](hero, series)
