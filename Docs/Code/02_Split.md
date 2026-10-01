# 拆：找骨架、拆圖層、切零件、嘴型

一張立繪變成一疊同樣大小的圖層，加上關節位置。三支程式依序執行：`live_layers.py parts`（骨架）→ `see_through.py`（拆圖層）→ `rig_parts.py`（切零件）。嘴型差分也在 `live_layers.py`。

產出的檔案格式見 [09_Files.md](09_Files.md)。

---

## 1. `Tools/art/live_layers.py`

```
python Tools/art/live_layers.py parts   <角色> <服裝>       找骨架＋粗分層
python Tools/art/live_layers.py mouths  <角色> <服裝>       嘴型差分
python Tools/art/live_layers.py scene   <角色> <服裝> [n]   情境圖去背、補背景、分 n 層深度
python Tools/art/live_layers.py preview <角色> <服裝>       粗分層和情境圖的預覽動圖
```

要 ComfyUI（`preview` 除外）。`<服裝>` 可以是服裝代號（`-`、`A`……）或關鍵姿勢資料夾（`pose_raise`……）。

### 函式呼叫流程

```
parts(hero, series)
├─ src_dir → 讀 full.png
├─ out_dir
├─ heroine_j3.prompt_for(hero, outfit_of(series), "full body, standing")
├─ split_figure(rgba, 提示詞, 資料夾, "fig")
│  ├─ flat(rgba)                                  貼到灰底
│  ├─ skeleton(plate)                             姿勢偵測
│  │  └─ _skeleton(img, None)  失敗 → _skeleton(img, "None")
│  │     ├─ workflows.load("pose") / fill
│  │     ├─ comfy_gen.upload(_tmp(img)) → comfy_gen.post("/prompt") → 等 comfy_gen.get("/history")
│  │     └─ 讀 ComfyUI 輸出資料夾的 art_pose_*.json
│  ├─ face_of(plate)
│  │  └─ heroine_j3.face_box  失敗 → 用 skeleton 的鼻子、眼睛、脖子
│  ├─ sam2_mask(...) × 多次                        臉、頭髮、手臂（上下兩次）、腿、軀幹、武器
│  │  └─ workflows.load("sam2") → heroine_j3.run_wf
│  ├─ clean_mask(...)                             每塊整理
│  ├─ inpaint(plate, 手臂底下, ...)                 補畫軀幹
│  │  └─ heroine_j3.img2img(..., mask) → workflows "inpaint" → heroine_j3.run_wf
│  └─ 寫 fig_*.png、fig_overview.png、fig_joints.json
├─ legacy_layers(d, joints, src)                  layer_hair / face / body.png
└─ eye_patch(hero, series, d, src)                eyes_closed.png、eyes.json
   └─ clean_mask

mouths(hero, series)
├─ src_dir、flat、face_of
├─ heroine_j3._ellipse_mask                       嘴巴的遮罩
├─ heroine_j3.prompt_for
└─ heroine_j3.img2img(..., mask) × 4               閉、啊、咿、喔 → mouth_*.png、mouth.json

scene(hero, series, n)
├─ cutout.cutout                                 去背
├─ inpaint(...)                                   補背景
├─ workflows "depth" → heroine_j3.run_wf          深度圖 → 切 n 層
└─ split_figure(..., "sc")

preview(hero, series)
└─ animate_figure(d, tag, size, t, ...) × 60 格 → preview_figure.gif（、preview_scene.gif）
```

### 1-1. 共用函式

