# 獨立成專案：功能盤點、搬遷計畫、檢討

2026-10-02 跟使用者討論後，把「立繪 → Live 2D」的工具從 towerD 搬出來獨立成這個專案。這份文件記錄當時的功能盤點、搬遷做法，以及搬之前的一次檢討。

## 1. 功能盤點（搬出來時）

**拆**
- 找骨架（`live_layers.py parts`）：姿勢偵測標出頭、肩、肘、腕、髖、膝、踝（寫 `fig_joints.json`），抓錯可以手動修。
- 拆圖層（`see_through.py`）：一張立繪拆成二十幾層；`--rebuild` 不用顯示卡重排。
- 切零件（`rig_parts.py`）：手臂三段、腿三段、切出武器、補身體底下被擋住的部分。
- 分六包與檢查（`split_groups.py`）：一包一張物件檢查圖，自動找缺件、左右不對稱、出界。
- 武器驗證（`object_check.py`）：完整一整塊、轉一圈看有沒有破綻。

**修（物件迴圈）**
- 輪廓（`outline.py`）：抽線、補線、刪輪廓外雜點、檢查完整度；手動標記存檔。
- 修補（`object_fix.py`）：照線稿局部重畫、平塗、最近顏色、鏡像、拆前後兩層、頭髮從雜物層和衣服分出來、補漏掉的臉、拆左右眼、刪假圖層、切出零件、自動分頭髮、清碎點。
- AI 重畫（`object_edit.py`）：Mage-Flow 照指令畫出單一物件。
- 放置（`object_place.py`）：對位、拆前後、沿骨架切。
- 多角度參考（`multiview.py`）：MV-Adapter 生成正、側、背面。
- 嘴型差分（`live_layers.py mouths`）。

**綁**（`inx_rig.py` → Inochi2D 的 `.inx`）
- 臉部：眨眼、眼神、眉毛、嘴型；頭左右轉、點頭、歪頭。
- 關節：腰、肩、肘、腕、髖、膝、踝、武器握點。
- 擺動：頭髮各片、裙子左右兩半、披風、帽子、配件、胸、髮帶、寬袖、流蘇。
- 連動變形：裙子跟腿、袖子被上臂拉、短褲跟大腿、領口跟轉頭、腰彎。

**驗**
- 十個標準動作（`Tests/live/motion_test`）：不拿武器、拿武器各一次。
- 綁定檢查（`rig_check.py`）、關節壓力測試（`rig_stress.py`）、批次截圖（`Tests/live/rig_render`）。

**播放與介面**
- Godot 播放器：`inochi_puppet.gd`（讀 `.inx`、含物理擺動）、`live_portrait.gd`（遊戲裡的會動立繪）。
- 工作室網頁（`Tools/live2d_studio`）。

做過的立繪（工作資料夾 `live/`）：芙蕾雅初始服（修補版 `freya/pose_apose`、AI 重畫版 `freya/pose_apose_gen`）、芙蕾雅服裝 C（`freya/C`）、艾莉西亞主設計（`alicia/-`）。

## 2. 搬遷計畫

### 跟 towerD 綁死、要切開的地方

1. 立繪從哪裡讀：原本寫死 `<專案根>/Assets/Heroines/<角色>[/skins/<服裝>]/full.png`。
2. 角色設定寫在程式裡：`key_poses.py` 的角色微調（`LORA`）、武器描述（`HOLD`）；`heroine_j3.py` 的提示詞和畫風。
3. `heroine_j3.py`、`key_poses.py` 牽扯太多：只用到局部重畫、送工作、提示詞、角色微調、動作骨架。
4. 工作資料夾寫死 `C:\Users\kwkev\Tool\art_work`（部分可用 `ART_WORK`）。
5. 外部程式路徑寫死：ComfyUI 位址、Godot、MV-Adapter 環境。
6. 輸出 `.inx` 是標準格式，不用改。

### 目標結構

