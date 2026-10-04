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

## 最新模型和官方價目（2026-10-04 查官方頁）

**圖轉 3D**

| 服務 | 最新模型 | 官方價格 |
|---|---|---|
| Meshy | Meshy 7.1（2026-09；7 是 2026-08） | 點數：圖轉 3D 只有網格 20、加 2K/4K 貼圖 30、8K 35；幾何 2K/4K 精度另加 5；重拓樸 5；**綁骨架 5；動作每個 3**（一次最多 10 個）。方案：免費 0 美元 100 點（作品是 CC BY 4.0，要標出處，不能用 API）；Pro 20 美元 1,000 點；Premium 40 美元 3,000 點；Ultra 100 美元 8,000 點（付費方案有 API、作品可私有）；Studio 每席 70 美元起（5,500 點）。新訂閱首月半價 |
| Tripo | P2.0（2026-09-21，原生四邊形網格，三角面最多 5 萬）；H3.1、P1.0（2026-03） | 1 點 = 0.01 美元。圖轉 3D 只有網格 20、有貼圖 30；高清貼圖 +10、超清 +20、高清幾何 +20、四邊形 +5、拆零件 +20；**綁骨架 25；動作每個 10**；骨架檢查免費 |
| 混元 3D（騰訊雲國際版官方） | 3.1 Pro（2026-07）；3.0、3.1、2.5 不公開，只能用 API；公開可下載的是 2.x（2.1 要 24 GB 顯示卡） | 點數：一般 25、低多邊形 30、只有幾何 15、快速版 15；**綁骨架 10**（輸出帶骨架的 FBX）；沒有動作。點數包 15～1,350 美元，每點 0.0135～0.015 美元；新用戶送 1,000 點（約 40 次） |
| 混元 3D（FAL 代理） | 3.1 Pro／快速版 | Pro 0.375 美元、快速版 0.225 美元；材質 +0.15、拆零件 +0.45、智慧拓樸 +0.75 |

**圖像編輯**

| 服務 | 模型 | 官方價格（每張） |
|---|---|---|
| Google Gemini | **3.1 Flash Lite Image**（最新） | 1K 約 0.034 美元；批次 0.017 |
| | 3.1 Flash Image（nano-banana 2） | 0.5K 0.045、1K 0.067、2K 0.101、4K 0.151 美元；批次約一半 |
| | 3 Pro Image（nano-banana Pro） | 1K／2K 0.134、4K 0.24 美元 |
| | 2.5 Flash Image（初代） | **2026-10-02 已停用** |
| | 都沒有免費額度 | |
| OpenAI | **GPT Image 2.5**（最新，分 Sunburst：編輯精準；Flare：快、日常用） | 按字詞單位計價：文字輸入每百萬 5 美元、圖片輸入 8 美元、圖片輸出 30 美元（跟 GPT Image 2 一樣）。官方沒有列每張價格；第三方估每張約 0.01～0.06 美元，有參考圖的編輯貴 2～3 倍 |

**一個角色加 10 個動作，照官方點數算：**
- Meshy：30＋5＋30 = 65 點。Pro 方案（每點 0.02 美元）約 1.3 美元；Ultra（每點 0.0125）約 0.8 美元。
- Tripo：30＋25＋100 = 155 點 = 1.55 美元。
- 混元 3D 官方：25＋10 = 35 點，約 0.5 美元，但沒有動作（要自己套）。

**一張立繪的物件迴圈（約 90 次編輯）：** Gemini 3.1 Flash Lite 1K 約 3 美元；3.1 Flash 2K 約 9 美元；3 Pro 約 12 美元。

**注意：**
- Meshy 的方案價格在官方說明頁；點數表在官方 API 文件。Tripo 的「新 API 用戶送 2,000 點」只在第三方文章看到，官方價目頁沒寫。
- 輸出的商用授權：Meshy 免費方案是 CC BY 4.0（要標出處），付費方案可私有；其他家沒查。
- 便宜不代表能用：三家對動漫角色的品質都還不知道，要先試。

## 願意等的話：批次和彈性方案（2026-10-04 查官方文件）

| 服務 | 方案 | 折扣 | 等多久 | 圖像模型能不能用 |
|---|---|---|---|---|
| Google Gemini | 批次 | 標準價 5 折 | 目標 24 小時內，多數更快；工作 48 小時過期 | **能**（價目表有 3.1 Flash、3.1 Flash Lite、3 Pro 圖像的批次價） |
| | 彈性 | 5 折 | 1～15 分鐘，忙的時候會被拒絕要重試 | **不能**（只有文字模型） |
| OpenAI | 批次 | 5 折 | 24 小時內 | **能**（GPT Image 2.5 的生成和編輯都可以） |
| xAI Grok | 批次 | 文字 2～5 折 | 24 小時內 | 圖像可以送批次，但**照原價**（官方：批次折扣只適用文字和語言模型） |
| Meshy、Tripo、混元 3D | 沒有 | — | — | 只有方案等級決定排隊優先；大方案每點比較便宜（混元的大點數包最低到定價的 67.5%） |

