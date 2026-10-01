class_name InochiPuppet
extends Node2D
## Plays an Inochi2D 0.8 model (.inx, what Inochi Creator 0.8 saves) in plain GDScript, so it runs everywhere Godot
## does, phones included (Docs/Design/22_Live2D_Inochi2D.md). Rules follow the Inochi2D 0.8.7 source:
##   - nodes form a tree; each has a local transform plus per-frame offsets from parameters (translation and
##     rotation add, scale multiplies); global = parent global * local
##   - a parameter (1D or 2D) maps its value to 0..1 on each axis, finds the cell between its axis points and
##     interpolates every binding linearly: node offsets, zSort, opacity, or vertex deformation (offsets added up)
##   - parts are drawn back to front by zSort (higher = further back); a composite draws its own parts as a group
##   - masks: a part with "Mask" masks only shows where its masks are drawn (soft edge, no threshold); a
##     ClipToLower part shows only over the part drawn just below it; dodge masks are not supported
## The call flow is described in Docs/Code/07_Player.md.
##   - SimplePhysics drivers (pendulum / spring pendulum, RK4 in 10 ms steps) push a parameter each frame
## Use: var p := InochiPuppet.new(); p.load_model("res://…/model.inx"); add_child(p); p.set_param("Eye:: Left:: Blink", 1.0)

const MAGIC := "TRNSRTS\u0000"
const PHYS_STEP := 0.01
const MAX_PHYS_DELTA := 0.25   ## a long frame (the game back from the background) doesn't run seconds of physics at once

var nodes := {}              ## uuid -> node dictionary (see _make_node)
var root_uuid := -1
var params: Array = []       ## parameter dictionaries (see _make_param)
var param_by_name := {}
var textures: Array = []     ## Texture2D per texture slot
var drivers: Array = []      ## SimplePhysics node dictionaries
var gravity := 9.8
var pixels_per_meter := 1000.0
var meta := {}
## moves / squashes the whole model from inside (the root node), so hair and cloth physics react to it — a jump
## or a run done with the Node2D's position would carry the model without the physics noticing
var root_offset := Vector2.ZERO
var root_scale := Vector2.ONE
var _order: Array = []       ## current draw order of root drawables (uuids)
var _views := {}             ## drawable uuid -> PuppetPartView (or composite CanvasGroup)
var _holders := {}           ## part uuid -> mask holder Node2D


# ================================================================== loading
func load_model(path: String) -> bool:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		push_error("InochiPuppet: cannot open %s" % path)
		return false
	f.big_endian = true
	var payload := {}
	var tex_blobs: Array = []
	while f.get_position() < f.get_length():
		var tag := f.get_buffer(8).get_string_from_ascii()
		if tag == "TRNSRTS":
			var n := f.get_32()
			payload = JSON.parse_string(f.get_buffer(n).get_string_from_utf8())
		elif tag == "TEX_SECT":
			var count := f.get_32()
			for i in count:
				var length := f.get_32()
				var encoding := f.get_8()
				tex_blobs.append([encoding, f.get_buffer(length)] if length > 0 else [])
		elif tag == "EXT_SECT":
			var count := f.get_32()
			for i in count:
				f.get_buffer(f.get_32())
				f.get_buffer(f.get_32())
		else:
			break
	if payload.is_empty():
		push_error("InochiPuppet: %s has no model data" % path)
		return false
	for blob in tex_blobs:
		textures.append(_decode_texture(blob))
	return load_payload(payload)


## the JSON part of a model (also used by tests that build models in code)
func load_payload(payload: Dictionary) -> bool:
	meta = payload.get("meta", {})
	var phys: Dictionary = payload.get("physics", {})
	gravity = float(phys.get("gravity", 9.8))
	pixels_per_meter = float(phys.get("pixelsPerMeter", 1000.0))
	root_uuid = _make_node(payload["nodes"], -1)
	for p in payload.get("param", []):
		var prm := _make_param(p)
		params.append(prm)
		param_by_name[prm["name"]] = prm
	# the pendulums start hanging at rest under their anchors' real places: without the transforms worked out first
	# every anchor was at the origin, and a pendulum hung far from it (a skirt's at the knee) started with a big swing
	# that bent the part at rest (2026-10-02)
	_update_transforms(root_uuid, Transform3D.IDENTITY)
	for uuid in nodes:
		var n: Dictionary = nodes[uuid]
		if n["type"] == "SimplePhysics":
			n["system"] = _new_physics(n)
			drivers.append(n)
	_build_views()
	update_puppet(0.0)
	return true


