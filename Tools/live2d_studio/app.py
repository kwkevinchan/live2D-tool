"""Live 2D 工作室: one local web page for the animated portraits' fixed flow 甲 (Docs/Design/22b, code flow
Docs/Code/Live2D.md section 10).

    myenv/Scripts/python.exe Tools/live2d_studio/app.py      (or Tools/live2d_studio/start.bat) -> http://127.0.0.1:7861

Tabs: 總覽 (every hero's folders and how far each got), 資料夾 (one plate through 甲: split, cut the pieces, six packs
with the part and assembly checks, mouth shapes, rig, check against the plate, the character's standard motions,
the weapon and objects on their own, then together), 狀態 (ComfyUI and the GPU). Key poses, skills and animation
are only in the design doc for now (the owner, 2026-10-01). Long jobs run the command line tools as subprocesses and
stream their output. The work lives outside the repo (live2d.toml [paths] work); ComfyUI and the GPU are shared
with the art studio (Tools/studio, port 7860).
"""
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

import gradio as gr
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ART = os.path.join(ROOT, "Tools", "art")
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "Tools", "art"))
import config as _C   # live2d.toml  # noqa: E402
COMFY = _C.COMFY_DIR
MODELS = _C.MODELS
WORK = _C.WORK
LIVE = os.path.join(WORK, "live")
CHECK = os.path.join(LIVE, "check")
PREVIEW = os.path.join(LIVE, "preview")
ASSETS = os.path.join(ROOT, "Assets")
SERVER = _C.COMFY_URL
GODOT = _C.GODOT
DECISIONS = os.path.join(WORK, "review_decisions.json")   # shared with the art studio; Claude reads it and acts on it

HERO_NAMES = {"alicia": "艾莉西亞", "freya": "芙蕾雅", "yukino": "雪乃", "rena": "蕾娜"}
POSE_NAMES = {"idle": "待機", "raise": "舉起", "draw": "拉弓", "release": "放箭", "cast": "施法", "recover": "收勢",
              "open": "展扇", "sweep": "橫掃", "point": "指向", "windup": "蓄力", "slam": "砸地", "impact": "扛肩",
              "apose": "A 字站姿", "ready": "預備"}
SKIN_NAMES = {"A": "休假日", "B": "星夜祭典", "C": "職業交換", "D": "夏日海灘", "E": "月下晚宴", "F": "裂隙侵蝕",
              "G": "深夜私語", "H": "賽車女郎", "I": "新年和服", "J": "婚禮"}
# each hero's skill: the key_poses.py action, the skill_preview.gd style and its poses in order
# the one plate the fixed flow 甲 is run on now (the owner: one character's one plate at a time); the folder tab is
# locked to it. Set to None to choose freely again.
FOCUS = ("freya", "pose_apose")

SKILLS = {"alicia": ("bow", "bow", ["raise", "draw", "release"], "弓：舉弓 → 拉滿 → 放箭"),
          "freya": ("staff", "fire", ["raise", "cast", "recover"], "爆炎球：舉杖聚火 → 出招 → 收勢"),
          "yukino": ("fan", "frost", ["open", "sweep", "point"], "冰封：展扇 → 橫掃 → 指向"),
          "rena": ("wrench", "slam", ["windup", "slam", "impact"], "部署：蓄力 → 砸地 → 扛肩")}


# ------------------------------------------------------------------ helpers
def comfy_up() -> bool:
    try:
        urllib.request.urlopen(SERVER + "/system_stats", timeout=2)
        return True
    except Exception:
        return False


def run(args, needs_comfy=False, exe=None, env_extra=None):
    """run a tool (a Tools/art script, or Godot with exe=GODOT) and yield its growing log"""
    if needs_comfy and not comfy_up():
        yield "ComfyUI 沒有開：到「狀態」分頁按「啟動 ComfyUI」。"
        return
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    env.update(env_extra or {})
    cmd = ([exe] if exe else [PY]) + args
    p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace")
    log = "執行：%s %s\n\n" % (os.path.basename(cmd[0 if exe else 1]), " ".join(a if len(a) < 90 else "…" + a[-60:] for a in cmd[1 if exe else 2:]))
    yield log
    for line in p.stdout:
        if exe and any(k in line for k in ("WASAPI", "audio driver", "Unicode parsing")):   # Godot's harmless noise
            continue
        log += line
        yield log[-6000:]
    p.wait()
    yield log[-6000:] + ("\n完成。" if p.returncode == 0 else "\n失敗（代碼 %d）。" % p.returncode)


