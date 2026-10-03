# 圖片轉 3D（動漫角色）

整理日期：2026-10-03。回到 [研究總覽](README.md)。

## 為什麼看這個方向

2D 拆層的根本問題是被擋住的部分要靠猜（[02_See_through.md](02_See_through.md)）。3D 模型沒有這個問題：手臂轉到哪裡、背面長什麼樣子，模型本身就有。轉成 3D 之後，用動漫風格的著色（卡通渲染）畫出來，就能做任何角度、任何動作。業界的動漫風 3D 遊戲就是這樣做的。

## 動漫角色專用的研究

| 名稱 | 年份 | 輸入 → 輸出 | 有沒有骨架 | 公開 |
|---|---|---|---|---|
| PAniC-3D | 2023 | 半身像 → 頭部 3D | 無 | 有 |
| CharacterGen | 2024 | 一張圖 → A 字站姿的 3D 角色（VRM 格式，可轉 OBJ、FBX） | 搭配 UniRig 自動綁骨 | 有（Apache-2.0） |
| StdGEN | 2025 電腦視覺年會 | 一張圖 → 3D 角色，**身體、衣服、頭髮分開**，約 3 分鐘 | 沒有 | 有（Apache-2.0，研究用） |
| Anime-Ready | 2026 學習表徵年會 | 一張圖或文字 → **有骨架、能控制表情**的 3D 角色，衣服、頭髮、配件分開 | 有 | 還沒（「待定」） |

**CharacterGen**
- 先把一張圖變成多個角度的圖，同時把姿勢轉成標準的 A 字站姿；再從這幾張圖重建網格。
- 資料集：Anime3D（多姿勢、動漫風的角色）。
- 用 VRoid 做的角色當訓練資料，所以結果偏 VRoid 的樣子。

**StdGEN**
- 也先把姿勢轉成 A 字站姿，再生成分開的身體、衣服、頭髮。
- 限制：訓練資料是全身圖，半身圖效果差；頭髮的細修靠遮罩預測準不準；只輸出網格，沒有骨架。
- 也是用 VRoid 的資料訓練。

**Anime-Ready**（目前最好的，但沒公開）
- 步驟：
  1. 先把輸入轉成正面 A 字站姿的圖。
  2. 用一個從兩萬個動漫角色做出來的「動漫體型身體範本」（有固定的網格、關節、蒙皮權重），身體就直接能動。
  3. 衣服貼著身體生成，每件分開。
  4. 每件衣服各自生成貼圖，顏色才不會互相滲。
- 30 人評分（5 分滿分）：

  | | CharacterGen | StdGEN | 混元 3D 2.0 | Anime-Ready |
  |---|---|---|---|---|
  | 網格品質 | 2.58 | 2.69 | 3.14 | 3.83 |
  | 貼圖品質 | 2.14 | 2.23 | 3.49 | 3.75 |
  | 像不像原圖 | 2.51 | 2.52 | 3.42 | 3.74 |

- 限制：用的是私有的兩萬角色資料；複雜姿勢或配件太多時，轉站姿會失敗；衣服網格有雙面的問題；不同角度的貼圖對不齊；衣服貼圖很慢（約 6 分鐘）。

## 通用的圖片轉 3D

| 名稱 | 公開 | 顯示卡 | 備註 |
|---|---|---|---|
| 混元 3D 2.1 | 有 | 約 29 GB | 3.0（2025-11）、3.1（2026-01）沒有公開；沒有動漫風格的預設，照輸入的圖生成 |
| TRELLIS.2 | 有（MIT，2025-12） | 至少 24 GB | 40 億參數；複雜形狀、材質 |

這兩個是一般物件和角色用的，不是專為動漫做的。我們的顯示卡 16 GB，兩個都跑不動原版。

## 自動綁骨

- **UniRig**（2025 電腦圖學年會，清華和 Tripo）：任何 3D 模型自動產生骨架和蒙皮。開源，有 ComfyUI 節點。
- **Make-It-Animatable**（2025 電腦視覺年會）：人形模型一秒內產生骨架、蒙皮權重；網格和高斯點雲都能用。開源，ComfyUI 節點裡推薦人形角色用它。

## 2D 和 3D 的混合

**From Rigging to Waving**（2025-09）：用 3D 骨架做出粗略的動畫畫面當「骨架引導」，再用針對手繪風格調整過的影片生成模型把畫面重畫成手繪的樣子，補上頭髮、裙子這些次要的擺動。頭髮另外分層處理，長髮才不會跟著身體網格亂變形。是否公開程式不明。

## 業界做法（一般知識，未另外查證）

- 動漫風 3D 遊戲（例如原神、崩壞系列、格鬥遊戲聖騎士之戰）用 3D 模型加卡通渲染做出 2D 的感覺。
- VRoid Studio：免費的動漫風 3D 角色製作軟體（滑桿調整），輸出 VRM 格式；上面幾篇研究都用 VRoid 的資料訓練。
- Godot 有讀 VRM 和動漫風著色（MToon）的外掛。

## 對我們的意義

**好處：**
- 被擋住的部分不用猜，任何角度、任何動作都可以；全身大動作（攻擊、施法）正是 3D 擅長的。
- 有自動綁骨（UniRig、Make-It-Animatable），動作可以套現成的動作資料。

**代價和風險：**
- **像不像原畫**：最好的 Anime-Ready 也只有 3.7 分（5 分滿分）；CharacterGen、StdGEN 偏 VRoid 的長相，跟我們的立繪風格會差很多。
- **細節**：3D 生成的貼圖解析度和臉部細節，通常比不上一張好的 2D 立繪。
- **顯示卡**：通用的模型要 24 GB 以上；動漫專用的公開模型（CharacterGen、StdGEN）比較小，但要實測。
- 遊戲端要改成 3D 角色（或把 3D 渲染成 2D 序列圖），整個呈現方式都會變。

**可能的組合：** 3D 只做「全身大動作」，臉和上半身維持 2D；或用 3D 渲染出各角度、各姿勢的參考圖，再拿去當 2D 重畫的引導（像 From Rigging to Waving 的做法）。

## 來源

- [PAniC-3D (arXiv 2303.14587)](https://arxiv.org/abs/2303.14587)
- [CharacterGen 專案頁](https://charactergen.github.io/)、[CharacterGen (arXiv 2402.17214)](https://arxiv.org/html/2402.17214v3)、[CharacterGen (GitHub)](https://github.com/zjp-shadow/CharacterGen)
- [StdGEN (arXiv 2411.05738)](https://arxiv.org/abs/2411.05738)、[StdGEN (GitHub)](https://github.com/hyz317/StdGEN)
- [Anime-Ready 論文筆記](https://en.papernotes.org/ICLR2026/3d_vision/anime-ready_controllable_3d_anime_character_generation_with_body-aligned_compone/)
- [Make-A-Character 2 (arXiv 2501.07870)](https://arxiv.org/pdf/2501.07870)
- [From Rigging to Waving (arXiv 2509.06573)](https://arxiv.org/abs/2509.06573)
- [UniRig (GitHub)](https://github.com/VAST-AI-Research/UniRig)、[ComfyUI-UniRig](https://github.com/PozzettiAndrea/ComfyUI-UniRig)、[Make-It-Animatable](https://jasongzy.github.io/Make-It-Animatable/)
- [混元 3D、TRELLIS.2 比較](https://app.cinevva.com/guides/ai-3d-model-generators)、[開源模型比較](https://triposr.org/blog/hunyuan3d-vs-trellis)
