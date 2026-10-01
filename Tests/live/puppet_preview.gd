extends Node2D
## Plays an Inochi2D model with InochiPuppet and saves frames, to check the player by eye (needs a window, not
## --headless). Parameters are swept so every kind of binding shows: head yaw / pitch, blink, mouth, breath, and the
## physics settling after the head moves.
##   Godot_console.exe --path . res://Tests/live/puppet_preview.tscn -- <model.inx> <out_dir> [param=value ...]

var puppet: InochiPuppet
var out_dir := "user://puppet_preview"


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	var model := args[0] if args.size() > 0 else ""
	if args.size() > 1:
		out_dir = args[1]
	DirAccess.make_dir_recursive_absolute(out_dir)
	RenderingServer.set_default_clear_color(Color(0.78, 0.78, 0.8))
	puppet = InochiPuppet.new()
	puppet.set_process(false)   # frames are stepped by hand below
	var t0 := Time.get_ticks_msec()
	if not puppet.load_model(model):
		get_tree().quit(1)
		return
	print("loaded %s in %d ms: %d nodes, %d params, %d textures" % [model.get_file(), Time.get_ticks_msec() - t0,
		puppet.nodes.size(), puppet.params.size(), puppet.textures.size()])
	print("params: ", ", ".join(puppet.param_names()))
	add_child(puppet)
	_fit()
	var probes: Array = []
	for a in args.slice(2):
		var kv := String(a).split("=")
		if kv[0] == "secs" or kv[0] == "motion":
			continue
		if kv[0] == "probe":   # probe=x,y (window pixels): list the parts drawn there
			probes.append(Vector2(float(kv[1].split(",")[0]), float(kv[1].split(",")[1])))
		else:   # held for the whole run: the sweep leaves it alone ("x,y" for a 2D parameter)
			var xy := kv[1].split(",")
			puppet.set_param(kv[0], Vector2(float(xy[0]), float(xy[1])) if xy.size() > 1 else float(kv[1]))
			_fixed[kv[0]] = true
	for pt in probes:
		_probe(pt)
	var secs := 0.0
	for a in args.slice(2):
		if String(a).begins_with("secs="):
			secs = float(String(a).substr(5))
	var motion := ""
	for a in args.slice(2):
		if String(a).begins_with("motion="):
			motion = String(a).substr(7)
	if motion != "":
		await _run_motion(motion)
	elif secs > 0.0:
		await _run_long(secs)
	else:
		await _run()
	get_tree().quit(0)


## scale and centre the model in the window from its parts' bounds
func _fit() -> void:
	var r := Rect2()
	var first := true
	for uuid in puppet.nodes:
		var n: Dictionary = puppet.nodes[uuid]
		if n.has("verts"):
			for p in puppet.part_points(n):
				r = Rect2(p, Vector2.ZERO) if first else r.expand(p)
				first = false
	var vp := get_viewport_rect().size
	var k := minf(vp.x / r.size.x, vp.y / r.size.y) * 0.92
	puppet.scale = Vector2.ONE * k
	puppet.position = vp / 2.0 - (r.position + r.size / 2.0) * k


func _run() -> void:
	var shots := {0: "rest", 30: "yaw_right", 60: "yaw_left_blink", 90: "mouth_open", 150: "settled"}
	var ms := 0.0
	for f in 151:
		var t := f / 30.0
		var yaw := 0.0
		if f >= 15 and f < 45:
			yaw = 1.0
		elif f >= 45 and f < 75:
			yaw = -1.0
		_set_first(["Head:: Yaw-Pitch", "Head:: Yaw", "Head Yaw"], Vector2(yaw, 0.3 if f >= 45 and f < 75 else 0.0))
		_set_first(["Eye:: Left:: Blink", "Eye:: Blink", "Blink"], 1.0 if f >= 55 and f < 65 else 0.0)
		_set_first(["Eye:: Right:: Blink", "Eye Blink R"], 1.0 if f >= 55 and f < 65 else 0.0)
		_set_first(["Mouth:: Shape", "Mouth:: Open", "Mouth"], 1.0 if f >= 80 and f < 110 else 0.0)
		_set_first(["Breath", "Breathe"], 0.5 + 0.5 * sin(t * 2.0))
		var s := Time.get_ticks_usec()
		puppet.update_puppet(1.0 / 30.0)
		ms += (Time.get_ticks_usec() - s) / 1000.0
		await get_tree().process_frame
		if shots.has(f):
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(out_dir.path_join("%03d_%s.png" % [f, shots[f]]))
			print("shot ", shots[f])
	print("update: %.2f ms per frame on average" % (ms / 151.0))


