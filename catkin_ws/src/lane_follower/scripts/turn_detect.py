#!/usr/bin/env python3
import rospy
import cv2
import numpy as np
import math
from dataclasses import dataclass
from typing import Optional, Tuple
from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image

# ---------------------------------------------------------
# 請確保您已在 ROS package 中建立名為 TurnDetect.msg 的自定義訊息，
# 內容包含:
#   string turn_direction
#   float32 pixel_size
# 並將 `your_ros_package_name` 替換為您的實際 package 名稱。
# ---------------------------------------------------------
try:
    from lane_follower.msg import TurnDetect
except ImportError:
    rospy.logwarn("尚未匯入 TurnDetect 訊息，請確認您的 package 名稱與 msg 設定。以下使用類似結構替代以防語法錯誤。")
    class TurnDetect:
        turn_direction = ""
        pixel_size = 0.0
        offset = 0.0

# ==========================================
# Defaults — 所有 runtime 可調的值都從 ROS param 讀，
# 這裡的常數只在 launch 沒設定時當 fallback。
# ==========================================
DEFAULT_BLUR_KERNEL = 5
DEFAULT_THRESHOLD_METHOD = 'otsu'
DEFAULT_INVERT_BINARY = True

DEFAULT_MIN_AREA = 1000.0
DEFAULT_ASPECT_RATIO_MIN = 0.5
DEFAULT_ASPECT_RATIO_MAX = 2.0
DEFAULT_AREA_RATIO_MIN = 0.4
DEFAULT_POLY_EPSILON_RATIO = 0.02

DEFAULT_CONFIRM_FRAMES = 10
DEFAULT_LOST_FRAMES = 5
DEFAULT_SAME_OBJECT_DIST_RATIO = 0.2
DEFAULT_SHOW_WINDOW = False  # ROS node 預設不開窗，需要時 launch 覆寫

# ==========================================
# Runtime parameter container — 由 TurnDetectNode 在啟動時填入。
# 純函式 (preprocess / find_triangle / Tracker) 透過此物件取參數，
# 避免依賴全域 mutable state。
# ==========================================
@dataclass
class TurnParams:
    blur_kernel: int = DEFAULT_BLUR_KERNEL
    threshold_method: str = DEFAULT_THRESHOLD_METHOD
    invert_binary: bool = DEFAULT_INVERT_BINARY
    min_area: float = DEFAULT_MIN_AREA
    aspect_ratio_min: float = DEFAULT_ASPECT_RATIO_MIN
    aspect_ratio_max: float = DEFAULT_ASPECT_RATIO_MAX
    area_ratio_min: float = DEFAULT_AREA_RATIO_MIN
    poly_epsilon_ratio: float = DEFAULT_POLY_EPSILON_RATIO
    confirm_frames: int = DEFAULT_CONFIRM_FRAMES
    lost_frames: int = DEFAULT_LOST_FRAMES
    same_object_dist_ratio: float = DEFAULT_SAME_OBJECT_DIST_RATIO


# ==========================================
# Data Structures
# ==========================================
@dataclass
class Triangle:
    contour: np.ndarray
    area: float
    bbox: Tuple[int, int, int, int] # x, y, w, h
    apex: Tuple[int, int]
    direction: str # "left" or "right"
    center: Tuple[int, int]

class State:
    DETECTED = "DETECTED"
    NOT_DETECTED = "NOT_DETECTED"

# ==========================================
# Algorithm Classes and Functions
# ==========================================
class Tracker:
    def __init__(self, params: TurnParams):
        self.params = params
        self.state = State.NOT_DETECTED
        self.consecutive_detects = 0
        self.consecutive_lost = 0
        self.last_triangle: Optional[Triangle] = None

    def _is_same_object(self, triangle: Triangle) -> bool:
        if self.last_triangle is None:
            return True
        lx, ly = self.last_triangle.center
        cx, cy = triangle.center
        dist = math.hypot(cx - lx, cy - ly)
        max_dist = self.params.same_object_dist_ratio * self.last_triangle.bbox[2]
        return dist < max_dist and triangle.direction == self.last_triangle.direction

    def update(self, triangle: Optional[Triangle]) -> str:
        if triangle is None:
            self.consecutive_lost += 1
            if self.consecutive_lost >= self.params.lost_frames:
                self.state = State.NOT_DETECTED
                self.consecutive_detects = 0
                self.last_triangle = None
            return self.state

        # 位置突變或方向改變視為新物件，重置計數
        if not self._is_same_object(triangle):
            self.consecutive_detects = 0

        self.consecutive_detects += 1
        self.consecutive_lost = 0
        self.last_triangle = triangle

        if self.consecutive_detects >= self.params.confirm_frames:
            self.state = State.DETECTED
        return self.state

