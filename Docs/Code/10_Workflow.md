# 流程程式（`Tools/wf/`）

一張立繪從選定到交付，照設定檔 `flows/plate.toml` 一步一步跑：程式決定下一步做什麼、執行工具、數重做次數、擋住不准的做法；到了每個檢查點就停下來，寫一個審查包，等審查的人（現在是 Claude Code 對話）看圖、從選單挑修法、交回結論。設計和來龍去脈見 [../Design/23_Workflow.md](../Design/23_Workflow.md)；流程本身（檢查點 L1～L14、上限、注意重點）見 [../Design/22b_Live2D_Flow.md](../Design/22b_Live2D_Flow.md)。

不需要顯示卡、ComfyUI、Godot；它呼叫的工具才需要（照原樣呼叫，工具一行都沒改）。只用 Python 3.11 內建的模組。

```
python Tools/wf run <角色>/<服裝>                        從 run.json 接著跑，到下一個檢查點停
python Tools/wf status [<角色>/<服裝>]                   每一步的狀態、次數、上限；不給就列出所有立繪
python Tools/wf review <角色>/<服裝>                     印出目前等審查的審查包
python Tools/wf verdict <角色>/<服裝> <審查包> <verdict.json> [--no-run]   交結論；合格就照結論執行、跑到下一個檢查點
python Tools/wf redo <角色>/<服裝> <步驟 | objects/<物件>> [--reason ...] 把一步（和它後面的）改回 pending
python Tools/wf unblock <角色>/<服裝> <步驟 | objects/<物件> | run> --reason ... [--more N]   使用者解開停住的
```

每個指令都可以加 `--flow <設定檔>`（預設 `flows/plate.toml`；第一次跑之後記在 `run.json`，之後不用再給）。`python -m wf ...`（把 `Tools` 加進搜尋路徑）也可以。

**結束代碼**：`0` 全部通過（或指令做完）；`10` 等審查，同時印一行 `REVIEW <角色>/<服裝> <審查包> <request.json 的路徑>`；`20` 停住了（到了上限、時限，或工具失敗），印 `BLOCKED ...`，只有使用者能解開；`2` 結論不合格式（印出每一條原因，什麼都沒執行）或指令寫錯。

---

## 1. 檔案

| 檔案 | 內容 |
|---|---|
| `Tools/wf/__main__.py` | `python Tools/wf` 的入口 |
| `Tools/wf/cli.py` | 指令列、`status` 的列印 |
| `Tools/wf/flow.py` | 讀設定檔、代入參數、展開 `{1..6}` 和 `foreach`、從 22b 取注意重點 |
| `Tools/wf/engine.py` | 狀態檔、執行工具、物件迴圈、上限和四道保險、處理結論 |
| `Tools/wf/review.py` | 寫審查包、檢查結論格式、寫 `llm_checks.md` |
| `Tools/wf/tests/` | 測試：假的流程 `fake_flow.toml`、代替工具的 `stub.py`、`test_wf.py` |
| `flows/plate.toml` | 一張立繪的流程（22b 甲，L0～L14） |

## 2. 函式呼叫流程

