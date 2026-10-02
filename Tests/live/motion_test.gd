extends Node2D
## Standard motions for testing a rigged plate (Docs/Design/22b step 6): the same set for every model, so what it can
## and can't do shows before any skill pose is made. Each motion runs MOTION_SECS seconds; every 2nd frame is saved
## to <out_dir>/<motion>/anim_*.png, and report.json lists per motion the parameters it wanted and the model lacked.
## Needs a window (the headless renderer draws nothing).
##   Godot_console.exe --path . res://Tests/live/motion_test.tscn -- <model.inx> <out_dir> [motion ...] [bare] [nophys]
## "nophys" turns the pendulums off (hair, skirt, cape stay put): the joints are checked first, the swings after.
## Each motion's frames.json lists, per saved frame, the parameters set and where the whole model was moved to, so
## Tools/art/motion_sheet.py can pick the frames of the biggest moves (the LLM looks at those, not at the GIFs).
## "pack=<name>" is the pack motion test (Docs/Design/22b, between a pack's assembly and the whole motions): only that
## pack's pieces and the painted-in body under them are drawn, and each of its parameters is turned to +1 and -1 in
## turn (PACK_SWEEP seconds each), so a seam or a hole isn't covered by the other packs; recorded as "pack_<name>".
## "bare" hides the weapon and the other objects: the character is verified on her own first, the weapon and the
## objects on their own (Tools/art/object_check.py), and only then together (Docs/Design/22b).

const MOTION_SECS := 4.0
## parts hidden by "bare": the weapon and the objects that aren't the character
const OBJECT_PARTS := ["Weapon", "Weapon Back", "Body Accessory"]
## pack motion tests: name -> [the pieces drawn (node name prefixes), the parameters turned (name prefixes)]
const PACKS := {
	"arms": [["Topwear", "Hidden Body", "Neck", "Upper Arm", "Forearm", "Hand"], ["Arm::"]],
	"legs": [["Bottomwear", "Hidden Pelvis", "Thigh", "Shin", "Foot"], ["Leg::", "Body:: Lean"]],
	"head": [["Neck", "Topwear", "Face", "Ears", "Nose", "Mouth", "Eye", "Iris", "Eyelash", "Eyebrow", "Earring",
		"Eyewear"],   # the hair and its ornaments (a hat worn on it too) are a pack of their own, swings on
		["Head::", "Eye:: Blink", "Mouth:: Open", "Brow:: Up"]],
	"body": [["Topwear", "Hidden Body", "Neck", "Chest", "Bottomwear", "Hidden Pelvis", "Cape"], ["Body::", "Breath"]],
	"weapon": [["Weapon", "Hand", "Forearm"], ["Weapon:: Turn", "Arm:: Left:: Wrist", "Arm:: Right:: Wrist"]],
	"held": [["Other Held", "Hand", "Forearm", "Upper Arm"], ["Arm::"]],
	# run without nophys: the hair's own swing is what is checked (the face only to see where the head is)
	"hair": [["Back Hair", "Front Hair", "Side", "Bangs", "Hair Ends", "Ponytail", "Ahoge", "Headwear", "Ribbon", "Face"],
		["Head:: Yaw", "Head:: Pitch", "Head:: Roll"]],
}
const PACK_SWEEP := 1.2
## the set, in order: [key, name]
const MOTIONS := [["walk", "走路"], ["jump", "跳躍"], ["run", "跑步"], ["wave", "揮手"], ["head", "頭部動作"],
	["face", "眨眼與表情"], ["idle", "呼吸待機"], ["hair", "甩頭"], ["hit", "受擊"], ["glance", "轉身看"]]