func _decode_texture(blob: Array) -> Texture2D:
	if blob.is_empty():
		return null
	var img := Image.new()
	var err := ERR_FILE_UNRECOGNIZED
	match int(blob[0]):
		0: err = img.load_png_from_buffer(blob[1])
		1: err = img.load_tga_from_buffer(blob[1])
	if err != OK:
		push_warning("InochiPuppet: texture encoding %d not supported" % int(blob[0]))
		return null
	img.generate_mipmaps()   # portraits are drawn smaller than their textures: without mipmaps thin lines break into dots
	return ImageTexture.create_from_image(img)


func _v3(a: Variant, d := Vector3.ZERO) -> Vector3:
	return Vector3(float(a[0]), float(a[1]), float(a[2])) if a is Array and a.size() >= 3 else d


func _v2(a: Variant, d := Vector2.ZERO) -> Vector2:
	return Vector2(float(a[0]), float(a[1])) if a is Array and a.size() >= 2 else d


func _make_node(src: Dictionary, parent: int) -> int:
	var uuid := int(src.get("uuid", nodes.size() + 1))
	var tr: Dictionary = src.get("transform", {})
	var n := {"uuid": uuid, "name": String(src.get("name", "")), "type": String(src.get("type", "Node")), "parent": parent,
		"children": [], "enabled": bool(src.get("enabled", true)), "zsort": float(src.get("zsort", 0.0)),
		"lock": bool(src.get("lockToRoot", false)),
		"t": _v3(tr.get("trans")), "r": _v3(tr.get("rot")), "s": _v2(tr.get("scale"), Vector2.ONE),
		# per-frame offsets from parameters
		"ot": Vector3.ZERO, "or": Vector3.ZERO, "os": Vector2.ONE, "osort": 0.0, "oopacity": 1.0,
		"global": Transform3D.IDENTITY}
	match n["type"]:
		"Part", "AnimatedPart":
			var m: Dictionary = src.get("mesh", {})
			var verts := _flat_v2(m.get("verts", []))
			n["verts"] = verts
			n["uvs"] = _flat_v2(m.get("uvs", []))
			n["indices"] = PackedInt32Array(m.get("indices", []))
			n["origin"] = _v2(m.get("origin"))
			n["deform"] = PackedVector2Array()
			n["deform"].resize(verts.size())
			var tex: Array = src.get("textures", [])
			n["texture"] = int(tex[0]) if not tex.is_empty() else -1
			n["opacity"] = float(src.get("opacity", 1.0))
			n["tint"] = _v3(src.get("tint"), Vector3.ONE)
			n["blend"] = String(src.get("blend_mode", "Normal"))
			n["mask_threshold"] = float(src.get("mask_threshold", 0.5))
			n["masks"] = []
			for mk in src.get("masks", []):
				n["masks"].append({"source": int(mk["source"]), "mode": String(mk.get("mode", "Mask"))})
		"Composite":
			n["opacity"] = float(src.get("opacity", 1.0))
			n["tint"] = _v3(src.get("tint"), Vector3.ONE)
			n["blend"] = String(src.get("blend_mode", "Normal"))
		"SimplePhysics":
			n["param"] = int(src.get("param", -1))
			n["model"] = String(src.get("model_type", "Pendulum"))
			n["map"] = String(src.get("map_mode", "AngleLength"))
			n["p_gravity"] = float(src.get("gravity", 1.0))
			n["length"] = float(src.get("length", 100.0))
			n["frequency"] = float(src.get("frequency", 1.0))
			n["angle_damping"] = float(src.get("angle_damping", 0.5))
			n["length_damping"] = float(src.get("length_damping", 0.5))
			n["output_scale"] = _v2(src.get("output_scale"), Vector2.ONE)
			n["local_only"] = bool(src.get("local_only", false))
	nodes[uuid] = n
	for c in src.get("children", []):
		n["children"].append(_make_node(c, uuid))
	return uuid


