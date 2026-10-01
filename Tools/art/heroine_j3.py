"""Heroine art in the J3 style (Japanese light-novel illustration, soft pastel), decided 2026-09-28.

For every heroine and outfit (default + skin series A-J):
  plate   : full-body standing figure on a flat light-grey background (txt2img), face refined by a
            crop-upscale-img2img pass
  expr    : blink / happy / hurt / cast / shy, each an inpaint of the face crop only, composited back with a
            feathered mask, so everything outside the face is pixel-identical to the plate
  scene   : a landscape wardrobe illustration (background + sitting/lying pose), same identity and outfit
Then Tools/art/grok/heroine_process.py turns plate + expressions into full/bust/chibi/meta.

Content rule: heroines are adults (20s) and nothing explicit (no nudity). Needs the local ComfyUI server.

    python Tools/art/heroine_j3.py gen   <work_dir> <hero> [series ...]   ("-" = default outfit)
    python Tools/art/heroine_j3.py scene <work_dir> <hero> [series ...]
    python Tools/art/heroine_j3.py install <work_dir> <hero> [series ...]
"""
import io, json, os, shutil, subprocess, sys, time, uuid

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
import comfy_gen as cg  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROCESS = os.path.join(ROOT, "Tools", "art", "grok", "heroine_process.py")

QUALITY = "score_9, score_8_up, score_7_up"
STYLE = ("source_anime, japanese light novel illustration, soft pastel colors, delicate lineart, airy lighting, "
         "anime eyes")
ADULT = "young adult woman, 20 years old, adult, slender, medium breasts, beautiful face, japanese anime face"
NEG = ("score_4, score_5, score_6, loli, child, young girl, teen, petite, flat chest, childlike face, "
       "western comic, western cartoon, realistic, 3d, mature, milf, old, aged up, thick lips, heavy makeup, "
       "nude, nipples, areola, pussy, topless, bottomless, see-through, "
       "lowres, bad anatomy, bad hands, extra fingers, missing fingers, text, watermark, signature, "
       "multiple views, character sheet, cropped, out of frame, blurry, jpeg artifacts")
PLATE = "full body, standing, looking at viewer, simple background, grey background, rating_questionable"
PLATE_NEG = ", scenery, detailed background, shadow on floor, cropped legs, feet out of frame"

import config as _C   # characters/<id>.toml  # noqa: E402
HEROES = {h: {k: c[k] for k in ("age", "look", "weapon", "neg") if k in c} for h, c in _C.CHARACTERS.items()}

# outfit: what she wears on the plate and in the scene. scene: (background, pose) for the wardrobe picture.
OUTFITS = {h: {sid: (o.get("outfit", ""), o.get("scene", ""), o.get("scene_pose", "")) for sid, o in c.get("outfits", {}).items()}
           for h, c in _C.CHARACTERS.items()}

# outfits that carry their own prop instead of the usual weapon on the battle plate
NO_WEAPON = {("alicia", k) for k in "BCDEGHIJ"} | {("freya", k) for k in "ACDEGHIJ"} | \
    {("yukino", k) for k in "CDEGHJ"} | {("rena", k) for k in "CDEGHIJ"}


def plate_prompt(hero, series):
    w = "" if (hero, series) in NO_WEAPON else HEROES[hero]["weapon"] + ", "
    return prompt_for(hero, series, w + PLATE)

EXPRESSIONS = {
    "blink": ("(closed eyes:1.5), smile", ", open eyes"),
    "happy": ("(closed eyes:1.2), happy, open mouth, big smile, blush", ", open eyes, sad"),
    "hurt": ("pained expression, one eye closed, clenched teeth, sweat, frown", ", smile"),
    "cast": ("determined, shouting, open mouth, v-shaped eyebrows, glowing eyes", ", smile, closed eyes"),
    "shy": ("embarrassed, heavy blush, looking away, wavy mouth, sweatdrop", ", grin"),
}


## Illustrious checkpoints (2026-09-29): the age is given as a number only; long age descriptions spoil the art
## (owner's call). Pony keeps ADULT so the current art can be reproduced. Content limits in NEG stay either way.
NEG_IL = ("child, loli, nude, nipples, areola, pussy, topless, bottomless, see-through, lowres, bad anatomy, bad hands, "
          "extra fingers, missing fingers, text, watermark, signature, multiple views, character sheet, cropped, "
          "out of frame, blurry, jpeg artifacts")


def neg_base():
    return NEG if cg.family() == "pony" else NEG_IL


def prompt_for(hero, series, extra):
    h = HEROES[hero]
    outfit = OUTFITS[hero][series][0]
    age = ADULT if cg.family() == "pony" else "%d years old" % h["age"]
    return "1girl, solo, %s, %s, %s, %s" % (age, h["look"], outfit, extra)


