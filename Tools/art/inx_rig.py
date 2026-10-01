"""Automatic Inochi2D rig (.inx, the Inochi2D 0.8 format Inochi Creator opens) from a heroine outfit's layers.
Docs/Design/22_Live2D_Inochi2D.md, items 2, 3 and 6: the rig is complete enough to play in the game (InochiPuppet)
and a starting point to refine by hand in Inochi Creator.

    python Tools/art/inx_rig.py <hero> <series> [out.inx]      series: an outfit ("-", "A" …) or a key-pose folder ("pose_draw")

Reads the plates (live2d.toml [paths] plates: <plates>/<hero>[/skins/<series>]/full.png, full_blink.png) and the layers made by
Tools/art/live_layers.py (<work>/live/<hero>/<series>/layer_{hair,face,body}.png, mouth_a.png, mouth.json).
Writes <work>/live/<hero>/<series>/<hero>_<series>.inx unless an output path is given.

With a See-through split (<work>/live/<hero>/<series>/st/, parts.json) rig_st builds the fine model: eyelids,
eyes, brows, head turn with depth, hair physics, arms (in shoulder / elbow / wrist pieces when the split has them)
and the weapon in its hand; see Docs/Code/05_Rig.md. Without it, rig builds the coarse model below.

Coarse model (puppet origin = centre of full.png, pixels):
    Root
    ├─ Body                 part; "Breath" lifts the chest (mesh deform, more near the shoulders)
    └─ Head                 node; "Head:: Yaw" (-1..1) moves it sideways, "Breath" lifts it a little
       ├─ Hair              part; "Hair:: Physics" (driven) sways the lower hair (deform, grows downwards)
       ├─ Hair Physics      SimplePhysics (spring pendulum) — hair swings when the head moves
       ├─ Face              part (eyes open, mouth closed)
       ├─ Eyes Closed       part (the eye area of full_blink.png); "Eye:: Blink" 0..1 fades it in
       └─ Mouth Open        part (the mouth area of mouth_a.png); "Mouth:: Open" 0..1 fades it in
"""
import io
import json
import os
import random
import struct
import sys

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
import config as _C   # live2d.toml
WORK = _C.WORK
CELL = 48          # mesh grid size in pixels
YAW_PX = 14        # how far the head moves at full yaw
PITCH_PX = 8       # how far the head drops at a full nod
ROLL = 0.2         # head tilt at the neck (radians)
HAIR_PARALLAX = 6  # extra hair movement at full yaw (the hair is further back than the face)
BREATH_PX = 6      # chest lift at full breath
SWING = {   # 22b follow table, "swings (physics)": (pendulum length px, frequency, angle damping, sway as a share of the size)
    "skirt": (160.0, 1.0, 0.3, 0.5), "hem": (140.0, 1.1, 0.35, 0.35), "hat": (90.0, 1.8, 0.5, 0.12),
    "accessory": (60.0, 2.0, 0.45, 0.25), "lock": (130.0, 1.2, 0.4, 0.22),
    "cape": (200.0, 0.8, 0.28, 0.4), "ends": (170.0, 0.9, 0.3, 0.3), "ponytail": (150.0, 1.0, 0.3, 0.35),
    "ahoge": (40.0, 2.6, 0.4, 0.35), "ribbon": (50.0, 2.0, 0.45, 0.3), "sleeve": (110.0, 1.1, 0.35, 0.35),
    "tassel": (60.0, 1.8, 0.4, 0.4), "chest": (30.0, 3.0, 0.55, 0.05)}
SLEEVE_FOLLOW = 0.45   # how much of the upper arm's turn the top beside the shoulder takes (22b: sleeves pulled up)
SHORTS_FOLLOW = 1.0    # shorts go with the thigh all the way
COLLAR_YAW = 0.35      # the collar slides this share of the head's turn
LEAN_FOLLOW_H = 0.18   # the skirt's top bends with the waist, fading out over this share of the figure's height
ARM_TURN = 0.08    # arm swing at the shoulder (radians): small, a single plate can't carry big gestures

_rng = random.Random(20260929)


def uid():
    return _rng.randrange(1, 2 ** 32 - 1)


def src_dir(hero, series):
    return _C.plate_dir(hero, series)   # live2d.toml [paths] plates


# ------------------------------------------------------------------ building blocks
def transform(x=0.0, y=0.0, z=0.0):
    return {"trans": [float(x), float(y), float(z)], "rot": [0.0, 0.0, 0.0], "scale": [1.0, 1.0]}


def node(name, children=None, x=0.0, y=0.0, zsort=0.0, kind="Node"):
    n = {"uuid": uid(), "name": name, "type": kind, "enabled": True, "zsort": float(zsort), "transform": transform(x, y),
         "lockToRoot": False}
    if children is not None:
        n["children"] = children
    return n


class Part:
    """a textured part cut from a full-size RGBA layer: its own cropped texture and a grid mesh over its pixels"""

    def __init__(self, name, rgba, tex_index, zsort, center, opacity=1.0):
        a = np.asarray(rgba)[..., 3]
        ys, xs = np.nonzero(a > 8)
        if len(xs) == 0:
            raise ValueError("%s is empty" % name)
        x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        self.name = name
        self.box = (int(x0), int(y0), int(x1), int(y1))
        self.image = rgba.crop(self.box)
        self.tex_index = tex_index
        w, h = self.image.size
        cx, cy = x0 + w / 2.0, y0 + h / 2.0          # part centre in full.png pixels
        self.pos = (cx - center[0], cy - center[1])  # in puppet space
        self.verts, self.uvs, self.indices = grid_mesh(np.asarray(self.image)[..., 3], w, h)
        self.uuid = uid()
        self.blend = "Normal"
        self.zsort = zsort
        self.opacity = opacity

    def world_x(self, i):
        return self.verts[i][0] + self.box[0] + self.image.size[0] / 2.0

    def world_y(self, i):
        """a vertex's y in full.png pixels (for deform weights)"""
        return self.verts[i][1] + self.box[1] + self.image.size[1] / 2.0

    def json(self, parent_pos=(0.0, 0.0)):
        return {"uuid": self.uuid, "name": self.name, "type": "Part", "enabled": True, "zsort": float(self.zsort),
                "transform": transform(self.pos[0] - parent_pos[0], self.pos[1] - parent_pos[1]), "lockToRoot": False,
                "mesh": {"verts": [c for v in self.verts for c in v], "uvs": [c for v in self.uvs for c in v],
                         "indices": self.indices, "origin": [0.0, 0.0]},
                "textures": [self.tex_index], "blend_mode": "Normal", "tint": [1.0, 1.0, 1.0], "screenTint": [0.0, 0.0, 0.0],
                "mask_threshold": 0.5, "masks": [], "opacity": float(self.opacity), "psdLayerPath": ""}


def grid_mesh(alpha, w, h):
    """a grid over the part: cells that contain pixels, vertices shared, two triangles per cell; verts centred"""
    nx, ny = max(1, int(np.ceil(w / CELL))), max(1, int(np.ceil(h / CELL)))
    xs = np.linspace(0, w, nx + 1)
    ys = np.linspace(0, h, ny + 1)
    index = {}
    verts, uvs, tris = [], [], []

    def vid(i, j):
        if (i, j) not in index:
            index[(i, j)] = len(verts)
            verts.append([float(xs[i] - w / 2.0), float(ys[j] - h / 2.0)])
            uvs.append([float(xs[i] / w), float(ys[j] / h)])
        return index[(i, j)]
    for j in range(ny):
        for i in range(nx):
            cell = alpha[int(ys[j]):int(np.ceil(ys[j + 1])), int(xs[i]):int(np.ceil(xs[i + 1]))]
            if cell.size and cell.max() > 8:
                a, b, c, d = vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)
                tris += [a, b, c, a, c, d]
    return verts, uvs, tris


def value_binding(target_uuid, key, values):
    return {"node": target_uuid, "param_name": key, "values": [[v] for v in values],
            "isSet": [[True] for _ in values], "interpolate_mode": "Linear"}


def deform_binding(part, offsets_per_point):
    return {"node": part.uuid, "param_name": "deform", "values": [[offs] for offs in offsets_per_point],
            "isSet": [[True] for _ in offsets_per_point], "interpolate_mode": "Linear"}


def param(name, axis, lo, hi, bindings, default=0.0):
    return {"uuid": uid(), "name": name, "is_vec2": False, "min": [float(lo), 0.0], "max": [float(hi), 0.0],
            "defaults": [float(default), 0.0], "axis_points": [axis, [0.0]], "bindings": bindings}


def diff_box(a, b, pad):
    """box around the pixels that differ between two images of the same size"""
    d = np.abs(np.asarray(a).astype(int) - np.asarray(b).astype(int)).max(-1)
    ys, xs = np.nonzero(d > 24)
    if len(xs) == 0:
        return None
    return (max(0, xs.min() - pad), max(0, ys.min() - pad), min(a.width, xs.max() + pad), min(a.height, ys.max() + pad))