var _defaults := {}
var _fixed := {}


## set the first parameter that exists; for a 2D parameter given a single number, only its second axis moves away
## from the model's default (Aka's "Mouth:: Shape" is 2D: its default (1, 1) is the closed mouth)
func _set_first(names: Array, value: Variant) -> void:
	for nm in names:
		var p: Dictionary = puppet.param_by_name.get(nm, {})
		if p.is_empty():
			continue
		if _fixed.has(nm):
			return
		if not _defaults.has(nm):
			_defaults[nm] = p["value"]
		var d: Vector2 = _defaults[nm]
		if value is Vector2:
			puppet.set_param(nm, value if p["is_vec2"] else value.x)
		elif p["is_vec2"]:
			puppet.set_param(nm, Vector2(d.x, lerpf(d.y, 1.0 - d.y, float(value))) if float(value) > 0.0 else d)
		else:
			puppet.set_param(nm, value)
		return


func _probe(screen: Vector2) -> void:
	var local: Vector2 = puppet.get_global_transform_with_canvas().affine_inverse() * (get_viewport().get_screen_transform().affine_inverse() * screen)
	var hits: Array = []
	for uuid in puppet.nodes:
		var n: Dictionary = puppet.nodes[uuid]
		if not n.has("indices"):
			continue
		var pts := puppet.part_points(n)
		var idx: PackedInt32Array = n["indices"]
		for i in range(0, idx.size(), 3):
			if Geometry2D.point_is_inside_triangle(local, pts[idx[i]], pts[idx[i + 1]], pts[idx[i + 2]]):
				hits.append("%s (z %.2f, %s%s)" % [n["name"], puppet.zsort_of(n), n["blend"], ", masked" if not n["masks"].is_empty() else ""])
				break
	print("probe %s: %s" % [screen, "; ".join(hits)])


## secs seconds of idle life: breathing, a blink every few seconds, the head looking around, talking now and then;
## a frame every 1.5 s plus every 3rd frame for an animated GIF (out_dir/anim_*.png)
func _run_long(secs: float) -> void:
	var frames := int(secs * 30.0)
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	var next_blink := 2.0
	var blink_t := -1.0
	var look := 0.0
	var look_to := 0.0
	var look_t := 0.0
	for f in frames:
		var t := f / 30.0
		if t >= next_blink:
			blink_t = t
			next_blink = t + rng.randf_range(2.5, 5.0)
		var blink := 0.0
		if blink_t >= 0.0 and t - blink_t < 0.2:
			blink = sin((t - blink_t) / 0.2 * PI)
		if t >= look_t:
			look_to = rng.randf_range(-1.0, 1.0) if rng.randf() < 0.7 else 0.0
			look_t = t + rng.randf_range(2.0, 4.0)
		look = lerpf(look, look_to, 0.06)
		var talking := fmod(t, 10.0) > 6.0 and fmod(t, 10.0) < 9.0
		var mouth := (0.5 + 0.5 * sin(t * 14.0)) if talking else 0.0
		_set_first(["Head:: Yaw-Pitch", "Head:: Yaw", "Head Yaw"], Vector2(look, 0.15 * sin(t * 0.7)))
		_set_first(["Eye:: Left:: Blink", "Eye:: Blink", "Blink"], blink)
		_set_first(["Eye:: Right:: Blink", "Eye Blink R"], blink)
		_set_first(["Mouth:: Shape", "Mouth:: Open", "Mouth"], mouth)
		_set_first(["Breath", "Breathe"], 0.5 + 0.5 * sin(t * 1.6))
		_set_first(["Eye:: Look"], clampf(look * 1.3, -1.0, 1.0))   # the eyes lead the head
		_set_first(["Brow:: Up"], 0.6 if talking else 0.0)
		# the body, arms and tail (models that have them): slow sways, and a big lean every 10 s so the hair,
		# sleeves and skirt physics have something to swing after
		var lean := sin(clampf((fmod(t, 10.0) - 1.0) / 2.0, 0.0, 1.0) * PI)
		_set_first(["Body:: Yaw-Pitch"], Vector2(0.6 * sin(t * 0.5) + 0.4 * lean, 0.2 * sin(t * 0.9)))
		_set_first(["Body:: Roll"], 0.5 * sin(t * 0.7) + 0.5 * lean)
		_set_first(["Head:: Roll"], 0.4 * sin(t * 0.6 + 1.0))
		_set_first(["Body:: X:: Move"], 0.5 * lean)
		_set_first(["Arm:: Left:: Move"], sin(t * 1.1))
		_set_first(["Arm:: Right:: Move"], sin(t * 0.9 + 2.0))
		_set_first(["Tail:: Move"], sin(t * 1.7))
		puppet.update_puppet(1.0 / 30.0)
		await get_tree().process_frame
		if f % 3 == 0 or f % 45 == 0:
			await RenderingServer.frame_post_draw
			var img := get_viewport().get_texture().get_image()
			if f % 3 == 0:
				img.save_png(out_dir.path_join("anim_%04d.png" % (f / 3)))
			if f % 45 == 0:
				img.save_png(out_dir.path_join("sheet_%04d.png" % f))
	print("recorded %d frames" % frames)


