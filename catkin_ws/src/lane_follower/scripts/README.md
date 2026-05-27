# lane_follower/scripts

ROS1 節點集合，實現自走車的車道追蹤與轉向控制。

---

## 系統架構

```
Camera(s)
  │
  ├── 單相機模式 ─────────────────────────────────────────┐
  │   /camera/image_raw ──────────────────────────────────┤
  │                                                        │
  └── 雙相機模式                                           │
      /cam_lane/image_raw (video0) ──► lane_detect_v2.py ─┤
      /cam_turn/image_raw (video1) ──► turn_detect.py ────┤
                                                           │
                           lane_detect (LaneData) ◄────────┤
                           turn_detect (TurnDetect) ◄──────┘
                                    │
                          lane_controller_fuzzy.py
                                    │
                             arduino_vel (Twist)
```

---

## 快速啟動

```bash
cd /root/catkin_ws
catkin_make && source devel/setup.bash

# 單相機模式（預設）
roslaunch lane_follower lane_detect_bringup.launch

# 雙相機模式
roslaunch lane_follower lane_detect_bringup.launch dual_camera:=true
```

**所有參數集中在一個設定檔：**

```
config/lane_follower.yaml
```

不需要改程式碼，直接改 YAML 再重新 launch 即可。

---

## 設定雙相機

### 步驟 1 — 確認裝置路徑

```bash
ls /dev/video*
# 通常走線相機 = /dev/video0，路標相機 = /dev/video1
```

### 步驟 2 — 修改 `config/lane_follower.yaml`

```yaml
lane_cam_device: "/dev/video0"   # 走線相機
turn_cam_device: "/dev/video1"   # 路標相機
```

### 步驟 3 — 啟動雙相機模式

```bash
roslaunch lane_follower lane_detect_bringup.launch dual_camera:=true
```

> **相機 remap 說明：**  
> launch 檔會把 `camera_node_lane` 的輸出 remap 到 `/cam_lane/image_raw`、`camera_node_turn` 到 `/cam_turn/image_raw`。  
> 若你的 `camera.py` 發布的 topic 名稱不是 `/camera/image_raw`，請修改 launch 檔中對應的 `<remap>` 標籤。

---

## Pi 4 (4 GB) 雙相機可行性評估

**結論：可行，但建議以下設定以確保穩定運行。**

| 項目 | 建議 | 原因 |
|------|------|------|
| 走線相機解析度 | 640×480 @ 30fps | 車道需要較高空間解析度 |
| 路標相機解析度 | 320×240 @ 15fps | 三角形辨識不需要高 FPS，可大幅降低 CPU/USB 負載 |
| USB 接法 | 兩隻各接不同 USB controller | Pi 4 有 USB 3.0 × 2（同一 controller）+ USB 2.0 × 2（另一 controller）— 把兩相機接在不同 controller 可避免頻寬競爭 |
| 相機格式 | MJPEG 優先（非 YUYV）| MJPEG 於相機端壓縮，USB 傳輸量約為 YUYV 的 1/10 |

**USB 頻寬估算：**

| 模式 | 格式 | 傳輸量 |
|------|------|--------|
| 640×480 @ 30fps MJPEG | ~3–5 MB/s | 單相機低負載 |
| 640×480 @ 30fps YUYV | ~27 MB/s | 需確認是否超出 USB 2.0 限制 |
| 320×240 @ 15fps MJPEG | <1 MB/s | 路標相機建議設定 |

**CPU 負載估算（Pi 4 全速 4 核心）：**
- `lane_detect_v2.py` 約佔 1 核心（Kalman + 輪廓）
- `turn_detect.py` 較輕，約 0.3–0.5 核心（降解析度後更低）
- `lane_controller_fuzzy.py` 幾乎不佔 CPU
- 剩餘核心供 ROS 通訊與 OS 使用
- **整體 Pi 4 (4GB) 可穩定運行此架構**

---

## 節點說明

### `lane_detect_v2.py` — 車道偵測節點

