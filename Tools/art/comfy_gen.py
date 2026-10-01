"""Generate sprites through a local ComfyUI server (SDXL / Pony checkpoint).

Usage:
  python comfy_gen.py <out_dir> <name> "<subject prompt>" [--seeds 1,2,3] [--w 1024 --h 1024]
  python comfy_gen.py <out_dir> <name> "<subject prompt>" --init base.png --denoise 0.4   (img2img)

Writes <out_dir>/<name>_<seed>.png. Background removal is a separate step (cutout.py).
"""
import argparse, json, os, time, urllib.request, uuid

SERVER = "http://127.0.0.1:8188"
# the checkpoint every tool uses; the art studio (Tools/studio) and ART_CKPT pick another one
CKPT = os.environ.get("ART_CKPT", "autismmixSDXL_autismmixPony.safetensors")
# Pony checkpoints read "score_9 ... source_anime" quality tags; Illustrious ones read "masterpiece, best quality ..."
ILLUSTRIOUS = ("waiIllustrious", "illustrious", "noob", "hassaku", "nova")
PONY_TAGS = ("score_9", "score_8_up", "score_7_up", "score_6_up", "score_4", "score_5", "score_6",
             "source_anime", "source_cartoon", "source_pony", "source_furry")
RATING = {"rating_safe": "general", "rating_questionable": "sensitive", "rating_explicit": "explicit"}
# Illustrious reads danbooru tags literally: "lineart" means an uncoloured line drawing (2026-09-29: every LoRA test
# came out black and white), so style words about lines are dropped and colour is asked for instead
IL_DROP = ("lineart", "clean lineart", "delicate lineart", "thick dark outline", "vector art style", "source_cartoon")


def family(ckpt=None):
    c = (ckpt or CKPT).lower()
    return "illustrious" if any(k.lower() in c for k in ILLUSTRIOUS) else "pony"


def adapt(text, negative=False, ckpt=None):
    """rewrite a Pony-style prompt for the checkpoint in use (Illustrious: other quality tags and rating words)"""
    if family(ckpt) == "pony":
        return text
    parts = [t.strip() for t in text.split(",")]
    parts = [RATING.get(t, t) for t in parts if t and t not in PONY_TAGS and t not in IL_DROP]
    head = "worst quality, low quality, lowres, bad anatomy, monochrome, greyscale, lineart, sketch" if negative else         "masterpiece, best quality, amazing quality, very aesthetic, anime coloring"
    return head + ", " + ", ".join(parts)


def add_lora(wf):
    """ART_LORA="file.safetensors:0.8" (and ART_LORA_TRIGGER): put a LoraLoader right after the checkpoint"""
    spec = os.environ.get("ART_LORA", "")
    ck = next((k for k, n in wf.items() if n.get("class_type") == "CheckpointLoaderSimple"), None)
    if not spec or ck is None or any(n.get("class_type") == "LoraLoader" for n in wf.values()):
        return wf
    name, _, strength = spec.partition(":")
    s = float(strength or 0.8)
    for node in wf.values():
        for k, v in node.get("inputs", {}).items():
            if isinstance(v, list) and len(v) == 2 and str(v[0]) == ck and v[1] in (0, 1):
                node["inputs"][k] = ["90", v[1]]
    wf["90"] = {"class_type": "LoraLoader", "inputs": {"model": [ck, 0], "clip": [ck, 1], "lora_name": name,
                "strength_model": s, "strength_clip": s}, "_meta": {"title": "角色 LoRA"}}
    trig = os.environ.get("ART_LORA_TRIGGER", "")
    if trig:
        for node in wf.values():
            if node.get("_meta", {}).get("title") == "正面提示詞":
                node["inputs"]["text"] = trig + ", " + node["inputs"]["text"]
    return wf


def adapt_workflow(wf):
    """adapt every text prompt in a ComfyUI workflow (negatives are the ones wired to a sampler's 'negative').
    Music workflows are left alone: their checkpoint is the music model, not the picture one"""
    if any(str(n.get("class_type", "")).startswith("SaveAudio") for n in wf.values()):
        return wf
    add_lora(wf)
    negs = set()
    for node in wf.values():
        neg = node.get("inputs", {}).get("negative")
        if isinstance(neg, list):
            negs.add(str(neg[0]))
    for nid, node in wf.items():
        if node.get("class_type") == "CLIPTextEncode" and isinstance(node["inputs"].get("text"), str):
            node["inputs"]["text"] = adapt(node["inputs"]["text"], nid in negs)
        if node.get("class_type") == "CheckpointLoaderSimple":
            node["inputs"]["ckpt_name"] = CKPT
    return wf

STYLE = ("score_9, score_8_up, score_7_up, source_cartoon, "
         "game asset, cute chibi mobile game sprite, single character, full body, "
         "side view, facing right, thick dark outline, clean flat colors, simple cel shading, "
         "vector art style, plain white background, centered")
NEG = ("score_4, score_5, score_6, realistic, photo, 3d render, text, watermark, signature, "
       "multiple views, character sheet, cropped, border, frame, scenery, ground, shadow, "
       "blurry, jpeg artifacts, nsfw, human")


