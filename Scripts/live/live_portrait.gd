class_name LivePortrait
extends Node2D
## A heroine portrait that lives by itself: one or more Inochi2D models (InochiPuppet), one per pose ("idle" plus
## key poses such as "draw" / "release" for a skill), with an idle loop — breathing, a blink every few seconds,
## looking around — plus talk() for a mouth moving while a line plays and play_pose() to switch poses with a short
## crossfade. Parameter names follow Tools/art/inx_rig.py (Breath, Head:: Yaw, Eye:: Blink, Mouth:: Open); models
## rigged by hand may use Aka-style names, both are tried.
##   var p := LivePortrait.new(); p.add_pose("idle", "res://…/alicia.inx"); add_child(p); p.talk(2.0)

signal pose_finished(pose: StringName)

const FADE := 0.12            ## seconds of crossfade between poses
const NAMES := {
	"breath": ["Breath", "Breathe"],
	"yaw": ["Head:: Yaw", "Head:: Yaw-Pitch"],
	"blink": ["Eye:: Blink", "Eye:: Left:: Blink", "Eye:: Right:: Blink"],
	"mouth": ["Mouth:: Open", "Mouth:: Shape"],
}

var poses := {}               ## pose name -> InochiPuppet
var _frames := {}             ## pose name -> {torso, neck} of its plate (for aligning poses)
var current: StringName = &""
var idle_pose: StringName = &"idle"
var _t := 0.0
var _rng := RandomNumberGenerator.new()
var _next_blink := 1.5
var _blink_t := -1.0
var _look := 0.0
var _look_to := 0.0
var _look_t := 0.0
var _talk_left := 0.0
var _pose_left := 0.0         ## seconds until a timed pose returns to idle
var _fade: Tween              ## the crossfade running, if any


func _ready() -> void:
	_rng.randomize()


## load a pose model; the first pose added is shown
func add_pose(pose: StringName, path: String) -> bool:
	var p := InochiPuppet.new()
	if not p.load_model(path):
		return false
	add_pose_puppet(pose, p, _read_frame(path))
	return true


## add a loaded model as a pose (add_pose does this after loading; tests build models in code)
func add_pose_puppet(pose: StringName, p: InochiPuppet, frame := {}) -> void:
	p.visible = poses.is_empty()
	add_child(p)
	# driven from here, so every pose gets the same idle parameters. Only after add_child: Godot turns processing
	# on when a node with _process enters the tree, and the model then also updated itself (hair physics ran twice)
	p.set_process(false)
	poses[pose] = p
	_frames[pose] = frame
	if current == &"":
		current = pose
	_align(pose)


## the plate's torso length (neck to the middle of the hips), neck (fig_joints.json next to the model, from
## Tools/art/live_layers.py) and foot line (the lowest row of the figure), relative to the plate centre: poses drawn
## with different framing are scaled so torso length matches the first, then moved so the neck lines up across and
## the feet stay on the same ground (a crouch keeps its feet down instead of hanging from the neck). (The face size
## is no good for this: a face seen from the side measures much smaller than the same face from the front.)
func _read_frame(path: String) -> Dictionary:
	var dir := path.get_base_dir()
	var jp := dir.path_join("fig_joints.json")
	var fp := dir.path_join("full.png")
	if not FileAccess.file_exists(jp) or not FileAccess.file_exists(fp):
		return {}
	var j = JSON.parse_string(FileAccess.get_file_as_string(jp))
	var img := Image.load_from_file(fp)
	if not j is Dictionary or img == null:
		return {}
	for k in ["neck", "hip_l", "hip_r"]:   # a joint the detector missed is null
		if not j.get(k) is Array:
			return {}
	var half := Vector2(img.get_width(), img.get_height()) / 2.0
	var neck := Vector2(float(j["neck"][0]), float(j["neck"][1]))
	var hips := (Vector2(float(j["hip_l"][0]), float(j["hip_l"][1])) + Vector2(float(j["hip_r"][0]), float(j["hip_r"][1]))) / 2.0
	var feet := float(img.get_height())
	for y in range(img.get_height() - 1, -1, -1):
		var hit := false
		for x in range(0, img.get_width(), 2):
			if img.get_pixel(x, y).a > 0.5:
				hit = true
				break
		if hit:
			feet = float(y)
			break
	return {"torso": neck.distance_to(hips), "neck": neck - half, "feet": feet - half.y}


