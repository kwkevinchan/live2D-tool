"""How much an image looks like the character, without comparing it to the plate pixel by pixel (Docs/Design/22d).
Each image is turned into a feature vector by a picture model and compared with the same character's OTHER pictures
(the other outfits and the key poses, never the plate under test):

    ccip   deepghs/ccip_onnx (caformer-24): trained to tell anime characters apart. Score = the mean of its three
           smallest "differences" to the references; it calls two pictures the same character under 0.178.
    wd     SmilingWolf/wd-vit-tagger-v3: the Danbooru tag probabilities (hair colour, hat, dress ...) as a vector;
           score = cosine similarity, mean of the three closest references.
    dino   onnx-community/dinov2-base: a general picture model (the CLS vector); same score as wd.

All three are ONNX, run on the CPU with onnxruntime (no torch, no GPU); the files come from the Hugging Face cache
(~880 MB, downloaded on first use).

    python Tools/art/char_score.py score <hero> <image|folder> ... [--exclude <series>] [--models ccip,wd,dino]
        whole-character score of the images against <plates>/<hero>/skins/*/{full,bust}.png and
        <work>/live/<hero>/pose_*/full.png (--exclude drops the reference made from the plate under test:
        "apose" drops every pose_apose*)
    python Tools/art/char_score.py objects <hero> <series> [--ref <series> ...]
        each object (st/part_*.png) and each pack (the objects of a pack stacked) against the same-named object /
        pack of the hero's other series (default: every other series with an st/ split)
    python Tools/art/char_score.py flag <hero> <series> <out.json> <image|folder> ... [--every N] [--limit 0.10]
        the flow's hint (wf, a "?" command at L10, L11, L13b): ccip of each render (folders walked, every Nth frame),
        the scores and the ones over the limit in <out.json>; exit 1 when any is over
    python Tools/art/char_score.py flag-packs <hero> <series> <out.json> [--packs face,hair,clothes] [--limit 0.10]
        the same per pack against the same pack of the hero's other splits (L6, L9); none = skipped, exit 0
    python Tools/art/char_score.py experiment <out_dir>
        the 22d experiment on Freya: makes the bad cases in <out_dir>, scores good / bad / other character at
        object, pack and whole level, writes <out_dir>/scores.json and prints the tables

Feeding images: transparent ones are put on white; renders on a flat grey (the corner colour) or a checkerboard have
that background turned white; then cropped to the figure and padded square.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C   # noqa: E402
import part_names as P   # noqa: E402

WORK = C.WORK
CCIP_SAME = 0.178    # ccip's own threshold (metrics.json of caformer-24): below = the same character
TOP = 3              # a score is the mean over the closest TOP references
FLAG_LIMIT = 0.10    # 22d: about twice the worst good render; over it the flow hands the picture to the reviewer
MODELS = {
    "ccip": ("deepghs/ccip_onnx", "ccip-caformer-24-randaug-pruned/model_feat.onnx"),
    "ccip_metric": ("deepghs/ccip_onnx", "ccip-caformer-24-randaug-pruned/model_metrics.onnx"),
    "wd": ("SmilingWolf/wd-vit-tagger-v3", "model.onnx"),
    "wd_tags": ("SmilingWolf/wd-vit-tagger-v3", "selected_tags.csv"),
    "dino": ("onnx-community/dinov2-base", "onnx/model.onnx"),
}


# ------------------------------------------------------------------ images in
def figure_mask(rgb):
    """True on the figure of an RGB render: not the corner colour, not a 170/200 checkerboard square"""
    a = rgb.astype(int)
    h, w = a.shape[:2]
    corners = np.concatenate([a[:6, :6].reshape(-1, 3), a[:6, -6:].reshape(-1, 3), a[-6:, :6].reshape(-1, 3), a[-6:, -6:].reshape(-1, 3)])
    bg = np.median(corners, 0)
    fig = np.abs(a - bg).sum(-1) > 24
    grey = (a.max(-1) - a.min(-1)) < 6
    for v in (170, 200):
        fig &= ~(grey & (np.abs(a[..., 0] - v) < 5))
    return fig


def prep(img, pad=0.04):
    """an image (PIL / path) as a square RGB picture on white, cropped to the figure"""
    if isinstance(img, str):
        img = Image.open(img)
    if img.mode in ("RGBA", "LA", "P") and "A" in img.convert("RGBA").getbands():
        rgba = np.asarray(img.convert("RGBA"))
        if rgba[..., 3].min() < 250:
            on = rgba[..., 3] > 16
            al = rgba[..., 3:4] / 255.0
            rgb = (rgba[..., :3] * al + 255 * (1 - al)).astype(np.uint8)
        else:
            rgb = rgba[..., :3].copy()
            on = figure_mask(rgb)
            rgb[~on] = 255
    else:
        rgb = np.asarray(img.convert("RGB")).copy()
        on = figure_mask(rgb)
        rgb[~on] = 255
    ys, xs = np.nonzero(on)
    if len(xs):
        rgb = rgb[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = rgb.shape[:2]
    s = int(max(h, w) * (1 + 2 * pad)) + 1
    out = Image.new("RGB", (s, s), (255, 255, 255))
    out.paste(Image.fromarray(rgb), ((s - w) // 2, (s - h) // 2))
    return out


# ------------------------------------------------------------------ models
_SESS = {}


def _file(key):
    from huggingface_hub import hf_hub_download
    return hf_hub_download(*MODELS[key])


def _session(key):
    if key not in _SESS:
        import onnxruntime as ort
        _SESS[key] = ort.InferenceSession(_file(key), providers=["CPUExecutionProvider"])
    return _SESS[key]


def _wd_keep():
    """indices of the general (0) and character (4) tags: the rating tags say nothing about who it is"""
    import csv
    rows = list(csv.DictReader(open(_file("wd_tags"), encoding="utf-8")))
    return np.array([i for i, r in enumerate(rows) if r["category"] in ("0", "4")]), [r["name"] for r in rows]


def features(images, model, batch=8):
    """[N, D] features of prepped square RGB images"""
    out = []
    for i in range(0, len(images), batch):
        part = images[i:i + batch]
        if model == "ccip":    # 384, [-1, 1], NCHW
            x = np.stack([np.asarray(im.resize((384, 384), Image.BILINEAR), np.float32).transpose(2, 0, 1) / 127.5 - 1 for im in part])
            out.append(_session("ccip").run(None, {"input": x})[0])
        elif model == "wd":    # 448, BGR 0..255, NHWC
            x = np.stack([np.asarray(im.resize((448, 448), Image.BICUBIC), np.float32)[..., ::-1] for im in part])
            out.append(_session("wd").run(None, {"input": np.ascontiguousarray(x)})[0])
        elif model == "dino":  # 224, ImageNet mean / std, NCHW; the CLS token
            m, s = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)
            x = np.stack([((np.asarray(im.resize((224, 224), Image.BICUBIC), np.float32) / 255 - m) / s).transpose(2, 0, 1) for im in part])
            out.append(_session("dino").run(None, {"pixel_values": x})[0][:, 0])
        else:
            raise ValueError(model)
    f = np.concatenate(out).astype(np.float32)
    if model == "wd":
        f = f[:, _wd_keep()[0]]
    return f


def scores(test, ref, model):
    """per test feature: (score, index of the closest reference). ccip: difference (lower = more alike);
    wd / dino: cosine similarity (higher = more alike)"""
    if model == "ccip":
        allf = np.concatenate([test, ref])
        d = _session("ccip_metric").run(None, {"input": allf})[0][:len(test), len(test):]
        k = np.sort(d, 1)[:, :TOP].mean(1)
        return k, d.argmin(1)
    a = test / np.linalg.norm(test, axis=1, keepdims=True)
    b = ref / np.linalg.norm(ref, axis=1, keepdims=True)
    s = a @ b.T
    return -np.sort(-s, 1)[:, :TOP].mean(1), s.argmax(1)


def better(model):
    """+1 when a higher score means more alike, -1 when lower does"""
    return -1 if model == "ccip" else 1


# ------------------------------------------------------------------ references
def whole_refs(hero, exclude=""):
    """the hero's other pictures: every outfit (full, bust) and the key poses, minus the plate under test"""
    refs = []
    for d in sorted(glob.glob(os.path.join(C.PLATES, hero, "skins", "*"))):
        if os.path.basename(d) != exclude:
            refs += [os.path.join(d, f) for f in ("full.png", "bust.png") if os.path.exists(os.path.join(d, f))]
    for d in sorted(glob.glob(os.path.join(WORK, "live", hero, "pose_*"))):
        name = os.path.basename(d)
        if exclude and (name == exclude or (exclude == "apose" and name.startswith("pose_apose"))):
            continue
        if os.path.exists(os.path.join(d, "full.png")):
            refs.append(os.path.join(d, "full.png"))
    return refs


