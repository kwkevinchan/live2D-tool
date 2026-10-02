# 驗：檢查與預覽

驗收順序（`Docs/Design/22b`）：每個物件完整 → 一包組起來 → 整體組起來 → 動作。人物、武器和物件分開驗，各自通過才整合。

| 檢查 | 程式 | 流程甲 |
|---|---|---|
| 部件、組裝 | `split_groups.py`（見 [03_Packs.md](03_Packs.md)） | 2 |
| 物件完整 | `outline.py --check`（見 [04_Repair.md](04_Repair.md)） | 物件迴圈 |
| 綁定後跟原圖比 | `rig_check.py` | 5 |
| 動態截圖 | `puppet_preview.tscn` | 5 |
| 人物的標準動作 | `motion_test.tscn ... bare` | 6 |
| 武器與物件 | `object_check.py` | 7 |
| 整合 | `motion_test.tscn` | 8 |
| 關節壓力測試 | `rig_stress.py` | （分段手腳時） |
| 技能預覽 | `skill_preview.tscn` | 甲之後 |
| 程式能跑、播放器規則 | `Tools/run_tests.sh`（含 `puppet_test.tscn`） | 每次提交前 |
| 自動審圖 | `review_plate.py` | 關鍵姿勢拆完 |

Godot 場景除了 `puppet_test` 都要開視窗，加 `--audio-driver Dummy` 免得出聲。下面的 `<Godot>` 是設定檔 `[paths] godot` 那支。

---

## 1. 畫出模型（`Tests/live/rig_render.gd`）

`rig_check.py` 和 `rig_stress.py` 共用：照立繪大小把模型畫成圖片。

```
<Godot> --path . res://Tests/live/rig_render.tscn -- <模型.inx>=<輸出.png>=<寬>x<高>[=<參數>:<值>;...] ...
<Godot> --path . res://Tests/live/rig_render.tscn -- @<工作清單檔>      一行一個（Windows 的指令長度有上限）
```

每個工作：建一個透明背景的畫面、模型原點放在畫面中心（剛好對上立繪）、設定參數（二維參數寫 `x,y`；沒寫的維持預設）、算一格（不跑物理）、等三格畫完後存檔。有失敗時結束代碼 1。

## 2. 跟原圖比（`Tools/art/rig_check.py`）

```
python Tools/art/rig_check.py                      工作資料夾裡每個綁好的資料夾
python Tools/art/rig_check.py rena yukino/pose_open
```

```
main(args)
├─ folders(args)                                  每個要檢查的資料夾
│  └─ model_and_plate(hero, series, ld)           最新的 .inx、立繪
├─ subprocess：<Godot> rig_render.tscn -- 模型=輸出=寬x高 ...   一次畫全部
│  └─ rig_render.gd：_ready → _render(...) × 每個模型
└─ 每個模型
   ├─ compare(plate, render)                      缺少／顏色不對／多出來
   └─ 存 <名稱>_check.jpg，併進 rig_check.json
```

1. **`folders(args)`**：要檢查的資料夾（裡面有 `.inx` 的）。只給角色時檢查她所有的資料夾。
2. **`model_and_plate`**：資料夾裡最新的 `.inx`，和它的立繪。
3. 一次啟動 Godot 畫出全部（靜止姿勢）。
4. **`compare(plate, render)`**：逐點比，人物輪廓內外 3 像素不算（縮放造成的邊緣差異）：
   - 缺少（藍）：立繪有、模型沒畫；
   - 顏色不對（紅）：RGB 差的總和超過 90；
   - 多出來（綠）：人物外面有畫。
   單獨的像素先去掉；相連的差異區域取最大的五塊。差異超過人物的 0.5%（`FLAG_SHARE`），或最大一塊超過 0.1%（`FLAG_AREA`），標為有問題（大塊用黃框標出）。
5. 產出在 `<work>/live/check/`：`<名稱>_check.jpg`、`rig_check.json`（跟舊的結果合併，不會洗掉別的資料夾）。有問題時結束代碼 1。

這個檢查拿「像不像原圖」當標準，現在只當參考（見總覽）。

## 3. 轉關節找破洞（`Tools/art/rig_stress.py`）

