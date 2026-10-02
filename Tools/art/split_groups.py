"""The See-through split in six packs, checked twice (the owner's order, 2026-10-01): 1 face (features, face
accessories, the hat, the neck; the collar is looked at here but stays in the top), 2 hair, 3 clothes, 4 limbs,
5 weapon, 6 other. See-through gives every layer in one run; this sorts them, then

  check 1, the parts: one sheet per pack, every part on its own, to be looked at: does each part look like what its
           name says, is its outline whole? Hints: empty parts, parts off the figure, left / right pairs that don't
           match (size, colour), required parts missing, half pairs;
  check 2, the assembly: the packs stacked one after another in parts.json order (face, + hair, + clothes, ...),
           to look at; the last stack is also compared with the plate, for reference only (the owner: whole parts
           come first, then how packs and the whole assemble, then motion; matching the plate is not the goal).

    python Tools/art/split_groups.py <hero> <series>        series: an outfit ("-", "A" ...) or a key-pose folder

Writes <work>/live/<hero>/<series>/st/groups/: <n>_<pack>/ (the pack's part images), parts_<n>.jpg (check 1),
assemble_<n>.jpg (check 2), groups.json (what went where, the checks' numbers and warnings). Read by the Live 2D
studio's folder tab. Docs/Design/22b step 2.
"""
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inx_rig import WORK, load_joints, src_dir   # noqa: E402

import part_names as P   # noqa: E402   every layer name: its pack, required, pairs (Tools/art/part_names.py)

PACKS = P.PACKS
REQUIRED = [(g, what, [kind]) for g, what, kind in P.required()]   # [pack, name shown, kinds that satisfy it]
PAIRS = P.pairs()   # left / right pairs: both must be there, a hidden one painted in (a big motion shows it otherwise)
PAIR_AREA = 2.0       # left / right parts this many times apart in size, or
PAIR_COLOR = 45       # this far apart in mean colour (sum of RGB), are not a matching pair
TILE = 220


def pack_of(name):
    return P.pack_of(name)


