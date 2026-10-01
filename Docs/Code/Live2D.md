# 會動的立繪：程式說明（依呼叫流程）

會動的立繪（Inochi2D 模型）從美術素材到遊戲畫面，經過的每支程式、每個函式，照實際呼叫的順序介紹：誰呼叫它、傳什麼進去、做了什麼。

設計與決定寫在 [Design/22_Live2D_Inochi2D.md](../Design/22_Live2D_Inochi2D.md)；這份只講程式。

## 0. 總覽

```
美術工具箱（拆層）                    本分支的程式
─────────────────                    ──────────────────────────────────────────────
art_work/live/<英雄>/<資料夾>/
  full.png、fig_joints.json、   ──►  Tools/art/inx_rig.py   自動綁定，產生 .inx 模型檔
  mouth.json、st/part_*.png、                │
  st/parts.json                             ▼
                                     Scripts/live/inochi_puppet.gd   播放器：讀 .inx、每格計算、畫出來
                                            │  （PuppetPartView 負責畫單一部件）
                                            ▼
                                     Scripts/live/live_portrait.gd   會動的立繪：呼吸、眨眼、說話、換姿勢
                                            │
                                            ▼
                                     遊戲畫面（英雄畫面由美術工具箱接上）

檢查：Tools/art/rig_check.py（靜止時跟原圖比）、Tools/art/rig_stress.py（轉關節找破洞）
預覽：Tests/live/puppet_preview、skill_preview；測試：Tests/live/puppet_test
```

| 檔案 | 用途 |
|---|---|
| `Scripts/live/inochi_puppet.gd`（`InochiPuppet`） | 播放器本體：讀模型、套參數、物理、決定前後順序、畫出來 |
| `Scripts/live/puppet_part_view.gd`（`PuppetPartView`） | 畫一個部件的網格，或當遮罩容器畫出遮罩 |
| `Scripts/live/live_portrait.gd`（`LivePortrait`） | 包住一個或多個模型（每個姿勢一個），自己呼吸、眨眼、東張西望、說話、換姿勢 |
| `Tools/art/inx_rig.py` | 自動綁定：從拆好的分層產生 `.inx` |
| `Tools/art/rig_check.py` | 把模型靜止時畫出來，逐點跟原圖比 |
| `Tools/art/rig_stress.py` | 把每個關節轉到兩端，找出破洞 |
| `Tests/live/rig_render.gd` | 上面兩支檢查工具用的：照原圖大小畫出模型（可指定參數） |
| `Tests/live/puppet_preview.gd` | 單一模型的預覽：掃過各參數、30 秒待機、跑跳 |
| `Tests/live/skill_preview.gd` | 技能動作預覽：換姿勢加特效（射箭、火球、冰霜、砸地） |
| `Tests/live/puppet_test.gd` | 播放器規則的自動測試（`Tools/run_tests.sh quick` 會跑） |

用詞：
- **模型**：一個 `.inx` 檔，裡面有節點樹、參數、貼圖。
- **節點**：模型樹上的一個點，有自己的位置、旋轉、縮放；子節點跟著父節點動。
- **部件**：有貼圖和網格、真的會畫出來的節點。
- **參數**：一個名字加一個數值（例如 `Eye:: Blink` 從 0 到 1），數值改變時，綁在它上面的節點跟著移動、旋轉、變形或變透明。
- **前後順序**：每個節點有 `zsort`，數字越大越後面（越先畫）。

---

## 1. 載入模型（播放器初始化）

使用方式：

```gdscript
var p := InochiPuppet.new()
p.load_model("res://…/alicia_pose_idle_st.inx")
add_child(p)
```

呼叫順序：

1. **`load_model(path) -> bool`**
   打開 `.inx` 檔，依序讀三個區段：
   - `TRNSRTS`：4 位元組長度＋模型的 JSON 內容；
   - `TEX_SECT`：貼圖數量，每張是長度、編碼（0 = PNG、1 = TGA）、資料；
   - `EXT_SECT`：延伸資料，略過。
   每張貼圖交給 `_decode_texture`，JSON 交給 `load_payload`。
2. **`_decode_texture(blob) -> Texture2D`**
   把 PNG / TGA 解成圖片，**產生縮圖層級**（立繪畫得比貼圖小，沒有這一步細線會斷成點點），再做成貼圖。
3. **`load_payload(payload) -> bool`**
   JSON 的主流程（測試也直接用它，在程式裡組模型）：
   - 讀物理設定（重力、每公尺幾像素）；
   - `_make_node(payload["nodes"], -1)`：遞迴建立整棵節點樹；
   - 每個參數交給 `_make_param`，並建立「名字 → 參數」的對照；
   - 找出所有物理節點（`SimplePhysics`），用 `_new_physics` 給初始狀態；
   - `_build_views()`：建立畫面用的節點；
   - `update_puppet(0.0)`：先算一格，讓第一次畫面就正確。