```
main(argv)                                        cli.py
├─ Run(target, flow)                              engine.py：讀設定檔和 run.json（沒有就開一份新的）
│  └─ Flow(path)                                  flow.py：tomllib 讀；檢查 after、修法的 id 都存在
├─ run → Run.advance()
│  ├─ refresh_stale()                             通過的步驟重算輸入檔的指紋，不一樣 → reset(步驟)
│  │  └─ fingerprint(step, v)                     後面的步驟會寫的檔不算（以最後寫它的為準）
│  └─ 重複：
│     ├─ 有等審查的 → say_review() → 10
│     ├─ 整張停住，或用掉的時間超過預估兩倍 → 20
│     ├─ next_step()                              照設定檔順序，第一個沒通過、after 都通過的；skip 的記成通過
│     ├─ 一般步驟 → work(step, job)
│     │  ├─ 有排隊的修法 → run_queue(...)          照結論挑的修法，一個做完才拿掉一個
│     │  ├─ run_cmds(cmd) → call(argv)            subprocess；輸出寫進 wf_logs/<步驟>.log
│     │  ├─ run_cmds(then)
│     │  ├─ 檢查 outputs 都有產出
│     │  └─ 有 check → open_review(...)，沒有 → pass_step(...)
│     └─ 物件迴圈 → work_objects(step, job)
│        ├─ 還有沒做完的物件 → work_object(step, 物件)   依 order 由後往前挑一個
│        │  ├─ run_queue(...) 或這一小步自己的指令（新開、重開、通過後的下一小步、拆完）
│        │  ├─ run_cmds(then)                      L5c：outline --check、split_groups
│        │  └─ open_review(..., stage)             L5a／L5b／L5c
│        ├─ 有物件停住、其他都通過 → 這一步停住
│        └─ 全部通過 → open_review(...)            L6 組裝檢查
│           └─ R.write_packet(...)                 review.py：複製檢查圖、寫 request.json
├─ verdict → Run.verdict(審查包, 檔案)
│  ├─ R.validate(request, verdict, 工作資料夾)     格式、選單、參數型別、禁用、每一筆都要有
│  ├─ 信心低 → 先不執行，等使用者（by: user）再交一次
│  ├─ 物件的小步 → object_verdict(...)            通過、下一小步、或重做（數三層上限、記失敗）
│  │  └─ count_fail(...)                          同一個問題、同一種做法失敗兩次 → 禁用
│  ├─ 其他 → step_verdict(...)
│  │  ├─ 組裝檢查（rounds）數輪數
│  │  ├─ to_objects → open_object(...)；在物件迴圈後面的檢查點 → reopen_objects(...)
│  │  └─ 其他修法排進佇列（rejected）；都通過 → pass_step(...)
│  ├─ R.append_log(llm_checks.md, ...)
│  └─ advance()                                   接著跑到下一個檢查點（--no-run 不跑）
├─ redo → Run.redo(步驟)                          reset(...)；凍結的物件要 --reason
└─ unblock → Run.unblock(步驟, 原因, 多給幾次)
```

## 3. 設定檔 `flows/plate.toml`

目前只做人物（2026-10-02）：`character_only` 一步（`object_fix --drop-objects`，分包之後、物件迴圈之前）拿掉武器和手上的東西；`objects_check`、`integrate` 標 `skip`；部件測試只跑手臂、腿、頭、身體、頭髮五包；交付看 `_motions_phys`。

```toml
[flow]
name = "plate"
work = "{live}/{hero}/{series}"      # 工作資料夾
estimate_min = 120                   # 預估分鐘；用掉超過兩倍就停
docs = { 22b = "Docs/Design/22b_Live2D_Flow.md" }

[flow.vars]                          # 自己加的值，可以用其他值組出來
inx = "{dir}/{name}_st.inx"

[limits]                             # 上限（見第 6 節）

[fix.place_box]                      # 修法：每一種寫一次，步驟用 id 指
stage = "place"
cmd = "python Tools/art/object_place.py {hero} {series} {pick} --as={part} --box={box} --clear={clear}"
params = { box = "box", clear = "layers?" }

[[step]]                             # 步驟，照順序
id = "split_groups"
check = "L4"
...
```

**代入的值**：`{hero}`、`{series}`、`{dir}`（工作資料夾）、`{live}`（`<work>/live`）、`{art_work}`、`{name}`（`<角色>_default` 或 `<角色>_<服裝>`，綁定和檢查圖的名字）、`{godot}`、`{plate_dir}`（立繪所在的資料夾）、`{mv_python}`、`{repo}`；加上 `[flow.vars]`、步驟的 `vars`、`foreach` 的一列、結論的 `params`。物件迴圈裡另有 `{part}`（物件名字）、`{pack}`（它在第幾包）、`{pick}`（L5b 挑中的候選，完整路徑）。

**指令的寫法**：先照空白切成一段一段，再代入，所以帶空白的值（AI 重畫的指令）還是一段。代入後是空的片段整段拿掉：選填的旗標寫成一段 `--weapon={pts}`，沒給就不加。開頭 `python` 換成目前的 Python（`LIVE2D_PYTHON` 可改）。指令前面加 `?`：結束代碼只當提示，寫進審查包的 `hints`（`rig_check`、`object_check`、`rig_stress`、`outline --check`、`char_score flag` 有問題時回 1，22b：看圖，不看數字下結論；`char_score` 的分數寫在 `_score/`，見 22d）；其他指令失敗就停住。`{same}` 是這一步自己的指令（換種子重跑）。

