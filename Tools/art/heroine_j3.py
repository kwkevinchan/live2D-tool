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

HEROES = {
    "alicia": {"age": 22, "look": "blonde hair, long high ponytail, green hair ribbon, green eyes, confident smile",
               "weapon": "(holding bow (weapon):1.3), wooden longbow, arrow quiver"},
    "freya": {"age": 26, "look": "red hair, long wavy hair, red eyes, mole under eye, alluring smile",
              "weapon": "holding wooden staff with fire orb"},
    "yukino": {"age": 24, "look": "silver hair, very long straight hair, blunt bangs, snowflake hair ornament, light blue eyes, "
                       "gentle smile", "weapon": "holding folding fan with snowflake pattern"},
    "rena": {"age": 23, "look": "(lavender hair:1.3), purple hair, high ponytail, yellow hair ribbon, goggles on head, amber eyes, grin",
             "neg": ", blonde hair, yellow hair, orange hair",
             "weapon": "holding giant wrench over shoulder"},
}

# outfit: what she wears on the plate and in the scene. scene: (background, pose) for the wardrobe picture.
OUTFITS = {
    "alicia": {
        "-": ("(short blue capelet:1.2) with gold trim, white strapless corset top, deep cleavage, bare shoulders, "
              "bare midriff, brown leather belt, very short green pleated miniskirt, brown gloves, "
              "brown thigh-high boots, bare thighs",
              "forest clearing, sunlight through trees, mossy log", "sitting on a log, legs crossed, bow across lap, "
              "leaning forward, smile"),
        "A": ("white off-shoulder crop top, bare midriff, denim short shorts, bare legs, brown ankle boots, "
              "straw hat", "grassy meadow, white horse in background, blue sky",
              "sitting in the grass, leaning back on hands, knees up, relaxed smile"),
        "B": ("green yukata with floral pattern, loose collar, bare shoulders, short hem, bare thighs, "
              "red obi, hair ornament, paper fan", "summer festival at night, lanterns, fireworks in sky",
              "sitting on a wooden bench, holding candy apple, looking back over shoulder"),
        "C": ("black witch hat, black corset dress, deep cleavage, high slit, bare thigh, sheer black sleeves, "
              "thigh-high stockings", "witch's study, candles, bookshelves, cauldron",
              "sitting on a desk, legs crossed, holding spellbook, playful smile"),
        "D": ("green bikini, frilled bikini, sarong, cleavage, bare midriff, bare legs, sunglasses on head",
              "tropical beach, sparkling sea, palm trees, blue sky",
              "lying on side on a beach towel, head propped on hand, water gun beside her, wink"),
        "E": ("emerald green evening gown, strapless, deep cleavage, bare back, high leg slit, bare thigh, "
              "long white gloves, gold necklace", "moonlit palace balcony, night sky, full moon, roses",
              "leaning on balcony railing, looking over shoulder, hand extended to viewer"),
        "F": ("dark purple armor bikini, corrupted armor, purple glowing crystals, cleavage, bare midriff, "
              "torn black cape, thigh boots, purple eyes glow", "dark rift portal, purple lightning, ruins",
              "kneeling on one knee, drawing a glowing purple bow, fierce look"),
        "G": ("mint green silk negligee, lace trim, thin straps, cleavage, short hem, bare legs, sheer robe "
              "falling off shoulders", "bedroom at night, candle light, white sheets, window moonlight",
              "lying on a bed on her stomach, legs up behind her, chin on hands, seductive smile"),
        "H": ("race queen outfit, white and green bodysuit, highleg, cleavage cutout, bare shoulders, "
              "white thigh-high boots, holding umbrella", "race circuit, pit lane, racing car, checkered flags",
              "sitting on a race car hood, one leg raised, umbrella on shoulder, confident smile"),
        "I": ("short furisode kimono, red and white floral, loose collar, bare shoulders, short hem, "
              "bare thighs, white tabi socks, hamaya arrow", "shrine at new year, torii gate, snow, red lanterns",
              "sitting on shrine stairs, legs to one side, holding hamaya arrow, gentle smile"),
        "J": ("white wedding dress, strapless, sweetheart neckline, cleavage, sheer veil, short front long back "
              "skirt, bare legs, white rose bouquet", "chapel garden, white roses, arch, petals falling",
              "sitting on a garden bench, veil blowing, bouquet in lap, loving smile"),
    },
    "freya": {
        "-": ("black witch hat with red band, black and red corset dress, deep cleavage, bare shoulders, sheer black "
              "sleeves, very high leg slit, bare thigh, gold jewelry, black high heels",
              "witch tower room at night, candles, floating magic flames, bookshelves",
              "sitting on a velvet armchair, legs crossed, chin on hand, fire orb floating beside her"),
        "A": ("off-shoulder red knit sweater, bare shoulders, black mini skirt, bare legs, ankle boots, hair down",
              "cafe terrace in town, afternoon sun, flower pots",
              "sitting at a cafe table, legs crossed, holding tea cup, relaxed smile"),
        "B": ("red yukata with goldfish pattern, loose collar, bare shoulders, short hem, bare thighs, black obi, "
              "hair up, kanzashi", "summer festival at night, goldfish scooping stall, lanterns",
              "crouching by a goldfish pool, holding a paper scoop, looking up at viewer, playful smile"),
        "C": ("light silver knight armor, bikini armor, cleavage, bare midriff, red cape, thigh-high armored boots, "
              "holding sword", "castle courtyard, banners, blue sky",
              "sitting on castle steps, sword resting on shoulder, teasing smile"),
        "D": ("red bikini, string bikini, cleavage, bare midriff, sheer black beach cover-up, sun hat, sunglasses",
              "beach under a parasol, sparkling sea, beach chair, iced tea",
              "lying on a beach chair, one knee up, holding sunscreen bottle, inviting smile"),
        "E": ("crimson red evening gown, off-shoulder, deep cleavage, bare back, high leg slit, bare thigh, "
              "long black gloves, ruby necklace", "grand ballroom, chandeliers, dancing crowd blurred",
              "leaning on a pillar, hip out, hand extended to viewer, confident smile"),
        "F": ("dark purple witch outfit, corrupted, purple glowing crystals, cleavage, bare midriff, torn black cape, "
              "purple flames, purple eyes glow", "dark rift portal, purple lightning, ruins",
              "floating in the air, legs crossed, purple fire in palm, fierce smile"),
        "G": ("black lace negligee, thin straps, cleavage, short hem, bare legs, sheer black robe slipping off shoulder",
              "bedroom at night, single lamp, dark red sheets",
              "lying on side on a bed, head propped on hand, looking at viewer, seductive smile"),
        "H": ("race queen outfit, red and black bodysuit, highleg, cleavage cutout, bare shoulders, "
              "black thigh-high boots, holding umbrella", "race circuit, pit lane, racing car, checkered flags",
              "leaning back against a race car, one leg bent, umbrella on shoulder, wink"),
        "I": ("short black and red furisode kimono, floral, loose collar, bare shoulders, short hem, bare thighs, "
              "holding folding fan", "shrine at new year, torii gate, snow, red lanterns",
              "sitting on shrine stairs, legs crossed, fan covering mouth, sly eyes"),
        "J": ("white wedding dress, strapless, sweetheart neckline, cleavage, high leg slit, bare thigh, sheer veil, "
              "red rose bouquet", "chapel at night, candles, red roses, stained glass",
              "sitting on the chapel altar steps, bouquet in lap, veil over shoulder, tender smile"),
    },
    "yukino": {
        "-": ("white and light blue miko outfit, detached wide sleeves, bare shoulders, cleavage, short blue hakama skirt, "
              "bare thighs, white thigh-high socks, zouri sandals", "snowy shrine, torii gate, falling snow, stone lanterns",
              "kneeling seiza on the shrine veranda, fan in lap, gentle smile"),
        "A": ("white off-shoulder blouse, light blue high-waist skirt, short skirt, bare legs, sandals, hair loose",
              "flower garden, white flowers, soft sunlight",
              "sitting on a garden swing, legs together, hands on the ropes, shy smile"),
        "B": ("white and blue yukata with snowflake pattern, loose collar, bare shoulders, short hem, bare thighs, "
              "light blue obi", "riverside at night, fireworks in sky, lanterns",
              "sitting on the riverbank, legs to one side, looking up at the fireworks, soft smile"),
        "C": ("mechanic outfit, unzipped jumpsuit tied at waist, white tube top, cleavage, bare midriff, bare shoulders, "
              "holding wrench, oil smudge on cheek", "workshop, gears, tools on the wall, warm light",
              "sitting on a workbench, legs dangling, holding a wrench, embarrassed smile, blush"),
        "D": ("white bikini, frilled bikini, cleavage, bare midriff, light blue sarong, flower in hair",
              "beach shallows, gentle waves, sunset",
              "sitting in shallow water, legs to one side, hands on chest, shy, blush"),
        "E": ("silver white evening gown, off-shoulder, cleavage, bare back, high leg slit, bare thigh, "
              "long white gloves, snowflake tiara", "moonlit terrace, snow, night sky",
              "dancing pose, skirt twirling, looking over shoulder, gentle smile"),
        "F": ("dark purple and black miko outfit, corrupted, purple glowing crystals, cleavage, bare shoulders, "
              "short hakama, purple eyes glow", "dark rift portal, purple ice shards, ruins",
              "kneeling on one knee, fan raised, purple frost swirling, cold expression"),
        "G": ("white silk slip dress, thin straps, cleavage, short hem, bare legs, hand on chest",
              "japanese bedroom at night, futon, moonlight through shoji",
              "sitting on a futon, knees together, leaning forward, shy, heavy blush"),
        "H": ("race queen outfit, ice blue and white bodysuit, highleg, cleavage cutout, bare shoulders, "
              "white thigh-high boots, holding umbrella", "race circuit, pit lane, racing car, checkered flags",
              "sitting on a tire stack, knees together, umbrella held with both hands, shy smile"),
        "I": ("short white and light blue furisode kimono, floral, loose collar, bare shoulders, short hem, "
              "bare thighs, white tabi socks, holding folding fan", "shrine at new year, torii gate, heavy snow",
              "standing under a red umbrella in snow, fan held to chest, looking at viewer, soft smile"),
        "J": ("white wedding dress, strapless, sweetheart neckline, cleavage, sheer veil, short front long back skirt, "
              "bare legs, white camellia bouquet", "snowy garden chapel, white camellias, soft light",
              "sitting on a white bench, bouquet held to chest, veil flowing, teary happy smile"),
    },
    "rena": {
        "-": ("cropped navy jacket with yellow stripes, white tube top, cleavage, bare midriff, black short shorts, "
              "tool belt, bare thighs, yellow work boots", "workshop, gears, sparks, machines, warm light",
              "sitting on a big crate, one leg up, wrench over shoulder, grin"),
        "A": ("orange overalls with one strap down, white crop top, bare midriff, cleavage, bare shoulders, "
              "short shorts, sneakers", "garage, motorbike, tools, sunlight",
              "sitting on a motorbike seat, legs crossed, holding a screwdriver, cheeky grin"),
        "B": ("purple yukata with firework pattern, loose collar, bare shoulders, short hem, bare thighs, yellow obi, "
              "fox mask on head", "summer festival at night, food stalls, cotton candy, lanterns",
              "sitting on a stool, holding cotton candy and squid skewer, happy open mouth"),
        "C": ("red and white miko outfit, detached sleeves, bare shoulders, cleavage, short red hakama, bare thighs",
              "shrine grounds, autumn leaves", "sitting on shrine steps, confused pout, holding gohei"),
        "D": ("yellow bikini, sporty bikini, cleavage, bare midriff, holding homemade water jet pack",
              "beach, sea spray, smoke from gadget, blue sky",
              "sitting in the sand wet, laughing, gadget smoking beside her, one eye closed"),
        "E": ("lavender evening gown, strapless, cleavage, high leg slit, bare thigh, long gloves, gear hair ornament",
              "ballroom balcony, night, city lights",
              "sitting on the balcony railing, holding skirt, flustered, blush, pout"),
        "F": ("dark purple mechanic outfit, corrupted, purple glowing crystals, cleavage, bare midriff, "
              "purple lightning, purple eyes glow", "dark rift portal, purple lightning, ruins",
              "crouching on a broken machine, wrench crackling with purple electricity, wild grin"),
        "G": ("lavender satin pajamas, unbuttoned top, cleavage, bare midriff, short pajama shorts, bare legs, "
              "hugging pillow", "bedroom at night, workbench in corner, small lamp",
              "lying on her stomach on a bed, hugging a pillow, legs kicking up, blush, pout"),
        "H": ("race queen outfit, purple and yellow bodysuit, highleg, cleavage cutout, bare shoulders, "
              "yellow thigh-high boots, waving checkered flag", "race circuit, pit lane, racing car",
              "standing on a race car, waving a checkered flag, energetic pose, big grin"),
        "I": ("short purple and yellow furisode kimono, floral, loose collar, bare shoulders, short hem, bare thighs, "
              "holding hagoita paddle", "shrine at new year, torii gate, snow",
              "jumping pose, swinging hagoita paddle, shuttlecock in air, big grin"),
        "J": ("white wedding dress, strapless, sweetheart neckline, cleavage, short front long back skirt, bare legs, "
              "lavender bouquet with small gears", "flower garden chapel, lavender field",
              "sitting on a garden swing, bouquet in lap, blushing, embarrassed smile"),
    },
}

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
    dest = os.path.join(ROOT, "Assets", "Heroines", hero) if series == "-" else \
        os.path.join(ROOT, "Assets", "Heroines", hero, "skins", series)
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
