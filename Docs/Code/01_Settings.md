# 設定與共用模組

每支工具都會用到的東西：設定檔、跟 ComfyUI 溝通、工作流程檔、提示詞和角色資料。

---

## 1. 設定檔（`Tools/art/config.py`）

讀兩種設定檔，給其他程式用：

```python
import config as C
C.WORK, C.PLATES, C.COMFY_URL, C.GODOT, C.CKPT, C.MV["python"]
C.plate_dir("freya", "C")            # 這套服裝的立繪資料夾
C.CHARACTERS["freya"]["lora"]        # 角色資料
C.character("freya")                 # 同上，沒有這個角色時丟出 KeyError
```

### 1-1. `live2d.toml`（專案根目錄）

| 區段與鍵 | 程式裡的名字 | 環境變數（優先） | 預設 |
|---|---|---|---|
| `[paths] work` | `WORK` | `ART_WORK` | `<專案>/art_work` |
| `[paths] plates` | `PLATES` | `ART_PLATES` | `<專案>/plates` |
| `[paths] godot` | `GODOT` | `GODOT` | 空 |
| `[comfyui] url` | `COMFY_URL` | `COMFY_URL` | `http://127.0.0.1:8188` |
| `[comfyui] dir` | `COMFY_DIR` | `COMFY_DIR` | 空（工作室的「啟動 ComfyUI」用） |
| `[comfyui] output` | `COMFY_OUT` | | 空（拆層、姿勢偵測從這裡讀 ComfyUI 存的檔） |
| `[models] checkpoint` | `CKPT` | `ART_CKPT` | `waiIllustriousSDXL_v170.safetensors` |
| `[models] dir` | `MODELS` | | 空（多角度參考圖直接讀模型檔） |
| `[mvadapter] python / repo / configs` | `MV` | | |

- `LIVE2D_CONFIG` 可以指定另一個設定檔。
- 路徑會展開 `~` 和環境變數，再正規化。

### 1-2. `characters/<角色>.toml`

每個角色一份，讀進 `CHARACTERS[<id>]`（`id` 沒寫就用檔名）。

| 鍵 | 用途 | 誰在用 |
|---|---|---|
| `id`、`name` | 英文代號、中文名 | （工作室目前沒讀，見總覽「已知問題」） |
| `age` | 年齡，寫進提示詞的「N years old」；一律成年 | `heroine_j3.prompt_for` |
| `look` | 外觀描述 | 提示詞 |
| `weapon` | 立繪上武器的畫法 | `heroine_j3.plate_prompt` |
| `hold` | 武器的白話描述 | `key_poses`、`rig_parts.paint_weapon`、`object_fix`（重畫武器時） |
| `lora`、`trigger` | 角色專屬微調的檔名、觸發詞 | `key_poses.LORA`、`object_fix` |
| `neg` | 這個角色額外的排除詞 | `heroine_j3.hero_neg` |
| `[outfits."<服裝>"] outfit / scene / scene_pose` | 每套服裝的描述、情境圖的背景和姿勢 | `heroine_j3.OUTFITS` |

主設計的服裝代號是 `-`。

### 1-3. `plate_dir(hero, series)`

立繪所在的資料夾：主設計是 `<plates>/<角色>`，其他服裝是 `<plates>/<角色>/skins/<服裝>`。裡面要有 `full.png`（去背的立繪），可以有 `full_blink.png`（閉眼）和 `scene.jpg`（情境圖）。

關鍵姿勢資料夾（`pose_*`）的立繪不在這裡，而在工作資料夾自己裡面；`live_layers.src_dir` 負責分辨（見 [02_Split.md](02_Split.md)）。

---

## 2. ComfyUI 連線（`Tools/art/comfy_gen.py`）

所有工具都透過這支跟 ComfyUI 溝通。它本身也可以當指令用（文生圖、圖生圖），但這條流程只用它的函式。