4. **`_make_node(src, parent) -> int`**
   把一個 JSON 節點轉成字典存進 `nodes`（以 `uuid` 為鍵），共同欄位有位置、旋轉、縮放、`zsort`，以及每格由參數加上去的偏移量（`ot`、`or`、`os`、`osort`、`oopacity`）。依類型再多讀：
   - 部件：網格頂點、貼圖座標、三角形、貼圖編號、透明度、色調、混合方式、遮罩；
   - 組合（`Composite`）：透明度、色調、混合方式；
   - 物理：驅動哪個參數、單擺或彈簧擺、長度、頻率、阻尼、輸出方式。
   再對每個子節點遞迴呼叫自己。小工具 `_v2`、`_v3`、`_flat_v2` 負責把 JSON 陣列轉成向量。
5. **`_make_param(src) -> Dictionary`**
   參數的範圍、預設值、軸上的點（一維或二維），以及每個綁定：綁到哪個節點、改什麼（位移、旋轉、縮放、`zSort`、透明度、網格變形），和每個軸點上的數值表。
6. **`_new_physics(n)`**：單擺的初始狀態，擺錘在錨點正下方、靜止。
7. **`_build_views()`**
   清掉舊的畫面節點；對每個「最上層可畫物」（`_root_drawables`）用 `_view_for` 建一個畫面節點掛到自己底下。
   - **`_root_drawables(uuid)`**：往下找所有部件；遇到組合就把整個組合當一個（組合裡的部件由組合自己畫）。
   - **`_parts_below(uuid)`**：一個組合底下的所有部件。
8. **`_view_for(uuid) -> Node2D`**：一個可畫物對應的畫面節點。
   - **組合**：一般混合就用普通 `Node2D` 當群組（Godot 不能在 `CanvasGroup` 裡再套裁切）；只有整組要相乘或相加時才用 `CanvasGroup`。群組裡每個部件再呼叫一次 `_view_for`。
   - **部件**：建一個 `PuppetPartView`，材質由 `_blend_material` 決定。
   - **有遮罩的部件**：再包一層遮罩容器（也是 `PuppetPartView`，`mask_of` 填遮罩部件），容器只讓子節點在遮罩範圍內顯示。混合方式放在容器上（`_group_material`），部件本身改用一般材質。
   - **「只畫在下面那層上」（`ClipToLower`，例如虹膜只畫在眼白上）**：沒有明寫遮罩時，用 `_lower_of` 找出正下方那個部件當遮罩。
   - **相乘的部件（陰影）** 不包容器：Godot 會把容器整塊合成，透明處在相乘時會變黑。
9. **`_lower_of(uuid) -> int`**
   照前後順序排好，往回找最近一個「不是 `ClipToLower`」的部件，先找同一個父節點底下的。在組合裡只看組合自己的部件（眼白和虹膜在同一個組合裡）。
10. **`_blend_material(mode)`**：部件用的著色器，依混合方式分四種（一般、相乘、相加、相減），共用快取。著色器做三件事：
    - 貼圖範圍外當透明（不然邊緣像素會被拉長成條紋）；
    - 把貼圖從「預乘透明」轉回一般顏色（不轉的話半透明邊緣會變黑框）；
    - 用頂點顏色（透明度、色調）乘上貼圖；相乘模式在透明處改成白色，才不會把底下塗黑。
11. **`_group_material(mode)`**：群組或容器合成時用的混合方式（只有相乘、相加、相減需要）。

---

## 2. 每一格的更新

`InochiPuppet._process(delta)` 每格呼叫 **`update_puppet(delta)`**。由 `LivePortrait` 管的模型會關掉自己的 `_process`，改由 `LivePortrait` 在設好參數後呼叫。順序跟 Inochi2D 官方一樣：

1. **歸零**（沒有載入模型時直接跳過）：每個節點的偏移量回到零（縮放和透明度回到 1），網格變形清空。
2. **套用參數**：每個不是物理驅動的參數呼叫 **`_apply_param(p)`**：
   - 數值換成 0～1 的比例，用 **`_cell(axis, v)`** 找出落在哪兩個軸點之間、偏多少；
   - 對每個綁定，在數值表裡內插（一維是線性，二維是雙線性）；
   - 網格變形直接加到頂點上；其他交給 **`_set_offset(n, key, v)`**：位移和旋轉用加的，縮放和透明度用乘的。
