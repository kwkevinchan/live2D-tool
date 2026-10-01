# Godot 播放器

| 檔案 | 用途 |
|---|---|
| `Scripts/live/inochi_puppet.gd`（`InochiPuppet`） | 播放器本體：讀 `.inx`、套參數、物理、決定前後順序、畫出來。純 GDScript，手機也能跑 |
| `Scripts/live/puppet_part_view.gd`（`PuppetPartView`） | 畫一個部件的網格；或當遮罩容器，畫出遮罩 |
| `Scripts/live/live_portrait.gd`（`LivePortrait`） | 包住一個或多個模型（每個姿勢一個），自己呼吸、眨眼、東張西望、說話、換姿勢 |

規則照 Inochi2D 0.8.7 的原始碼。用詞：

- **模型**：一個 `.inx` 檔，裡面有節點樹、參數、貼圖。
- **節點**：樹上的一點，有自己的位置、旋轉、縮放；子節點跟著父節點動。
- **部件**：有貼圖和網格、真的會畫出來的節點。
- **組合**：把底下的部件當成一組來畫的節點。
- **參數**：一個名字加一個數值（例如 `Eye:: Blink` 從 0 到 1），數值改變時，綁在它上面的節點跟著移動、旋轉、變形或變透明。
- **前後順序**：每個節點有 `zsort`，數字越大越後面（越先畫）；實際值是自己加上所有父節點的。

---

## 1. 函式呼叫流程

### 1-1. 載入

```
InochiPuppet.load_model(path)
├─ 依序讀區段：TRNSRTS（JSON）、TEX_SECT（貼圖）、EXT_SECT（略過）
├─ _decode_texture(blob)          每張貼圖：PNG / TGA → 產生縮圖層級 → ImageTexture
└─ load_payload(payload)          （測試直接呼叫這個，在程式裡組模型）
   ├─ 讀物理設定（重力、每公尺幾像素）
   ├─ _make_node(nodes, -1)        遞迴建立整棵樹
   │  ├─ _v2 / _v3 / _flat_v2      JSON 陣列 → 向量
   │  └─ _make_node(child, uuid)   每個子節點
   ├─ _make_param(p)               每個參數 → 建立名字對照 param_by_name
   ├─ _new_physics(n)              每個 SimplePhysics 節點的初始狀態
   │  └─ _anchor(n)
   ├─ _build_views()               建立畫面用的節點
   │  ├─ _root_drawables(root)     最上層可畫物（組合整個算一個）
   │  └─ _view_for(uuid)           每個可畫物
   │     ├─ 組合：Node2D 或 CanvasGroup，底下每個部件再 _view_for（_parts_below）
   │     ├─ 部件：PuppetPartView，材質 _blend_material(blend)
   │     ├─ ClipToLower 沒有遮罩時：_lower_of(uuid) 找正下方的部件當遮罩
   │     └─ 有遮罩：再包一層遮罩容器（PuppetPartView, mask_of），材質 _group_material(blend)
   └─ update_puppet(0.0)           先算一格
```

### 1-2. 每一格

```
_process(delta)                    （由 LivePortrait 管的模型關掉這個，改由 LivePortrait 呼叫）
└─ update_puppet(delta)
   ├─ 歸零：每個節點的偏移量、網格變形
   ├─ _apply_param(p)              每個不是物理驅動的參數
   │  ├─ _cell(axis, v)            落在哪兩個軸點之間、偏多少
   │  ├─ 網格變形：直接加到頂點
   │  └─ _set_offset(n, key, v)    位移、旋轉用加的；縮放、透明度用乘的
   ├─ _update_transforms(root, I)  從根往下：全域 = 父的全域 × 自己的 _local(n)
   ├─ _physics(n, delta)           每個物理節點
   │  ├─ _anchor(n)
   │  ├─ _phys_tick(...) × N       每 0.01 秒一步，最多算 0.25 秒
   │  │  └─ _rk4(state, f, h)      四階龍格－庫塔法
   │  └─ 擺錘位置 → 參數值 → _apply_param(p)
   ├─ _update_transforms(root, I)  物理改了參數，再算一次
   └─ _redraw()
      ├─ zsort_of(n)               排出前後順序，有變才 move_child
      ├─ 每個畫面節點：顯示與否、色調、透明度、queue_redraw
      └─ PuppetPartView._draw()
         └─ _draw_part(n)          part_points(n) ＋貼圖座標 → 畫三角形
```

### 1-3. 會動的立繪