```
python Tools/art/rig_stress.py freya/pose_apose [更多資料夾]
python Tools/art/rig_stress.py --find-ranges freya/pose_apose
```

給分段手腳的模型用（沒有關節參數的會跳過）。

```
main(args)
└─ folders(args) → model_and_plate(...)           （從 rig_check 借來）
   ├─ model_params(inx) → joint_params(names)      沒有關節參數 → 跳過
   ├─ --find-ranges → find_ranges(ld, model, plate, name)
   │  ├─ pose(pname, angle) × 每 0.1 弧度          full_turn、range_key
   │  ├─ render(model, plate, todo, name)
   │  ├─ Judge(ld, plate, 靜止圖)
   │  ├─ judge(img, pname, value) × 每個姿勢，到第一個失敗為止
   │  └─ 寫 parts.json 的 ranges
   └─ 一般
      ├─ poses(names, ranges)                     每個關節兩端
      ├─ render(model, plate, todo, name)         寫工作清單檔 → <Godot> rig_render.tscn -- @清單
      ├─ Judge(ld, plate, 靜止圖)
      │  ├─ body_area(ld, plate_alpha)
      │  └─ load_meta(ld)                         關節附近的範圍
      ├─ 每個姿勢：judge(img, pname, value)
      │  ├─ holes(rest, posed, body, near_joints) （轉腰時用 lower_area）
      │  ├─ moved_pieces(ld, pname, value, rest_rgb)
      │  └─ ghosts(old, new, rest_rgb, posed)
      └─ 存 <名稱>_stress.jpg
```

1. **`model_params`**：直接讀 `.inx` 的 JSON 區段拿參數名字。
2. **`poses`**：每個關節參數（`…:: Shoulder / Elbow / Wrist / Hip / Knee / Ankle / Lean`、`Weapon:: Turn`）各轉到兩端。範圍用 `parts.json` 的 `ranges`，沒有就用綁定的全範圍（`inx_rig` 的旋轉常數）。
3. 一次啟動 Godot 畫出「靜止」加每個姿勢（用工作清單檔）。
4. **`Judge`** 判斷每張：
   - **`body_area`**：不會動的層（手臂、手、武器、腿以外）合起來、補小縫、填滿內部，就是「身體範圍」。
   - **破洞 `holes`**：靜止時有畫、轉動後變透明、而且在身體範圍內（手臂移開後底下沒補）；加上關節附近（40 像素內）轉動後才出現的窄縫（4 像素以下）。手臂移開後露出人物外面的背景是正常的。轉腰時改看裙子和腿的範圍。
   - **殘影 `ghosts`**：**`moved_pieces`** 算出這個關節以下的零件（例如轉肩膀＝上臂、前臂、手，加上手上的武器）靜止時在哪、照綁定的角度轉過去後在哪；舊位置上現在沒有零件、卻還顯示跟靜止時一樣的顏色，就是殘影（例如手指留在身體層裡）。太細的帶子不算。
   - 單一破洞或殘影超過人物的 0.05%（`HOLE_AREA`）標為有問題。
5. 產出：`<work>/live/check/<名稱>_stress.jpg`（每個姿勢一格，破洞洋紅、殘影青色），每個姿勢印一行。有問題時結束代碼 1。

**`--find-ranges`**：每個關節從 0 開始每次多轉 0.1 弧度，兩個方向各自轉到第一個出問題的角度為止，最後一個通過的角度寫進 `parts.json` 的 `ranges`（例如 `"shoulder_r": [-0.6, 1.2]`）。技能動作要在這個範圍內。

## 4. 武器與物件（`Tools/art/object_check.py`）

```
python Tools/art/object_check.py <角色> <服裝>
```

先執行 `split_groups.py`（要讀 `groups.json`）。

```
main(hero, series)
├─ 讀 groups.json、parts.json、inx_rig.load_joints   握點
├─ 武器：5_weapon/ 的各層合成一張
├─ 其他：6_other/ 的每一層，scipy ndimage.label 拆成一件一件
└─ 每件
   ├─ whole(alpha)                                幾塊、浮動、洞
   ├─ 每 15 度轉一次（split_groups.checker、label）→ object_<名稱>.gif
   └─ 每 30 度一格 → objects_check.jpg 的一列
   寫 objects.json
```

