# 流程程式：讓程式跑流程、LLM 只看圖下結論（設計，2026-10-02）

> 2026-10-03：流程本身搬到 [../Flow/](../Flow/README.md)，每一步一份文件；注意重點改從那裡取（`flow#L4`），檢查點重新編號（部件動作 L9、靜態 L10、標準動作 L11、物件 L13、整合 L13b）。下面的設計保留當時的寫法（`22b#L4`）。

這份是「流程程式」`wf` 的設計：把 [22b_Live2D_Flow.md](22b_Live2D_Flow.md) 的甲流程（檢查點 L1～L14、三層重做上限、四道保險、各檢查點的注意重點）寫成一個設定檔，由程式照著跑。工具本身不改；工具的說明見 [../Code/README.md](../Code/README.md)，過去的錯誤見 [../LessonsLearned.md](../LessonsLearned.md)。

**已經做好（2026-10-02，分支 `wf-engine`）**：程式在 `Tools/wf/`，流程在 `flows/plate.toml`，說明在 [../Code/10_Workflow.md](../Code/10_Workflow.md)。下面第一～八節是原本的設計；做的時候改了的地方列在第九節，第十節的問題先用暫定的答案。

## 為什麼要做

現在整條流程是 Claude Code 對話憑記憶照 22b 跑的：

- **步驟會被跳過**：2026-10-02 芙蕾雅主設計的部件動作測試（L9）整步漏做，一路做到整合驗證，使用者問了才補（`llm_checks.md`：「這一步原本漏做，使用者指出後補」）。
- **上限和保險靠手記**：每個物件試了幾次、哪種做法已經失敗兩次、這一包重做了幾次，都是對話自己數。帽子試了 7 張、5 種做法，數得對是運氣。
- **每張檢查圖都要手動打開**：做完一步，對話要自己想起來該看哪幾張圖、對照哪幾條注意重點。

使用者（2026-10-02）：「用講的已經到極限了」，要一個跑流程的程式。分工改成：**程式決定下一步做什麼、數次數、擋住不准的做法；LLM 只看圖、下結論、從選單裡挑修法。**

---

## 一、流程寫成設定檔 `flows/plate.toml`

一張立繪的流程寫在 `flows/plate.toml`（放在版本庫裡）。每一步寫清楚：

| 欄位 | 意思 |
|---|---|
| `id` | 步驟名字，`wf redo <id>` 用 |
| `cmd` | 要執行的指令，裡面的 `{hero}`、`{series}`、`{dir}`（工作資料夾）、`{godot}`、`{part}` 由程式代入 |
| `inputs`／`outputs` | 讀哪些檔、寫哪些檔（可用 `*`）；用來判斷「上游改了、這一步要重做」 |
| `after` | 要等哪幾步通過才能做 |
| `check` | 檢查點編號（`L4`），沒有就是不用看、做完直接往下 |
| `images` | 這個檢查點要看的圖 |
| `focus` | 注意重點：指向 22b「各檢查點的注意重點」的那一節，再加幾條這一步特別要提醒的；不把整份清單抄進來 |
| `fix` | 沒通過時可以用的修法選單，每一項有自己的參數 |
| `limit` | 這一步的重做上限、預估時間 |
| `gate` | `human`＝這一步一定要使用者點頭 |

一段例子（只列幾步，參數照現在的工具）：