def preprocess(frame: np.ndarray, params: TurnParams) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    k = params.blur_kernel | 1  # 強制奇數
    blur = cv2.GaussianBlur(gray, (k, k), 0)

    if params.threshold_method == 'otsu':
        _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        binary = cv2.adaptiveThreshold(
            blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

    if params.invert_binary:
        binary = cv2.bitwise_not(binary)

    return binary

def _find_apex(pts: list) -> Tuple[int, int]:
    """三角形 apex：與另外兩點連線中點距離最遠的頂點。"""
    best_idx = 0
    best_dist = -1.0
    for i in range(3):
        other1 = pts[(i + 1) % 3]
        other2 = pts[(i + 2) % 3]
        mid_x = (other1[0] + other2[0]) / 2.0
        mid_y = (other1[1] + other2[1]) / 2.0
        dist = math.hypot(pts[i][0] - mid_x, pts[i][1] - mid_y)
        if dist > best_dist:
            best_dist = dist
            best_idx = i
    return tuple(pts[best_idx])


def _passes_shape_filters(area: float, w: int, h: int, params: TurnParams) -> bool:
    if h == 0:
        return False
    aspect_ratio = float(w) / h
    if not (params.aspect_ratio_min <= aspect_ratio <= params.aspect_ratio_max):
        return False
    return (area / (w * h)) >= params.area_ratio_min


def find_triangle(binary: np.ndarray, params: TurnParams) -> Optional[Triangle]:
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_triangle = None
    max_area = 0.0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < params.min_area or area <= max_area:
            continue

        x, y, w, h = cv2.boundingRect(cnt)
        if not _passes_shape_filters(area, w, h, params):
            continue

        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, params.poly_epsilon_ratio * peri, True)
        if len(approx) != 3:
            continue

        pts = [pt[0] for pt in approx]
        apex = _find_apex(pts)
        center_x = x + w / 2.0
        center_y = y + h / 2.0
        # 方向判定：由 apex.x 相對於 bbox 中心 x 決定
        direction = "right" if apex[0] > center_x else "left"

        max_area = area
        best_triangle = Triangle(
            contour=cnt,
            area=area,
            bbox=(x, y, w, h),
            apex=apex,
            direction=direction,
            center=(int(center_x), int(center_y)),
        )

    return best_triangle