3. **算位置**：**`_update_transforms(root, 單位矩陣)`** 從根節點往下遞迴，每個節點的全域位置 = 父節點的全域位置 × 自己的本地位置（**`_local(n)`**：原本的位置／旋轉／縮放再加上偏移）。根節點另外套上 `root_offset`、`root_scale`（跳躍、跑步用，這樣物理才感覺得到整個人在動）。
4. **物理**：每個物理節點呼叫 **`_physics(n, delta)`**：
   - **`_anchor(n)`**：錨點位置（通常是節點的全域位置）；
   - 以 0.01 秒為一步呼叫 **`_phys_tick`**，用 **`_rk4`**（四階龍格－庫塔法）推進單擺或彈簧擺；一格最多算 0.25 秒（`MAX_PHYS_DELTA`，遊戲從背景回來時那一格可能有好幾秒，全算會卡住）；
   - 擺錘位置換算成參數值（角度＋長度，或 X＋Y），寫進被驅動的參數，再 `_apply_param`。
5. **再算一次位置**：物理改了參數，位置要重算。
6. **畫面**：**`_redraw()`**：
   - 用 **`zsort_of(n)`**（自己的 `zsort` + 偏移 + 所有父節點的）排出前後順序，順序有變才搬動畫面節點；
   - 每個畫面節點設定顯示與否、色調、透明度，要求重畫；組合裡的部件也各自排序；
   - 重畫時 `PuppetPartView._draw()` → **`_draw_part(n)`**：用 **`part_points(n)`**（網格頂點＋變形，經過全域位置換算）和貼圖座標畫出三角形。遮罩容器則畫出遮罩部件的網格。

---

## 3. 從外部控制播放器

| 函式／變數 | 用途 |
|---|---|
| `set_param(name, value) -> bool` | 設定參數（一維給數字，二維給 `Vector2`）；找不到回傳 `false` |
| `get_param(name) -> Vector2` | 讀參數目前的值 |
| `param_names()` | 模型所有參數的名字 |
| `root_offset`、`root_scale` | 從模型內部移動、壓扁整個人（跳躍、跑步）：頭髮物理會跟著反應 |
| `part_points(n)`、`zsort_of(n)` | 部件目前的頂點位置、前後順序（預覽和特效定位用） |
| `nodes`、`params`、`param_by_name` | 模型資料，唯讀使用 |

---

## 4. 會動的立繪（`LivePortrait`）

使用方式：

```gdscript
var lp := LivePortrait.new()
lp.add_pose(&"idle", ".../pose_idle/alicia_pose_idle_st.inx")
lp.add_pose(&"draw", ".../pose_draw/alicia_pose_draw_st.inx")
add_child(lp)
lp.talk(2.0)                    # 說話 2 秒
lp.play_pose(&"draw", 0.6)      # 換成拉弓，0.6 秒後自動回到待機
lp.pose_finished.connect(...)   # 回到待機時通知
```

### 4-1. 加入姿勢

1. **`add_pose(pose, path) -> bool`**
   建一個 `InochiPuppet` 並 `load_model`，關掉它自己的每格更新（由 `LivePortrait` 統一驅動，所有姿勢拿到一樣的呼吸、眨眼數值），第一個加入的顯示、其他隱藏。接著：
2. **`_read_frame(path) -> Dictionary`**
   讀模型旁邊的 `fig_joints.json` 和 `full.png`，算出：
   - 軀幹長度（脖子到兩髖中點）；
   - 脖子位置；
   - 腳底高度（原圖最下面一排有顏色的像素）。
   位置都以原圖中心為原點。缺脖子或髖部（偵測不到時是 `null`）就回傳空的，那個姿勢不對齊。
3. **`_align(pose)`**
   跟第一個姿勢對齊：先縮放到軀幹一樣長，再左右對齊脖子、上下對齊腳底（蹲下的姿勢腳還是踩在地上）。不用臉的大小，是因為側臉量起來會小很多。

### 4-2. 每格的待機動作

**`_process(delta)`**：
1. 計時的姿勢到時間了，就 `play_pose(idle_pose)` 並發出 `pose_finished`。
2. 每 2.5～5.5 秒眨一次眼（0.18 秒）。
3. 每 2～5 秒換一個看的方向，平滑轉過去。
4. 說話時嘴巴開合。
5. 對每個顯示中的姿勢用 **`_drive(p, key, v)`** 設定參數，再呼叫它的 `update_puppet(delta)`。

**`_drive(p, key, v)`**：照 `NAMES` 表試名字，自動綁定的名字（`Breath`、`Head:: Yaw`、`Eye:: Blink`、`Mouth:: Open`）和手工模型的名字（Aka 用的 `Head:: Yaw-Pitch` 等）都認得。二維參數時，轉頭改 X、張嘴改 Y；眨眼兩隻眼都設。

### 4-3. 說話與換姿勢

- **`talk(seconds)`**：接下來這幾秒嘴巴會動。
- **`play_pose(pose, duration = 0)`**：新姿勢在 0.12 秒內淡入、舊的淡出；有給時間的話，時間到自動回待機。淡入淡出還沒結束又換姿勢時，先停掉上一次的淡入淡出、把其他姿勢收好，淡出結束時也只隱藏已經不是目前姿勢的那一個（否則快速切回來時兩個姿勢都會不見）。

---

## 5. 自動綁定（`Tools/art/inx_rig.py`）

