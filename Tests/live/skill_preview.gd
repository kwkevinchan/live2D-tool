extends Node2D
## A skill played with key poses (Docs/Design/22, combat motions): LivePortrait switches idle -> the skill's poses ->
## idle with crossfades, plus effects: light gathering at the weapon hand, then the style's release (an arrow
## streak, a fireball, a frost sweep, a ground slam), a flash and a small shake. Poses that are missing fall back to
## the idle model. Saves frames for a GIF.
##   Godot_console.exe --path . res://Tests/live/skill_preview.tscn -- <out_dir> [style=bow|fire|frost|slam] idle=<inx> [<pose>=<inx> ...]
## The pose names are the style's (STYLES below), e.g. bow: raise, draw, release.

## per style, 30 fps: the poses and the frame each starts on (hold = seconds before idle comes back, 0 = stays),
## where light gathers (pose, from frame, to frame) and the release (pose, frame); the effect sits at that pose's
## weapon hand (weapon_grip in fig_joints.json next to its model), gather_at "top" puts the gathering on the top of
## the weapon (a staff's orb), release_at "top" / "bottom" does the same for the release (a fireball leaving the staff's orb, a
## wrench hitting the ground)
const STYLES := {
	"bow": {"poses": [["raise", 30, 0.0], ["draw", 42, 0.0], ["release", 63, 0.6]],
			"gather": ["draw", 42, 63], "release": ["draw", 63], "color": Color(0.7, 1.0, 0.8)},
	"fire": {"poses": [["raise", 30, 0.0], ["cast", 45, 0.0], ["recover", 56, 0.4]],   # Freya: raise 0.5 s, cast 0.35 s (launch at 40%), recover 0.4 s
			"gather": ["raise", 32, 45], "gather_at": "top", "release": ["cast", 49], "release_at": "top", "color": Color(1.0, 0.55, 0.2)},
	"frost": {"poses": [["open", 30, 0.0], ["sweep", 40, 0.0], ["point", 52, 0.3]],   # Yukino: open 0.35 s, sweep 0.4 s (release at 50%), point 0.3 s
			"gather": ["open", 31, 40], "release": ["sweep", 46], "color": Color(0.6, 0.85, 1.0)},
	"slam": {"poses": [["windup", 30, 0.0], ["slam", 44, 0.0], ["impact", 50, 0.4]],   # Rena: windup 0.45 s, hits 0.15 s into the downswing, impact 0.4 s
			"gather": ["windup", 31, 44], "release": ["slam", 49], "release_at": "bottom", "color": Color(1.0, 0.85, 0.4)},
}
const FRAMES := 120

var out_dir := "user://skill_preview"
var style := "bow"
var lp: LivePortrait
var fx: Node2D
var _sparks: Array = []       ## [pos, vel, life, size]
var _shot := 0.0              ## release effect time left
var _flash := 0.0
var _shake := 0.0
var _gather := 0.0
var _origin := Vector2.ZERO
var _impact := Vector2.ZERO   ## where the release happened (the slam ring stays there)
var _aims := {}               ## pose -> [hand in model space, direction away from the other hand]
var _tips := {}               ## pose -> [top, bottom] of its weapon in model space


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.16, 0.14, 0.2))
	var paths := {}
	for a in OS.get_cmdline_user_args():
		var kv := String(a).split("=", true, 1)
		if kv.size() == 2:
			paths[kv[0]] = kv[1]
		else:
			out_dir = a
	style = paths.get("style", "bow")
	if not STYLES.has(style):
		printerr("unknown style ", style)
		get_tree().quit(1)
		return
	DirAccess.make_dir_recursive_absolute(out_dir)
	lp = LivePortrait.new()
	add_child(lp)
	lp.set_process(false)   # stepped by hand in _run (running on its own too, every timing went twice as fast); after add_child, or Godot turns it back on
	var names: Array = ["idle"]
	for p in STYLES[style]["poses"]:
		names.append(p[0])
	for pose in names:
		var path: String = paths.get(pose, paths.get("idle", ""))
		if not lp.add_pose(StringName(pose), path):
			printerr("cannot load ", path)
			get_tree().quit(1)
			return
		_aims[pose] = _read_aim(path)
		_tips[pose] = _read_tips(path)
	_fit()
	fx = Node2D.new()
	fx.z_index = 10
	fx.draw.connect(_draw_fx)
	add_child(fx)
	await _run()
	get_tree().quit(0)