def patch(full_size, src, box):
    """a full-size transparent layer holding only src's pixels inside box (feathered edge)"""
    out = Image.new("RGBA", full_size, (0, 0, 0, 0))
    crop = src.crop(box)
    m = Image.new("L", crop.size, 0)
    inner = Image.new("L", (max(1, crop.width - 8), max(1, crop.height - 8)), 255)
    m.paste(inner, (4, 4))
    from PIL import ImageFilter
    m = m.filter(ImageFilter.GaussianBlur(3))
    alpha = Image.fromarray(np.minimum(np.asarray(m), np.asarray(crop.split()[3])))
    crop.putalpha(alpha)
    out.paste(crop, box[:2])
    return out


# ------------------------------------------------------------------ layer clean-up (CPU only)
def refine_layers(full, hair, face, body, face_info):
    """Fix the SAM2 split before rigging (Docs/Design/22 item 1), without the GPU:
    - body pixels around the head whose colour matches the hair (strands, the ponytail, the hair ribbon sitting on
      the hair) move to the hair layer: whatever the head carries must move with it
    - the body layer is painted in under the head (OpenCV inpaint) so a turning head uncovers body, not holes"""
    import cv2
    cx, cy, hh = face_info
    F = np.asarray(full).astype(np.float32)
    H, Fc, B = (np.asarray(x).copy() for x in (hair, face, body))
    ha, ba = H[..., 3] > 128, B[..., 3] > 128
    hsv = cv2.cvtColor(F[..., :3].astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    # the hair colour: median hue / saturation / value of the pixels SAM2 called hair
    hue = hsv[..., 0][ha]
    mh, ms, mv = np.median(hue), np.median(hsv[..., 1][ha]), np.median(hsv[..., 2][ha])
    dh = np.minimum(np.abs(hsv[..., 0] - mh), 180 - np.abs(hsv[..., 0] - mh))
    like_hair = (dh < 9) & (np.abs(hsv[..., 1] - ms) < 70) & (np.abs(hsv[..., 2] - mv) < 55)   # tight: a brown bow is close in hue
    yy, xx = np.mgrid[0:F.shape[0], 0:F.shape[1]]
    near_head = (yy < cy + 2.4 * hh) & (np.abs(xx - cx) < 2.6 * hh)
    # connected to the hair already (grow the hair mask into like-hair body pixels, a few times)
    grow = ha.copy()
    k = np.ones((5, 5), np.uint8)
    for _ in range(40):
        nxt = cv2.dilate(grow.astype(np.uint8), k) > 0
        nxt &= (like_hair & near_head & ba) | grow
        if (nxt == grow).all():
            break
        grow = nxt
    moved = grow & ~ha
    # small things sitting on top of the head (ribbon, hair clip): body islands above the face centre, near the hair
    n, lab = cv2.connectedComponents((ba & ~moved & (yy < cy - 0.2 * hh) & near_head).astype(np.uint8))
    hair_near = cv2.dilate(ha.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    for i in range(1, n):
        comp = lab == i
        if (comp & hair_near).any() and comp.sum() < (hh * hh * 2):
            moved |= comp
    H[moved] = np.asarray(full)[moved]
    B[moved, 3] = 0
    # paint the body in under the head, a little beyond its outline
    head_mask = (H[..., 3] > 16) | (Fc[..., 3] > 16)
    under = cv2.dilate(head_mask.astype(np.uint8), np.ones((2 * YAW_PX + 3, 2 * YAW_PX + 3), np.uint8)) > 0
    # only inside the figure's outline (body and head together, gaps closed): never paint into the background
    figure = ((B[..., 3] > 128) | head_mask).astype(np.uint8)
    figure = cv2.morphologyEx(figure, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8)) > 0
    figure = cv2.erode(figure.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    hole = under & figure & (B[..., 3] < 250) & (yy > cy + 0.4 * hh)   # the neck and shoulders, not beside the face
    rgb = np.ascontiguousarray(B[..., :3])
    B[..., :3] = cv2.inpaint(rgb, hole.astype(np.uint8) * 255, 7, cv2.INPAINT_TELEA)
    B[..., 3] = np.where(hole, 255, B[..., 3])
    print("refine: %d px moved to the hair, %d px painted in under the head" % (int(moved.sum()), int(hole.sum())), flush=True)
    return Image.fromarray(H), Image.fromarray(Fc), Image.fromarray(B)


# ------------------------------------------------------------------ writing
def write_inx(path, payload, images):
    buf = io.BytesIO()
    js = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    buf.write(b"TRNSRTS\x00" + struct.pack(">I", len(js)) + js)
    buf.write(b"TEX_SECT" + struct.pack(">I", len(images)))
    for im in images:
        png = io.BytesIO()
        im.save(png, "PNG", optimize=True)
        data = png.getvalue()
        buf.write(struct.pack(">I", len(data)) + bytes([0]) + data)   # encoding 0 = PNG
    open(path, "wb").write(buf.getvalue())


def rig(hero, series, out=None):
    ld = os.path.join(WORK, "live", hero, series)
    # a key-pose folder (pose_draw …) brings its own plate; installed outfits read theirs from Assets
    sd = ld if os.path.exists(os.path.join(ld, "full.png")) else src_dir(hero, series)
    full = Image.open(os.path.join(sd, "full.png")).convert("RGBA")
    bp = os.path.join(sd, "full_blink.png")   # a side face may have none (eyes_closed.png or no closed eyes then)
    blink = Image.open(bp).convert("RGBA") if os.path.exists(bp) else full
    center = (full.width / 2.0, full.height / 2.0)
    img = lambda n: Image.open(os.path.join(ld, n)).convert("RGBA")
    have = lambda n: os.path.exists(os.path.join(ld, n))
    mouth_info = json.load(open(os.path.join(ld, "mouth.json")))
    cx, cy, face_h = mouth_info["face"]
    joints = load_joints(os.path.join(ld, "fig_joints.json"), (cx, cy, face_h)) if have("fig_joints.json") else {}
    neck = joints.get("neck") or [cx, cy + 0.9 * face_h]
    hh = max(40.0, (neck[1] - cy) / 0.9)   # head unit: the neck sits 0.9 of it below the face centre
    limbs = joints and all(have("fig_%s.png" % k) for k in ("torso", "arm_l", "arm_r", "leg_l", "leg_r"))

    torso_src = img("fig_torso.png") if limbs else img("layer_body.png")
    hair_l, face_l, torso_l = refine_layers(full, img("layer_hair.png"), img("layer_face.png"), torso_src, (cx, cy, hh))
    moved_to_hair = np.asarray(hair_l)[..., 3] > 128
    images = []

    def add_part(name, rgba, zsort, opacity=1.0):
        p = Part(name, rgba, len(images), zsort, center, opacity)
        images.append(p.image)
        return p

    def without_hair(rgba):
        a = np.asarray(rgba).copy()
        a[moved_to_hair, 3] = 0
        return Image.fromarray(a)
    body = add_part("Torso" if limbs else "Body", torso_l, 0.3)
    hair = add_part("Hair", hair_l, -0.1)
    face = add_part("Face", face_l, 0.0)
    if have("eyes_closed.png"):
        eyes = add_part("Eyes Closed", img("eyes_closed.png"), -0.2)
    else:
        eye_box = diff_box(full, blink, 6) or (int(cx - hh), int(cy - 0.4 * hh), int(cx + hh), int(cy + 0.2 * hh))
        eyes = add_part("Eyes Closed", patch(full.size, blink, eye_box), -0.2)
    mb = mouth_info["mouth_box"]
    mouth = add_part("Mouth Open", patch(full.size, img("mouth_a.png"), mb), -0.2)

    # the head pivots around the neck; its parts sit relative to it
    head_pos = (neck[0] - center[0], neck[1] - center[1])
    head = node("Head", x=head_pos[0], y=head_pos[1], zsort=-0.1)
    phys_param = uid()
    hair_top, hair_bottom = hair.box[1], hair.box[3]
    phys = node("Hair Physics", x=0.0, y=-1.6 * hh, kind="SimplePhysics")
    phys.update({"param": phys_param, "model_type": "SpringPendulum", "map_mode": "AngleLength", "gravity": 1.0,
                 "length": float(max(80.0, (hair_bottom - hair_top) * 0.6)), "frequency": 1.2, "angle_damping": 0.35,
                 "length_damping": 0.6, "output_scale": [1.0, 1.0]})
    head["children"] = [hair.json(head_pos), phys, face.json(head_pos), eyes.json(head_pos), mouth.json(head_pos)]

    # arms hang from shoulder nodes (they rotate there), legs are plain parts behind the torso
    arm_nodes, extra_params = [], []
    root_children = [body.json()]
    grip = joints.get("weapon_grip") or {}
    weapon = add_part("Weapon", without_hair(img("fig_weapon.png")), 0.22) if limbs and have("fig_weapon.png") else None
    if limbs:
        for side, key in (("Left", "l"), ("Right", "r")):
            arm = add_part("Arm %s" % side, without_hair(img("fig_arm_%s.png" % key)), 0.25)
            sh_pt = joints["shoulder_%s" % key]
            sh_pos = (sh_pt[0] - center[0], sh_pt[1] - center[1])
            kids = [arm.json(sh_pos)]
            if weapon is not None and grip.get("hand") == "arm_%s" % key:   # the weapon goes where its hand goes
                kids.append(weapon.json(sh_pos))
            sh = node("Shoulder %s" % side, children=kids, x=sh_pos[0], y=sh_pos[1], zsort=-0.05)
            arm_nodes.append(sh)
            root_children.append(sh)
            out_dir = 1.0 if sh_pt[0] > neck[0] else -1.0   # rotate outwards for +1
            extra_params.append(param("Arm:: %s:: Move" % side, [0.0, 0.5, 1.0], -1.0, 1.0, [
                value_binding(sh["uuid"], "transform.r.z", [ARM_TURN * out_dir, 0.0, -ARM_TURN * out_dir])]))
        for side, key in (("Left", "l"), ("Right", "r")):
            leg = add_part("Leg %s" % side, without_hair(img("fig_leg_%s.png" % key)), 0.35)
            root_children.append(leg.json())
        if weapon is not None and not grip.get("hand"):   # held by nobody: stays with the body
            root_children.append(weapon.json())
    root_children.append(head)
    root = node("Root", children=root_children)

    # Breath: the chest rises, most at the shoulders, nothing at the hips; the head and shoulders follow
    chest_top = neck[1] + 0.3 * hh
    hips = max(joints.get("hip_l", [0, cy + 4.5 * hh])[1], joints.get("hip_r", [0, 0])[1]) if joints else cy + 4.5 * hh
    lift = []
    for i in range(len(body.verts)):
        y = body.world_y(i)
        w = float(np.clip((hips - y) / max(1.0, hips - chest_top), 0.0, 1.0))
        lift.append([0.0, -BREATH_PX * w])
    breath = [deform_binding(body, [[[0.0, 0.0]] * len(body.verts), lift]),
              value_binding(head["uuid"], "transform.t.y", [0.0, -BREATH_PX * 0.8])]
    breath += [value_binding(sh["uuid"], "transform.t.y", [0.0, -BREATH_PX * 0.8]) for sh in arm_nodes]
    params = [
        param("Breath", [0.0, 1.0], 0.0, 1.0, breath),
        param("Head:: Yaw", [0.0, 0.5, 1.0], -1.0, 1.0, [
            value_binding(head["uuid"], "transform.t.x", [-YAW_PX, 0.0, YAW_PX]),
            value_binding(hair.uuid, "transform.t.x", [-HAIR_PARALLAX, 0.0, HAIR_PARALLAX])]),
        param("Eye:: Blink", [0.0, 1.0], 0.0, 1.0, [value_binding(eyes.uuid, "opacity", [0.0, 1.0])]),
        param("Mouth:: Open", [0.0, 1.0], 0.0, 1.0, [value_binding(mouth.uuid, "opacity", [0.0, 1.0])]),
    ] + extra_params
    # Hair:: Physics: the pendulum angle (-1..1 = half a turn) bends the lower hair sideways
    sway = []
    for side in (-1.0, 0.0, 1.0):
        offs = []
        for i in range(len(hair.verts)):
            y = hair.world_y(i)
            w = float(np.clip((y - (cy - 0.5 * hh)) / max(1.0, hair_bottom - (cy - 0.5 * hh)), 0.0, 1.0)) ** 1.5
            offs.append([side * 0.35 * (hair_bottom - hair_top) * w, 0.0])
        sway.append(offs)
    hp = param("Hair:: Physics", [0.0, 0.5, 1.0], -1.0, 1.0, [deform_binding(hair, sway)])
    hp["uuid"] = phys_param
    params.append(hp)

    payload = {"meta": {"name": "%s %s" % (hero, series), "version": "v0.8.6", "rigger": "Tools/art/inx_rig.py",
                        "artist": "", "rights": None, "copyright": "", "licenseURL": "", "contact": "", "reference": "",
                        "thumbnailId": 4294967295, "preservePixels": False},
               "physics": {"pixelsPerMeter": 1000.0, "gravity": 9.8}, "nodes": root, "param": params,
               "automation": None, "animations": None, "groups": []}
    out = out or os.path.join(ld, "%s_%s.inx" % (hero, "default" if series == "-" else series))
    write_inx(out, payload, images)
    print("rig ->", out, "(%d parts%s)" % (len(images), ", arms and legs" if limbs else ""), flush=True)
    return out


# ------------------------------------------------------------------ See-through layers (fine parts)
def composite(name, children, zsort=0.0, x=0.0, y=0.0):
    n = node(name, children=children, x=x, y=y, zsort=zsort, kind="Composite")
    n.update({"blend_mode": "Normal", "tint": [1.0, 1.0, 1.0], "screenTint": [0.0, 0.0, 0.0], "mask_threshold": 0.5, "opacity": 1.0})
    return n


def turn_follow(pt, pivot, angles, weights):
    """deform offsets for the axis points: each vertex turned around pivot by angle x its weight"""
    out = []
    for a in angles:
        offs = []
        for i, w in enumerate(weights):
            dx, dy = pt.world_x(i) - pivot[0], pt.world_y(i) - pivot[1]
            aa = a * w
            ca, sa = np.cos(aa), np.sin(aa)
            offs.append([float(ca * dx - sa * dy - dx), float(sa * dx + ca * dy - dy)])
        out.append(offs)
    return out


def near(pt, at, radius):
    """weights: a Gaussian around a point"""
    return [float(np.exp(-((pt.world_x(i) - at[0]) ** 2 + (pt.world_y(i) - at[1]) ** 2) / (radius * radius)))
            for i in range(len(pt.verts))]


def skirt_follow(pt, hip, knee, hips_x, rng, frac=None):
    """deform offsets (at -rng, 0, +rng) for a skirt over one leg: each point turns around the hip by the leg's angle,
    weighted by how near it is to this leg across (a Gaussian as wide as the hips are apart) and how far down it is
    (none at the hip, all by the knee)"""
    spread = max(20.0, abs(hips_x[0] - hips_x[1]) if len(hips_x) == 2 else 60.0)
    out = []
    for sgn in (-1.0, 0.0, 1.0):
        a = sgn * rng * (SKIRT_FOLLOW if frac is None else frac)
        ca, sa = np.cos(a), np.sin(a)
        offs = []
        for i in range(len(pt.verts)):
            x, y = pt.world_x(i), pt.world_y(i)
            w = np.exp(-((x - hip[0]) / spread) ** 2) * float(np.clip((y - hip[1]) / max(1.0, knee[1] - hip[1]), 0.0, 1.0))
            dx, dy = x - hip[0], y - hip[1]
            nx, ny = ca * dx - sa * dy, sa * dx + ca * dy
            offs.append([float((nx - dx) * w), float((ny - dy) * w)])
        out.append(offs)
    return out


def clean_objects(obj, full):
    """See-through paints a hidden bowstring in as a thick pale bar: drop the painted-in pixels (not what the plate
    shows there) that are pale and grey; the visible bow and string stay"""
    import cv2
    o = np.asarray(obj).copy()
    f = np.asarray(full)
    hsv = cv2.cvtColor(o[..., :3], cv2.COLOR_RGB2HSV)
    painted = np.abs(o[..., :3].astype(int) - f[..., :3].astype(int)).max(-1) > 24
    painted |= f[..., 3] < 128
    pale = (hsv[..., 1] < 45) & (hsv[..., 2] > 150)
    drop = painted & pale & (o[..., 3] > 0)
    o[drop, 3] = 0
    print("objects: %d painted-in pale pixels dropped" % int(drop.sum()), flush=True)
    return Image.fromarray(o)


def load_joints(path, face=None):
    """fig_joints.json with the neck, shoulders and hips the pose detector missed (null there) estimated from the
    face and each other, in face heights (measured on the installed plates); wrists and elbows stay null"""
    j = json.load(open(path))
    cx, cy, h = j.get("face") or face
    j.setdefault("face", [cx, cy, h])
    if not j.get("neck"):
        j["neck"] = [cx, cy + 0.74 * h]
    nx, ny = j["neck"]
    for side, dx in (("l", 0.72), ("r", -0.72)):
        if not j.get("shoulder_" + side):
            j["shoulder_" + side] = [nx + dx * h, ny + 0.1 * h]
    for side, dx in (("l", 0.45), ("r", -0.45)):
        if not j.get("hip_" + side):
            other = j.get("hip_" + ("r" if side == "l" else "l"))
            j["hip_" + side] = [nx + dx * h, other[1] if other else ny + 2.2 * h]
    return j


def st_usable(hero, series):
    """the See-through split exists and found the face where the pose's joints put it (on one plate it took a
    shape on her chest for a second head; the fig_* split is used then)"""
    ld = os.path.join(WORK, "live", hero, series)
    jp = os.path.join(ld, "fig_joints.json")
    if not (os.path.exists(os.path.join(ld, "st", "parts.json")) and os.path.exists(jp)):
        return False
    a = None
    for n in ("eyewhite-l", "eyewhite-r", "face"):   # the eyes pin the face down best
        fp = os.path.join(ld, "st", "part_%s.png" % n)
        if os.path.exists(fp):
            a = np.asarray(Image.open(fp).convert("RGBA"))[..., 3] > 128
            if a.sum() > 0:
                break
    if a is None or a.sum() == 0:
        return False
    ys, xs = np.nonzero(a)
    cx, cy, h = json.load(open(jp))["face"]
    far = np.hypot(xs.mean() - cx, ys.mean() - cy)
    if far > max(30.0, 0.5 * h):
        print("See-through face is %.0f px from the pose's face: using the fig_* split instead" % far, flush=True)
        return False
    return True


BODY_ORDER = ["hidden", "legwear", "thigh-l", "thigh-r", "footwear", "bottomwear", "hidden-pelvis", "neck", "handwear-l", "handwear-r",
              "upperarm-l", "upperarm-r", "topwear"]   # back to front
WAIST_TURN, HIP_TURN, KNEE_TURN, ANKLE_TURN = 0.6, 1.2, 1.6, 0.8   # radians at the parameters' ends
GOWN_HIP, GOWN_KNEE = 0.3, 0.5   # under a skirt past the knees the legs only move inside it
SKIRT_FOLLOW = 0.8               # how much of a hip's turn the skirt over that leg takes (22b: pushed by the thigh)
SHOULDER_TURN, ELBOW_TURN, WRIST_TURN, WEAPON_TURN = 1.4, 1.6, 0.8, 3.1   # radians at the parameters' ends (a whole weapon may turn half a round)
WEAPON_BACK_Z = 1.3   # behind everything, back hair (0.6 from the head) included
LOWER_BODY = {"Legs", "Footwear", "Bottomwear", "Hidden Pelvis", "Bottomwear Physics"}   # stay with the pelvis when the waist turns
OVER_HEAD = -0.8   # in front of the head node (-0.5) and everything on it
BODY_Z = (0.5, 0.35)   # the body accessory (0.34) and the weapon stay in front


def body_depths(names, st):
    """zSort for the body layers, back to front in the order of st/parts.json: See-through paints in what is hidden
    (an arm under a cape, the body under kimono sleeves, a robe under the hakama), and a part holds the plate's
    colours only where it is the front-most in that order, so any other order shows painted-in guesses (Rena's
    belt, in the shorts in front of the top, vanished under the top's repaint); BODY_ORDER without parts.json"""
    pj_path = os.path.join(st, "parts.json")
    order = [n for n in BODY_ORDER if n in names]
    if os.path.exists(pj_path):
        listed = [q["name"] for q in json.load(open(pj_path)).get("order_back_to_front", [])]
        order.sort(key=lambda n: listed.index(n) if n in listed else len(listed))
    print("body back to front:", " < ".join(order), flush=True)
    step = (BODY_Z[0] - BODY_Z[1]) / max(1, len(order) - 1)
    return {n: BODY_Z[0] - step * k for k, n in enumerate(order)}


def as_plate(part, full):
    """a layer drawn in front of the rest of the head shows what the plate shows wherever it covers the figure:
    See-through paints hair in where goggles or a hair clip sit on it, which would hide them"""
    o = np.asarray(part).copy()
    f = np.asarray(full)
    on = (o[..., 3] > 0) & (f[..., 3] > 128)
    o[on, :3] = f[on, :3]
    return Image.fromarray(o)


def rig_st(hero, series, out=None):
    """Rig from the See-through split in <work>/live/<hero>/<series>/st/ (art-tools Tools/art/see_through.py):
    real eyelid closing (lashes come down, eye white and iris squash, the iris clipped to the eye white), eyes that
    look sideways, eyebrows, head turn with depth (front hair, face, back hair move by different amounts), front and
    back hair on their own physics, breathing torso, arms turning at the shoulders, the bow in its hand."""
    ld = os.path.join(WORK, "live", hero, series)
    st = os.path.join(ld, "st")
    sd = ld if os.path.exists(os.path.join(ld, "full.png")) else src_dir(hero, series)
    full = Image.open(os.path.join(sd, "full.png")).convert("RGBA")
    center = (full.width / 2.0, full.height / 2.0)
    have = lambda n: os.path.exists(os.path.join(st, "part_%s.png" % n))
    joints = load_joints(os.path.join(ld, "fig_joints.json"))
    mouth_info = json.load(open(os.path.join(ld, "mouth.json"))) if os.path.exists(os.path.join(ld, "mouth.json")) else {}
    cx, cy, face_h = joints["face"]
    neck = joints["neck"]
    fig = np.asarray(full)[..., 3] > 128
    from scipy import ndimage
    near_fig = ndimage.binary_dilation(np.asarray(full)[..., 3] > 8, iterations=2)

    pjp = os.path.join(st, "parts.json")
    parts_meta = json.load(open(pjp)) if os.path.exists(pjp) else {}
    listed = [q["name"] for q in parts_meta.get("order_back_to_front", [])]

    def head_depth(n):
        """zSort of a head piece from its place in parts.json: behind the face (Freya's hat, whose painted-in brim
        would cover the locks of hair over her face), between face and front hair, or in front of everything"""
        if n not in listed or "face" not in listed or "front_hair" not in listed:
            return -0.15
        i = listed.index(n)
        return 0.5 if i < listed.index("face") else -0.06 if i < listed.index("front_hair") else -0.15

    def over_head(n):
        """an arm raised across the face (Rena's windup) or a weapon held up in front of it is drawn in front of the
        whole head: parts.json lists it after the front hair and, above the neck, it covers head pieces with the
        plate's own colours (the list's order says nothing where parts don't overlap: in one plate the front hair
        came first, and hands resting on the knees are no reason to go over the head)"""
        if n not in listed or "front_hair" not in listed or listed.index(n) < listed.index("front_hair") or not have(n):
            return False
        im = np.asarray(part_img(n)).astype(int)
        head_px = np.zeros(fig.shape, bool)
        for h in ("front_hair", "back_hair", "face", "headwear", "headwear-front", "ears", "ears-l", "ears-r"):
            if have(h):
                head_px |= np.asarray(part_img(h))[..., 3] > 128
        head_px[int(neck[1]):] = False
        shows = (im[..., 3] > 128) & (np.abs(im[..., :3] - plate_rgb).sum(-1) < 10)
        return int((shows & head_px).sum()) >= 50

    def part_img(n):
        """a See-through part cut to the figure: off the figure nothing is ever hidden, so painted-in pixels there
        (a hank of hair beside Yukino, an arc over her head) would always show"""
        im = np.asarray(Image.open(os.path.join(st, "part_%s.png" % n)).convert("RGBA")).copy()
        im[~near_fig, 3] = 0
        return Image.fromarray(im)
    plate_rgb = np.asarray(full)[..., :3].astype(int)

    def real(n):
        """an optional part is taken only if most of it lies on the figure: See-through sometimes invents parts
        (wings, a second small head) that the plate doesn't have"""
        if not have(n):
            return False
        im = np.asarray(part_img(n))
        a = im[..., 3] > 128
        if a.sum() == 0:
            return False
        same = np.abs(im[..., :3].astype(int) - plate_rgb).max(-1) < 30   # the plate shows this very pixel
        ok = (a & fig & same).sum() / a.sum() > 0.5
        if not ok:
            print("dropped invented part:", n, flush=True)
        return ok
    images = []

    def add(name, rgba, zsort, opacity=1.0, blend="Normal"):
        pt = Part(name, rgba, len(images), zsort, center, opacity)
        pt.blend = blend
        images.append(pt.image)
        return pt

    def pj(pt, parent_pos=(0.0, 0.0)):
        j = pt.json(parent_pos)
        j["blend_mode"] = pt.blend
        return j
    # leftover: what sits on the head (the ribbon) moves with it, the rest stays with the body
    left_head = left_body = None
    if have("leftover"):
        left = np.asarray(part_img("leftover")).copy()
        top = left.copy()
        top[int(neck[1]):, :, 3] = 0
        left[:int(neck[1]), :, 3] = 0
        left_head = Image.fromarray(top) if top[..., 3].max() > 8 else None
        left_body = Image.fromarray(left) if left[..., 3].max() > 8 else None

    head_pos = (neck[0] - center[0], neck[1] - center[1])
    head = node("Head", x=head_pos[0], y=head_pos[1], zsort=-0.5)
    hp = lambda pt: pj(pt, head_pos)
    back_hair = add("Back Hair", part_img("back_hair"), 1.1)
    front_hair = add("Front Hair", as_plate(part_img("front_hair"), full), -0.1)
    face = add("Face", part_img("face"), 0.1)
    head_kids = [hp(back_hair), hp(face)]
    feats = []
    for n, z in (("ears-l", 0.15), ("ears-r", 0.15), ("ears", 0.15), ("nose", 0.05), ("mouth", 0.04)):
        if have(n):
            pt = add(n.capitalize(), part_img(n), z)
            head_kids.append(hp(pt))
            if n in ("nose", "mouth"):
                feats.append(pt)
    eyes = {}
    for side in ("l", "r"):
        if not have("eyewhite-%s" % side):
            continue
        white_img = part_img("eyewhite-%s" % side)
        white = add("Eye White %s" % side.upper(), white_img, 0.02)
        if have("irides-%s" % side):
            iris_img = part_img("irides-%s" % side)
        elif have("irides"):   # one part for both irises (side views): take the part inside this eye white
            iris_img = np.asarray(part_img("irides")).copy()
            x0, y0, x1, y1 = white.box
            keep = np.zeros(iris_img.shape[:2], bool)
            keep[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = True
            iris_img[~keep, 3] = 0
            iris_img = Image.fromarray(iris_img) if iris_img[..., 3].max() > 8 else None
        else:
            iris_img = None
        kids = [hp(white)]
        iris = None
        if iris_img is not None:
            iris = add("Iris %s" % side.upper(), iris_img, -0.01, blend="ClipToLower")
            kids.append(hp(iris))
        comp = composite("Eye %s" % side.upper(), kids, zsort=0.03)
        head_kids.append(comp)
        lash = brow = None
        if have("eyelash-%s" % side):
            lash = add("Eyelash %s" % side.upper(), part_img("eyelash-%s" % side), 0.0)
            head_kids.append(hp(lash))
        if have("eyebrow-%s" % side):
            brow = add("Eyebrow %s" % side.upper(), part_img("eyebrow-%s" % side), -0.02)
            head_kids.append(hp(brow))
        eyes[side] = (white, iris, lash, brow, comp)
    closed = None
    if os.path.exists(os.path.join(ld, "eyes_closed.png")):   # the drawn closed eyes, faded in at the end of the blink
        closed = add("Eyes Closed", Image.open(os.path.join(ld, "eyes_closed.png")).convert("RGBA"), -0.03)
        head_kids.append(hp(closed))
    mouth_open = None
    if mouth_info and os.path.exists(os.path.join(ld, "mouth_a.png")):
        mouth_open = add("Mouth Open", patch(full.size, Image.open(os.path.join(ld, "mouth_a.png")).convert("RGBA"), mouth_info["mouth_box"]), 0.035)
        head_kids.append(hp(mouth_open))
    head_kids.append(hp(front_hair))
    hat = None
    hat_front = None
    if real("headwear"):
        hat = add("Headwear", part_img("headwear"), head_depth("headwear"))
        head_kids.append(hp(hat))
    if hat is not None and have("headwear-front"):
        # the crown and band sitting on the forehead and the bangs, split off a hat whose brim goes behind the head
        hat_front = add("Headwear Front", part_img("headwear-front"), head_depth("headwear-front"))
        head_kids.append(hp(hat_front))
    if left_head is not None:
        head_kids.append(hp(add("Head Accessory", left_head, -0.2)))
    # hair in pieces and things hanging from the head (object_fix --split-hair / --carve): each swings on its own below
    head_swing = []   # (part, kind, hung at (x, y) in the picture)
    for n in sorted(f[5:-4] for f in os.listdir(st) if f.startswith("part_") and f.endswith(".png")):
        kind = next((k for k in ("side_lock", "ahoge", "ribbon", "earring", "ponytail", "hair_ends") if n.startswith(k)), None)
        if kind is None or np.asarray(part_img(n))[..., 3].max() <= 8:
            continue
        z = 1.1 if kind == "hair_ends" else head_depth(n)   # the ends stay as far back as the back hair
        pt = add(n.replace("_", " ").title(), part_img(n), z)
        head_kids.append(hp(pt))
        top_mid = ((pt.box[0] + pt.box[2]) / 2.0, pt.box[1] if kind != "ahoge" else pt.box[3])
        head_swing.append((pt, {"side_lock": "lock", "earring": "ribbon", "hair_ends": "ends"}.get(kind, kind), top_mid))
    phys_back, phys_front = uid(), uid()
    hb = back_hair.box
    pb = node("Back Hair Physics", x=0.0, y=-1.2 * face_h, kind="SimplePhysics")
    pb.update({"param": phys_back, "model_type": "SpringPendulum", "map_mode": "AngleLength", "gravity": 1.0,
               "length": float(max(80.0, (hb[3] - hb[1]) * 0.6)), "frequency": 1.1, "angle_damping": 0.35, "length_damping": 0.6,
               "output_scale": [1.0, 1.0]})
    pf = node("Front Hair Physics", x=0.0, y=-1.2 * face_h, kind="SimplePhysics")
    pf.update({"param": phys_front, "model_type": "SpringPendulum", "map_mode": "AngleLength", "gravity": 1.0,
               "length": 120.0, "frequency": 1.6, "angle_damping": 0.45, "length_damping": 0.6, "output_scale": [1.0, 1.0]})
    head_kids += [pb, pf]
    head["children"] = head_kids

    # body
    root_kids = []
    kept = {}   # parts the follow rules below swing
    depth = body_depths([n for n in BODY_ORDER if have(n)], st)
    # "hidden": the body painted in under the arms and the weapon (the art split's rig_parts.py), shown only where
    # a moved arm uncovers it; its colours are painted, so it skips the real() check
    # "hidden-pelvis": the skirt continued up under the top, shown when the upper body leans off it (stays on the pelvis)
    for n, label in (("hidden", "Hidden Body"), ("legwear", "Legs"), ("footwear", "Footwear"), ("bottomwear", "Bottomwear"),
                     ("hidden-pelvis", "Hidden Pelvis"), ("neck", "Neck")):
        if have(n) and np.asarray(part_img(n))[..., 3].max() > 8:   # a layer emptied by a carve (all of it a cape) is skipped
            kept[n] = add(label, part_img(n), depth[n])
            root_kids.append(pj(kept[n]))
    top = add("Topwear", part_img("topwear"), depth["topwear"])
    root_kids.append(pj(top))
    known = {"back_hair", "front_hair", "face", "ears", "ears-l", "ears-r", "nose", "mouth", "headwear", "headwear-front", "side_hair", "leftover",
             "legwear", "footwear", "bottomwear", "neck", "topwear", "objects", "objects-back", "handwear-l", "handwear-r", "irides",
             "hidden", "hidden-pelvis"}
    known |= {"%s-%s" % (k, sd) for k in ("upperarm", "forearm", "hand", "thigh", "shin", "foot") for sd in ("l", "r")}
    carved = [f[5:-4] for f in os.listdir(st) if f.startswith("part_") and f.endswith(".png")
              and f[5:-4].startswith(("side_lock", "ahoge", "ribbon", "earring", "ponytail", "hair_ends", "chest", "cape",
                                      "sleeve", "tassel"))]
    known |= set(carved)
    chest = cape = None
    if have("chest") and np.asarray(part_img("chest"))[..., 3].max() > 8:   # in front of the top it was cut from
        chest = add("Chest", part_img("chest"), depth["topwear"] - 0.003)
        root_kids.append(pj(chest))
    if have("cape") and np.asarray(part_img("cape"))[..., 3].max() > 8:   # behind the body, in front of the back hair
        cape = add("Cape", part_img("cape"), BODY_Z[0] + 0.15)   # behind the hair ends (0.6) too: hair lies on the cape
        root_kids.append(pj(cape))
    known |= {"%s-%s" % (k, sd) for k in ("eyewhite", "irides", "eyelash", "eyebrow") for sd in ("l", "r")}
    for f in sorted(os.listdir(st)):
        n = f[5:-4] if f.startswith("part_") and f.endswith(".png") else None
        if n and n not in known and real(n):   # anything else See-through finds (and the plate has) stays with the body
            kept["Other " + n] = add("Other " + n, part_img(n), 0.36)
            root_kids.append(pj(kept["Other " + n]))   # "Other …": the objects pack (hidden when the character is tested alone)
    if left_body is not None:
        kept["Body Accessory"] = add("Body Accessory", left_body, 0.34)
        root_kids.append(pj(kept["Body Accessory"]))
    pivots = parts_meta.get("pivots") or {}
    grip = joints.get("weapon_grip") or {}
    if pivots.get("grip"):   # the split's own grip (hand "l" / "r", point, tip) wins over the pose detector's
        g = pivots["grip"]
        grip = {"hand": "arm_" + g["hand"], "point": g["point"], "tip": g.get("tip")}
    weapon = None
    if have("objects"):
        weapon = add("Weapon", clean_objects(part_img("objects"), full), OVER_HEAD - 0.05 if over_head("objects") else 0.27)
    # "objects-back": the stretches of the weapon the figure hides (under a hat brim, behind the dress), painted in by
    # the art split; drawn behind everything so at rest the figure covers it as on the plate, turning with the weapon
    weapon_back = add("Weapon Back", part_img("objects-back"), WEAPON_BACK_Z) if weapon is not None and have("objects-back") else None
    arm_nodes, arm_params = [], []
    limb_swing = []   # (part, kind, node it hangs from, that node's place in puppet space)

    def rel(a, b):
        return (a[0] - b[0], a[1] - b[1])
    for side, key in (("Left", "l"), ("Right", "r")):
        chain = all(have("%s-%s" % (k, key)) for k in ("upperarm", "forearm", "hand"))
        if not chain and not have("handwear-%s" % key):
            continue
        if any(over_head("%s-%s" % (k, key)) for k in ("handwear", "upperarm", "forearm", "hand")):
            z = OVER_HEAD
        else:
            z = depth.get("%s-%s" % ("upperarm" if chain else "handwear", key), 0.4)

        def pv(j):
            return pivots.get("%s_%s" % (j, key)) or joints.get("%s_%s" % (j, key))
        sh_pt = pv("shoulder")
        sh_pos = rel(sh_pt, center)
        holds = weapon is not None and grip.get("hand") == "arm_%s" % key
        if chain:
            # shoulder -> elbow -> wrist, each piece turning at its joint; the weapon hangs from the hand at its grip
            el_pos, wr_pos = rel(pv("elbow"), center), rel(pv("wrist"), center)
            hand = add("Hand %s" % side, part_img("hand-%s" % key), z - 0.004)
            wrist_kids = [pj(hand, wr_pos)]
            if holds:
                g_pos = rel(grip["point"], center)
                weapon.zsort = z - 0.002   # behind the fingers that close around it
                grip_node = node("Grip %s" % side, children=[pj(weapon, g_pos)] + ([pj(weapon_back, g_pos)] if weapon_back else []),
                                 x=g_pos[0] - wr_pos[0], y=g_pos[1] - wr_pos[1])
                wrist_kids.append(grip_node)
                arm_params.append(param("Weapon:: Turn", [0.0, 0.5, 1.0], -1.0, 1.0, [
                    value_binding(grip_node["uuid"], "transform.r.z", [-WEAPON_TURN, 0.0, WEAPON_TURN])]))
                if have("tassel") and np.asarray(part_img("tassel"))[..., 3].max() > 8:   # a tassel on the weapon
                    tas = add("Tassel", part_img("tassel"), z - 0.001)
                    grip_node["children"].append(pj(tas, g_pos))
                    limb_swing.append((tas, "tassel", grip_node, g_pos))
            wrist = node("Wrist %s" % side, children=wrist_kids, x=wr_pos[0] - el_pos[0], y=wr_pos[1] - el_pos[1])
            fore = add("Forearm %s" % side, part_img("forearm-%s" % key), z - 0.002)
            elbow = node("Elbow %s" % side, children=[pj(fore, el_pos), wrist],
                         x=el_pos[0] - sh_pos[0], y=el_pos[1] - sh_pos[1])
            if have("sleeve-%s" % key) and np.asarray(part_img("sleeve-%s" % key))[..., 3].max() > 8:   # a wide sleeve's drape
                slv = add("Sleeve %s" % side, part_img("sleeve-%s" % key), z - 0.001)
                elbow["children"].append(pj(slv, el_pos))
                limb_swing.append((slv, "sleeve", elbow, el_pos))
            upper = add("Upper Arm %s" % side, part_img("upperarm-%s" % key), z)
            sh = node("Shoulder %s" % side, children=[pj(upper, sh_pos), elbow], x=sh_pos[0], y=sh_pos[1], zsort=0.0)
            outw = 1.0 if sh_pt[0] > neck[0] else -1.0   # +1 turns outwards (and up) on either side, like "Move"
            ua_len = float(np.hypot(pv("elbow")[0] - sh_pt[0], pv("elbow")[1] - sh_pt[1]))
            for j, nd, rng in (("Shoulder", sh, SHOULDER_TURN), ("Elbow", elbow, ELBOW_TURN), ("Wrist", wrist, WRIST_TURN)):
                binds = [value_binding(nd["uuid"], "transform.r.z", [rng * outw, 0.0, -rng * outw])]
                if j == "Shoulder":   # the top beside the shoulder goes some way with a raised arm (a sleeve pulled up)
                    wts = near(top, sh_pt, 0.35 * ua_len)
                    binds.append(deform_binding(top, turn_follow(top, sh_pt, [rng * outw * SLEEVE_FOLLOW, 0.0,
                                                                              -rng * outw * SLEEVE_FOLLOW], wts)))
                arm_params.append(param("Arm:: %s:: %s" % (side, j), [0.0, 0.5, 1.0], -1.0, 1.0, binds))
        else:
            arm = add("Arm %s" % side, part_img("handwear-%s" % key), z)
            kids = [pj(arm, sh_pos)]
            if holds:
                kids.append(pj(weapon, sh_pos))
                if weapon_back:
                    kids.append(pj(weapon_back, sh_pos))
            sh = node("Shoulder %s" % side, children=kids, x=sh_pos[0], y=sh_pos[1], zsort=0.0)
        arm_nodes.append(sh)
        root_kids.append(sh)
        out_dir = 1.0 if sh_pt[0] > neck[0] else -1.0
        arm_params.append(param("Arm:: %s:: Move" % side, [0.0, 0.5, 1.0], -1.0, 1.0, [
            value_binding(sh["uuid"], "transform.r.z", [ARM_TURN * out_dir, 0.0, -ARM_TURN * out_dir])]))
    if weapon is not None and not grip.get("hand"):
        root_kids.append(pj(weapon))
        if weapon_back:
            root_kids.append(pj(weapon_back))
    root_kids.append(head)

    # legs: hip -> knee -> ankle, each piece turning at its joint (a split with thigh- / shin- / foot- parts)
    leg_nodes = []
    skirt_pt = kept.get("bottomwear")
    knees_y = [q[1] for q in (pivots.get("knee_l"), pivots.get("knee_r")) if q]
    gown = skirt_pt is not None and knees_y and skirt_pt.box[3] > max(knees_y) + 40
    shorts = skirt_pt is not None and knees_y and skirt_pt.box[3] < min(knees_y) - 0.25 * (min(knees_y) - skirt_pt.box[1])
    hips_x = [q[0] for q in (pivots.get("hip_l"), pivots.get("hip_r")) if q]
    for side, key in (("Left", "l"), ("Right", "r")):
        pts = [pivots.get("%s_%s" % (j, key)) or joints.get("%s_%s" % (j, key)) for j in ("hip", "knee", "ankle")]
        if not all(have("%s-%s" % (k, key)) for k in ("thigh", "shin", "foot")) or not all(pts):
            continue
        hp_pos, kn_pos, an_pos = (rel(q, center) for q in pts)
        z = depth.get("thigh-" + key, 0.45)
        foot = add("Foot %s" % side, part_img("foot-" + key), z - 0.004)
        ankle = node("Ankle %s" % side, children=[pj(foot, an_pos)], x=an_pos[0] - kn_pos[0], y=an_pos[1] - kn_pos[1])
        shin = add("Shin %s" % side, part_img("shin-" + key), z - 0.002)
        knee = node("Knee %s" % side, children=[pj(shin, kn_pos), ankle], x=kn_pos[0] - hp_pos[0], y=kn_pos[1] - hp_pos[1])
        thigh = add("Thigh %s" % side, part_img("thigh-" + key), z)
        hip = node("Hip %s" % side, children=[pj(thigh, hp_pos), knee], x=hp_pos[0], y=hp_pos[1])
        leg_nodes.append(hip)
        for j, nd, rng in (("Hip", hip, GOWN_HIP if gown else HIP_TURN), ("Knee", knee, GOWN_KNEE if gown else KNEE_TURN),
                           ("Ankle", ankle, ANKLE_TURN)):
            binds = [value_binding(nd["uuid"], "transform.r.z", [-rng, 0.0, rng])]
            if j == "Hip" and skirt_pt is not None:   # the skirt over this leg turns with it, less further from the leg
                binds.append(deform_binding(skirt_pt, skirt_follow(skirt_pt, pts[0], pts[1], hips_x, rng,
                                                                   SHORTS_FOLLOW if shorts else None)))
            arm_params.append(param("Leg:: %s:: %s" % (side, j), [0.0, 0.5, 1.0], -1.0, 1.0, binds))
    # follow rules (22b, bones and follow): things that hang swing on a pendulum of their own, hung where they would
    # feel the motion; each drives a "<part>:: Physics" parameter that bends the part, more the further from where
    # it hangs
    swings = []   # (part, physics uuid, per-vertex weights 0..1, sway px at full swing)

    def pendulum(label, kind, pos):
        ln, fq, dmp, _ = SWING[kind]
        n = node("%s Physics" % label, x=pos[0], y=pos[1], kind="SimplePhysics")
        n.update({"param": uid(), "model_type": "SpringPendulum", "map_mode": "AngleLength", "gravity": 1.0, "length": ln,
                  "frequency": fq, "angle_damping": dmp, "length_damping": 0.6, "output_scale": [1.0, 1.0]})
        return n

    def below(pt, y0):   # 0 above y0, growing to 1 at the part's bottom
        y1 = pt.box[3]
        return [float(np.clip((pt.world_y(i) - y0) / max(1.0, y1 - y0), 0.0, 1.0)) ** 1.5 for i in range(len(pt.verts))]
    waist_y = (pivots.get("waist") or [0, (joints["hip_l"][1] + joints["hip_r"][1]) / 2.0])[1]
    skirt = kept.get("bottomwear")
    if skirt is not None and skirt.box[3] - waist_y > 40:   # a skirt in two pieces: each half hung at its own knee
        hips_ = {h["name"]: h for h in leg_nodes}
        wb = below(skirt, waist_y)
        amount = SWING["skirt"][3] * (skirt.box[3] - waist_y)
        if "Hip Left" in hips_ and "Hip Right" in hips_:
            mid_x = (pivots["hip_l"][0] + pivots["hip_r"][0]) / 2.0
            soft = max(10.0, abs(pivots["hip_l"][0] - pivots["hip_r"][0]) / 4.0)
            for nm, sgn_ in (("Hip Left", 1.0), ("Hip Right", -1.0)):   # the character's left is the picture's right
                kn = hips_[nm]["children"][1]["transform"]["trans"]
                ph = pendulum("Bottomwear %s" % nm.split()[1], "skirt", (kn[0], kn[1]))
                hips_[nm]["children"].append(ph)
                half = [w * float(1.0 / (1.0 + np.exp(-sgn_ * (skirt.world_x(i) - mid_x) / soft))) for i, w in enumerate(wb)]
                swings.append((skirt, ph["param"], half, amount))
        else:
            ph = pendulum("Bottomwear", "skirt", (0.0, waist_y - center[1]))
            root_kids.append(ph)
            swings.append((skirt, ph["param"], wb, amount))
    if cape is not None:   # a cape: heavy and slow, hung where it starts, the hem swinging most
        ph = pendulum("Cape", "cape", ((cape.box[0] + cape.box[2]) / 2.0 - center[0], cape.box[1] - center[1]))
        root_kids.append(ph)
        swings.append((cape, ph["param"], below(cape, cape.box[1] + 0.1 * (cape.box[3] - cape.box[1])),
                       SWING["cape"][3] * (cape.box[3] - cape.box[1])))
    if chest is not None:   # a light, quick bounce (clothed; adults only, 22b)
        ph = pendulum("Chest", "chest", ((chest.box[0] + chest.box[2]) / 2.0 - center[0], chest.box[1] - center[1]))
        root_kids.append(ph)
        mid = ((chest.box[0] + chest.box[2]) / 2.0, (chest.box[1] + chest.box[3]) / 2.0)
        cwts = near(chest, mid, 0.5 * max(chest.box[2] - chest.box[0], chest.box[3] - chest.box[1]))
        edge = 0.2 * min(chest.box[2] - chest.box[0], chest.box[3] - chest.box[1])   # still at the cut's edges: no seam opens
        cwts = [w * float(np.clip(min(chest.world_x(i) - chest.box[0], chest.box[2] - chest.world_x(i),
                                      chest.world_y(i) - chest.box[1], chest.box[3] - chest.world_y(i)) / max(1.0, edge), 0, 1))
                for i, w in enumerate(cwts)]
        swings.append((chest, ph["param"], cwts, SWING["chest"][3] * (chest.box[3] - chest.box[1])))
    for pt, kind, top_mid in head_swing:   # hair pieces and things on the head
        ph = pendulum(pt.name, kind, (top_mid[0] - neck[0], top_mid[1] - neck[1]))
        head["children"].append(ph)
        if kind == "ahoge":   # it sticks up: the tip, the top, swings most
            wts = [float(np.clip((pt.box[3] - pt.world_y(i)) / max(1.0, pt.box[3] - pt.box[1]), 0, 1)) ** 1.5
                   for i in range(len(pt.verts))]
        else:
            wts = below(pt, pt.box[1])
        swings.append((pt, ph["param"], wts, SWING[kind][3] * (pt.box[3] - pt.box[1])))
    for pt, kind, nd, nd_pos in limb_swing:   # a sleeve's drape on the forearm, a tassel on the weapon
        ph = pendulum(pt.name, kind, (0.0, 0.0))
        nd["children"].append(ph)
        swings.append((pt, ph["param"], below(pt, pt.box[1]), SWING[kind][3] * (pt.box[3] - pt.box[1])))
    if top.box[3] - waist_y > 0.12 * full.height:   # a coat's or cape's hem below the waist, hung at the waist
        ph = pendulum("Topwear", "hem", ((top.box[0] + top.box[2]) / 2.0 - center[0], waist_y - center[1]))
        root_kids.append(ph)
        swings.append((top, ph["param"], below(top, waist_y), SWING["hem"][3] * (top.box[3] - waist_y)))
    if hat is not None:   # the brim and the tip, further from the head the more
        hc = (cx, cy)
        far = [float(np.hypot(hat.world_x(i) - hc[0], hat.world_y(i) - hc[1])) for i in range(len(hat.verts))]
        mx = max(1.0, max(far))
        ph = pendulum("Headwear", "hat", (0.0, -0.8 * face_h))
        head["children"].append(ph)
        swings.append((hat, ph["param"], [float(np.clip(f / mx, 0, 1)) ** 2 for f in far], SWING["hat"][3] * (hat.box[2] - hat.box[0])))
        if hat_front is not None:   # the same swing, so the two pieces stay one hat
            ff = [float(np.hypot(hat_front.world_x(i) - hc[0], hat_front.world_y(i) - hc[1])) for i in range(len(hat_front.verts))]
            swings.append((hat_front, ph["param"], [float(np.clip(f / mx, 0, 1)) ** 2 for f in ff], SWING["hat"][3] * (hat.box[2] - hat.box[0])))
    if have("side_hair") and np.asarray(part_img("side_hair"))[..., 3].max() > 8:   # long locks over the shoulders (sorted out of See-through's grab-bag): on the head, in
        # front of the top and behind the arms as on the plate, swinging more the further down
        z_abs = (depth.get("topwear", 0.4) + depth.get("hidden", depth.get("topwear", 0.4) - 0.04)) / 2.0
        locks = add("Side Hair", part_img("side_hair"), z_abs + 0.5)   # the head node sits at -0.5
        head["children"].append(hp(locks))
        ph = pendulum("Side Hair", "lock", (0.0, locks.box[1] - neck[1]))
        head["children"].append(ph)
        swings.append((locks, ph["param"], below(locks, locks.box[1]), SWING["lock"][3] * (locks.box[3] - locks.box[1])))
    for key, pt in kept.items():   # pouches and trinkets below the neck: hung at their top
        if key == "Body Accessory" or key.startswith("Other "):
            ph = pendulum(pt.name, "accessory", ((pt.box[0] + pt.box[2]) / 2.0 - center[0], pt.box[1] - center[1]))
            root_kids.append(ph)
            swings.append((pt, ph["param"], below(pt, pt.box[1]), SWING["accessory"][3] * (pt.box[3] - pt.box[1])))

    # the waist: everything above it (torso, neck, arms, head, what they hold) turns there ("Body:: Lean"); the
    # skirt and the legs stay with the pelvis
    waist_pt = pivots.get("waist") or [(joints["hip_l"][0] + joints["hip_r"][0]) / 2.0, (joints["hip_l"][1] + joints["hip_r"][1]) / 2.0]
    waist_pos = rel(waist_pt, center)
    upper = [k for k in root_kids if k["name"] not in LOWER_BODY]
    for k in upper:
        k["transform"]["trans"][0] -= waist_pos[0]
        k["transform"]["trans"][1] -= waist_pos[1]
    waist = node("Waist", children=upper, x=waist_pos[0], y=waist_pos[1])
    lean = [value_binding(waist["uuid"], "transform.r.z", [-WAIST_TURN, 0.0, WAIST_TURN])]
    fade = LEAN_FOLLOW_H * full.height
    for n in ("bottomwear", "hidden-pelvis"):   # the skirt's top goes with the waist, so no crack opens there
        if n in kept:
            pt = kept[n]
            wts = [float(np.clip(1.0 - (pt.world_y(i) - waist_y) / fade, 0.0, 1.0)) for i in range(len(pt.verts))]
            lean.append(deform_binding(pt, turn_follow(pt, waist_pt, [-WAIST_TURN, 0.0, WAIST_TURN], wts)))
    arm_params.append(param("Body:: Lean", [0.0, 0.5, 1.0], -1.0, 1.0, lean))
    root = node("Root", children=[k for k in root_kids if k["name"] in LOWER_BODY] + leg_nodes + [waist])

    # parameters
    hips = max(joints["hip_l"][1], joints["hip_r"][1])
    chest_top = neck[1] + 0.3 * face_h
    lift = [[0.0, -BREATH_PX * float(np.clip((hips - top.world_y(i)) / max(1.0, hips - chest_top), 0.0, 1.0))] for i in range(len(top.verts))]
    breath = [deform_binding(top, [[[0.0, 0.0]] * len(top.verts), lift]),
              value_binding(head["uuid"], "transform.t.y", [0.0, -BREATH_PX * 0.8])]
    breath += [value_binding(sh["uuid"], "transform.t.y", [0.0, -BREATH_PX * 0.8]) for sh in arm_nodes]
    if chest is not None:
        breath.append(value_binding(chest.uuid, "transform.t.y", [0.0, -BREATH_PX * 0.9]))
    yaw = [value_binding(head["uuid"], "transform.t.x", [-YAW_PX, 0.0, YAW_PX]),
           value_binding(front_hair.uuid, "transform.t.x", [-HAIR_PARALLAX, 0.0, HAIR_PARALLAX]),
           value_binding(back_hair.uuid, "transform.t.x", [HAIR_PARALLAX * 0.6, 0.0, -HAIR_PARALLAX * 0.6])]
    for pt in feats:
        yaw.append(value_binding(pt.uuid, "transform.t.x", [-3.0, 0.0, 3.0]))
    # the collar: the top around the neck and the neck slide a little with the head (22b: collar with a head turn)
    cw = near(top, neck, 0.5 * face_h)
    yaw.append(deform_binding(top, [[[-YAW_PX * COLLAR_YAW * w, 0.0] for w in cw], [[0.0, 0.0] for _ in cw],
                                    [[YAW_PX * COLLAR_YAW * w, 0.0] for w in cw]]))
    if "neck" in kept:
        yaw.append(value_binding(kept["neck"].uuid, "transform.t.x", [-YAW_PX * COLLAR_YAW, 0.0, YAW_PX * COLLAR_YAW]))
    blink, look, brows = [], [], []
    for side, (white, iris, lash, brow, comp) in eyes.items():
        yaw.append(value_binding(comp["uuid"], "transform.t.x", [-3.0, 0.0, 3.0]))
        for pt in (lash, brow):
            if pt is not None:
                yaw.append(value_binding(pt.uuid, "transform.t.x", [-3.0, 0.0, 3.0]))
        bottom = white.box[3]
        eye_h = max(4.0, white.box[3] - white.box[1])
        for pt in (white, iris):   # squash toward the lower lid
            if pt is None:
                continue
            shut = [[0.0, (bottom - pt.world_y(i)) * 0.92] for i in range(len(pt.verts))]
            blink.append(deform_binding(pt, [[[0.0, 0.0]] * len(pt.verts), shut]))
        if lash is not None:
            blink.append(value_binding(lash.uuid, "transform.t.y", [0.0, eye_h * 0.7]))
        if brow is not None:
            blink.append(value_binding(brow.uuid, "transform.t.y", [0.0, eye_h * 0.15]))
            brows.append(value_binding(brow.uuid, "transform.t.y", [0.0, -eye_h * 0.35]))
        if iris is not None:
            w = white.box[2] - white.box[0]
            look.append(value_binding(iris.uuid, "transform.t.x", [-w * 0.2, 0.0, w * 0.2]))
    # Head:: Pitch (a nod, +1 = down): the head drops, the face's features (on its front) move further than it, the
    # back hair less; Head:: Roll tilts the head at the neck
    pitch = [value_binding(head["uuid"], "transform.t.y", [-PITCH_PX, 0.0, PITCH_PX]),
             value_binding(back_hair.uuid, "transform.t.y", [PITCH_PX * 0.3, 0.0, -PITCH_PX * 0.3])]
    front_feats = list(feats) + [x for e in eyes.values() for x in (e[2], e[3]) if x is not None]
    pitch += [value_binding(pt.uuid, "transform.t.y", [-3.0, 0.0, 3.0]) for pt in front_feats]
    pitch += [value_binding(e[4]["uuid"], "transform.t.y", [-3.0, 0.0, 3.0]) for e in eyes.values()]
    blink_p = param("Eye:: Blink", [0.0, 1.0], 0.0, 1.0, blink)
    params = [param("Breath", [0.0, 1.0], 0.0, 1.0, breath),
              param("Head:: Yaw", [0.0, 0.5, 1.0], -1.0, 1.0, yaw),
              param("Head:: Pitch", [0.0, 0.5, 1.0], -1.0, 1.0, pitch),
              param("Head:: Roll", [0.0, 0.5, 1.0], -1.0, 1.0, [value_binding(head["uuid"], "transform.r.z", [-ROLL, 0.0, ROLL])]),
              blink_p,
              param("Eye:: Look", [0.0, 0.5, 1.0], -1.0, 1.0, look),
              param("Brow:: Up", [0.0, 1.0], 0.0, 1.0, brows)] + arm_params
    if closed is not None:   # the drawn closed eye covers the squashed eye only at the very end of the blink
        blink_p["axis_points"] = [[0.0, 0.8, 1.0], [0.0]]
        for bnd in blink_p["bindings"]:   # stretch the two-point bindings over three points
            v = bnd["values"]
            if bnd["param_name"] == "deform":
                mid = [[a[0] * 0.2 + b[0] * 0.8, a[1] * 0.2 + b[1] * 0.8] for a, b in zip(v[0][0], v[1][0])]
                bnd["values"] = [v[0], [mid], v[1]]
            else:
                bnd["values"] = [v[0], [v[0][0] * 0.2 + v[1][0] * 0.8], v[1]]
            bnd["isSet"] = [[True]] * 3
        blink_p["bindings"].append(value_binding(closed.uuid, "opacity", [0.0, 0.0, 1.0]))
    if mouth_open is not None:
        params.append(param("Mouth:: Open", [0.0, 1.0], 0.0, 1.0, [value_binding(mouth_open.uuid, "opacity", [0.0, 1.0])]))
    for pid, pt, amount in ((phys_back, back_hair, 0.3), (phys_front, front_hair, 0.12)):
        top_y, bot_y = pt.box[1], pt.box[3]
        sway = []
        for sgn in (-1.0, 0.0, 1.0):
            sway.append([[sgn * amount * (bot_y - top_y) * float(np.clip((pt.world_y(i) - top_y) / max(1.0, bot_y - top_y), 0.0, 1.0)) ** 1.5, 0.0]
                         for i in range(len(pt.verts))])
        prm = param("%s:: Physics" % pt.name, [0.0, 0.5, 1.0], -1.0, 1.0, [deform_binding(pt, sway)])
        prm["uuid"] = pid
        params.append(prm)
    by_pid = {}
    for pt, pid, wts, amount in swings:   # one parameter per pendulum, bending every part hung on it
        vert = 1.0 if pt.name == "Chest" else 0.0   # the chest bounces as much as it sways
        sway = [[[sgn * amount * w, sgn * amount * w * vert] for w in wts] for sgn in (-1.0, 0.0, 1.0)]
        if pid in by_pid:
            by_pid[pid]["bindings"].append(deform_binding(pt, sway))
            continue
        prm = param("%s:: Physics" % pt.name, [0.0, 0.5, 1.0], -1.0, 1.0, [deform_binding(pt, sway)])
        prm["uuid"] = pid
        by_pid[pid] = prm
        params.append(prm)

    payload = {"meta": {"name": "%s %s" % (hero, series), "version": "v0.8.6", "rigger": "Tools/art/inx_rig.py (See-through)",
                        "artist": "", "rights": None, "copyright": "", "licenseURL": "", "contact": "", "reference": "",
                        "thumbnailId": 4294967295, "preservePixels": False},
               "physics": {"pixelsPerMeter": 1000.0, "gravity": 9.8}, "nodes": root, "param": params,
               "automation": None, "animations": None, "groups": []}
    out = out or os.path.join(ld, "%s_%s_st.inx" % (hero, "default" if series == "-" else series))
    write_inx(out, payload, images)
    print("rig (See-through) ->", out, "(%d parts)" % len(images), flush=True)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    use_st = st_usable(sys.argv[1], sys.argv[2])
    (rig_st if use_st else rig)(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