def load_parts(hero, series):
    """{part name: RGBA array} of a See-through split"""
    st = os.path.join(WORK, "live", hero, series, "st")
    meta = json.load(open(os.path.join(st, "parts.json")))
    out = {}
    for q in meta["order_back_to_front"]:
        f = os.path.join(st, "part_%s.png" % q["name"])
        if os.path.exists(f):
            out[q["name"]] = np.asarray(Image.open(f).convert("RGBA"))
    return out


def stack(parts, names):
    """the named parts stacked back to front (dict order = parts.json order) on a transparent canvas"""
    names = [n for n in parts if n in names]
    if not names:
        return None
    img = Image.fromarray(np.zeros_like(parts[names[0]]))
    for n in names:
        img.alpha_composite(Image.fromarray(parts[n]))
    return img


def packs_of(parts):
    """{pack: stacked image} by part_names.PACKS"""
    out = {}
    for key, _ in P.PACKS:
        im = stack(parts, [n for n in parts if P.pack_of(n) == key])
        if im is not None:
            out[key] = im
    return out


def same_object(name, parts):
    """the same object in another split: the same name, else the same kind (ears-l for ears)"""
    if name in parts:
        return name
    e = P.lookup(name)
    return next((n for n in parts if e and P.lookup(n) and P.lookup(n).kind == e.kind), None)


