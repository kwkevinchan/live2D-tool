"""Key-pose plates for combat motions (pilot 2026-09-30: Alicia drawing a bow in 3 poses). Needs ComfyUI.

    python Tools/art/key_poses.py cand <hero> <action>          skeleton pictures + 4 candidates per pose
    python Tools/art/key_poses.py pick <hero> <action> <pose>=<seed> ...   cut out + blink -> art_work/live/<hero>/pose_<pose>/

Each pose is an OpenPose skeleton drawn in code (POSES), fed to the xinsir openpose ControlNet with the heroine's
character LoRA (face and hair stay hers) and her outfit tags. A picked plate gets full.png (cut out) and
full_blink.png (eyes closed by inpainting the face), the files Tools/art/live_layers.py and the Inochi2D rig read.
Outputs stay in the work folder; nothing goes into Assets.
"""
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "grok"))
import comfy_gen as cg      # noqa: E402
import heroine_j3 as j3     # noqa: E402
import workflows as W       # noqa: E402

WORK = os.environ.get("ART_WORK", r"C:\Users\kwkev\Tool\art_work")
W_, H_ = 832, 1216
SEEDS = tuple(int(x) for x in os.environ.get("POSE_SEEDS", "61,62,63,64").split(","))
LORA = {h: "%s_waiIllustriousSDXL_v170.safetensors" % h for h in ("alicia", "freya", "yukino", "rena")}
HOLD = {"alicia": "holding bow", "freya": "holding a crooked dark wooden staff with a red orb set in its curled top", "yukino": "holding folding fan", "rena": "holding wrench"}
# COCO-18: nose, neck, r_sho, r_elb, r_wri, l_sho, l_elb, l_wri, r_hip, r_knee, r_ank, l_hip, l_knee, l_ank,
#          r_eye, l_eye, r_ear, l_ear  (x, y as a share of the picture; "r" is the character's right)
_LEGS = [(0.53, 0.52), (0.57, 0.70), (0.59, 0.88), (0.45, 0.52), (0.41, 0.70), (0.38, 0.88)]
_HEAD = [(0.45, 0.16), (0.50, 0.24)]
_FACE = [(0.44, 0.145), (0.465, 0.145), (0.47, 0.155), (0.51, 0.155)]
POSES = {
    "bow": {
        "raise": _HEAD + [(0.57, 0.26), (0.62, 0.36), (0.55, 0.31), (0.44, 0.26), (0.36, 0.18), (0.29, 0.10)] + _LEGS + _FACE,
        "draw": _HEAD + [(0.57, 0.26), (0.65, 0.24), (0.48, 0.19), (0.44, 0.26), (0.30, 0.26), (0.16, 0.26)] + _LEGS + _FACE,
        "release": _HEAD + [(0.57, 0.26), (0.67, 0.25), (0.78, 0.20), (0.44, 0.26), (0.30, 0.26), (0.16, 0.26)] + _LEGS + _FACE,
    },
}
# the other heroes' skills (2026-10-01); they all act towards the left (the enemy side), like the bow
_STAND = [(0.46, 0.52), (0.42, 0.70), (0.39, 0.88), (0.54, 0.52), (0.58, 0.70), (0.61, 0.88)]
_LUNGE = [(0.46, 0.52), (0.38, 0.68), (0.33, 0.88), (0.54, 0.52), (0.58, 0.70), (0.64, 0.88)]
_FRONT = [(0.465, 0.145), (0.495, 0.145), (0.45, 0.155), (0.52, 0.155)]
_SHO = [(0.43, 0.26), (0.57, 0.26)]


def _pose(head, r_arm, l_arm, legs, face):
    """head = [nose, neck]; r_arm / l_arm = [elbow, wrist] (shoulders fixed)"""
    return head + [_SHO[0]] + r_arm + [_SHO[1]] + l_arm + legs + face