| 函式 | 做什麼 |
|---|---|
| `upload(path)` | 把圖片上傳到 ComfyUI（`/upload/image`，覆蓋同名檔），回傳 ComfyUI 那邊的檔名 |
| `post(path, data)` | 送出請求。送工作（`/prompt`）時先經過 `adapt_workflow`，把提示詞改成目前繪圖模型看得懂的寫法 |
| `get(path)` | 讀 ComfyUI 的回應（工作紀錄、圖片） |
| `run(prompt, seed, w, h, init, denoise)` | 指令模式用：送一張文生圖或圖生圖，等它畫完，回傳圖片 |

### 2-1. 提示詞自動改寫

- **`family(ckpt)`**：檔名含 `waiIllustrious`、`illustrious`、`noob`、`hassaku`、`nova` 的是 Illustrious 系列，其餘當成 Pony 系列。
- **`adapt(text, negative)`**：Pony 系列原樣不動。Illustrious 系列會拿掉 Pony 的品質標籤（`score_9`……、`source_*`），把分級詞換成 Illustrious 的（`rating_safe` → `general`），也拿掉 `lineart` 這類描述線條的字（Illustrious 會照字面畫成黑白線稿），最前面再加上 Illustrious 的品質詞或排除詞。
- **`adapt_workflow(wf)`**：對一整個工作流程做上面的改寫。接到採樣器 `negative` 的文字節點當排除詞，其他當正面提示詞；模型載入節點一律換成 `CKPT`。有存音訊節點的工作流程不動（那是音樂模型）。
- **`add_lora(wf)`**：環境變數 `ART_LORA="<檔名>:<強度>"` 有設定時，在模型後面插入角色專屬微調（節點編號 90），把所有接到模型的線改接到它；`ART_LORA_TRIGGER` 有設定時，把觸發詞加在「正面提示詞」最前面。工作流程裡已經有微調節點就不再加。

**注意**：`ART_LORA` 是環境變數，設了之後同一個程序裡每個工作都會被加上微調。用 Mage-Flow 重畫物件前要先清掉（`object_edit.py` 會自己 `pop`）。

---

## 3. 工作流程檔（`Tools/art/workflows.py`、`Tools/art/workflows/*.json`）

每個工作流程是一個 ComfyUI「API 格式」的 JSON。工具只照**節點標題**填入會變的值（提示詞、圖片、種子、大小），所以可以把檔案拖進 ComfyUI 網頁調整、存回來，工具就照新的跑。

| 函式 | 做什麼 |
|---|---|
| `load(name)` | 讀 `workflows/<name>.json`；檔案不存在就先寫出預設的 |
| `fill(wf, {節點標題: {輸入: 值}})` | 填值；找不到標題時丟出 `KeyError` |
| `node_id(wf, title)` | 標題對應的節點編號 |
| `write_defaults(force)` | 寫出預設檔（`python Tools/art/workflows.py [--force]`；不加 `--force` 時保留已經改過的檔） |

| 工作流程 | 用途 | 會被填的節點標題 |
|---|---|---|
| `txt2img` | 文生圖 | 模型、正面提示詞、排除詞、畫布、採樣、存圖 |
| `img2img` | 圖生圖 | ＋輸入圖 |
| `inpaint` | 局部重畫（只畫遮罩裡） | ＋遮罩 |
| `inpaint_lines` | 局部重畫，照線稿畫（萬用控制模型 `xinsir_union_promax_sdxl` 的線稿模式，強度 0.8、作用到 80% 步數；線稿是黑底白線） | ＋線稿圖 |
| `lineart` | 抽出立繪的線稿 | 輸入圖、存圖 |
| `pose` | 姿勢偵測（DWPose），存關節點 JSON | 輸入圖、骨架、存關節 |
| `sam2` | 用正負點切出一塊（SAM2） | 輸入圖、分割（`coordinates_positive`、`coordinates_negative`） |
| `see_through` | 拆圖層（See-through），存 PSD 和每層圖片 | 輸入圖、分層、深度、存 PSD |
| `depth` | 深度圖（Depth Anything V2） | 輸入圖 |
| `wan_i2v` | 圖生影片（Wan 2.2），這條流程目前沒用 | |

