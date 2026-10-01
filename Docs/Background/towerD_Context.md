# 背景：這套工具在 towerD 的來龍去脈

這套工具是從遊戲《星晶守望者》（towerD）裡長出來的。下面摘錄 towerD 文件裡跟「會動的立繪」有關、搬出來之後仍然有用的部分，每段標明原始出處（towerD 版本庫，2026-10-02 的 `explore` 分支）。towerD 的其他設計文件講的是遊戲本身，沒有搬過來。

## 1. 最早的決定：Live2D-lite（2026-09，已被取代）

出處：towerD `Docs/Design/00_Overview.md` 決策 D4、`Docs/Design/02_Heroines.md` 第 6 節。

- **決策 D4**：先做「Live2D-lite」：AI 立繪＋閉眼差分＋shader 形變（呼吸、搖擺、髮絲），用 `HeroinePortrait` 介面包起來，之後可以換成真正的 Live2D。當時沒做真正的 Live2D，是因為需要 Cubism Editor 和人工綁定。
- **呼叫端介面**（之後換實作時要相容）：`HeroinePortrait` 對外是 `heroine_id`、`bust`、`look_at_mouse`、`skin`、`play(state)`、`series()`；狀態有 `IDLE`、`HAPPY`、`HURT`、`CAST`、`SHY`。表情是淡入另一張表情立繪（`full_<表情>.png`）。
- **Live2D-lite 的待機動作**（shader 版，給新做法當參考值）：呼吸週期 3.6 秒、胸口上升約 1.4 px；對位站姿（髖左右移、肩反向）週期 6.5 秒；頭以頸為軸側傾 ±1.4°；髮和衣襬延遲跟著頭和身體；眨眼約 0.14 秒。

2026-09-29 改成用 **Inochi2D**（開源，有 Inochi Creator 可以手動綁定；遊戲裡用自己寫的 GDScript 播放器讀 `.inx`，手機也能跑）。之後從「人工在 Inochi Creator 綁定」再改成這個工具包的「自動拆層、自動綁定」。演變過程見 `Docs/Design/22_Live2D_Inochi2D.md`。

## 2. 立繪的規格（輸入）

出處：towerD `Docs/Design/02_Heroines.md` 6.1、`Docs/Design/10_Phase5_Skins.md`。

- 全身立繪：去背 PNG，裁切後約 700～850 × 1190，四周約 12 px 透明邊，7～8 頭身。
- 閉眼差分：同一張全身圖只重畫眼睛，羽化貼回，其餘像素相同（`full_blink.png`）。
- 同一個角色的每套服裝（skin）以預設立繪為底只換衣服，**身體位置和大小跟預設立繪一致**，這樣同一套動作參數可以沿用。
- 畫立繪的模型：`waiIllustriousSDXL_v170`＋該角色的角色專屬微調（LoRA）；舊的立繪用 Pony 系的 `autismmixSDXL`。

## 3. 角色內容界線（照抄，不能改寫）

出處：towerD `Docs/Design/14_ArtStyle.md` 第 6 節（內容界線）。這套工具做出來的所有角色、AI 重畫的所有物件，都要遵守：

1. Every character is unambiguously an ADULT woman. Youngest is 21. No high-school girls, no school uniforms, no sailor/blazer/pleated-uniform looks, no student/"JK" framing, no childlike bodies, faces, proportions or behaviour, no "loli" styling. Adult body proportions (about 7-8 heads tall) and mature adult faces for everyone, including battle sprites (NO chibi/super-deformed heroines; the battle mini-sprite is a downscale of the adult full-body art).
2. Fanservice is fine up to lingerie & sleepwear, but NO nudity: no exposed nipples or genitals, no fabric that is see-through over nipples or genitals, no open-cup / crotchless designs, no bondage/harness gear, no sex acts, no explicit or spread poses. Level = mainstream gacha swimsuit/lingerie event art.
3. Allowed at the top (lingerie) tier: lace bra-and-panty sets, babydolls, garter belts with stockings, silk slips/chemises, sheer robes worn OVER opaque lingerie.
4. If an image looks underage, nude, or explicit → discard and regenerate.

towerD 的專案說明另外寫明：英雄角色一律是明確的成年人（二十多歲），造型可以性感，但不能裸露。乳搖等胸部擺動只用在衣著完整的成年角色，而且幅度要小。

## 4. 跟美術工作室的分工

出處：towerD `Docs/ArtStudio_Manual.md`、2026-10-01 的交接。

- towerD 的「美術工作室」（`Tools/studio`，網址 :7860）負責畫立繪、訓練角色微調、表情、Q 版、塔和敵人的圖。
- 「會動的立繪」從 2026-10-01 起由這套工具負責（工作室 :7861，`Tools/live2d_studio`）。美術工作室原本的 Live 2D、動畫、技能姿勢分頁已經拿掉。
- 兩邊共用 ComfyUI（:8188）和同一張顯示卡：要跑很久的工作前先跟對方說，並看佇列。
- 兩邊都用到 `comfy_gen.py`、`workflows.py`：搬出來之後兩邊各有一份，修改時要注意同步。

## 5. 哪個模型適合畫什麼

出處：2026-10-01 美術工作室和這邊的實測（記憶整理）。

- **人物**：`waiIllustriousSDXL_v170`＋角色專屬微調。
- **物件、武器、建築、道具**：SDXL 照文字畫不出來（會畫成機器人、符號、人）。改用 **Mage-Flow-Edit-Turbo** 從既有的圖改（英文命令句、白底、一張約 3 秒、大約一半照做，每次跑 3～4 張）。
- **Gemma 4**：只能看圖、輸出文字，不能畫圖。可以用來審圖（物件是否符合描述）或把中文說明轉成提示詞。

## 6. 當時的硬體與環境

- 顯示卡 RTX 5060 Ti 16 GB；記憶體 31 GB。
- ComfyUI 0.38.0（StabilityMatrix 安裝），Godot 4.7.2。
- 網路有流量限制：下載超過約 5 GB 要先問。
