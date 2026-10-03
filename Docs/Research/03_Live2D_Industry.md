# 業界怎麼人工做 Live2D

整理日期：2026-10-03。回到 [研究總覽](README.md)。來源以 Live2D 官方文件為主，價錢和工時來自委託市場的整理文章。

## 分工

一個直播用的 Live2D 角色通常分兩個人：
- **畫師**：設計角色、畫表情，交出**分好層的原稿**（分層檔）。
- **綁定師**：把圖層做成網格、變形、參數、物理（頭髮擺動）、臉部追蹤。

多數人先找畫師，畫完再找綁定師。

## 第一步：為動而畫的分層原稿

官方說法：靜止時看起來是一張圖，其實拆成頭髮、眉毛、睫毛、耳朵等零件；**分得越細，模型品質越好**。

拆法（官方教學）：
- **三大塊**：頭髮、臉、身體，再往下分。
- **頭髮**：前髮、側髮、後髮；左右分開的（鬢角、雙馬尾）每邊一層。被擋住的部分也要畫，動的時候才不會斷開。
- **眼睛**：睫毛、眼珠、眼白分開。睫毛跟眼角翹起的那一小段分開比較好變形。眼白當遮罩，因為眼珠一動就會露出原本被擋住的地方。進階做法把睫毛再分成 4 塊，代表眼皮的那條橫線另成一塊。
- **嘴**：上唇、下唇、嘴裡面。**嘴裡面要畫得比原圖大一圈**；不靠遮罩，而是在嘴唇周圍補一圈膚色把嘴裡面蓋住。
- **眉毛、鼻子**：各自一層（幾乎不變形）。
- **臉的輪廓、耳朵**：被擋住的地方也畫；頭畫圓一點，轉頭時比較有立體感。
- **脖子**：**畫長一點**，轉頭時才不會露出切口。
- **四肢**：上臂、前臂、手；裙子、左腿、右腿。
- **被擋住的部分**：「動得多的零件，和別的零件動時會露出來的地方，要先畫」。補畫的部分另開一層，不要直接畫在原本的圖層上（之後難改）。
- **格式**：每個零件一層，線稿和上色合成一層；RGB、8 位元、分層檔。實際上會留兩份：一份保留資料夾和遮罩方便改，一份合併好給 Live2D 讀。

重點：**被擋住的部分畫多少，是看這個模型要動多少來決定的**。一般直播角色動作小，所以只多畫一小圈。

## 第二步：綁定

**基本元件**
- **網格**：每個零件一塊，可以自動產生。
- **彎曲變形器**（方格）：把裡面的網格整片彎曲，用來做轉頭、身體轉動時的立體感。
- **旋轉變形器**：照角度轉，主要用在脖子、手臂、腿。
- **參數**：一個滑桿，在幾個值（例如 -1、0、1）各存一個形狀（關鍵形），中間自動內插。

**轉頭（最重要）**
- 官方說：臉的上下左右轉動「是做模型最重要的步驟」。
- 臉的每個零件（輪廓、眼、鼻、嘴、眉、耳、頭髮）**各有一個彎曲變形器**，各自變形才有前後的視差和立體感。
- 左右轉時：照透視變形，**遠的那邊變窄、近的那邊變寬**；頭髮往反方向移，做出視差。
- 先做左右（三個關鍵形：左、正、右），再做上下；兩個都好了，用「自動產生四角」做出斜方向的形狀。
- 頭髮之類有物理的零件，放在跟著頭轉的那個變形器裡面。

**眨眼**
- 「眼睛開合」參數加兩個關鍵形（開、閉）。上眼皮（睫毛）往下變形到閉合的樣子，眼珠只在眼白範圍裡顯示。
- 技巧：眼珠跟著上眼皮一起往下移一點，眨眼比較自然。
- 參數名稱照標準取，播放端會自動眨眼。

**標準參數和範圍**（官方標準參數表）

| 參數 | 範圍 | 說明 |
|---|---|---|
| 頭左右 `ParamAngleX` | -30～30 | 可以改大（例如 ±45） |
| 頭上下 `ParamAngleY`、歪頭 `ParamAngleZ` | -30～30 | |
| 眼睛開合 `ParamEyeLOpen` / `R` | 0～1（預設 1） | |
| 嘴型 `ParamMouthForm` | -1～1 | 正是笑、負是生氣 |
| 張嘴 `ParamMouthOpenY` | 0～1 | |
| 身體左右 `ParamBodyAngleX` | **-10～10** | 身體只轉頭的三分之一 |
| 呼吸 `ParamBreath` | 0～1 | |

從範圍就看得出來：**Live2D 的動作本來就小**，頭轉 30 度、身體 10 度。

**物理**：頭髮、衣服、飾品照頭和身體的動作延遲擺動。

## 官方編輯器的自動化（Cubism）