```
python Tools/art/inx_rig.py <英雄> <資料夾> [輸出檔]
    資料夾：造型（"-" 是初始造型）或姿勢資料夾（pose_idle、pose_draw…）
輸出：art_work/live/<英雄>/<資料夾>/<英雄>_<資料夾>_st.inx（細部分層）或 <英雄>_<資料夾>.inx（舊的粗分層）
```

### 5-1. 入口

1. **`st_usable(hero, series)`**：有細部分層（`st/parts.json`），而且拆出來的眼睛（或臉）離 `fig_joints.json` 的臉不遠（半張臉以內）。
2. 可以用就呼叫 **`rig_st`**，否則退回 **`rig`**（舊的粗分層：頭髮、臉、身體、四肢）。

### 5-2. `rig_st`：讀資料

1. 讀原圖 `full.png`（姿勢資料夾自己有；造型則用 `src_dir` 到 `Assets/Heroines/` 找）。
2. **`load_joints(path)`**：讀 `fig_joints.json`，偵測不到的脖子、肩膀、髖部用臉的位置和大小推算補上（手肘、手腕保持空的）。
3. 讀 `st/parts.json`：`order_back_to_front`（前後順序清單）和 `pivots`（關節與握把位置，新做法才有）。
4. 裡面的小函式：
   - **`part_img(n)`**：讀 `st/part_<n>.png`，**裁到人物輪廓內（外擴 2 格）**，人物外面補畫出來的東西一律不要；
   - **`have(n)`**：有沒有這個部件；
   - **`real(n)`**：可有可無的部件（帽子、不認得的部件）要一半以上的點落在人物上、顏色跟原圖一樣才採用，否則印出 `dropped invented part` 並丟掉；
   - **`as_plate(img, full)`**：落在人物上的點全部換成原圖顏色（前髮用：它在頭的最前面，看得到的一定要是原圖）；
   - **`head_depth(n)`**：頭上的東西（帽子）照順序清單放在臉後面、臉和前髮之間，或最前面；
   - **`over_head(n)`**：手臂或武器是否要畫在整顆頭前面：順序清單排在前髮後面，**而且**在脖子以上蓋住頭部、那裡顯示的是原圖顏色（五十點以上）；
   - **`add(name, img, zsort)`**：建立一個 `Part`（裁出貼圖、做網格），貼圖存進清單；
   - **`pj(part, parent_pos)`**：部件轉成 JSON，位置換算成相對父節點。

### 5-3. `rig_st`：頭部

- 剩餘層（`leftover`）以脖子為界切成兩半：上半跟頭走（髮帶、帽子），下半跟身體。
- `Head` 節點放在脖子位置（`zsort` -0.5，整顆頭在身體前面），底下依序：
  - 後髮（很後面）、臉、耳朵、鼻子、嘴；
  - 每隻眼睛一個組合：眼白＋虹膜（虹膜只畫在眼白上）；睫毛、眉毛另外放；
  - 畫好的閉眼圖（`eyes_closed.png`，有的話）、張嘴圖（`mouth_a.png` 依 `mouth.json` 的範圍）；
  - 前髮（`as_plate`）、帽子（`head_depth`）、頭上的剩餘層；
  - 前髮、後髮各一個彈簧擺物理。

### 5-4. `rig_st`：身體與手臂

1. **`body_depths(names, st)`**：身體各層的前後照順序清單排（每一層只有在排最前面的地方才是原圖顏色，別的順序會露出補畫的猜測），在 0.5～0.35 之間平均分配。
2. 身體底下補畫的一層（`hidden`，新做法才有：手臂和武器底下的身體，手臂移開時才露出來）、腿、鞋、下身、脖子、上衣依序加入。`hidden` 的顏色本來就是補畫的，不經過 `real` 檢查；不認得的部件用 `real` 檢查後跟身體走；身體的剩餘層放在身體前面。
3. 武器（`objects`）經 **`clean_objects`** 去掉補畫出來的淺灰粗條（被遮住的弓弦）。
4. 握把：`parts.json` 的 `pivots.grip` 優先，沒有就用 `fig_joints.json` 的 `weapon_grip`。
5. 每隻手臂：
   - **有上臂／前臂／手三段（新做法）**：`Shoulder` → `Elbow` → `Wrist` 三個節點串起來，各掛自己那一段；拿武器的手在 `Wrist` 底下再掛 `Grip` 節點，武器放在手指後面。參數：
     `Arm:: Left:: Shoulder`（±1.4 弧度）、`Elbow`（±1.6）、`Wrist`（±0.8）、`Weapon:: Turn`（±1.2）；
   - **只有整條手臂**：掛在 `Shoulder` 節點下，拿武器的話武器也掛在同一個節點；
   - 兩種都有 `Arm:: Left:: Move`（肩膀小幅擺動）；
   - `over_head` 成立的話，整條手臂放到頭前面。