POSES["staff"] = {   # Freya, 爆炎球 (pose names as the live2d skill preview's style=fire): raise fire overhead, thrust the staff forward, recover
    # raise: both hands hold the staff upright in front, the orb at head height (a one-hand overhead raise was drawn
    # with the staff upside down in every try)
    "raise": _pose([(0.48, 0.16), (0.50, 0.24)], [(0.38, 0.36), (0.44, 0.30)], [(0.62, 0.36), (0.47, 0.36)], _STAND, _FRONT),
    "cast": _pose(_HEAD, [(0.33, 0.25), (0.22, 0.24)], [(0.47, 0.30), (0.36, 0.28)], _LUNGE, _FACE),
    "recover": _pose([(0.48, 0.16), (0.50, 0.24)], [(0.39, 0.38), (0.37, 0.50)], [(0.66, 0.30), (0.74, 0.26)], _STAND, _FRONT),
}
POSES["fan"] = {   # Yukino, 冰封: open the fan, sweep the frost, point the fan at the target
    "open": _pose([(0.48, 0.16), (0.50, 0.24)], [(0.40, 0.36), (0.47, 0.30)], [(0.61, 0.37), (0.63, 0.48)], _STAND, _FRONT),
    "sweep": [(0.5 + (x - 0.5) * 0.85, y) for x, y in   # pulled in: the fan and sleeves went past the frame
              _pose(_HEAD, [(0.33, 0.27), (0.22, 0.30)], [(0.64, 0.33), (0.72, 0.40)], _LUNGE, _FACE)],
    "point": _pose(_HEAD, [(0.34, 0.23), (0.25, 0.19)], [(0.62, 0.36), (0.57, 0.46)], _STAND, _FACE),
}
POSES["wrench"] = {   # Rena, 部署: wrench up, slam it into the ground, stand up with sparks around
    "windup": _pose([(0.48, 0.16), (0.50, 0.24)], [(0.44, 0.14), (0.50, 0.06)], [(0.60, 0.15), (0.53, 0.07)], _STAND, _FRONT),
    "slam": _pose(_HEAD, [(0.37, 0.40), (0.33, 0.58)], [(0.47, 0.42), (0.37, 0.58)],   # hands low: the grip is near the ground
                  [(0.46, 0.53), (0.38, 0.70), (0.36, 0.88), (0.54, 0.53), (0.62, 0.72), (0.64, 0.88)], _FACE),
    "impact": _pose([(0.48, 0.16), (0.50, 0.24)], [(0.37, 0.33), (0.42, 0.22)], [(0.63, 0.33), (0.68, 0.24)], _STAND, _FRONT),
}
POSES["stand"] = {   # the idle plate in the same style as the key poses (so a crossfade doesn't change the outfit)
    "idle": [(0.50, 0.16), (0.50, 0.24), (0.43, 0.26), (0.40, 0.38), (0.38, 0.48), (0.57, 0.26), (0.61, 0.38), (0.63, 0.48),
             (0.46, 0.52), (0.45, 0.70), (0.45, 0.88), (0.54, 0.52), (0.55, 0.70), (0.55, 0.88),
             (0.485, 0.145), (0.515, 0.145), (0.47, 0.155), (0.53, 0.155)],
}
# the rig's base plate (2026-10-01, the owner's motion plan): an A-pose, arms away from the body and the weapon held
# clear of it, so a turning arm uncovers almost nothing; poses themselves come from ready / skill plates and video
POSES["base"] = {
    "apose": [(0.50, 0.16), (0.50, 0.24), (0.43, 0.26), (0.36, 0.36), (0.30, 0.46), (0.57, 0.26), (0.64, 0.36), (0.70, 0.46),
              (0.46, 0.52), (0.44, 0.70), (0.43, 0.88), (0.54, 0.52), (0.56, 0.70), (0.57, 0.88),
              (0.485, 0.145), (0.515, 0.145), (0.47, 0.155), (0.53, 0.155)],
}
# the resting state in battle: ready to act (freya: side-on half crouch, staff slanted forward in both hands)
POSES["staff"]["ready"] = _pose(_HEAD, [(0.37, 0.34), (0.30, 0.40)], [(0.52, 0.34), (0.40, 0.40)],
                                [(0.46, 0.53), (0.39, 0.70), (0.34, 0.88), (0.54, 0.53), (0.60, 0.71), (0.64, 0.88)], _FACE)
APOSE = {"alicia": "holding the bow lowered at arm's length beside her, the bow not touching her body",
         "freya": "holding the staff upright at arm's length beside her, the staff not touching her body or dress",
         "yukino": "holding the closed folding fan at arm's length beside her",
         "rena": "holding the giant wrench upright at arm's length beside her, resting on the ground"}
IDLE = {"alicia": "holding a bow lowered at her side", "freya": "gripping the staff upright in her left hand, the staff standing on the ground beside her",
        "yukino": "holding a closed folding fan at her chest", "rena": "holding a giant wrench over her shoulder"}
