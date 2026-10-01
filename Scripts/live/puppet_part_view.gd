class_name PuppetPartView
extends Node2D
## Draws one Inochi2D part of an InochiPuppet (its deformed mesh, textured), or — as a mask holder — the meshes of
## the parts that mask it (the holder clips its child to them).

var puppet: InochiPuppet
var uuid := -1
var mask_of: Array = []      ## mask holder: uuids of the masking parts; empty = draw this part


func _draw() -> void:
	if puppet == null:
		return
	if mask_of.is_empty():
		_draw_part(puppet.nodes[uuid])
	else:
		for m in mask_of:
			_draw_part(puppet.nodes[m])


func _draw_part(n: Dictionary) -> void:
	var idx: PackedInt32Array = n["indices"]
	var tid: int = n["texture"]
	if idx.is_empty() or tid < 0 or tid >= puppet.textures.size() or puppet.textures[tid] == null:
		return
	var tex: Texture2D = puppet.textures[tid]
	RenderingServer.canvas_item_add_triangle_array(get_canvas_item(), idx, puppet.part_points(n),
		PackedColorArray([Color.WHITE]), n["uvs"], PackedInt32Array(), PackedFloat32Array(), tex.get_rid())