var puppet: InochiPuppet
var out_dir := "user://motion_test"
var _h := 100.0               ## the model's half height (model units): motion sizes scale with it
var _missing := {}            ## motion -> {parameter: true} it wanted and the model lacks
var _motion := ""
var _defaults := {}           ## parameter -> its value as loaded
var _wave := "Right"          ## the arm that waves: the free one when the other holds a weapon that shows
var _secs := MOTION_SECS      ## this motion's length
var _sweep: Array = []        ## pack test: the parameters turned, in order


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.78, 0.78, 0.8))
	var args := OS.get_cmdline_user_args()
	if args.size() < 2:
		printerr("usage: -- <model.inx> <out_dir> [motion ...]")
		get_tree().quit(1)
		return
	out_dir = args[1]
	puppet = InochiPuppet.new()
	if not puppet.load_model(args[0]):
		get_tree().quit(1)
		return
	add_child(puppet)
	puppet.set_process(false)   # stepped by hand (after add_child: Godot turns processing on when it enters the tree)
	_fit()
	for p in puppet.params:
		_defaults[p["name"]] = p["value"]
	var picked: Array = args.slice(2)
	if picked.has("nophys"):
		picked.erase("nophys")
		for d in puppet.drivers:
			d["enabled"] = false
	var pack := ""
	for a in picked.duplicate():
		if String(a).begins_with("pack="):
			pack = String(a).substr(5)
			picked.erase(a)
	if pack != "":
		if not PACKS.has(pack):
			printerr("no pack %s (%s)" % [pack, ", ".join(PACKS.keys())])
			get_tree().quit(1)
			return
		for uuid in puppet.nodes:   # only this pack's pieces are drawn
			var n: Dictionary = puppet.nodes[uuid]
			if n.has("verts"):
				var keep := false
				for pre in PACKS[pack][0]:
					if String(n["name"]).begins_with(pre):
						keep = true
				n["enabled"] = keep
		for p in puppet.params:
			for pre in PACKS[pack][1]:
				if String(p["name"]).begins_with(pre) and not p["driven"] and not _sweep.has(p["name"]):
					_sweep.append(p["name"])
		_secs = PACK_SWEEP * maxf(1.0, _sweep.size())
		await _record("pack")
		print("pack %s: %d parameters turned" % [pack, _sweep.size()])
		DirAccess.rename_absolute(out_dir.path_join("pack"), out_dir.path_join("pack_" + pack))
		get_tree().quit(0)
		return
	if picked.has("bare"):
		picked.erase("bare")
		for uuid in puppet.nodes:
			var n: Dictionary = puppet.nodes[uuid]
			if n["name"] in OBJECT_PARTS or String(n["name"]).begins_with("Other "):
				n["enabled"] = false
	# a weapon in the right hand would swing over the head and through the body (Freya's staff, 2026-10-02): wave
	# with the free hand
	var weapon_on := false
	var grip := ""
	for uuid in puppet.nodes:
		var n: Dictionary = puppet.nodes[uuid]
		if n["name"] == "Weapon" and n["enabled"]:
			weapon_on = true
		if String(n["name"]).begins_with("Grip "):
			grip = String(n["name"]).substr(5)
	if weapon_on and grip == "Right":
		_wave = "Left"
	for m in MOTIONS:
		if picked.is_empty() or picked.has(m[0]):
			await _record(m[0])
	var report := {}
	for m in MOTIONS:
		if _missing.has(m[0]) or picked.is_empty() or picked.has(m[0]):
			report[m[0]] = {"name": m[1], "missing": (_missing.get(m[0], {}) as Dictionary).keys()}
	var f := FileAccess.open(out_dir.path_join("report.json"), FileAccess.WRITE)
	f.store_string(JSON.stringify(report, " "))
	f.close()
	print("recorded %d motions" % report.size())
	get_tree().quit(0)


## scale and centre the model, a little smaller than the window so jumps and runs stay inside it
func _fit() -> void:
	var r := Rect2()
	var first := true
	for uuid in puppet.nodes:
		var n: Dictionary = puppet.nodes[uuid]
		if n.has("verts"):
			for p in puppet.part_points(n):
				r = Rect2(p, Vector2.ZERO) if first else r.expand(p)
				first = false
	_h = r.size.y / 2.0
	var vp := get_viewport_rect().size
	var k := minf(vp.x / r.size.x, vp.y / r.size.y) * 0.72
	puppet.scale = Vector2.ONE * k
	puppet.position = vp / 2.0 - (r.position + r.size / 2.0) * k + Vector2(0, vp.y * 0.06)


## a limb chain's parameter (arm / leg pieces): set it, or note once that the motion wanted the pieces
func _limb(name: String, value: float, pieces: String) -> void:
	if puppet.param_by_name.has(name):
		puppet.set_param(name, value)
	else:
		if not _missing.has(_motion):
			_missing[_motion] = {}
		_missing[_motion][pieces] = true


## set a parameter if the model has it, else note that this motion wanted it
func _put(name: String, value: float) -> void:
	if not puppet.set_param(name, value):
		if not _missing.has(_motion):
			_missing[_motion] = {}
		_missing[_motion][name] = true