ACTION_TAGS = {"stand": {"idle": "standing, {idle}, relaxed, gentle smile, looking at viewer, front view"},
               "base": {"apose": "a-pose, standing straight, arms held slightly away from the body, {apose}, neutral "
                                 "expression, looking at viewer, front view, symmetrical"},
               "staff": {"ready": "combat stance, half crouch, side-on, holding the staff slanted forward with both hands, "
                                   "the orb pointing ahead, alert, ready to cast",
                         "raise": "holding the staff upright in front of her with both hands, the red orb at the top next to her face, eyes closed, concentrating",
                         "cast": "thrusting the staff forward, other hand open and empty, palm forward, dynamic pose, side view, detailed face",
                         "recover": "holding the staff at her side, other arm sweeping outward, confident smile"},
               "fan": {"open": "opening a folding fan in front of her chest, snowflakes, calm, elegant",
                       "sweep": "sweeping a folding fan outward, dynamic pose, side view, whole body in frame, wide margins, "
                                "closed long pleated hakama like a skirt down to the ankles, legs hidden by the hakama",
                       "point": "pointing a folding fan at the viewer's left, frost, cold stare, hand on hip"},
               "wrench": {"windup": "arms up, both arms above head, holding one giant wrench high above her head with both hands, grin",
                          "slam": "slamming a giant wrench into the ground, the wrench head striking the floor at her feet, crouching, dynamic pose",
                          "impact": "holding a giant wrench on her shoulder, fist raised, cheeky grin"},
               "bow": {"raise": "raising a bow, reaching for an arrow, determined",
                       "draw": "drawing a bow, full draw, arrow nocked, bowstring pulled to the cheek, aiming, focused, side view",
                       "release": "releasing an arrow, arrow flying, bowstring snapping, follow-through, dynamic pose"}}
# OpenPose limb pairs and colours (the look the ControlNet was trained on)
LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13), (1, 0),
         (0, 14), (14, 16), (0, 15), (15, 17)]
COLOURS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85),
           (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
           (255, 0, 255), (255, 0, 170), (255, 0, 85)]


def skeleton_image(pts):
    img = Image.new("RGB", (W_, H_), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    p = [(x * W_, y * H_) for x, y in pts]
    for i, (a, b) in enumerate(LIMBS):
        c = COLOURS[i % len(COLOURS)]
        dr.line([p[a], p[b]], fill=tuple(int(v * 0.6) for v in c), width=9)
    for i, (x, y) in enumerate(p):
        dr.ellipse((x - 6, y - 6, x + 6, y + 6), fill=COLOURS[i])
    return img


# drawing slips the review sheets caught (2026-10-01): a second staff, a third leg
EXTRA_NEG = ", two staffs, multiple staffs, extra weapon, extra legs, three legs, extra arms, extra hands, extra limbs, "             "floating weapon, bad anatomy"
# the game draws the skill effects itself: painted fire, magic circles or floor flames double up and split into odd
# parts (live2d, 2026-10-01)
NO_FX = ", fire, flames, fireball, magic circle, rune circle, glowing effects, embers, particles, sparks, lightning, "         "electricity, ice wind, snowflakes"
POSE_NEG = {("yukino", "sweep"): ", side slit, slit hakama, bare legs, thighs, leg out of the skirt"}   # her hakama is closed
NO_FX_FOR = {("freya", None), ("yukino", "sweep"), ("rena", None)}
OVERHEAD = {("wrench", "windup")}   # arms above the head: the skeleton alone wasn't followed


def pose_workflow(strength=0.85, end=0.85):
    wf = W.load("txt2img")
    wf["20"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "xinsir_openpose_sdxl.safetensors"},
                "_meta": {"title": "骨架 ControlNet"}}
    wf["21"] = {"class_type": "LoadImage", "inputs": {"image": ""}, "_meta": {"title": "骨架圖"}}
    ks = W.node_id(wf, "採樣")
    pos, neg = wf[ks]["inputs"]["positive"], wf[ks]["inputs"]["negative"]
    wf["22"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": pos, "negative": neg, "control_net": ["20", 0],
                "image": ["21", 0], "strength": strength, "start_percent": 0.0, "end_percent": end}, "_meta": {"title": "套用骨架"}}
    wf[ks]["inputs"]["positive"] = ["22", 0]
    wf[ks]["inputs"]["negative"] = ["22", 1]
    return wf


