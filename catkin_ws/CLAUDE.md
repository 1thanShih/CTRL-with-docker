# CLAUDE.md — /root/catkin_ws

## 專案概述

ROS1 自走車專案，實現基於視覺的車道追蹤 (lane following) 與路口轉向 (turn detection)，部署在 TurtleBot 或類似機器人平台上。

## 套件結構

```
catkin_ws/
└── src/
    └── lane_follower/
        ├── config/
        │   └── lane_follower.yaml       # ★ 系統總配置檔（相機裝置 + 所有演算法參數）
        ├── scripts/
        │   ├── lane_detect_v2.py        # 車道偵測節點（完整 CV pipeline）
        │   ├── turn_detect.py           # 三角形路標偵測節點
        │   └── lane_controller_fuzzy.py # Sugeno 模糊控制器節點
        ├── launch/
        │   ├── lane_detect_bringup.launch      # ★ 主要 launch，支援 dual_camera:=true/false
        │   ├── lane_detect_v2.launch           # 不含 Arduino 的輕量版
        │   └── lane_detect_bringup_Shih.launch # 個人調參版本（不讀 YAML）
        ├── msg/
        │   ├── LaneData.msg             # float32 offset, float32 angle
        │   └── TurnDetect.msg           # string turn_direction, float32 pixel_size, float32 offset
        ├── CMakeLists.txt
        └── package.xml
```

## 三個核心 Scripts

### `lane_detect_v2.py`
車道辨識 ROS 節點，包含完整的電腦視覺 pipeline：

**Pipeline：** Preprocess → Detect → Track → Measure → Smooth → Render

- **Preprocess：** 灰階 + 高斯模糊 + Otsu 二值化（`USE_OTSU_FALLBACK=True`，針對深色車道線在淺色地板）+ 形態學 open/close + ROI masking
- **Detect：** 輪廓偵測，過濾小面積，用 `resolve_floating_v4()` 合併破碎輪廓（距離法 + 延伸線交點法）
- **Track：** `LaneTracker` — IoU-based 配對優先，fallback 到位置平分，最多 `MAX_MEMORY_FRAMES=15` 幀記憶
- **Measure：** 在 `anchor_y = frame_height * 0.8` 行計算偏移量；yaw 用二次多項式擬合取微分（`ENABLE_YAW_B=True`）
- **Smooth：** `LaneSmoother` — Kalman（預設）或 EMA，最多 15 幀純預測後 reset
- **Publish：** `lane_detect` (LaneData)、`lane_detect/image_out` (debug)、`lane_detect/image_binary`
- 支援直接從 `/dev/videoX` 硬體讀取，或訂閱 ROS Image topic

### `turn_detect.py`
三角形路標辨識 ROS 節點：

- **偵測：** Otsu + bitwise_not → `cv2.approxPolyDP` 找 3 頂點輪廓 → apex.x vs 中心 x 判左/右
- **穩定性：** `Tracker` — 連續 10 幀確認才發布，連續 5 幀消失才重置
- **Publish：** `turn_detect` (TurnDetect: direction, pixel_size, offset)
- 過濾條件：最小面積 1000 px²、長寬比 0.5~2.0、面積/bbox 比 ≥ 0.4

### `lane_controller_fuzzy.py`
Sugeno 模糊推論控制器：

- **模糊輸入：** offset（5 集合，中心 ±100/±50/0 px）+ angle（5 集合，中心 ±50/±25/0°）
- **規則庫：** 5×5 矩陣，Product Inference，輸出 -1.0 ~ 1.0
- **控制優先級（高→低）：**
  1. 大轉彎執行中 → 固定角速度
  2. 路標消失 → 停車掃描（左1s/右2s/左1s 循環）
  3. 靠近路標 → 慢速 + offset 對齊
  4. 正常循線 → 模糊輸出
- **大轉彎：** 第 1 次 / 第 2 次以後分別用不同 threshold + duration 參數
- **Publish：** `arduino_vel` (Twist)

## 設定檔

`config/lane_follower.yaml` 是唯一需要修改的設定檔，包含：
- `lane_cam_device` / `turn_cam_device`：相機裝置路徑（雙相機時分別設定）
- 所有演算法參數（以 `lane_detect_*` / `turn_detect_*` / `ctrl_*` 為前綴）

啟動方式：
```bash
# 單相機（預設，兩節點用同一顆 USB cam）
roslaunch lane_follower lane_detect_bringup.launch

# 雙相機
roslaunch lane_follower lane_detect_bringup.launch dual_camera:=true
```

雙相機模式下 launch 檔自動：
1. 啟動 `camera_node_lane`（`/dev/video0` → `/cam_lane/image_raw`）
2. 啟動 `camera_node_turn`（`/dev/video1` → `/cam_turn/image_raw`）
3. 各節點訂閱對應的 topic

## ROS Topic 關係

```
單相機模式:
  /camera/image_raw ──┬──► lane_detect_v2 ──► lane_detect (LaneData)
                      └──► turn_detect    ──► turn_detect (TurnDetect)

雙相機模式:
  /cam_lane/image_raw ──► lane_detect_v2 ──► lane_detect (LaneData)
  /cam_turn/image_raw ──► turn_detect    ──► turn_detect (TurnDetect)

lane_detect ──┐
              └──► lane_controller_fuzzy ──► arduino_vel (Twist)
turn_detect ──┘
```

## 常用指令

```bash
# 編譯
cd /root/catkin_ws && catkin_make && source devel/setup.bash

# 啟動完整系統
roslaunch lane_follower lane_detect_v2.launch

# 查看 offset/angle 輸出
rostopic echo /lane_detect

# 查看轉向偵測輸出
rostopic echo /turn_detect

# 查看 debug 影像（需 rqt_image_view）
rosrun rqt_image_view rqt_image_view /lane_detect/image_out
```

## 環境依賴

- ROS1 Noetic
- Python 3
- OpenCV (`cv2`)
- NumPy
- `filterpy`（Kalman filter，`pip install filterpy`）
- `cv_bridge`, `sensor_msgs`, `geometry_msgs`

## 硬體假設

- 車道：**深色線條在淺色地板**（因此使用 `THRESH_BINARY_INV`）
- 路標：**三角形指示牌**（尖端朝左 = 左轉，尖端朝右 = 右轉）
- 輸出馬達：通過 `arduino_vel` Twist topic 控制 Arduino
