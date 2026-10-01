"""Draw one object of a plate with an instruction-following edit model (the owner's idea, 2026-10-02, branch
explore): "draw the hat in this picture", the plate as the reference, the object painted whole on white.
Mage-Flow-Edit-Turbo (Microsoft, 4B, 4 steps) through ComfyUI's native nodes; needs ComfyUI.

    python Tools/art/object_edit.py <hero> <series> <part> --instr "..." [--seeds 1,2] [--mask <layer>[,...]]
                                    [--src orig] [--pad 0.25] [--extra <picture>[,...]]

1. the box: where the object's layer(s) are (st/_orig/ with --src orig), grown by --pad of its size each side;
2. the reference: the plate cut to that box on white (the whole figure in it, so the model sees what the object is
   part of); --extra pictures (another view angle) go in as further references;
3. the edit: the instruction, the output the size of the reference (edit models keep the framing, so the object
   lands where it is on the plate);
4. the white backdrop off (near-white joined to the border), put back at the plate's place: st/gen/<part>_e<seed>.png,
   and st/gen/<part>_edit.jpg (reference | each result on grey).
"""
import argparse
import os
import sys
import time
import uuid

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inx_rig import WORK   # noqa: E402

UNET = "mage_flow_edit_turbo_int8_convrot.safetensors"
CLIP = "qwen3vl_4b_fp8_scaled.safetensors"
VAE = "mage_flow_vae_bf16.safetensors"
# --engine qwen: Qwen-Image-Edit-2511 (ComfyUI template image_qwen_image_edit_2511; a .gguf model needs ComfyUI-GGUF)
QWEN_UNET = os.environ.get("QWEN_UNET", "qwen-image-edit-2511-Q4_K_M.gguf")
QWEN_CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
QWEN_VAE = "qwen_image_vae.safetensors"
QWEN_LORA = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"   # 4 steps (--fast)
# --engine gemini: Google AI Studio (GOOGLE_API_KEY, or the repo's .env, never committed); picture output needs a
# billed project (the free tier's image quota is 0, 2026-10-02)
GEMINI_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


def graph(instr, neg, seed, refs, w, h, steps=4, cfg=1.0):
    """the ComfyUI template image_mage_flow_edit_turbo_int8, flattened to the API format"""
    def n(cls, **inp):
        return {"class_type": cls, "inputs": inp}
    g = {
        "1": n("UNETLoader", unet_name=UNET, weight_dtype="default"),
        "3": n("CLIPLoader", clip_name=CLIP, type="mage", device="default"),
        "4": n("VAELoader", vae_name=VAE),
        "6": n("KSampler", model=["1", 0], positive=["5", 0], negative=["5", 1], latent_image=["5", 2], seed=seed,
               steps=steps, cfg=cfg, sampler_name="euler", scheduler="simple", denoise=1.0),
        "8": n("VAEDecode", samples=["6", 0], vae=["4", 0]),
        "9": n("SaveImage", images=["8", 0], filename_prefix="objedit"),
    }
    enc = {"clip": ["3", 0], "prompt": instr, "negative_prompt": neg, "width": w, "height": h, "batch_size": 1,
           "vae": ["4", 0]}
    for i, name in enumerate(refs, 1):
        g["2%d" % i] = n("LoadImage", image=name)
        enc["images.image_%d" % i] = ["2%d" % i, 0]
    g["5"] = n("TextEncodeMageFlowEdit", **enc)
    return g