def folder_label(series):
    if series == "-":
        return "主設計"
    if series.startswith("pose_"):
        return "姿勢：" + POSE_NAMES.get(series[5:], series[5:])
    return "造型：%s（%s）" % (SKIN_NAMES.get(series, series), series)


def folders(hero):
    """the hero's work folders (outfits and key poses) in a stable order: outfits first, then poses"""
    d = os.path.join(LIVE, hero)
    if not os.path.isdir(d):
        return []
    fs = [f for f in os.listdir(d) if os.path.isdir(os.path.join(d, f))]
    return sorted(fs, key=lambda f: (f.startswith("pose_"), f))


def folder_choices(hero):
    return [(folder_label(f), f) for f in folders(hero)]


def fdir(hero, series):
    return os.path.join(LIVE, hero, series)


def plate_of(hero, series):
    d = fdir(hero, series)
    if os.path.exists(os.path.join(d, "full.png")):
        return os.path.join(d, "full.png")
    a = os.path.join(ASSETS, "Heroines", hero) if series == "-" else os.path.join(ASSETS, "Heroines", hero, "skins", series)
    return os.path.join(a, "full.png") if os.path.exists(os.path.join(a, "full.png")) else None


def model_of(hero, series):
    ms = glob.glob(os.path.join(fdir(hero, series), "*.inx"))
    return max(ms, key=os.path.getmtime) if ms else None


def check_name(hero, series):
    return "%s_%s" % (hero, "default" if series == "-" else series)


def check_results():
    p = os.path.join(CHECK, "rig_check.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def review_of(hero, series):
    p = os.path.join(fdir(hero, series), "review.json")
    try:
        return json.load(open(p, encoding="utf-8")).get("warnings", [])
    except (OSError, ValueError):
        return None


def decisions():
    """the owner's verdicts. A broken file stops the page instead of being read as empty: an empty read followed by
    a write would wipe every earlier verdict"""
    if not os.path.exists(DECISIONS):
        return {}
    try:
        return json.load(open(DECISIONS, encoding="utf-8"))
    except ValueError:
        raise gr.Error("review_decisions.json 讀不到（可能正在寫入），請等一下再按")


def when(path):
    return time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(path))) if path and os.path.exists(path) else ""


# ------------------------------------------------------------------ 總覽
def overview_rows():
    checks = check_results()
    dec = decisions()
    rows = []
    for hero in HERO_NAMES:
        for s in folders(hero):
            d = fdir(hero, s)
            st = os.path.join(d, "st", "parts.json")
            parts = len(json.load(open(st, encoding="utf-8")).get("order_back_to_front", [])) if os.path.exists(st) else 0
            rv = review_of(hero, s)
            v = dec.get("pose:%s:%s" % (hero, s[5:])) if s.startswith("pose_") else None
            m = model_of(hero, s)
            c = checks.get(check_name(hero, s))
            rows.append([HERO_NAMES[hero], folder_label(s),
                         "✓" if plate_of(hero, s) else "—",
                         "%d 層" % parts if parts else "—",
                         "—" if rv is None else ("✓" if not rv else "⚠ " + "；".join(rv)),
                         v["verdict"] if v else ("等你看" if rv is not None and s.startswith("pose_") else ""),
                         when(m) if m else "—",
                         "—" if not c else ("%s %.2f%%" % ("⚠" if c.get("flagged") else "✓", 100 * c.get("bad_share", 0)))])
    return rows


OVERVIEW_HEAD = ["英雄", "資料夾", "原圖", "細部分層", "自動審圖", "你的審核", "綁定時間", "跟原圖比"]