| 函式 | 做什麼 |
|---|---|
| `src_dir(hero, series)` | 立繪在哪：`pose_*` 在工作資料夾自己裡面，其餘照設定檔 `plate_dir` |
| `outfit_of(series)` | 提示詞用哪套服裝：關鍵姿勢一律畫主設計（`-`） |
| `out_dir(hero, series)` | 工作資料夾 `<work>/live/<角色>/<服裝>/`（沒有就建立） |
| `flat(rgba)` | 把去背的人物貼到淺灰底（200, 200, 205）上：模型要的是有底色的圖；回傳（圖, 透明度） |
| `face_of(plate)` | 找臉：先用 `heroine_j3.face_box`；側臉找不到時，改用骨架的鼻子、眼睛、脖子推算 |
| `skeleton(img)` | 姿勢偵測（`pose` 工作流程），回傳信心 0.3 以上的關節 `{編號: (x, y)}`（COCO-18 編號）。人物偵測失敗時，改成整張圖當一個人再試一次。結果從 ComfyUI 的輸出資料夾讀 |
| `sam2_mask(img, pos, neg)` | SAM2 用正點、負點切出一塊，回傳布林遮罩 |
| `inpaint(img, mask, pos, neg, seed, denoise)` | 局部重畫：遮罩先擴大 9 像素再羽化，用目前的繪圖模型重畫，結果只貼回遮罩範圍 |
| `clean_mask(m, min_px)` | 遮罩整理：留最大一塊和超過 `min_px` 的塊，填洞，邊緣平滑 |

### 1-2. `parts`：找骨架、粗分層

`parts(hero, series)` → `split_figure(rgba, 提示詞, 資料夾, "fig")`：

1. 姿勢偵測拿到關節；`face_of` 拿到臉的位置和大小。
2. 用 SAM2 從關節點切：
   - 臉、頭髮：以臉為中心放幾個點，臉和頭髮互為負點；
   - 手臂：上臂和前臂加手**分兩次切**再合起來（一次切會停在手肘，手套留在身上）；
   - 腿：髖到膝、膝到踝；
   - 軀幹：脖子到髖中點上的三個點。
3. 每塊用 `clean_mask` 整理。手臂往外擴 7 像素吃掉自己的輪廓線（但不吃進腿）。
4. **武器**：不屬於任何部位、而且在「身體往外擴半個頭」範圍以外的部分，再用 SAM2 從它上面的五個點切一次；佔人物 2% 以上、離某隻手腕夠近才算武器，那隻手就是握武器的手（`weapon_grip`）。
5. 每個像素只歸一個部位，前面的先拿（臉、頭髮、右臂、左臂、武器、右腿、左腿），剩下的是軀幹。
6. **補畫軀幹被手臂擋住的地方**（局部重畫，提示詞加 `arms at sides`），手臂擺動時才不會露洞。腿後面不補（補過一次，畫出第二隻灰色的腿）。
7. 手臂再往軀幹裡長 9 像素，轉動時關節才蓋得住。
8. 寫出 `fig_<部位>.png`、`fig_overview.png`（彩色標出每個部位和關節點）、`fig_joints.json`。

接著：
- **`legacy_layers`**：合成三層 `layer_hair.png`、`layer_face.png`、`layer_body.png`，給沒有細部分層時的粗綁定用。
- **`eye_patch`**：有 `full_blink.png` 時，只留跟 `full.png` 不同的像素（閉起來的眼睛），存成 `eyes_closed.png` 和 `eyes.json`（範圍）。

`fig_joints.json` 是後面每一步都會讀的關節檔；姿勢偵測抓錯時要手動改這個檔（原本的另存一份）。

### 1-3. `mouths`：嘴型差分

1. 找臉，裁出頭部方框，放大到 768。
2. 嘴巴在臉的下三分之一：以（臉中心, 臉中心 + 0.3 臉高）為中心畫橢圓遮罩。
3. 每種嘴型各局部重畫一次（強度 0.92，種子 301 起）：

   | 檔名 | 提示詞重點 |
   |---|---|
   | `mouth_closed.png` | 閉嘴、微笑 |
   | `mouth_a.png` | 張大嘴（啊） |
   | `mouth_i.png` | 露齒（咿） |
   | `mouth_o.png` | 小圓嘴（喔） |