func _flat_v2(a: Array) -> PackedVector2Array:
	var out := PackedVector2Array()
	out.resize(a.size() / 2)
	for i in out.size():
		out[i] = Vector2(float(a[i * 2]), float(a[i * 2 + 1]))
	return out


func _make_param(src: Dictionary) -> Dictionary:
	var is2 := bool(src.get("is_vec2", false))
	var axes: Array = src.get("axis_points", [[0.0, 1.0], [0.0]])
	var p := {"uuid": int(src.get("uuid", 0)), "name": String(src.get("name", "")), "is_vec2": is2,
		"min": _v2(src.get("min"), Vector2.ZERO), "max": _v2(src.get("max"), Vector2.ONE),
		"value": _v2(src.get("defaults"), Vector2.ZERO), "axes": [PackedFloat32Array(axes[0]), PackedFloat32Array(axes[1] if axes.size() > 1 else [0.0])],
		"bindings": [], "driven": false}
	for b in src.get("bindings", []):
		var node := int(b["node"])
		var target := String(b["param_name"])
		var vals: Array = b["values"]
		var grid: Array = []   # grid[x][y]: float, or PackedVector2Array for "deform"
		for x in vals.size():
			var col: Array = []
			for y in (vals[x] as Array).size():
				var v: Variant = vals[x][y]
				if target == "deform":
					var pts := PackedVector2Array()
					for q in (v as Array):
						pts.append(Vector2(float(q[0]), float(q[1])))
					col.append(pts)
				else:
					col.append(float(v))
			grid.append(col)
		p["bindings"].append({"node": node, "target": target, "grid": grid})
	return p


# ================================================================== parameters
## set a parameter by name (a float for 1D parameters, a Vector2 for 2D ones); returns false if there is none
func set_param(name: String, value: Variant) -> bool:
	var p: Dictionary = param_by_name.get(name, {})
	if p.is_empty():
		return false
	p["value"] = value if value is Vector2 else Vector2(float(value), 0.0)
	return true


func get_param(name: String) -> Vector2:
	var p: Dictionary = param_by_name.get(name, {})
	return p.get("value", Vector2.ZERO)


func param_names() -> PackedStringArray:
	return PackedStringArray(params.map(func(p): return p["name"]))


func _apply_param(p: Dictionary) -> void:
	var range_v: Vector2 = p["max"] - p["min"]
	var off := Vector2(
		clampf((p["value"].x - p["min"].x) / range_v.x if range_v.x != 0.0 else 0.0, 0.0, 1.0),
		clampf((p["value"].y - p["min"].y) / range_v.y if range_v.y != 0.0 else 0.0, 0.0, 1.0))
	var ix := _cell(p["axes"][0], off.x)
	var iy := _cell(p["axes"][1], off.y) if p["is_vec2"] else Vector2(0, 0)
	for b in p["bindings"]:
		var n: Dictionary = nodes.get(b["node"], {})
		if n.is_empty():
			continue
		var g: Array = b["grid"]
		var x0 := int(ix.x)
		var y0 := int(iy.x)
		var x1 := mini(x0 + 1, g.size() - 1)
		var y1 := mini(y0 + 1, (g[0] as Array).size() - 1) if p["is_vec2"] else y0
		if b["target"] == "deform":
			var d: PackedVector2Array = n.get("deform", PackedVector2Array())
			var a0: PackedVector2Array = g[x0][y0]
			if a0.size() != d.size():
				continue
			var a1: PackedVector2Array = g[x1][y0]
			var wx: float = ix.y
			if p["is_vec2"]:
				var b0: PackedVector2Array = g[x0][y1]
				var b1: PackedVector2Array = g[x1][y1]
				var wy: float = iy.y
				for i in d.size():
					d[i] += (a0[i].lerp(b0[i], wy)).lerp(a1[i].lerp(b1[i], wy), wx)
			else:
				for i in d.size():
					d[i] += a0[i].lerp(a1[i], wx)
			n["deform"] = d
		else:
			var v: float
			if p["is_vec2"]:
				v = lerpf(lerpf(g[x0][y0], g[x0][y1], iy.y), lerpf(g[x1][y0], g[x1][y1], iy.y), ix.y)
			else:
				v = lerpf(g[x0][y0], g[x1][y0], ix.y)
			_set_offset(n, b["target"], v)


