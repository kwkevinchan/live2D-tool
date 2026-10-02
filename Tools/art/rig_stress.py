"""Stress test for rigs whose arms and weapon turn at their joints (the split with upperarm- / forearm- / hand- parts
and "pivots" in parts.json): turns every joint to both ends of its range, one at a time, renders each pose with
the game's player (Tests/live/rig_render.tscn) and finds holes, i.e. background showing through inside the
figure (a torso that was never painted in under the arm, a gap at a bent elbow, the staff's missing part behind
the hand), and ghosts, i.e. a moved piece still showing at its old place (fingers left in a body layer). The shared
completeness check for the art split (see Docs/Design/22).

  python Tools/art/rig_stress.py freya/pose_idle [more folders]
  python Tools/art/rig_stress.py --find-ranges freya/pose_idle
One contact sheet per model (<work>/live/check/<name>_stress.jpg: every pose, holes in magenta, ghosts in cyan) and
a line per pose; exit status 1 when a pose has a hole or a ghost bigger than HOLE_AREA of the figure. Joints are
tested at the ends of the folder's "ranges" in st/parts.json when it has them, else at the rig's full range.
--find-ranges turns each joint out from 0 in STEP radian steps, both ways, until the first angle that fails, and
writes the last passing angle per side into st/parts.json "ranges" (radians, clockwise on screen positive):
{"shoulder_r": [-0.6, 1.2], "elbow_r": [...], ..., "weapon": [...]}. Skill timelines keep inside these.
"""
import json
import os
import struct
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inx_rig import (ANKLE_TURN, ELBOW_TURN, HIP_TURN, KNEE_TURN, ROOT, SHOULDER_TURN, WAIST_TURN, WEAPON_TURN,   # noqa: E402
                     WORK, WRIST_TURN, load_joints)
from rig_check import GODOT, OUT, folders, model_and_plate   # noqa: E402

JOINTS = ("Shoulder", "Elbow", "Wrist", "Hip", "Knee", "Ankle", "Lean")
VALUES = (-1.0, 1.0)
STEP = 0.1           # radians per step for --find-ranges
TURN = {"Shoulder": SHOULDER_TURN, "Elbow": ELBOW_TURN, "Wrist": WRIST_TURN, "Weapon": WEAPON_TURN,
        "Hip": HIP_TURN, "Knee": KNEE_TURN, "Ankle": ANKLE_TURN, "Lean": WAIST_TURN}
LOWER = ("legwear", "footwear", "bottomwear", "hidden-pelvis", "thigh-", "shin-", "foot-")   # parts that stay when the waist turns
GAP = 4              # px: narrower gaps between pieces are closed over and counted as holes
HOLE_AREA = 0.0005   # of the figure's pixels, for one connected hole
GHOST_WIDTH = 3      # px: ghost areas thinner than about twice this are ignored
JOINT_R = 40         # px around a pivot where cracks count


def model_params(inx):
    """parameter names of an .inx (INP1: magic, big-endian JSON length, JSON)"""
    with open(inx, "rb") as f:
        f.read(8)
        n = struct.unpack(">I", f.read(4))[0]
        payload = json.loads(f.read(n))
    return [p["name"] for p in payload.get("param", [])]


def joint_params(names):
    return [n for n in names if n == "Weapon:: Turn" or any(n.endswith(":: " + j) for j in JOINTS)]


def range_key(pname):
    """a joint parameter's key in "ranges": "Arm:: Right:: Shoulder" -> "shoulder_r", "Weapon:: Turn" -> "weapon" """
    if pname == "Weapon:: Turn":
        return "weapon"
    if pname == "Body:: Lean":
        return "waist"
    return "%s_%s" % (pname.rsplit(":: ", 1)[1].lower(), "l" if ":: Left:: " in pname else "r")


def full_turn(pname):
    """radians the rig turns the joint at parameter value 1"""
    return TURN["Weapon" if pname == "Weapon:: Turn" else pname.rsplit(":: ", 1)[1]]


def pose(pname, angle):
    """(label, "param:value", param, value) for a joint turned to angle radians"""
    v = max(-1.0, min(1.0, angle / full_turn(pname)))
    return ("%s %+.1f" % (pname.replace(":: ", " "), angle), "%s:%s" % (pname, v), pname, v)


