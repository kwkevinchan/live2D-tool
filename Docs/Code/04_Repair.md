# 修：輪廓、修補、AI 重畫、放回去、多角度參考圖

每個物件都要做到完整、乾淨、符合名字。兩條路：

- **修補**：`outline.py`（先輪廓）→ `object_fix.py --outline`（照輪廓上色）→ `outline.py --check`（檢查完整）。還有很多不用 AI 的修補模式。
- **AI 重畫**：`object_edit.py`（請 Mage-Flow 照指令把整個物件重畫）→ `object_place.py`（放回拆層裡）。研究見 `Docs/Design/22c_Object_Generation.md`：頭髮、帽子、杖、裙子用重畫比較好，四肢還是修補的好。

被擋住的部分不知道長什麼樣子時，用 `multiview.py` 生成背面、側面當參考。

所有工具都只改 `st/` 裡的檔案，原檔第一次改之前會備份到 `st/_orig/`。

---

## 1. 輪廓（`Tools/art/outline.py`）

```
python Tools/art/outline.py <角色> <服裝> lineart                     抽一次立繪的線稿（要 ComfyUI）→ st/lineart.png
python Tools/art/outline.py <角色> <服裝> <圖層> [選項]               抽輪廓、補線、刪輪廓外的
python Tools/art/outline.py <角色> <服裝> <圖層> --check [--file <候選>]   檢查是否完整
```

### 1-0. 函式呼叫流程

```
main()
├─ <圖層> 是 lineart → make_lineart(ld, st)
│  └─ workflows "lineart" → comfy_gen.upload → heroine_j3.run_wf → st/lineart.png
├─ --check
│  └─ object_check.whole(alpha)                   一塊？浮動？洞？ → <圖層>_check.json
└─ 一般
   ├─ 讀／存 marks.json
   ├─ inx_rig.load_joints（補 pivots 沒有的關節）
   ├─ poly_mask（--erase-poly）、--erase-rgb
   ├─ object_fix.clean(part, erase)
   ├─ 找線：luma、st/lineart.png
   ├─ edges(on) → 畫出來的邊／切開的邊
   ├─ 被線切開的區塊編號（--drop）
   ├─ object_fix.reach_mask(part, ...)            四肢的範圍（武器 → bridges）
   ├─ 每段切開的邊
   │  ├─ far_pair(端點)
   │  ├─ tangent(端點, 畫出來的邊) × 2
   │  ├─ 四肢：ray_until(...) × 2 → poly_mask
   │  └─ 其他：intersect(...) → poly_mask
   ├─ --line 手畫的線 → 填滿
   ├─ 形狀：填滿、取最大一塊＋凸包裡的小塊
   ├─ 成對的四肢：object_fix.mirrored(另一邊) 比對
   └─ 寫 _lines / _shape / _fill / _cut.png、.json、.jpg
```

### 1-1. 步驟

1. **讀圖層**：`st/part_<圖層>.png`（`--src orig` 讀 `st/_orig/` 的原檔）。先套用手動標記：
   - `--erase-poly "x,y x,y x,y|..."`：刪掉多邊形裡的；
   - `--erase-rgb "r,g,b:容許差[:all]"`：刪掉邊緣 6 像素內的這個顏色（頭髮殘邊），加 `:all` 是整層都刪；
   - `--erase x0,y0,x1,y1;...`：刪掉方框裡的；
   - 接著 `object_fix.clean`：留主體和附近的塊，遠處的碎點刪掉。
2. **找線**：亮度低於 80（`LINE_Y`）的像素，加上立繪線稿（`st/lineart.png`，比 70 亮的是線）落在這層內縮 1 像素以內的部分（被擋住的地方，立繪上的線是前面那個東西的，不算）。8 像素以下的小點不算線。
   - 邊緣 2 像素內有線＝**畫出來的邊**；沒有＝**切開的邊**（被擋住或被拆層切斷）。
