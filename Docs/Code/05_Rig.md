# 綁：自動綁定（`Tools/art/inx_rig.py`）

```
python Tools/art/inx_rig.py <角色> <服裝> [輸出.inx]
```

從拆好的圖層產生 Inochi2D 0.8 的 `.inx` 模型（Inochi Creator 打得開，也可以拿來手動微調）。不需要 ComfyUI。

- **細部綁定 `rig_st`**：有細部分層（`st/parts.json`）時用，輸出 `<角色>_<服裝>_st.inx`。
- **粗綁定 `rig`**：只有 `live_layers.py parts` 的粗分層時用，輸出 `<角色>_<服裝>.inx`。

主設計的 `<服裝>` 在檔名裡寫成 `default`。模型裡的座標以立繪中心為原點。

---

## 0. 函式呼叫流程

```
__main__
├─ st_usable(hero, series)                        細部分層能不能用
└─ rig_st(hero, series, out)  或  rig(hero, series, out)

rig_st(hero, series, out)
├─ 讀 full.png、load_joints(fig_joints.json)、mouth.json、parts.json
├─ 頭
│  ├─ part_img(n) / have(n) / real(n) / as_plate(img, full)
│  ├─ add(name, img, zsort)  每個部件
│  │  └─ Part(...) → grid_mesh(alpha, w, h)
│  ├─ composite("Eye L/R", ...)                  眼白＋虹膜
│  ├─ patch(size, mouth_a.png, mouth_box)        張嘴圖
│  ├─ head_depth(n)                              帽子、髮束的前後
│  └─ node("… Physics", kind="SimplePhysics")    前髮、後髮的擺
├─ 身體
│  ├─ body_depths(names, st)                     照 parts.json 排前後
│  ├─ add(...) × 身體各層、chest、cape、Other …
│  └─ clean_objects(objects, full)               武器
├─ 手臂（每一邊）
│  ├─ over_head(n)                               要不要畫在頭前面
│  ├─ node("Shoulder") → node("Elbow") → node("Wrist") → node("Grip")
│  ├─ param("Weapon:: Turn", ...) ← value_binding
│  └─ param("Arm:: <側>:: Shoulder / Elbow / Wrist / Move", ...)
│     └─ 肩膀：near(top, 肩) → turn_follow(top, 肩, 角度, 權重) → deform_binding
├─ 腿（每一邊）
│  ├─ node("Hip") → node("Knee") → node("Ankle")
│  └─ param("Leg:: <側>:: Hip / Knee / Ankle", ...)
│     └─ 髖：skirt_follow(skirt, 髖, 膝, 兩髖 x, 範圍) → deform_binding
├─ 擺動
│  ├─ pendulum(label, kind, pos) × 每個會擺的東西
│  └─ below(pt, y0) / near(...)                  權重
├─ 腰：其他節點移到 node("Waist") 底下
│  └─ param("Body:: Lean") ← turn_follow(裙子上緣)
├─ 參數：Breath、Head:: Yaw / Pitch / Roll、Eye:: Blink / Look、Brow:: Up、Mouth:: Open、各種 Physics
│  └─ param(...) ← value_binding / deform_binding
└─ write_inx(out, payload, images)

rig(hero, series, out)
├─ load_joints、mouth.json
├─ refine_layers(full, hair, face, body, face_info)   頭髮顏色的像素移到頭髮層、補頭底下
├─ add_part(...) → Part(...)
├─ diff_box(full, blink) → patch(...)              閉眼（沒有 eyes_closed.png 時）
├─ node / param / value_binding / deform_binding
└─ write_inx(...)
```

## 1. 入口：用哪一種

**`st_usable(hero, series)`**：要有 `st/parts.json` 和 `fig_joints.json`，而且拆出來的眼白（沒有就用臉）的中心，離 `fig_joints.json` 的臉不超過半張臉（至少 30 像素）。曾經有一張把胸前的圖案當成第二顆頭；這時改用粗綁定。

## 2. 共用的積木