- **武器**：武器包的各層（`objects`＋`objects-back`）合成一個東西，在握點轉。
- **其他物件**：「其他」包裡每一個分開的東西（300 像素以上）各算一件，在自己的中心轉。

每件檢查：

- **`whole(alpha)`**：分成幾塊（60 像素以下的碎點不算；中心落在最大塊凸包裡的小塊算同一個東西，記為「浮動」，例如杖頭的寶珠）、輪廓內的洞有多大（有浮動小塊時，它所在的那個開口不算洞：杖頭圓環裡的空間是設計，2026-10-02）。
- 武器要一整塊、要有握點；洞超過面積的 1%（至少 40 像素）算有問題。
- 每 15 度轉一格做成動圖，每 30 度一格排成檢查圖。

產出（`st/groups/objects/`）：`object_<名稱>.gif`、`objects_check.jpg`、`objects.json`（每件的數字和是否通過）。沒有武器也算沒通過。沒通過時結束代碼 1。

## 5. 標準動作（`Tests/live/motion_test.gd`）

```
<Godot> --path . res://Tests/live/motion_test.tscn -- <模型.inx> <輸出資料夾> [動作 ...] [bare] [nophys] [pack=<包>]
```

```
_ready()
├─ InochiPuppet.new() → load_model → add_child → set_process(false)
├─ _fit()                                         縮放置中
├─ 記下每個參數的預設值；nophys → 關掉擺動
├─ pack=<包> → 只留 PACKS[包] 的零件，_sweep = 這包的參數，_record("pack") → pack_<包>/，結束
├─ bare → 關掉武器和物件的節點
├─ _record(motion) × 每個動作
│  └─ 每一格
│     ├─ 參數回到預設；_put("Breath", ...)
│     ├─ _m_<動作>(t)                             各動作自己設參數
│     │  ├─ _put(name, v)                          模型沒有 → 記進缺少清單
│     │  ├─ _limb(name, v, 說明)                   分段手腳的參數
│     │  ├─ _legs(step, hip, knee)                 走路、跑步的腿
│     │  └─ _blink(t, at)
│     ├─ puppet.update_puppet(1/30)
│     └─ 每兩格存 anim_*.png
└─ 寫 report.json
```

每個模型跑同一套十個動作，每個 4 秒（每秒 30 格，每兩格存一張 `<輸出>/<動作>/anim_*.png`）：

| 動作 | 內容 | 用到的參數 |
|---|---|---|
| `walk` 走路 | 上下起伏、左右晃、手臂反向擺、膝蓋輪流彎 | `Arm:: * :: Move`、`Head:: Pitch`、`Leg:: *` |
| `jump` 跳躍 | 蹲、跳、落地壓扁，兩次 | `Arm:: * :: Move`、`Leg:: *` |
| `run` 跑步 | 快步、前傾、手肘彎 | `Arm:: * :: Elbow`、`Head:: Yaw / Pitch`、`Leg:: *` |
| `wave` 揮手 | 右手舉起揮動 | `Arm:: Right:: Shoulder / Elbow / Move`、`Head:: Roll`、`Mouth:: Open` |
| `head` 頭部動作 | 右轉、左轉、點頭、歪頭 | `Head:: Yaw / Pitch / Roll` |
| `face` 眨眼與表情 | 眨眼、看旁邊、揚眉、說話 | `Eye:: Blink / Look`、`Brow:: Up`、`Mouth:: Open` |
| `idle` 呼吸待機 | 呼吸、眨眼、慢慢看 | `Eye:: *`、`Head:: Yaw` |
| `hair` 甩頭 | 快速左右轉頭兩秒後停：看頭髮擺動和停下來 | `Head:: Yaw` |
| `hit` 受擊 | 一秒時被打退：身體震、頭甩、閉眼 | `Head:: Yaw / Roll`、`Eye:: Blink` |
| `glance` 轉身看 | 眼睛先動、頭跟上、再轉回來 | `Eye:: Look / Blink`、`Head:: Yaw` |