```
LivePortrait.add_pose(pose, path)
├─ InochiPuppet.new() → load_model(path)
└─ add_pose_puppet(pose, p, _read_frame(path))
   ├─ add_child(p) → p.set_process(false)    （先加進樹再關，否則 Godot 會再打開）
   └─ _align(pose)

LivePortrait._process(delta)
├─ 計時姿勢到了 → play_pose(idle_pose) → 發出 pose_finished
├─ 眨眼、視線、說話的數值
└─ 每個顯示中的模型：_drive(p, key, v) × 4 → p.update_puppet(delta)

LivePortrait.play_pose(pose, duration)  → Tween 淡入淡出
LivePortrait.talk(seconds)
```

---

## 2. 載入模型（`InochiPuppet`）

```gdscript
var p := InochiPuppet.new()
p.load_model("res://…/freya_pose_apose_st.inx")
add_child(p)
```

1. **`load_model(path) -> bool`**：打開 `.inx`，依序讀區段：`TRNSRTS`（4 位元組長度＋JSON）、`TEX_SECT`（貼圖數量，每張是長度、編碼、資料）、`EXT_SECT`（略過）。
2. **`_decode_texture(blob)`**：編碼 0 是 PNG、1 是 TGA。**產生縮圖層級**：立繪畫得比貼圖小，沒有這步細線會斷成點點。
3. **`load_payload(payload)`**：見上面的流程。
4. **`_make_node(src, parent)`**：節點存成字典（以 `uuid` 為鍵），共同欄位有位置 `t`、旋轉 `r`、縮放 `s`、`zsort`、`lockToRoot`，以及每格由參數加上去的偏移 `ot`、`or`、`os`、`osort`、`oopacity`。依類型再多讀：
   - 部件：頂點、貼圖座標、三角形、原點、貼圖編號、透明度、色調、混合方式、遮罩；
   - 組合：透明度、色調、混合方式；
   - 物理：驅動哪個參數、單擺或彈簧擺、輸出方式、重力倍數、長度、頻率、角度和長度的阻尼、輸出倍率、只看本地座標。
5. **`_make_param(src)`**：範圍、預設值、軸點（一維或二維），每個綁定轉成表格 `grid[x][y]`（數字，或變形時的頂點位移陣列）。
6. **`_view_for(uuid)`** 的幾個特別處理：
   - **組合**：一般混合用普通 `Node2D` 當群組（Godot 不能在 `CanvasGroup` 裡再套裁切）；只有整組要相乘、相加時才用 `CanvasGroup`。
   - **有遮罩的部件**：包一層遮罩容器（`clip_children = CLIP_CHILDREN_ONLY`），容器畫遮罩部件，子節點只在遮罩範圍內顯示。混合方式放在容器上，部件本身改用一般材質。遮罩邊緣是軟的（不套門檻值）。
   - **相乘的部件（陰影）不包容器**：Godot 會把容器整塊合成，透明處在相乘時會變黑。
7. **`_lower_of(uuid)`**：「只畫在下面那層上」（`ClipToLower`，例如虹膜只畫在眼白上）的對象：照前後順序往回找最近一個不是 `ClipToLower` 的部件，先找同一個父節點底下的。在組合裡只看組合自己的部件。
8. **`_blend_material(mode)`**：部件的著色器，分一般、相乘、相加、相減四種，共用快取。著色器做三件事：
   - 貼圖範圍外當透明（不然邊緣像素會被拉長成條紋）；
   - 把貼圖從「預乘透明」轉回一般顏色（不轉的話半透明邊緣會變黑框）；
   - 乘上頂點顏色（透明度、色調）；相乘模式在透明處改成白色。
9. **`_group_material(mode)`**：群組或容器合成時的混合方式（只有相乘、相加、相減才需要）。

## 3. 每一格的細節

- **`_apply_param(p)`**：值先換成 0～1 的比例（超出範圍截斷），**`_cell`** 找出所在的格子和偏移，一維線性內插、二維雙線性內插。
- **`_local(n)`**：（原本的位置＋偏移）、（旋轉＋偏移）、（縮放 × 偏移）。
- **`_update_transforms`**：根節點另外套上 `root_offset`、`root_scale`（跳躍、跑步用：從模型內部移動，物理才感覺得到）。`lockToRoot` 的節點只跟根走。
- **`_physics(n, delta)`**：
  - 找出它驅動的參數，標成「由物理驅動」（之後一般的套參數會跳過它）；
  - 以 0.01 秒為一步推進；一格最多算 0.25 秒（`MAX_PHYS_DELTA`：遊戲從背景回來時那一格可能有好幾秒）；
  - 彈簧擺：重力、彈力、角度和長度兩種阻尼；單擺：只算角度；
  - 擺錘位置換到節點本地座標，依輸出方式（`AngleLength`、`LengthAngle`、`XY`、`YX`）換成參數值，乘上輸出倍率。