| 名字 | 做什麼 |
|---|---|
| `Part(name, rgba, tex_index, zsort, center, opacity)` | 從立繪大小的圖層做出部件：裁出貼圖（`box` 是在立繪上的範圍）、位置（以立繪中心為原點）、網格 |
| `Part.world_x(i)`、`world_y(i)` | 第 i 個頂點在立繪上的座標（算變形權重用） |
| `grid_mesh(alpha, w, h)` | 每 48 像素（`CELL`）一格，格子裡有像素就做兩個三角形，頂點共用 |
| `node(...)`、`composite(...)` | 一般節點、組合節點的 JSON |
| `value_binding(uuid, key, values)` | 位移、旋轉、透明度的綁定（每個軸點一個值） |
| `deform_binding(part, offsets)` | 網格變形的綁定（每個軸點一組頂點位移） |
| `param(name, axis, lo, hi, bindings)` | 一維參數 |
| `turn_follow(pt, pivot, angles, weights)` | 變形：每個頂點繞某點轉「角度 × 權重」 |
| `near(pt, at, radius)` | 權重：以某點為中心的高斯 |
| `skirt_follow(...)` | 裙子跟腿（見 4-6） |
| `diff_box(a, b, pad)`、`patch(size, src, box)` | 從差分圖裁出一塊、邊緣羽化（張嘴、閉眼） |
| `clean_objects(obj, full)` | 武器層裡補畫出來的淺灰粗條（被擋住的弓弦）刪掉 |
| `load_joints(path)` | 讀 `fig_joints.json`，偵測不到的脖子、肩、髖用臉的位置和大小推算（手肘、手腕保持空的） |
| `write_inx(path, payload, images)` | 寫檔：JSON 區段＋每張貼圖存成 PNG（格式見 [09_Files.md](09_Files.md)） |

## 3. 調整用的常數

| 常數 | 值 | 意思 |
|---|---|---|
| `YAW_PX`、`PITCH_PX`、`ROLL` | 14、8、0.2 | 轉頭位移、點頭位移（像素）、歪頭角度（弧度） |
| `HAIR_PARALLAX` | 6 | 轉頭時前髮多移、後髮反向移的量 |
| `BREATH_PX` | 6 | 呼吸時胸口抬起 |
| `ARM_TURN` | 0.08 | 「Move」參數的肩膀小擺動 |
| `SHOULDER_TURN`、`ELBOW_TURN`、`WRIST_TURN`、`WEAPON_TURN` | 1.4、1.6、0.8、3.1 | 參數到 ±1 時的旋轉（弧度） |
| `WAIST_TURN`、`HIP_TURN`、`KNEE_TURN`、`ANKLE_TURN` | 0.6、1.2、1.6、0.8 | 同上 |
| `GOWN_HIP`、`GOWN_KNEE` | 0.3、0.5 | 長裙（下緣比膝蓋低 40 像素以上）裡的腿只能小動 |
| `SKIRT_FOLLOW`、`SHORTS_FOLLOW` | 0.8、1.0 | 裙子、短褲跟著大腿轉的比例 |
| `SLEEVE_FOLLOW` | 0.45 | 舉手時上衣靠肩膀的地方跟著轉的比例 |
| `COLLAR_YAW` | 0.35 | 轉頭時領口跟著滑的比例 |
| `LEAN_FOLLOW_H` | 0.18 | 彎腰時裙子上緣跟著彎、往下淡出的範圍（人物高度的比例） |
| `SWING` | 見 4-7 | 每種擺動的擺長、頻率、阻尼、擺幅 |

`rig_stress.py` 直接匯入這些旋轉常數，把參數值換算成角度。

---

## 4. 細部綁定 `rig_st`

### 4-1. 讀資料

1. 立繪：資料夾自己有 `full.png`（關鍵姿勢）就用它，否則照設定檔找。
2. `load_joints`、`mouth.json`（有的話）、`st/parts.json` 的順序清單和 `pivots`。
3. 內部的小函式：
   - **`part_img(n)`**：讀 `st/part_<n>.png`，**裁到人物輪廓外擴 2 像素**（人物外面不可能被擋住，多畫的一定會露出來）。
   - **`have(n)`**：有沒有這一層。
   - **`real(n)`**：可有可無的層（帽子、不認得的層）要一半以上落在人物上、而且是立繪顯示的顏色才採用，否則印出 `dropped invented part` 丟掉。
   - **`as_plate(img, full)`**：落在人物上的像素全部換成立繪的顏色（前髮用：它在頭的最前面）。
   - **`head_depth(n)`**：頭上的東西照順序清單放：排在臉之前＝臉後面（0.5）、在臉和前髮之間（-0.06）、在前髮之後＝最前面（-0.15）。
   - **`over_head(n)`**：手臂或武器要不要畫在整顆頭前面：順序清單排在前髮之後，**而且**在脖子以上蓋住頭部、那裡顯示立繪顏色的像素有 50 個以上（蕾娜舉起扳手）。
   - **`add(name, img, zsort, opacity, blend)`**：建立部件，貼圖加進清單。
   - **`pj(part, parent_pos)`**：部件轉成 JSON，位置換成相對父節點。