3. **被線切開的區塊**：被線跟主體分開、80 像素以上的區塊編號列出來；`--drop 2,3` 刪掉這些編號（例如黏在手臂上的披風——程式分不出披風和手套）。
4. **補線**：每段切開的邊（至少 12 像素）取最遠的兩個端點，用端點附近 16 像素的畫出來的邊算方向（主成分分析），往外延伸：
   - **四肢**：沿骨頭的範圍（`object_fix.reach_mask`）走到盡頭再橫接，兩邊延伸一樣長，不能超出範圍；兩條線往內收時直接橫接（是尖端，不是四肢）。
   - **武器**：把各塊用跟武器一樣粗的線接起來（`object_fix.bridges`）。
   - **其他**：兩條射線的交點；沒有交點就直接橫接。
   - `--line "x,y x,y ...|..."`：手畫被擋住的邊，照畫的接。
   - `--no-grow`：形狀本來就完整（臉），只補洞。
5. **形狀**：補好的輪廓填滿，取最大一塊，加上中心在它凸包裡的小塊（杖頭的寶珠）。形狀外的都是噪點，刪掉。
6. **成對的四肢**：拿另一邊翻過來疊在這邊的骨頭上比，形狀超過 30% 在另一邊（外擴 10 像素）外面時警告（大概黏到別的東西）。

手動標記存在 `st/outline/marks.json`：有給就存，沒給就讀回上次的。

### 1-2. 產出（`st/outline/`）

| 檔案 | 內容 |
|---|---|
| `<圖層>_lines.png` | 補好的輪廓（透明底黑線），上色時當線稿 |
| `<圖層>_shape.png` | 輪廓裡面 |
| `<圖層>_fill.png` | 輪廓裡面但還沒有顏色的（要補的） |
| `<圖層>_cut.png` | 刪完噪點的圖層 |
| `<圖層>.jpg` | 對照圖：原圖層 ｜ 線（綠＝畫出來的邊、紅＝切開的邊、黃＝刪掉的，加區塊編號）｜ 補好的（藍＝新補的線、洋紅＝要上色的）｜ 線稿 |
| `<圖層>.json` | 數字：畫出來的邊佔多少、補了哪些、區塊、要上色多少像素、警告 |

### 1-3. `--check`

拿 `_shape.png` 比對圖層（或 `--file` 指定的候選）：一整塊（浮在凸包裡的不算斷）、輪廓外（外擴 2 像素）沒有像素、輪廓內沒顏色的不超過 2%，三項都過才算完整。寫 `<圖層>_check.json`，沒過結束代碼 1。

---

## 2. 修補（`Tools/art/object_fix.py`）

一支工具，很多模式。每次只用一種模式。

### 2-0. 函式呼叫流程

`main()` 照選項分到不同的函式，先符合的先做：

```
main()
├─ --apply <種子>   → 複製候選到 part_<圖層>.png（原檔先備份），結束
├─ 讀 parts.json 的 pivots，inx_rig.load_joints 補上缺的關節
├─ --make-face / --split-lr / --drop-part → face_ops(a, ld, st, meta)
├─ --carve / --split-hair                 → carve_ops(a, ld, st, meta)
│                                            ├─ _new_layer(...)  寫新層、插進順序
│                                            └─ outline.poly_mask（--carve-poly）
├─ clean(part, erase)
├─ --mirror → mirrored(part, st, pv, size)
│             └─ bone(另一邊)、bone(這一邊)
├─ --flat        → flat_fill(a, ld, st, meta)       （--from-view 照 multiview.square 的算法放回）
├─ --split-front → split_front(a, ld, st, meta)
├─ --sort-hair   → sort_hair(a, ld, st, meta)
├─ --move-hair   → move_hair(a, ld, st, meta)
├─ --drop-specks → 就地刪碎點，結束
└─ AI 補畫
   ├─ --outline：讀 outline/ 的 _cut、_shape、_lines
   ├─ 要補哪裡
   │  ├─ --grow auto → reach_mask(part, alpha, pv, shape)
   │  │                └─ 武器：bridges(on)
   │  ├─ --grow hull → hull(on)
   │  └─ --grow none / grey、--mirror、--only
   ├─ 裁出來、放大、要補的先填最近的顏色
   ├─ 設 ART_LORA = key_poses.LORA[角色]、ART_LORA_TRIGGER
   ├─ 每個種子
   │  ├─ 有線稿：inpaint_lines(j3, canvas, mask, 線稿, ...)
   │  │          └─ heroine_j3._wf_common(..., "inpaint_lines") → comfy_gen.upload × 3 → heroine_j3.run_wf
   │  └─ 沒線稿：heroine_j3.img2img(canvas, ..., mask)
   └─ 寫 fix/<圖層>_<種子>.png、fix/<圖層>.jpg
```

### 2-1. AI 補畫（預設）