def overview_gallery():
    out = []
    for hero in HERO_NAMES:
        for s in folders(hero):
            p = plate_of(hero, s)
            if p:
                out.append((p, "%s・%s" % (HERO_NAMES[hero], folder_label(s))))
    return out


def check_all():
    yield from run([os.path.join(ART, "rig_check.py")])


# ------------------------------------------------------------------ 資料夾
PACK_TITLES = ["臉部（五官、臉部飾品、帽子、脖子、領口）", "頭髮", "軀幹與衣物", "四肢（連鞋子）", "武器", "其他物件"]


def folder_view(hero, series):
    """what the folder has, in the order the work goes"""
    if not series:
        return [], "這位英雄還沒有資料夾。"
    d = fdir(hero, series)
    out = []
    p = plate_of(hero, series)
    if p:
        out.append((p, "原圖"))
    gd = os.path.join(d, "st", "groups")
    for k, t in enumerate(PACK_TITLES, 1):   # check 1: the parts, pack by pack
        q = os.path.join(gd, "parts_%d.jpg" % k)
        if os.path.exists(q):
            out.append((q, "部件檢查 %d：%s" % (k, t)))
    for k, t in enumerate(PACK_TITLES, 1):   # check 2: the packs stacked one after another
        q = os.path.join(gd, "assemble_%d.jpg" % k)
        if os.path.exists(q):
            out.append((q, "組裝檢查 %d：%s%s" % (k, "臉部" if k == 1 else "＋" + t.split("（")[0], "（全部 vs 原圖）" if k == 6 else "")))
    for f, label in (("review.jpg", "審圖（原圖／骨架／分層分色）"),):
        if os.path.exists(os.path.join(d, f)):
            out.append((os.path.join(d, f), label))
    ck = os.path.join(CHECK, check_name(hero, series) + "_check.jpg")
    if os.path.exists(ck):
        out.append((ck, "綁定後 vs 原圖（藍＝少了、紅＝顏色不對、綠＝多出來）"))
    for f, label in (("mouth_a.png", "嘴型：啊"), ("mouth_i.png", "嘴型：咿"), ("mouth_o.png", "嘴型：喔"),
                     ("preview_figure.gif", "粗分層預覽（動）"), ("preview_scene.gif", "情境圖預覽（動）"),
                     ("scene_bg.png", "情境圖：補畫後的背景")):
        if os.path.exists(os.path.join(d, f)):
            out.append((os.path.join(d, f), label))
    out += [(q, "情境圖第 %s 層" % q[-5]) for q in sorted(glob.glob(os.path.join(d, "scene_layer*.png")))]
    for f, label in (("000_rest.png", "動態截圖：靜止"), ("030_yaw_right.png", "轉頭"), ("060_yaw_left_blink.png", "轉頭＋眨眼"),
                     ("090_mouth_open.png", "張嘴")):
        q = os.path.join(d, "_shots", f)
        if os.path.exists(q):
            out.append((q, label))
    m = model_of(hero, series)
    c = check_results().get(check_name(hero, series))
    try:
        g = json.load(open(os.path.join(gd, "groups.json"), encoding="utf-8"))
        gtxt = "全部組起來跟原圖差 %.2f%%%s" % (100 * g["packs"][-1].get("bad_share", 0),
                                          "；" + "；".join(g["warnings"]) if g["warnings"] else "，部件沒有發現問題")
    except (OSError, ValueError, KeyError, IndexError):
        gtxt = "還沒做"
    info = ["**%s・%s**" % (HERO_NAMES[hero], folder_label(series)),
            "細部分層：%s" % ("有（%s）" % when(os.path.join(d, "st", "parts.json")) if os.path.exists(os.path.join(d, "st", "parts.json")) else "還沒拆"),
            "分包與組裝檢查：%s" % gtxt,
            "綁定：%s" % ("%s（%s）" % (os.path.basename(m), when(m)) if m else "還沒綁"),
            "跟原圖比：%s" % ("還沒比" if not c else "%.2f%% 不同%s" % (100 * c["bad_share"], "，有問題" if c.get("flagged") else "，通過"))]
    return out, "\n\n".join(info)


def do_split(hero, series):
    yield from run([os.path.join(ART, "see_through.py"), hero, series], needs_comfy=True)