**步驟的欄位**

| 欄位 | 意思 |
|---|---|
| `id` | 名字，`redo` 用 |
| `cmd`、`then` | 指令（一個或一串）；`then` 在 `cmd` 之後、修法之後都會跑 |
| `after` | 要等哪幾步通過 |
| `inputs`、`outputs` | 讀、寫哪些檔（工作資料夾裡的相對路徑，可用 `*`、`{1..6}`）；`inputs` 算指紋，`outputs` 跑完要存在 |
| `check` | 檢查點；沒有就做完直接通過 |
| `images`、`focus` | 審查包要看的圖、注意重點（`22b#L4` 由程式從 22b「各檢查點的注意重點」取那一段的條列） |
| `fix`、`pass_fix` | 沒通過時、通過時可以挑的修法（`[fix]` 的 id；`manual` 每一步都有） |
| `gate = "human"` | 結論一定要 `by: "user"` |
| `per_item`、`items` | 結論要一筆一筆：`items` 是一串名字，或 `groups:parts`（`groups.json` 的每個物件）、`groups:packs`（每一包）、`foreach:pack` |
| `foreach` | 指令和圖照每一列各跑一次，例如 `[{ pack = "arms", phys = "nophys" }, { pack = "hair", phys = "" }]` |
| `after_fix = "cmd"` | 修法做完後重跑這一步自己的指令（預設只跑 `then`） |
| `rounds` | 組裝檢查：`pack`（每一包數輪數）或 `plate`（只數整張） |
| `reopens` | 這個檢查點可以點名重開已通過的物件（L6、L6b、L8～L12） |
| `kind = "each_object"`、`order`、`[[step.stage]]` | 物件迴圈（見第 5 節） |
| `skip = "原因"` | 跳過，原因寫進紀錄 |

**修法的欄位**：`cmd`；`params`（名字 → 型別，`?` 結尾是選填）；`defaults`；`kind`（`opens` 交給物件迴圈、`split` 要再拆、`manual`）；`stage`（物件迴圈裡做完之後停在哪一小步）；`images`（做完要看的圖）；`note`。

**參數型別**：`int`、`ints`（`1,2,3` 或 `[1,2,3]`）、`float`、`text`、`box`（四個整數，x1>x0、y1>y0）、`points`（`[[x,y],...]` 或 `x,y;x,y`）、`layer`／`layers`（工作資料夾裡要有 `st/part_<名字>.png`）、`name`／`names`（新的圖層名字：小寫英文、數字、`_`、`-`）、`file`（工作資料夾裡的檔）、`flag`（`true` 時加上 `--<名字>`）。

## 4. 狀態檔 `run.json`

在工作資料夾，程式自己讀寫，每改一次就整份寫回（先寫暫存檔再換名字，關掉也不會寫壞）。

```json
{
 "flow": "plate", "flow_file": ".../flows/plate.toml", "target": "freya/-",
 "started": "2026-10-02T15:30:45", "elapsed_min": 94.2,
 "blocked": null, "blocked_cap": null,
 "open": { "id": "L5b-6", "step": "objects", "key": "objects/headwear", "stage": "candidates", "since": "..." },
 "counts": { "plate_redos": 14, "plate_rounds": 1, "pack_redos": { "2_hair": 9 }, "pack_rounds": { "arms": 1 },
             "reviews": { "L4": 2, "L5b": 6 } },
 "bonus": { "per_object:objects/headwear": 2 },
 "steps": {
  "see_through": { "status": "passed", "attempts": 1, "review": "L2-1", "fp": { "full.png": "sha256:3f1a..." } },
  "objects/headwear": { "status": "needs_review", "stage": "candidates", "attempts": 7, "redos": 5,
                        "pick": "st/gen/headwear_qf3.png", "last_fix": "edit_slow",
                        "tries": [ { "n": 1, "review": "L5a-3", "verdict": "pass", "fix": [ { "id": "edit_fast" } ] } ],
                        "fails": { "place_fit:misplaced": 2 }, "banned": [ "place_fit:misplaced" ] }
 },
 "manual": [ { "time": "...", "item": "objects/face", "review": "L5c-2", "what": "照下巴線切掉臉的下緣" } ],
 "log": [ "2026-10-02T09:01:00 objects/headwear 進物件迴圈：L4-1 點名" ]
}
```