```toml
[flow]
name = "plate"
work = "{art_work}/live/{hero}/{series}"
estimate_min = 120          # 整張立繪的預估時間；超過兩倍就停（時限規則）

[limits]                    # 22b「三層檢查與重做上限」，由程式數
per_object = 10             # 測試期間；原本 3
per_pack_factor = 2         # 一包的物件重做總數 ≤ 物件數 × 2
per_pack_min = 6
pack_rounds = 3             # 一包的組裝檢查最多幾輪
plate_redos = 30            # 整張立繪的物件重做總數
plate_rounds = 3
same_way_fails = 2          # 同一個問題、同一種做法失敗兩次就不准再用

[[step]]
id = "see_through"
cmd = "python Tools/art/see_through.py {hero} {series} --seed {seed}"
inputs = ["full.png", "fig_joints.json"]
outputs = ["st/part_*.png", "st/parts.json", "st/_stack_vs_plate.jpg"]
after = ["joints"]
check = "L2"
images = ["st/_stack_vs_plate.jpg"]   # 加上程式印出的圖層清單
focus = ["22b#L2", "長髮有沒有被丟進雜物層", "帽子、武器有沒有被認出來"]
vars = { seed = 42 }
fix = [
  { id = "reseed",     cmd = "{same} --seed {seed}", params = { seed = "int" } },
  { id = "make_face",  cmd = "python Tools/art/object_fix.py {hero} {series} face --make-face" },
  { id = "split_lr",   cmd = "python Tools/art/object_fix.py {hero} {series} {part} --split-lr", params = { part = "layer" } },
  { id = "drop_part",  cmd = "python Tools/art/object_fix.py {hero} {series} {part} --drop-part", params = { part = "layer" } },
  { id = "sort_hair",  cmd = "python Tools/art/object_fix.py {hero} {series} leftover --sort-hair" },
  { id = "to_objects", note = "記下來，留給物件迴圈修" },
]

[[step]]
id = "rig_parts"
cmd = "python Tools/art/rig_parts.py {hero} {series}"
after = ["see_through"]
check = "L3"
then = ["split_groups"]      # 先分一次包，才有 parts_4/5 可看
images = ["st/groups/parts_4.jpg", "st/groups/parts_5.jpg", "st/groups/parts_3.jpg"]
focus = ["22b#L3"]
fix = [
  { id = "weapon_points", cmd = "{same} --weapon {pts} --not {neg}", params = { pts = "points", neg = "points" } },
  { id = "mirror",  cmd = "python Tools/art/object_fix.py {hero} {series} {part} --mirror", params = { part = "layer" } },
  { id = "grey",    cmd = "python Tools/art/object_fix.py {hero} {series} hidden --grow grey --only {box}", params = { box = "box" } },
  { id = "specks",  cmd = "python Tools/art/object_fix.py {hero} {series} {part} --drop-specks {n}", params = { part = "layer", n = "int" } },
]

[[step]]
id = "split_groups"
cmd = "python Tools/art/split_groups.py {hero} {series}"
outputs = ["st/groups/parts_*.jpg", "st/groups/assemble_*.jpg", "st/groups/groups.json"]
after = ["rig_parts"]
check = "L4"                 # 第一次看部件；物件迴圈結束後再看一次組裝（L6）
per_item = "object"          # 結論要一個物件一個
images = ["st/groups/parts_{1..6}.jpg"]
focus = ["22b#L4", "先問看得出來是什麼嗎"]
on_redo = "objects"          # 被判重做的物件交給物件迴圈

[[step]]
id = "objects"
kind = "each_object"         # 每個要修的物件一件小工作，見第二節
from = "split_groups"
substeps = ["outline", "candidates", "place"]   # L5a → L5b → L5c
then_check = { id = "L6", images = ["st/groups/assemble_{1..6}.jpg"], focus = ["22b#L6"] }

[[step]]
id = "inx_rig"
cmd = "python Tools/art/inx_rig.py {hero} {series}"
outputs = ["{hero}_{series}_st.inx"]
after = ["objects", "mouths"]

[[step]]
id = "pack_motion"           # 第 4b 步：2026-10-02 漏做的那一步，現在寫死在流程裡
foreach = { pack = ["arms", "legs", "head", "body", "weapon", "held"] }
cmd = "{godot} --audio-driver Dummy --path . res://Tests/live/motion_test.tscn -- {inx} {dir}/_packs pack={pack} nophys"
then = ["python Tools/art/motion_sheet.py {dir}/_packs --max 16"]
after = ["inx_rig"]
check = "L9"
per_item = "pack"
images = ["_packs/sheet_pack_{pack}.jpg"]
focus = ["22b#L9", "零件後面的補畫層有沒有空洞"]
on_redo = "objects"          # 算進第二層（一包）的上限

[[step]]
id = "motions"
cmd = "{godot} --audio-driver Dummy --path . res://Tests/live/motion_test.tscn -- {inx} {dir}/_motions_{mode} bare {mode}"
foreach = { mode = ["nophys", "phys"] }
then = ["python Tools/art/motion_sheet.py {dir}/_motions_{mode}"]
after = ["pack_motion", "static"]
check = "L11"
per_item = "motion"
images = ["_motions_nophys/sheet.jpg", "_motions_phys/sheet.jpg", "_motions_nophys/report.json"]
focus = ["22b#L11"]

[[step]]
id = "integrate"
cmd = "{godot} --audio-driver Dummy --path . res://Tests/live/motion_test.tscn -- {inx} {dir}/_motions_all"
after = ["motions", "objects_check"]   # 6、7 都通過才能做
check = "L13b"
images = ["_motions_all/sheet.jpg"]
focus = ["22b#L13b"]

[[step]]
id = "handover"
check = "L14"
gate = "human"               # 交付一定給使用者看
```

