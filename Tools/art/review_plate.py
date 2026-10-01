"""Review sheets for hero plates (2026-10-01): catch extra legs, a second weapon, a floating weapon before rigging.

    python Tools/art/review_plate.py <hero> [pose ...]      art_work/live/<hero>/pose_<pose>/review.jpg (+ review.json)
    python Tools/art/review_plate.py cand <hero> <action>   candidates of a key pose: art_work/poses/<hero>/<action>/review_<pose>.jpg

One sheet per plate, three panels: the plate, the plate with the skeleton it was drawn from (limbs or objects off the
skeleton are the drawing's mistakes), and the See-through split coloured by the owner's groups:
人物 (face and features, hair, neck and arms), 服裝 (hat, accessories, top, skirt, socks, shoes), 武器 (held objects),
其他物件 (what the model could not name). Counts that point at a mistake are written in red: more than one weapon piece,
more than two shoes or gloves, no face, a big leftover.
"""
import glob
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
import key_poses as K   # noqa: E402

WORK = K.WORK
GROUPS = [   # (group, colour, See-through layer names)
    ("五官", (255, 214, 102), ("face", "eyewhite-l", "eyewhite-r", "irides-l", "irides-r", "eyelash-l", "eyelash-r",
                              "eyebrow-l", "eyebrow-r", "nose", "mouth", "ears-l", "ears-r", "ears")),
    ("頭髮", (240, 120, 60), ("front_hair", "back_hair")),
    ("四肢", (255, 170, 190), ("neck", "handwear-l", "handwear-r", "handwear")),
    ("帽子", (150, 90, 220), ("headwear",)),
    ("飾品", (230, 80, 200), ("neckwear", "earwear", "eyewear", "accessories")),
    ("上衣", (70, 140, 255), ("topwear",)),
    ("裙子", (60, 200, 220), ("bottomwear",)),
    ("襪子", (120, 220, 120), ("legwear",)),
    ("鞋子", (40, 150, 60), ("footwear",)),
    ("武器", (255, 40, 40), ("objects",)),
    ("其他物件", (128, 128, 128), ("leftover", "tail", "wings")),
]


def _font(size):
    for f in ("msjh.ttc", "msjhbd.ttc", "mingliu.ttc"):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", f), size)
        except OSError:
            pass
    return ImageFont.load_default()


def pieces(mask, min_share):
    """separate pieces of a mask bigger than min_share of the figure"""
    import cv2
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return int(sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_share))


def skeleton_overlay(plate_rgba, pts):
    base = Image.new("RGBA", plate_rgba.size, (200, 200, 205, 255))
    base.alpha_composite(plate_rgba)
    sk = K.skeleton_image(pts).resize(plate_rgba.size).convert("RGBA")
    a = (np.asarray(sk.convert("L")) > 10).astype(np.uint8) * 200
    sk.putalpha(Image.fromarray(a))
    base.alpha_composite(sk)
    return base


def group_map(d, size):
    """colour picture of the split plus counts and warnings"""
    pj = os.path.join(d, "st", "parts.json")
    img = Image.new("RGBA", size, (30, 30, 34, 255))
    if not os.path.exists(pj):
        return img, {}, ["還沒拆圖層"]
    parts = json.load(open(pj))["order_back_to_front"]
    names = [p["name"] for p in parts]
    fig = np.asarray(Image.open(os.path.join(d, "full.png")).convert("RGBA"))[..., 3] > 40
    area = max(1, int(fig.sum()))
    arr = np.zeros((size[1], size[0], 4), np.uint8)
    masks = {}
    for p in parts:   # back to front, so the front part's colour wins
        m = np.asarray(Image.open(os.path.join(d, "st", p["file"])))[..., 3] > 128
        masks[p["name"]] = m
        colour = next((c for g, c, ns in GROUPS if p["name"] in ns), (255, 255, 255))
        arr[m] = colour + (255,)
    img.alpha_composite(Image.fromarray(arr))
    counts, warn = {}, []
    union = lambda ns: np.any([masks[n] for n in ns if n in masks], axis=0) if any(n in masks for n in ns) else None
    w = union(("objects",))
    if w is not None:   # a hand across a staff cuts it in two: close small gaps before counting
        import cv2
        w = cv2.dilate(w.astype(np.uint8), np.ones((31, 31), np.uint8)) > 0
    counts["武器塊數"] = pieces(w, 0.004 * area) if w is not None else 0
    if counts["武器塊數"] > 1:
        warn.append("武器分成 %d 塊（多一把？）" % counts["武器塊數"])
    for label, ns in (("鞋子", ("footwear",)), ("手套／手臂", ("handwear-l", "handwear-r", "handwear"))):
        m = union(ns)
        counts[label] = pieces(m, 0.002 * area) if m is not None else 0
        if counts[label] > 2:
            warn.append("%s有 %d 塊（多一隻腳或手？）" % (label, counts[label]))
    if "face" not in names:
        warn.append("沒有臉這一層（頭不能動）")
    plate = np.asarray(Image.open(os.path.join(d, "full.png")).convert("RGBA")).astype(int)
    fh = masks.get("front_hair")
    if fh is not None:   # front hair is drawn over the head: painted-in hair there hides goggles, eyes (live2d)
        arr_fh = np.asarray(Image.open(os.path.join(d, "st", "part_front_hair.png"))).astype(int)
        off = fh & fig & (np.abs(arr_fh[..., :3] - plate[..., :3]).sum(2) > 90)
        counts["前髮與原圖不同"] = int(off.sum())
        if off.sum() > 0.002 * area:
            warn.append("前髮有 %d 像素跟原圖不同（蓋住了什麼？）" % off.sum())
    feet = masks.get("footwear")
    if feet is not None and feet.any():   # the rig stands every pose on its lowest row: that must be the feet
        low_fig = int(np.nonzero(fig.any(axis=1))[0].max())
        low_feet = int(np.nonzero(feet.any(axis=1))[0].max())
        counts["腳底以下"] = low_fig - low_feet
        if low_fig - low_feet > 0.015 * fig.shape[0]:
            warn.append("有東西比腳底低 %d 像素（姿勢會被墊高）" % (low_fig - low_feet))
    stack = Image.new("RGBA", size, (0, 0, 0, 0))   # every part in parts.json order, against the plate
    for p in parts:
        stack.alpha_composite(Image.open(os.path.join(d, "st", p["file"])).convert("RGBA"))
    st = np.asarray(stack).astype(int)
    solid = plate[..., 3] > 128   # the plate's own soft edges don't count
    off = solid & ((st[..., 3] < 128) | (np.abs(st[..., :3] - plate[..., :3]).sum(2) > 90))
    counts["疊回與原圖不同"] = int(off.sum())
    if off.sum() > 0.005 * area:
        warn.append("圖層疊回去有 %d 像素跟原圖不同" % off.sum())
    lo = masks.get("leftover")
    counts["其他物件比例"] = round(100.0 * lo.sum() / area, 1) if lo is not None else 0.0
    if counts["其他物件比例"] > 8:
        warn.append("其他物件占 %.0f%%（有東西沒被認出來）" % counts["其他物件比例"])
    return img, counts, warn


