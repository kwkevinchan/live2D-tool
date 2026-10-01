# 檔案格式與圖層名字

所有工具做出來的東西都在工作資料夾（設定檔 `[paths] work`），不進版本庫。

---

## 1. 資料夾結構

```
<work>/
├─ live/
│  ├─ <角色>/<服裝>/              一張立繪的工作資料夾（主設計的服裝是 "-"，關鍵姿勢是 pose_<姿勢>）
│  │  ├─ full.png、full_blink.png、pose.json      關鍵姿勢資料夾自己的立繪
│  │  ├─ fig_joints.json、fig_*.png、fig_overview.png、layer_*.png     找骨架、粗分層
│  │  ├─ eyes_closed.png、eyes.json               閉眼差分
│  │  ├─ mouth_*.png、mouth.json                  嘴型差分
│  │  ├─ <角色>_<服裝>_st.inx、<角色>_<服裝>.inx   綁定結果（細部、粗）
│  │  ├─ _shots/、_motions/、_motions_all/        動態截圖、標準動作
│  │  └─ st/                                      細部分層
│  │     ├─ st_<名稱>.png、st_<名稱>_depth.png、st_layers.json      拆層模型的原始輸出
│  │     ├─ part_<名稱>.png、parts.json           目前的圖層和順序（每一步直接改這裡）
│  │     ├─ _stack_vs_plate.jpg、lineart.png
│  │     ├─ _orig/                                第一次修改前的原檔
│  │     ├─ groups/                               分六包（見 03_Packs.md）
│  │     │  └─ objects/                           武器與物件驗證
│  │     ├─ outline/                              輪廓（含 marks.json）
│  │     ├─ fix/                                  修補的候選
│  │     └─ gen/                                  AI 重畫的候選
│  └─ check/                       rig_check、rig_stress 的結果
├─ poses/<角色>/<動作>/            關鍵姿勢的候選
├─ review_decisions.json           使用者的審核（跟美術工作室共用）
└─ comfyui.log
```

`<名稱>` 在檢查結果裡是 `<角色>_<服裝>`，主設計寫成 `<角色>_default`。

## 2. `fig_joints.json`

`live_layers.py parts` 寫，`see_through.fix_grip`、`refine_leftover` 會更新。座標是立繪像素，偵測不到是 `null`。

```json
{
  "neck": [x, y],
  "shoulder_l": [x, y], "shoulder_r": [x, y],
  "elbow_l": [x, y],    "elbow_r": [x, y],
  "wrist_l": [x, y],    "wrist_r": [x, y],
  "hip_l": [x, y],      "hip_r": [x, y],
  "knee_l": [x, y],     "knee_r": [x, y],
  "ankle_l": [x, y],    "ankle_r": [x, y],
  "face": [中心x, 中心y, 臉高],
  "weapon_grip": {"hand": "arm_l" | "arm_r", "point": [x, y], "from": "..."},
  "parts": ["leg_l", "torso", ...]
}
```

`weapon_grip.from` 有值表示是程式自己算的（不是姿勢偵測的），重新拆層時會重算。姿勢偵測抓錯時手動改這個檔。讀的時候都經過 `inx_rig.load_joints`，補上缺的脖子、肩、髖。

## 3. `st/parts.json`

```json
{
  "size": [寬, 高],
  "order_back_to_front": [
    {"name": "objects-back", "file": "part_objects-back.png", "depth": 1.0, "from": "painted in: ..."},
    {"name": "back_hair", "file": "part_back_hair.png", "depth": 0.83},
    ...
  ],
  "pivots": {
    "shoulder_l": [x, y], "elbow_l": [x, y], "wrist_l": [x, y],
    "shoulder_r": [x, y], "elbow_r": [x, y], "wrist_r": [x, y],
    "hip_l": [x, y], "knee_l": [x, y], "ankle_l": [x, y], "foot_l": [x, y],
    "hip_r": [x, y], "knee_r": [x, y], "ankle_r": [x, y], "foot_r": [x, y],
    "waist": [x, y],
    "grip": {"hand": "l" | "r", "point": [x, y], "tip": [x, y]}
  },
  "ranges": {"shoulder_r": [-0.6, 1.2], "weapon": [-1.0, 2.0], ...}
}
```

- `order_back_to_front`：從最後面到最前面。`depth` 是拆層模型的深度中位數（自己加的層是 0 或 1）；`from` 說明這層是怎麼來的。
- `pivots`：`rig_parts.py` 寫。注意 `grip.hand` 在這裡是 `l`／`r`，在 `fig_joints.json` 是 `arm_l`／`arm_r`。
- `ranges`：`rig_stress.py --find-ranges` 寫，每個關節兩個方向不會出破洞的角度（弧度，畫面上順時針為正）。

## 4. 其他 JSON