4. 結果縮回去貼回整張立繪，加上原本的透明度。
5. 寫 `mouth.json`：`face`（臉中心、臉高）和 `mouth_box`（嘴巴範圍）。綁定只用 `mouth_a.png` 在這個範圍裡的部分。

工作室可以選嘴型用哪個繪圖模型（`ART_CKPT`），要跟這張立繪原本的畫風一樣。

### 1-4. `scene`、`preview`

- **`scene`**：情境圖去背（`cutout.py`）、把人物後面的背景補畫出來、算深度、依深度切成 n 層（近的先切，遠的層在被擋住的地方用 OpenCV 補色）、人物再做一次粗分層（`sc_*`）。
- **`preview`**：不經過 Godot，用 Python 直接把粗分層的部位繞關節轉，做成 `preview_figure.gif`（60 格，含眨眼、嘴型、呼吸）；有情境圖時另做 `preview_scene.gif`（每層視差不同，加落葉）。

---

## 2. `Tools/art/see_through.py`

```
python Tools/art/see_through.py <角色> <服裝> [--res 1280] [--seed 42]
python Tools/art/see_through.py <角色> <服裝> --rebuild        不用 ComfyUI：從存下的原始輸出重排一次
```

用 See-through 模型（ComfyUI 節點 jtydhr88/ComfyUI-See-through）把一張圖拆成約二十三層：前髮、後髮、臉、左右眼白、虹膜、睫毛、眉毛、嘴、鼻、耳、脖子、上衣、手套、下著、襪子、鞋子、飾品、手持物品……被擋住的地方會補畫，每層有深度。每張約八分鐘。

### 函式呼叫流程

```
__main__
├─ --rebuild：讀 st_layers.json
│  ├─ to_plate(meta, src, out, crop, res)
│  ├─ fix_grip(hero, series, out)
│  └─ refine_leftover(hero, series, out)
└─ decompose(hero, series, res, seed)
   ├─ live_layers.src_dir → 讀 full.png，貼白底
   ├─ crop_box(src)                               裁到人物
   ├─ live_layers._tmp → comfy_gen.upload
   ├─ workflows.load("see_through") / fill
   ├─ comfy_gen.post("/prompt") → 每 3 秒 comfy_gen.get("/history")
   ├─ 從 ComfyUI 輸出資料夾複製 st_*.png，寫 st_layers.json
   ├─ to_plate(meta, src, out)                    貼回立繪畫布 → part_*.png、parts.json
   ├─ fix_grip(hero, series, out)                 關鍵姿勢的關節、握點
   │  └─ key_poses.POSES、W_、H_
   └─ refine_leftover(hero, series, out)          細分「其他」
      ├─ live_layers.flat
      └─ live_layers.sam2_mask                    帽子
   沒有臉 → decompose(hero, series, res, seed + 7)

raw_layers(meta, src)                             給 rig_parts.py 呼叫
```

### 2-1. 主流程 `decompose`

1. 立繪貼到白底（模型是用插畫訓練的）。
2. **`crop_box`**：裁到人物外框再往外留 4%（人物在畫面裡太小時，五官會被放到下巴）。
3. 送出 `see_through` 工作流程，每三秒印一次進度。失敗時丟出錯誤（附 ComfyUI 的訊息）。
4. 從 ComfyUI 輸出資料夾找 `<前綴>*_layers.json`（每層的檔名、位置、深度中位數），每層圖片複製成 `st/st_<名稱>.png`。
5. 在 `st_layers.json` 記下裁切範圍和解析度（`input`），之後才能貼回原位或重排。
6. 依序執行 `to_plate`、`fix_grip`、`refine_leftover`。
7. 命令列模式下，拆完沒有臉這一層就換種子（+7）再拆一次。

### 2-2. `to_plate`：貼回立繪的畫布