PRESETS = {
    "sprite": (STYLE, NEG),
    # Heroine illustrations: this Pony checkpoint is strongest at anime characters.
    "heroine": ("score_9, score_8_up, score_7_up, source_anime, rating_safe, 1girl, solo, "
                "full body, standing, looking at viewer, game character illustration, detailed eyes, "
                "clean lineart, soft cel shading, simple background, white background",
                "score_4, score_5, score_6, nsfw, nude, cleavage, underwear, lowres, bad anatomy, bad hands, "
                "extra fingers, missing fingers, extra limbs, text, watermark, signature, multiple views, "
                "cropped, out of frame, blurry, jpeg artifacts, 3d, realistic"),
}
PRESETS["chibi"] = (
    "score_9, score_8_up, score_7_up, source_anime, rating_safe, 1girl, solo, chibi, super deformed, "
    "full body, standing, game character sprite, cute, big head, anime coloring, soft shading, clean lineart, "
    "simple background, white background, centered",
    PRESETS["heroine"][1] + ", realistic proportions, tall, multiple girls, 2girls, multiple views, "
    "reference sheet, mini person, clone, scenery, detailed background, gradient background, floor, shadow")
# Repaint of the SVG sprites (img2img): keep the shapes, add anime-style rendering to match the portraits.
PRESETS["repaint"] = (
    "score_9, score_8_up, score_7_up, source_anime, rating_safe, game asset, anime style, "
    "detailed anime shading, soft gradient shading, rim light, clean lineart, vibrant colors, "
    "white background, centered, no humans",
    "score_4, score_5, score_6, realistic, photo, 3d render, text, watermark, signature, blurry, "
    "jpeg artifacts, multiple views, cropped, frame, border, scenery, nsfw, 1girl, human")
PRESETS["scenery"] = (
    "score_9, score_8_up, score_7_up, source_anime, rating_safe, scenery, no humans, anime background art, "
    "fantasy, detailed background, soft lighting, vibrant colors, wide shot, masterpiece",
    "score_4, score_5, score_6, 1girl, 1boy, human, character, text, watermark, signature, blurry, "
    "jpeg artifacts, frame, border, ui, nsfw, realistic, photo, 3d")
PRESET = "sprite"


def workflow(prompt, seed, w, h, steps=28, cfg=6.5):
    import workflows as W
    style, neg = PRESETS[PRESET]
    return W.fill(W.load("txt2img"), {"正面提示詞": {"text": f"{style}, {prompt}"}, "排除詞": {"text": neg},
        "畫布": {"width": w, "height": h}, "採樣": {"seed": seed, "steps": steps, "cfg": cfg}})


def img2img_workflow(prompt, seed, image_name, denoise, steps=30, cfg=6.0):
    import workflows as W
    style, neg = PRESETS[PRESET]
    return W.fill(W.load("img2img"), {"正面提示詞": {"text": f"{style}, {prompt}"}, "排除詞": {"text": neg},
        "輸入圖": {"image": image_name}, "採樣": {"seed": seed, "steps": steps, "cfg": cfg, "denoise": denoise}})


def upload(path):
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{os.path.basename(path)}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + data + \
           f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(SERVER + "/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req).read())["name"]


def post(path, data):
    if path == "/prompt":   # every tool queues through here: fit the prompts to the checkpoint in use
        data["prompt"] = adapt_workflow(data["prompt"])
    req = urllib.request.Request(SERVER + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def get(path):
    return urllib.request.urlopen(SERVER + path).read()


def run(prompt, seed, w, h, init=None, denoise=1.0):
    wf = img2img_workflow(prompt, seed, upload(init), denoise) if init else workflow(prompt, seed, w, h)
    pid = post("/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())})["prompt_id"]
    save = next(k for k, n in wf.items() if n.get("class_type") == "SaveImage")
    while True:
        hist = json.loads(get(f"/history/{pid}"))
        if pid in hist:
            outs = hist[pid]["outputs"][save]["images"]
            img = outs[0]
            return get(f"/view?filename={img['filename']}&subfolder={img['subfolder']}&type={img['type']}")
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("name")
    ap.add_argument("prompt")
    ap.add_argument("--seeds", default="1")
    ap.add_argument("--w", type=int, default=1024)
    ap.add_argument("--h", type=int, default=1024)
    ap.add_argument("--init", help="init image for img2img")
    ap.add_argument("--denoise", type=float, default=0.45)
    ap.add_argument("--preset", default="sprite", choices=sorted(PRESETS))
    a = ap.parse_args()
    global PRESET
    PRESET = a.preset
    os.makedirs(a.out_dir, exist_ok=True)
    for s in [int(x) for x in a.seeds.split(",")]:
        data = run(a.prompt, s, a.w, a.h, a.init, a.denoise if a.init else 1.0)
        path = os.path.join(a.out_dir, f"{a.name}_{s}.png")
        with open(path, "wb") as f:
            f.write(data)
        print(path)


if __name__ == "__main__":
    main()