| 檔案 | 誰寫 | 內容 |
|---|---|---|
| `st/st_layers.json` | `see_through.py` | 拆層模型的原始資訊：每層 `filename`、`name`、`left`、`top`、`depth_median`；`input`（`crop` 裁切範圍、`resolution`） |
| `mouth.json` | `live_layers.py mouths` | `face`（中心、臉高）、`mouth_box`（x0, y0, x1, y1） |
| `eyes.json` | `live_layers.py parts` | `eye_box` |
| `review.json` | `review_plate.py` | `counts`、`warnings` |
| `pose.json` | `key_poses.py pick` | `hero`、`action`、`pose`、`seed`：這張是用哪個骨架畫的 |
| `st/groups/groups.json` | `split_groups.py` | 見 [03_Packs.md](03_Packs.md) |
| `st/groups/objects/objects.json` | `object_check.py` | `passed`，每件的 `pieces`、`floating`、`holes`、`pivot`、`warnings` |
| `st/outline/<圖層>.json`、`_check.json`、`marks.json` | `outline.py` | 見 [04_Repair.md](04_Repair.md) |
| `_motions/report.json` | `motion_test` | `{動作: {name, missing: [缺的參數]}}` |
| `check/rig_check.json` | `rig_check.py` | `{名稱: {figure_px, bad_share, missing, colour, extra, areas, flagged, model}}` |

## 5. 圖層名字

綁定、分包、擺動都靠名字判斷。最後一欄是這一層從哪裡來：See-through 原本就有的，或我們的工具加的。

| 名字 | 是什麼 | 誰加的 |
|---|---|---|
| `front_hair`、`back_hair` | 前髮、後髮 | See-through |
| `face`、`nose`、`mouth`、`neck` | 臉、鼻、嘴、脖子 | See-through（臉漏掉時 `object_fix --make-face`） |
| `eyewhite-l/r`、`irides-l/r`（或 `irides`）、`eyelash-l/r`、`eyebrow-l/r` | 眼白、虹膜、睫毛、眉毛 | See-through（共用一層時 `--split-lr`） |
| `ears`、`ears-l/r` | 耳朵 | See-through |
| `headwear` | 帽子 | See-through 或 `refine_leftover` |
| `headwear-front` | 帽子在臉和瀏海前面的部分 | `object_fix --split-front`、`object_place --front` |
| `topwear`、`bottomwear` | 上衣、下著（裙子） | See-through |
| `handwear-l/r` | 整條手臂（拆層叫它手套） | See-through；切零件後刪掉 |
| `upperarm-l/r`、`forearm-l/r`、`hand-l/r` | 上臂、前臂、手 | `rig_parts.py` |
| `legwear`、`footwear` | 兩條腿、鞋子 | See-through；切零件後刪掉 |
| `thigh-l/r`、`shin-l/r`、`foot-l/r` | 大腿、小腿、腳掌 | `rig_parts.py` |
| `objects` | 武器看得到的部分 | See-through、`refine_leftover` 或 `rig_parts --weapon` |
| `objects-back` | 武器被擋住、補畫的部分 | `rig_parts.py` |
| `hidden` | 會動的零件底下補畫的身體 | `rig_parts.py` |
| `hidden-pelvis` | 上衣下緣後面補畫的裙子 | `rig_parts.py` |
| `leftover` | 立繪有、各層都沒有的（雜物） | `to_plate` |
| `side_hair` | 從雜物層、衣服層分出來的長髮 | `object_fix --sort-hair`、`--move-hair` |
| `side_lock-l/r`、`hair_ends` | 側髮、髮尾 | `object_fix --split-hair` |
| `chest`、`cape`、`sleeve-l/r`、`ponytail`、`ahoge`、`ribbon`、`earring`、`tassel`、`quiver` | 胸、披風、寬袖、馬尾、呆毛、髮帶、耳環、流蘇、箭筒 | `object_fix --carve`（名字決定綁定時怎麼擺） |

## 6. `.inx` 模型檔

```
"TRNSRTS\0" + JSON 長度（4 位元組，大端序）+ JSON
"TEX_SECT" + 貼圖數量（4 位元組）+ 每張：長度（4 位元組）、編碼（1 位元組，0 = PNG）、資料
```

JSON 裡有 `meta`、`physics`（`pixelsPerMeter`、`gravity`）、`nodes`（節點樹，從 `Root` 開始）、`param`（參數）。寫入是 `inx_rig.write_inx`，讀取是 `InochiPuppet.load_model`，`rig_stress.model_params` 只讀參數名字。

節點的共同欄位：`uuid`、`name`、`type`（`Node`、`Part`、`Composite`、`SimplePhysics`）、`enabled`、`zsort`、`transform`（`trans`、`rot`、`scale`）、`lockToRoot`、`children`。參數的綁定：`node`、`param_name`（`transform.t.x`、`transform.r.z`、`opacity`、`deform`……）、`values`（每個軸點一個值）。
