"""Every layer of a split on one sheet, each cut to its own box on a checker, named, with its pixel count (Docs/Design/22b L2:
the stack shows the whole matches the plate; this shows what each layer holds - a face half made of hat band, a fireball
spread over three layers).

    python Tools/art/layer_sheet.py <st dir> [out.jpg] [name,name,...] [--h 300]     default out: <st dir>/_layers.jpg
"""
import glob
import json
import os
import sys
import numpy as np
from PIL import Image, ImageDraw


def main():
    args = [x for i, x in enumerate(sys.argv[1:], 1) if not x.startswith("--") and sys.argv[i - 1] != "--h"]
    st = args[0]
    out = args[1] if len(args) > 1 and args[1].endswith(".jpg") else os.path.join(st, "_layers.jpg")
    only = next((x.split(",") for x in args[1:] if not x.endswith(".jpg")), None)
    H = int(sys.argv[sys.argv.index("--h") + 1]) if "--h" in sys.argv else 300
    meta = os.path.join(st, "parts.json")   # back to front, as the split is stacked
    order = [q["name"] for q in json.load(open(meta))["order_back_to_front"]] if os.path.exists(meta) else []
    files = [os.path.join(st, "part_%s.png" % n) for n in order if os.path.exists(os.path.join(st, "part_%s.png" % n))] or \
        sorted(glob.glob(os.path.join(st, "part_*.png")))
    if only:
        files = [os.path.join(st, "part_%s.png" % n) for n in only]
    tiles = []
    for f in files:
        name = os.path.basename(f)[5:-4]
        im = Image.open(f).convert("RGBA")
        a = np.asarray(im)[..., 3]
        ys, xs = np.nonzero(a > 8)
        if not len(xs):
            tiles.append((name + " (empty)", Image.new("RGB", (120, H), (60, 0, 0))))
            continue
        c = im.crop((max(0, xs.min() - 6), max(0, ys.min() - 6), xs.max() + 7, ys.max() + 7))
        y, x = np.mgrid[0:c.height, 0:c.width]
        v = np.where(((x // 10) + (y // 10)) % 2 == 0, 215, 180).astype(np.uint8)
        bg = Image.fromarray(np.dstack([v, v, v, np.full_like(v, 255)]), "RGBA")
        bg.alpha_composite(c)
        k = min(H / bg.height, 2.5 * H / bg.width)
        bg = bg.resize((max(1, int(bg.width * k)), max(1, int(bg.height * k))), Image.LANCZOS)
        tiles.append(("%s %dpx" % (name, int((a > 128).sum())), bg.convert("RGB")))
    W = 1600
    rows, row, w = [], [], 0
    for t in tiles:
        if row and w + t[1].width + 6 > W:
            rows.append(row)
            row, w = [], 0
        row.append(t)
        w += t[1].width + 6
    rows.append(row)
    sheet = Image.new("RGB", (W, len(rows) * (H + 20)), (35, 35, 42))
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(rows):
        x = 0
        for name, im in r:
            sheet.paste(im, (x, i * (H + 20) + 18))
            d.text((x + 2, i * (H + 20) + 3), name, fill=(255, 230, 120))
            x += im.width + 6
    sheet.save(out, quality=88)
    print(out, sheet.size)


if __name__ == "__main__":
    main()