1. 每層照「裁切範圍＋模型把輸入縮放置中到 res×res」換算回立繪座標，貼到跟立繪一樣大的畫布。
2. 一層有 65% 以上落在人物外面，當成模型自己發明的（例如翅膀），丟掉。
3. 每層裁到人物輪廓外擴 2 像素（人物外面不會有東西被擋住，那裡多畫的一定會露出來）。
4. 照深度從遠到近排好。
5. **前髮**：模型畫了頭髮、立繪卻是別的東西的地方（雪乃的長髮蓋住整件褲裙），從前髮拿掉。
6. **從最前面往後**：每層在「自己是最前面」的地方換成立繪的顏色。這裡模型畫得跟立繪差很多的整塊（超過人物 0.5%），表示其實不是這一層，從這層拿掉（臉除外）。手持物品只留看得到的輪廓再外擴 4 像素（模型會把被擋住的弓弦畫成粗條）。
7. 立繪上有、但沒有任何一層蓋到的像素，放進 `part_leftover.png`（排最前面）。
8. 寫 `parts.json`（`size`、`order_back_to_front`）和 `_stack_vs_plate.jpg`（左立繪、右各層疊起來），印出疊起來跟立繪的平均差異。

### 2-3. `fix_grip`：關鍵姿勢的關節和握點

只對有 `pose.json` 的資料夾（關鍵姿勢，`key_poses.py` 畫的）：

- 關節缺值、或跟畫圖時的骨架差超過畫面高度 9%，改用畫圖時的骨架。
- 用拆出來的兩隻眼白算臉的位置（臉部偵測曾經抓到伸出去的袖子）。
- 脖子跑到臉的高度，改用畫圖時的骨架。
- 握點：手持物品那一層（沒有就用 `leftover`）離手腕最近的點。

### 2-4. `refine_leftover`：把「其他」再細分

模型叫不出名字的東西（芙蕾雅的寬簷帽、杖、長裙襬）會全部丟進 `leftover`，可能佔人物一半以上。`leftover` 超過人物 8% 時：

1. **武器**（還沒有 `objects` 時）：用比杖粗的筆刷做開運算，被抹掉的細長部分裡，最長、離手腕 1.2 臉高以內的那條就是武器。粗的武器（蕾娜的扳手）抹不掉，改找碰到手或肩膀的長條。握點更新到 `fig_joints.json`。
2. **帽子**（沒有帽子、或帽子不到人物 3% 時）：臉上方、左右 2.5 臉寬以內的部分，用 SAM2 從帽冠和兩端帽簷三點切。
3. **裙子**：髖部以下剩下的，加進 `bottomwear`。
4. 剩下的留在 `leftover`，新增的層插在 `leftover` 前面。

### 2-5. `raw_layers`

給 `rig_parts.py` 用：每層模型原本的輸出（還沒換成立繪顏色）貼回立繪畫布。手臂底下的衣服，模型自己補畫的版本比較可靠。

### 2-6. `--rebuild`

不用 ComfyUI，從 `st_layers.json` 和 ComfyUI 輸出資料夾裡的原始圖層重新做 `to_plate`、`fix_grip`、`refine_leftover`。**會覆蓋 `part_*.png`**：切零件和所有修補都要重做。改了上面這些規則想重來時用。

---

## 3. `Tools/art/rig_parts.py`：切零件

```
python Tools/art/rig_parts.py <角色> <服裝> [--weapon x,y;x,y|x,y;... --not x,y;...] [--match-plate]
```

在 `st/` 裡直接改寫：把整條手臂切成上臂、前臂、手，腿切成大腿、小腿、腳掌，把武器切出來補完整，再補畫會動的零件底下的身體。最後在 `parts.json` 寫入 `pivots`（關節位置）。

- `--weapon`：沿著武器描幾個點（`x,y;x,y`），幾條線用 `|` 分開（杖身一條、浮在杖頭的寶珠一個點）。不給就不切武器。
- `--not`：不是武器的點（SAM2 至少要一個負點，否則會出錯）。
- `--match-plate`：最後把每層看得到的地方換成立繪顏色（預設關閉）。

### 函式呼叫流程