```
python Tools/art/object_fix.py <角色> <服裝> <圖層> [--outline] [--grow auto|none|hull|grey] [--mirror]
                               [--seeds 1,2,3] [--denoise 0.8] [--only x0,y0,x1,y1] [--desc "..."] [--dry]
python Tools/art/object_fix.py <角色> <服裝> <圖層> --apply <種子>
```

1. **清理**：`clean`（留主體和附近 12 像素內的塊，或大於最大塊 5% 的），`--erase` 方框刪掉。
2. **要補哪裡**：
   - `--outline`：`outline.py` 算好的形狀裡、沒顏色的地方。上色時照它的線稿（`inpaint_lines` 工作流程），形狀裡要補的全部用新顏色，形狀外一律透明。
   - `--grow auto`（預設）：四肢用骨頭的範圍（`reach_mask`：沿骨頭、寬度取這層到骨頭距離的中位數 ×1.6，從關節延伸到下一個關節再多一點）；武器用 `bridges`；其他用「前面的層擋住、離自己邊緣 25 像素內」的地方。都會再加上輪廓裡的洞。
   - `--grow none`：只補輪廓裡的洞。
   - `--grow hull`：只補自己幾塊之間的空隙（被握著的杖切成兩半的手）。
   - `--grow grey`：重畫裡面灰色、褪色的污漬（飽和度低於 `--grey-sat`）。
   - `--mirror`：拿另一邊翻過來、沿骨頭拉長（寬度不變）、轉到這邊的骨頭上（`mirrored`），再輕輕重畫一遍和外圈 6 像素（強度預設 0.4）。單純翻過來的版本存成候選 0。
   - `--only`：只補方框裡的。
3. **畫**：物件自己放在灰底上，裁出來放大到長邊 1024。強度低於 0.95 時，要補的地方先填最近的顏色（不然 AI 會照著灰底畫）。用設定檔的繪圖模型加角色專屬微調（強度 0.8），提示詞「單一個 <物件描述>」（`DESC` 表；武器用角色的 `hold`；`--desc` 可以自己給）。畫成灰底色的不算（`--outline` 例外）。
4. **產出**：每個種子一張候選 `st/fix/<圖層>_<種子>.png`，加上對照圖 `st/fix/<圖層>.jpg`（原本 ｜ 要補的（洋紅）｜ 每個候選）。`--dry` 只出對照圖，不用 ComfyUI。
5. **`--apply <種子>`**：把候選換成正式的圖層（原檔先備份）。

### 2-2. 不用 AI 的模式

| 選項 | 做什麼 |
|---|---|
| `--flat` | 輪廓裡被前面的層擋住、跟立繪顏色不同、或空著的地方，填這層看得到的顏色的中位數（額頭在瀏海底下就是一片皮膚）。別的層也顯示立繪的地方算別人的。離自己顏色很遠的大塊（芙蕾雅額頭上的帽帶）拿出來存成 `st/fix/<圖層>_moved.png`。結果存成候選 8 |
| `--flat --nearest` | 每個像素取最近一個看得到的顏色，而不是一個中位數（帽簷：旁邊是紅的取紅、上面是黑的取黑）；灰白的殘影不當來源 |
| `--flat --nearest --palette "r,g,b;r,g,b"` | 只能用這幾種顏色（不會拉出條紋） |
| `--flat --from-view <圖>[:flip] [--figure <圖>]` | 顏色從另一個角度的參考圖取（`multiview.py` 的輸出，照它的縮放放回立繪上）；背面圖要加 `:flip`（從前面看身體後面的頭髮，等於背面圖左右翻轉） |
| `--split-front` | 這層在臉和前髮上面、顯示立繪的部分，切成 `<圖層>-front`，排在前髮後面（帽冠和帽帶在瀏海前，帽簷在頭後面） |
| `--sort-hair` | 從雜物層把頭髮分出來：每一塊大多接近前髮的顏色（或三成以上接近而且碰到頭髮層）就是頭髮，移到 `side_hair` |
| `--move-hair [--ycut Y] [--palette ...] [--keep-holes]` | 衣服層搶走了疊在同色布料上的頭髮：線稿之間、15 像素內有頭髮灰藍陰影、在 Y 以上的紅色區塊移到 `side_hair`；留下的洞填最近的顏色（或只用 `--palette` 的顏色），`--keep-holes` 則留空 |
| `--carve <新名字> [--carve-rgb "r,g,b:容許差"] [--carve-box ...] [--carve-poly ...] [--carve-front] [--carve-copy]` | 從這層切一塊成新的一層（披風、胸、馬尾、呆毛、髮帶、耳環、袖子、流蘇……綁定時依名字決定怎麼擺動）。預設排在原層後面，`--carve-front` 排前面；`--carve-copy` 是複製不切（胸跟著彈，下面的上衣保持完整，邊緣不會裂） |
| `--split-hair` | 前髮 → 瀏海＋左右側髮（`side_lock-*`：臉中心以下、離臉的中線超過 0.3 個臉高的部分）；後髮 → 後髮＋髮尾（`hair_ends`：脖子再往下 0.35 個臉高以下） |
| `--make-face` | 拆層沒拆出臉：在臉的橢圓範圍裡取立繪的膚色，眼睛和嘴的洞填膚色，做成 `face`，排在眼睛前面 |
| `--split-lr` | 兩隻眼共用一層：從臉中間切成 `-l`、`-r`；只有一隻時，另一隻以兩個虹膜的中間為軸翻過去 |
| `--drop-part` | 從 `parts.json` 拿掉拆層模型發明的層（檔案移到 `st/_orig/`） |
| `--drop-specks <像素>` | 刪掉小於這個大小的分離碎點 |