func _align(pose: StringName) -> void:
	var first: StringName = poses.keys()[0]
	var a: Dictionary = _frames.get(first, {})
	var b: Dictionary = _frames.get(pose, {})
	if pose == first or a.is_empty() or b.is_empty() or b["torso"] <= 0.0:
		return
	var k: float = a["torso"] / b["torso"]
	var p: InochiPuppet = poses[pose]
	p.scale = Vector2.ONE * k
	p.position = Vector2(a["neck"].x - b["neck"].x * k, a["feet"] - b["feet"] * k)


## show a pose; with a duration it goes back to the idle pose afterwards (a skill: draw 0.4 s, then release 0.6 s)
func play_pose(pose: StringName, duration := 0.0) -> void:
	if not poses.has(pose) or pose == current:
		return
	# a switch during a crossfade: stop that fade and settle every other pose first, so its end can't hide the
	# pose that is showing now (switching back before 0.12 s left nothing on screen)
	if _fade != null and _fade.is_valid():
		_fade.kill()
	var old: InochiPuppet = poses.get(current)
	for k in poses:
		if poses[k] != old:
			poses[k].visible = false
			poses[k].modulate.a = 1.0
	var nxt: InochiPuppet = poses[pose]
	nxt.visible = true
	nxt.modulate.a = 0.0
	_fade = create_tween().set_parallel(true)
	_fade.tween_property(nxt, "modulate:a", 1.0, FADE)
	if old:
		_fade.tween_property(old, "modulate:a", 0.0, FADE)
		_fade.chain().tween_callback(func():
			if old != poses.get(current):
				old.visible = false
				old.modulate.a = 1.0)
	current = pose
	_pose_left = duration


## move the mouth for this many seconds (while a voice line plays)
func talk(seconds: float) -> void:
	_talk_left = maxf(_talk_left, seconds)


func _process(delta: float) -> void:
	_t += delta
	if _pose_left > 0.0:
		_pose_left -= delta
		if _pose_left <= 0.0:
			var was := current
			play_pose(idle_pose)
			pose_finished.emit(was)
	if _t >= _next_blink:
		_blink_t = _t
		_next_blink = _t + _rng.randf_range(2.5, 5.5)
	var blink := sin((_t - _blink_t) / 0.18 * PI) if _blink_t >= 0.0 and _t - _blink_t < 0.18 else 0.0
	if _t >= _look_t:
		_look_to = _rng.randf_range(-0.6, 0.6) if _rng.randf() < 0.6 else 0.0
		_look_t = _t + _rng.randf_range(2.0, 5.0)
	_look = lerpf(_look, _look_to, minf(1.0, delta * 2.0))
	var mouth := 0.0
	if _talk_left > 0.0:
		_talk_left -= delta
		mouth = 0.5 + 0.5 * sin(_t * 15.0)
	for pose in poses:
		var p: InochiPuppet = poses[pose]
		if not p.visible:
			continue
		_drive(p, "breath", 0.5 + 0.5 * sin(_t * 1.7))
		_drive(p, "yaw", _look)
		_drive(p, "blink", blink)
		_drive(p, "mouth", mouth)
		p.update_puppet(delta)


func _drive(p: InochiPuppet, key: String, v: float) -> void:
	for nm in NAMES[key]:
		var prm: Dictionary = p.param_by_name.get(nm, {})
		if prm.is_empty():
			continue
		if prm["is_vec2"]:   # Aka-style 2D: yaw on x; a 2D mouth opens on y (0 closed, 1 open)
			var cur: Vector2 = prm["value"]
			p.set_param(nm, Vector2(v, cur.y) if key == "yaw" else Vector2(cur.x, v))
		else:
			p.set_param(nm, v)
		if key != "blink":   # blink sets both eyes on Aka-style models
			return