### 4-2. 節點樹

```
Root
├─ Legs / Footwear / Bottomwear / Hidden Pelvis     （跟骨盆走：彎腰時不動）
├─ Hip Left / Hip Right                              腿分段時
│   ├─ Thigh、Bottomwear <側> Physics
│   └─ Knee ─ Shin、Ankle ─ Foot
└─ Waist                                             「Body:: Lean」在這裡轉
    ├─ Hidden Body、Neck、Topwear、Chest、Cape、Other …、Body Accessory、各種 Physics
    ├─ Shoulder Left / Right
    │   ├─ Upper Arm
    │   └─ Elbow ─ Forearm、Sleeve（＋Physics）
    │       └─ Wrist ─ Hand
    │           └─ Grip ─ Weapon、Weapon Back、Tassel（＋Physics）   握武器的那隻手
    ├─ Weapon、Weapon Back                           沒人握時
    └─ Head（脖子位置）
        ├─ Back Hair、Face、Ears、Nose、Mouth
        ├─ Eye L / Eye R（組合）─ Eye White、Iris（只畫在眼白上）
        ├─ Eyelash、Eyebrow、Eyes Closed、Mouth Open
        ├─ Front Hair、Headwear、Headwear Front、Head Accessory
        ├─ Side Lock / Ahoge / Ribbon / Earring / Ponytail / Hair Ends、Side Hair
        └─ Back Hair Physics、Front Hair Physics、Headwear Physics、各髮束的 Physics
```

只有整條手臂（沒有分段）時，`Shoulder` 底下直接掛 `Arm`，握武器的話武器也掛在同一個節點。沒有腿分段時，腿以 `Legs`、`Footwear` 跟骨盆走。

### 4-3. 頭

- `Head` 放在脖子的位置，`zsort` -0.5（整顆頭在身體前面）。
- `leftover` 以脖子高度切開：上半是 `Head Accessory`（髮帶等，跟頭走），下半是 `Body Accessory`（跟身體走）。
- 每隻眼睛一個組合：眼白＋虹膜（`ClipToLower`，只畫在眼白上）。側臉只有一層虹膜時，取眼白範圍內的部分。睫毛、眉毛另外放。
- 閉眼圖 `eyes_closed.png`、張嘴圖（`mouth_a.png` 在 `mouth.json` 的嘴巴範圍裡的部分）有的話加進去。
- 頭上的前後順序（數字越大越後面，相對 `Head`）：

  | 部件 | zsort |
  |---|---|
  | 後髮、髮尾 | 1.1 |
  | 耳朵 | 0.15 |
  | 臉 | 0.1 |
  | 鼻 | 0.05 |
  | 嘴、張嘴圖 | 0.04、0.035 |
  | 眼睛組合（眼白 0.02、虹膜 -0.01） | 0.03 |
  | 睫毛、眉毛、閉眼圖 | 0、-0.02、-0.03 |
  | 前髮 | -0.1 |
  | 帽子、帽子前半、切出來的髮束 | `head_depth` |
  | 頭上的飾品 | -0.2 |
  | 側髮 | 上衣和 `hidden` 之間（換算成相對 `Head`） |

### 4-4. 身體

- **`body_depths`**：身體各層（`BODY_ORDER`：`hidden`、腿、鞋、下著、`hidden-pelvis`、脖子、手臂、上衣）的前後照 `parts.json` 的順序排，在 0.5～0.35 之間平均分配。理由：一層只在它排最前面的地方是立繪的顏色，換別的順序會露出補畫的猜測。
- 依序加入 `Hidden Body`、`Legs`、`Footwear`、`Bottomwear`、`Hidden Pelvis`、`Neck`、`Topwear`（空的層跳過）。`hidden` 本來就是補畫的，不經過 `real`。
- `chest`（`object_fix --carve chest --carve-copy` 切的）放在上衣正前面；`cape` 放在 0.65（身體後面、後髮前面）。
- 不認得、但通過 `real` 的層，以 `Other <名字>` 掛在身體上（0.36）；`Body Accessory` 0.34。