### 5-5. `rig_st`：參數與寫檔

| 參數 | 綁定 |
|---|---|
| `Breath` 0～1 | 上衣網格往上抬（肩膀最多、髖部不動），頭和肩膀跟著上移 |
| `Head:: Yaw` -1～1 | 頭左右移，前髮移多一點、後髮反方向（有深度感），五官、眼睛小幅移動 |
| `Eye:: Blink` 0～1 | 眼白和虹膜往下眼瞼壓扁、睫毛下移、眉毛稍降；有閉眼圖的話最後兩成淡入 |
| `Eye:: Look` -1～1 | 虹膜左右移 |
| `Brow:: Up` 0～1 | 眉毛上揚 |
| `Mouth:: Open` 0～1 | 張嘴圖淡入 |
| `Back Hair:: Physics`、`Front Hair:: Physics` | 由物理驅動，頭髮下半部左右擺 |
| `Arm:: …` | 見 5-4 |

最後 **`write_inx(path, payload, images)`** 寫出 `.inx`：JSON 區段＋每張貼圖存成 PNG。

### 5-6. 共用的積木

| 函式 | 做什麼 |
|---|---|
| `Part(name, rgba, tex_index, zsort, center)` | 從原圖大小的圖層裁出部件：貼圖、在原圖中的範圍、位置（以原圖中心為原點）、網格 |
| `grid_mesh(alpha, w, h)` | 每 48 像素一格，有像素的格子做成兩個三角形 |
| `node(...)`、`composite(...)` | 節點、組合的 JSON |
| `value_binding(uuid, key, values)` | 位移／旋轉／透明度的綁定 |
| `deform_binding(part, offsets)` | 網格變形的綁定（每個軸點一組頂點位移） |
| `param(name, axis, lo, hi, bindings)` | 一維參數 |
| `patch(size, src, box)`、`diff_box(a, b, pad)` | 從差分圖裁出一塊（張嘴、閉眼），邊緣羽化 |
| `refine_layers(...)` | 舊粗分層用：頭附近頭髮顏色的點移到頭髮層，頭部底下的身體補畫 |

---

### 連動規則（22b「骨架與連動」）

- **擺動**：`rig_st()` 的 `pendulum(label, kind, pos)` 做一個 SimplePhysics 節點（彈簧擺，參數在 `SWING`：擺長、頻率、角度阻尼、擺幅佔物件大小的比例），掛在會帶動它的節點底下：裙子掛在 `Hip Left` 的膝蓋位置（沒有腿分段就掛骨盆，名稱 `Bottomwear Physics` 在 `LOWER_BODY` 裡），上衣下擺和身上配件掛腰，帽子掛頭。每個擺推一個「<零件>:: Physics」參數，綁在零件的網格變形上：權重 `below()`（某條線以下從 0 長到 1，1.5 次方）或帽子的「離頭中心的距離」平方。播放器的擺是看錨點的世界座標，所以掛在會轉的節點下面就會被帶動。
- **裙子跟腿**：`skirt_follow()` 讓「Leg:: <側>:: Hip」參數也帶動裙子的網格：每個點繞髖轉腿角度的 `SKIRT_FOLLOW` 倍，權重＝橫向離這條腿的高斯（寬度＝兩髖距離）×（從髖到膝 0→1）。裙子下緣比膝蓋低 40 像素以上算長裙，髖、膝範圍改用 `GOWN_HIP`、`GOWN_KNEE`。
- **手臂分段的方向**：「Arm:: <側>:: Shoulder / Elbow / Wrist」+1 在兩邊都是往外轉（跟「Move」一樣乘上左右方向）。

## 6. 檢查工具

### 6-1. 跟原圖比（`rig_check.py`）

```
python Tools/art/rig_check.py                   全部綁好的資料夾
python Tools/art/rig_check.py rena yukino/pose_open
結果：art_work/live/check/<名稱>_check.jpg、rig_check.json；有問題時結束代碼 1
```

1. **`folders(args)`**：列出要檢查的資料夾（有 `.inx` 的）。
2. **`model_and_plate(...)`**：資料夾裡最新的 `.inx` 和對應的原圖。
3. 一次啟動 Godot 跑 `Tests/live/rig_render.tscn`，每個模型畫成跟原圖一樣大的圖：
   - **`rig_render.gd` 的 `_ready()`** 讀參數列（`模型=輸出=寬x高[=參數:值;…]`），逐一呼叫 **`_render()`**：建一個透明背景的畫面、放入模型（原點在畫面中心，剛好對上原圖）、設定參數、算一格、等畫面畫完後存檔。
4. **`compare(plate, render)`**：逐點比對，輪廓內外 3 格不算（縮放造成的邊緣差異）：
   - 缺少：原圖有、模型沒畫（藍色）；
   - 顏色不對：RGB 差總和超過 90（紅色）；
   - 多出來：人物外面有畫（綠色）。
   相連的差異區域用黃框標出最大的幾塊。差異超過人物的 0.5%，或單一塊超過 0.1%，就標為有問題。