func _record(motion: String) -> void:
	_motion = motion
	var dir := out_dir.path_join(motion)
	DirAccess.make_dir_recursive_absolute(dir)
	for p in puppet.params:   # every motion starts from the model's own defaults
		p["value"] = _defaults.get(p["name"], Vector2.ZERO)
	var frames := int(_secs * 30.0)
	var log: Array = []   # per saved frame: {"frame", "params": {name: value}, "offset": [x, y], "scale": [x, y]}
	for f in frames:
		var t := f / 30.0
		puppet.root_offset = Vector2.ZERO
		puppet.root_scale = Vector2.ONE
		if motion != "pack":
			_put("Breath", 0.5 + 0.5 * sin(t * 1.7))
		call("_m_" + motion, t)
		puppet.update_puppet(1.0 / 30.0)
		await get_tree().process_frame
		if f % 2 == 0:
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(dir.path_join("anim_%04d.png" % (f / 2)))
			var vals := {}
			for p in puppet.params:
				var v: Vector2 = p["value"]
				var d: Vector2 = _defaults.get(p["name"], Vector2.ZERO)
				if not v.is_equal_approx(d):   # the swings' own values too: the sheet picks their biggest frames
					vals[p["name"]] = v.x if not p["is_vec2"] else [v.x, v.y]
			log.append({"frame": f / 2, "params": vals, "offset": [puppet.root_offset.x, puppet.root_offset.y],
				"scale": [puppet.root_scale.x, puppet.root_scale.y]})
	var lf := FileAccess.open(dir.path_join("frames.json"), FileAccess.WRITE)
	lf.store_string(JSON.stringify(log))
	lf.close()
	print("motion ", motion)


## the pack test: each parameter in turn goes 0 -> +1 -> -1 -> 0 (the others at rest)
func _m_pack(t: float) -> void:
	var i := int(t / PACK_SWEEP)
	if i >= _sweep.size():
		return
	var u := fmod(t, PACK_SWEEP) / PACK_SWEEP
	_put(_sweep[i], sin(u * TAU))


func _blink(t: float, at: float) -> float:
	return sin((t - at) / 0.18 * PI) if t >= at and t - at < 0.18 else 0.0


# ------------------------------------------------------------------ the motions (t = seconds into the motion)
func _m_walk(t: float) -> void:   # two steps a second: a bob, a sway, arms swinging opposite, the head nodding a little
	var step := t * TAU * 1.0
	puppet.root_offset = Vector2(sin(step) * _h * 0.015, -absf(sin(step)) * _h * 0.02)
	_put("Arm:: Left:: Move", sin(step))
	_put("Arm:: Right:: Move", -sin(step))
	_put("Head:: Pitch", 0.15 * sin(step * 2.0))
	_legs(step, 0.15, 0.5)   # seen from the front a walk is knees in turn, little sideways swing (narrow stances crossed)


func _m_jump(t: float) -> void:   # crouch, up, fall, land with a squash, twice
	var c := fmod(t, 2.0)
	var bend := 0.0
	if c < 0.3:
		var k := sin(c / 0.3 * PI)
		puppet.root_scale = Vector2(1.0 + 0.06 * k, 1.0 - 0.08 * k)
		bend = k
	elif c < 1.1:
		var u := (c - 0.3) / 0.8
		puppet.root_offset.y = -_h * 0.35 * 4.0 * u * (1.0 - u)
		puppet.root_scale = Vector2(0.97, 1.04)
		_put("Arm:: Left:: Move", -1.0)
		_put("Arm:: Right:: Move", -1.0)
	elif c < 1.4:
		var k := sin((c - 1.1) / 0.3 * PI)
		puppet.root_scale = Vector2(1.0 + 0.1 * k, 1.0 - 0.12 * k)
		bend = k
	for sd in ["Left", "Right"]:   # knees bend on the crouch and the landing, toes point in the air
		var sg := 1.0 if sd == "Left" else -1.0
		_limb("Leg:: %s:: Hip" % sd, -0.5 * bend * sg, "腿分段（大腿／小腿／腳掌）")
		_limb("Leg:: %s:: Knee" % sd, 0.55 * bend * sg, "腿分段（大腿／小腿／腳掌）")
		_limb("Leg:: %s:: Ankle" % sd, (0.5 if c >= 0.3 and c < 1.1 else -0.5 * bend) * sg, "腳掌（腳踝）")


func _m_run(t: float) -> void:   # quick steps, a bigger bob, leaning into the run, arms pumping
	var step := t * TAU * 2.2
	puppet.root_offset = Vector2(sin(t * 1.2) * _h * 0.25, -absf(sin(step)) * _h * 0.04)
	_put("Arm:: Left:: Move", sin(step))
	_put("Arm:: Right:: Move", -sin(step))
	_limb("Arm:: Left:: Elbow", 0.8, "手臂分段（上臂／前臂／手）")   # arm pieces: +1 turns outwards on either side
	_limb("Arm:: Right:: Elbow", 0.8, "手臂分段（上臂／前臂／手）")
	_put("Head:: Yaw", 0.5 * cos(t * 1.2))
	_legs(step, 0.3, 0.6)
	_put("Head:: Pitch", -0.2)


