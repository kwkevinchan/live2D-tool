extends Node
## InochiPuppet rules on small models built in code (no files, runs headless): parameter bindings (1D, 2D, deform,
## opacity, zSort), draw order, masks, ClipToLower inside a composite, physics reacting to a moving model, and
## LivePortrait's idle loop and pose switching.
##   Godot_console.exe --headless --path . res://Tests/live/puppet_test.tscn

var failures := 0
var checks := 0


func check(cond: bool, msg: String) -> void:
	checks += 1
	if not cond:
		failures += 1
		printerr("FAIL: ", msg)


func _tr(x := 0.0, y := 0.0) -> Dictionary:
	return {"trans": [x, y, 0.0], "rot": [0.0, 0.0, 0.0], "scale": [1.0, 1.0]}


## a 2x2-vertex square part (texture slot 0 missing on purpose: nothing is drawn, the rules still run)
func _part(uuid: int, name: String, z: float, extra := {}) -> Dictionary:
	var p := {"uuid": uuid, "name": name, "type": "Part", "enabled": true, "zsort": z, "transform": _tr(), "lockToRoot": false,
		"mesh": {"verts": [-10.0, -10.0, 10.0, -10.0, 10.0, 10.0, -10.0, 10.0], "uvs": [0, 0, 1, 0, 1, 1, 0, 1],
			"indices": [0, 1, 2, 0, 2, 3], "origin": [0.0, 0.0]},
		"textures": [0], "blend_mode": "Normal", "tint": [1, 1, 1], "screenTint": [0, 0, 0], "mask_threshold": 0.5,
		"masks": [], "opacity": 1.0}
	p.merge(extra, true)
	return p


func _param(name: String, bindings: Array, axes := [[0.0, 1.0], [0.0]], is2 := false, lo := [0.0, 0.0], hi := [1.0, 1.0]) -> Dictionary:
	return {"uuid": name.hash(), "name": name, "is_vec2": is2, "min": lo, "max": hi, "defaults": [0.0, 0.0],
		"axis_points": axes, "bindings": bindings}


func _puppet(nodes: Dictionary, params: Array) -> InochiPuppet:
	var p := InochiPuppet.new()
	add_child(p)
	p.load_payload({"meta": {}, "physics": {"pixelsPerMeter": 1000.0, "gravity": 9.8}, "nodes": nodes, "param": params})
	return p


func _ready() -> void:
	_bindings()
	_order_and_masks()
	_physics()
	await _portrait()
	await _self_update()
	print("puppet: %d checks, %d failures" % [checks, failures])
	get_tree().quit(1 if failures > 0 else 0)


func _bindings() -> void:
	var a := _part(2, "A", 0.0)
	var root := {"uuid": 1, "name": "Root", "type": "Node", "enabled": true, "zsort": 0.0, "transform": _tr(), "children": [a]}
	var move := _param("Move", [{"node": 2, "param_name": "transform.t.x", "values": [[0.0], [40.0]]}])
	var grid := _param("Grid", [{"node": 2, "param_name": "transform.t.y", "values": [[0.0, 10.0], [20.0, 30.0]]}],
		[[0.0, 1.0], [0.0, 1.0]], true)
	var bend := _param("Bend", [{"node": 2, "param_name": "deform",
		"values": [[[[0, 0], [0, 0], [0, 0], [0, 0]]], [[[0, 0], [0, 0], [6, 0], [6, 0]]]]}])
	var fade := _param("Fade", [{"node": 2, "param_name": "opacity", "values": [[1.0], [0.0]]}])
	var p := _puppet(root, [move, grid, bend, fade])
	var n: Dictionary = p.nodes[2]
	p.set_param("Move", 0.5)
	p.update_puppet(0.0)
	check(is_equal_approx((n["global"] as Transform3D).origin.x, 20.0), "1D binding interpolates (x %.1f)" % (n["global"] as Transform3D).origin.x)
	p.set_param("Grid", Vector2(0.5, 0.5))
	p.update_puppet(0.0)
	check(is_equal_approx((n["global"] as Transform3D).origin.y, 15.0), "2D binding is bilinear (y %.1f)" % (n["global"] as Transform3D).origin.y)
	p.set_param("Bend", 1.0)
	p.update_puppet(0.0)
	var pts := p.part_points(n)
	check(is_equal_approx(pts[2].x - pts[1].x, 6.0) and is_equal_approx(pts[0].x, 10.0), "deform moves only the bound vertices")
	p.set_param("Fade", 1.0)
	p.update_puppet(0.0)
	check(p._views[2].self_modulate.a < 0.01, "opacity binding fades the part")
	p.set_param("Move", 7.0)
	p.update_puppet(0.0)
	check(is_equal_approx((n["global"] as Transform3D).origin.x, 40.0), "values beyond the range clamp")
	p.queue_free()


