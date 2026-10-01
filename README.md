# 立繪 → Live 2D 工具包

從一張角色立繪做出會動的 Live 2D 模型（Inochi2D 的 `.inx` 檔），以及在 Godot 裡播放、驗證它的工具。

2026-10-02 從遊戲專案 towerD（星晶守望者）的 `explore` 分支搬出來（commit d3b44d6c）。資料夾結構暫時跟 towerD 一樣，程式裡的相對路徑才不用改；之後再整理成獨立套件。

## 流程

詳細規則見 `Docs/Design/22b_Live2D_Flow.md`（固定流程甲），AI 重畫的研究見 `Docs/Design/22c_Object_Generation.md`，程式說明見 `Docs/Code/README.md`（每支程式的呼叫流程、參數、檔案格式）。

1. **找骨架**：`Tools/art/live_layers.py parts <角色> <服裝>`（姿勢偵測，寫 `fig_joints.json`；偵測錯要手動修）
2. **拆圖層**：`Tools/art/see_through.py <角色> <服裝>`（拆層模型；`--rebuild` 不用顯示卡重排）
3. **切零件**：`Tools/art/rig_parts.py <角色> <服裝>`（手臂、腿三段，切出武器，補身體底下）
4. **分六包、檢查每個物件**：`Tools/art/split_groups.py`、`Tools/art/object_check.py`（武器）
5. **每個物件做到完整乾淨**：`Tools/art/outline.py`（先輪廓）、`Tools/art/object_fix.py`（修補、平塗、鏡像、切出零件、分頭髮……）、`Tools/art/object_edit.py`（AI 照指令重畫單一物件）、`Tools/art/object_place.py`（放回去）、`Tools/art/multiview.py`（多角度參考圖）
6. **嘴型**：`Tools/art/live_layers.py mouths <角色> <服裝>`
7. **綁骨架**：`Tools/art/inx_rig.py <角色> <服裝>` → `.inx`
8. **驗證**：Godot 跑 `Tests/live/motion_test.tscn`（十個標準動作，不拿武器加 `bare`，再拿武器跑一次）；`Tools/art/rig_check.py`、`Tools/art/rig_stress.py`

驗收順序：**物件要看得出來是物件**（最重要的前提），先看每個物件的檢查圖（完整、乾淨、符合名字），再看組裝，最後看動作。**組起來像原圖不是目標。** 每一步做完都由 LLM 先看檢查圖、寫下結論（L1～L14），重做有上限，見 `Docs/Design/22b_Live2D_Flow.md`「LLM 檢查點」「三層檢查與重做上限」。

工作室網頁：`Tools/live2d_studio/start.bat`（照流程甲排好的按鈕和檢查圖）。

## 資料夾

| 位置 | 內容 |
|---|---|
| `Tools/art/` | 流程工具（Python）、圖層名字表（`part_names.py`）、去背（`cutout.py`）、ComfyUI 工作流程（`workflows/`）、臉部偵測模型（`models/`） |
| `Tools/run_tests.sh` | 改程式後先跑：Python 能編譯、能匯入，Godot 播放器測試 |
| `Tools/live2d_studio/` | 工作室網頁（Gradio） |
| `Scripts/live/` | Godot 播放器：`inochi_puppet.gd`（讀 `.inx`、物理擺動）、`live_portrait.gd`（遊戲裡的會動立繪）、`puppet_part_view.gd` |
| `Tests/live/` | Godot 驗證場景：標準動作、播放器測試、批次截圖、預覽 |
| `Docs/` | 流程、研究、程式說明 |
| `project.godot` | 只為了跑播放器和驗證場景的最小 Godot 專案（Godot 4.7.2） |

## 設定

- **`live2d.toml`**（專案根目錄）：工作資料夾、立繪資料夾、Godot、ComfyUI（網址、安裝位置、輸出資料夾）、繪圖模型、MV-Adapter。換電腦或換立繪來源只改這個檔。環境變數優先：`ART_WORK`、`ART_PLATES`、`COMFY_URL`、`COMFY_DIR`、`GODOT`、`ART_CKPT`（也可以用 `LIVE2D_CONFIG` 指定另一個設定檔）。
- **`characters/<角色>.toml`**：每個角色一份：名字、年齡（一律成年）、外觀描述、武器描述、角色專屬微調（LoRA）和觸發詞、每套服裝的描述。加新角色就加一個檔案。
- 程式從 `Tools/art/config.py` 讀這兩種檔案。
- 立繪放在 `<plates>/<角色>/full.png`（主設計）或 `<plates>/<角色>/skins/<服裝>/full.png`；目前 `plates` 指向 towerD 的 `Assets/Heroines`。

## 外部依賴（不在版本庫裡）

- **ComfyUI**（`127.0.0.1:8188`）：拆層（ComfyUI-See-through）、姿勢偵測與線稿（comfyui_controlnet_aux）、切武器（ComfyUI-segment-anything-2）、局部重畫（comfyui-inpaint-nodes）。
- **模型**：繪圖模型 `waiIllustriousSDXL_v170`、每個角色的角色專屬微調、萬用控制模型 `xinsir_union_promax_sdxl`、修圖模型 Mage-Flow-Edit-Turbo（`mage_flow_edit_turbo_int8_convrot`＋`qwen3vl_4b_fp8_scaled`＋`mage_flow_vae_bf16`）、MV-Adapter（另有自己的 Python 環境）。
- **Python**：numpy、scipy、Pillow、opencv、rembg（去背）、gradio（工作室）。這台電腦 PATH 上的 `python` 都有。
- **Godot 4.7.2**：跑驗證場景要開視窗（無視窗模式畫不出東西）。
- **工作資料夾**：環境變數 `ART_WORK`（預設 `C:\Users\kwkev\Tool\art_work`），所有中間產物和 `.inx` 都在這裡，不進版本庫。

## 還綁著 towerD、之後要切開的地方

1. ✅ 立繪路徑、角色設定、外部路徑已改成設定檔（2026-10-02）。`plates` 目前仍指向 towerD 的立繪資料夾，換成別的資料夾只要改 `live2d.toml`。
2. **`heroine_j3.py`、`key_poses.py` 整支帶過來了**：其實只用到局部重畫、送工作、提示詞、角色微調、動作骨架這幾個功能，要抽成小模組。（`heroine_j3.py install` 已拿掉，去背搬成 `cutout.py`，2026-10-02。）
3. **待使用者決定（22b 的檢討）**：放置工具 `--merge` 會把原圖像素貼回 AI 畫好的物件、綁定時會切掉人物輪廓外的部分、分包工具會印跟原圖的差異百分比；另外拆層的 `to_plate`、切零件的 `order_for_motion` 會把看得到的地方換成原圖顏色。這些都讓結果往「像原圖」跑（見 `Docs/Code/README.md` 第 4 節）。

## 規矩

- 金鑰、密碼、簽章檔一律不進版本庫。
- 角色一律是明確的成年人；造型可以性感，不能裸露。