預設檔裡的模型名稱是舊的 Pony 模型，但送出時 `adapt_workflow` 會換成設定檔的 `CKPT`。

---

## 4. 提示詞與送工作（`Tools/art/heroine_j3.py`）

原本是 towerD 畫角色立繪的工具（立繪、表情、情境圖），這條流程只用到其中幾個函式：

| 函式 | 做什麼 | 誰在用 |
|---|---|---|
| `prompt_for(hero, series, extra)` | 「1girl, solo, 年齡, 外觀, 服裝, extra」。Pony 系列用一長串成年描述，Illustrious 系列只寫「N years old」 | 嘴型、補畫身體、拆層補救 |
| `neg_base()` | 共用排除詞（內容界線：不能是小孩、不能裸露）；依模型系列選一套 | 所有局部重畫 |
| `hero_neg(pos)` | 從提示詞認出是哪個角色，加上她的 `neg` | `txt2img`、`img2img` |
| `run_wf(wf)` | 送出一個工作流程，等到完成，回傳第一張存下的圖（RGB）；失敗時丟出錯誤 | 幾乎所有工具 |
| `img2img(img, pos, neg, seed, denoise, mask)` | 圖生圖；給了遮罩就用 `inpaint` 只畫遮罩裡 | `live_layers.inpaint`、`object_fix` |
| `face_box(plate)` | 用動漫臉部偵測（`Tools/art/models/lbpcascade_animeface.xml`）找臉，回傳頭部方框和（臉中心 x、y、臉高） | `live_layers.face_of` |
| `_ellipse_mask(...)` | 羽化的橢圓遮罩 | 嘴型 |
| `expression(...)` | 只重畫臉部，做表情差分（閉眼等） | `key_poses.pick` |

其餘的 `plates`、`gen`、`scene`、`install` 指令是畫立繪用的，`install` 在這個專案會失敗（見總覽「已知問題」）。

---

## 5. 關鍵姿勢與角色微調（`Tools/art/key_poses.py`）

技能用的關鍵姿勢立繪：程式畫出骨架圖，用姿勢控制模型（`xinsir_openpose_sdxl`）加角色專屬微調畫出候選。

```
python Tools/art/key_poses.py cand <角色> <動作>                    每個姿勢的骨架圖＋四張候選 → <work>/poses/<角色>/<動作>/sheet.jpg
python Tools/art/key_poses.py pick <角色> <動作> <姿勢>=<種子> ...   挑中的去背＋閉眼 → <work>/live/<角色>/pose_<姿勢>/
```

（`pick` 目前會失敗，見總覽「已知問題」。）

其他工具從這支借用的資料：

| 名字 | 內容 | 誰在用 |
|---|---|---|
| `LORA` | 角色 → 微調檔名（來自角色檔 `lora`） | `object_fix`（`rig_parts` 補畫身體時沒有加微調） |
| `HOLD` | 角色 → 武器的白話描述（來自角色檔 `hold`） | `rig_parts.paint_weapon`、`object_fix` |
| `POSES[動作][姿勢]` | 十八個關節點（佔畫面的比例，COCO-18 順序：鼻、頸、右肩、右肘、右腕、左肩、左肘、左腕、右髖、右膝、右踝、左髖、左膝、左踝、右眼、左眼、右耳、左耳） | `see_through.fix_grip`、`rig_parts.split_legs`（關鍵姿勢資料夾用畫圖時的骨架補關節） |
| `W_`、`H_` | 關鍵姿勢立繪的大小 832×1216 | 同上 |

動作有 `bow`（弓）、`staff`（杖）、`fan`（扇）、`wrench`（扳手）、`stand`（待機）、`base`（A 字站姿，綁骨架用的底圖）。

`clear_background` 會把立繪上大片的底色（跟四邊顏色接近、400 像素以上的連通區）也變透明，處理武器和身體之間圍住的背景。