## (left index, offset 0..1 inside the cell), like Parameter.findOffset
func _cell(pos: PackedFloat32Array, val: float) -> Vector2:
	if pos.size() < 2:
		return Vector2(0, 0)
	for i in pos.size() - 1:
		if pos[i + 1] > val or i == pos.size() - 2:
			return Vector2(i, (val - pos[i]) / (pos[i + 1] - pos[i]) if pos[i + 1] != pos[i] else 0.0)
	return Vector2(0, 0)


func _set_offset(n: Dictionary, key: String, v: float) -> void:
	match key:
		"zSort": n["osort"] += v
		"transform.t.x": n["ot"].x += v
		"transform.t.y": n["ot"].y += v
		"transform.t.z": n["ot"].z += v
		"transform.r.x": n["or"].x += v
		"transform.r.y": n["or"].y += v
		"transform.r.z": n["or"].z += v
		"transform.s.x": n["os"].x *= v
		"transform.s.y": n["os"].y *= v
		"opacity": n["oopacity"] *= v


# ================================================================== frame update
func _process(delta: float) -> void:
	update_puppet(delta)


## one frame, in the same order as Puppet.update(): reset offsets, parameters, transforms, drivers, transforms, draw
func update_puppet(delta: float) -> void:
	if root_uuid < 0:   # no model loaded
		return
	for uuid in nodes:
		var n: Dictionary = nodes[uuid]
		n["ot"] = Vector3.ZERO
		n["or"] = Vector3.ZERO
		n["os"] = Vector2.ONE
		n["osort"] = 0.0
		n["oopacity"] = 1.0
		if n.has("deform"):
			n["deform"].fill(Vector2.ZERO)
	for p in params:
		if not p["driven"]:
			_apply_param(p)
	_update_transforms(root_uuid, Transform3D.IDENTITY)
	for d in drivers:
		_physics(d, delta)
	_update_transforms(root_uuid, Transform3D.IDENTITY)
	_redraw()


func _local(n: Dictionary) -> Transform3D:
	var t: Vector3 = n["t"] + n["ot"]
	var r: Vector3 = n["r"] + n["or"]
	var s: Vector2 = n["s"] * n["os"]
	var basis := Basis.from_euler(r, EULER_ORDER_XYZ).scaled_local(Vector3(s.x, s.y, 1.0))
	return Transform3D(basis, t)


func _update_transforms(uuid: int, parent: Transform3D) -> void:
	var n: Dictionary = nodes[uuid]
	var g := _local(n)
	if uuid == root_uuid and (root_offset != Vector2.ZERO or root_scale != Vector2.ONE):
		g = Transform3D(Basis.from_scale(Vector3(root_scale.x, root_scale.y, 1.0)), Vector3(root_offset.x, root_offset.y, 0.0)) * g
	if n["lock"] and root_uuid in nodes:
		g = _local(nodes[root_uuid]) * g
	elif n["parent"] >= 0:
		g = parent * g
	n["global"] = g
	for c in n["children"]:
		_update_transforms(c, g)


func zsort_of(n: Dictionary) -> float:
	var base := zsort_of(nodes[n["parent"]]) if n["parent"] >= 0 else 0.0
	return base + n["zsort"] + n["osort"]


## the part's vertices in puppet space (deformed, origin removed, through its global transform)
func part_points(n: Dictionary) -> PackedVector2Array:
	var g: Transform3D = n["global"]
	var verts: PackedVector2Array = n["verts"]
	var d: PackedVector2Array = n["deform"]
	var o: Vector2 = n["origin"]
	var out := PackedVector2Array()
	out.resize(verts.size())
	for i in verts.size():
		var v: Vector2 = verts[i] - o + d[i]
		var w := g * Vector3(v.x, v.y, 0.0)
		out[i] = Vector2(w.x, w.y)
	return out


# ================================================================== physics (SimplePhysics driver)
func _new_physics(n: Dictionary) -> Dictionary:
	var a := _anchor(n)
	return {"bob": a + Vector2(0, n["length"]), "dbob": Vector2.ZERO, "angle": 0.0, "dangle": 0.0}