批次價（每張）：Gemini 3 Pro Image 1K/2K 約 0.067、4K 約 0.12；3.1 Flash Image 約 0.022～0.076（依解析度）；3.1 Flash Lite 1K 約 0.017 美元。

**代價**：一輪要等到 24 小時。我們「一個物件畫完、看完、放進組裡看完才做下一個」的做法，每輪都要等，會很慢。適合的用法是：第一輪大量候選（所有零件各出幾張）丟批次過夜，挑完、要重做的幾張用即時的。

## xAI Grok 的圖像模型（2026-10-04）

| 模型 | 官方價目頁 | 第三方整理的細分 |
|---|---|---|
| grok-imagine-image-2.0（2026-08） | 0.04 美元／張 | 1K 低品質 0.04、2K 低或 1K 中 0.06、2K 中 0.08；編輯每張輸入圖另加 0.01 |
| grok-imagine-image-quality | 0.05 美元 | 1K 0.05～2K 0.07 |
| grok-imagine-image（初代） | 0.02 美元 | |

- 能編輯：用文字指令改圖，一次最多 5 張參考圖（可以拿來保持長相）。官方文件沒提遮罩，要自己把遮罩外蓋回原圖。
- 內容審查：官方只寫「生成的內容要經過內容政策審查、不拿來訓練」。一般認為 xAI 比 Google、OpenAI 寬鬆，但 API 實際的界線要自己試。
- 沒有批次折扣。

## 來源

- [neilsonnn/image-blaster](https://github.com/neilsonnn/image-blaster)：`README.md`、`.claude/skills/image-blast-uncover/SKILL.md`、`image-blast-plate/SKILL.md`、`image-blast-3d/SKILL.md`
- 價錢（官方）：[Meshy API Pricing](https://docs.meshy.ai/en/api/pricing)、[Meshy plans](https://help.meshy.ai/en/articles/12062933-what-are-your-prices-and-plans-offered-and-do-you-have-monthly-annual-plans)、[Meshy API changelog](https://docs.meshy.ai/en/api/changelog)、[Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)、[OpenAI API pricing](https://developers.openai.com/api/docs/pricing)、[OpenAI image generation guide](https://developers.openai.com/api/docs/guides/image-generation)、[Tencent Hunyuan Global 3D API](https://www.tencentcloud.com/techpedia/148311?lang=en)
- 新模型：[Tripo P2.0](https://finance.yahoo.com/technology/ai/articles/tripo-ai-releases-latest-model-032200541.html)、[Tripo H3.1 / P1.0 (GDC 2026)](https://www.prnewswire.com/news-releases/tripo-ai-debuts-production-grade-native-3d-diffusion-at-gdc-2026-302708371.html)、[Meshy 7](https://finance.yahoo.com/technology/ai/articles/meshy-releases-meshy-7-foundation-150000321.html)、[Hunyuan 3D v3.1 Pro](https://layer.ai/models/tencent-hunyuan3d-v3-1-pro)、[Hunyuan 3D open source vs API](https://www.tencentcloud.com/techpedia/148276?lang=en)
- 等待的方案（官方）：[Gemini Batch API](https://ai.google.dev/gemini-api/docs/batch-mode)、[Gemini Flex inference](https://ai.google.dev/gemini-api/docs/flex-inference)、[OpenAI Batch API](https://developers.openai.com/api/docs/guides/batch)、[xAI API Pricing](https://docs.x.ai/developers/pricing)、[xAI image generation](https://docs.x.ai/docs/guides/image-generations)、[xAI models](https://docs.x.ai/docs/models)
- Grok 圖像（第三方）：[Grok Imagine Image 2.0 on OpenRouter](https://openrouter.ai/x-ai/grok-imagine-image-2.0)、[Grok Imagine Image Quality on OpenRouter](https://openrouter.ai/x-ai/grok-imagine-image-quality)
- 價錢（第三方）：、[Meshy credits guide](https://www.meshy.ai/tutorials/meshy-credits-guide)、[Meshy API pricing explained](https://meshyiai.com/api-pricing/)、[Tripo pricing](https://developers.tripo3d.ai/en/pricing)、[Tripo credits guide](https://www.tripo3d.ai/getting-started/zero-to-3d-getting-started-credits-pricing-guide)、[Hunyuan 3D on fal](https://fal.ai/hunyuan-3d)、[Hunyuan 3D Pro image-to-3D on fal](https://fal.ai/models/fal-ai/hunyuan-3d/v3.1/pro/image-to-3d)、[Nano Banana pricing](https://benchlm.ai/media-pricing/nano-banana)、[Nano Banana Pro pricing](https://www.pixmind.io/posts/nano-banana-pro-pricing-guide-2026)、[GPT Image 2 pricing](https://aireiter.com/blog/gpt-image-2-api-pricing)、[GPT Image 2 per-image breakdown](https://www.hiapi.ai/en/blog/gpt-image-2-api-pricing)