- **自動產生臉部動作**：先自動產生臉、左右眼、左右眉、嘴的變形器，再自動產生頭的上下左右轉動（要求有這六個變形器）。
- **自動產生變形器**（5.1，2024-07）：人形模型讀進分層檔後，馬上產生整套變形器結構。
- **自動產生擺動**（5.1）：頭髮、飾品的擺動，可調強度。
- **3D 旋轉表現**（5.1）：馬上產生上下左右轉動的基本形狀。
- **模型範本**：把做好的模型的零件結構、變形器、參數關鍵形套到新模型上；5.1 起可以只套到某些零件。

也就是說，官方編輯器已經把「轉頭、擺動、變形器結構」自動化到一定程度，前提是**有一份好的分層原稿**。

## 價錢和工時

- 基本（頭動、對嘴、簡單頭髮擺動）約 200–600 美元；中等（完整物理、眼睛追蹤、呼吸、一套換裝）約 600–1,500 美元；專業 1,500–4,000 美元以上。
- 綁定加插畫，一個模型可能要到約 20 小時。

## 軟體授權

- Cubism Editor PRO：個人和年營收 1,000 萬日圓以下的小公司約每年 100 美元（三年約 260 美元）；有 42 天試用，試用後有功能受限的免費版。
- 輸出的模型格式是 Live2D 專有的；我們用的 Inochi2D 是開源的替代品。

## 遊戲裡的全身大動作：用 Spine，不是 Live2D

- **Spine** 是做 2D 遊戲角色動畫的主流工具：用骨架加網格，時間軸上打關鍵影格（像 3D 軟體）。動畫之間能平順地接，能同時播（邊跳邊攻擊）。因為是骨架，需要手臂、腿、手、頭這些零件，所以只適合四肢都拆開的角色。
- **Live2D** 是用參數控制變形量，擅長表情和擺動，主要用在直播角色和介面上。
- 結論：**全身的角色動畫（攻擊、走路）業界多用 Spine；Live2D 主要做臉、上半身和小幅度的動。**

## 對我們的意義

- 我們的流程想用一張圖自動做到「Live2D 等級的臉」加上「Spine 等級的全身動作」，兩件業界分開做、而且都是從**為動而畫的原稿**開始的事。
- 被擋住的部分要畫多少，業界是照動作幅度決定的；我們要的動作幅度大，等於需要畫非常多的被擋住部分。
- 官方編輯器的自動化（轉頭、擺動、範本）值得參考：轉頭時每個零件各自彎曲、遠窄近寬、頭髮反向。我們目前的轉頭只是五官平移幾像素。
- 嘴的做法（嘴裡面畫大一圈、嘴唇周圍補膚色）和眼睛的做法（睫毛分段、眼珠跟著眼皮下移），可以直接照著改。

## 來源

- 官方：[About Material Separation](https://docs.live2d.com/en/cubism-editor-manual/divide-the-material/)、[Illustration Processing](https://docs.live2d.com/en/cubism-editor-tutorials/psd/)、[How to create PSDs to import](https://docs.live2d.com/en/cubism-editor-manual/reimport-psd/)
- 官方：[Adding XY Facial Movement](https://docs.live2d.com/en/cubism-editor-tutorials/xy/)、[Adding Body Movement](https://docs.live2d.com/en/cubism-editor-tutorials/deformer/)、[Rotation Deformer](https://docs.live2d.com/en/cubism-editor-manual/making-and-rotation-of-rotationdeformer/)、[Keyforms (X, Y)](https://docs.live2d.com/en/cubism-editor-manual/keyform-xydirection/)
- 官方：[Standard Parameter List](https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/)、[Eye Blinking tutorial](https://docs.live2d.com/en/cubism-editor-tutorials/eye-blink/)、[Natural Eye Blinking (Cubism 2)](https://sites.google.com/a/cybernoids.jp/cubism2_en/user_tutorials/kuroi2)
- 官方：[Auto generation of facial motion](https://docs.live2d.com/en/cubism-editor-manual/face-auto-edit/)、[Auto Generation of Deformer](https://docs.live2d.com/en/cubism-editor-manual/auto-generation-of-deformer/)、[5.1 New Features](https://docs.live2d.com/en/cubism-editor-manual/new-function5-1/)、[Model templates](https://docs.live2d.com/en/cubism-editor-manual/template/)
- 綁定流程：[Deformer Hierarchy (Cookbook)](https://r3dhummingbird.gitbook.io/live2d-cubism-cookbook/modeling-and-rigging/deformer-hierarchy)、[VTuber Rigging & Live2D Workflow](https://news.viverse.com/post/vtuber-rigging-tips-and-tricks-for-beginners-workflow)
- 價錢：[VTuber art commissions guide](https://blog.artbase.au/blog/vtuber-art-commissions-guide/)、[VTuber model commissions pricing](https://draw.market/en/blog/vtuber-model-commissions-guide.html)
- 授權：[Live2D Pricing: Free vs Pro](https://kudos.tv/blogs/stream-blog/live2d)、[Live2D Help: PRO license](https://help.live2d.com/en/license/license_01/)
- Spine 和 Live2D：[Spine and Live2D impressions](https://note.com/mublog1/n/n1dbffe0201a2?hl=en)、[Spine](https://esotericsoftware.com/)