func _order_and_masks() -> void:
	var back := _part(2, "Back", 0.5)
	var front := _part(3, "Front", -0.5, {"masks": [{"source": 2, "mode": "Mask"}]})
	var white := _part(5, "White", 0.1)
	var iris := _part(6, "Iris", -0.2, {"blend_mode": "ClipToLower"})
	var comp := {"uuid": 4, "name": "Eye", "type": "Composite", "enabled": true, "zsort": -1.0, "transform": _tr(),
		"blend_mode": "Normal", "opacity": 1.0, "tint": [1, 1, 1], "children": [white, iris]}
	var root := {"uuid": 1, "name": "Root", "type": "Node", "enabled": true, "zsort": 0.0, "transform": _tr(), "children": [front, back, comp]}
	var swap := _param("Swap", [{"node": 2, "param_name": "zSort", "values": [[0.0], [-2.0]]}])
	var p := _puppet(root, [swap])
	check(p._order == [2, 3, 4], "higher zSort is drawn first (%s)" % [p._order])
	check(p._holders.has(3) and p._holders[3].mask_of == [2], "a masked part sits in a holder drawing its mask")
	check(p._lower_of(6) == 5, "ClipToLower inside a composite clips to that composite's part")
	p.set_param("Swap", 1.0)
	p.update_puppet(0.0)
	check(p._order[-1] == 2, "a zSort binding reorders parts (%s)" % [p._order])
	p.queue_free()


func _physics() -> void:
	var hair := _part(2, "Hair", 0.0)
	var phys := {"uuid": 3, "name": "Phys", "type": "SimplePhysics", "enabled": true, "zsort": 0.0, "transform": _tr(0, -50),
		"param": 77, "model_type": "SpringPendulum", "map_mode": "AngleLength", "gravity": 1.0, "length": 100.0,
		"frequency": 1.0, "angle_damping": 0.4, "length_damping": 0.5, "output_scale": [1.0, 1.0]}
	var root := {"uuid": 1, "name": "Root", "type": "Node", "enabled": true, "zsort": 0.0, "transform": _tr(), "children": [hair, phys]}
	var sway := _param("Sway", [{"node": 2, "param_name": "transform.t.x", "values": [[-50.0], [0.0], [50.0]]}],
		[[0.0, 0.5, 1.0], [0.0]], false, [-1.0, 0.0], [1.0, 0.0])
	sway["uuid"] = 77
	var p := _puppet(root, [sway])
	for i in 60:
		p.update_puppet(1.0 / 30.0)
	var rest: float = p.get_param("Sway").x
	p.root_offset = Vector2(200, 0)
	var peak := 0.0
	for i in 20:
		p.update_puppet(1.0 / 30.0)
		peak = maxf(peak, absf(p.get_param("Sway").x - rest))
	check(absf(rest) < 0.05, "physics settles hanging down (%.3f)" % rest)
	check(peak > 0.05, "moving the model swings the physics (peak %.3f)" % peak)
	for i in 300:
		p.update_puppet(1.0 / 30.0)
	check(absf(p.get_param("Sway").x - rest) < 0.05, "and it settles again (%.3f)" % p.get_param("Sway").x)
	p.queue_free()
	# a pendulum hung far from the origin (a skirt's at the knee) is at rest from the first frame: its start state
	# is worked out at its anchor's real place (it once started at the origin and bent the skirt at rest)
	var far := phys.duplicate(true)
	far["transform"] = _tr(300, 400)
	var root2 := {"uuid": 1, "name": "Root", "type": "Node", "enabled": true, "zsort": 0.0, "transform": _tr(),
		"children": [_part(2, "Hair", 0.0), far]}
	var sway2 := sway.duplicate(true)
	var q := _puppet(root2, [sway2])
	q.update_puppet(0.0)
	check(absf(q.get_param("Sway").x) < 0.05, "a pendulum far from the origin starts at rest (%.3f)" % q.get_param("Sway").x)
	q.queue_free()