func _fit() -> void:
	var p: InochiPuppet = lp.poses[&"idle"]
	var r := Rect2()
	var first := true
	for uuid in p.nodes:
		var n: Dictionary = p.nodes[uuid]
		if n.has("verts"):
			for q in p.part_points(n):
				r = Rect2(q, Vector2.ZERO) if first else r.expand(q)
				first = false
	var vp := get_viewport_rect().size
	var k := minf(vp.x / r.size.x, vp.y / r.size.y) * 0.85
	lp.scale = Vector2.ONE * k
	_origin = vp / 2.0 - (r.position + r.size / 2.0) * k
	lp.position = _origin


## the weapon hand (weapon_grip) of a pose's plate, relative to the plate centre, and the direction away from the
## other hand (where an arrow flies, where a staff points)
func _read_aim(inx: String) -> Array:
	var dir := inx.get_base_dir()
	var j = JSON.parse_string(FileAccess.get_file_as_string(dir.path_join("fig_joints.json"))) if FileAccess.file_exists(dir.path_join("fig_joints.json")) else null
	var img := Image.load_from_file(dir.path_join("full.png")) if FileAccess.file_exists(dir.path_join("full.png")) else null
	if not j is Dictionary or img == null or not j.get("weapon_grip") is Dictionary:
		return [Vector2.ZERO, Vector2(1, -0.3).normalized()]
	var half := Vector2(img.get_width(), img.get_height()) / 2.0
	var grip := Vector2(j["weapon_grip"]["point"][0], j["weapon_grip"]["point"][1])
	var other := "wrist_l" if j["weapon_grip"]["hand"] == "arm_r" else "wrist_r"
	var pull := Vector2(j[other][0], j[other][1]) if j.get(other) is Array else grip - Vector2(1, 0)
	var d := grip - pull
	return [grip - half, d.normalized() if d.length() > 1.0 else Vector2(1, 0)]


func _aim_point(pose: String) -> Vector2:   # through the pose's own alignment inside the portrait
	var p: InochiPuppet = lp.poses[StringName(pose)]
	return lp.position + (p.position + _aims[pose][0] * p.scale) * lp.scale


## the top or bottom tip of the pose's weapon, from its layer next to the model (st/part_objects.png or
## fig_weapon.png, plate-sized): where a wrench swung down hits the ground, the orb on top of a staff; the weapon
## hand when there is no weapon layer
func _weapon_tip(pose: String, top: bool) -> Vector2:
	var t: Vector2 = _tips[pose][0 if top else 1]
	if t.x == INF:
		return _aim_point(pose)
	var p: InochiPuppet = lp.poses[StringName(pose)]
	return lp.position + (p.position + t * p.scale) * lp.scale


func _read_tips(inx: String) -> Array:
	var none := [Vector2(INF, INF), Vector2(INF, INF)]
	var dir := inx.get_base_dir()
	var img: Image = null
	for f in ["st/part_objects.png", "fig_weapon.png"]:
		if FileAccess.file_exists(dir.path_join(f)):
			img = Image.load_from_file(dir.path_join(f))
			break
	if img == null:
		return none
	var w := img.get_width()
	var h := img.get_height()
	var rows := [-1, -1]
	for y in h:
		for x in range(0, w, 2):
			if img.get_pixel(x, y).a > 0.5:
				if rows[0] < 0:
					rows[0] = y
				rows[1] = y
				break
	if rows[0] < 0:
		return none
	var out := []
	for y in rows:   # the middle of the opaque run on that row
		var xs := []
		for x in w:
			if img.get_pixel(x, y).a > 0.5:
				xs.append(x)
		out.append(Vector2((xs[0] + xs[-1]) / 2.0, y) - Vector2(w, h) / 2.0)
	return out


func _gather_point() -> Vector2:
	var g: Array = STYLES[style]["gather"]
	return _weapon_tip(g[0], true) if STYLES[style].get("gather_at", "") == "top" else _aim_point(g[0])