def poses(names, ranges):
    """every joint at both ends of its range (the folder's "ranges", else the rig's full turn)"""
    out = []
    for n in joint_params(names):
        lo, hi = ranges.get(range_key(n), [-full_turn(n), full_turn(n)])
        for a in (lo, hi):
            if abs(a) > 1e-6:
                out.append(pose(n, a))
    return out


def moved_pieces(ld, pname, value, rest_rgb):
    """for a pose that turns one joint: (where the pieces below that joint showed at rest, where they are now), both
    as masks, the new place by turning their layers around the joint the way the rig does"""
    st = os.path.join(ld, "st")
    meta = json.load(open(os.path.join(st, "parts.json")))
    pv = dict(meta.get("pivots") or {})
    joints = load_joints(os.path.join(ld, "fig_joints.json"))
    grip = pv.get("grip") or {}
    if pname == "Weapon:: Turn":
        side, pieces, pivot, rng = grip.get("hand"), ["objects", "objects-back"], grip.get("point"), WEAPON_TURN
    elif pname == "Body:: Lean":   # everything above the waist
        pieces = [f[5:-4] for f in os.listdir(st) if f.startswith("part_") and f.endswith(".png") and not f[5:].startswith(LOWER)]
        pivot = pv.get("waist") or [(joints["hip_l"][0] + joints["hip_r"][0]) / 2.0, (joints["hip_l"][1] + joints["hip_r"][1]) / 2.0]
        rng = WAIST_TURN
    elif pname.startswith("Leg:: "):
        side = "l" if ":: Left:: " in pname else "r"
        joint = pname.rsplit(":: ", 1)[1]
        chain = {"Hip": ["thigh", "shin", "foot"], "Knee": ["shin", "foot"], "Ankle": ["foot"]}[joint]
        pieces = ["%s-%s" % (k, side) for k in chain]
        pivot = pv.get("%s_%s" % (joint.lower(), side)) or joints.get("%s_%s" % (joint.lower(), side))
        rng = TURN[joint]
    else:
        side = "l" if ":: Left:: " in pname else "r"
        joint = pname.rsplit(":: ", 1)[1]
        chain = {"Shoulder": ["upperarm", "forearm", "hand"], "Elbow": ["forearm", "hand"], "Wrist": ["hand"]}[joint]
        pieces = ["%s-%s" % (k, side) for k in chain] + (["objects", "objects-back"] if grip.get("hand") == side else [])
        pivot = pv.get("%s_%s" % (joint.lower(), side)) or joints.get("%s_%s" % (joint.lower(), side))
        rng = {"Shoulder": SHOULDER_TURN, "Elbow": ELBOW_TURN, "Wrist": WRIST_TURN}[joint]
    if pivot is None:
        return None
    old = new = None
    for n in pieces:
        f = os.path.join(st, "part_%s.png" % n)
        if not os.path.exists(f):
            continue
        im = Image.open(f).convert("RGBA")
        a = np.asarray(im)
        shows = (a[..., 3] > 128) & (np.abs(a[..., :3].astype(int) - rest_rgb).sum(-1) < 30)
        # the rig turns clockwise on screen for a positive value; PIL turns counter-clockwise
        turned = np.asarray(im.rotate(-np.degrees(value * rng), resample=Image.NEAREST, center=tuple(pivot)))[..., 3] > 128
        old = shows if old is None else old | shows
        new = turned if new is None else new | turned
    return (old, new) if old is not None else None


def ghosts(old, new, rest_rgb, posed):
    """the pieces' old place still showing their old colours where no moved piece is now; slivers narrower than
    about 2 * GHOST_WIDTH px don't count (after a small turn the strip along a piece's edge looks much as before)"""
    same = (posed[..., 3] > 128) & (np.abs(posed[..., :3].astype(int) - rest_rgb).sum(-1) < 30)
    return ndimage.binary_opening(old & ~ndimage.binary_dilation(new, iterations=3) & same, iterations=GHOST_WIDTH)


MOVING = ("upperarm-", "forearm-", "hand-", "handwear-", "objects", "held-", "thigh-", "shin-", "foot-")   # held-: a fireball moves with its hand


