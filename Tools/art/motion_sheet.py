"""The biggest moves of each standard motion on one sheet (the LLM reads pictures, and a GIF shows it only its first
frame, 2026-10-02): from Tests/live/motion_test.tscn's output, per motion the frames where a parameter is at its
largest or smallest, or the whole model is moved furthest, plus the first frame; cut to the figure at full size, one
row per motion. Checkpoints L9 / L11 look at this sheet.

    python Tools/art/motion_sheet.py <motions_dir> [out.jpg] [--max 6]

<motions_dir> is what motion_test wrote (<dir>/<motion>/anim_*.png and frames.json). Writes <motions_dir>/sheet.jpg
(unless an output is given) and one <motions_dir>/sheet_<motion>.jpg per motion.
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw

ROW_H = 520


def pick(log, most):
    """frame numbers to show: the first, and for each parameter (and the model's move) its extreme frames"""
    keys = {}
    for i, e in enumerate(log):
        for k, v in e["params"].items():
            keys.setdefault(k, []).append((i, v if not isinstance(v, list) else float(np.hypot(*v))))
        off = float(np.hypot(*e["offset"])) + 100.0 * abs(e["scale"][0] - 1.0) + 100.0 * abs(e["scale"][1] - 1.0)
        keys.setdefault("(move)", []).append((i, off))
    score = {0: ("start", 0.0)}
    for k, vals in keys.items():
        hi = max(vals, key=lambda q: q[1])
        lo = min(vals, key=lambda q: q[1])
        for idx, val, tag in ((hi[0], hi[1], "max"), (lo[0], lo[1], "min")):
            mag = abs(val)
            if mag < 1e-3:
                continue
            if idx not in score or mag > score[idx][1]:
                score[idx] = ("%s %s %.2f" % (k.replace(":: ", " "), tag, val) if k != "(move)" else "move %.0f px" % val, mag)
    chosen = sorted(score, key=lambda i: -score[i][1])[:most]
    if 0 not in chosen:
        chosen = [0] + chosen[:most - 1]
    return [(i, score[i][0]) for i in sorted(chosen)]


def figure_box(frames, bg):
    """the box around everything that isn't the backdrop colour, over the frames"""
    box = None
    for im in frames:
        a = np.asarray(im.convert("RGB")).astype(int)
        m = np.abs(a - bg).sum(-1) > 30
        ys, xs = np.nonzero(m)
        if len(xs):
            b = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return box


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("motions")
    ap.add_argument("out", nargs="?", default="")
    ap.add_argument("--max", type=int, default=6)
    a = ap.parse_args()
    rows = []
    for m in sorted(os.listdir(a.motions)):
        d = os.path.join(a.motions, m)
        fj = os.path.join(d, "frames.json")
        if not os.path.exists(fj):
            continue
        log = json.load(open(fj))
        picks = pick(log, a.max)
        ims = [Image.open(os.path.join(d, "anim_%04d.png" % log[i]["frame"])).convert("RGB") for i, _ in picks]
        bg = np.asarray(ims[0]).astype(int)[2, 2]
        box = figure_box(ims, bg)
        if box is None:
            continue
        pad = 10
        box = (max(0, box[0] - pad), max(0, box[1] - pad), box[2] + pad, box[3] + pad)
        tiles = []
        for im, (i, why) in zip(ims, picks):
            t = im.crop(box)
            k = (ROW_H - 22) / t.height
            t = t.resize((max(1, int(t.width * k)), ROW_H - 22), Image.LANCZOS)
            cell = Image.new("RGB", (t.width, ROW_H), (30, 30, 36))
            cell.paste(t, (0, 22))
            ImageDraw.Draw(cell).text((4, 4), "%s #%d: %s" % (m, log[i]["frame"], why), fill=(255, 230, 120))
            tiles.append(cell)
        rows.append(tiles)
        row = Image.new("RGB", (sum(t.width + 4 for t in tiles), ROW_H), (20, 20, 24))   # one picture per motion too:
        x = 0                                                                             # the whole sheet is tall
        for t in tiles:
            row.paste(t, (x, 0))
            x += t.width + 4
        row.save(os.path.join(a.motions, "sheet_%s.jpg" % m), quality=88)
    if not rows:
        raise SystemExit("no motions with frames.json in %s" % a.motions)
    w = max(sum(t.width + 4 for t in r) for r in rows)
    sheet = Image.new("RGB", (w, ROW_H * len(rows)), (20, 20, 24))
    for y, r in enumerate(rows):
        x = 0
        for t in r:
            sheet.paste(t, (x, y * ROW_H))
            x += t.width + 4
    out = a.out or os.path.join(a.motions, "sheet.jpg")
    sheet.save(out, quality=88)
    print("%d motions -> %s" % (len(rows), out), flush=True)


if __name__ == "__main__":
    main()