規則：

- **沒有寫在設定檔裡的步驟不會被做，寫了的不會被跳過**。要跳過某一步，只能在設定檔裡標 `skip = "原因"`，原因會寫進紀錄。
- `focus` 的 `22b#L4` 由程式從 22b 取出「L4 部件檢查」那一節的條列，放進審查包；22b 改了，下一次自動跟著改。
- `fix` 是**選單**：審查的人只能從裡面挑，參數照型別檢查（`box` 是四個整數、`layer` 必須是現有的圖層名、`points` 是一串座標）。選單外的修法用 `manual`（見第四節）。

## 二、物件迴圈：每個物件一件小工作

L4（或 L6、L9、L11 點名）判「重做」的每個物件，各自變成一件小工作 `objects/<物件名>`，有自己的狀態和次數，依 22b「由後往前補」排順序（身體、腿先，手臂、武器、頭髮後）。

一件小工作照三小步走，每一小步都停下來給 LLM 看：

1. `outline`（L5a）：`outline.py {hero} {series} {part}`，看 `st/outline/{part}.jpg`。
2. `candidates`（L5b）：`object_fix.py`（修補）或 `object_edit.py --engine qwen --fast`（AI 重畫，三張先挑；三張都不行才 40 步），看 `st/fix/{part}.jpg` 或 `st/gen/{part}_{tag}.jpg`。
3. `place`（L5c）：`object_fix.py --apply` 或 `object_place.py`，再自動重跑 `outline.py --check` 和 `split_groups.py`，看 `parts_<n>.jpg` 的那一格和 `assemble_<n>.jpg`。

結論是「要再拆」時（帽子要拆前後兩層、側髮要從前髮切出來），程式執行選定的拆法（`--carve`、`--split-hair`、`--split-front`），拆出的新物件各自開一件新的小工作，從第 1 小步開始。

**程式負責擋的上限和保險**（22b 的數字，寫在 `[limits]`）：

| 項目 | 上限 | 到了怎麼辦 |
|---|---|---|
| 一個物件的重做 | 10 次（測試期間） | 這個物件 `blocked`，其他物件繼續 |
| 一包的物件重做總數 | 物件數 × 2，至少 6 次 | 這一包 `blocked` |
| 一包的組裝檢查 | 3 輪 | 這一包 `blocked` |
| 整張立繪的物件重做總數 | 30 次 | 整張停下，等使用者 |
| 整張立繪的組裝檢查 | 3 輪 | 整張停下，等使用者 |
| 時間 | 預估的 2 倍 | 整張停下，等使用者 |

四道保險怎麼做到：