### 2-3. 給其他工具用的函式

| 函式 | 做什麼 |
|---|---|
| `kind_of(part)` | 去掉 `-l`、`-r` 的種類名 |
| `reach_mask(part, alpha, pivots, shape)` | 四肢、武器完整時該蓋到的範圍；沒有關節時回傳 `None` |
| `bridges(on)` | 把各塊在最近的點用線接起來（最小生成樹），線粗＝距離變換第 75 百分位 ×2 |
| `bone(part, pivots)` | 這個零件的骨頭兩端 |
| `mirrored(part, st, pivots, size)` | 另一邊翻過來疊到這邊的骨頭上 |
| `clean(a, erase)` | 留主體和附近的塊 |
| `REACH` | 每種四肢零件從哪個關節到哪個關節、多延伸多少 |

---

## 3. AI 重畫一個物件（`Tools/art/object_edit.py`）

```
python Tools/art/object_edit.py <角色> <服裝> <圖層> --instr "<英文指令>" [--seeds 1,2] [--mask <圖層>,...]
                                [--src orig] [--pad 0.25] [--extra <參考圖>,...] [--neg "..."] [--tag e]
```

用 Mage-Flow-Edit-Turbo（照指令修圖的模型，四步；`UNET`、`CLIP`、`VAE` 三個模型檔名寫在程式開頭）。要 ComfyUI。

```
main()
├─ 範圍：這層（或 --mask）的外框＋pad
├─ 參考圖：立繪貼白底、裁切、放大 → comfy_gen.upload（--extra 也上傳）
├─ 清掉 ART_LORA
├─ 每個種子
│  ├─ graph(instr, neg, seed, refs, W, H)       組出工作流程
│  ├─ heroine_j3.run_wf(...)
│  ├─ unwhite(rgb)                               去白底
│  └─ 放回立繪座標 → gen/<圖層>_<tag><種子>.png
└─ 對照圖 gen/<圖層>_<tag>.jpg
```

1. **範圍**：這層（或 `--mask` 指定的幾層）的外框，四邊各往外加 `--pad`（預設 25%），寬高對齊 16。
2. **參考圖**：立繪貼白底，裁成這個範圍（整個人物都在裡面，模型才知道這個物件是什麼的一部分）；小於 1024 時放大。`--extra` 可以再給參考圖（例如背面圖）。
3. **重畫**：送出 `graph(...)`（ComfyUI 範本攤平成的工作流程），輸出跟參考圖一樣大（修圖模型會保持構圖，所以物件會畫在立繪上的同一個位置）。執行前清掉 `ART_LORA`。
4. **去背**：接近白色、而且連到邊框的區域變透明（`unwhite`）。結果放回立繪座標。
5. **產出**（`st/gen/`）：`<圖層>_<tag><種子>.png`（跟立繪一樣大）、`<圖層>_<tag>.jpg`（參考圖 ｜ 每個種子的原始輸出和去背結果）。

經驗：大約一半照指令畫，要跑三四個種子；沒碰到的地方也會稍微變；只有白底、沒有透明。

