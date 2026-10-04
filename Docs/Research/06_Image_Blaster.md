# image-blaster：一張圖變成 3D 場景（Claude 技能組）

整理日期：2026-10-04。回到 [研究總覽](README.md)。專案 2026-04 建立，約 6,600 顆星，MIT 授權。

## 一句話

一組給 Claude Code 用的技能：把一張**場景**圖變成可以走進去的 3D 環境（高斯點雲）、場景裡每個可移動物件的 3D 模型，以及環境音和物件音效。全部用雲端付費服務，五分鐘內完成。**不是做角色的。**

## 怎麼做

1. **看圖列物件**（`image-blast-uncover`）：Claude 自己看圖，用「照實描述」的語言列出可以單獨拿起來或推動的物件（地毯、牆、地板不算；不准把桌子和椅子當成一組）。每個物件寫一份描述檔，**停下來給使用者確認**要做哪些。
2. **清乾淨的底圖**（`image-blast-plate`）：用圖像編輯把確認的物件**一次全部**從原圖拿掉，得到沒有物件的場景圖。指令只說「拿掉什麼」，不說要留什麼、不說怎麼補。
3. **場景 3D**：清乾淨的底圖送 World Labs 的 Marble，生成可以走的高斯點雲。
4. **每個物件 3D**（`image-blast-3d`）：
   - 先用圖像編輯做一張**單一物件的乾淨參考圖**：「把某某從圖裡分離出來，照原樣（顏色、材質、比例），白底、置中、裁緊、棚拍光，沒有其他物件、沒有人、沒有字、地上沒有影子；跟它疊在一起或放在它上面的東西都拿掉」。只要一個，不要一對、一組。
   - 參考圖送混元 3D（透過 FAL）或 Meshy 生成網格；預設 5 萬面、有材質。
   - 參考圖會留著重用；要重做模型時不重做參考圖。
5. **音效**：ElevenLabs 生成環境循環音和物件音效。

**用到的模型（都是雲端）：**
- 圖像編輯：nano-banana（Google Gemini 的圖像模型，預設）、gpt-image-2（備用）。
- 3D 物件：混元 3D（FAL）、Meshy。
- 場景：World Labs Marble。
- 音效：ElevenLabs。

## 對我們的意義

**不能直接用**：它做的是場景和道具，沒有角色的骨架、動作、表情。

**用得上的兩點：**

1. **「單一物件的乾淨參考圖」的指令和流程**：跟我們物件迴圈裡的 AI 重畫是同一件事。差別在它用的是雲端最強的圖像編輯（Gemini、GPT 的圖像模型），我們用本機的 Qwen 快速版。我們遇到的問題（畫成一般的樣子、比例不對、多畫東西），換成更強的模型可能少很多。這跟之前還沒決定的「要不要用付費的 Gemini」是同一個問題。
2. **先清乾淨底圖、再做其他事**：等於我們流程改進第 3 項「拆層之前先處理立繪（擦掉手上的東西）」。它的做法是一次編輯拿掉全部，指令只說拿掉什麼。

**對 3D 方向的補充：** 它呼叫 Meshy 的設定裡有「綁骨架」和「套動作」的選項（以 1.7 公尺高的人形綁），也就是**雲端有現成的「圖片 → 有骨架、會動的 3D 角色」服務**，不受我們 16 GB 顯示卡的限制。混元 3D 新版（3.x）沒有公開，但能透過 FAL 用。價錢沒查。

## 價錢（2026-10-04 查）

除了 Meshy 的點數表來自官方文件，其他多是第三方整理的數字，買之前要到官方頁再確認。

**圖轉 3D 角色（含綁骨架、套動作）**

| 服務 | 圖轉 3D（有貼圖） | 綁骨架 | 每個動作 | 一個角色加 10 個動作 |
|---|---|---|---|---|
| Meshy | 30 點 | 5 點 | 3 點 | 65 點，約 1.3 美元（照 Pro 方案每月 20 美元 1,000 點換算） |
| Tripo | 30 點 | 25 點 | 10 點 | 155 點，約 1.6 美元（1 點 = 0.01 美元；新用戶送 2,000 點） |
| 混元 3D 3.1（FAL） | 0.375 美元（快速版 0.225）；材質加 0.15、拆零件加 0.45 | 沒有 | 沒有 | 只有模型，約 0.5–1 美元 |

- Meshy 的點數：官方文件寫綁骨架 5 點、動作每個 3 點；有些介紹文章說免費，以官方為準。點數換美元的比例官方文件沒寫，上表用介紹文章的 Pro 方案換算。
- Tripo 的網頁方案：專業版每月 49.9 美元 3,000 點、高級版 139.9 美元 8,000 點。
- 輸出的商用授權各方案不同，沒查。

**圖像編輯（做物件參考圖、清底圖）**

| 模型 | 每張 |
|---|---|
| Gemini 2.5 Flash Image（初代 nano-banana） | 0.039 美元（批次 0.0195） |
| Gemini 3.1 Flash Image（nano-banana 2） | 1K 0.067、2K 0.101、4K 0.151 美元 |
| Gemini 3 Pro Image（nano-banana Pro） | 1K／2K 0.134、4K 0.24 美元；FAL 上編輯每次 0.15 |
| GPT Image 2 | 依解析度和服務商約 0.01–0.06 美元；有參考圖的編輯會貴 2–3 倍 |

**換算成我們的用量（估計）：**
- 一張立繪的物件迴圈：約 30 個物件 × 3 張 ≈ 90 次編輯。用 Gemini 3.1 Flash 2K 約 9 美元，用 Pro 約 12 美元。
- 一個 3D 角色加 10 個動作：Meshy 或 Tripo 約 1.5 美元，但動漫角色的品質不知道，要先試。

## 來源

- [neilsonnn/image-blaster](https://github.com/neilsonnn/image-blaster)：`README.md`、`.claude/skills/image-blast-uncover/SKILL.md`、`image-blast-plate/SKILL.md`、`image-blast-3d/SKILL.md`
- 價錢：[Meshy API Pricing（官方）](https://docs.meshy.ai/en/api/pricing)、[Meshy credits guide](https://www.meshy.ai/tutorials/meshy-credits-guide)、[Meshy API pricing explained](https://meshyiai.com/api-pricing/)、[Tripo pricing](https://developers.tripo3d.ai/en/pricing)、[Tripo credits guide](https://www.tripo3d.ai/getting-started/zero-to-3d-getting-started-credits-pricing-guide)、[Hunyuan 3D on fal](https://fal.ai/hunyuan-3d)、[Hunyuan 3D Pro image-to-3D on fal](https://fal.ai/models/fal-ai/hunyuan-3d/v3.1/pro/image-to-3d)、[Nano Banana pricing](https://benchlm.ai/media-pricing/nano-banana)、[Nano Banana Pro pricing](https://www.pixmind.io/posts/nano-banana-pro-pricing-guide-2026)、[GPT Image 2 pricing](https://aireiter.com/blog/gpt-image-2-api-pricing)、[GPT Image 2 per-image breakdown](https://www.hiapi.ai/en/blog/gpt-image-2-api-pricing)