def graph_qwen(instr, neg, seed, refs, fast=False):
    """the ComfyUI template image_qwen_image_edit_2511 flattened: the first reference scaled to the model's size and
    encoded as the start latent, every reference (up to 3) given to the text encoder; 40 steps at cfg 4, or 4 steps
    at cfg 1 with the Lightning LoRA (fast)"""
    def n(cls, **inp):
        return {"class_type": cls, "inputs": inp}
    g = {"1": n("UnetLoaderGGUF", unet_name=QWEN_UNET) if QWEN_UNET.endswith(".gguf")
         else n("UNETLoader", unet_name=QWEN_UNET, weight_dtype="default"),
         "2": n("CLIPLoader", clip_name=QWEN_CLIP, type="qwen_image", device="default"),
         "3": n("VAELoader", vae_name=QWEN_VAE),
         "4": n("ModelSamplingAuraFlow", model=["1", 0], shift=3.1),
         "5": n("CFGNorm", model=["4", 0], strength=1.0)}
    model = ["5", 0]
    if fast:
        g["6"] = n("LoraLoaderModelOnly", model=model, lora_name=QWEN_LORA, strength_model=1.0)
        model = ["6", 0]
    for i, name in enumerate(refs[:3], 1):
        g["2%d" % i] = n("LoadImage", image=name)
    g["30"] = n("FluxKontextImageScale", image=["21", 0])
    imgs = {"image1": ["30", 0]}
    imgs.update({"image%d" % i: ["2%d" % i, 0] for i in range(2, min(3, len(refs)) + 1)})
    g["31"] = n("TextEncodeQwenImageEditPlus", clip=["2", 0], vae=["3", 0], prompt=instr, **imgs)
    g["32"] = n("TextEncodeQwenImageEditPlus", clip=["2", 0], vae=["3", 0], prompt=neg, **imgs)
    g["33"] = n("FluxKontextMultiReferenceLatentMethod", conditioning=["31", 0], reference_latents_method="index_timestep_zero")
    g["34"] = n("FluxKontextMultiReferenceLatentMethod", conditioning=["32", 0], reference_latents_method="index_timestep_zero")
    g["35"] = n("VAEEncode", pixels=["30", 0], vae=["3", 0])
    g["36"] = n("KSampler", model=model, positive=["33", 0], negative=["34", 0], latent_image=["35", 0], seed=seed,
                steps=4 if fast else 40, cfg=1.0 if fast else 4.0, sampler_name="euler", scheduler="simple", denoise=1.0)
    g["37"] = n("VAEDecode", samples=["36", 0], vae=["3", 0])
    g["38"] = n("SaveImage", images=["37", 0], filename_prefix="objedit_qwen")
    return g


def gemini_key():
    k = os.environ.get("GOOGLE_API_KEY")
    if not k:
        env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
        if os.path.exists(env):
            k = next((l.split("=", 1)[1].strip() for l in open(env) if l.startswith("GOOGLE_API_KEY=")), None)
    if not k:
        raise SystemExit("no GOOGLE_API_KEY (environment or .env)")
    return k


def run_gemini(instr, images):
    """one picture from Google's image model: the instruction and the reference pictures in, a picture out"""
    import base64
    import io
    import json
    import urllib.error
    import urllib.request
    parts = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        parts.append({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}})
    parts.append({"text": instr})
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % GEMINI_MODEL,
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": gemini_key()})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        msg = json.loads(e.read()).get("error", {}).get("message", "")
        raise SystemExit("Gemini %d: %s" % (e.code, msg.splitlines()[0] if msg else ""))
    for c in r.get("candidates", []):
        for p in c.get("content", {}).get("parts", []):
            if "inlineData" in p:
                return Image.open(io.BytesIO(base64.b64decode(p["inlineData"]["data"]))).convert("RGB")
    raise SystemExit("Gemini gave no picture: %s" % str(r)[:300])


