"""Every layer name the toolkit knows, in one table: which pack it belongs to (split_groups.py), whether every plate
must have it and whether it comes in left / right pairs, what it is for the AI's prompt (object_fix.py), where the
rig hangs it, how it swings and where it may sit (inx_rig.py, the position check of split_groups.py). A new kind of
layer is one more row here (2026-10-02: eyewear, earwear, neckwear and tail were missing from the packs and the rig).

    import part_names as P
    e = P.lookup("side_lock-l")      # the row, or None for a name nobody knows
    e.pack, e.kind, e.swing, e.attach

Names match exactly, or by prefix for rows ending in "-" or marked prefix=True (a side "-l" / "-r", or a carved
name with a number). Exact rows win over prefixes, longer prefixes over shorter ones.
"""
from collections import namedtuple

Part = namedtuple("Part", "name zh pack need pair desc region attach z swing prefix kind")

PACKS = [("face", "臉部（五官、臉部飾品、帽子、脖子、領口）"), ("hair", "頭髮"), ("clothes", "軀幹與衣物"),
         ("limbs", "四肢（連鞋子）"), ("weapon", "武器"), ("other", "其他物件")]


def _p(name, zh, pack, need="", pair=False, desc="", region="", attach="", z=None, swing="", prefix=False):
    """need: "required" (every plate) or "" (depends on the design)
    region: where the layer may sit, for the position check: "head" (above the neck), "bone:<a>-<b>" (along a
            bone, joints from parts.json pivots / fig_joints.json, "<b>" = "" for a hand or a foot past its joint)
    attach: how inx_rig hangs a layer it has no own code for: "head" or "body" ("" = inx_rig handles it itself)
    z:      zSort for those ("depth" = from the parts.json order: behind / between / in front of face and bangs)
    swing:  the pendulum kind (inx_rig.SWING) for those"""
    kind = name.rstrip("-")
    return Part(name, zh, pack, need, pair, desc, region, attach, z, swing, prefix or name.endswith("-"), kind)


TABLE = [
    # 1 face (moves with the head)
    _p("face", "臉", "face", "required", desc="face", region="head"),
    _p("eyewhite-", "眼白", "face", "required", True, "eye", "head"),
    _p("irides", "虹膜（兩眼一層）", "face", desc="eye iris", region="head"),
    _p("irides-", "虹膜", "face", "required", True, "eye iris", "head"),
    _p("eyelash-", "睫毛", "face", "required", True, "eyelashes", "head"),
    _p("eyebrow-", "眉毛", "face", "required", True, "eyebrow", "head"),
    _p("mouth", "嘴", "face", "required", desc="mouth", region="head"),
    _p("nose", "鼻", "face", desc="nose", region="head"),
    _p("ears", "耳朵", "face", pair=True, desc="ear", region="head", prefix=True),
    _p("neck", "脖子", "face", "required", desc="neck"),

    _p("eyewear", "眼鏡、護目鏡", "face", desc="glasses, goggles", attach="head", z="depth"),
    _p("earwear", "耳飾", "face", desc="earrings", region="head", attach="head", z="depth", swing="ribbon"),
    _p("earring", "耳環", "face", desc="earring", attach="head", z="depth", swing="ribbon", prefix=True),
    _p("leftover-head", "脖子以上的雜物", "face"),
    # 2 hair (each piece swings)
    _p("front_hair", "前髮", "hair", "required", desc="bangs, hair"),
    _p("back_hair", "後髮", "hair", "required", desc="long hair"),
    # hair ornaments go with the hair, and a hat worn on the head is one (the user, 2026-10-02): they sit on it and
    # are checked swinging with it
    _p("headwear", "帽子", "hair", desc="hat"),
    _p("headwear-front", "帽子的前半", "hair", desc="hat"),
    _p("ribbon", "髮帶", "hair", desc="hair ribbon", attach="head", z="depth", swing="ribbon", prefix=True),
    _p("side_hair", "側髮（長髮）", "hair", desc="long hair"),
    _p("side_lock", "側髮", "hair", desc="lock of hair", attach="head", z="depth", swing="lock", prefix=True),
    _p("bangs", "瀏海", "hair", desc="bangs", attach="head", z="depth", swing="lock", prefix=True),
    _p("hair_ends", "髮尾", "hair", desc="hair ends", attach="head", z=1.1, swing="ends", prefix=True),
    _p("ponytail", "馬尾", "hair", desc="ponytail", attach="head", z="depth", swing="ponytail", prefix=True),
    _p("ahoge", "呆毛", "hair", desc="ahoge", attach="head", z="depth", swing="ahoge", prefix=True),
    # 3 body and clothes
    _p("topwear", "上衣", "clothes", "required", desc="clothes"),
    _p("bottomwear", "下著", "clothes", desc="skirt"),
    _p("neckwear", "領飾、圍巾", "clothes", desc="scarf, necktie, collar ornament", attach="body", z="body"),
    _p("hidden", "身體底下補畫", "clothes", desc="body, clothes"),
    _p("hidden-pelvis", "上衣下緣後的裙子", "clothes", desc="skirt"),
    _p("chest", "胸", "clothes", desc="chest, clothes", prefix=True),
    _p("abdomen", "腹", "clothes", desc="belly, clothes"),
    _p("belly", "小腹", "clothes", desc="belly, clothes"),
    _p("cape", "披風", "clothes", desc="cape", prefix=True),
    _p("sleeve", "寬袖", "clothes", desc="wide sleeve", prefix=True),
    # 4 limbs (with the shoes)
    _p("handwear-", "整條手臂（切零件前）", "limbs", pair=True, desc="arm, sleeve"),
    _p("upperarm-", "上臂", "limbs", "required", True, "upper arm, shoulder, sleeve", "bone:shoulder-elbow"),
    _p("forearm-", "前臂", "limbs", "required", True, "forearm, sleeve", "bone:elbow-wrist"),
    _p("hand-", "手", "limbs", "required", True, "hand, fingers", "bone:wrist-"),
    _p("legwear", "腿（切零件前）", "limbs", desc="legs"),
    _p("footwear", "鞋子（切零件前）", "limbs", desc="shoes"),
    _p("thigh-", "大腿", "limbs", "required", True, "thigh, leg", "bone:hip-knee"),
    _p("shin-", "小腿", "limbs", "required", True, "lower leg, knee", "bone:knee-ankle"),
    _p("foot-", "腳掌", "limbs", "required", True, "foot, shoe", "bone:ankle-"),
    # 5 weapon
    _p("objects", "武器", "weapon", "required", desc="weapon"),
    _p("objects-back", "武器被擋住的部分", "weapon", desc="weapon"),
    _p("tassel", "流蘇", "weapon", desc="tassel", prefix=True),
    # 6 other
    _p("leftover", "雜物", "other"),
    _p("quiver", "箭筒", "other", desc="quiver", prefix=True),   # an object: "Other …" on the body (hidden in bare)
    # held-l / held-r: what a hand holds that isn't the weapon (a fireball on the palm): inx_rig hangs it from that
    # wrist as "Other Held …", hidden with the objects when the character is tested alone
    _p("held-", "手上拿的東西（武器以外）", "other", desc="object held in the hand", prefix=True),   # no region: a fireball reaches far past the hand
    _p("tail", "尾巴", "other", desc="tail", attach="body", z=0.62, swing="tail"),
    _p("wings", "翅膀", "other", desc="wings", attach="body", z=0.66, swing="wings"),
]
_EXACT = {e.name: e for e in TABLE if not e.prefix}
_PREFIX = sorted((e for e in TABLE if e.prefix), key=lambda e: -len(e.name))