**ROS Node:** `lane_detect_node`

**Pipeline 流程：**

| 步驟 | 模組 | 說明 |
|------|------|------|
| 1 | Preprocess | 灰階 → 高斯模糊 → Otsu 二值化（反轉）→ 形態學 open/close → ROI masking |
| 2 | Detect | 輪廓偵測，過濾小面積，`resolve_floating_v4()` 合併破碎輪廓 |
| 3 | Track | `LaneTracker` — IoU 配對優先，最多 15 幀記憶補值 |
| 4 | Measure | 在 anchor 行（預設圖高 80%）計算 offset 與 yaw |
| 5 | Smooth | `LaneSmoother` — Kalman（預設）或 EMA，最多 15 幀純預測後 reset |
| 6 | Render | 疊加車道填色、anchor 點、offset 箭頭、狀態文字 |

**Subscribe：** `~image_topic`（支援 ROS topic 或 `/dev/videoX` 直接開啟）

**Publish：**
- `lane_detect`（`LaneData`：`offset: float32`, `angle: float32`）
- `lane_detect/image_out`（彩色 debug 圖）
- `lane_detect/image_binary`（二值化遮罩）

**主要 YAML 參數（`config/lane_follower.yaml`）：**

| 參數 | 預設 | 說明 |
|------|------|------|
| `lane_detect_strict_roi` | `true` | 嚴格裁切 ROI |
| `lane_detect_min_contour_area` | `500.0` | 最小輪廓面積 (px²) |
| `lane_detect_anchor_ratio` | `0.8` | 測量行位置（圖高比例）|
| `lane_detect_enable_yaw_b` | `true` | 二次曲線計算 yaw |
| `lane_detect_max_predict_frames` | `15` | 失偵後最多預測幀數 |

---

### `turn_detect.py` — 路標偵測節點

**ROS Node:** `turn_detect_node`

**偵測流程：**
1. Otsu 二值化 + `bitwise_not`（反轉）
2. `cv2.approxPolyDP` 找 3 頂點輪廓
3. apex.x > 中心.x → `"right"`；反之 → `"left"`
4. `Tracker`：連續 **10 幀**確認才發布，連續 **5 幀**消失才重置

**Subscribe：** `~image_topic`

**Publish：** `turn_detect`（`TurnDetect`：`turn_direction`, `pixel_size`, `offset`）

---

### `lane_controller_fuzzy.py` — 模糊控制器節點

**ROS Node:** `lane_controller_fuzzy`

**模糊控制器：**
- 輸入：`offset`（5 集合，中心 ±100/±50/0 px）+ `angle`（5 集合，中心 ±50/±25/0°）
- 規則庫：5×5 矩陣，Product Inference，輸出 -1.0 ~ 1.0 → 乘以 `max_angular`

**控制優先順序：**

| 優先級 | 條件 | 動作 |
|--------|------|------|
| 1 | 大轉彎執行中 | 固定角速度轉 |
| 2 | 路標消失 → 掃描 | 停止前進，週期左右掃描（1s↺ 2s↻ 1s↺）|
| 3 | 靠近路標 | 慢速 + offset 對齊 |
| 4 | 正常循線 | 模糊推論輸出角速度 |

**Subscribe：** `lane_detect`（LaneData）、`turn_detect`（TurnDetect）

**Publish：** `arduino_vel`（`geometry_msgs/Twist`）

---

## 自定義訊息

### `LaneData.msg`
```
float32 offset    # 偏離車道中心（正 = 偏右，px）
float32 angle     # 車頭航向角（正 = 偏右，度）
```

### `TurnDetect.msg`
```
string  turn_direction  # "left" 或 "right"
float32 pixel_size      # 三角形面積（px²），越大表示越近
float32 offset          # 標誌中心相對影像中心的偏移（px）
```

---

## 依賴套件

```bash
pip install filterpy        # Kalman filter

# ROS packages
# cv_bridge, sensor_msgs, geometry_msgs（通常隨 ROS 安裝）
```