- **`_redraw()`**：前後順序有變才搬動畫面節點；組合裡的部件也各自排序；遮罩容器也要重畫。

## 4. 從外部控制

| 函式／變數 | 用途 |
|---|---|
| `set_param(name, value) -> bool` | 設定參數（一維給數字，二維給 `Vector2`）；找不到回傳 `false` |
| `get_param(name) -> Vector2` | 讀參數目前的值 |
| `param_names()` | 所有參數的名字 |
| `update_puppet(delta)` | 自己驅動時呼叫（先 `set_process(false)`） |
| `root_offset`、`root_scale` | 從模型內部移動、壓扁整個人 |
| `part_points(n)`、`zsort_of(n)` | 部件目前的頂點位置、前後順序（預覽和特效定位用） |
| `nodes`、`params`、`param_by_name`、`textures` | 模型資料，唯讀使用 |

## 5. 會動的立繪（`LivePortrait`）

```gdscript
var lp := LivePortrait.new()
lp.add_pose(&"idle", ".../pose_idle/alicia_pose_idle_st.inx")
lp.add_pose(&"draw", ".../pose_draw/alicia_pose_draw_st.inx")
add_child(lp)
lp.talk(2.0)                    # 說話 2 秒
lp.play_pose(&"draw", 0.6)      # 換成拉弓，0.6 秒後自動回到待機
lp.pose_finished.connect(...)   # 回到待機時通知
```

- **`add_pose(pose, path)`**：載入模型，交給 `add_pose_puppet`。第一個加入的顯示，其他隱藏。
- **`add_pose_puppet(pose, p, frame)`**：加進樹之後才關掉模型自己的更新（Godot 在節點進樹時會打開有 `_process` 的節點，之前曾因此物理一格跑兩次）。所有姿勢由這裡統一驅動，拿到一樣的呼吸、眨眼數值。
- **`_read_frame(path)`**：讀模型旁邊的 `fig_joints.json` 和 `full.png`，算出軀幹長度（脖子到兩髖中點）、脖子位置、腳底高度（最下面一排有顏色的像素），都以立繪中心為原點。缺脖子或髖部就回傳空的（那個姿勢不對齊）。
- **`_align(pose)`**：跟第一個姿勢對齊：縮放到軀幹一樣長，左右對齊脖子、上下對齊腳底（蹲下時腳還踩在地上）。不用臉的大小，因為側臉量起來會小很多。
- **`_process(delta)`**：
  1. 計時的姿勢到時間就回待機，發出 `pose_finished`；
  2. 每 2.5～5.5 秒眨一次眼（0.18 秒）；
  3. 每 2～5 秒換一個看的方向（六成機率），平滑轉過去；
  4. 說話時嘴巴開合；
  5. 每個顯示中的姿勢：`_drive` 設定呼吸、轉頭、眨眼、張嘴，再 `update_puppet(delta)`。
- **`_drive(p, key, v)`**：照 `NAMES` 表試名字，自動綁定的（`Breath`、`Head:: Yaw`、`Eye:: Blink`、`Mouth:: Open`）和手工模型的（`Head:: Yaw-Pitch` 等）都認得。二維參數時，轉頭改 X、張嘴改 Y；眨眼兩隻眼都設。
- **`play_pose(pose, duration)`**：新姿勢 0.12 秒（`FADE`）淡入、舊的淡出。淡入淡出還沒結束又換姿勢時，先停掉上一次、把其他姿勢收好；淡出結束時只隱藏已經不是目前姿勢的那一個（否則快速切回來時兩個都會不見）。
- **`talk(seconds)`**：接下來這幾秒嘴巴會動。

## 6. `PuppetPartView`

- `puppet`、`uuid`：要畫哪個模型的哪個部件。
- `mask_of`：空的＝畫這個部件；有值＝當遮罩容器，畫這些遮罩部件的網格。
- **`_draw()`** → **`_draw_part(n)`**：用 `RenderingServer.canvas_item_add_triangle_array` 畫出部件目前的頂點（`part_points`）、貼圖座標和三角形。

## 7. 沒有支援的

閃避遮罩（dodge）、遮罩的門檻值、`EXT_SECT` 延伸資料、動畫（`animations`）、自動化（`automation`）。