## a pose model is driven by LivePortrait only: set_process(false) before add_child is undone when the node enters
## the tree, and the model then updated itself too (hair physics ran twice a frame)
func _self_update() -> void:
	var lp := LivePortrait.new()
	add_child(lp)
	var root := {"uuid": 1, "name": "Root", "type": "Node", "enabled": true, "zsort": 0.0, "transform": _tr(), "children": [_part(2, "Face", 0.0)]}
	var p := InochiPuppet.new()
	p.load_payload({"nodes": root, "param": []})
	lp.add_pose_puppet(&"idle", p)
	await get_tree().process_frame
	check(not p.is_processing(), "a pose model doesn't update itself besides LivePortrait")
	lp.queue_free()


func _portrait() -> void:
	var dir := "user://puppet_test"
	DirAccess.make_dir_recursive_absolute(dir)
	var lp := LivePortrait.new()
	add_child(lp)
	for pose in ["idle", "draw"]:
		var face := _part(2, "Face", 0.0)
		var root := {"uuid": 1, "name": "Root", "type": "Node", "enabled": true, "zsort": 0.0, "transform": _tr(), "children": [face]}
		var p := InochiPuppet.new()
		p.load_payload({"nodes": root, "param": [_param("Mouth:: Open", [{"node": 2, "param_name": "opacity", "values": [[0.0], [1.0]]}]),
			_param("Eye:: Blink", [])]})
		p.set_process(false)
		p.visible = lp.poses.is_empty()
		lp.add_child(p)
		lp.poses[StringName(pose)] = p
		if lp.current == &"":
			lp.current = StringName(pose)
	lp.talk(0.5)
	var opened := false
	for i in 20:
		await get_tree().process_frame
		lp._process(1.0 / 30.0)
		opened = opened or lp.poses[&"idle"].get_param("Mouth:: Open").x > 0.5
	check(opened, "talk() moves the mouth")
	var done := [false]
	lp.pose_finished.connect(func(_p): done[0] = true)
	lp.play_pose(&"draw", 0.3)
	check(lp.current == &"draw" and lp.poses[&"draw"].visible, "play_pose shows the pose")
	for i in 20:
		lp._process(1.0 / 30.0)
	check(done[0] and lp.current == &"idle", "a timed pose returns to idle")
	# switching back before the crossfade ends: the first fade must not hide the pose that is showing again
	for i in 12:
		await get_tree().process_frame
	lp.play_pose(&"draw")
	await get_tree().process_frame
	lp.play_pose(&"idle")
	await get_tree().create_timer(LivePortrait.FADE * 3.0).timeout
	var idle_p: InochiPuppet = lp.poses[&"idle"]
	var draw_p: InochiPuppet = lp.poses[&"draw"]
	check(idle_p.visible and idle_p.modulate.a > 0.99 and not draw_p.visible,
		"a quick switch back keeps the current pose shown (idle %s %.2f, draw %s)" % [idle_p.visible, idle_p.modulate.a, draw_p.visible])
	lp.queue_free()
