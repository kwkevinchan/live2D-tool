# 10. 靜態截圖（L10）

回到 [主流程](README.md)。

（舊編號 L8、第 5 步。）

## 做什麼、為什麼

用遊戲的播放器畫出五張：站好、轉頭（右）、轉頭（左）＋眨眼、張嘴、靜止。看綁定後靜止時的前後順序、轉頭的深度、眨眼、張嘴的位置。

## 輸入、輸出

- 輸入：`<名稱>_st.inx`。
- 輸出：`_shots/000_rest.png`、`030_yaw_right.png`、`060_yaw_left_blink.png`、`090_mouth_open.png`、`150_settled.png`；`check/<名稱>_check.jpg`（跟原圖比，只當參考）；`_score/L10.json`（角色相似度）。

## 指令

```
python Tools/art/rig_check.py <角色>/<造型>                                     跟原圖比（提示）
<Godot> --audio-driver Dummy --path . res://Tests/live/puppet_preview.tscn -- <模型.inx> <資料夾>/_shots
python Tools/art/char_score.py flag <角色> <造型> <資料夾>/_score/L10.json <資料夾>/_shots
```

## 看什麼

- 審查包：五張截圖（裁出人物並排看）、`_score_L10.json`。

### 注意重點

**L10 靜態**
- 眨眼：眼白和虹膜壓扁、閉眼圖最後兩成淡入，看有沒有露出眼白殘影。
- 轉頭：前髮、後髮有前後深度；領口跟著滑。
- 縮圖看不出細微的問題（LessonsLearned 十一），有疑問看原尺寸。
- `check/<名稱>_check.jpg` 跟原圖的比對只當參考（原則 2）。

## 修法選單

| 修法 | 什麼時候用 |
|---|---|
| `to_objects` | 物件要修 |
| `rerig` | 綁定要重做 |

## 已知問題

- 跟原圖比的那張（`_check.jpg`）跟「不追求像原圖」的原則衝突，之後考慮拿掉（2026-10-02 討論過）。

## 相關

- 程式：[../Code/06_Verify.md](../Code/06_Verify.md)。