func _run() -> void:
	var s: Dictionary = STYLES[style]
	var cues := {}
	for p in s["poses"]:
		cues[p[1]] = p
	var g: Array = s["gather"]
	var rel: Array = s["release"]
	var col: Color = s["color"]
	for f in FRAMES:
		if cues.has(f):
			lp.play_pose(StringName(cues[f][0]), cues[f][2])
		if f >= g[2]:   # the gathered light goes with the pose it gathered on
			_gather = maxf(0.0, _gather - 0.34)
		if f >= g[1] and f < g[2]:
			_gather = minf(1.0, _gather + 1.0 / float(g[2] - g[1]))
			if f % 2 == 0:
				var a := randf() * TAU
				_sparks.append([_gather_point() + Vector2(cos(a), sin(a)) * 160.0, -Vector2(cos(a), sin(a)) * 240.0, 0.6, 3.0])
		if f == rel[1]:
			var at: String = s.get("release_at", "")
			_impact = _weapon_tip(rel[0], at == "top") if at != "" else _aim_point(rel[0])
			_release(_impact, _aims[rel[0]][1])
		var dt := 1.0 / 30.0
		lp._process(dt)
		_flash = maxf(0.0, _flash - dt)
		_shot = maxf(0.0, _shot - dt)
		_shake = maxf(0.0, _shake - dt)
		lp.position = _origin + (Vector2(randf_range(-1, 1), randf_range(-1, 1)) * 10.0 * _shake / 0.25 if _shake > 0.0 else Vector2.ZERO)
		for sp in _sparks:
			sp[0] += sp[1] * dt
			if style == "slam":
				sp[1].y += 900.0 * dt   # sparks from the ground fall back
			sp[2] -= dt
		_sparks = _sparks.filter(func(sp): return sp[2] > 0.0)
		fx.queue_redraw()
		await get_tree().process_frame
		if f % 2 == 0:
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(out_dir.path_join("anim_%04d.png" % (f / 2)))
	print("recorded skill ", style)


func _release(at: Vector2, dir: Vector2) -> void:
	_gather = 0.0
	_flash = 0.25
	_shot = 0.35 if style == "bow" else 0.5
	_shake = 0.4 if style == "slam" else 0.25
	if style == "slam":   # sparks burst up and out from where the wrench hits
		for i in 40:
			var a := randf_range(PI * 1.05, PI * 1.95)
			_sparks.append([at, Vector2(cos(a), sin(a)) * randf_range(250.0, 650.0), randf_range(0.4, 0.8), randf_range(2.0, 5.0)])
	elif style == "frost":   # ice shards along the sweep
		for i in 24:
			var a := dir.angle() + randf_range(-0.9, 0.9)
			_sparks.append([at, Vector2(cos(a), sin(a)) * randf_range(300.0, 700.0), randf_range(0.4, 0.7), randf_range(2.0, 4.0)])


func _draw_fx() -> void:
	var vp := get_viewport_rect().size
	var s: Dictionary = STYLES[style]
	var col: Color = s["color"]
	var rp: String = s["release"][0]
	if _gather > 0.0:
		var c := _gather_point()
		fx.draw_circle(c, 18.0 + 30.0 * _gather, Color(col, 0.25 * _gather))
		fx.draw_circle(c, 8.0 + 10.0 * _gather, Color(1, 1, 0.9, 0.7 * _gather))
	for sp in _sparks:
		fx.draw_circle(sp[0], sp[3], Color(col.lightened(0.3), clampf(sp[2] / 0.6, 0.0, 1.0)))
	if _shot > 0.0:
		var c := _impact
		var dir: Vector2 = _aims[rp][1]
		match style:
			"bow":
				var k := 1.0 - _shot / 0.35
				var a := c + dir * vp.x * 0.7 * k
				fx.draw_line(a - dir * 110.0, a, Color(1, 1, 0.85, 0.9), 6.0)
				fx.draw_line(a - dir * 210.0, a, Color(col, 0.35), 14.0)
			"fire":
				var k := 1.0 - _shot / 0.5
				var a := c + dir * vp.x * 0.7 * k
				for i in 5:   # a trail of shrinking embers behind the ball
					fx.draw_circle(a - dir * 26.0 * i, 30.0 - 5.0 * i, Color(col, 0.6 - 0.1 * i))
				fx.draw_circle(a, 16.0, Color(1, 0.95, 0.7, 0.95))
			"frost":
				var k := 1.0 - _shot / 0.5
				var r := 60.0 + 260.0 * k
				var a0 := dir.angle()
				fx.draw_arc(c, r, a0 - 0.9, a0 + 0.9, 32, Color(col, 0.8 * (1.0 - k)), 14.0)
				fx.draw_arc(c, r * 0.8, a0 - 0.7, a0 + 0.7, 32, Color(1, 1, 1, 0.6 * (1.0 - k)), 5.0)
			"slam":
				var k := 1.0 - _shot / 0.5
				fx.draw_arc(c, 30.0 + 280.0 * k, PI, TAU, 40, Color(col, 0.8 * (1.0 - k)), 10.0)
				fx.draw_line(c - Vector2(160.0 * k, 0), c + Vector2(160.0 * k, 0), Color(1, 1, 0.9, 0.9 * (1.0 - k)), 4.0)
	if _flash > 0.0:
		fx.draw_rect(Rect2(Vector2.ZERO, vp), Color(1, 1, 1, 0.6 * _flash / 0.25))
