"""The project's settings: live2d.toml at the repo root (paths, ComfyUI, Godot, MV-Adapter, the checkpoint) and one
characters/<id>.toml per character (look, weapon, LoRA, outfits). Environment variables win over the files:
ART_WORK, ART_PLATES, COMFY_URL, COMFY_DIR, GODOT, ART_CKPT.

    import config as C
    C.WORK, C.PLATES, C.COMFY_URL, C.GODOT, C.CKPT, C.MV["python"]
    C.plate_dir("freya", "C")          # where the plate (full.png) of an outfit lives
    C.CHARACTERS["freya"]["lora"]
"""
import glob
import os
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_cfg_path = os.environ.get("LIVE2D_CONFIG", os.path.join(ROOT, "live2d.toml"))
_cfg = tomllib.load(open(_cfg_path, "rb")) if os.path.exists(_cfg_path) else {}
_paths = _cfg.get("paths", {})
_comfy = _cfg.get("comfyui", {})


def _p(env, key, default=""):
    v = os.environ.get(env) or _paths.get(key) or default
    return os.path.normpath(os.path.expandvars(os.path.expanduser(v))) if v else ""


WORK = _p("ART_WORK", "work", os.path.join(ROOT, "art_work"))   # everything the tools make (outside the repo)
PLATES = _p("ART_PLATES", "plates", os.path.join(ROOT, "plates"))   # <plates>/<id>/full.png, <plates>/<id>/skins/<outfit>/full.png
GODOT = _p("GODOT", "godot")
COMFY_URL = os.environ.get("COMFY_URL") or _comfy.get("url", "http://127.0.0.1:8188")
COMFY_DIR = os.path.normpath(os.environ.get("COMFY_DIR") or _comfy.get("dir", ""))   # to start it from the studio
COMFY_OUT = os.path.normpath(_comfy.get("output", ""))   # where ComfyUI saves images (the split reads its layers there)
CKPT = os.environ.get("ART_CKPT") or _cfg.get("models", {}).get("checkpoint", "waiIllustriousSDXL_v170.safetensors")
MODELS = os.path.normpath(_cfg.get("models", {}).get("dir", ""))   # the model folder (MV-Adapter reads files there)
MV = {k: os.path.normpath(v) for k, v in _cfg.get("mvadapter", {}).items()}   # python, repo, configs
STUDIO = _cfg.get("studio", {})   # the Live 2D studio: focus ("<hero>/<series>"), outfit_names

CHARACTERS = {}
for f in sorted(glob.glob(os.path.join(ROOT, "characters", "*.toml"))):
    c = tomllib.load(open(f, "rb"))
    CHARACTERS[c.get("id") or os.path.basename(f)[:-5]] = c


def plate_dir(hero, series):
    """the folder holding an outfit's plate: <plates>/<hero> for the main design ("-"), <plates>/<hero>/skins/<series>"""
    return os.path.join(PLATES, hero) if series in ("-", "") else os.path.join(PLATES, hero, "skins", series)


def character(hero):
    if hero not in CHARACTERS:
        raise KeyError("no characters/%s.toml" % hero)
    return CHARACTERS[hero]
