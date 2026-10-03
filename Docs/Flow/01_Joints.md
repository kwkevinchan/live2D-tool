# 1. 找骨架（L1）

回到 [主流程](README.md)。

## 做什麼、為什麼

找出肩、肘、腕、髖、膝、踝、脖子、臉的位置和武器的握點。後面切四肢、綁定的轉軸都從這裡來；關節點偏了，零件會接不起來（手腕高了 50 像素，前臂碰不到手），在這一步修最便宜。

## 輸入、輸出

- 輸入：`full.png`、`full_blink.png`。
- 輸出：
  - `fig_joints.json`：關節點；手改前的偵測結果另存 `fig_joints_detected.json`。
  - `fig_joints.jpg`：現在的關節點畫在立繪上，標了名字和缺哪幾點。
  - `fig_overview.png`：自動偵測的總覽，手改之後不會變。
  - 舊的粗分層：`fig_*.png`、`layer_*.png`。
  - 閉眼差分：`eyes_closed.png`、`eyes.json`。

## 指令

```
python Tools/art/live_layers.py parts <角色> <造型>     DWPose 骨架、SAM2 粗分（要 ComfyUI，約 35～90 秒）
python Tools/art/live_layers.py joints <角色> <造型>    畫 fig_joints.jpg（手改後也重畫）
```

## 看什麼

- 審查包：`fig_joints.jpg`（現在的點），`fig_overview.png`（自動抓的）。

### 注意重點

**L1 骨架**
- 看 `fig_joints.jpg`（現在的關節點、名字）；`fig_overview.png` 是自動抓的，手改之後不會變。
- 盔甲、寬袖底下的手腕常抓錯或抓不到，手肘、手腕可能跑到肩膀上（LessonsLearned 四）。
- 握點常抓錯：抓到放在箭筒上的那隻手，或劍柄上方（四）。
- 膝蓋、腳踝要有，不然切不出腿（四）。
- 脖子跑到臉的高度、臉被伸出去的袖子誤認（`see_through.fix_grip` 記下的事件）。
- 關節點偏了，後面零件會接不起來（手腕高了 50 像素，前臂碰不到手）（五）：在這一步就修掉，比切完再補便宜。

## 修法選單

| 修法 | 什麼時候用 |
|---|---|
| `rerun` 重跑 | 偵測整個亂掉 |
| `manual` 手改 | 改 `fig_joints.json` 的點（先另存偵測的）；這一步最常用 |

## 常見問題和現在的處理

| 問題 | 處理 | 狀態 |
|---|---|---|
| 被長髮、火球擋住的手臂抓不到肘、腕 | 手改 | 手改（每輪一樣） |
| 肩膀抓到頭髮上、脖子在下巴高度 | 手改 | 手改 |
| 長裙裡的膝蓋、腳踝抓錯或抓不到 | 手改 | 手改 |

芙蕾雅主設計兩輪都改同樣七點（`shoulder_r 256,352`、`shoulder_l 452,342`、`elbow_r 274,438`、`wrist_r 210,525`、`neck 380,312`、`knee_l 380,805`、`ankle_l 432,1062`）。

## 已知問題

- 想做成工具：同一張立繪重跑時沿用上一輪確認過的點；或試別的骨架偵測器。

## 相關

- 程式：[../Code/02_Split.md](../Code/02_Split.md)（`live_layers.py`）。