### 6-2. 轉關節找破洞（`rig_stress.py`）

```
python Tools/art/rig_stress.py freya/pose_idle
結果：art_work/live/check/<名稱>_stress.jpg（每個姿勢一格，破洞洋紅色、殘影青色）；有破洞或殘影時結束代碼 1
```

1. **`model_params(inx)`**：直接讀 `.inx` 的 JSON 區段，取得參數名字。
2. **`poses(names)`**：每個關節參數（`…:: Shoulder / Elbow / Wrist`、`Weapon:: Turn`）各取兩端 -1、+1。沒有關節參數的模型（整條手臂的舊做法）直接略過。
3. 一次啟動 Godot 畫出「靜止」加上每個姿勢（同樣用 `rig_render`，帶參數）。
4. **`body_area(ld, alpha)`**：不會動的部件（手臂、手、武器以外）合起來、補起小縫、填滿內部，就是「身體範圍」。
5. **`holes(rest, posed, body)`**：兩種破洞：
   - 靜止時有畫、轉動後變透明、而且在身體範圍內（手臂移開後，底下的身體沒補畫）；
   - 轉動後人物裡面出現、靜止時沒有的窄縫（關節裂開）。
   手臂移開後露出人物外面的背景是正常的，不算。
6. **`moved_pieces(ld, 參數, 值, 靜止畫面)`**：只轉一個關節時，這個關節以下的部件（例如轉肩膀是上臂、前臂、手，加上手上的武器）在靜止時看得到的範圍，以及照同樣角度繞關節轉過去之後的範圍。旋轉方向跟綁定一致（驗證過：算出來的新位置有 99% 被畫面蓋到）。
7. **`ghosts(舊範圍, 新範圍, 靜止畫面, 姿勢畫面)`**：殘影：部件的舊位置上現在沒有任何移動的部件，卻還顯示跟靜止時一樣的顏色（例如手指留在身體層裡，或排在後面的武器被前面的層當成原圖顏色畫進去）。

單一破洞或殘影超過人物的 0.05% 標為有問題。

---

### 輪廓（`Tools/art/outline.py`）

先輪廓、後顏色（22b 物件拆法 1～5）。線＝亮度 < `LINE_Y`（80）的像素（8 像素以下的點不算）；邊上 `NEAR_LINE`（2）像素內有線的是畫出來的邊，其餘是切開的邊。每段切開的邊（至少 `MIN_CUT` 12 像素）取離最遠的兩個端點，用端點附近 `TANGENT_R`（16）像素的畫出來的邊做主成分分析求方向，往外延伸：有骨架範圍（`object_fix.reach_mask`）的走到範圍盡頭再接起來，而且補的不能超出範圍；武器直接加上 `bridges()`；其他求兩條射線的交點。封閉形狀取最大一塊，加上中心在它凸包裡的小塊；形狀外的像素刪掉。成對的四肢拿 `object_fix.mirrored()` 翻過來的另一邊比，形狀三成以上在另一邊（擴 10 像素）外面就警告。`--check` 用 `object_check.whole()` 數塊數，加上輪廓外的像素、輪廓內沒顏色的比例（≤ 2%）。

上色：`object_fix.py --outline` 讀 `st/outline/` 的剪好的圖、形狀、線稿，用 `inpaint_lines` 工作流程（`workflows.py`：局部重繪加上 `xinsir_union_promax_sdxl` 的線稿模式，強度 0.8、作用到 80% 步數；線稿是黑底白線），形狀裡要補的像素全部換成新的顏色，形狀外一律透明。

### 單獨補一個物件（`Tools/art/object_fix.py`）

補一個圖層缺的、被擋住的、斷開的部分（22b「物件拆法」的第 2 步）。要補的範圍：四肢用 `parts.json` 的骨架點畫一條沿骨頭的帶子（寬度取圖層到骨頭距離的中位數 ×1.6），武器用 `bridges()` 把各塊在最近點用線接起來（線粗取距離變換的 75 百分位 ×2），其他圖層取前面圖層擋住、離自己邊緣 25 像素內的地方；再加上輪廓內的洞。補畫用 `heroine_j3.img2img`（局部重繪）、`ART_CKPT`（預設 waiIllustriousSDXL_v170）和 `key_poses.LORA` 的角色微調（強度 0.8），跟灰底差超過 40 的像素才算畫出來。`--dry` 只出範圍圖不用 ComfyUI。`object_check.whole()` 另外回傳浮動部件數（中心在最大塊凸包裡的小塊）。

## 7. 預覽與測試

### 7-1. 單一模型預覽（`puppet_preview.gd`）