```
live2d-pipeline/
  pipeline/            每一步一個模組（拆、修、組、綁、驗）
    comfy/             ComfyUI 客戶端＋工作流程
    config.py          讀專案設定
  characters/          每個角色一個設定檔
  godot_addon/         Godot 外掛：播放器＋驗證場景
  studio/              工作室網頁
  docs/
  tests/
  live2d.toml          工作資料夾、ComfyUI、Godot、模型檔名
```

遊戲那邊只留 Godot 外掛和產出的 `.inx`。

### 步驟與進度

1. ✅ 2026-10-02：複製到 `C:\Users\kwkev\Git\live2d-pipeline`（從 towerD `explore` 分支 d3b44d6c），保留跟 towerD 一樣的資料夾結構，`git init`。towerD 那邊的檔案照舊保留。
2. ✅ 2026-10-02：帶過來文件（22、22b、22c、程式說明），補背景文件（`Docs/Background/towerD_Context.md`）、這份文件、經驗教訓（`Docs/LessonsLearned.md`）。
3. ✅ 2026-10-02：立繪路徑、角色設定、外部路徑改成設定檔（`live2d.toml`、`characters/<角色>.toml`，`Tools/art/config.py` 讀）。角色資料從 towerD 的 `heroine_j3.py`、`key_poses.py` 自動轉換，逐項比對跟原本一模一樣；預設繪圖模型改成 WAI（新立繪都用它畫）。驗證：所有程式編譯通過、芙蕾雅 C 重新綁定的節點和參數跟原本一樣、分包和武器驗證、輪廓檢查、工作室網頁、Godot 播放器測試、十個標準動作、ComfyUI 連線。
4. ✅ 2026-10-02：放上 GitHub `git@github.com:kwkevinchan/live2D-tool.git`。
5. ✅ 2026-10-02：程式說明（`Docs/Code/`，每支程式的呼叫流程、檔案格式）；修好搬家後壞掉的地方（去背 `cutout.py`、`review_plate.py`、工作室的原圖和名字、觸發詞、`Tools/run_tests.sh`）；圖層名字統一成一張表（`part_names.py`，補上眼鏡、耳飾、領飾、尾巴）；流程加上 LLM 檢查點和三層檢查的重做上限（22b）。
6. 之後：`heroine_j3.py`、`key_poses.py` 抽成小模組；重整成 `pipeline/` 套件。
7. 之後：Godot 播放器包成外掛，towerD 改用外掛和 `.inx`；towerD 刪掉搬走的檔案。
8. 下一步：芙蕾雅的 A 字站姿從頭跑到尾（使用者 2026-10-02）。

### 待使用者決定

- towerD 用 git 子模組裝播放器外掛，還是直接複製。

## 3. 搬之前的檢討（2026-10-02）

使用者逐個物件看芙蕾雅初始服 AI 版時，指出「組起來看很像原圖」是原罪：組起來互相遮住，看起來很像，但物件本身黏著頭髮碎片、有白洞、側髮切成碎塊。

程式裡把結果往「像原圖」拉的地方（之後要改）：

| 位置 | 做法 | 問題 |
|---|---|---|
| `object_place.py --merge` | AI 畫好的物件，原圖看得到的像素一律換回原圖 | 拆層分錯的頭髮被貼回帽子、披風 |
| `object_place.py --fit` | 對位到跟原圖那層重疊最多 | 拿拆層結果當標準答案 |
| `inx_rig.py` 的 `part_img()` | 綁定時切掉人物輪廓外的部分 | AI 補完整的部分被刪掉 |
| `inx_rig.py` 的 `real()`、`as_plate()` | 用跟原圖像不像判斷零件真假、前髮用原圖顏色蓋 | 同上 |
| `object_fix.py --flat` | 用跟原圖一不一樣判斷像素歸屬 | 同上 |
| `split_groups.py` | 每次印跟原圖差多少 %、多少 % 在人物外 | 變成在追的數字 |
| 驗收方式 | 主要看原圖和模型並排、動作截圖 | 物件層級的問題被遮住 |

結論寫進 `Docs/Design/22b_Live2D_Flow.md`：**每次都逐個物件檢查，物件檢查圖先看；組起來像原圖不是優點。**