def body_area(ld, plate_alpha):
    """where the body is without the arms and the weapon: the See-through parts that don't move, cut to the figure,
    with small gaps closed and enclosed space filled (a torso that was never painted in under an arm counts)"""
    st = os.path.join(ld, "st")
    near = ndimage.binary_dilation(plate_alpha > 8, iterations=2)
    body = np.zeros(plate_alpha.shape, bool)
    for n in [q["name"] for q in load_meta(ld).get("order_back_to_front", [])]:   # the layers in use, not stray files
        f = os.path.join(st, "part_%s.png" % n)
        if os.path.exists(f) and not n.startswith(MOVING):
            body |= np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 128
    return ndimage.binary_fill_holes(ndimage.binary_closing(body & near, iterations=6))


def holes(rest, posed, body, near_joints):
    """background showing where the moved pieces used to cover the body, plus cracks (narrower than GAP px) at the
    joints that the rest pose doesn't have (elsewhere a thin gap is just a piece moving off its neighbour: the
    staff's crook off her hat)"""
    r, q = rest > 128, posed > 128
    uncovered = r & ~q & body
    cracks = ndimage.binary_closing(q, iterations=GAP) & ~q & ~ndimage.binary_closing(r, iterations=GAP) & near_joints
    return ndimage.binary_opening(uncovered | cracks, iterations=1)


def render(model, plate, todo, name):
    """renders the poses (rest first) with the game's player; paths of the images (None where it failed)"""
    w, h = Image.open(plate).size
    renders = [os.path.join(OUT, "%s_stress_%03d.png" % (name, i)) for i in range(len(todo))]
    jobs = os.path.join(OUT, "%s_jobs.txt" % name)   # a file, not arguments: Windows caps the command line
    with open(jobs, "w", encoding="utf-8") as f:
        f.write("\n".join("%s=%s=%dx%d=%s" % (model, r, w, h, t[1]) for t, r in zip(todo, renders)))
    subprocess.run([GODOT, "--path", ROOT, "res://Tests/live/rig_render.tscn", "--", "@" + jobs],
                   capture_output=True, timeout=120 + 10 * len(todo))
    os.remove(jobs)
    return [r if os.path.exists(r) else None for r in renders]


class Judge:
    """holes and ghosts of posed renders against the rest render of one folder"""

    def __init__(self, ld, plate, rest_path):
        plate_alpha = np.asarray(Image.open(plate).convert("RGBA"))[..., 3]
        self.ld = ld
        self.fig = max(1, int((plate_alpha > 128).sum()))
        self.body = body_area(ld, plate_alpha)
        rest = np.asarray(Image.open(rest_path).convert("RGBA"))
        self.rest, self.rest_rgb = rest[..., 3], rest[..., :3].astype(int)
        pv = load_meta(ld).get("pivots") or {}
        pts = [v for k, v in pv.items() if k != "grip"] + ([pv["grip"]["point"]] if pv.get("grip") else [])
        yy, xx = np.mgrid[0:self.rest.shape[0], 0:self.rest.shape[1]]
        self.near_joints = np.zeros(self.rest.shape, bool)
        for x, y in pts:
            self.near_joints |= (xx - x) ** 2 + (yy - y) ** 2 < JOINT_R ** 2

    def lower_area(self):
        """the skirt and legs: where a turning waist must not open a gap"""
        if not hasattr(self, "_lower"):
            st = os.path.join(self.ld, "st")
            m = np.zeros(self.rest.shape, bool)
            for f in os.listdir(st):
                if f.startswith("part_") and f.endswith(".png") and f[5:].startswith(LOWER):
                    m |= np.asarray(Image.open(os.path.join(st, f)).convert("RGBA"))[..., 3] > 128
            self._lower = m
        return self._lower

    def __call__(self, img, pname, value):
        """(bad, hole mask, ghost mask, biggest hole, biggest ghost)"""
        body = self.lower_area() if pname == "Body:: Lean" else self.body   # a lean moves the whole upper body
        hm = holes(self.rest, img[..., 3], body, self.near_joints)
        mv = moved_pieces(self.ld, pname, value, self.rest_rgb) if pname else None
        gm = ghosts(mv[0], mv[1], self.rest_rgb, img) if mv else np.zeros_like(hm)

        def biggest(m):
            labels, n = ndimage.label(m)
            return int(max(ndimage.sum(m, labels, range(1, n + 1)))) if n else 0
        bh, bg = biggest(hm), biggest(gm)
        return max(bh, bg) > HOLE_AREA * self.fig, hm, gm, bh, bg