def do_groups(hero, series):
    yield from run([os.path.join(ART, "split_groups.py"), hero, series])


def do_check_shots(hero, series):
    for step in (do_check, do_shots):
        last = ""
        for log in step(hero, series):
            last = log
            yield log
        if "失敗" in last[-40:] and step is do_shots:
            return


def do_review(hero, series):
    if not series.startswith("pose_"):
        yield "自動審圖目前只做姿勢資料夾。"
        return
    yield from run([os.path.join(ART, "review_plate.py"), hero, series[5:]])


def do_rig(hero, series):
    yield from run([os.path.join(ART, "inx_rig.py"), hero, series])


def do_check(hero, series):
    yield from run([os.path.join(ART, "rig_check.py"), "%s/%s" % (hero, series)])


def do_shots(hero, series):
    m = model_of(hero, series)
    if not m:
        yield "還沒綁定，先按「3. 綁定」。"
        return
    out = os.path.join(fdir(hero, series), "_shots")
    os.makedirs(out, exist_ok=True)
    yield from run(["--path", ROOT, "res://Tests/live/puppet_preview.tscn", "--", m, out], exe=GODOT)


def checkpoints():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(MODELS, "StableDiffusion", "*.safetensors"))
                  if not os.path.basename(p).startswith("ace_step"))


def do_layers(step, ckpt, hero, series, n=4):
    """live_layers.py: mouths (mouth shapes for talking), scene (the scene picture cut into depth layers), parts (the
    old coarse split), preview; the image model only matters for the inpainting steps (use the outfit's own style)"""
    args = [os.path.join(ART, "live_layers.py"), step, hero, series] + ([str(int(n))] if step == "scene" else [])
    yield from run(args, needs_comfy=step != "preview", env_extra={"ART_CKPT": ckpt} if ckpt else None)


MOTIONS = [("walk", "走路"), ("jump", "跳躍"), ("run", "跑步"), ("wave", "揮手"), ("head", "頭部動作"),
           ("face", "眨眼與表情"), ("idle", "呼吸待機"), ("hair", "甩頭"), ("hit", "受擊"), ("glance", "轉身看")]


def motions_dir(hero, series, whole=False):
    """the character's standard motions (weapon and objects hidden), or the whole model's (after both passed)"""
    return os.path.join(fdir(hero, series), "_motions_all" if whole else "_motions")