## legs for walking / running: hips swing opposite, the knee bends on the leg coming forward
func _legs(step: float, hip: float, knee: float) -> void:
	for sd in ["Left", "Right"]:
		var ph := step + (0.0 if sd == "Left" else PI)
		var sg := 1.0 if sd == "Left" else -1.0
		_limb("Leg:: %s:: Hip" % sd, hip * sin(ph) * sg, "腿分段（大腿／小腿／腳掌）")
		_limb("Leg:: %s:: Knee" % sd, -knee * maxf(0.0, sin(ph + 0.8)) * sg, "腿分段（大腿／小腿／腳掌）")
		_limb("Leg:: %s:: Ankle" % sd, 0.3 * sin(ph - 0.6) * sg, "腳掌（腳踝）")


func _m_wave(t: float) -> void:   # one arm up and waving (the free one, _wave); arm pieces when the rig has them
	var w := sin(t * TAU * 1.5)
	_put("Arm:: %s:: Move" % _wave, w)
	if puppet.param_by_name.has("Arm:: %s:: Shoulder" % _wave):
		_put("Arm:: %s:: Shoulder" % _wave, 0.8)   # up and out (+1 is outwards on either side); the forearm on further
		_put("Arm:: %s:: Elbow" % _wave, 0.6 + 0.4 * w)
	else:
		_missing[_motion] = _missing.get(_motion, {})
		_missing[_motion]["Arm:: %s:: Shoulder / Elbow（手臂分段，舉手要用）" % _wave] = true
	_put("Head:: Roll", 0.3 * w)
	_put("Mouth:: Open", 0.3)


func _m_head(t: float) -> void:   # turn right, turn left, nod, tilt
	if t < 1.0:
		_put("Head:: Yaw", sin(t * PI))
	elif t < 2.0:
		_put("Head:: Yaw", -sin((t - 1.0) * PI))
	elif t < 3.0:
		_put("Head:: Pitch", sin((t - 2.0) * TAU))
	else:
		_put("Head:: Roll", sin((t - 3.0) * TAU))


func _m_face(t: float) -> void:   # blink, look sideways, raise the brows, talk
	_put("Eye:: Blink", maxf(_blink(t, 0.3), _blink(t, 0.7)))
	_put("Eye:: Look", sin(clampf((t - 1.0) / 1.0, 0.0, 1.0) * TAU))
	_put("Brow:: Up", sin(clampf((t - 1.8) / 0.8, 0.0, 1.0) * PI))
	_put("Mouth:: Open", (0.5 + 0.5 * sin(t * 15.0)) if t > 2.5 else 0.0)


func _m_idle(t: float) -> void:   # standing: breathing, a blink, a slow look
	_put("Eye:: Blink", _blink(t, 1.5))
	_put("Head:: Yaw", 0.25 * sin(t * 0.8))
	_put("Eye:: Look", 0.4 * sin(t * 0.8 + 0.6))


func _m_hair(t: float) -> void:   # quick head turns for 2 s, then still: the hair swings and settles
	_put("Head:: Yaw", (1.0 if int(t * 4.0) % 2 == 0 else -1.0) if t < 2.0 else 0.0)


func _m_hit(t: float) -> void:   # knocked back at 1 s: the body jolts, the head snaps, eyes shut, then settles
	var k := exp(-(t - 1.0) * 5.0) if t >= 1.0 else 0.0
	puppet.root_offset.x = _h * 0.06 * k * cos((t - 1.0) * 18.0)
	_put("Head:: Yaw", -0.8 * k)
	_put("Head:: Roll", 0.6 * k)
	_put("Eye:: Blink", minf(1.0, k * 2.0))


func _m_glance(t: float) -> void:   # the eyes lead, the head follows, then back
	var go := clampf(t / 0.4, 0.0, 1.0)
	var back := clampf((t - 2.5) / 0.6, 0.0, 1.0)
	_put("Eye:: Look", 1.0 * go * (1.0 - back))
	var hd := clampf((t - 0.3) / 0.8, 0.0, 1.0)
	_put("Head:: Yaw", 0.9 * hd * hd * (3.0 - 2.0 * hd) * (1.0 - back))
	_put("Eye:: Blink", _blink(t, 1.6))