func _anchor(n: Dictionary) -> Vector2:
	var g: Transform3D = n["global"]
	if n["local_only"]:
		var t: Vector3 = n["t"] + n["ot"]
		return Vector2(t.x, t.y)
	return Vector2(g.origin.x, g.origin.y)


func _physics(n: Dictionary, delta: float) -> void:
	var p: Dictionary = {}
	for prm in params:
		if prm["uuid"] == n["param"]:
			p = prm
	if p.is_empty() or not n["enabled"]:
		return
	p["driven"] = true
	var s: Dictionary = n["system"]
	var anchor := _anchor(n)
	var h := minf(delta, MAX_PHYS_DELTA)
	while h > PHYS_STEP:
		_phys_tick(n, s, anchor, PHYS_STEP)
		h -= PHYS_STEP
	_phys_tick(n, s, anchor, h)
	var out: Vector2 = s["bob"]
	var inv: Transform3D = (n["global"] as Transform3D).affine_inverse()
	var local := out
	if not n["local_only"]:
		var w := inv * Vector3(out.x, out.y, 0.0)
		local = Vector2(w.x, w.y)
	var ang: Vector2 = local.normalized()
	var rel: float = out.distance_to(anchor) / float(n["length"])
	var val := Vector2.ZERO
	match n["map"]:
		"XY":
			val = ang * rel - Vector2(0, 1)
			val.y = -val.y
		"YX":
			val = ang * rel - Vector2(0, 1)
			val = Vector2(-val.y, val.x)
		"AngleLength":
			val = Vector2(atan2(-ang.x, ang.y) / PI, rel)
		"LengthAngle":
			val = Vector2(rel, atan2(-ang.x, ang.y) / PI)
	p["value"] = val * n["output_scale"]
	_apply_param(p)


func _phys_tick(n: Dictionary, s: Dictionary, anchor: Vector2, h: float) -> void:
	if h <= 0.0:
		return
	var g: float = n["p_gravity"] * gravity * pixels_per_meter
	var length: float = n["length"]
	if n["model"] == "SpringPendulum":
		var state := [s["bob"], s["dbob"]]
		var f := func(st: Array) -> Array:
			var bob: Vector2 = st[0]
			var dbob: Vector2 = st[1]
			var k_sqrt: float = n["frequency"] * TAU
			var k := k_sqrt * k_sqrt
			var rest := length - g / k
			var off := bob - anchor
			var nrm := off.normalized()
			var ratio := g / length
			var crit_a := 2.0 * sqrt(ratio)
			var crit_l := 2.0 * k_sqrt
			var force := Vector2(0, g) - nrm * (off.length() - rest) * k
			var rot := Vector2(dbob.x * nrm.y + dbob.y * nrm.x, dbob.y * nrm.y - dbob.x * nrm.x)
			var drot := -Vector2(rot.x * n["angle_damping"] * crit_a, rot.y * n["length_damping"] * crit_l)
			force += Vector2(drot.x * nrm.y - rot.y * nrm.x, drot.y * nrm.y + rot.x * nrm.x)
			return [dbob, force]
		var st := _rk4(state, f, h)
		s["bob"] = st[0]
		s["dbob"] = st[1]
	else:
		var d: Vector2 = s["bob"] - anchor
		var state := [atan2(-d.x, d.y), s["dangle"]]
		var f := func(st: Array) -> Array:
			var ratio := g / length
			var dd: float = -ratio * sin(float(st[0])) - float(st[1]) * float(n["angle_damping"]) * 2.0 * sqrt(ratio)
			return [st[1], dd]
		var st := _rk4(state, f, h)
		s["dangle"] = st[1]
		s["bob"] = anchor + Vector2(-sin(float(st[0])), cos(float(st[0]))) * length


func _rk4(y: Array, f: Callable, h: float) -> Array:
	var add := func(a: Array, b: Array, k: float) -> Array: return [a[0] + b[0] * k, a[1] + b[1] * k]
	var k1: Array = f.call(y)
	var k2: Array = f.call(add.call(y, k1, h / 2.0))
	var k3: Array = f.call(add.call(y, k2, h / 2.0))
	var k4: Array = f.call(add.call(y, k3, h))
	return [y[0] + (k1[0] + k2[0] * 2.0 + k3[0] * 2.0 + k4[0]) * (h / 6.0),
		y[1] + (k1[1] + k2[1] * 2.0 + k3[1] * 2.0 + k4[1]) * (h / 6.0)]