def unwhite(rgb):
    """alpha: off where the colour is near white and joined to the border"""
    white = rgb.min(-1) > 235
    lab, _ = ndimage.label(white)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    return ~np.isin(lab, list(edge))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("series")
    ap.add_argument("part")
    ap.add_argument("--instr", required=True)
    ap.add_argument("--neg", default="")
    ap.add_argument("--seeds", default="1,2")
    ap.add_argument("--mask", default="")
    ap.add_argument("--src", default="current", choices=["current", "orig"])
    ap.add_argument("--pad", type=float, default=0.25)
    ap.add_argument("--extra", default="", help="more reference pictures (another view angle), comma separated")
    ap.add_argument("--tag", default="", help="file tag: st/gen/<part>_<tag><seed>.png (default e / q / qf / g by engine)")
    ap.add_argument("--engine", default="mage", choices=["mage", "qwen", "gemini"],
                    help="mage: Mage-Flow-Edit-Turbo (local); qwen: Qwen-Image-Edit-2511 (local); gemini: Google (cloud)")
    ap.add_argument("--fast", action="store_true", help="--engine qwen: 4 steps with the Lightning LoRA")
    a = ap.parse_args()
    a.tag = a.tag or {"mage": "e", "qwen": "qf" if a.fast else "q", "gemini": "g"}[a.engine]
    ld = os.path.join(WORK, "live", a.hero, a.series)
    st = os.path.join(ld, "st")
    gd = os.path.join(st, "gen")
    os.makedirs(gd, exist_ok=True)
    full = Image.open(os.path.join(ld, "full.png")).convert("RGBA")
    area = np.zeros((full.height, full.width), bool)
    for nm in (a.mask or a.part).split(","):
        f = os.path.join(st, "_orig", "part_%s.png" % nm) if a.src == "orig" else os.path.join(st, "part_%s.png" % nm)
        if not os.path.exists(f):
            f = os.path.join(st, "part_%s.png" % nm)
        area |= np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 128
    ys, xs = np.nonzero(area)
    bw, bh = xs.max() - xs.min(), ys.max() - ys.min()
    x0, y0 = max(0, int(xs.min() - a.pad * bw)), max(0, int(ys.min() - a.pad * bh))
    x1, y1 = min(full.width, int(xs.max() + a.pad * bw)), min(full.height, int(ys.max() + a.pad * bh))
    x1, y1 = x0 + (x1 - x0) // 16 * 16, y0 + (y1 - y0) // 16 * 16   # the model works in steps of 16
    bg = Image.new("RGBA", full.size, (255, 255, 255, 255))
    bg.alpha_composite(full)
    ref = bg.crop((x0, y0, x1, y1)).convert("RGB")
    w, h = ref.size
    k = max(1.0, 1024.0 / max(w, h))   # small boxes are enlarged for the model, and brought back after
    W, H = int(w * k) // 16 * 16, int(h * k) // 16 * 16

    import comfy_gen as cg
    import heroine_j3 as j3
    tmp = os.path.join(os.environ.get("TEMP", "."), "oe_%s" % uuid.uuid4().hex)
    names = []
    pics = [ref.resize((W, H), Image.LANCZOS)] + [Image.open(e).convert("RGB") for e in a.extra.split(",") if e]
    if a.engine != "gemini":
        for i, im in enumerate(pics):
            im.save(tmp + "_%d.png" % i)
            names.append(cg.upload(tmp + "_%d.png" % i))
    os.environ.pop("ART_LORA", None)   # comfy_gen adds an SDXL LoRA when this is set: not for this model
    tiles = [(ref, "reference")]
    for sd in [int(s) for s in a.seeds.split(",") if s]:
        t0 = time.time()
        if a.engine == "mage":
            out = j3.run_wf(graph(a.instr, a.neg, sd, names, W, H))
        elif a.engine == "qwen":
            out = j3.run_wf(graph_qwen(a.instr, a.neg, sd, names, a.fast))
        else:   # the cloud model takes no seed: each call is simply another try
            out = run_gemini(a.instr, pics)
        out = out.resize((w, h), Image.LANCZOS)
        print("seed %d: %.0f s" % (sd, time.time() - t0), flush=True)
        rgb = np.asarray(out).astype(int)
        alpha = unwhite(rgb)
        res = np.zeros((full.height, full.width, 4), np.uint8)
        res[y0:y1, x0:x1, :3] = rgb
        res[y0:y1, x0:x1, 3] = np.where(alpha, 255, 0)
        Image.fromarray(res).save(os.path.join(gd, "%s_%s%d.png" % (a.part, a.tag, sd)))
        view = Image.new("RGB", (w, h), (200, 200, 205))
        sub = Image.fromarray(res[y0:y1, x0:x1])
        view.paste(sub, (0, 0), sub)
        tiles.append((out, "seed %d raw" % sd))
        tiles.append((view, "seed %d cut" % sd))
        print("seed %d: %d px" % (sd, int(alpha.sum())), flush=True)
    for f in os.listdir(os.path.dirname(tmp)):
        if f.startswith(os.path.basename(tmp)):
            os.remove(os.path.join(os.path.dirname(tmp), f))
    th = 360
    ims = [(t.resize((max(1, t.width * th // t.height), th)), c) for t, c in tiles]
    sheet = Image.new("RGB", (sum(i.width + 4 for i, _ in ims), th + 20), (40, 40, 48))
    x = 0
    for i, c in ims:
        sheet.paste(i, (x, 20))
        ImageDraw.Draw(sheet).text((x + 4, 4), c, fill=(255, 255, 255))
        x += i.width + 4
    sheet.save(os.path.join(gd, "%s_%s.jpg" % (a.part, a.tag)), quality=88)
    print("sheet ->", os.path.join(gd, "%s_%s.jpg" % (a.part, a.tag)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
