# 程式說明：總覽

這個資料夾說明每一支程式在做什麼、怎麼呼叫、讀什麼寫什麼。內容照 2026-10-01 的程式碼（commit c3c6ca3）整理；設計上的決定和來龍去脈在 `Docs/Design/`，這裡只講程式。

| 文件 | 內容 |
|---|---|
| [01_Settings.md](01_Settings.md) | 設定檔、ComfyUI 連線、工作流程檔、提示詞和角色資料（`config.py`、`comfy_gen.py`、`workflows.py`、`heroine_j3.py`、`key_poses.py`） |
| [02_Split.md](02_Split.md) | 拆：找骨架、拆圖層、切零件、嘴型（`live_layers.py`、`see_through.py`、`rig_parts.py`） |
| [03_Packs.md](03_Packs.md) | 分成六包、部件檢查、組裝檢查（`split_groups.py`） |
| [04_Repair.md](04_Repair.md) | 修：輪廓、修補、AI 重畫、放回去、多角度參考圖（`outline.py`、`object_fix.py`、`object_edit.py`、`object_place.py`、`multiview.py`） |
| [05_Rig.md](05_Rig.md) | 綁：從圖層產生 `.inx` 模型（`inx_rig.py`） |
| [06_Verify.md](06_Verify.md) | 驗：跟原圖比、轉關節找破洞、武器驗證、標準動作、預覽、播放器測試 |
| [07_Player.md](07_Player.md) | Godot 播放器：讀 `.inx`、每格計算、物理、畫出來；會動的立繪（`inochi_puppet.gd`、`live_portrait.gd`） |
| [08_Studio.md](08_Studio.md) | 工作室網頁（`Tools/live2d_studio/app.py`） |
| [09_Files.md](09_Files.md) | 工作資料夾裡每個檔案的格式、圖層的名字 |

---

## 1. 整條流程和對應的程式

固定流程甲（`Docs/Design/22b_Live2D_Flow.md`）的每一步：

| 步驟 | 程式 | 要 ComfyUI | 產出（都在 `<work>/live/<角色>/<服裝>/`） | LLM 檢查 |
|---|---|---|---|---|
| 0. 選立繪 | （設定檔 `live2d.toml` 的 `plates`） | | | L0 |
| 找骨架 | `live_layers.py parts` | 要 | `fig_joints.json`、`fig_*.png`（粗分層）、`layer_*.png` | L1 |
| 1. 拆圖層 | `see_through.py` | 要 | `st/part_*.png`、`st/parts.json`、`st/st_layers.json` | L2 |
| 1b. 切零件 | `rig_parts.py` | 要（補畫身體底下、武器被擋住的部分） | 手臂、腿分段，武器補完整，`parts.json` 的 `pivots` | L3 |
| 2. 分六包 | `split_groups.py` | | `st/groups/parts_<n>.jpg`、`assemble_<n>.jpg` | L4（部件）、L6（組裝） |
| 物件迴圈 | `outline.py` → `object_fix.py`（或 `object_edit.py` → `object_place.py`） | 上色時要 | `st/outline/`、`st/fix/`、`st/gen/` | L5a、L5b、L5c |
| 3. 嘴型 | `live_layers.py mouths` | 要 | `mouth_*.png`、`mouth.json` | L7 |
| 4. 綁定 | `inx_rig.py` | | `<角色>_<服裝>_st.inx` | |
| 5. 跟原圖比 | `rig_check.py`、Godot `puppet_preview.tscn` | | `live/check/`、`_shots/` | L8 |
| 6. 人物標準動作 | Godot `motion_test.tscn ... bare` | | `_motions/` | L9 |
| 7. 武器與物件 | `object_check.py` | | `st/groups/objects/` | L10 |
| 8. 整合 | Godot `motion_test.tscn`（不加 `bare`） | | `_motions_all/` | L11 |
| 關節壓力測試 | `rig_stress.py` | | `live/check/<名稱>_stress.jpg` | L12 |
| 交付 | | | `llm_checks.md` | L14 |

每一步做完由 LLM 看檢查圖、寫下結論，通過才往下（檢查點的內容見 `Docs/Design/22b_Live2D_Flow.md`「LLM 檢查點」）。結論記在工作資料夾的 `llm_checks.md`。

工作室網頁（[08_Studio.md](08_Studio.md)）把上面每一步排成按鈕，背後執行的就是這些指令。

```
立繪 full.png
   │  live_layers.py parts          姿勢偵測 → fig_joints.json（頭、肩、肘、腕、髖、膝、踝、握點）
   ▼
   │  see_through.py                拆成二十幾層 → st/part_*.png + parts.json（前後順序）
   ▼
   │  rig_parts.py                  手臂三段、腿三段、武器、補身體底下 → parts.json 的 pivots
   ▼
   │  split_groups.py               六包，每個物件一格的檢查圖
   ▼
   │  outline.py / object_fix.py    每個物件：輪廓 → 補線 → 上色 → 檢查完整
   │  object_edit.py / object_place.py   （或請 AI 照指令重畫，再放回去）
   ▼
   │  live_layers.py mouths         張嘴的差分
   ▼
   │  inx_rig.py                    節點樹＋參數＋物理 → .inx
   ▼
   │  rig_check / rig_stress / object_check / motion_test   驗證
   ▼
Godot：InochiPuppet 讀 .inx → LivePortrait 在遊戲裡播放
```

