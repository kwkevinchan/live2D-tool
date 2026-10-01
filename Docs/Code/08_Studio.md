# 工作室網頁（`Tools/live2d_studio/app.py`）

```
python Tools/live2d_studio/app.py [--no-browser]      → http://127.0.0.1:7861
```

（`start.bat` 用的 Python 路徑在這個專案不存在，見總覽「已知問題」。）

一個本機網頁（Gradio），把流程甲排成按鈕。每個按鈕在背景執行對應的指令工具，進度即時顯示在「進度」框裡；執行完自動重新整理圖片。工作資料夾、ComfyUI、Godot 的位置都讀設定檔。

---

## 1. 函式呼叫流程

```
__main__
└─ build()                                   組出整個頁面，接上每個按鈕
   └─ launch(127.0.0.1:7861, allowed_paths=[WORK, ASSETS])

按下一個步驟按鈕，例如「4. 綁定」
└─ do_rig(hero, series)
   └─ run([inx_rig.py, hero, series])        子程序執行，一行一行回傳進度
      ├─ needs_comfy 時先 comfy_up()          ComfyUI 沒開就直接提示
      └─ subprocess.Popen(...)               PYTHONIOENCODING=utf-8、不緩衝
└─ .then(folder_view)                        重新整理這個資料夾的圖片和說明
└─ .then(motions_view)

選擇資料夾
├─ folder_view(hero, series)
│  ├─ plate_of、model_of、check_results、check_name
│  └─ 讀 st/groups/groups.json
├─ motions_view(hero, series)                人物的標準動作
├─ motions_view(hero, series, whole=True)    整合後的標準動作
├─ objects_view(hero, series)
└─ part_names(hero, series)                  更新「單獨補一個物件」的圖層選單
```

## 2. 分頁

### 2-1. 總覽

- **`overview_rows()`**：每個角色的每個資料夾一列：原圖、細部分層幾層、自動審圖、使用者的審核（`review_decisions.json`）、綁定時間、跟原圖比的結果。
- **`overview_gallery()`**：所有的原圖。
- 「全部重新跟原圖比」＝ `check_all()` → `rig_check.py`（不帶參數，全部）。

### 2-2. 資料夾

`FOCUS = ("freya", "pose_apose")` 時鎖定這一張立繪（一次只做一張）；改成 `None` 才能自由選。

| 按鈕 | 函式 | 執行 |
|---|---|---|
| 1. 拆層 | `do_split` | `see_through.py`（要 ComfyUI） |
| 2. 分成六包 | `do_groups` | `split_groups.py` |
| 3. 嘴型差分 | `do_layers("mouths", ckpt, ...)` | `live_layers.py mouths`，`ART_CKPT` 用選單選的模型 |
| 4. 綁定 | `do_rig` | `inx_rig.py` |
| 5. 跟原圖比＋動態截圖 | `do_check_shots` → `do_check`、`do_shots` | `rig_check.py <角色/資料夾>`；Godot `puppet_preview.tscn`，截圖存在 `_shots/` |
| 6. 人物的標準動作 | `do_motions` | Godot `motion_test.tscn ... bare` → `_motions/`，每個動作做成動圖（`crop_box` 裁到人物附近） |
| 4～6 一次做完 | `do_all` | 依序執行，某一步失敗就停 |
| 7. 武器與物件 | `do_objects` | `object_check.py`（要先做第 2 步） |
| 8. 整合驗證 | `do_motions(whole=True)` | 先 `ready_to_join` 確認 6、7 都通過，再跑不加 `bare` 的標準動作 → `_motions_all/` |

**單獨補一個物件**（收合區）：

| 按鈕 | 函式 | 執行 |
|---|---|---|
| 1～3 抽輪廓、補線、刪噪點 | `do_outline` | `outline.py <圖層> [--drop ...]` |
| 4 照輪廓補顏色 | `do_fix_outline` | `object_fix.py <圖層> --outline --seeds ...` |
| 換上這張 | `do_fix_apply` | `object_fix.py <圖層> --apply <種子>` |
| 5 檢查完整度 | `do_outline(check=True)` | `outline.py <圖層> --check` |
| 舊補法：先看要補哪裡／補畫候選 | `do_fix` | `object_fix.py <圖層> [--dry]` |

`fix_view` 顯示輪廓對照圖和補畫對照圖。

**其他工具**（收合區）：審圖（`review_plate.py`，沒搬過來）、情境圖（`live_layers.py scene`）、粗分層（`live_layers.py parts`）、預覽動圖（`live_layers.py preview`）。

### 2-3. 狀態

- **`status_text()`**：ComfyUI 有沒有開、顯示卡用量（`nvidia-smi`）、Godot 找不找得到。
- **`start_comfy()`**：用 ComfyUI 自己的 Python 在背景啟動，等最多三分鐘；紀錄寫到 `<work>/comfyui.log`。

## 3. 小函式

| 函式 | 做什麼 |
|---|---|
| `run(args, needs_comfy, exe, env_extra)` | 執行一支工具（或 `exe=GODOT` 時執行 Godot），回傳越來越長的紀錄（只留最後 6000 字）；濾掉 Godot 無害的雜訊；最後加「完成。」或「失敗（代碼 N）。」 |
| `folders(hero)`、`folder_label(series)` | 角色的資料夾（服裝在前、姿勢在後）和中文名稱 |
| `plate_of(hero, series)` | 原圖：資料夾自己的 `full.png`，或 `<專案>/Assets/Heroines/...`（還沒改用設定檔） |
| `model_of(hero, series)` | 資料夾裡最新的 `.inx` |
| `check_results()` | 讀 `<work>/live/check/rig_check.json` |
| `review_of(hero, series)` | 讀資料夾的 `review.json` 的自動警告 |
| `decisions()` | 讀 `<work>/review_decisions.json`（跟美術工作室共用）。讀壞了就停下來，不當成空的，免得寫回去時把之前的決定洗掉 |
| `character_passed`、`ready_to_join` | 人物標準動作有沒有缺東西、武器與物件有沒有通過 |
| `checkpoints()` | 模型資料夾裡的繪圖模型清單（嘴型選單用） |

角色和服裝的中文名寫在 `HERO_NAMES`、`SKIN_NAMES`、`POSE_NAMES`；`SKILLS` 記每個角色的技能（關鍵姿勢的動作、技能預覽的種類、姿勢順序），目前頁面上沒有用到。