## motion=jump: three hops (crouch, up, fall, land with a squash); motion=run: runs back and forth with a bob and a
## forward lean. The whole model moves through InochiPuppet.root_offset so its physics swing. 12 s, frames as in secs=
func _run_motion(kind: String) -> void:
	var size := 0.0
	for uuid in puppet.nodes:
		var n: Dictionary = puppet.nodes[uuid]
		if n.has("verts"):
			for p in puppet.part_points(n):
				size = maxf(size, absf(p.y))
	var h := size * 0.3          # jump height / run width in model units
	puppet.scale *= 0.8
	puppet.position.y += get_viewport_rect().size.y * 0.08
	for f in 360:
		var t := f / 30.0
		var off := Vector2.ZERO
		var sq := Vector2.ONE
		var lean := 0.0
		if kind == "jump":
			var c := fmod(t, 4.0)            # 0-0.4 crouch, 0.4-1.4 air, 1.4-1.8 land, rest idle
			if c < 0.4:
				var k := sin(c / 0.4 * PI)
				sq = Vector2(1.0 + 0.06 * k, 1.0 - 0.08 * k)
			elif c < 1.4:
				var u := (c - 0.4) / 1.0
				off.y = -h * 4.0 * u * (1.0 - u)
				sq = Vector2(0.97, 1.04)
			elif c < 1.8:
				var k := sin((c - 1.4) / 0.4 * PI)
				sq = Vector2(1.0 + 0.1 * k, 1.0 - 0.12 * k)
		else:
			var x := sin(t * 0.8)                   # back and forth
			var v := cos(t * 0.8)                   # speed (and direction)
			off.x = x * h * 0.8
			off.y = -absf(sin(t * 9.0)) * h * 0.04  # a step bob
			lean = clampf(v, -1.0, 1.0)
		puppet.root_offset = off
		puppet.root_scale = sq
		_set_first(["Body:: Yaw-Pitch"], Vector2(0.8 * lean, -0.3 * absf(lean)))
		_set_first(["Body:: Roll"], -0.6 * lean)
		_set_first(["Head:: Yaw-Pitch", "Head:: Yaw"], Vector2(0.7 * lean, 0.0))
		_set_first(["Breath", "Breathe"], 0.5 + 0.5 * sin(t * 4.0))
		_set_first(["Arm:: Left:: Move"], sin(t * 9.0) * absf(lean) if kind == "run" else (-1.0 if off.y < -h * 0.2 else 0.0))
		_set_first(["Arm:: Right:: Move"], -sin(t * 9.0) * absf(lean) if kind == "run" else (-1.0 if off.y < -h * 0.2 else 0.0))
		puppet.update_puppet(1.0 / 30.0)
		await get_tree().process_frame
		if f % 2 == 0:
			await RenderingServer.frame_post_draw
			var img := get_viewport().get_texture().get_image()
			img.save_png(out_dir.path_join("anim_%04d.png" % (f / 2)))
			if f % 30 == 0:
				img.save_png(out_dir.path_join("sheet_%04d.png" % f))
	print("recorded motion ", kind)
