"""ComfyUI workflow files for the art tools (Tools/art/workflows/*.json, ComfyUI "API" format).

Every tool loads its graph from here and fills in only what changes (prompt, picture, seed, size) by node title,
so a graph can be opened in ComfyUI (drag the file onto the page), tuned there, and saved back: the tools follow.
Node titles are fixed names in Chinese, e.g. 正面提示詞 / 排除詞 / 採樣 / 存圖.

    python Tools/art/workflows.py        (re)write the default files (keeps files you changed unless --force)
"""
import copy
import json
import os
import sys

DIR = os.path.join(os.path.dirname(__file__), "workflows")


def _n(cls, title, **inputs):
    return {"class_type": cls, "inputs": inputs, "_meta": {"title": title}}


def defaults():
    ck = "autismmixSDXL_autismmixPony.safetensors"
    t2i = {
        "1": _n("CheckpointLoaderSimple", "模型", ckpt_name=ck),
        "2": _n("CLIPSetLastLayer", "CLIP 跳層", clip=["1", 1], stop_at_clip_layer=-2),
        "3": _n("CLIPTextEncode", "正面提示詞", clip=["2", 0], text=""),
        "4": _n("CLIPTextEncode", "排除詞", clip=["2", 0], text=""),
        "5": _n("EmptyLatentImage", "畫布", width=832, height=1216, batch_size=1),
        "6": _n("KSampler", "採樣", model=["1", 0], positive=["3", 0], negative=["4", 0], latent_image=["5", 0],
                seed=1, steps=30, cfg=6.0, sampler_name="dpmpp_2m", scheduler="karras", denoise=1.0),
        "7": _n("VAEDecode", "解碼", samples=["6", 0], vae=["1", 2]),
        "8": _n("SaveImage", "存圖", images=["7", 0], filename_prefix="art"),
    }
    i2i = copy.deepcopy(t2i)
    i2i["9"] = _n("LoadImage", "輸入圖", image="")
    i2i["5"] = _n("VAEEncode", "編碼", pixels=["9", 0], vae=["1", 2])
    i2i["6"]["inputs"]["denoise"] = 0.5
    inpaint = copy.deepcopy(i2i)
    inpaint["10"] = _n("LoadImageMask", "遮罩", image="", channel="red")
    inpaint["11"] = _n("SetLatentNoiseMask", "只重畫遮罩", samples=["5", 0], mask=["10", 0])
    inpaint["6"]["inputs"]["latent_image"] = ["11", 0]
    # inpaint held to line art (Live 2D objects: colour inside a completed outline, 22b); the union ControlNet in its
    # line-art mode takes white lines on black
    lines = copy.deepcopy(inpaint)
    lines["12"] = _n("ControlNetLoader", "線稿模型", control_net_name="xinsir_union_promax_sdxl.safetensors")
    lines["13"] = _n("SetUnionControlNetType", "線稿類型", control_net=["12", 0], type="canny/lineart/anime_lineart/mlsd")
    lines["14"] = _n("LoadImage", "線稿圖", image="")
    lines["15"] = _n("ControlNetApplyAdvanced", "套用線稿", positive=["3", 0], negative=["4", 0], control_net=["13", 0],
                     image=["14", 0], strength=0.8, start_percent=0.0, end_percent=0.8, vae=["1", 2])
    lines["6"]["inputs"]["positive"] = ["15", 0]
    lines["6"]["inputs"]["negative"] = ["15", 1]
    sam2 = {
        "1": _n("LoadImage", "輸入圖", image=""),
        "2": _n("DownloadAndLoadSAM2Model", "SAM2 模型", model="sam2.1_hiera_large.safetensors", segmentor="single_image",
                device="cuda", precision="fp16"),
        "3": _n("Sam2Segmentation", "分割", sam2_model=["2", 0], image=["1", 0], keep_model_loaded=False,
                coordinates_positive="[]", coordinates_negative="[]"),
        "4": _n("MaskToImage", "遮罩轉圖", mask=["3", 0]),
        "8": _n("SaveImage", "存圖", images=["4", 0], filename_prefix="art_mask"),
    }
    depth = {
        "1": _n("LoadImage", "輸入圖", image=""),
        "2": _n("DepthAnythingV2Preprocessor", "深度", image=["1", 0], ckpt_name="depth_anything_v2_vitl.pth", resolution=1024),
        "8": _n("SaveImage", "存圖", images=["2", 0], filename_prefix="art_depth"),
    }
    wan = {
        "1": _n("UNETLoader", "影片模型", unet_name="wan2.2_ti2v_5B_fp16.safetensors", weight_dtype="default"),
        "2": _n("ModelSamplingSD3", "取樣偏移", model=["1", 0], shift=8.0),
        "3": _n("CLIPLoader", "文字編碼", clip_name="umt5_xxl_fp8_e4m3fn_scaled.safetensors", type="wan"),
        "4": _n("VAELoader", "解碼器", vae_name="wan2.2_vae.safetensors"),
        "5": _n("LoadImage", "輸入圖", image=""),
        "6": _n("Wan22ImageToVideoLatent", "影片畫布", vae=["4", 0], width=832, height=480, length=73, batch_size=1,
                start_image=["5", 0]),
        "7": _n("CLIPTextEncode", "正面提示詞", clip=["3", 0], text=""),
        "8": _n("CLIPTextEncode", "排除詞", clip=["3", 0], text=""),
        "9": _n("KSampler", "採樣", model=["2", 0], positive=["7", 0], negative=["8", 0], latent_image=["6", 0],
                seed=1, steps=20, cfg=5.0, sampler_name="uni_pc", scheduler="simple", denoise=1.0),
        "10": _n("VAEDecode", "解碼", samples=["9", 0], vae=["4", 0]),
        "11": _n("VHS_VideoCombine", "存影片", images=["10", 0], frame_rate=24, loop_count=0, filename_prefix="anim",
                 format="video/h264-mp4", pingpong=False, save_output=True),
    }
    pose = {
        "1": _n("LoadImage", "輸入圖", image=""),
        "2": _n("DWPreprocessor", "骨架", image=["1", 0], detect_hand="disable", detect_body="enable", detect_face="disable",
                resolution=1024, bbox_detector="yolox_l.onnx", pose_estimator="dw-ll_ucoco_384_bs5.torchscript.pt",
                scale_stick_for_xinsr_cn="disable"),
        "3": _n("SavePoseKpsAsJsonFile", "存關節", pose_kps=["2", 1], filename_prefix="art_pose"),
    }
    see = {
        "1": _n("LoadImage", "輸入圖", image=""),
        "2": _n("SeeThrough_LoadLayerDiffModel", "分層模型", model="seethroughv0.0.2_layerdiff3d", vae_ckpt="", unet_ckpt="",
                quant_mode="none", cache_tag_embeds=True, group_offload=False, auto_download=False),
        "3": _n("SeeThrough_LoadDepthModel", "深度模型", model="seethroughv0.0.1_marigold", quant_mode="none",
                cache_tag_embeds=True, group_offload=False, auto_download=False),
        "4": _n("SeeThrough_GenerateLayers", "分層", image=["1", 0], layerdiff_model=["2", 0], seed=42, resolution=1280,
                num_inference_steps=30),
        "5": _n("SeeThrough_GenerateDepth", "深度", layers=["4", 0], depth_model=["3", 0], seed=42, resolution_depth=-1),
        "6": _n("SeeThrough_PostProcess", "整理", layers_depth=["5", 0], tblr_split=True, use_lama=True),
        "7": _n("SeeThrough_SavePSD", "存 PSD", parts=["6", 0], filename_prefix="seethrough"),
    }
    # a plate's line art (Live 2D outlines, 22b step 2): white lines on black
    lineart = {
        "1": _n("LoadImage", "輸入圖", image=""),
        "2": _n("LineArtPreprocessor", "抽線", image=["1", 0], coarse="disable", resolution=1024),
        "3": _n("SaveImage", "存圖", images=["2", 0], filename_prefix="lineart"),
    }
    return {"txt2img": t2i, "img2img": i2i, "inpaint": inpaint, "inpaint_lines": lines, "lineart": lineart, "sam2": sam2, "depth": depth, "wan_i2v": wan, "pose": pose,
            "see_through": see}


def load(name):
    path = os.path.join(DIR, name + ".json")
    if not os.path.exists(path):
        write_defaults()
    return json.load(open(path, encoding="utf-8"))


def fill(wf, values):
    """values: {node title: {input: value}}"""
    by_title = {n.get("_meta", {}).get("title"): n for n in wf.values()}
    for title, inputs in values.items():
        if title not in by_title:
            raise KeyError("workflow has no node titled %s" % title)
        by_title[title]["inputs"].update(inputs)
    return wf


def node_id(wf, title):
    return next(k for k, n in wf.items() if n.get("_meta", {}).get("title") == title)


def write_defaults(force=False):
    os.makedirs(DIR, exist_ok=True)
    for name, wf in defaults().items():
        path = os.path.join(DIR, name + ".json")
        if force or not os.path.exists(path):
            json.dump(wf, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("wrote", path)


if __name__ == "__main__":
    write_defaults("--force" in sys.argv)