# ================================================================== drawing
## one CanvasItem per root drawable (a part, a masked part inside its mask holder, or a composite group)
func _build_views() -> void:
	for c in get_children():
		c.queue_free()
	_views.clear()
	_holders.clear()
	for uuid in _root_drawables(root_uuid):
		add_child(_view_for(uuid))


func _root_drawables(uuid: int) -> Array:
	var out: Array = []
	var n: Dictionary = nodes[uuid]
	if n["type"] == "Composite":
		return [uuid]
	if n["type"] in ["Part", "AnimatedPart"]:
		out.append(uuid)
	for c in n["children"]:
		out.append_array(_root_drawables(c))
	return out


func _parts_below(uuid: int) -> Array:
	var out: Array = []
	for c in nodes[uuid]["children"]:
		if nodes[c]["type"] in ["Part", "AnimatedPart"]:
			out.append(c)
		out.append_array(_parts_below(c))
	return out


func _view_for(uuid: int) -> Node2D:
	var n: Dictionary = nodes[uuid]
	if n["type"] == "Composite":
		# a plain node when the composite only groups (normal blend): Godot can't nest clip groups inside a
		# CanvasGroup; a canvas group only when the composite blends as a whole (multiply hair shadows)
		var grp: Node2D = CanvasGroup.new() if n["blend"] not in ["Normal", ""] else Node2D.new()
		grp.material = _group_material(n["blend"])
		grp.set_meta("composite", true)
		for pu in _parts_below(uuid):
			grp.add_child(_view_for(pu))
		_views[uuid] = grp
		return grp
	var v := PuppetPartView.new()
	v.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC   # squashed mesh parts (a closing mouth) stay sharp
	v.puppet = self
	v.uuid = uuid
	v.material = _blend_material(n["blend"])
	_views[uuid] = v
	var mask_srcs: Array = n["masks"].filter(func(m): return m["mode"] == "Mask" and nodes.has(m["source"]))
	if n["blend"] == "ClipToLower" and mask_srcs.is_empty():   # shows only over what is drawn just below it
		var lower := _lower_of(uuid)
		if lower >= 0:
			mask_srcs = [{"source": lower}]
	# a multiply part (a shadow) draws on its own: Godot composites a clip group over its whole mesh area, and in
	# multiply mode the transparent part of that area turns black. Shadows are painted inside what they shade.
	if mask_srcs.is_empty() or n["blend"] == "Multiply":
		return v
	var holder := PuppetPartView.new()   # draws the masks; its child only shows inside them
	holder.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	holder.puppet = self
	holder.uuid = uuid
	holder.mask_of = mask_srcs.map(func(m): return m["source"])
	holder.clip_children = CanvasItem.CLIP_CHILDREN_ONLY
	# Godot composites a clip group with the holder's material, so the part's blend mode goes on the holder
	# (a multiply shadow inside the group would otherwise multiply against nothing) and the part itself draws
	# normally inside the group. The mask edge is soft: the alpha threshold is not applied.
	holder.material = _group_material(n["blend"])
	if holder.material != null:
		v.material = _blend_material("Normal")
	holder.add_child(v)
	_holders[uuid] = holder
	return holder


## Parts sample their texture as transparent outside 0..1 (Inochi2D clamps to a transparent border; Godot would
## smear the edge pixels) and un-premultiply it (Inochi2D textures hold premultiplied colour: drawn as they are,
## soft edges turn into dark outlines). Multiply and add parts blend in the same shader.
static var _materials := {}