- 全部都有 `Breath`。跳躍、跑步、受擊用 `root_offset`、`root_scale` 移動整個模型（物理才感覺得到）。
- 每個動作從模型的預設值開始。模型缺的參數記在 `report.json`（`{動作: {name, missing}}`）；分段手腳缺的記成「手臂分段」「腿分段」這類說明。
- **`bare`**：關掉 `Weapon`、`Weapon Back`、`Body Accessory` 和所有 `Other …` 部件，先驗人物本身（第 6 步）；不加就是整合驗證（第 8 步）。
- **`nophys`**：關掉所有擺動（頭髮、裙子、披風不動），先看關節，再打開看擺動。
- 每個動作寫 `frames.json`（每張存檔的參數值、整個模型的移動），`Tools/art/motion_sheet.py <資料夾> [--max N]` 挑出參數最大、最小、移動最多的幾格，原尺寸排成 `sheet_<動作>.jpg`（LLM 讀圖時動圖只看得到第一格，所以 L9、L11 看這張）。工作室另外把截圖做成動圖給人看。
- **`pack=<包>`（部件動作測試，22b 第 4b 步、L6b）**：只畫 `PACKS` 裡這一包的零件（照節點名稱開頭比對：`arms`、`legs`、`head`、`body`、`weapon`、`held`），把這包的參數（照參數名稱開頭比對、跳過被擺動帶動的）一個一個轉：每個 `PACK_SWEEP`（1.2 秒）0 → +1 → -1 → 0，不加呼吸。存在 `<輸出>/pack_<包>/`，同樣寫 `frames.json`，用 `motion_sheet.py --max 16` 做總表。

## 6. 單一模型預覽（`Tests/live/puppet_preview.gd`）

```
<Godot> --path . res://Tests/live/puppet_preview.tscn -- <模型.inx> <輸出資料夾> [參數=值 ...] [secs=30] [motion=jump|run] [probe=x,y]
```

```
_ready()
├─ load_model → add_child → _fit()
├─ 參數=值 → set_param、記成固定；probe=x,y → _probe(畫面座標)
└─ motion= → _run_motion(kind)  ／  secs= → _run_long(secs)  ／  其他 → _run()
   └─ 每一格：_set_first(名字清單, 值) → update_puppet(1/30) → 存圖
```

載入後印出載入時間、節點數、參數名字，縮放置中，然後選一種：

- **預設 `_run`**：五秒內掃過轉頭、眨眼、張嘴、呼吸，存 `000_rest.png`、`030_yaw_right.png`、`060_yaw_left_blink.png`、`090_mouth_open.png`、`150_settled.png`，印出每格平均計算時間。
- **`secs=N` `_run_long`**：待機 N 秒（呼吸、眨眼、東張西望、偶爾說話、身體和手臂小動），存動圖用的連續畫面。
- **`motion=jump|run` `_run_motion`**：跳三下或來回跑 12 秒，頭髮跟著甩。
- `參數=值`：整段固定這個參數（二維寫 `x,y`）。
- `probe=x,y`：印出畫面這一點畫的是哪些部件（查錯用）。

參數名字會依序試好幾種寫法（自動綁定的和手工模型的都認得）。工作室的「動態截圖」就是這個預設模式。

## 7. 技能預覽（`Tests/live/skill_preview.gd`）

```
<Godot> --path . res://Tests/live/skill_preview.tscn -- <輸出資料夾> style=bow|fire|frost|slam idle=<模型> <姿勢>=<模型> ...
```

```
_ready()
├─ 讀參數（style、每個姿勢的模型）
├─ LivePortrait.new() → add_pose(姿勢, 模型) × 每個姿勢（缺的用 idle）
│  ├─ _read_aim(inx)                              握點、方向
│  └─ _read_tips(inx)                             武器兩端
├─ _fit()
└─ _run()  120 格
   ├─ 到了格數 → lp.play_pose(姿勢, hold)
   ├─ 聚光期間：_gather_point() → _aim_point(pose) / _weapon_tip(pose, top)
   ├─ 放出那一格：_release(at, dir)
   ├─ fx 節點每格 _draw_fx()
   └─ 每兩格存圖
```