1. **次數上限**：上表，程式每執行一次修法就加一，到了就把狀態改成 `blocked`，審查包裡附上全部的嘗試。
2. **同一個問題、同一種做法失敗兩次就不准再用**：每次結論都要寫「問題的種類」（固定幾種：`unrecognizable` 看不出是什麼、`incomplete` 不完整、`dirty` 有碎片或殘影或白洞、`misplaced` 位置或大小不對、`order` 前後錯、`style` 畫風不對）。程式記「物件＋問題種類＋修法」失敗幾次；兩次之後，下一個審查包的選單裡這個修法會被拿掉，審查的人挑了也會被退回。例：芙蕾雅的帽子「位置不對」，`--fit` 對位失敗兩次後，選單只剩 `--box`、換來源（從原圖切）等。
3. **通過的物件凍結**：通過的物件之後只有 L6、L9、L11 的結論**點名**它才會重開，重開的次數算進那一層的上限。程式拒絕對凍結的物件執行修法。
4. **時限**：程式記每一步的開始、結束時間，加總超過 `estimate_min × 2` 就停。

## 三、狀態檔 `run.json`

每張立繪一個 `art_work/live/<hero>/<series>/run.json`，程式自己讀寫，人和 LLM 只讀：

```json
{
  "flow": "plate", "hero": "freya", "series": "-",
  "started": "2026-10-02T08:20:00", "elapsed_min": 94,
  "counts": { "plate_redos": 14, "plate_rounds": 1 },
  "steps": {
    "see_through": { "status": "passed", "attempts": 1, "review": "L2-1",
                     "outputs": { "st/parts.json": "sha256:3f1a…" } },
    "split_groups": { "status": "passed", "attempts": 2, "review": "L4-2" },
    "objects/headwear": {
      "status": "passed", "attempts": 7, "pack": "1_face",
      "tries": [
        { "n": 1, "fix": "edit_fast", "problem": null, "result": "redo" },
        { "n": 2, "fix": "place_fit", "problem": "misplaced", "result": "redo" },
        { "n": 3, "fix": "place_box", "problem": "misplaced", "result": "redo" }
      ],
      "banned": [ "place_fit:misplaced" ]
    },
    "pack_motion": { "status": "needs_review", "attempts": 1, "review": "L9-1" },
    "motions":     { "status": "pending",  "stale_because": null }
  }
}
```

狀態只有六種：

| 狀態 | 意思 |
|---|---|
| `pending` | 還沒做，或上游改了要重做 |
| `running` | 指令正在跑 |
| `needs_review` | 做完了，審查包寫好了，等結論 |
| `passed` | 通過 |
| `rejected` | 沒通過，等程式照結論執行修法（執行後回到 `running`） |
| `blocked` | 到了上限、時限，或修法執行失敗；只有使用者能解開 |

**上游改了，下游要重做**（跟 `make` 一樣）：每一步通過時，程式記下它讀到的每個檔的指紋（`sha256`）。之後只要有一個輸入檔的指紋不同（例如物件迴圈換了 `st/part_headwear.png`），這一步和它之後的每一步都改回 `pending`，`stale_because` 寫是哪個檔。被後面的步驟改寫的檔，以最後寫它的那一步為準，不會讓前面已通過的步驟重做。

**可以中斷、接著做**：程式隨時可以被關掉（電腦重開、顯示卡被別人借走），`wf run` 會從 `run.json` 接著做；`running` 的步驟重跑一次。

**`wf redo <步驟>`**：手動把某一步（和它的下游）改回 `pending`，例如 `wf redo inx_rig`、`wf redo objects/front_hair`。凍結的物件用這個指令重開時要加理由，理由寫進紀錄。

## 四、審查包

到了檢查點，程式停下來，在工作資料夾寫一個審查包 `reviews/<檢查點>-<第幾次>/`：

```
reviews/L4-2/
  request.json      要看什麼、看什麼重點、過去試過什麼、可以怎麼修
  parts_1.jpg … parts_6.jpg   從 st/groups/ 複製過來的檢查圖（當時的版本，之後不會變）
  verdict.json      審查的人寫的結論（寫進來之前不存在）
```