def do_motions(hero, series, whole=False):
    """the standard motions (Tests/live/motion_test.tscn): one GIF per motion, and what the model lacked. The
    character goes first on her own ("bare": no weapon, no objects); whole=True is the check after joining them"""
    m = model_of(hero, series)
    if not m:
        yield "還沒綁定，先按「4. 綁定」。"
        return
    if whole:
        ok, why = ready_to_join(hero, series)
        if not ok:
            yield "還不能整合：" + why
            return
    out = motions_dir(hero, series, whole)
    os.makedirs(out, exist_ok=True)
    last = ""
    for log in run(["--path", ROOT, "res://Tests/live/motion_test.tscn", "--", m, out] + ([] if whole else ["bare"]), exe=GODOT):
        last = log
        yield log
    made = 0
    for key, _ in MOTIONS:
        fr = sorted(glob.glob(os.path.join(out, key, "anim_*.png")))
        if not fr:
            continue
        ims = [Image.open(f).convert("RGB") for f in fr]
        box = crop_box(ims[len(ims) // 2])
        ims = [i.crop(box) for i in ims]
        ims[0].save(os.path.join(out, key + ".gif"), save_all=True, append_images=ims[1:], duration=66, loop=0)
        made += 1
    yield last + "\n做好 %d 個動作的動圖。" % made


def crop_box(img):
    """the figure's area in a motion frame, with room for jumps and runs"""
    import numpy as np
    a = np.asarray(img).astype(int)
    m = np.abs(a - a[2, 2]).sum(-1) > 30
    if not m.any():
        return (0, 0, img.width, img.height)
    ys, xs = np.nonzero(m)
    w = xs.max() - xs.min()
    return (max(0, xs.min() - w), 0, min(img.width, xs.max() + w), img.height)


def objects_dir(hero, series):
    return os.path.join(fdir(hero, series), "st", "groups", "objects")


def objects_result(hero, series):
    try:
        return json.load(open(os.path.join(objects_dir(hero, series), "objects.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def character_passed(hero, series):
    """the character's standard motions exist and none of them lacks anything"""
    try:
        rep = json.load(open(os.path.join(motions_dir(hero, series), "report.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return False, "人物的標準動作還沒做（6）"
    lack = [v["name"] for v in rep.values() if v.get("missing")]
    return (not lack), ("人物的標準動作還缺：" + "、".join(lack)) if lack else ""


def ready_to_join(hero, series):
    ok1, why1 = character_passed(hero, series)
    o = objects_result(hero, series)
    ok2 = bool(o and o.get("passed"))
    why2 = "" if ok2 else ("武器與物件還沒驗證（7）" if o is None else "武器與物件沒通過：" + "；".join(
        "%s %s" % (x["title"], "、".join(x["warnings"])) for x in o["objects"] if not x["passed"]))
    return ok1 and ok2, "；".join(w for w in (why1, why2) if w)


def do_objects(hero, series):
    if not os.path.exists(os.path.join(fdir(hero, series), "st", "groups", "groups.json")):
        yield "先做「2. 分成六包」。"
        return
    yield from run([os.path.join(ART, "object_check.py"), hero, series])


def part_names(hero, series):
    try:
        meta = json.load(open(os.path.join(fdir(hero, series), "st", "parts.json"), encoding="utf-8"))
        return [q["name"] for q in meta["order_back_to_front"]]
    except (OSError, ValueError, KeyError):
        return []


def do_outline(hero, series, part, drop, check=False):
    """steps 1-3 of an object (outline.py: its lines, completed, noise dropped) or step 5 (--check: whole?)"""
    if not part:
        yield "先選一個圖層。"
        return
    args = [os.path.join(ART, "outline.py"), hero, series, part]
    yield from run(args + (["--check"] if check else (["--drop", drop.strip()] if drop and drop.strip() else [])))


def do_fix_outline(hero, series, part, seeds):
    """step 4: colour inside the completed outline, held to it as line art"""
    if not part:
        yield "先選一個圖層。"
        return
    yield from run([os.path.join(ART, "object_fix.py"), hero, series, part, "--outline", "--seeds", seeds or "1,2,3"], needs_comfy=True)


def do_fix(hero, series, part, seeds, dry):
    """one object completed on its own (Tools/art/object_fix.py): what would be filled, or candidates from AI"""
    if not part:
        yield "先選一個圖層。"
        return
    args = [os.path.join(ART, "object_fix.py"), hero, series, part]
    yield from run(args + (["--dry"] if dry else ["--seeds", seeds or "1,2,3"]), needs_comfy=not dry)


def do_fix_apply(hero, series, part, seed):
    if not part or not str(seed).strip():
        yield "先選圖層，再填要用第幾號（seed）。"
        return
    yield from run([os.path.join(ART, "object_fix.py"), hero, series, part, "--apply", str(int(seed))])


def fix_view(hero, series, part):
    st = os.path.join(fdir(hero, series), "st")
    out = []
    for f, cap in ((os.path.join(st, "outline", "%s.jpg" % part), "輪廓：綠＝畫出來的邊、紅＝切開的邊、黃＝刪掉的、藍＝補上的線、洋紅＝要上色的"),
                   (os.path.join(st, "fix", "%s.jpg" % part), "左：原本；洋紅：要補的地方；其餘：候選")):
        if part and os.path.exists(f):
            out.append((f, cap))
    return out


def objects_view(hero, series):
    d = objects_dir(hero, series)
    o = objects_result(hero, series)
    gal = []
    if os.path.exists(os.path.join(d, "objects_check.jpg")):
        gal.append((os.path.join(d, "objects_check.jpg"), "每 30 度轉一次"))
    gal += [(os.path.join(d, "object_%s.gif" % x["key"]), x["title"]) for x in (o or {}).get("objects", [])
            if os.path.exists(os.path.join(d, "object_%s.gif" % x["key"]))]
    if o is None:
        return gal, "武器與物件還沒驗證。"
    lines = ["%s：%s" % (x["title"], "通過" if x["passed"] else "、".join(x["warnings"])) for x in o["objects"]]
    return gal, "**武器與物件**：%s\n\n%s" % ("全部通過" if o["passed"] else "沒通過", "\n\n".join(lines))


def motions_view(hero, series, whole=False):
    out = motions_dir(hero, series, whole)
    try:
        rep = json.load(open(os.path.join(out, "report.json"), encoding="utf-8"))
    except (OSError, ValueError):
        rep = {}
    gal = [(os.path.join(out, k + ".gif"), n) for k, n in MOTIONS if os.path.exists(os.path.join(out, k + ".gif"))]
    lines = ["%s：%s" % (n, "缺 " + "、".join(rep[k]["missing"]) if rep.get(k, {}).get("missing") else "可以做") for k, n in MOTIONS if k in rep]
    head = "**%s**（%s）\n\n" % ("整合後的標準動作" if whole else "人物的標準動作（不含武器、物件）", when(os.path.join(out, "report.json")))
    return gal, (head + "\n\n".join(lines)) if lines else ("還沒做整合驗證。" if whole else "還沒做人物的標準動作。")


def do_all(hero, series):
    """rig, check, shots, the character's standard motions in one go (after a new split)"""
    for step in (do_rig, do_check, do_shots, do_motions):
        last = ""
        for log in step(hero, series):
            last = log
            yield log
        if "失敗" in last[-40:]:
            return


# ------------------------------------------------------------------ 狀態
def status_text():
    lines = ["**ComfyUI**：%s　[打開 ComfyUI 網頁](%s)" % ("執行中" if comfy_up() else "沒有開", SERVER)]
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        lines.append("**顯示卡**：%s" % gpu)
    except Exception:
        pass
    lines.append("**Godot**：%s" % ("有" if os.path.exists(GODOT) else "找不到（設定環境變數 GODOT）"))
    lines.append("顯示卡和 ComfyUI 跟美術工作室共用：拆層、姿勢候選、動畫這些長時間的工作，Claude 開始前會先通知美術工具箱，避免撞在一起。")
    return "\n\n".join(lines)


def start_comfy():
    if not comfy_up():
        log = open(os.path.join(WORK, "comfyui.log"), "w", encoding="utf-8")
        subprocess.Popen([os.path.join(COMFY, "venv", "Scripts", "python.exe"), "main.py", "--listen", "127.0.0.1", "--port", "8188"],
                         cwd=COMFY, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(90):
            if comfy_up():
                break
            time.sleep(2)
    return status_text()


# ------------------------------------------------------------------ page
def build():
    os.makedirs(PREVIEW, exist_ok=True)
    heroes = [(n, h) for h, n in HERO_NAMES.items()]
    with gr.Blocks(title="Live 2D 工作室") as ui:
        gr.Markdown("# 星晶守望者・Live 2D 工作室\n會動的立繪：拆層 → 綁定 → 跟原圖比 → 技能姿勢 → 預覽。遊戲裡用的是臉部動態加關鍵姿勢淡入切換。")
        with gr.Tab("總覽"):
            with gr.Row():
                ov_refresh = gr.Button("重新整理")
                ov_check = gr.Button("全部重新跟原圖比（約 1 分鐘）")
            ov_table = gr.Dataframe(headers=OVERVIEW_HEAD, value=overview_rows(), interactive=False, wrap=True)
            ov_log = gr.Textbox(label="進度", lines=3, max_lines=8, autoscroll=True)
            ov_gal = gr.Gallery(overview_gallery(), columns=8, height=420, object_fit="contain", label="全部的原圖")
            ov_refresh.click(lambda: (overview_rows(), overview_gallery()), None, [ov_table, ov_gal])
            ov_check.click(check_all, None, ov_log).then(overview_rows, None, ov_table)
        with gr.Tab("資料夾"):
            with gr.Row():
                fh, fs = FOCUS or ("alicia", (folders("alicia") or [None])[0])
                f_hero = gr.Radio(heroes, value=fh, label="英雄", interactive=FOCUS is None)
                f_series = gr.Dropdown(folder_choices(fh), value=fs, label="資料夾", interactive=FOCUS is None)
            if FOCUS:
                gr.Markdown("**目前專注的立繪：%s・%s**（一次只跑一張；要換在 `app.py` 的 `FOCUS` 改）" % (HERO_NAMES[FOCUS[0]], folder_label(FOCUS[1])))
            with gr.Row():
                with gr.Column(scale=3):
                    f_gal = gr.Gallery(columns=4, height=640, object_fit="contain", label="這個資料夾")
                    f_mgal = gr.Gallery(columns=5, height=420, object_fit="contain", label="人物的標準動作（不含武器、物件）")
                    f_minfo = gr.Markdown()
                    f_ogal = gr.Gallery(columns=5, height=300, object_fit="contain", label="武器與物件")
                    f_oinfo = gr.Markdown()
                    f_jgal = gr.Gallery(columns=5, height=420, object_fit="contain", label="整合後的標準動作")
                    f_jinfo = gr.Markdown()
                with gr.Column(scale=2):
                    f_info = gr.Markdown()
                    gr.Markdown("### 甲、固定流程（依序按）")
                    b_split = gr.Button("1. 拆層（See Through，約 8 分鐘，要 ComfyUI）")
                    b_groups = gr.Button("2. 分成六包＋部件檢查＋組裝檢查")
                    cks = checkpoints()
                    l_ck = gr.Dropdown(cks, value=next((c for c in cks if "Pony" in c), cks[0] if cks else None),
                                       label="嘴型用的模型（要跟這張立繪原本的畫風一樣）")
                    b_mouth = gr.Button("3. 嘴型差分（閉／啊／咿／喔，要 ComfyUI）")
                    b_rig = gr.Button("4. 綁定")
                    b_check = gr.Button("5. 跟原圖比＋動態截圖（轉頭、眨眼、張嘴）")
                    b_motion = gr.Button("6. 人物的標準動作驗證（不含武器、物件；走路、跳躍、跑步、揮手、頭部……共 10 個）")
                    b_all = gr.Button("4～6 一次做完", variant="primary")
                    b_obj = gr.Button("7. 武器與物件獨立驗證（完整、轉一圈）")
                    b_join = gr.Button("8. 整合驗證（6、7 都通過才能做：帶武器的標準動作）")
                    with gr.Accordion("單獨補一個物件（先輪廓、後顏色）", open=False):
                        x_part = gr.Dropdown(part_names(fh, fs), label="圖層")
                        x_drop = gr.Textbox("", label="要刪掉的區塊編號（看輪廓檢查圖上的黃色數字，例如 2,3；可留空）")
                        x_seeds = gr.Textbox("1,2,3", label="候選的 seed")
                        x_line = gr.Button("1～3 抽輪廓、補齊線條、刪掉輪廓外的噪點")
                        x_color = gr.Button("4 照輪廓補顏色（候選，要 ComfyUI）")
                        with gr.Row():
                            x_pick = gr.Number(label="用第幾號（seed）", precision=0)
                            x_apply = gr.Button("換上這張")
                        x_check = gr.Button("5 檢查完整度")
                        with gr.Row():
                            x_dry = gr.Button("舊補法：先看要補哪裡")
                            x_go = gr.Button("舊補法：補畫候選")
                        x_gal = gr.Gallery(columns=1, height=300, object_fit="contain", label="補畫前後")
                    with gr.Accordion("其他工具", open=False):
                        b_review = gr.Button("審圖（原圖疊骨架，姿勢資料夾）")
                        with gr.Row():
                            l_n = gr.Slider(2, 6, value=4, step=1, label="情境圖背景分幾層")
                            b_scene = gr.Button("情境圖：去背、補畫背景、分層")
                        b_parts = gr.Button("粗分層（骨架＋SAM2，See Through 拆不好時的備案）")
                        b_prev = gr.Button("粗分層／情境圖預覽動圖")
                    f_log = gr.Textbox(label="進度", lines=8, max_lines=14, autoscroll=True)
            f_hero.change(lambda h: gr.update(choices=folder_choices(h), value=(folders(h) or [None])[0]), f_hero, f_series)
            f_series.change(folder_view, [f_hero, f_series], [f_gal, f_info])
            for b, step in ((b_mouth, "mouths"), (b_parts, "parts"), (b_prev, "preview")):
                b.click(lambda c, h, s, _st=step: (yield from do_layers(_st, c, h, s)), [l_ck, f_hero, f_series], f_log).then(
                    folder_view, [f_hero, f_series], [f_gal, f_info])
            b_scene.click(lambda c, h, s, n: (yield from do_layers("scene", c, h, s, n)), [l_ck, f_hero, f_series, l_n], f_log).then(
                folder_view, [f_hero, f_series], [f_gal, f_info])
            for b, fn in ((b_split, do_split), (b_groups, do_groups), (b_review, do_review), (b_rig, do_rig), (b_check, do_check_shots),
                          (b_motion, do_motions), (b_all, do_all)):
                b.click(fn, [f_hero, f_series], f_log).then(folder_view, [f_hero, f_series], [f_gal, f_info]).then(
                    motions_view, [f_hero, f_series], [f_mgal, f_minfo])
            f_series.change(motions_view, [f_hero, f_series], [f_mgal, f_minfo])
            f_series.change(lambda h, s: gr.update(choices=part_names(h, s), value=None), [f_hero, f_series], x_part)
            x_part.change(fix_view, [f_hero, f_series, x_part], x_gal)
            x_dry.click(lambda h, s, p, sd: (yield from do_fix(h, s, p, sd, True)), [f_hero, f_series, x_part, x_seeds], f_log).then(
                fix_view, [f_hero, f_series, x_part], x_gal)
            x_go.click(lambda h, s, p, sd: (yield from do_fix(h, s, p, sd, False)), [f_hero, f_series, x_part, x_seeds], f_log).then(
                fix_view, [f_hero, f_series, x_part], x_gal)
            x_line.click(lambda h, s, p, d: (yield from do_outline(h, s, p, d)), [f_hero, f_series, x_part, x_drop], f_log).then(
                fix_view, [f_hero, f_series, x_part], x_gal)
            x_color.click(do_fix_outline, [f_hero, f_series, x_part, x_seeds], f_log).then(fix_view, [f_hero, f_series, x_part], x_gal)
            x_check.click(lambda h, s, p: (yield from do_outline(h, s, p, "", True)), [f_hero, f_series, x_part], f_log)
            x_apply.click(do_fix_apply, [f_hero, f_series, x_part, x_pick], f_log).then(folder_view, [f_hero, f_series], [f_gal, f_info])
            f_series.change(objects_view, [f_hero, f_series], [f_ogal, f_oinfo])
            f_series.change(lambda h, s: motions_view(h, s, True), [f_hero, f_series], [f_jgal, f_jinfo])
            b_obj.click(do_objects, [f_hero, f_series], f_log).then(objects_view, [f_hero, f_series], [f_ogal, f_oinfo])
            b_join.click(lambda h, s: (yield from do_motions(h, s, True)), [f_hero, f_series], f_log).then(
                lambda h, s: motions_view(h, s, True), [f_hero, f_series], [f_jgal, f_jinfo])
        with gr.Tab("狀態"):
            st = gr.Markdown(status_text())
            with gr.Row():
                gr.Button("啟動 ComfyUI", variant="primary").click(start_comfy, outputs=st)
                gr.Button("重新整理").click(status_text, outputs=st)
        ui.load(folder_view, [f_hero, f_series], [f_gal, f_info])
        ui.load(motions_view, [f_hero, f_series], [f_mgal, f_minfo])
        ui.load(objects_view, [f_hero, f_series], [f_ogal, f_oinfo])
        ui.load(lambda h, s: motions_view(h, s, True), [f_hero, f_series], [f_jgal, f_jinfo])
    return ui


if __name__ == "__main__":
    build().queue().launch(server_name="127.0.0.1", server_port=7861, inbrowser="--no-browser" not in sys.argv,
                           allowed_paths=[WORK, ASSETS])