def load_meta(ld):
    return json.load(open(os.path.join(ld, "st", "parts.json")))


def find_ranges(ld, model, plate, name):
    """per joint and side, the last angle (STEP radians apart, out from 0) before the first one that fails"""
    names = joint_params(model_params(model))
    todo = [("rest", "", None, 0.0)]
    steps = {}   # (param, side) -> [angles]
    for n in names:
        for sgn in (-1, 1):
            k = int(round(full_turn(n) / STEP))
            angs = [sgn * STEP * i for i in range(1, k + 1)]
            steps[(n, sgn)] = angs
            todo += [pose(n, a) for a in angs]
    print("%-28s rendering %d poses" % (name, len(todo)), flush=True)
    paths = render(model, plate, todo, name)
    if paths[0] is None:
        print("%-28s rest NOT RENDERED" % name)
        return None
    judge = Judge(ld, plate, paths[0])
    by_pose = {t[1]: p for t, p in zip(todo, paths)}
    ranges = {}
    for n in names:
        side = [0.0, 0.0]
        for i, sgn in enumerate((-1, 1)):
            for a in steps[(n, sgn)]:
                pth = by_pose[pose(n, a)[1]]
                bad = pth is None or judge(np.asarray(Image.open(pth).convert("RGBA")), n, pose(n, a)[3])[0]
                if bad:
                    break
                side[i] = round(a, 3)
        ranges[range_key(n)] = side
        print("%-28s %-14s %+.1f .. %+.1f rad" % (name, range_key(n), side[0], side[1]), flush=True)
    for pth in paths:
        if pth:
            os.remove(pth)
    meta = load_meta(ld)
    meta["ranges"] = ranges
    json.dump(meta, open(os.path.join(ld, "st", "parts.json"), "w"), indent=1)
    return ranges


def main(args):
    os.makedirs(OUT, exist_ok=True)
    find = "--find-ranges" in args
    args = [a for a in args if a != "--find-ranges"]
    flagged = 0
    for hero, series, ld in folders(args):
        model, plate = model_and_plate(hero, series, ld)
        name = "%s_%s" % (hero, "default" if series == "-" else series)
        if not joint_params(model_params(model)):
            print("%-28s no joint parameters (not a split with arm pieces)" % name)
            continue
        if find:
            flagged += find_ranges(ld, model, plate, name) is None
            continue
        todo = [("rest", "", None, 0.0)] + poses(model_params(model), load_meta(ld).get("ranges") or {})
        paths = render(model, plate, todo, name)
        if paths[0] is None:
            print("%-28s rest NOT RENDERED" % name)
            flagged += 1
            continue
        judge = Judge(ld, plate, paths[0])
        w, h = Image.open(plate).size
        tiles = []
        for (label, _, pname, value), r in zip(todo, paths):
            if r is None:
                print("%-28s %-26s NOT RENDERED" % (name, label))
                flagged += 1
                continue
            img = np.asarray(Image.open(r).convert("RGBA"))
            bad, hm, gm, bh, bg = judge(img, pname, value)
            flagged += bad
            print("%-28s %-26s %s holes %d px (biggest %d), ghosts %d px (biggest %d)" % (
                name, label, "FLAG" if bad else "ok  ", int(hm.sum()), bh, int(gm.sum()), bg))
            v = img[..., :3].copy()
            v[img[..., 3] < 128] = (70, 70, 80)
            v[hm] = (255, 0, 255)
            v[gm] = (0, 255, 255)
            t = Image.fromarray(v)
            ImageDraw.Draw(t).text((8, 8), label, fill=(255, 255, 0))
            tiles.append(t.resize((w * 360 // h, 360)))
            os.remove(r)
        if tiles:
            cols = 6
            tw = tiles[0].width
            sheet = Image.new("RGB", (tw * min(cols, len(tiles)), 360 * ((len(tiles) + cols - 1) // cols)), (40, 40, 48))
            for i, t in enumerate(tiles):
                sheet.paste(t, ((i % cols) * tw, (i // cols) * 360))
            sheet.save(os.path.join(OUT, name + "_stress.jpg"), quality=85)
    print("contact sheets in", OUT)
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