```
Godot_console.exe --path . res://Tests/live/puppet_preview.tscn -- <模型.inx> <輸出資料夾> [參數=值 …] [secs=30] [motion=jump|run] [probe=x,y]
```
需要視窗（不能加 `--headless`）。
- `_ready()`：載入模型、用 `_fit()` 縮放置中，依參數選一種：
  - **`_run()`**：依序掃過轉頭、眨眼、張嘴、呼吸，存下靜止、轉頭、眨眼、張嘴、物理穩定後五張；
  - **`_run_long(secs)`**：待機若干秒（呼吸、眨眼、東張西望、偶爾說話，也會動身體和手臂），存動圖用的連續畫面；
  - **`_run_motion(kind)`**：跳三下或來回跑，用 `root_offset`、`root_scale` 移動，頭髮物理會跟著甩。
- `_set_first(names, value)`：設定第一個存在的參數名字；`名字=值` 指定的參數整段固定不動。
- `_probe(screen)`：印出某個畫面座標下是哪個部件（查錯用）。

### 7-2. 技能動作預覽（`skill_preview.gd`）

```
Godot_console.exe --path . res://Tests/live/skill_preview.tscn -- <輸出資料夾> style=bow|fire|frost|slam idle=<模型> <姿勢>=<模型> …
```
- **`STYLES`**：每種技能的時間表（每秒 30 格）：
  | 技能 | 姿勢與開始的格數 | 聚光 | 放出 |
  |---|---|---|---|
  | `bow`（艾莉西亞） | raise 30、draw 42、release 63（0.6 秒後回待機） | draw 的手，42～63 格 | 63 格，射箭光軌 |
  | `fire`（芙蕾雅） | raise 30、cast 45、recover 56（0.4 秒） | raise 的杖頂，32～45 格 | 49 格，火球從 cast 的杖頂飛出 |
  | `frost`（雪乃） | open 30、sweep 40、point 52（0.3 秒） | open 的手，31～40 格 | 46 格，冰霜弧線加冰晶 |
  | `slam`（蕾娜） | windup 30、slam 44、impact 50（0.4 秒） | windup 的扳手頂端，31～44 格 | 49 格，扳手最低點的衝擊圈加火花 |
- 流程：
  1. `_ready()`：讀參數，用 `LivePortrait.add_pose` 載入待機和該技能的姿勢（缺的姿勢用待機代替），每個姿勢讀：
     - **`_read_aim(inx)`**：`fig_joints.json` 的握把位置，和「遠離另一隻手」的方向（箭、火球飛的方向）；
     - **`_read_tips(inx)`**：武器圖層最上、最下那一點（杖頂寶珠、扳手頭）。
  2. `_fit()` 縮放置中。
  3. **`_run()`**：跑 120 格，到了時間就 `play_pose`；聚光期間在 **`_gather_point()`**（手或武器頂端）產生往內聚的光點，結束後光跟著淡出；放出那一格呼叫 **`_release(at, dir)`**（閃光、震動，砸地和冰霜另外噴出碎片）；每兩格存一張圖。
  4. **`_draw_fx()`**：每格畫出聚光、光點、各技能的放出效果、閃光。
  - 位置換算：**`_aim_point(pose)`**、**`_weapon_tip(pose, top)`** 都會經過該姿勢在 `LivePortrait` 裡的對齊（縮放和位移）。

### 7-3. 自動測試（`puppet_test.gd`）

`Tools/run_tests.sh quick` 會跑（不需視窗）。在程式裡組小模型，不讀檔案，共 16 項：
- **`_bindings()`**：一維、二維、網格變形、透明度的綁定，數值超出範圍時截斷；
- **`_order_and_masks()`**：前後順序、`zSort` 參數交換順序、遮罩容器、組合裡的「只畫在下面那層上」；
- **`_physics()`**：靜止時穩定、模型移動時頭髮擺動、之後再穩定下來；
- **`_portrait()`**：`LivePortrait` 說話時嘴巴會動、計時姿勢到時間回待機並發出通知、淡入淡出中快速切回來時目前的姿勢仍然顯示。

---

## 8. 檔案格式約定

### 8-1. 美術交給綁定的資料夾（`art_work/live/<英雄>/<資料夾>/`）

| 檔案 | 內容 |
|---|---|
| `full.png` | 原圖（去背）。所有座標都以它的像素為單位 |
| `fig_joints.json` | 姿勢偵測：`neck`、`shoulder_l/r`、`elbow_l/r`、`wrist_l/r`、`hip_l/r`（`[x, y]` 或 `null`）、`face`（`[x, y, 大小]`）、`weapon_grip`（`{hand, point}`） |
| `mouth.json`、`mouth_a.png` | 嘴巴範圍與張嘴差分 |
| `eyes_closed.png`、`full_blink.png` | 閉眼差分（有的話） |
| `st/part_<名稱>.png` | 細部分層，每張都是原圖大小 |
| `st/parts.json` | `order_back_to_front`（前後順序清單，每一層只在排最前面的地方是原圖顏色）；新做法再加 `pivots` |