## 2. 怎麼執行

- **Python 工具**：在專案根目錄執行 `python Tools/art/<工具>.py ...`。每支工具都會把自己的資料夾加進搜尋路徑，彼此直接 `import`（例如 `import live_layers as L`）。需要 numpy、scipy、Pillow、opencv；工作室另外要 gradio。這台電腦 PATH 上的 `python` 已經有這些套件（towerD 的 `myenv` 也可以）。Windows 主控台是 cp950，輸出有中文時加 `PYTHONIOENCODING=utf-8`。
- **多角度參考圖**：`multiview.py` 要用 MV-Adapter 自己的 Python（`live2d.toml` 的 `[mvadapter] python`）。
- **Godot 場景**：`<Godot> --path . res://Tests/live/<場景>.tscn -- <參數>`。除了 `puppet_test` 之外都要開視窗（無視窗模式畫不出東西），開視窗時加 `--audio-driver Dummy`。Godot 路徑在 `live2d.toml` 的 `[paths] godot`。
- **ComfyUI**：預設 `http://127.0.0.1:8188`。要用到它的工具在下面各文件會註明。

## 3. 共同的約定

- **座標**：一律是立繪 `full.png` 的像素（x 往右、y 往下）。每個圖層 `part_*.png` 都跟立繪一樣大，所以同一個座標在每一層都指同一點。`.inx` 模型裡的座標則以立繪中心為原點。
- **左右**：檔名和參數裡的 `l`／`r`、`Left`／`Right` 指**角色自己的**左右。角色面向我們，所以角色的右邊在畫面左邊。
- **前後順序**：`st/parts.json` 的 `order_back_to_front` 從最後面排到最前面。一層只有在「排最前面的地方」才是立繪看得到的顏色，其餘是拆層模型補畫的猜測。綁定時照這個順序給 `zsort`（數字越大越後面）。
- **原檔備份**：修補類工具第一次改某一層時，會把原本的 `part_<名稱>.png`（和 `parts.json`）複製到 `st/_orig/`，之後不再覆蓋。`outline.py --src orig`、`object_edit.py --src orig` 從這裡讀。
- **候選與套用**：會用 AI 的工具不直接改圖層，先產生候選（`st/fix/<名稱>_<種子>.png`、`st/gen/<名稱>_e<種子>.png`）和一張對照圖，看過再用 `object_fix.py --apply <種子>` 或 `object_place.py` 換上去。
- **結束代碼**：檢查類工具（`rig_check`、`rig_stress`、`object_check`、`outline --check`）有問題時回傳 1，可以拿來判斷是否通過。

## 4. 搬家後的問題

2026-10-01 讀程式時找到、已經在 `fix-after-move` 分支修好的：

| 原本的問題 | 怎麼修 |
|---|---|
| `key_poses.py pick`、`live_layers.py scene` 匯入沒搬過來的 `heroine_process` | 去背的部分搬成 `Tools/art/cutout.py` |
| `heroine_j3.py install` 呼叫沒搬過來的程式 | 拿掉（把立繪裝進立繪資料夾是美術工具箱的事） |
| 工作室從 `<專案>/Assets` 找原圖 | 改用設定檔的 `plates` |
| 工作室「審圖」要的 `review_plate.py` 沒搬過來 | 從 towerD 搬過來 |
| 工作室 `start.bat` 指向不存在的 Python | 改用 PATH 上的 `python`（`LIVE2D_PYTHON` 可改） |
| 工作室的角色名、服裝名、`FOCUS` 寫死 | 角色名讀角色檔；服裝名和 `FOCUS` 改在 `live2d.toml` 的 `[studio]` |
| 觸發詞寫死成 `<角色>_tdc` | 讀角色檔的 `trigger`（`key_poses.TRIGGER`） |
| `multiview.py` 角色微調檔名寫死 | `--lora <角色>` 讀角色檔的 `lora` |
| 裙子左右兩半的物理參數同名 | 改成 `Bottomwear Left / Right:: Physics` |
| 沒有 `Tools/run_tests.sh` | 新增：Python 編譯和匯入、Godot 播放器測試 |

**往「像原圖」拉的程式**：`Docs/Design/Project_Split.md` 第 3 節已經列出放置工具的 `--merge`、綁定時把圖層裁到人物輪廓（`part_img`、`real`、`as_plate`），以及分包工具印出跟原圖的差異。這次讀程式時，另外看到兩處會把立繪顏色蓋回圖層，要不要改請使用者決定：

- `see_through.py` 的 `to_plate`：每一層「看得到的地方」都換成立繪的顏色，畫得跟立繪差太多的整塊直接從該層拿掉。
- `rig_parts.py` 的 `order_for_motion`：會動的零件在靜止時看得到的地方換成立繪的顏色。（另一個 `front_to_plate` 預設關閉，要加 `--match-plate` 才會做。）
