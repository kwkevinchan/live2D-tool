extends Node
## Renders rigged models at rest, pixel for pixel on their plate (model space is relative to the plate centre), for
## Tools/art/rig_check.py to compare with the plate. Needs a window (the headless renderer draws nothing).
##   Godot_console.exe --path . res://Tests/live/rig_render.tscn -- <model.inx>=<out.png>=<w>x<h>[=<param>:<v>;...] ...
## (a 2D parameter takes <x>,<y>; parameters left out stay at their defaults). @<file> reads the jobs from a file, one
## per line (Windows caps the command line: a range search renders a couple of hundred poses).


func _ready() -> void:
	var failed := 0
	var jobs: Array = []
	for a in OS.get_cmdline_user_args():
		if String(a).begins_with("@"):
			jobs.append_array(FileAccess.get_file_as_string(String(a).substr(1)).split("\n", false))
		else:
			jobs.append(String(a))
	for a in jobs:
		var f := String(a).strip_edges().split("=")
		if f.size() < 3:
			continue
		var wh := f[2].split("x")
		var size := Vector2i(int(wh[0]), int(wh[1]))
		if not await _render(f[0], f[1], size, f[3] if f.size() > 3 else ""):
			failed += 1
	get_tree().quit(1 if failed else 0)


func _render(inx: String, out: String, size: Vector2i, params: String) -> bool:
	var vp := SubViewport.new()
	vp.size = size
	vp.transparent_bg = true
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(vp)
	var p := InochiPuppet.new()
	p.set_process(false)          # at rest: parameters at their defaults, no physics step
	if not p.load_model(inx):
		printerr("cannot load ", inx)
		vp.queue_free()
		return false
	p.position = Vector2(size) / 2.0
	vp.add_child(p)
	for kv in params.split(";", false):
		var nv := kv.rsplit(":", true, 1)
		var v := nv[1].split(",")
		if not p.set_param(nv[0], Vector2(float(v[0]), float(v[1])) if v.size() > 1 else float(v[0])):
			printerr("no parameter ", nv[0], " in ", inx.get_file())
	p.update_puppet(0.0)
	for i in 3:
		await RenderingServer.frame_post_draw
	var ok := vp.get_texture().get_image().save_png(out) == OK
	print("rendered ", inx.get_file(), " -> ", out)
	vp.queue_free()
	return ok
