"""Other view angles of a heroine from one plate, with MV-Adapter (huanngzh/MV-Adapter, ICCV 2025, Apache-2.0)
on our own SDXL checkpoint + her character LoRA, so the new angles keep the look (2026-10-01, the owner's pipeline:
complete what a single front view can't show).

Runs in its own venv (live2d.toml [mvadapter] python: MV-Adapter pins old diffusers / transformers; torch comes
from ComfyUI's venv through a .pth file) and needs the MV-Adapter repo ([mvadapter] repo).

    mvadapter-env/Scripts/python.exe Tools/art/multiview.py <plate.png> <out_dir> --lora freya [--prompt "..."]

Writes view_<azimuth>.png (768 px squares on grey) and views.jpg (all in a row).
"""
import argparse
import os
import sys

import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as _C   # live2d.toml [mvadapter], [models]
sys.path.insert(0, _C.MV["repo"])
from mvadapter.pipelines.pipeline_mvadapter_i2mv_sdxl import MVAdapterI2MVSDXLPipeline   # noqa: E402
from mvadapter.schedulers.scheduling_shift_snr import ShiftSNRScheduler                   # noqa: E402
from diffusers import AutoencoderKL                                                        # noqa: E402


def _load(path, name):
    """one MV-Adapter file by path: its utils package pulls in 3D texturing (nvdiffrast, triton) we never call"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


get_plucker_embeds_from_cameras_ortho = _load(os.path.join(_C.MV["repo"], "mvadapter", "utils", "geometry.py"),
                                              "mv_geometry").get_plucker_embeds_from_cameras_ortho


def camera_c2w(azimuth_deg, distance=1.8, device="cuda"):
    """camera-to-world matrices on a level circle (MV-Adapter's mesh_utils.camera.get_c2w, elevation 0)"""
    import math
    import torch.nn.functional as F
    n = len(azimuth_deg)
    az = torch.tensor(azimuth_deg, dtype=torch.float32, device=device) * math.pi / 180
    dist = torch.full((n,), distance, dtype=torch.float32, device=device)
    pos = torch.stack([dist * torch.cos(az), dist * torch.sin(az), torch.zeros_like(az)], dim=-1)
    up = torch.tensor([0, 0, 1], dtype=torch.float32, device=device)[None, :].repeat(n, 1)
    lookat = F.normalize(-pos, dim=-1)
    right = F.normalize(torch.cross(lookat, up, dim=-1), dim=-1)
    up = F.normalize(torch.cross(right, lookat, dim=-1), dim=-1)
    c2w = torch.cat([torch.stack([right, up, -lookat], dim=-1), pos[:, :, None]], dim=-1)
    c2w = torch.cat([c2w, torch.zeros_like(c2w[:, :1])], dim=1)
    c2w[:, 3, 3] = 1.0
    return c2w

MODELS = _C.MODELS
CKPT = os.path.join(MODELS, "StableDiffusion", _C.CKPT)
ADAPTER = os.path.join(MODELS, "MVAdapter")
VIEWS = [0, 90, 180, 270]   # 6 views at once overflowed 16 GB (2026-10-01): front, right, back, left


def pipeline(lora=None, lora_scale=float(os.environ.get("MV_LORA_SCALE", "0.3"))):   # 0.8 overpowered the camera: every view came out frontal
    vae = AutoencoderKL.from_pretrained(os.path.join(ADAPTER, "sdxl-vae-fp16-fix"), torch_dtype=torch.float16)
    # the SDXL configs and tokenizers (3 MB) sit in a plain folder: the HF cache uses symlinks Windows refuses
    pipe = MVAdapterI2MVSDXLPipeline.from_single_file(CKPT, config=_C.MV["configs"], vae=vae,
                                                      torch_dtype=torch.float16)
    pipe.scheduler = ShiftSNRScheduler.from_scheduler(pipe.scheduler, shift_mode="interpolated", shift_scale=8.0)
    pipe.init_custom_adapter(num_views=len(VIEWS))
    pipe.load_custom_adapter(ADAPTER, weight_name="mvadapter_i2mv_sdxl.safetensors")
    # the whole pipe on the GPU (model CPU offload broke MV-Adapter's reference attention: KeyError on the processors);
    # 4 views instead of 6 keep it inside 16 GB
    pipe.to(device="cuda", dtype=torch.float16)
    pipe.cond_encoder.to(device="cuda", dtype=torch.float16)
    if lora:
        # the character's LoRA file (characters/<id>.toml "lora"), or a file name given as it is
        name = _C.CHARACTERS[lora]["lora"] if lora in _C.CHARACTERS else lora
        pipe.load_lora_weights(os.path.join(MODELS, "Lora"), weight_name=name)
        pipe.fuse_lora(lora_scale=lora_scale)
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()
    return pipe


def square(plate, size=768):
    """the figure centred on grey, 90% of the square (as MV-Adapter's own preprocessing)"""
    im = plate.convert("RGBA")
    box = im.split()[3].getbbox()
    im = im.crop(box)
    k = size * 0.9 / max(im.size)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    bg = Image.new("RGBA", (size, size), (127, 127, 127, 255))
    bg.alpha_composite(im, ((size - im.width) // 2, (size - im.height) // 2))
    return bg.convert("RGB")


def run(plate, out, lora, prompt, seed=7, steps=40, cfg=3.0):
    os.makedirs(out, exist_ok=True)
    pipe = pipeline(lora)
    size = 768
    c2w = camera_c2w([x - 90 for x in VIEWS])
    ctrl = ((get_plucker_embeds_from_cameras_ortho(c2w, [1.1] * len(VIEWS), size) + 1.0) / 2.0).clamp(0, 1)
    ref = square(Image.open(plate))
    ref.save(os.path.join(out, "reference.png"))
    images = pipe(prompt, height=size, width=size, num_inference_steps=steps, guidance_scale=cfg,
                  num_images_per_prompt=len(VIEWS), control_image=ctrl, control_conditioning_scale=1.0,
                  reference_image=ref, reference_conditioning_scale=1.0,
                  negative_prompt="watermark, ugly, deformed, noisy, blurry, low contrast, extra limbs, two staffs, "
                                  "child, loli, nude",
                  generator=torch.Generator(device="cuda").manual_seed(seed)).images
    row = Image.new("RGB", (size * len(images), size))
    for i, (az, im) in enumerate(zip(VIEWS, images)):
        im.save(os.path.join(out, "view_%03d.png" % az))
        row.paste(im, (i * size, 0))
    row.save(os.path.join(out, "views.jpg"), quality=88)
    print("views ->", out, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("plate")
    ap.add_argument("out")
    ap.add_argument("--lora", default=None, help="a character id (characters/<id>.toml) or a LoRA file name")
    ap.add_argument("--prompt", default="high quality, anime, full body, standing")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    run(a.plate, a.out, a.lora, a.prompt, a.seed)