### 8-2. 新做法的 `pivots`（跟美術工具箱約定）

```json
"pivots": {
  "shoulder_l": [x, y], "elbow_l": [x, y], "wrist_l": [x, y],
  "shoulder_r": [x, y], "elbow_r": [x, y], "wrist_r": [x, y],
  "grip": {"hand": "l", "point": [x, y], "tip": [x, y]}
}
```
搭配的部件：`upperarm-l/r`、`forearm-l/r`、`hand-l/r`（各自補畫完整、關節處多重疊幾格），`objects`（武器完整，包括被手遮住的部分）。順序清單裡，三段要放在原本整條手臂的位置。不同角度的整組部件放在 `st_<角度>/`（尚未實作）。

### 8-3. `.inx` 模型檔

```
"TRNSRTS\0" + JSON 長度（4 位元組，大端序）+ JSON
"TEX_SECT" + 貼圖數量 + 每張：長度、編碼（0 = PNG）、資料
```
JSON 裡有 `meta`、`physics`、`nodes`（節點樹）、`param`（參數）。寫入是 `inx_rig.write_inx`，讀取是 `InochiPuppet.load_model`，`rig_stress.model_params` 只讀參數名字。

---

## 9. 常用指令

```bash
# 綁定一個資料夾，再檢查
python Tools/art/inx_rig.py freya pose_idle
python Tools/art/rig_check.py freya/pose_idle
python Tools/art/rig_stress.py freya/pose_idle          # 有手臂分段時

# 技能動作預覽（每兩格一張圖，存到輸出資料夾）
Godot_console.exe --path . res://Tests/live/skill_preview.tscn -- out style=fire \
  idle=.../pose_idle/freya_pose_idle_st.inx raise=... cast=... recover=...

# 播放器測試
Tools/run_tests.sh quick
```
環境變數 `ART_WORK` 可以把素材資料夾換到別處（測試用），`GODOT` 可以指定 Godot 執行檔。

---

## 10. Live 2D 工作室（`Tools/live2d_studio/app.py`）

```
myenv/Scripts/python.exe Tools/live2d_studio/app.py      （或 Tools/live2d_studio/start.bat）→ http://127.0.0.1:7861
```
一個本機網頁（Gradio），把上面的工具照工作順序排成分頁；長時間的工作用子程序執行上面的指令，進度即時顯示。美術工作室（`Tools/studio`，7860）是另一個網頁，兩邊共用 ComfyUI、顯示卡和審核檔 `art_work/review_decisions.json`。

- **共用的小函式**：
  - `run(args, needs_comfy, exe)`：執行一支工具（Python 腳本，或 `exe=GODOT` 時執行 Godot），一行一行回傳進度；要 ComfyUI 而它沒開時直接提示。
  - `folders(hero)`、`folder_label(series)`：英雄的資料夾（造型在前、姿勢在後）和中文名稱。
  - `plate_of`（原圖：資料夾自己的，或 `Assets` 裡的造型）、`model_of`（資料夾裡最新的 `.inx`）、`check_results`（`rig_check.json`）、`review_of`（`review.json` 的自動警告）、`decisions`（審核檔；讀壞了就停下來，不當成空的，免得寫回去時把之前的決定洗掉）。
- **總覽**：`overview_rows()` 每個資料夾一列：原圖、細部分層幾層、自動審圖、你的審核、綁定時間、跟原圖比的結果；`overview_gallery()` 全部的原圖。「全部重新跟原圖比」＝`rig_check.py` 全部跑一次（結果併進 `rig_check.json`，不會洗掉別的資料夾）。
- **資料夾**：選英雄和資料夾，`folder_view()` 依工作順序列出：原圖、自動審圖、分層疊回、綁定後跟原圖的比對圖、動態截圖。步驟按鈕：
  1. `do_split` → `see_through.py`（要 ComfyUI）
  2. `do_review` → `review_plate.py`（姿勢資料夾）
  3. `do_rig` → `inx_rig.py`
  4. `do_check` → `rig_check.py <英雄/資料夾>`
  5. `do_shots` → Godot 跑 `puppet_preview.tscn`，截圖存在資料夾的 `_shots/`
  - `do_all`：3～5 一次做完，某一步失敗就停。
  - 「嘴型、情境圖、粗分層」（收合區）：`do_layers(step, ckpt, …)` → `live_layers.py mouths / scene / parts / preview`；模型選單決定補畫用的畫風（`ART_CKPT`），要跟這套造型原本的一樣。
- 關鍵姿勢、待審核、技能預覽、動畫的分頁已拿掉（2026-10-01，使用者：先留在設計文件裡）；對應的指令工具還在（`key_poses.py`、`skill_preview.tscn`、`animate.py`）。
- **狀態**：ComfyUI、顯示卡、Godot 是否可用；「啟動 ComfyUI」。