def sheet(title, panels, lines, warn, out):
    w, h = panels[0].size
    s = 0.5 if h > 900 else 1.0
    pw, ph = int(w * s), int(h * s)
    legend_h = 150
    img = Image.new("RGB", (pw * len(panels), ph + legend_h), (24, 22, 30))
    for i, p in enumerate(panels):
        img.paste(p.convert("RGB").resize((pw, ph)), (i * pw, 0))
    dr = ImageDraw.Draw(img)
    f, fs = _font(20), _font(15)
    dr.text((8, ph + 6), title, fill=(255, 230, 140), font=f)
    x = 8
    for g, c, _ in GROUPS:   # legend
        dr.rectangle((x, ph + 36, x + 14, ph + 50), fill=c)
        dr.text((x + 18, ph + 34), g, fill=(230, 230, 230), font=fs)
        x += 30 + 16 * len(g)
    dr.text((8, ph + 62), "  ".join(lines), fill=(200, 200, 200), font=fs)
    dr.text((8, ph + 88), "  ".join(warn) if warn else "沒有發現問題", fill=(255, 90, 90) if warn else (120, 220, 120), font=f)
    img.save(out, quality=88)


def review_folder(hero, pose):
    d = os.path.join(WORK, "live", hero, "pose_%s" % pose)
    plate = Image.open(os.path.join(d, "full.png")).convert("RGBA")
    info = json.load(open(os.path.join(d, "pose.json"))) if os.path.exists(os.path.join(d, "pose.json")) else {}
    pts = K.POSES.get(info.get("action"), {}).get(info.get("pose") or pose)
    shown = Image.new("RGBA", plate.size, (200, 200, 205, 255))
    shown.alpha_composite(plate)
    panels = [shown, skeleton_overlay(plate, pts) if pts else shown]
    gm, counts, warn = group_map(d, plate.size)
    panels.append(gm)
    lines = ["%s %s" % (k, v) for k, v in counts.items()]
    out = os.path.join(d, "review.jpg")
    sheet("%s %s（種子 %s）" % (hero, pose, info.get("seed", "?")), panels, lines, warn, out)
    json.dump({"counts": counts, "warnings": warn}, open(os.path.join(d, "review.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(pose, "->", out, "|", "; ".join(warn) or "ok", flush=True)
    return warn


def review_candidates(hero, action):
    """before a pick: each candidate at full size with its skeleton over it (no split yet)"""
    d = os.path.join(WORK, "poses", hero, action)
    for pose, pts in K.POSES[action].items():
        files = sorted(glob.glob(os.path.join(d, "%s_[0-9]*.png" % pose)))
        if not files:
            continue
        panels = [skeleton_overlay(Image.open(f).convert("RGBA"), pts) for f in files]
        names = [os.path.basename(f)[:-4] for f in files]
        sheet("%s %s：候選（骨架疊在圖上）" % (hero, pose), panels, names, [], os.path.join(d, "review_%s.jpg" % pose))
        print(pose, "->", os.path.join(d, "review_%s.jpg" % pose), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "cand":
        review_candidates(sys.argv[2], sys.argv[3])
    else:
        hero = sys.argv[1]
        poses = sys.argv[2:] or [os.path.basename(p)[5:] for p in sorted(glob.glob(os.path.join(WORK, "live", hero, "pose_*")))]
        for p in poses:
            review_folder(hero, p)