def checker(w, h, c=16):
    y, x = np.mgrid[0:h, 0:w]
    v = np.where(((x // c) + (y // c)) % 2 == 0, 200, 170).astype(np.uint8)
    return Image.fromarray(np.dstack([v, v, v, np.full_like(v, 255)]), "RGBA")


def label(img, text, color=(255, 255, 255)):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, 18], fill=(0, 0, 0))
    d.text((4, 3), text, fill=color)


def main(hero, series):
    ld = os.path.join(WORK, "live", hero, series)
    st = os.path.join(ld, "st")
    meta = json.load(open(os.path.join(st, "parts.json")))
    order = [q["name"] for q in meta["order_back_to_front"] if os.path.exists(os.path.join(st, "part_%s.png" % q["name"]))]
    sd = ld if os.path.exists(os.path.join(ld, "full.png")) else src_dir(hero, series)
    plate = Image.open(os.path.join(sd, "full.png")).convert("RGBA")
    pa = np.asarray(plate)
    fig = pa[..., 3] > 128
    joints = load_joints(os.path.join(ld, "fig_joints.json")) if os.path.exists(os.path.join(ld, "fig_joints.json")) else {}
    neck_y = int(joints["neck"][1]) if joints.get("neck") else None
    pivots = meta.get("pivots") or {}

    # the images of every part; "leftover" splits at the neck: what sits on the head (a ribbon) goes with the face
    imgs = {n: np.asarray(Image.open(os.path.join(st, "part_%s.png" % n)).convert("RGBA")) for n in order}
    packs = {n: pack_of(n) for n in order}
    if "leftover" in imgs and neck_y:
        top, low = imgs["leftover"].copy(), imgs["leftover"].copy()
        top[neck_y:, :, 3] = 0
        low[:neck_y, :, 3] = 0
        i = order.index("leftover")
        order[i:i + 1] = ["leftover-head", "leftover"]
        imgs["leftover-head"], imgs["leftover"] = top, low
        packs["leftover-head"] = "face"

    kinds = {P.lookup(n).kind if P.lookup(n) else n for n in order}
    missing = [(g, what) for g, what, keys in REQUIRED if not any(k in kinds for k in keys)]
    half = []
    for g, what, pre in PAIRS:
        sides = {sd for sd in ("l", "r") if pre + sd in order}
        if len(sides) == 1:
            half.append((g, "%s只有一隻（缺%s邊，要補畫）" % (what, "左" if "l" not in sides else "右")))
    pair_warn = []
    for g, what, pre in PAIRS:
        l, r = imgs.get(pre + "l"), imgs.get(pre + "r")
        if l is None or r is None:
            continue
        ml, mr = l[..., 3] > 128, r[..., 3] > 128
        al, ar = int(ml.sum()), int(mr.sum())
        if min(al, ar) and max(al, ar) > PAIR_AREA * min(al, ar):
            pair_warn.append((g, "%s左右大小差 %.1f 倍" % (what, max(al, ar) / min(al, ar))))
        if al and ar:
            dc = float(np.abs(l[ml][:, :3].mean(0) - r[mr][:, :3].mean(0)).sum())
            if dc > PAIR_COLOR:
                pair_warn.append((g, "%s左右顏色不一樣（差 %d）" % (what, dc)))
    out = os.path.join(st, "groups")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    report = {"packs": [], "warnings": []}
    stack = np.zeros_like(pa)
    for k, (key, title) in enumerate(PACKS, 1):
        names = [n for n in order if packs[n] == key]
        pd = os.path.join(out, "%d_%s" % (k, key))
        os.makedirs(pd)
        # check 1: every part on its own
        tiles, warns = [], []
        for n in names:
            a = imgs[n]
            Image.fromarray(a).save(os.path.join(pd, "part_%s.png" % n))
            on = a[..., 3] > 128
            px = int(on.sum())
            off = int((on & (pa[..., 3] < 10)).sum())
            w = []
            if px < 15:
                w.append("幾乎是空的")
            if px and off > 0.05 * px:
                w.append("%d%% 在人物外面" % (100 * off // px))
            pw = P.position_warning(n, a[..., 3], joints, pivots)   # far from where its name says it belongs
            if pw:
                w.append(pw)
            warns += ["%s：%s" % (n, x) for x in w]
            ys, xs = np.nonzero(a[..., 3] > 8)
            t = checker(TILE, TILE)
            if len(xs):
                crop = Image.fromarray(a).crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
                crop.thumbnail((TILE - 8, TILE - 26))
                t.alpha_composite(crop, ((TILE - crop.width) // 2, 22 + (TILE - 22 - crop.height) // 2))
            label(t, "%s  %d px" % (n, px), (255, 120, 120) if w else (255, 255, 255))
            tiles.append(t)
        warns = (["缺必有的：%s" % what for g, what in missing if g == key] + [t for g, t in half if g == key] +
                 [t for g, t in pair_warn if g == key] + warns)
        cols = 5
        sheet = Image.new("RGBA", (TILE * cols, 24 + TILE * max(1, (len(tiles) + cols - 1) // cols)), (40, 40, 48, 255))
        label(sheet, "%d. %s: %d parts%s" % (k, key, len(names), ("  !! " + "; ".join(warns)) if warns else ""),
              (255, 120, 120) if warns else (255, 255, 255))
        for i, t in enumerate(tiles):
            sheet.alpha_composite(t, ((i % cols) * TILE, 24 + (i // cols) * TILE))
        sheet.convert("RGB").save(os.path.join(out, "parts_%d.jpg" % k), quality=86)
        # check 2: the packs so far, stacked in parts.json order
        stack = np.zeros_like(pa)
        done = {g for g, _ in PACKS[:k]}
        for n in order:
            if packs[n] in done:
                img = Image.fromarray(stack)
                img.alpha_composite(Image.fromarray(imgs[n]))
                stack = np.asarray(img)
        have = stack[..., 3] > 128
        cover = float((have & fig).sum()) / max(1, fig.sum())
        entry = {"pack": key, "title": title, "parts": names, "warnings": warns, "figure_covered": round(cover, 4)}
        view = checker(plate.width, plate.height)
        view.alpha_composite(Image.fromarray(stack))
        side = checker(plate.width, plate.height)
        side.alpha_composite(plate)
        both = Image.new("RGBA", (plate.width * 2, plate.height), (40, 40, 48, 255))
        both.paste(view, (0, 0))
        both.paste(side, (plate.width, 0))
        text = "%d. + %s: covers %.0f%% of the figure" % (k, key, 100 * cover)
        if k == len(PACKS):   # everything: only what the figure leaves uncovered (a hole), no colour against the plate
            # (the user, 2026-10-02: the parts need only be right and close in style; painting the differences from the
            # plate on the sheet read as "make it match the plate")
            missing = fig & ~have
            entry.update({"missing": int(missing.sum()), "missing_share": round(float(missing.sum()) / max(1, fig.sum()), 4)})
            text = "all packs: covers %.0f%% of the figure" % (100 * cover)
        label(both, text)
        both.convert("RGB").resize((both.width // 2, both.height // 2)).save(os.path.join(out, "assemble_%d.jpg" % k), quality=86)
        report["packs"].append(entry)
        report["warnings"] += ["%s：%s" % (title.split("（")[0], w) for w in warns]
        print("%d %-8s %2d parts, covers %5.1f%% of the figure%s" % (k, key, len(names), 100 * cover,
                                                                     ("  " + "; ".join(warns)) if warns else ""), flush=True)
    json.dump(report, open(os.path.join(out, "groups.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    last = report["packs"][-1]
    print("all packs: %.2f%% of the figure uncovered; %d warnings -> %s" % (100 * last["missing_share"], len(report["warnings"]), out), flush=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