def _wf_common(pos, neg, latent, seed, steps, cfg, denoise, prefix, template="txt2img"):
    import workflows as W
    return W.fill(W.load(template), {"正面提示詞": {"text": "%s, %s, %s" % (QUALITY, STYLE, pos)},
        "排除詞": {"text": neg_base() + neg}, "採樣": {"seed": seed, "steps": steps, "cfg": cfg, "denoise": denoise},
        "存圖": {"filename_prefix": prefix}})


def run_wf(wf):
    save = next(k for k, n in wf.items() if n.get("class_type") == "SaveImage")
    pid = cg.post("/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())})["prompt_id"]
    while True:
        hist = json.loads(cg.get("/history/%s" % pid))
        if pid in hist:
            outs = hist[pid]["outputs"]
            if save not in outs:
                raise RuntimeError("comfy failed: %s" % hist[pid].get("status"))
            img = outs[save]["images"][0]
            data = cg.get("/view?filename=%s&subfolder=%s&type=%s" % (img["filename"], img["subfolder"], img["type"]))
            return Image.open(io.BytesIO(data)).convert("RGB")
        time.sleep(1)


def hero_neg(pos):
    for h in HEROES.values():
        if h["look"] in pos:
            return h.get("neg", "")
    return ""


def txt2img(pos, neg, seed, w, h):
    neg = neg + hero_neg(pos)
    import workflows as W
    wf = W.fill(_wf_common(pos, neg, None, seed, 30, 6.0, 1.0, "j3"), {"畫布": {"width": w, "height": h}})
    return run_wf(wf)


def img2img(img, pos, neg, seed, denoise, mask=None):
    neg = neg + hero_neg(pos)
    tmp = os.path.join(os.environ.get("TEMP", "."), "j3_%s.png" % uuid.uuid4().hex)
    img.save(tmp)
    import workflows as W
    wf = _wf_common(pos, neg, None, seed, 30, 6.0, denoise, "j3i", "inpaint" if mask is not None else "img2img")
    W.fill(wf, {"輸入圖": {"image": cg.upload(tmp)}})
    if mask is not None:
        mtmp = tmp.replace(".png", "_m.png")
        Image.merge("RGB", (mask, mask, mask)).save(mtmp)
        W.fill(wf, {"遮罩": {"image": cg.upload(mtmp)}})
        os.remove(mtmp)
    out = run_wf(wf)
    os.remove(tmp)
    return out


# ------------------------------------------------------------------ face crop helpers
CASCADE = os.path.join(os.path.dirname(__file__), "models", "lbpcascade_animeface.xml")  # nagadomi, MIT


def face_box(plate):
    """Square box around the head, in plate pixels, from the anime face cascade (largest hit in the top half).
    Returns (box, (face_cx, face_cy, face_h))."""
    import cv2
    g = cv2.equalizeHist(cv2.cvtColor(np.asarray(plate), cv2.COLOR_RGB2GRAY))
    det = cv2.CascadeClassifier(CASCADE)
    hits = []
    for nb in (4, 2, 1):   # goggles or a hand over the face: accept weaker hits before giving up
        hits = det.detectMultiScale(g, scaleFactor=1.03, minNeighbors=nb, minSize=(40, 40))
        # a full-body figure's face is 4-18% of the image height, in the upper part
        hits = [h for h in hits if h[1] + h[3] / 2 < plate.height * 0.45 and 0.04 < h[3] / plate.height < 0.18]
        if hits:
            break
    if not hits:
        raise RuntimeError("no face found")
    big = max(r[2] * r[3] for r in hits)
    x, y, w, h = min([r for r in hits if r[2] * r[3] >= 0.5 * big], key=lambda r: r[1])
    cx, cy, hh = x + w / 2.0, y + h * 0.5, float(h)
    side = int(max(192, hh * 2.4))
    x0 = int(np.clip(cx - side / 2, 0, plate.width - side))
    y0 = int(np.clip(cy - side * 0.5, 0, plate.height - side))
    return (x0, y0, x0 + side, y0 + side), (cx, cy, hh)


def _ellipse_mask(size, center, radii, feather):
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    d = ((xx - center[0]) / radii[0]) ** 2 + ((yy - center[1]) / radii[1]) ** 2
    m = (np.clip(1.0 - d, 0, 1) > 0).astype(np.uint8) * 255
    return Image.fromarray(m).filter(ImageFilter.GaussianBlur(feather))


def refine_face(plate, box, pos, seed, denoise=0.35):
    """Upscale the head crop to 768, repaint lightly, paste back with a soft edge (sharper eyes)."""
    crop = plate.crop(box).resize((768, 768), Image.LANCZOS)
    out = img2img(crop, pos + ", face focus, detailed eyes", "", seed, denoise)
    side = box[2] - box[0]
    small = out.resize((side, side), Image.LANCZOS)
    m = _ellipse_mask((side, side), (side / 2, side / 2), (side * 0.46, side * 0.46), side * 0.05)
    res = plate.copy()
    res.paste(small, box[:2], m)
    return res


def expression(plate, box, info, pos, name, seed):
    """Inpaint the face only (upscaled crop), composite back so the rest is untouched."""
    extra, neg = EXPRESSIONS[name]
    side = box[2] - box[0]
    cx, cy, hh = info
    crop = plate.crop(box).resize((768, 768), Image.LANCZOS)
    k = 768.0 / side
    fc = ((cx - box[0]) * k, (cy - box[1]) * k)
    # the face oval: eyes, brows, mouth, cheeks (blush); keeps hair and ears
    fm = _ellipse_mask((768, 768), (fc[0], fc[1]), (0.44 * hh * k, 0.46 * hh * k), 10)
    out = img2img(crop, pos + ", face focus, " + extra, neg, seed, 0.75, mask=fm)
    out = Image.composite(out, crop, fm)
    small = out.resize((side, side), Image.LANCZOS)
    m = fm.resize((side, side), Image.LANCZOS)
    res = plate.copy()
    res.paste(small, box[:2], m)
    return res


# ------------------------------------------------------------------ commands
def plates(work, hero, series, seeds=(101, 102, 103, 104)):
    """Candidate plates to pick from; `gen` with J3_SEED=<seed> then builds the chosen one."""
    d = os.path.join(work, hero, series, "cand")
    os.makedirs(d, exist_ok=True)
    pos = plate_prompt(hero, series)
    for sd in seeds:
        txt2img(pos, PLATE_NEG, sd, 832, 1216).save(os.path.join(d, "%d.png" % sd))
    print(hero, series, "candidates ->", d)


def gen(work, hero, series):
    seed = int(os.environ.get("J3_SEED", "101"))
    d = os.path.join(work, hero, series)
    os.makedirs(d, exist_ok=True)
    # J3_PLATE: a candidate's file name when it isn't just the seed (a touched-up one like "101_bow12")
    cand = os.path.join(d, "cand", "%s.png" % os.environ.get("J3_PLATE", seed))
    if os.path.exists(cand):
        plate = Image.open(cand).convert("RGB")
    else:
        pos = plate_prompt(hero, series)
        plate = txt2img(pos, PLATE_NEG, seed, 832, 1216)
    plate.save(os.path.join(d, "plate_raw.png"))
    box, info = face_box(plate)
    face_pos = prompt_for(hero, series, "portrait")
    plate = refine_face(plate, box, face_pos, seed)
    plate.save(os.path.join(d, "plate.png"))
    for i, name in enumerate(EXPRESSIONS):
        expression(plate, box, info, face_pos, name, seed + 7 * (i + 1)).save(os.path.join(d, "expr_%s.png" % name))
    print(hero, series, "plate + expressions ->", d)


def scene(work, hero, series, seed=202):
    d = os.path.join(work, hero, series)
    os.makedirs(d, exist_ok=True)
    _, bg, pose = OUTFITS[hero][series]
    pos = prompt_for(hero, series, "%s, %s, scenery, detailed background, cowboy shot, rating_questionable" % (pose, bg))
    img = txt2img(pos, ", simple background", seed, 1216, 832)
    img.save(os.path.join(d, "scene.png"))
    print(hero, series, "scene ->", d)


def install(work, hero, series):
    d = os.path.join(work, hero, series)
    out = os.path.join(d, "out")
    args = [sys.executable, PROCESS, "process", os.path.join(d, "plate.png"), out, "--id", hero]
    for name in EXPRESSIONS:
        args += ["--variant", "%s=%s" % (name, os.path.join(d, "expr_%s.png" % name))]
    subprocess.run(args, check=True)
    dest = _C.plate_dir(hero, series)   # live2d.toml [paths] plates
    os.makedirs(dest, exist_ok=True)
    for f in os.listdir(out):
        if f.endswith(".png") and not f.startswith("_") or f == "meta.json":
            shutil.copy(os.path.join(out, f), os.path.join(dest, f))
    sc = os.path.join(d, "scene.png")
    if os.path.exists(sc):
        Image.open(sc).convert("RGB").save(os.path.join(dest, "scene.jpg"), quality=88)
    print("installed", hero, series, "->", dest)


def main():
    cmd, work, hero = sys.argv[1], sys.argv[2], sys.argv[3]
    series_list = sys.argv[4:] or list(OUTFITS[hero])
    for s in series_list:
        {"plates": plates, "gen": gen, "scene": scene, "install": install}[cmd](work, hero, s)


if __name__ == "__main__":
    main()