### 4-5. 手臂與武器

- 握點：`parts.json` 的 `pivots.grip` 優先，沒有才用 `fig_joints.json` 的 `weapon_grip`。
- 武器：`objects` 經 `clean_objects`，放在 0.27（`over_head` 時放到頭前面）。`objects-back` 放在 1.3（所有東西後面，包括後髮）。
- **分段手臂**（上臂、前臂、手都有）：`Shoulder` → `Elbow` → `Wrist` 串起來；握武器的手在 `Wrist` 底下多一個 `Grip` 節點，武器排在手指後面一點。有 `sleeve-<側>` 時掛在 `Elbow` 下，有 `tassel` 時掛在 `Grip` 下。
- 手臂的前後：照上臂（或整條手臂）在 `body_depths` 的位置；`over_head` 時 -0.8（頭前面）。手、前臂、武器、袖子各往前一點點。

### 4-6. 腿

有大腿、小腿、腳掌三段和髖、膝、踝三個關節時：`Hip` → `Knee` → `Ankle`，前後照大腿在 `body_depths` 的位置（沒有就 0.45）。

- **長裙**：下緣比膝蓋低 40 像素以上，髖、膝的範圍改成 `GOWN_HIP`、`GOWN_KNEE`。
- **短褲**：下緣在膝蓋上方很多，整片跟大腿走（`SHORTS_FOLLOW`）。
- **`skirt_follow`**：轉髖時，裙子每個頂點繞髖轉「腿的角度 × 0.8」，權重＝橫向離這條腿的高斯（寬度＝兩髖距離）×（從髖到膝由 0 長到 1）。

### 4-7. 擺動（物理）

**`pendulum(label, kind, pos)`** 做一個彈簧擺節點（`SimplePhysics`），掛在會帶動它的節點底下。播放器看的是擺的錨點在世界中的位置，所以掛在會轉的節點下就會被帶動。每個擺推動一個「<部件>:: Physics」參數，綁在部件的網格變形上。

| 種類 | 擺長 | 頻率 | 角度阻尼 | 擺幅（部件大小的比例） | 用在哪 | 掛在哪 |
|---|---|---|---|---|---|---|
| `skirt` | 160 | 1.0 | 0.3 | 0.5 | 裙子，左右兩半各一個 | 各自的膝蓋（沒有腿分段就掛腰） |
| `hem` | 140 | 1.1 | 0.35 | 0.35 | 上衣下擺（低於腰超過人物 12%） | 腰 |
| `cape` | 200 | 0.8 | 0.28 | 0.4 | 披風 | 披風上緣 |
| `chest` | 30 | 3.0 | 0.55 | 0.05 | 胸（上下也動；切口邊緣不動） | 胸的上緣 |
| `hat` | 90 | 1.8 | 0.5 | 0.12 | 帽子（離頭中心越遠擺越多，帽子前半共用同一個擺） | 頭 |
| `lock` | 130 | 1.2 | 0.4 | 0.22 | 側髮、`side_lock-*` | 頭 |
| `ends` | 170 | 0.9 | 0.3 | 0.3 | 髮尾 `hair_ends` | 頭 |
| `ponytail` | 150 | 1.0 | 0.3 | 0.35 | 馬尾 | 頭 |
| `ahoge` | 40 | 2.6 | 0.4 | 0.35 | 呆毛（往上翹，尖端擺最多） | 頭 |
| `ribbon` | 50 | 2.0 | 0.45 | 0.3 | 髮帶、耳環 | 頭 |
| `sleeve` | 110 | 1.1 | 0.35 | 0.35 | 寬袖 `sleeve-*` | 手肘 |
| `tassel` | 60 | 1.8 | 0.4 | 0.4 | 武器上的流蘇 | 握點 |
| `accessory` | 60 | 2.0 | 0.45 | 0.25 | 身上的小東西（`Body Accessory`、`Other …`） | 它的上緣 |

權重多半是 `below`：從某條線往下由 0 長到 1（1.5 次方），越下面擺越多。

前髮、後髮另有自己的擺（後髮：擺長取後髮高度的 0.6、頻率 1.1；前髮：擺長 120、頻率 1.6），擺幅是高度的 0.3 和 0.12。