`request.json` 的例子（L5b，芙蕾雅的帽子第 6 次）：

```json
{
  "review": "L5b-6",
  "check": "L5b",
  "item": "objects/headwear",
  "images": [ { "file": "gen_headwear_e40.jpg", "what": "40 步版兩張候選，左起第 1、2 張" } ],
  "focus": [
    "22b#L5b 全部（程式已展開成條列）",
    "物件正確、風格接近就好，不用跟原圖一樣；擋到別的東西用放置解決",
    "帽簷前緣有沒有蓋住眼睛"
  ],
  "history": [
    { "n": 3, "fix": "place_box", "params": { "box": "110,15,645,278" }, "verdict": "redo",
      "problem": "misplaced", "reason": "parts_1.jpg 帽子那格：帽簷中間垂到眼睛" },
    { "n": 4, "fix": "place_clear", "verdict": "redo", "problem": "incomplete",
      "reason": "帽簷被挖出缺口，單獨看是破洞的帽子" }
  ],
  "counts": { "object": "6/10", "pack": "9/12", "plate": "12/30" },
  "menu": [
    { "id": "edit_fast",  "params": { "instr": "text", "seeds": "ints" } },
    { "id": "edit_slow",  "params": { "instr": "text", "seeds": "ints" } },
    { "id": "place_box",  "params": { "box": "box" } },
    { "id": "sam_plate",  "params": { "pos": "points", "neg": "points" } },
    { "id": "split_front" },
    { "id": "manual",     "params": { "what": "text" } }
  ],
  "banned": [ "place_fit:misplaced" ],
  "answer_with": "wf verdict freya/- L5b-6 verdict.json"
}
```

審查的人回 `verdict.json`，格式固定，程式會檢查：

```json
{
  "review": "L5b-6",
  "items": [
    {
      "item": "objects/headwear",
      "verdict": "redo",
      "problem": "style",
      "reason": "gen_headwear_e40.jpg 第 1 張：從下往上看對了，但整頂偏暗、扣環變成方扣；第 2 張整頂歪掉",
      "pick": null,
      "fix": { "id": "place_box",
               "params": { "pick": "gen_headwear_qf3.png", "box": "133,2,621,240" },
               "why": "快速版第 3 張這頂帽子本身是對的；照原圖的框放會蓋住眼睛，縮小約 7%、放高，帽簷停在眼睛上方" }
    }
  ],
  "confidence": "high",
  "by": "claude-code"
}
```

- `verdict` 只能是 `pass`、`redo`、`split`（要再拆）。`redo` 和 `split` 一定要有 `fix`，而且要在選單裡、不在 `banned` 裡、參數型別對。
- `reason` 要寫**在哪張圖的哪裡**（「parts_1.jpg 帽子那格的右下」），不能只寫「不好」。
- 有候選圖的檢查點（L5b）用 `pick` 挑一張；`pick: null` 表示一張都不挑。
- 一張圖有好幾個物件時（L4、L9、L11），每個物件、每一包、每個動作都要有一筆；少一筆程式就退回（22b「逐個物件看」）。
- `manual`：選單外的修法（例如 2026-10-02 手動照下巴線切掉臉的下緣、用裙子顏色補法杖後面的洞）。由對話或使用者直接改檔，`what` 寫改了什麼；程式重新算指紋、照常算一次重做。同一種手動修法用到第二次，就該做成工具、加進選單（記在 `Docs/Code/`）。

程式收到結論後：照 `fix` 執行指令，做完自動產生下一個審查包；全部通過才往下一步。

**`llm_checks.md` 由程式產生**：每個結論寫一筆（時間、檢查點、看了哪些圖、結論、每個問題在哪、用了什麼修法、次數），格式跟現在的 `llm_checks.md` 一樣，人不用再手寫。

## 五、審查怎麼送到 LLM

### 第一階段（現在）：程式在背景跑，Claude Code 對話來審