def lookup(name):
    """the table row for a layer name, or None"""
    if name in _EXACT:
        return _EXACT[name]
    return next((e for e in _PREFIX if name.startswith(e.name)), None)


def pack_of(name):
    e = lookup(name)
    return e.pack if e else "other"


def required():
    """[(pack, label, kind)] every plate must have; a layer satisfies one when its row has that kind"""
    seen, out = set(), []
    for e in TABLE:
        if e.need == "required" and e.kind not in seen:
            seen.add(e.kind)
            out.append((e.pack, "%s %s" % (e.zh, e.kind), e.kind))
    return out


def pairs():
    """[(pack, label, prefix)] layers that come as <prefix>l and <prefix>r"""
    return [(e.pack, e.zh, e.kind + "-") for e in TABLE if e.pair]


def desc(name, default=""):
    e = lookup(name)
    return e.desc if e and e.desc else default


# ------------------------------------------------------------------ position check
def _seg_far(xs, ys, a, b, tol):
    """share of the points farther than tol from the segment a-b"""
    import numpy as np
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    t = np.clip(((xs - a[0]) * d[0] + (ys - a[1]) * d[1]) / max(1e-6, d @ d), 0, 1)
    dist = np.hypot(xs - (a[0] + t * d[0]), ys - (a[1] + t * d[1]))
    return float((dist > tol).mean())


def position_warning(name, alpha, joints, pivots=None):
    """a warning (Chinese) when a layer lies far from where its name says it belongs, else None. joints: fig_joints
    (through inx_rig.load_joints), pivots: parts.json "pivots" (win over the joints). Only layers with a region"""
    import numpy as np
    e = lookup(name)
    if not e or not e.region or not joints or not joints.get("face"):
        return None
    ys, xs = np.nonzero(alpha > 128)
    if len(xs) < 30:
        return None
    fh = float(joints["face"][2])
    pv = dict(joints)
    pv.update({k: v for k, v in (pivots or {}).items() if isinstance(v, (list, tuple))})
    if e.region == "head":
        neck = pv.get("neck")
        if not neck:
            return None
        low = float((ys > neck[1] + 0.5 * fh).mean())
        return "%d%% 在脖子以下（不像%s）" % (100 * low, e.zh) if low > 0.3 else None
    side = name[-1] if name[-2:] in ("-l", "-r") else ""
    if not side:
        return None
    a_name, b_name = e.region[5:].split("-")
    a = pv.get("%s_%s" % (a_name, side))
    if not a:
        return None
    if b_name:
        b = pv.get("%s_%s" % (b_name, side))
    else:   # a hand or a foot: on past the joint, along the bone before it, about half that bone long
        before = {"wrist": "elbow", "ankle": "knee"}.get(a_name)
        p = pv.get("%s_%s" % (before, side)) if before else None
        b = list(np.asarray(a, float) + (np.asarray(a, float) - np.asarray(p, float)) * 0.45) if p else a
    if not b:
        return None
    far = _seg_far(xs, ys, a, b, 0.6 * fh)
    return "%d%% 離%s的骨頭太遠（混進了別的東西？）" % (100 * far, e.zh) if far > 0.25 else None
