"""Checks rigged Inochi2D models against their plates: renders each model at rest with the game's player
(Tests/live/rig_render.tscn, pixel for pixel on the plate) and marks where the render differs: plate pixels the
render lacks (a lost belt), wrong colours (hair painted over goggles, a robe over the hakama) and extra pixels
off the figure. One picture per model with the differences marked, a summary line each, and rig_check.json.

  python Tools/art/rig_check.py                    every rigged folder under <work>/live
  python Tools/art/rig_check.py rena yukino/pose_open
Exit status 1 when a model is flagged (more than FLAG_SHARE of the figure differs, or one area bigger than
FLAG_AREA of it). Needs a window for Godot (GODOT = the console exe, default below).
"""
import glob
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inx_rig import ROOT, WORK, src_dir   # noqa: E402

GODOT = os.environ.get("GODOT", r"C:\Users\kwkev\Tool\Godot_v4.7.2-stable_win64\Godot_v4.7.2-stable_win64_console.exe")
OUT = os.path.join(WORK, "live", "check")
COLOR_OFF = 90       # sum of RGB differences that counts as a wrong colour
FLAG_SHARE = 0.005   # of the figure's pixels
FLAG_AREA = 0.001    # one connected area, of the figure's pixels
EDGE = 3             # px either side of the figure's outline that aren't judged


def folders(args):
    """(hero, series, folder) for every rigged folder asked for"""
    live = os.path.join(WORK, "live")
    picks = args or [h for h in sorted(os.listdir(live)) if h not in ("check", "preview") and os.path.isdir(os.path.join(live, h))]
    for a in picks:
        hero, _, series = a.partition("/")
        for s in ([series] if series else sorted(os.listdir(os.path.join(live, hero)))):
            ld = os.path.join(live, hero, s)
            if os.path.isdir(ld) and glob.glob(os.path.join(ld, "*.inx")):
                yield hero, s, ld


def model_and_plate(hero, series, ld):
    model = max(glob.glob(os.path.join(ld, "*.inx")), key=os.path.getmtime)   # the latest rig of this folder
    sd = ld if os.path.exists(os.path.join(ld, "full.png")) else src_dir(hero, series)
    return model, os.path.join(sd, "full.png")


def compare(plate_path, render_path):
    p = np.asarray(Image.open(plate_path).convert("RGBA")).astype(int)
    r = np.asarray(Image.open(render_path).convert("RGBA")).astype(int)
    fig = p[..., 3] > 128
    # the outline (EDGE px either side of the figure's edge) differs by texture filtering and the rig's margin
    inside = ndimage.binary_erosion(fig, iterations=EDGE)
    outside = ~ndimage.binary_dilation(p[..., 3] > 8, iterations=EDGE)
    missing = inside & (r[..., 3] < 64)
    extra = outside & (r[..., 3] > 128)
    off = inside & (r[..., 3] > 128) & (np.abs(p[..., :3] - r[..., :3]).sum(-1) > COLOR_OFF)
    missing, extra, off = (ndimage.binary_opening(m, iterations=1) for m in (missing, extra, off))   # lone pixels
    bad = missing | extra | off
    labels, n = ndimage.label(bad)
    areas = []
    for i, sl in enumerate(ndimage.find_objects(labels), 1):
        m = labels[sl] == i
        kind = max((("missing", missing[sl][m].sum()), ("colour", off[sl][m].sum()), ("extra", extra[sl][m].sum())), key=lambda k: k[1])[0]
        areas.append({"px": int(m.sum()), "kind": kind, "box": [sl[1].start, sl[0].start, sl[1].stop, sl[0].stop]})
    areas.sort(key=lambda a: -a["px"])
    figure = max(1, int(fig.sum()))
    res = {"figure_px": figure, "bad_share": float(bad.sum()) / figure,
           "missing": int(missing.sum()), "colour": int(off.sum()), "extra": int(extra.sum()), "areas": areas[:5]}
    res["flagged"] = res["bad_share"] > FLAG_SHARE or bool(areas and areas[0]["px"] > FLAG_AREA * figure)
    # the picture: the plate dimmed, missing blue, wrong colour red, extra green, the biggest areas boxed
    v = (p[..., :3] * 0.35 + 150 * 0.65 * (~fig)[..., None]).astype(np.uint8)
    v[missing] = (40, 90, 255)
    v[off] = (255, 40, 40)
    v[extra] = (40, 220, 60)
    img = Image.fromarray(v)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    for a in areas[:5]:
        if a["px"] > FLAG_AREA * figure:
            d.rectangle(a["box"], outline=(255, 230, 0), width=3)
    return res, img


def main(args):
    os.makedirs(OUT, exist_ok=True)
    jobs = []
    for hero, series, ld in folders(args):
        model, plate = model_and_plate(hero, series, ld)
        name = "%s_%s" % (hero, "default" if series == "-" else series)
        w, h = Image.open(plate).size
        jobs.append((name, model, plate, os.path.join(OUT, name + "_render.png"), (w, h)))
    if not jobs:
        print("nothing rigged")
        return 0
    cmd = [GODOT, "--path", ROOT, "res://Tests/live/rig_render.tscn", "--"]
    cmd += ["%s=%s=%dx%d" % (m, r, w, h) for _, m, _, r, (w, h) in jobs]
    subprocess.run(cmd, capture_output=True, timeout=120 + 20 * len(jobs))
    path = os.path.join(OUT, "rig_check.json")
    try:   # results of earlier runs stay (a run of one folder used to wipe the others)
        report = json.load(open(path))
    except (OSError, ValueError):
        report = {}
    flagged = 0
    for name, model, plate, render, _ in jobs:
        if not os.path.exists(render):
            print("%-28s NOT RENDERED (%s)" % (name, os.path.basename(model)))
            flagged += 1
            continue
        res, img = compare(plate, render)
        img.save(os.path.join(OUT, name + "_check.jpg"), quality=88)
        res["model"] = model
        report[name] = res
        flagged += res["flagged"]
        top = res["areas"][0] if res["areas"] else None
        print("%-28s %s %5.2f%% differs (missing %d, colour %d, extra %d)%s" % (
            name, "FLAG" if res["flagged"] else "ok  ", 100 * res["bad_share"], res["missing"], res["colour"], res["extra"],
            "; biggest: %s %d px at %s" % (top["kind"], top["px"], top["box"]) if top else ""))
        os.remove(render)
    json.dump(report, open(path + ".tmp", "w"), indent=1)
    os.replace(path + ".tmp", path)
    print("pictures and rig_check.json in", OUT)
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