用 `LivePortrait` 在關鍵姿勢之間切換，加上特效：武器手聚光 → 放出（箭、火球、冰霜、砸地）→ 閃光和小震動。缺的姿勢用待機代替。跑 120 格，每兩格存一張。

| 技能 | 姿勢與開始的格數 | 聚光 | 放出 |
|---|---|---|---|
| `bow`（艾莉西亞） | raise 30、draw 42、release 63（0.6 秒後回待機） | draw 的手，42～63 | 63，射箭光軌 |
| `fire`（芙蕾雅） | raise 30、cast 45、recover 56（0.4 秒） | raise 的杖頂，32～45 | 49，火球從 cast 的杖頂飛出 |
| `frost`（雪乃） | open 30、sweep 40、point 52（0.3 秒） | open 的手，31～40 | 46，冰霜弧線加冰晶 |
| `slam`（蕾娜） | windup 30、slam 44、impact 50（0.4 秒） | windup 的扳手頂端，31～44 | 49，扳手最低點的衝擊圈加火花 |

- **`_read_aim`**：從模型旁邊的 `fig_joints.json` 讀握點，和「遠離另一隻手」的方向（箭、火球飛的方向）。
- **`_read_tips`**：武器層最上、最下那一點（杖頭、扳手頭）。
- 位置換算（`_aim_point`、`_weapon_tip`）都會經過該姿勢在 `LivePortrait` 裡的對齊（縮放、位移）。

## 8. 播放器測試（`Tests/live/puppet_test.gd`）

```
<Godot> --headless --path . res://Tests/live/puppet_test.tscn
Tools/run_tests.sh                 所有 Python 程式能編譯、能匯入，再跑這個測試
```

不需要視窗，也不讀檔案：在程式裡組小模型，檢查播放器的規則，印出「N checks, M failures」，有失敗時結束代碼 1。

```
_ready()
├─ _bindings()           ┐
├─ _order_and_masks()    │ 用 _part / _param / _tr 組 JSON → _puppet(nodes, params) → load_payload
├─ _physics()            ┘ 每項結果交給 check(條件, 說明)
├─ _portrait()           LivePortrait：talk、play_pose、pose_finished、快速切回
└─ _self_update()        LivePortrait.add_pose_puppet 之後模型不會自己更新
```

- **`_bindings`**：一維線性、二維雙線性、網格變形只動綁到的頂點、透明度、超出範圍時截斷。
- **`_order_and_masks`**：前後順序、`zSort` 參數交換順序、遮罩容器、組合裡的「只畫在下面那層上」。
- **`_physics`**：靜止時穩定、模型移動時頭髮擺動、之後再停下來。
- **`_portrait`**：說話時嘴巴會動、計時姿勢到時間回待機並發出通知、淡入淡出中快速切回來時目前的姿勢仍然顯示。
- **`_self_update`**：由 `LivePortrait` 驅動的模型不會自己再更新一次（否則物理一格跑兩次）。

## 9. 自動審圖（`Tools/art/review_plate.py`）

```
python Tools/art/review_plate.py <角色> [姿勢 ...]        關鍵姿勢資料夾 → review.jpg、review.json
python Tools/art/review_plate.py cand <角色> <動作>       關鍵姿勢的候選 → <work>/poses/<角色>/<動作>/review_<姿勢>.jpg
```

拆層之前抓畫錯的地方（多一條腿、多一把武器、武器浮在空中）。從 towerD 原樣搬來。

```
review_folder(hero, pose)
├─ 讀 full.png、pose.json → key_poses.POSES      畫圖時的骨架
├─ skeleton_overlay(plate, pts)                   立繪疊骨架
├─ group_map(d, size)                             拆層依群組上色，數武器塊數、鞋子、手臂、臉、前髮、腳底、雜物比例
│  └─ pieces(mask, min_share)
└─ sheet(title, panels, lines, warn, out)         三格：立繪 ｜ 疊骨架 ｜ 群組上色

review_candidates(hero, action)                   每張候選疊上骨架
```

其中「圖層疊回去跟原圖不同」這一項也是拿原圖當標準，只當參考。