- **狀態**：`pending`、`running`、`needs_review`、`passed`、`rejected`（有排隊的修法）、`blocked`（`why` 寫原因，`cap` 寫是哪一個上限）。
- **`attempts`** 執行過幾次（步驟的指令或修法）；**`redos`** 被判重做幾次（算上限用的是這個）。
- **`fp`**：通過時輸入檔的指紋；之後不一樣，這一步和它後面的都改回 `pending`，`stale_because` 寫是哪個檔。
- **接著做**：`running` 的步驟重跑一次（佇列裡的修法做完一個才拿掉一個，所以中斷時做到一半的那個會重做）。
- **`elapsed_min`**：工具執行的時間，加上每次等審查的時間（每次最多算 20 分鐘）。

## 5. 物件迴圈

L2、L3 用 `to_objects` 記下的、L4 判重做的、L6／L6b／L8～L12 點名的物件，各自是一件小工作 `objects/<名字>`，照 `order`（由後往前：身體、腿先，手臂、武器、頭髮後）一次做一件。每件照三小步（`[[step.stage]]`）走，每一小步都停下來審：

| 小步 | 檢查點 | 自己的指令 | 通過時 |
|---|---|---|---|
| `outline` | L5a | `outline.py <物件>` | 從 `pass_menu` 挑出候選的做法（`edit_fast`、`mirror`……），或直接改圖層的（`flat`） |
| `candidates` | L5b | （沒有，由上一個結論挑） | `pick` 挑一張候選，再從 `pass_menu` 挑放法（`place_box`、`place_fit`、`apply`……） |
| `place` | L5c | （沒有）；做完自動跑 `outline --check`、`split_groups` | 這個物件通過、凍結 |

- 重做時從這一小步的選單挑；修法的 `stage` 決定做完停在哪一小步（例如在 L5c 改用 `edit_slow` 重畫，就回到 L5b 看候選）。
- 要再拆（`split`）：執行拆法，`new` 寫的新物件各開一件小工作，原本的從 L5a 重來。
- 全部通過（或有的停住）之後，看這一步自己的 L6 組裝檢查，一包一筆。

## 6. 上限和四道保險

| 上限（`[limits]`） | 預設 | 到了 |
|---|---|---|
| `per_object` 一個物件的重做 | 10 | 這個物件停住，其他物件繼續 |
| 一包的物件重做總數：`max(per_pack_min, per_pack_factor × 物件數)` | 6、2 | 這個物件停住（這一包之後每個要重做的都會停） |
| `pack_rounds` 一包的組裝檢查 | 3 | 那一步停住 |
| `plate_redos` 整張的物件重做 | 30 | 整張停住 |
| `plate_rounds` 整張的組裝檢查 | 3 | 整張停住 |
| `step_redos` 一般步驟的重做 | 3 | 那一步停住 |
| 時間：`estimate_min` 的 2 倍 | 120 → 240 | 整張停住 |

1. **次數上限**：上表。`unblock --more N` 讓那一個上限多 N 次（時間是多 N 分鐘），原因寫進紀錄。
2. **同一個做法失敗兩次就禁用**：結論判重做時，「上一次用的修法：問題種類」記一次失敗；兩次就禁用。審查包的 `banned` 列出來，結論再挑它會被退回（這一次的結論剛好是第二次失敗時也算）。問題種類：`unrecognizable` 看不出是什麼、`incomplete` 不完整、`dirty` 有碎片殘影白洞、`misplaced` 位置大小不對、`order` 前後錯、`style` 畫風不對。
3. **通過的物件凍結**：只有標了 `reopens` 的檢查點能用 `to_objects` 點名重開（審查包的 `frozen` 列出凍結的物件）；L4 點名凍結的物件會被退回。手動 `redo objects/<名字>` 要加 `--reason`。重開時物件迴圈後面的每一步都改回 `pending`。
4. **時限**：見上表最後一列。

## 7. 審查包 `reviews/<檢查點>-<第幾次>/`