1. Claude Code 對話在背景啟動 `wf run freya/-`。
2. 程式做到檢查點，寫好審查包，印一行 `REVIEW freya/- L4-2 reviews/L4-2/request.json`，然後結束（結束代碼 `10`＝等審查）。
3. 對話收到「背景工作結束」的通知（跨對話時改用訊息：程式寫一行到 `art_work/live/inbox.jsonl`，對話用監看等它），讀 `request.json`，照 `images` 一張一張看圖、照 `focus` 逐條對。
4. 對話寫 `verdict.json`，執行 `wf verdict freya/- L4-2 reviews/L4-2/verdict.json`；程式檢查格式、執行修法、再在背景跑到下一個檢查點。

這一階段對話不用記流程走到哪、不用數次數、不用想該開哪張圖：全部在審查包裡。

### 第二階段（之後）：程式直接呼叫 Claude 讀圖

程式把審查包的圖和文字直接送給 Claude（讀圖），要求照 `verdict.json` 的格式回答，收到就執行。只有這幾種情況停下來找人：

- 到了任何一個上限或時限（`blocked`）；
- 結論的 `confidence` 是 `low`，或同一個審查包問兩次結論不一樣；
- 設定檔標了 `gate = "human"` 的步驟。

第一階段累積的結論（每個審查包都有使用者看得到的結論）就是第二階段的對照組：同一包圖，看自動呼叫的結論跟對話的結論差多少。

## 六、使用者的角色

**工作室多一個「審查」分頁**（`Tools/live2d_studio/app.py`）：

- 左邊列出所有立繪目前停在哪、哪些是 `needs_review`、哪些 `blocked`。
- 點一個審查包：上面是檢查圖，下面是重點、過去的嘗試（每次的圖都留著，可以前後對照）、LLM 的結論。
- 按鈕：**同意**（照 LLM 的結論做）、**改判**（改成通過、重做或要再拆，從同一份選單挑修法，原因必填）、**解開**（`blocked` 的放寬一次上限或指定下一步）。改判寫成同一個 `verdict.json` 格式，`by` 是 `user`，並在 `llm_checks.md` 標出「使用者改判」。

**一定要使用者的步驟**（`gate = "human"`，在設定檔裡改）：

- 選哪一張立繪（第 0 步，本來就是使用者選）；
- 任何 `blocked`；
- 交付（L14）。

## 七、做多大

**自己寫一支小程式**，`Tools/wf/`，約 500～800 行 Python：

| 部分 | 大約 |
|---|---|
| 讀設定檔、代入參數、展開 `foreach`、`{1..6}` | 120 行 |
| 狀態檔、指紋、上游改了下游重做 | 150 行 |
| 執行指令、記時間、時限 | 80 行 |
| 物件迴圈、上限、禁用做法、凍結 | 150 行 |
| 審查包、檢查結論格式、產生 `llm_checks.md` | 150 行 |
| 指令列 | 80 行 |

不用 `Airflow`、`Prefect`、`Dagster` 這類現成的排程系統：它們要另外架服務、資料庫，很重；設計上是「機器跑到底」，中間停下來等人或等 LLM 看圖、再照看圖的結論決定下一步，正好是它們最不擅長的。我們的流程一張立繪只有十幾步、一次跑一張，需要的是上限、保險和審查包，不是排程。

指令：

| 指令 | 做什麼 |
|---|---|
| `wf run <hero>/<series>` | 從 `run.json` 接著跑，到下一個檢查點停 |
| `wf status [<hero>/<series>]` | 每一步的狀態、次數、用了多少時間、還剩多少上限 |
| `wf review <hero>/<series>` | 印出目前等審查的審查包（給對話用） |
| `wf verdict <hero>/<series> <審查包> <verdict.json>` | 交結論，程式檢查後執行 |
| `wf redo <hero>/<series> <步驟>` | 把一步和它的下游改回 `pending` |

（做出來的寫法是 `python Tools/wf <指令> ...`，另外多一個 `unblock`，見第九節。）