---

## 4. 放回拆層（`Tools/art/object_place.py`）

```
python Tools/art/object_place.py <角色> <服裝> <st/gen/...png> --as <圖層>[,<圖層>...] [選項]
```

把 `object_edit.py` 畫的物件換成拆層裡的一層（原檔先備份）。

```
main()
├─ --clip-above、--no-skin                      先刪
├─ --fit → fit(gen, target[, turns, shift])     （--wide 時正反各試一次）
│  ├─ score(...) × 粗搜、細搜
│  │  └─ moved(sc, dx, dy, rot)
│  └─ moved(..., gen)                           套用找到的
├─ --bones → object_fix.bone(part, pv)、object_fix.seg_dist(...)   每個像素給最近的骨頭
└─ 每個目標層
   ├─ --merge：立繪看得到的地方換回立繪像素
   ├─ keep(st, name)                            備份原檔
   ├─ --front：切出 <圖層>-front、keep、插進順序
   └─ 存 part_<圖層>.png
```

| 選項 | 做什麼 |
|---|---|
| （無） | 直接用 AI 畫的取代 |
| `--fit [圖層,...]` | 先對位：移動、縮放、旋轉 AI 畫的，讓它跟立繪上這個東西（預設是 `--as` 的那幾層）重疊最多（交集／聯集）。先粗搜（±40 像素、0.85～1.15 倍、±12 度），再細搜 |
| `--fit --wide` | 搜更大範圍（±40 度、±100 像素），也試左右翻轉（弓畫成反方向彎的） |
| `--bones` | 切給好幾個四肢零件（`--as upperarm-r,forearm-r,hand-r`）：每個像素給最近的骨頭 |
| `--front [圖層,...]` | 穿過人物的東西：在這些層（預設臉和前髮）上面、而且立繪上確實是這個東西的部分，切成 `<圖層>-front`，排在前髮後面 |
| `--merge` | 立繪看得到這層的地方用立繪的像素，其他用 AI 的；後面的層顯示立繪的地方（裙子開衩裡的腿）這層要透明。**這是往「像原圖」拉的做法，Project_Split 第 3 節列為要改掉的** |
| `--clip-above Y` | 刪掉 Y 以上（裙子連帶畫到的上衣） |
| `--no-skin` | 刪掉膚色像素（從裙子開衩看到的腿） |

---

## 5. 多角度參考圖（`Tools/art/multiview.py`）

```
<mvadapter python> Tools/art/multiview.py <立繪.png> <輸出資料夾> --lora <角色> [--prompt "..."] [--seed 7]
```

用 MV-Adapter 從一張立繪生成正面、右側、背面、左側四個角度（768×768），用我們自己的繪圖模型加角色專屬微調，所以長相保持一致。在 MV-Adapter 自己的 Python 環境執行（它的 torch 借 ComfyUI 的），不經過 ComfyUI，但會吃滿顯示卡。

```
__main__ → run(plate, out, lora, prompt, seed)
├─ pipeline(lora)                               載入模型、MV-Adapter、角色微調
├─ camera_c2w([0, 90, 180, 270] - 90)           相機
├─ get_plucker_embeds_from_cameras_ortho(...)   相機條件（從 MV-Adapter 的 geometry.py 用 _load 單獨載入）
├─ square(Image.open(plate))                    參考圖
├─ pipe(...)                                    一次畫四個角度
└─ 存 view_*.png、views.jpg
```

- **`square(plate)`**：人物裁出來，放大到正方形的 90%，置中在灰底上（MV-Adapter 的前處理）。`object_fix --from-view` 照同樣的算法放回立繪。
- **`pipeline(lora)`**：載入繪圖模型、MV-Adapter、角色微調（強度預設 0.3，環境變數 `MV_LORA_SCALE`；太高每個角度都畫成正面）。整個放上顯示卡（分批載入會壞），一次四個角度（六個會超過 16 GB）。
- **`camera_c2w`**：水平一圈的相機矩陣（取代 MV-Adapter 需要 3D 套件的那支函式）。
- 產出：`reference.png`、`view_000.png`／`view_090.png`／`view_180.png`／`view_270.png`、`views.jpg`。

用途：看立繪擋住的地方（後髮、帽子後緣、側髮）長什麼樣子；不拿來取代看得到的地方。武器要另外跑。