- `request.json`：`review`、`check`、`title`（例如「L4 部件檢查」，名字取自 22b）、`step`、`item`、`items`（要一筆一筆交的名字）、`images`（複製進來的檔名 `file` 和原本的位置 `from`；之後原檔改了，這裡的不會變）、`missing_images`、`focus`、`history`（這件工作最近十次的結論）、`counts`、`menu`、`pass_menu`、`pass_needs_fix`、`pick`、`banned`、`last_fix`、`fails`、`frozen`、`reopens`、`gate`、`hints`（工具的結束代碼）、`answer_with`（交結論的指令）、`verdict_template`（結論的空白範本）。
- `verdict.json`：審查的人寫（使用者改判另存 `verdict_user.json`）。

```json
{
 "review": "L5b-6",
 "items": [ { "item": "objects/headwear", "verdict": "pass", "reason": "gen_headwear_qf.jpg 第 3 張帽子完整",
              "pick": "st/gen/headwear_qf3.png",
              "fix": { "id": "place_box", "params": { "box": [133, 2, 621, 240] }, "why": "帽簷停在眼睛上方" } } ],
 "confidence": "high",
 "by": "claude-code"
}
```

程式檢查（不合就整份退回、什麼都不執行）：`review` 對得上；`confidence` 是 `high` 或 `low`；`by` 有寫，要使用者的地方是 `user`；`items` 每一個要的名字剛好一筆；`verdict` 是 `pass`、`redo`、`split`；`reason` 有寫，不通過的要提到審查包裡某一張圖的檔名；不通過的 `problem` 是六種之一、一定要有 `fix`；`fix`（一個或一串）在選單裡、沒被禁用、參數型別對；`split` 要有拆法；L5b 通過要有 `pick`；下一小步沒有自己的指令時，通過要從 `pass_menu` 挑做法。`confidence: low` 時程式先不執行，等使用者看過用 `by: "user"` 再交一次。

## 8. `llm_checks.md`

每個被接受的結論在工作資料夾的 `llm_checks.md` 加一段，格式跟手寫的一樣：

```
## L4 部件檢查（2026-10-02 09:06）

- 審查包：`reviews/L4-1`（split_groups；claude-code，信心 high）
- 看了：st_groups_parts_1.jpg、st_groups_parts_2.jpg、…
- 結論：**沒通過 → 重做**
  - 通過：face、neck、…
  - headwear：重做（有碎片、殘影或白洞）：st_groups_parts_1.jpg 帽子那格右邊的紅色帽簷不見了。修法：`to_objects`
- 次數：這一步 0/3、組裝輪數 0/3、整張 0/30。
```

使用者改判的那一筆另外標「使用者改判」。

## 9. Claude Code 對話怎麼用（第一階段）

1. 在背景執行 `python Tools/wf run freya/-`，等它結束。
2. 結束代碼 `10`：讀 `REVIEW` 那一行的 `request.json`，照 `images` 一張一張看圖（看審查包資料夾裡的複本），照 `focus` 逐條對，參考 `history`、`hints`。
3. 照 `verdict_template` 寫 `verdict.json`（放在審查包資料夾），執行 `answer_with` 那一行（也在背景，它會接著跑工具）。被退回（結束代碼 `2`）就照印出的原因改了再交。
4. 結束代碼 `20`：停住了，把原因和 `python Tools/wf status freya/-` 的結果交給使用者；使用者決定後才 `unblock`。L0（選立繪）、L14（交付）一定要使用者點頭，結論的 `by` 寫 `user`。
5. 選單外的修法（`manual`）：先直接改檔，再交 `{"id": "manual", "params": {"what": "改了什麼"}}`；程式記在 `run.json` 的 `manual`，`status` 會列出來，交付時給使用者看。

## 10. 測試

`Tools/wf/tests/test_wf.py`（`Tools/run_tests.sh` 會跑）：用 `fake_flow.toml`，每個指令都是 `stub.py` 寫小檔案，工作資料夾是暫存資料夾（`ART_WORK`），不用顯示卡、ComfyUI、Godot。測：整條跑完（審查包、修法、選立繪和交付要使用者）、修法執行後再審、結論格式的每一種退回、信心低等使用者、物件到上限停住再解開、同一個做法失敗兩次禁用、輸入改了下游重做、中斷後接著做、時限、凍結物件只能由組裝檢查重開，以及 `flows/plate.toml` 每個指令、修法、注意重點都代入得出來（不執行）。