## ClipToLower (Inochi2D draws it only where something is already drawn): the nearest part drawn before this one
## (at rest) under the same parent node, or anywhere, that is not ClipToLower itself
func _lower_of(uuid: int) -> int:
	# inside a composite, "below" means the composite's own parts (it draws on its own transparent canvas: an iris
	# clips to the eye white next to it)
	var roots := _root_drawables(root_uuid)
	var up: int = nodes[uuid]["parent"]
	while up >= 0:
		if nodes[up]["type"] == "Composite":
			roots = _parts_below(up)
			break
		up = nodes[up]["parent"]
	var keyed: Array = []
	for i in roots.size():
		keyed.append([zsort_of(nodes[roots[i]]), i, roots[i]])
	keyed.sort_custom(func(a, b): return a[0] > b[0] or (a[0] == b[0] and a[1] < b[1]))
	var order: Array = keyed.map(func(k): return k[2])
	var at := order.find(uuid)
	if at < 0:
		return -1
	var parent: int = nodes[uuid]["parent"]
	for pass_same_parent in [true, false]:
		for i in range(at - 1, -1, -1):
			var o: Dictionary = nodes[order[i]]
			if o["type"] in ["Part", "AnimatedPart"] and o["blend"] != "ClipToLower" and (not pass_same_parent or o["parent"] == parent):
				return order[i]
	return -1


func _blend_material(mode: String) -> Material:
	var kind := "mix"
	match mode:
		"Multiply": kind = "mul"
		"LinearDodge", "Additive", "AddGlow", "ColorDodge", "Screen": kind = "add"
		"Subtract": kind = "sub"
	if not _materials.has(kind):
		var sh := Shader.new()
		var body := "	COLOR = t * tint;
"
		if kind == "mul":   # Godot multiplies dst by the colour alone: fade the colour to white where it is transparent
			body = "	t *= tint;
	COLOR = vec4(mix(vec3(1.0), t.rgb, t.a), 1.0);
"
		# textures hold premultiplied colour (Inochi2D keeps them that way): back to straight colour first
		# in a canvas fragment shader COLOR already holds texture * modulate: keep the vertex colour (modulate) in a
		# varying and sample the texture once
		sh.code = ("shader_type canvas_item;
render_mode blend_%s;
varying vec4 tint;
void vertex() {
	tint = COLOR;
}
"
			+ "void fragment() {
	vec4 t = texture(TEXTURE, UV);
"
			+ "	if (UV.x < 0.0 || UV.x > 1.0 || UV.y < 0.0 || UV.y > 1.0) t = vec4(0.0);
"
			+ "	t.rgb /= max(t.a, 0.0001);
%s}
") % [kind, body]
		var m := ShaderMaterial.new()
		m.shader = sh
		_materials[kind] = m
	return _materials[kind]


## the material a mask holder composites its group with (Godot uses the holder's material for that): only the
## part's blend mode, never its texture shader
func _group_material(mode: String) -> Material:
	var m := CanvasItemMaterial.new()
	match mode:
		"Multiply": m.blend_mode = CanvasItemMaterial.BLEND_MODE_MUL
		"LinearDodge", "Additive", "AddGlow", "ColorDodge", "Screen": m.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
		"Subtract": m.blend_mode = CanvasItemMaterial.BLEND_MODE_SUB
		_: return null
	return m


func _redraw() -> void:
	# draw order: higher zSort further back (drawn first), stable
	var roots := _root_drawables(root_uuid)
	var keyed: Array = []
	for i in roots.size():
		keyed.append([zsort_of(nodes[roots[i]]), i, roots[i]])
	keyed.sort_custom(func(a, b): return a[0] > b[0] or (a[0] == b[0] and a[1] < b[1]))
	var order: Array = keyed.map(func(k): return k[2])
	if order != _order:
		_order = order
		for i in order.size():
			var item: Node = _holders.get(order[i], _views[order[i]])
			move_child(item, i)
	for uuid in _views:
		var n: Dictionary = nodes[uuid]
		var item: CanvasItem = _views[uuid]
		item.visible = n["enabled"]
		var tint: Vector3 = n.get("tint", Vector3.ONE)
		item.self_modulate = Color(tint.x, tint.y, tint.z, clampf(float(n.get("opacity", 1.0)) * n["oopacity"], 0.0, 1.0))
		if item is PuppetPartView:
			item.queue_redraw()
		elif item.has_meta("composite"):   # composite: sort its own parts too
			var kids: Array = item.get_children()
			kids.sort_custom(func(a, b): return zsort_of(nodes[a.uuid]) > zsort_of(nodes[b.uuid]))
			for i in kids.size():
				item.move_child(kids[i], i)
	for uuid in _holders:
		_holders[uuid].queue_redraw()