```
__main__ → run(hero, series, weapon_pts, not_pts, weapon_lines, match_plate)
├─ load(folder)                                   parts.json、full.png、每層圖
├─ 1. 武器（有 --weapon 時）
│  ├─ live_layers.flat → live_layers.sam2_mask
│  ├─ weapon_corridor(lines, half, fig)           武器完整的範圍
│  ├─ paint_weapon(wa, 範圍 & ~看得到的, hero, size)
│  │  └─ workflows "inpaint" → comfy_gen.upload → heroine_j3.run_wf（提示詞用 key_poses.HOLD）
│  ├─ extend_down(wa, hidden_w, corridor)         直的武器接到腳底
│  └─ give_to_body(arrs, 舊武器層的其他東西, names)
├─ 2. 手臂（每一邊）
│  ├─ cut_arm(handwear, 肩, 腕)
│  │  └─ geodesic(mask, start) × 2
│  └─ give_to_body(arrs, 超過肩膀的部分, names)
├─ 2b. split_legs(folder, arrs, meta, joints, pivots)
│  └─ key_poses.POSES（關鍵姿勢時）
├─ adopt_crumbs(arrs)
├─ 3. 握點
│  ├─ carry_across(objects, 手擋住的地方)
│  └─ weapon_tip(武器, 握點)
├─ 4. 會動的零件底下
│  ├─ see_through.raw_layers(st_layers.json, src)
│  ├─ order_for_motion(src, arrs, meta, raw)
│  │  ├─ is_leg、moving
│  │  └─ in_palette(raw, layer, under)
│  ├─ paint_hidden(src, arrs, meta, holes, hero, series)   洞夠大時
│  │  └─ live_layers.flat → heroine_j3.prompt_for → live_layers.inpaint
│  ├─ 上臂貼身的帶子：cv2.inpaint
│  └─ 手旁邊的小洞：cv2.inpaint
├─ front_to_plate(meta, arrs, src)                只有 --match-plate
└─ save(st, meta, arrs)、刪掉舊的整條手臂檔
```

### 3-1. 武器（有 `--weapon` 時）

1. SAM2 在立繪上沿描點切，只留描線附近（寬 64 像素）的部分（SAM2 會流進同色的深色裙襬）。
2. 用距離變換估武器的半寬；沿描線、照這個寬度的立繪像素也算武器（SAM2 在同色布料上會跟丟）。
3. **`weapon_corridor`**：武器完整的範圍。描線照武器寬度畫粗；最長那條如果往下走，延伸到腳底（杖的下半截常被裙子擋住）。
4. **`paint_weapon`**：範圍裡立繪沒顯示的部分，在**只有武器的灰底畫布**上局部重畫（提示詞用角色的 `hold`），模型才會接著畫武器，而不是畫前面的裙子。畫成灰底色的不算。
5. **`extend_down`**：直的武器還是沒到腳底時，重複它最下面一段，順著斜率一列一列往下接。
6. 補畫的部分只留在人物輪廓內，而且要跟武器連在一起（不連的碎塊轉動時會留在原地）。
7. 原本的 `objects` 層裡不是這把武器的東西（例如被當成武器的袖子）：碰到某隻手臂就給那隻手臂，否則給最近的身體層。
8. 武器的像素和它的柔邊從其他層拿掉。
9. 看得到的武器存成 `objects`，補畫的部分存成 `objects-back`（排最後面：靜止時被帽簷、裙子擋住，跟立繪一樣；武器轉動時才露出來）。

### 3-2. 手臂 `cut_arm`

對 `handwear-l`、`handwear-r`（See-through 的「手套」層，其實是整條手臂）：