def draw_overlay(frame: np.ndarray, triangle: Optional[Triangle], state: str, fps: float) -> np.ndarray:
    display = frame.copy()
    
    cv2.putText(display, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
    
    color = (0, 255, 0) if state == State.DETECTED else (0, 0, 255)
    cv2.putText(display, f"State: {state}", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
    
    if triangle:
        x, y, w, h = triangle.bbox
        cv2.rectangle(display, (x, y), (x+w, y+h), (255, 0, 0), 2)
        cv2.drawContours(display, [triangle.contour], -1, (0, 255, 255), 2)
        
        cv2.circle(display, triangle.apex, 5, (0, 0, 255), -1)
        
        offset = triangle.center[0] - frame.shape[1] / 2.0
        info = f"Area: {triangle.area:.0f} Dir: {triangle.direction}"
        cv2.putText(display, info, (x, y - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(display, f"Offset: {offset:.1f}", (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        
    return display

# ==========================================
# ROS Node
# ==========================================
class TurnDetectNode:
    def __init__(self):
        # 固定節點名，原因同 lane_detect_v2.py — yaml 私有參數需要對齊節點 namespace。
        rospy.init_node('turn_detect_node')
        self.bridge = CvBridge()

        # 讀取 ROS 參數配置 — topic / 顯示
        self.image_topic = rospy.get_param('~image_topic', '/camera/image_raw')
        self.debug_topic = rospy.get_param('~debug_topic', 'turn_detect/image_out')
        self.show_window = rospy.get_param('~show_window', DEFAULT_SHOW_WINDOW)

        # 演算法參數 — 全部從 rosparam 讀取，允許 launch / yaml 覆寫
        self.params = TurnParams(
            blur_kernel=int(rospy.get_param('~blur_kernel', DEFAULT_BLUR_KERNEL)),
            threshold_method=str(rospy.get_param('~threshold_method', DEFAULT_THRESHOLD_METHOD)),
            invert_binary=bool(rospy.get_param('~invert_binary', DEFAULT_INVERT_BINARY)),
            min_area=float(rospy.get_param('~min_area', DEFAULT_MIN_AREA)),
            aspect_ratio_min=float(rospy.get_param('~aspect_ratio_min', DEFAULT_ASPECT_RATIO_MIN)),
            aspect_ratio_max=float(rospy.get_param('~aspect_ratio_max', DEFAULT_ASPECT_RATIO_MAX)),
            area_ratio_min=float(rospy.get_param('~area_ratio_min', DEFAULT_AREA_RATIO_MIN)),
            poly_epsilon_ratio=float(rospy.get_param('~poly_epsilon_ratio', DEFAULT_POLY_EPSILON_RATIO)),
            confirm_frames=int(rospy.get_param('~confirm_frames', DEFAULT_CONFIRM_FRAMES)),
            lost_frames=int(rospy.get_param('~lost_frames', DEFAULT_LOST_FRAMES)),
            same_object_dist_ratio=float(rospy.get_param('~same_object_dist_ratio', DEFAULT_SAME_OBJECT_DIST_RATIO)),
        )

        # 建立 Publisher 與 Subscriber
        self.pub = rospy.Publisher('turn_detect', TurnDetect, queue_size=10)
        self.debug_pub = rospy.Publisher(self.debug_topic, Image, queue_size=1)
        self.sub = rospy.Subscriber(self.image_topic, Image, self.image_callback, queue_size=1, buff_size=2**24)

        self.tracker = Tracker(self.params)

        self.tick_freq = cv2.getTickFrequency()
        self.prev_tick = cv2.getTickCount()

        rospy.on_shutdown(self._on_shutdown)

        rospy.loginfo("Turn Detect Node Started.")
        rospy.loginfo("Subscribed to topic: %s", self.image_topic)

    def _on_shutdown(self):
        if self.show_window:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    def image_callback(self, msg):
        try:
            # 將 ROS Image 轉為 OpenCV BGR 格式
            frame = self.bridge.imgmsg_to_cv2(msg, "bgr8")
        except CvBridgeError as e:
            rospy.logerr(f"CV Bridge Error: {e}")
            return
            
        curr_tick = cv2.getTickCount()
        fps = self.tick_freq / (curr_tick - self.prev_tick) if (curr_tick - self.prev_tick) > 0 else 0.0
        self.prev_tick = curr_tick
            
        binary = preprocess(frame, self.params)
        triangle = find_triangle(binary, self.params)
        state = self.tracker.update(triangle)
        
        # 如果狀態為 DETECTED，發布結果至 ROS topic
        if state == State.DETECTED and self.tracker.last_triangle:
            msg_out = TurnDetect()
            msg_out.turn_direction = self.tracker.last_triangle.direction
            msg_out.pixel_size = float(self.tracker.last_triangle.area)
            msg_out.offset = float(self.tracker.last_triangle.center[0] - frame.shape[1] / 2.0)
            self.pub.publish(msg_out)
        
        if self.show_window or self.debug_pub.get_num_connections() > 0:
            display = draw_overlay(frame, triangle, state, fps)
            
            if self.show_window:
                cv2.imshow("ROS Turn Detect", display)
                cv2.waitKey(1)
                
            if self.debug_pub.get_num_connections() > 0:
                try:
                    out_msg = self.bridge.cv2_to_imgmsg(display, "bgr8")
                    out_msg.header = msg.header
                    self.debug_pub.publish(out_msg)
                except CvBridgeError as e:
                    rospy.logerr(f"CV Bridge Error on publish: {e}")

    def run(self):
        rospy.spin()

if __name__ == "__main__":
    try:
        node = TurnDetectNode()
        node.run()
    except rospy.ROSInterruptException:
        pass