**現有的工具照原樣呼叫，一行都不改**。工具的結束代碼（`rig_check`、`object_check`、`outline --check` 有問題回 1）只當提示寫進審查包，不當結論（22b：看圖，不看數字下結論）。

## 八、怎麼開始

**第一個測試：芙蕾雅主設計 `freya/-` 整條重跑一次**，跟 2026-10-02 手動跑的結果比。

1. 手動跑的資料夾整個複製一份到 `art_work/live/freya/-_hand_20261002/`，`llm_checks.md` 一起保留。
2. 工作資料夾回到只有 `full.png`、`full_blink.png`，`wf run freya/-` 從找骨架開始。
3. 這一輪由 Claude Code 對話審（第一階段）。
4. 比這幾件事：

| 比什麼 | 手動那次 | 程式要做到 |
|---|---|---|
| 有沒有漏步驟 | L9 漏做，使用者指出才補 | 每一步都有審查包，L9 在 L10、L11 前面 |
| 物件重做次數 | 帽子 7 張、5 種做法；前髮 2 輪；其他 1 次 | `run.json` 數得出來，而且跟紀錄對得上 |
| 禁用做法 | 靠對話自己記 | `--fit` 對位失敗兩次後從選單消失 |
| 選單外的修法 | 下巴照線切、裙子補洞、法杖中線、`hidden` 刪範圍外，都是臨時寫的 | 每個 `manual` 都有紀錄，列成「要做成工具」清單 |
| 時間 | 約 1.5 小時（08:20～09:54） | 記下每一步的時間，看程式多花或少花 |
| 沒解決的問題 | 腰彎時長裙裂開、膝蓋接縫、法杖後面的糊 | 一樣列在交付的審查包裡 |

5. 跑完寫一份比較，交給使用者決定要不要拿它跑下一張（芙蕾雅 A 字站姿 `freya/pose_apose`）。

## 九、做的時候改了的地方（2026-10-02）

程式照上面的設計做，下面這幾處不一樣，以 `flows/plate.toml` 和 [../Code/10_Workflow.md](../Code/10_Workflow.md) 為準：

| 原本的設計 | 做出來的 | 為什麼 |
|---|---|---|
| 修法寫在每一步裡（`fix = [{ id = ..., cmd = ... }]`） | 修法統一寫在 `[fix.<id>]`，步驟用 `fix = ["reseed", ...]` 指；另有 `pass_fix`（通過時可以挑的下一步做法） | 同一個修法（`carve`、`edit_fast`、`place_box`）好幾個檢查點都用，只寫一次 |
| 物件迴圈的三小步寫成 `substeps`，L6 寫成 `then_check` | 三小步寫成 `[[step.stage]]`，各有自己的指令、圖、選單；L6 就是物件迴圈這一步自己的 `check` | 每一小步的選單不一樣 |
| L5b 的指令固定 | L5b、L5c 沒有自己的指令：L5a 通過時從 `pass_menu` 挑出候選的做法（AI 重畫、鏡像、上色），L5b 通過時 `pick` 一張再挑放法 | 每個物件適合的做法不一樣（四肢先鏡像，被擋住的用 AI），先定死會白跑一次顯示卡 |
| 修法做完要回到哪一小步沒有寫 | 每個修法有 `stage`：做完停在哪一小步（例如在 L5c 改用 40 步重畫，就回到 L5b） | 「回到 L5a 或 L5b」要由程式決定 |
| 禁用的修法從選單拿掉 | 留在選單，另外列在 `banned`（`修法:問題種類`），挑了會被退回；這次的結論剛好是第二次失敗時也算 | 禁用是「對這一種問題」，換一種問題還可以用 |
| 「只當提示」的結束代碼 | 指令前面加 `?` | 一步裡有的指令失敗要停（拆層），有的只是提示（`rig_check`） |
| 選填的參數 | 寫成一個片段 `--weapon={pts}`，值是空的整段拿掉 | 不用另外的條件語法 |
| 第 0 步不審 | 第 0 步 `plate` 是檢查點 `L0`，`gate = "human"`：把立繪複製進工作資料夾，等使用者點頭 | 第十節的暫定答案：選立繪一定要使用者 |
| `wf` 五個指令 | 多一個 `wf unblock`：使用者解開停住的，那一個上限多給幾次，原因寫進紀錄 | `blocked` 要有地方解開；工作室的審查分頁還沒做 |
| 時間：開始到現在 | 工具執行的時間，加上每次等審查的時間（每次最多算 20 分鐘） | 隔夜接著做時，睡覺的時間不該算 |
| 嘴型排在物件迴圈之後 | `mouths` 在設定檔裡排在物件迴圈後面，但只等 `see_through` | 物件重開時不用重做嘴型（它只讀立繪） |
| 多角度參考圖沒寫 | `multiview` 寫進流程、標 `skip`（混合版不跑） | 要跑時拿掉 `skip` 就好；跳過也有紀錄 |
| 部件動作測試六包 | 七包：多一個 `hair`（打開擺動跑） | 頭髮包在 `freya-hair-pack` 分支加進 `motion_test.gd`；這個分支上的 `motion_test.gd` 還沒有，要合併那個分支後才跑得動 |
| 結論低信心：第二階段的規則 | 第一階段就用：先不執行，等使用者 | 第十節的暫定答案 |
| 約 500～800 行 | 程式約 1200 行（另有測試約 300 行、設定檔約 400 行） | 結論格式的檢查、物件迴圈的三小步、各層上限比估的多 |