def cand(hero, action):
    os.environ["ART_LORA"] = "%s:1.0" % LORA[hero]
    os.environ["ART_LORA_TRIGGER"] = "%s_tdc" % hero
    d = os.path.join(WORK, "poses", hero, action)
    os.makedirs(d, exist_ok=True)
    outfit = j3.OUTFITS[hero]["-"][0]
    look = ", ".join(t for t in j3.HEROES[hero]["look"].split(", ") if "smile" not in t)
    for pose, pts in POSES[action].items():
        sk = skeleton_image(pts)
        skp = os.path.join(d, "%s_skeleton.png" % pose)
        sk.save(skp)
        up = cg.upload(skp)
        for sd in SEEDS:
            out = os.path.join(d, "%s_%d.png" % (pose, sd))
            if os.path.exists(out):
                continue
            prompt = "1girl, solo, %d years old, %s, %s, %s, %s, full body, simple background, grey background" % (
                j3.HEROES[hero]["age"], look, outfit, ACTION_TAGS[action][pose].replace("{idle}", IDLE[hero]).replace("{apose}", APOSE[hero]), HOLD[hero])
            wf = W.fill(pose_workflow(*((1.1, 1.0) if (action, pose) in OVERHEAD else ())), {"正面提示詞": {"text": prompt}, "排除詞": {"text": j3.neg_base() + EXTRA_NEG + (
                                          NO_FX if (hero, None) in NO_FX_FOR or (hero, pose) in NO_FX_FOR else "") + POSE_NEG.get((hero, pose), "")},
                                          "畫布": {"width": W_, "height": H_}, "採樣": {"seed": sd}, "骨架圖": {"image": up}})
            j3.run_wf(wf).save(out)
            print(pose, sd, "done", flush=True)
    sheet(d, action)


def sheet(d, action):
    poses = list(POSES[action])
    tw, th = 200, 292
    img = Image.new("RGB", (tw * (len(SEEDS) + 1), th * len(poses)), (30, 26, 36))
    dr = ImageDraw.Draw(img)
    for r, pose in enumerate(poses):
        img.paste(Image.open(os.path.join(d, "%s_skeleton.png" % pose)).resize((tw, th)), (0, r * th))
        for c, sd in enumerate(SEEDS):
            p = os.path.join(d, "%s_%d.png" % (pose, sd))
            if os.path.exists(p):
                img.paste(Image.open(p).convert("RGB").resize((tw, th)), ((c + 1) * tw, r * th))
                dr.text(((c + 1) * tw + 4, r * th + 4), "%s %d" % (pose, sd), fill=(255, 230, 120))
    img.save(os.path.join(d, "sheet.jpg"), quality=86)
    print("sheet ->", os.path.join(d, "sheet.jpg"), flush=True)


def clear_background(plate, rgba):
    """the cutout keeps background enclosed between a staff and the body (2026-10-01: 12-18% of some figures was
    background grey). The plates are drawn on a flat colour, so large patches of that colour go transparent too"""
    import cv2
    import numpy as np
    rgb = np.asarray(plate.convert("RGB")).astype(int)
    edge = np.concatenate([rgb[:6].reshape(-1, 3), rgb[:, :6].reshape(-1, 3), rgb[:, -6:].reshape(-1, 3)])
    bg = np.median(edge, 0)
    near = (np.abs(rgb - bg).sum(2) < 24).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(near, connectivity=4)
    kill = np.zeros(near.shape, bool)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= 400:   # small grey bits (a buckle, a highlight) stay
            kill |= lab == i
    kill = cv2.dilate(kill.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    arr = np.asarray(rgba).copy()
    arr[kill, 3] = 0
    out = Image.fromarray(arr)
    return out, out.split()[3]


def pick(hero, action, picks):
    import heroine_process as hp
    d = os.path.join(WORK, "poses", hero, action)
    for spec in picks:
        pose, sd = spec.split("=")
        plate = Image.open(os.path.join(d, "%s_%s.png" % (pose, sd))).convert("RGB")
        out = os.path.join(WORK, "live", hero, "pose_%s" % pose)
        os.makedirs(out, exist_ok=True)
        _, alpha, rgba = hp.cutout(plate)
        rgba, alpha = clear_background(plate, rgba)
        rgba.save(os.path.join(out, "full.png"))
        try:
            import live_layers
            box, info = live_layers.face_of(plate)
            face_pos = j3.prompt_for(hero, "-", "portrait")
            os.environ["ART_LORA"] = "%s:1.0" % LORA[hero]
            os.environ["ART_LORA_TRIGGER"] = "%s_tdc" % hero
            bl = j3.expression(plate, box, info, face_pos, "blink", int(sd) + 7).convert("RGBA")
            bl.putalpha(alpha if isinstance(alpha, Image.Image) else Image.fromarray(alpha))
            bl.save(os.path.join(out, "full_blink.png"))
        except RuntimeError as e:
            print("no blink for", pose, e, flush=True)
        json.dump({"hero": hero, "action": action, "pose": pose, "seed": int(sd)}, open(os.path.join(out, "pose.json"), "w"))
        print("picked", pose, sd, "->", out, flush=True)


if __name__ == "__main__":
    cmd, hero, action = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == "cand":
        cand(hero, action)
    else:
        pick(hero, action, sys.argv[4:])