### 4-8. 腰

除了 `LOWER_BODY`（`Legs`、`Footwear`、`Bottomwear`、`Hidden Pelvis`、`Bottomwear Physics`）和腿以外，其餘全部移到 `Waist` 節點底下（位置在 `pivots.waist`，沒有就是兩髖中點）。轉腰時裙子和 `hidden-pelvis` 的上緣跟著彎，往下在人物高度 18% 的範圍內淡出，接縫才不會裂開。

### 4-9. 參數

| 參數 | 範圍 | 綁定 |
|---|---|---|
| `Breath` | 0～1 | 上衣網格往上抬（肩膀最多、髖部不動）；頭、肩膀上移 4.8，胸 5.4 |
| `Head:: Yaw` | -1～1 | 頭左右移 14；前髮再多移 6、後髮反向 3.6；五官、眼睛組合、睫毛、眉毛 ±3；領口（脖子附近的上衣）和脖子跟著滑 0.35 |
| `Head:: Pitch` | -1～1（+1 低頭） | 頭上下 8；五官和眼睛多移 3、後髮反向 2.4 |
| `Head:: Roll` | -1～1 | 頭在脖子處歪 ±0.2 弧度 |
| `Eye:: Blink` | 0～1 | 眼白和虹膜往下眼瞼壓扁（92%）；睫毛下移眼高的 0.7、眉毛下移 0.15。有閉眼圖時軸點改成 0、0.8、1：壓扁在 0.8 完成，最後兩成閉眼圖淡入 |
| `Eye:: Look` | -1～1 | 虹膜左右移眼白寬的 0.2 |
| `Brow:: Up` | 0～1 | 眉毛上揚眼高的 0.35 |
| `Mouth:: Open` | 0～1 | 張嘴圖淡入（有張嘴圖時才有） |
| `Arm:: <側>:: Shoulder / Elbow / Wrist` | -1～1 | 各關節轉 1.4／1.6／0.8 弧度；**+1 在兩邊都是往外（往上）轉**。轉肩膀時，上衣靠肩膀的部分跟著轉 0.45 |
| `Arm:: <側>:: Move` | -1～1 | 肩膀小擺 0.08 弧度（分段、整條手臂都有） |
| `Weapon:: Turn` | -1～1 | 武器在握點轉 ±3.1 弧度 |
| `Leg:: <側>:: Hip / Knee / Ankle` | -1～1 | 轉 1.2／1.6／0.8 弧度（長裙 0.3／0.5）；轉髖時裙子跟著（`skirt_follow`）。腿的方向**沒有**左右對稱處理 |
| `Body:: Lean` | -1～1 | 腰以上轉 ±0.6 弧度 |
| `Back Hair:: Physics`、`Front Hair:: Physics`、`<部件>:: Physics` | -1～1 | 由物理驅動，部件的網格往左右彎 |

參數名字取自擺的名字（`swing_names`）：裙子左右兩半是 `Bottomwear Left:: Physics`、`Bottomwear Right:: Physics`（2026-10-01 之前兩個同名）。

---

## 5. 粗綁定 `rig`

沒有細部分層時用（粗分層來自 `live_layers.py parts`）。**需要 `mouth.json`**（沒有會出錯）。

```
Root
├─ Torso（或 Body）           「Breath」抬胸口
├─ Shoulder Left / Right ─ Arm、Weapon（握武器的那隻）     有四肢分層時
├─ Leg Left / Right
└─ Head（脖子位置）
   ├─ Hair、Hair Physics（彈簧擺）
   ├─ Face
   ├─ Eyes Closed             「Eye:: Blink」淡入
   └─ Mouth Open              「Mouth:: Open」淡入
```

- **`refine_layers`**：綁定前先整理：頭部附近跟頭髮顏色相近、連著頭髮的身體像素移到頭髮層；頭頂上的小東西（髮帶、髮夾）也移過去；頭底下的身體用 OpenCV 補色，轉頭時才不會露洞。
- 閉眼：有 `eyes_closed.png` 就用；沒有就從 `full_blink.png` 跟 `full.png` 的差異裁一塊。
- 參數：`Breath`、`Head:: Yaw`、`Eye:: Blink`、`Mouth:: Open`、`Arm:: <側>:: Move`、`Hair:: Physics`。