**還沒做的**：工作室的「審查」分頁（第六節）、第二階段直接呼叫模型（第五節）、跨對話的 `inbox.jsonl`、同一個工作資料夾同時只能有一個 `wf run` 的鎖、`--hair-ends`（頭髮拆成多片，在 `freya-hair-pack` 分支）。`Tools/run_tests.sh` 多了 `LIVE2D_SKIP_GODOT=1`，Godot 不能開的時候只跑 Python 的部分。

## 十、要請使用者決定的事

1. **哪些步驟一定要你看**：目前只有選立繪、`blocked`、交付。L4（主要關卡）要不要也加？還是只在第一張立繪加，之後拿掉？
2. **要不要直接呼叫 Claude 讀圖**（第二階段）：要用 Anthropic 的付費金鑰，一張立繪大約要送四、五十個審查包；要不要先估費用再決定？
3. **結論的信心怎麼表示**：只分高、低兩級？還是要每個物件一個信心？低信心是停下來找你，還是同一包再問一次、兩次一樣才算？
4. **跨對話的訊息**：第一階段是由啟動它的那個對話自己等，還是任何一個開著的對話都可以接（寫到 `inbox.jsonl`）？
5. **`manual` 要不要限制**：選單外的手動修法要不要每次都先問你，還是先讓對話做、在審查分頁事後看？
6. **上限要不要回到原本的 3 次**：每個物件 10 次是測試期間的數字，第一個測試跑完後要不要改回去？
7. **設定檔放哪**：`flows/plate.toml` 放在專案根目錄，還是跟其他設定一起放進 `live2d.toml` 旁邊？

**目前做法（暫定，使用者可改）**：

1. 一定要使用者的只有選立繪（L0）、任何 `blocked`、交付（L14）；L4 不加。
2. 只做第一階段：程式不呼叫任何模型的服務，審查的人就是 Claude Code 對話。
3. 信心只分 `high`、`low` 兩級，整份結論一個；`low` 時程式先不執行，停下來等使用者（`by: "user"` 再交一次）。
4. 由啟動 `wf run` 的那個對話自己等：結束代碼 `10` 加上 `REVIEW` 那一行；`inbox.jsonl` 沒做。
5. `manual` 可以用，不用先問；每次都記在 `run.json` 的 `manual`，`wf status` 會列出來，交付時給使用者看。
6. 每個物件的上限維持 10 次（`[limits] per_object`）。
7. 設定檔放在專案根目錄 `flows/plate.toml`。