1. 先用 31×31 的閉運算把被袖子切斷的部分接起來。
2. **`geodesic`**：從肩膀沿手臂內部走的距離（四鄰的廣度優先搜尋）。
3. 手的末端：含手腕那一塊、離手腕 110 像素內，走最遠的點（垂下的布可能比手還低）。
4. 從末端沿距離圖走回肩膀，得到一條路徑；**手肘在路徑一半、手腕在 0.8** 的位置。
5. 每個像素歸給最近的骨頭（肩–肘、肘–腕、腕–末端）；每段在關節處多一個圓形的蓋子（半徑＝手臂寬 + 3），轉動時不會裂開。
6. 上臂超過肩膀、往身體那一側的部分還給身體（不然轉肩膀時會掃過脖子）。
7. 三段插在原本整條手臂的位置，靜止時跟原本一樣。

關節存進 `pivots`：`shoulder_*`、`elbow_*`、`wrist_*`。

### 3-3. 腿 `split_legs`

`legwear`（See-through 把兩條腿放在同一層）和 `footwear`：

1. 關節：關鍵姿勢用畫圖時的骨架；其他用 `fig_joints.json` 的膝蓋、腳踝（沒有就不切，印出提示）。髖用立繪上找到的。
2. 每個像素歸給最近的骨頭（左右的髖–膝、膝–踝），膝蓋和腳踝處加圓形蓋子。
3. 沒有鞋子層時，小腿超過腳踝的部分切成腳掌；有鞋子層時，每隻鞋給比較近的腳踝。
4. `pivots` 加上 `hip_*`、`knee_*`、`ankle_*`、`foot_*`（腳尖：腳掌離腳踝最遠的點）、`waist`（兩髖中點）。
5. **腰**：上衣往下延伸約 25 像素藏在裙子後面（身體前傾時不會露縫）；另外做 `hidden-pelvis`：裙子往上延伸到上衣下緣後面 45 像素，上半身傾斜時露出來的是裙子。
6. 刪掉舊的 `part_legwear.png`、`part_footwear.png`。

### 3-4. 小碎塊與握點

- **`adopt_crumbs`**：身體層裡黏在會動零件旁邊的小塊（800 像素以下、三成以上貼著零件）跟零件一起動（例如拆層留在衣服裡的手指）。
- **握點**：碰到武器最多的那隻手；接觸點的平均位置是握點。**`carry_across`** 把手擋住的那段武器補起來：每一列（或行）複製最近的、沒被擋住的那一列，照武器中線的走向平移（直接用畫好的，不用 AI 猜）。**`weapon_tip`**：武器兩端裡周圍像素比較多的那端（杖頭寶珠、扳手頭）。`pivots.grip = {hand, point, tip}`。武器排在握它的手正後面。

### 3-5. 會動的零件底下的身體

1. **`order_for_motion`**：重排順序成「`objects-back`、身體各層、`hidden`、腿、裙子、手臂和武器、前髮」。會動的零件在靜止時看得到的地方換成立繪顏色；身體各層在零件底下的部分，衣服改用模型自己補畫的版本（顏色要接近這層看得到的顏色，`in_palette`），頭髮和沒有補畫的地方清空，留給 `hidden`。
2. **要補的洞**：零件底下、拆層原本有身體（或身體輪廓的小縫）、現在沒有身體層蓋到的地方；腿底下在身體大輪廓（61×61 閉運算）內的也算（站在裙子開衩裡的腿後面是裙子內側）。
3. **`paint_hidden`**：不會動的層合起來，在洞裡局部重畫（排除手、武器），畫成背景色的不算，存成 `hidden` 層，排在第一個會動零件前面。
4. **上臂貼著身體的那條帶子**：不用 AI（貼著皮膚畫，AI 會畫出手臂的殘影），用 OpenCV 從旁邊的身體接著補。
5. **手放在衣服上留下的小洞**：同樣用 OpenCV 從旁邊補。A 字站姿的手臂離身體夠遠，手臂和身體之間的空隙保持透明。
6. 存檔：每層 `part_*.png`、`parts.json`（含 `pivots`）；刪掉舊的整條手臂檔。

**要用到的 ComfyUI**：補畫身體底下（幾乎每張都會用到）和補畫武器。