def sheet_tiles(path, head=24):
    """the tiles of a _packs/sheet_pack_*.jpg (split at the dark full-height separators), without the label strip"""
    a = np.asarray(Image.open(path).convert("RGB"))
    dark = (a[head:].max(-1) < 60).mean(0) > 0.97
    tiles, x0 = [], 0
    for x in range(a.shape[1] + 1):
        if x == a.shape[1] or dark[x]:
            if x - x0 > 40:
                tiles.append(Image.fromarray(a[head:, x0:x]))
            x0 = x + 1
    return tiles


# ------------------------------------------------------------------ bad cases (experiment)
def hue_shift(rgba, mask, deg):
    """turn the hue of the masked pixels by deg"""
    a = rgba.copy()
    px = a[mask][:, :3].astype(np.float32) / 255.0
    if not len(px):
        return a
    mx, mn = px.max(1), px.min(1)
    d = np.maximum(mx - mn, 1e-6)
    r, g, b = px.T
    h = np.where(mx == r, (g - b) / d % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6.0
    h = (h + deg / 360.0) % 1
    v, c = mx, mx - mn
    k = lambda n: (n + h * 6) % 6   # noqa: E731
    f = lambda n: v - c * np.clip(np.minimum(k(n), 4 - k(n)), 0, 1)   # noqa: E731   hsv -> rgb, the closed form
    px2 = np.stack([f(5), f(3), f(1)], 1)
    rows = a[mask]
    rows[:, :3] = (px2 * 255).round().astype(np.uint8)
    a[mask] = rows
    return a


def bbox(alpha, t=128):
    ys, xs = np.nonzero(alpha > t)
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else None


def paste_fit(dst, src, src_box, dst_box):
    """paste src's src_box region scaled onto dst_box (PIL RGBA images)"""
    piece = src.crop(src_box).resize((max(1, dst_box[2] - dst_box[0]), max(1, dst_box[3] - dst_box[1])), Image.LANCZOS)
    dst.alpha_composite(piece, (int(dst_box[0]), int(dst_box[1])))


def plate_to_render(plate_alpha, render_rgb):
    """(scale, dx, dy) mapping plate pixels onto a rest-pose render (figure boxes matched by height)"""
    pb = bbox(plate_alpha)
    ys, xs = np.nonzero(figure_mask(render_rgb))
    rb = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    s = (rb[3] - rb[1]) / float(pb[3] - pb[1])
    return s, rb[0] - pb[0] * s, rb[1] - pb[1] * s


def to_render(mask, m, shape):
    s, dx, dy = m
    im = Image.fromarray((mask * 255).astype(np.uint8))
    im = im.resize((int(im.width * s), int(im.height * s)), Image.NEAREST)
    out = Image.new("L", (shape[1], shape[0]), 0)
    out.paste(im, (int(round(dx)), int(round(dy))))
    return np.asarray(out) > 128


def make_bad(render_path, fparts, aparts, out_dir, tag):
    """deliberately wrong versions of a rest-pose render: {name: path}"""
    base = Image.open(render_path).convert("RGBA")
    rgb = np.asarray(base)[..., :3]
    full = stack(fparts, list(fparts))
    m = plate_to_render(np.asarray(full)[..., 3], rgb)
    s, dx, dy = m
    bg = tuple(int(v) for v in np.median(rgb[:6, :6].reshape(-1, 3), 0)) + (255,)
    kinds = lambda parts, ks: [n for n in parts if P.lookup(n) and P.lookup(n).kind in ks]   # noqa: E731
    hair_k = ("front_hair", "back_hair", "side_lock", "hair_ends", "side_hair", "bangs")
    head_k = ("face", "eyewhite", "irides", "eyelash", "eyebrow", "mouth", "nose", "ears")
    fa = lambda names: np.max([fparts[n][..., 3] > 128 for n in names], 0)   # noqa: E731
    rbox = lambda b: tuple(int(round(v)) for v in (b[0] * s + dx, b[1] * s + dy, b[2] * s + dx, b[3] * s + dy))   # noqa: E731
    out = {}

    def save(name, img):
        p = os.path.join(out_dir, "%s_%s.png" % (tag, name))
        img.convert("RGB").save(p)
        out[name] = p

    # 1 the head under a flat patch (face and front hair box)
    hb = rbox(bbox(fa(kinds(fparts, head_k + ("front_hair",))).astype(np.uint8) * 255))
    img = base.copy()
    img.paste((214, 190, 170, 255), hb)
    save("head_patch", img)
    # 2 hair recoloured blue (hue +200) where the hair parts are
    hm = to_render(fa(kinds(fparts, hair_k)), m, rgb.shape)
    save("hair_blue", Image.fromarray(hue_shift(np.asarray(base), hm, 200)))
    # 3 the whole figure in another palette (hue +120)
    save("all_green", Image.fromarray(hue_shift(np.asarray(base), figure_mask(rgb), 120)))
    # 4 Alicia's right arm pasted over Freya's
    arm = [n for n in fparts if n.endswith("-r") and P.lookup(n) and P.lookup(n).kind in ("upperarm", "forearm", "hand")]
    aarm = [n for n in aparts if n.endswith("-r") and P.lookup(n) and P.lookup(n).kind in ("upperarm", "forearm", "hand")]
    asrc = stack(aparts, aarm)
    img = base.copy()
    paste_fit(img, asrc, bbox(np.asarray(asrc)[..., 3]), rbox(bbox(fa(arm).astype(np.uint8) * 255)))
    save("alicia_arm", img)
    # 5 Alicia's hair and hat: Freya's hair and hat painted over with the background, Alicia's placed by the face box
    gone = to_render(fa(kinds(fparts, hair_k + ("headwear",))) & ~fa(kinds(fparts, head_k)), m, rgb.shape)
    a = np.asarray(base).copy()
    a[gone] = bg
    img = Image.fromarray(a)
    fb, ab = bbox(fparts["face"][..., 3]), bbox(aparts["face"][..., 3])
    k = (fb[2] - fb[0]) / float(ab[2] - ab[0])
    ahair = stack(aparts, kinds(aparts, hair_k + ("headwear",)))
    hb2 = bbox(np.asarray(ahair)[..., 3])
    # Alicia's hair box carried into Freya's plate by the faces, then into the render
    fbox = ((hb2[0] - ab[0]) * k + fb[0], (hb2[1] - ab[1]) * k + fb[1], (hb2[2] - ab[0]) * k + fb[0], (hb2[3] - ab[1]) * k + fb[1])
    back = Image.new("RGBA", img.size, (0, 0, 0, 0))
    paste_fit(back, ahair, hb2, rbox(fbox))
    back.alpha_composite(img)   # her hair behind Freya's face: the face stays on top
    face_only = to_render(fa(kinds(fparts, head_k)), m, rgb.shape)
    hair_on = np.asarray(back).copy()
    front = Image.new("RGBA", img.size, (0, 0, 0, 0))
    paste_fit(front, ahair, hb2, rbox(fbox))
    f = np.asarray(front)
    keep = (f[..., 3] > 128) & ~face_only
    hair_on[keep] = f[keep]
    save("alicia_hair", Image.fromarray(hair_on))
    # 6 Alicia's face over Freya's
    aface = stack(aparts, kinds(aparts, head_k))
    img = base.copy()
    paste_fit(img, aface, bbox(np.asarray(aface)[..., 3]), rbox(bbox(fa(kinds(fparts, head_k)).astype(np.uint8) * 255)))
    save("alicia_face", img)
    return out


def bad_object(a, how, other=None):
    """a wrong version of an object (RGBA array): recoloured, a flat silhouette, or another character's"""
    on = a[..., 3] > 16
    if how == "recolor":
        return hue_shift(a, on, 150)
    if how == "flat":
        b = a.copy()
        b[on, :3] = a[on, :3].reshape(-1, 3).mean(0).astype(np.uint8)
        return b
    return other


# ------------------------------------------------------------------ commands
def run_set(items, refs, models):
    """items: [(group, label, image)]; refs: [image]. -> rows of {group, label, <model>: score}"""
    rimgs = [prep(r) for r in refs]
    timgs = [prep(x) for _, _, x in items]
    rows = [{"group": g, "label": n} for g, n, _ in items]
    for mo in models:
        sc, _ = scores(features(timgs, mo), features(rimgs, mo), mo)
        for r, v in zip(rows, sc):
            r[mo] = round(float(v), 4)
    return rows


def summary(rows, models):
    """per group: n, mean, min, max per model"""
    out = {}
    for r in rows:
        out.setdefault(r["group"], []).append(r)
    res = {}
    for g, rs in out.items():
        res[g] = {"n": len(rs)}
        for mo in models:
            v = np.array([r[mo] for r in rs])
            res[g][mo] = (round(float(v.mean()), 3), round(float(v.min()), 3), round(float(v.max()), 3))
    return res


def separation(rows, models, good, bad):
    """per model: does every good beat every bad? (the worst good vs the best bad, and the share of pairs ordered)"""
    res = {}
    for mo in models:
        sg = better(mo) * np.array([r[mo] for r in rows if r["group"] in good])
        sb = better(mo) * np.array([r[mo] for r in rows if r["group"] in bad])
        if len(sg) and len(sb):
            res[mo] = {"auc": round(float((sg[:, None] > sb[None, :]).mean()), 3),
                       "worst_good": round(float(better(mo) * sg.min()), 3), "best_bad": round(float(better(mo) * sb.max()), 3)}
    return res


def print_table(title, summ, models):
    print("\n== %s" % title)
    print("%-28s %4s  %s" % ("group", "n", "  ".join("%-24s" % m for m in models)))
    for g, s in summ.items():
        print("%-28s %4d  %s" % (g, s["n"], "  ".join("%-24s" % ("%.3f (%.3f..%.3f)" % s[m]) for m in models)))


def cmd_score(args):
    imgs = []
    for p in args.images:
        imgs += sorted(glob.glob(os.path.join(p, "*.png")) + glob.glob(os.path.join(p, "*.jpg"))) if os.path.isdir(p) else [p]
    refs = whole_refs(args.hero, args.exclude)
    rows = run_set([("test", os.path.basename(p), p) for p in imgs], refs, args.models)
    for r in rows:
        print("%-40s %s" % (r["label"], "  ".join("%s %.3f" % (m, r[m]) for m in args.models)))
    if "ccip" in args.models:
        print("ccip under %.3f = the same character (%d of %d)" % (CCIP_SAME, sum(r["ccip"] < CCIP_SAME for r in rows), len(rows)))


def cmd_objects(args):
    test = load_parts(args.hero, args.series)
    refs = args.ref or [os.path.basename(os.path.dirname(d)) for d in glob.glob(os.path.join(WORK, "live", args.hero, "*", "st"))
                        if os.path.basename(os.path.dirname(d)) != args.series]
    rparts = [load_parts(args.hero, r) for r in refs]
    for level, tdict, rdicts in (("object", test, rparts), ("pack", packs_of(test), [packs_of(r) for r in rparts])):
        for n, a in tdict.items():
            ref = [d[same_object(n, d)] for d in rdicts if same_object(n, d)]
            if not ref:
                continue
            ref = [Image.fromarray(x) if isinstance(x, np.ndarray) else x for x in ref]
            img = Image.fromarray(a) if isinstance(a, np.ndarray) else a
            r = run_set([(level, n, img)], ref, args.models)[0]
            print("%-7s %-22s %s" % (level, n, "  ".join("%s %.3f" % (m, r[m]) for m in args.models)))


def _exclude(series):
    """the references made from the plate under test: a pose_apose* split drops every A-pose"""
    return "apose" if series.startswith("pose_apose") else series


def _write_flag(out, kind, limit, rows, note=""):
    over = [r for r in rows if r["ccip"] > limit]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    json.dump({"kind": kind, "model": "ccip", "limit": limit, "note": note, "over": [r["label"] for r in over],
               "scores": {r["label"]: round(float(r["ccip"]), 3) for r in rows}},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in rows:
        print("%-36s ccip %.3f%s" % (r["label"], r["ccip"], "  OVER" if r["ccip"] > limit else ""))
    print("%d of %d over %.2f%s -> %s" % (len(over), len(rows), limit, (" (%s)" % note) if note else "", out))
    sys.exit(1 if over else 0)


def cmd_flag(args):
    """a hint for the flow (wf, a '?' command): ccip of renders against the hero's other pictures; exit 1 when any is
    over the limit. Folders are walked (motion frames: <motion>/anim_*.png), every Nth picture of each folder kept"""
    imgs = []
    for p in args.images:
        if not os.path.isdir(p):
            imgs += [p] if os.path.exists(p) else []
            continue
        for d, _, fs in sorted(os.walk(p)):
            fs = sorted(f for f in fs if f.endswith(".png"))
            imgs += [os.path.join(d, f) for f in fs[::args.every]]
    refs = whole_refs(args.hero, _exclude(args.series))
    if not imgs or not refs:
        _write_flag(args.out, "whole", args.limit, [], "no pictures" if not imgs else "no references")
    rows = run_set([("test", os.path.relpath(p, os.path.commonpath(imgs) if len(imgs) > 1 else os.path.dirname(p)), p)
                    for p in imgs], refs, ["ccip"])
    _write_flag(args.out, "whole", args.limit, rows)


def cmd_flag_packs(args):
    """the same hint per pack (face, hair, clothes by default: the packs 22d found it works on) against the same pack
    of the hero's other splits; the first split of a character has no references and is skipped"""
    test = packs_of(load_parts(args.hero, args.series))
    others = [os.path.basename(os.path.dirname(os.path.dirname(d))) for d in glob.glob(os.path.join(WORK, "live", args.hero, "*", "st", "parts.json"))]
    # not itself, nor its own copies (<series>_hand_<date>, <series>_moved_<date>: the same picture)
    rpacks = [packs_of(load_parts(args.hero, r)) for r in sorted(others) if r != args.series and not r.startswith(args.series + "_")]
    rows = []
    for n in args.packs:
        ref = [d[n] for d in rpacks if n in d]
        if n in test and ref:
            rows.append(run_set([("pack", n, test[n])], ref, ["ccip"])[0])
    _write_flag(args.out, "pack", args.limit, rows, "" if rows else "no other split of %s to compare" % args.hero)


def cmd_experiment(args):
    out = args.out
    os.makedirs(out, exist_ok=True)
    models = args.models
    L = os.path.join(WORK, "live")
    F, A = os.path.join(L, "freya", "-"), os.path.join(L, "alicia", "-")
    fparts, aparts = load_parts("freya", "-"), load_parts("alicia", "-")
    result = {"models": models}

    # ---- whole: renders vs the other outfits and poses
    good = [("good -", os.path.basename(p), p) for p in sorted(glob.glob(os.path.join(F, "_shots", "*.png")))]
    good += [("good - motion", "%s/%s" % (os.path.basename(os.path.dirname(p)), os.path.basename(p)), p)
             for p in sorted(glob.glob(os.path.join(F, "_motions_all", "*", "anim_*.png")))[::10]]
    apose = [("good apose", "%s/%s" % (s, os.path.basename(p)), p) for s in ("pose_apose_r2", "pose_apose_r3")
             for p in sorted(glob.glob(os.path.join(L, "freya", s, "_shots", "*.png")))]
    bad = []
    bd = os.path.join(out, "bad")
    os.makedirs(bd, exist_ok=True)
    for shot in ("000_rest", "090_mouth_open", "150_settled"):
        for name, p in make_bad(os.path.join(F, "_shots", shot + ".png"), fparts, aparts, bd, shot).items():
            bad.append(("bad " + name, shot, p))
    other = [("other alicia motion", "%s/%s" % (os.path.basename(os.path.dirname(p)), os.path.basename(p)), p)
             for p in sorted(glob.glob(os.path.join(A, "_motions_all", "*", "anim_*.png")))[::20]]
    other += [("other alicia plates", os.path.relpath(p, os.path.join(C.PLATES, "alicia")), p)
              for p in [os.path.join(C.PLATES, "alicia", "full.png")] + sorted(glob.glob(os.path.join(C.PLATES, "alicia", "skins", "*", "full.png")))]
    other += [("other rena/yukino", h, os.path.join(C.PLATES, h, "full.png")) for h in ("rena", "yukino")]
    refs = whole_refs("freya", "apose")   # no pose_apose*, no main plate (it is not in skins/ and not a pose_)
    print("whole references: %d" % len(refs))
    rows = run_set(good + apose + bad + other, refs, models)
    refs_skins = [r for r in refs if os.sep + "skins" + os.sep in r or "/skins/" in r]
    rows_sk = run_set(good + apose + bad + other, refs_skins, models)   # outfits only: does it know her, or the dress?
    result["whole"] = {"rows": rows, "summary": summary(rows, models), "refs": refs,
                       "separation_bad": separation(rows, models, ("good -", "good - motion", "good apose"), [g for g, _, _ in bad]),
                       "separation_other": separation(rows, models, ("good -", "good - motion", "good apose"), [g for g, _, _ in other]),
                       "summary_skins_only": summary(rows_sk, models)}
    print_table("whole (refs: %d other outfits + poses)" % len(refs), result["whole"]["summary"], models)
    print_table("whole (refs: outfits only, %d)" % len(refs_skins), result["whole"]["summary_skins_only"], models)
    print("separation good vs bad:", result["whole"]["separation_bad"])
    print("separation good vs other:", result["whole"]["separation_other"])

    # ---- object: each object vs the same object in Freya's other splits
    ref_series = ["C", "pose_apose_r2", "pose_apose_r3", "pose_apose"]
    rparts = [load_parts("freya", s) for s in ref_series]
    orows, wcases = [], []
    for n, a in fparts.items():
        if (a[..., 3] > 128).sum() < 400:
            continue   # specks (an eyelash, a nose) are too small to say anything
        ref = [Image.fromarray(d[same_object(n, d)]) for d in rparts if same_object(n, d)]
        if not ref:
            continue
        cases = [("good", Image.fromarray(a)), ("bad recolor", Image.fromarray(bad_object(a, "recolor"))),
                 ("bad flat", Image.fromarray(bad_object(a, "flat")))]
        an = same_object(n, aparts)
        if an:
            cases.append(("other alicia", Image.fromarray(aparts[an])))
        orows += run_set([(g, n, im) for g, im in cases], ref, models)
        wcases.append(("good", n, cases[0][1]))
    # the same objects judged against whole-character pictures: does that work at all?
    wrows = run_set(wcases, refs, models)
    result["object"] = {"rows": orows, "summary": summary(orows, models),
                        "separation_bad": separation(orows, models, ("good",), ("bad recolor", "bad flat")),
                        "separation_other": separation(orows, models, ("good",), ("other alicia",)),
                        "vs_whole_refs": summary(wrows, models)}
    # per object: is the good one better than each of its bad ones? (the honest per-object check)
    per = {}
    for mo in models:
        wins = tot = 0
        for n in {r["label"] for r in orows}:
            g = [r[mo] for r in orows if r["label"] == n and r["group"] == "good"]
            for r in orows:
                if r["label"] == n and r["group"] != "good":
                    tot += 1
                    wins += better(mo) * g[0] > better(mo) * r[mo]
        per[mo] = "%d/%d" % (wins, tot)
    result["object"]["good_beats_own_bad"] = per
    print_table("object (refs: the same object in C, apose, r2, r3)", result["object"]["summary"], models)
    print("object vs whole refs (good only):", result["object"]["vs_whole_refs"])
    print("separation good vs bad:", result["object"]["separation_bad"], " vs other:", result["object"]["separation_other"])
    print("good beats its own bad versions:", per)

    # ---- pack: packs stacked from the objects, and the rendered pack tiles
    fp, ap = packs_of(fparts), packs_of(aparts)
    rp = [packs_of(d) for d in rparts]
    tiles = {}
    for f in sorted(glob.glob(os.path.join(F, "_packs", "sheet_pack_*.jpg"))):
        key = os.path.basename(f)[len("sheet_pack_"):-4]
        tiles[key] = sheet_tiles(f)
    tile_pack = {"head": "face", "hair": "hair", "body": "clothes", "arms": "limbs", "legs": "limbs", "weapon": "weapon", "held": "other"}
    prows = []
    for key, im in fp.items():
        ref = [d[key] for d in rp if key in d]
        if not ref:
            continue
        a = np.asarray(im)
        cases = [("good stacked", im), ("bad recolor", Image.fromarray(bad_object(a, "recolor"))),
                 ("bad flat", Image.fromarray(bad_object(a, "flat")))]
        if key in ap:
            cases.append(("other alicia", ap[key]))
        if key == "hair":   # Freya's hair with Alicia's hat / Alicia's hair with Freya's hat
            ah = [n for n in aparts if P.pack_of(n) == "hair"]
            mix = dict((n, aparts[n]) for n in ah if not n.startswith("headwear"))
            cases.append(("bad mixed hair", stack({**mix, **{n: fparts[n] for n in fparts if n.startswith("headwear")}}, list(mix) + [n for n in fparts if n.startswith("headwear")])))
        for tk, tl in tiles.items():
            if tile_pack.get(tk) == key:
                cases += [("good render tile", t) for t in tl[:4]]
                cases += [("bad render tile recolor", Image.fromarray(hue_shift(np.asarray(t.convert("RGBA")), figure_mask(np.asarray(t)), 150))) for t in tl[:2]]
        prows += run_set([(g, key, x) for g, x in cases], ref, models)
    # the assemble steps (packs added one by one) against the same step of the other splits
    for k in range(1, 7):
        def left(series):
            p = os.path.join(L, "freya" if series != "alicia" else "alicia", series if series != "alicia" else "-", "st", "groups", "assemble_%d.jpg" % k)
            if not os.path.exists(p):
                return None
            im = Image.open(p).convert("RGB")
            return im.crop((0, 20, im.width // 2, im.height))
        ref = [x for x in (left(s) for s in ref_series) if x is not None]
        cases = [("good assemble", left("-"))]
        if left("alicia") is not None:
            cases.append(("other alicia", left("alicia")))
        prows += run_set([(g, "assemble_%d" % k, x) for g, x in cases if x is not None], ref, models)
    result["pack"] = {"rows": prows, "summary": summary(prows, models),
                      "separation_bad": separation(prows, models, ("good stacked", "good render tile", "good assemble"),
                                                   ("bad recolor", "bad flat", "bad mixed hair", "bad render tile recolor")),
                      "separation_other": separation(prows, models, ("good stacked", "good render tile", "good assemble"), ("other alicia",))}
    print_table("pack (refs: the same pack of C, apose, r2, r3)", result["pack"]["summary"], models)
    print("separation good vs bad:", result["pack"]["separation_bad"], " vs other:", result["pack"]["separation_other"])
    json.dump(result, open(os.path.join(out, "scores.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nwrote %s" % os.path.join(out, "scores.json"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("hero")
    s.add_argument("images", nargs="+")
    s.add_argument("--exclude", default="")
    o = sub.add_parser("objects")
    o.add_argument("hero")
    o.add_argument("series")
    o.add_argument("--ref", nargs="*")
    e = sub.add_parser("experiment")
    e.add_argument("out")
    for p in (s, o, e):
        p.add_argument("--models", default="ccip,wd,dino", type=lambda v: v.split(","))
    f = sub.add_parser("flag")
    f.add_argument("hero")
    f.add_argument("series")
    f.add_argument("out")
    f.add_argument("images", nargs="+")
    f.add_argument("--every", type=int, default=1)
    fp = sub.add_parser("flag-packs")
    fp.add_argument("hero")
    fp.add_argument("series")
    fp.add_argument("out")
    fp.add_argument("--packs", default="face,hair,clothes", type=lambda v: v.split(","))
    for p in (f, fp):
        p.add_argument("--limit", type=float, default=FLAG_LIMIT)
    args = ap.parse_args()
    {"score": cmd_score, "objects": cmd_objects, "experiment": cmd_experiment, "flag": cmd_flag,
     "flag-packs": cmd_flag_packs}[args.cmd](args)


if __name__ == "__main__":
    main()
