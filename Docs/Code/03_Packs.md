# 分成六包：部件檢查、組裝檢查（`Tools/art/split_groups.py`）

```
python Tools/art/split_groups.py <角色> <服裝>
```

把拆好的圖層分成六包，每包出兩種檢查圖。不需要 ComfyUI。流程甲第 2 步；工作室「2. 分成六包」。

---

## 函式呼叫流程

```
main(hero, series)
├─ 讀 parts.json、full.png
├─ inx_rig.load_joints(fig_joints.json)           脖子高度（切開 leftover）
├─ pack_of(name)                                  每層歸哪一包
├─ 檢查：缺必有的（REQUIRED）、少一邊（PAIRS）、左右大小顏色
└─ 每一包
   ├─ 每個部件：存 part_*.png、checker(...) 棋盤底、label(...) 標名字 → parts_<n>.jpg
   └─ 前 n 包疊起來：checker、label → assemble_<n>.jpg
   最後寫 groups.json
```

`checker`、`label` 也給 `object_check.py` 用。

## 1. 六包與分類規則

| 編號 | 包 | 內容 |
|---|---|---|
| 1 | `face` 臉部 | 臉、五官、眼白、虹膜、睫毛、眉毛、耳朵、脖子、帽子（含 `headwear-front`）、眼鏡 `eyewear`、耳飾 `earwear`、`ribbon`、`earring`、`leftover` 脖子以上的部分 |
| 2 | `hair` 頭髮 | 前髮、後髮、側髮，以及切出來的 `side_lock`、`hair_ends`、`ponytail`、`ahoge`、`bangs` |
| 3 | `clothes` 軀幹與衣物 | 上衣、下著、領飾 `neckwear`、`hidden`、`hidden-pelvis`、`chest`、`cape`、`sleeve` |
| 4 | `limbs` 四肢 | 上臂、前臂、手、大腿、小腿、腳掌、整條手臂（`handwear-*`）、襪子、鞋子 |
| 5 | `weapon` 武器 | `objects`、`objects-back`、`tassel` |
| 6 | `other` 其他 | `leftover` 脖子以下的部分、`quiver`、尾巴 `tail`、翅膀 `wings`，以及不認得的層 |

分類、必有、成對都讀共用的名字表 `Tools/art/part_names.py`（`pack_of`、`required`、`pairs`）：完全相同的名字優先，其次是最長的前綴，都不是就歸「其他」。新增一種圖層只改那張表。`leftover` 以 `fig_joints.json` 的脖子高度切成兩半，上半歸臉部。

## 2. 自動找的問題

每包的標題列會列出這些警告（紅字）：

- **缺必有的層**（`REQUIRED`）：臉、眼白、虹膜、睫毛、眉毛、嘴、脖子、前髮、後髮、上衣、上臂、前臂、手、大腿、小腿、腳掌、武器。
- **成對的少一邊**（`PAIRS`）：眼白、虹膜、睫毛、眉毛、耳朵、上臂、前臂、手、大腿、小腿、腳掌，只有一邊時提示要補畫。
- **左右對不起來**：大小差 2 倍以上（`PAIR_AREA`），或平均顏色差超過 45（`PAIR_COLOR`，RGB 差的總和）。
- **個別部件**：幾乎是空的（15 像素以下）；超過 5% 在人物外面。
- **位置不對**（`part_names.position_warning`）：臉部的東西有三成以上在脖子再往下半個臉高以下；四肢零件有四分之一以上離自己的骨頭（`pivots`，沒有就用 `fig_joints.json`）超過 0.6 個臉高。用來抓「名字跟內容對不上」，例如手裡混進了前臂和箭筒。離骨頭不遠的混入（上臂混進一塊上衣）抓不到，還是要靠看圖。

## 3. 兩種檢查圖

- **部件檢查 `parts_<n>.jpg`**：一包一張，每個部件單獨一格（220×220，棋盤格底，標名字和像素數；有問題的標紅）。**驗收先看這張**：每個部件是否完整、乾淨、符合名字。
- **組裝檢查 `assemble_<n>.jpg`**：依 `parts.json` 的順序把前 n 包疊起來（臉部 → ＋頭髮 → ＋衣物……），旁邊放立繪，標出覆蓋了人物的百分之幾。最後一張（全部）不再標跟立繪的差異（2026-10-02 起：部件只要對、畫風接近，不用像立繪）；人物範圍裡沒蓋到的像素數記在 `groups.json`。

## 4. 產出

`st/groups/`（每次執行先整個刪掉重建）：

| 檔案 | 內容 |
|---|---|
| `<n>_<包>/part_<名稱>.png` | 這包的每一層（`leftover-head` 是 `leftover` 脖子以上的部分） |
| `parts_<n>.jpg`、`assemble_<n>.jpg` | 兩種檢查圖 |
| `groups.json` | 每包的部件、警告、覆蓋比例；最後一包另有 `missing`、`missing_share`（人物範圍裡沒有任何部件蓋到的像素，是破洞；不跟立繪比顏色，2026-10-02 使用者：組裝圖上畫跟原圖的差異會被讀成「要像原圖」） |

`object_check.py`（武器與物件驗證）和工作室都讀 `groups.json`，所以要先執行這支。
