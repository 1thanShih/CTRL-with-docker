#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
from geometry_msgs.msg import Twist
import sys
import threading

try:
    from lane_follower.msg import LaneData, TurnDetect
except ImportError:
    rospy.logerr("Cannot import LaneData or TurnDetect! Please ensure you have run 'catkin_make' and 'source devel/setup.bash' after creating the custom message.")
    sys.exit(1)

class FuzzyLogicController:
    """
    Lightweight, dependency-free Fuzzy Controller using Sugeno inference.
    """
    def __init__(self):
        # Define the center points of the fuzzy sets (NL, NM, Z, PM, PL)
        self.offset_centers = [-100.0, -50.0, 0.0, 50.0, 100.0]
        self.angle_centers = [-50.0, -25.0, 0.0, 25.0, 50.0]
        
        # Create a 5x5 Rule Base (Sugeno singletons, range -1.0 to 1.0)
        # Column: Offset (NL, NM, Z, PM, PL)
        # Row: Angle (NL, NM, Z, PM, PL)
        # Logic: offset > 0 or angle > 0 means the car is drifting right, requires left turn (positive output)
        self.rule_matrix = [
            [-1.0, -1.0, -0.8, -0.4,  0.0],
            [-1.0, -0.6, -0.4,  0.0,  0.4],
            [-0.8, -0.4,  0.0,  0.4,  0.8],
            [-0.4,  0.0,  0.4,  0.6,  1.0],
            [ 0.0,  0.4,  0.8,  1.0,  1.0]
        ]
        
    def fuzzify(self, val, centers):
        """
        Fuzzify the input value, returning a dictionary of adjacent set memberships {index: weight}
        """
        if val <= centers[0]:
            return {0: 1.0}
        if val >= centers[-1]:
            return {len(centers)-1: 1.0}
            
        for i in range(len(centers) - 1):
            if centers[i] <= val <= centers[i+1]:
                # Simple linear interpolation (triangular/trapezoidal membership functions)
                ratio = (val - centers[i]) / float(centers[i+1] - centers[i])
                return {i: 1.0 - ratio, i+1: ratio}
        return {2: 1.0}
        
    def compute(self, offset, angle):
        offset_memberships = self.fuzzify(offset, self.offset_centers)
        angle_memberships = self.fuzzify(angle, self.angle_centers)
        
        num = 0.0
        den = 0.0
        
        # Rule Evaluation - using Product Inference
        for o_idx, o_weight in offset_memberships.items():
            for a_idx, a_weight in angle_memberships.items():
                rule_weight = o_weight * a_weight
                out_val = self.rule_matrix[a_idx][o_idx]
                
                num += rule_weight * out_val
                den += rule_weight
                
        if den == 0:
            return 0.0
        return num / den

class LaneControllerFuzzy:
    def __init__(self):
        # 固定節點名，原因同 lane_detect_v2.py — yaml 私有參數需要對齊節點 namespace。
        rospy.init_node('lane_controller_fuzzy')
        
        # Read parameters
        self.base_speed = rospy.get_param('~base_speed', 0.5)
        self.max_angular = rospy.get_param('~max_angular', 1.0) # Max angular velocity is +/- 1.0 rad/s
        
        # Params for Turn 1
        self.turn_pixel_threshold_1 = rospy.get_param('~turn_pixel_threshold_1', 1000.0)
        self.hard_turn_angular_1 = rospy.get_param('~hard_turn_angular_1', 2.0)
        self.hard_turn_duration_1 = rospy.get_param('~hard_turn_duration_1', 1.0)
        
        # Params for Turn 2
        self.turn_pixel_threshold_2 = rospy.get_param('~turn_pixel_threshold_2', 1000.0)
        self.hard_turn_angular_2 = rospy.get_param('~hard_turn_angular_2', 2.0)
        self.hard_turn_duration_2 = rospy.get_param('~hard_turn_duration_2', 1.0)
        
        # Cooldown after a hard turn to ignore signs and resume lane following
        self.hard_turn_cooldown = rospy.get_param('~hard_turn_cooldown', 2.0)

        # Sign alignment parameters
        self.sign_detect_pixel_threshold = rospy.get_param('~sign_detect_pixel_threshold', 5000.0)
        self.sign_offset_threshold = rospy.get_param('~sign_offset_threshold', 50.0)
        self.sign_align_angular = rospy.get_param('~sign_align_angular', 0.5)
        self.scan_angular_z = rospy.get_param('~scan_angular_z', 0.5)

        # Safety / robustness
        # 看門狗：lane_detect 連續多久沒訊息就送 zero Twist (秒)
        self.lane_data_timeout = rospy.get_param('~lane_data_timeout', 0.3)
        # 掃描尋標的最大持續時間 (秒)，逾時就回到一般循線避免原地空轉
        self.max_scan_duration = rospy.get_param('~max_scan_duration', 4.0)
        
        # Turn state
        self.hard_turn_count = 0  # 紀錄大轉彎次數
        self.hard_turn_end_time = 0.0
        self.ignore_sign_end_time = 0.0
        self.active_hard_turn_dir = None
        self.active_hard_turn_angular = 0.0
        self.last_sign_time = 0.0
        self.approaching_sign = False
        self.aligning_sign = False
        self.align_angular_z = 0.0
        self.is_scanning = False
        self.scan_start_time = 0.0

        # Watchdog state — 預設為 0 代表「尚未收到任何 lane_detect」，
        # watchdog 在收到第一筆之前不會送出 zero Twist。
        self.last_lane_time = 0.0
        self.state_lock = threading.Lock()

        # Initialize Fuzzy Controller
        self.fuzzy_controller = FuzzyLogicController()

        # Publisher
        self.cmd_pub = rospy.Publisher('arduino_vel', Twist, queue_size=10)

        # Subscriber: Subscribe to the custom message containing offset and angle
        self.lane_sub = rospy.Subscriber('lane_detect', LaneData, self.lane_callback)
        self.turn_sub = rospy.Subscriber('turn_detect', TurnDetect, self.turn_callback)

        # Watchdog timer — 10 Hz 檢查 lane_detect 是否斷訊
        self.watchdog_timer = rospy.Timer(rospy.Duration(0.1), self._watchdog_cb)

        # 註冊關閉時的回調函數，讓車子可以安全煞停
        rospy.on_shutdown(self.shutdown_hook)
        
        rospy.loginfo("Fuzzy Lane Controller Started.")
        rospy.loginfo("Max Angular Speed: %.2f rad/s, Base Speed: %.2f m/s", self.max_angular, self.base_speed)

    def shutdown_hook(self):
        rospy.loginfo("Shutting down... Stopping the car.")
        twist = Twist()  # 所有欄位預設為 0
        # 大量發送停機指令，確保信號送到 Arduino
        for _ in range(10):
            try:
                self.cmd_pub.publish(twist)
                rospy.sleep(0.05)
            except Exception:
                pass

    def _current_turn_params(self) -> tuple:
        """回傳 (pixel_threshold, hard_turn_angular, hard_turn_duration)。
        第 1 次大轉彎用 Turn 1 參數，之後用 Turn 2 參數。"""
        if self.hard_turn_count == 0:
            return (self.turn_pixel_threshold_1, self.hard_turn_angular_1, self.hard_turn_duration_1)
        return (self.turn_pixel_threshold_2, self.hard_turn_angular_2, self.hard_turn_duration_2)

    def turn_callback(self, msg):
        now = rospy.Time.now().to_sec()

        # 大轉彎進行中或冷卻期內，忽略新的路標避免重複觸發
        if now < self.ignore_sign_end_time:
            return
        if msg.turn_direction not in ('left', 'right'):
            return
        # 路標太小視為尚未抵達，繼續正常循線
        if msg.pixel_size < self.sign_detect_pixel_threshold:
            return

        self.last_sign_time = now
        self.approaching_sign = True
        self.is_scanning = False

        pixel_threshold, hard_turn_angular, hard_turn_duration = self._current_turn_params()

        # 標誌大於門檻 → 觸發大轉彎
        if msg.pixel_size >= pixel_threshold:
            self.active_hard_turn_dir = msg.turn_direction
            self.hard_turn_end_time = now + hard_turn_duration
            self.ignore_sign_end_time = self.hard_turn_end_time + self.hard_turn_cooldown
            self.active_hard_turn_angular = hard_turn_angular
            self.approaching_sign = False
            self.aligning_sign = False
            self.hard_turn_count += 1
            rospy.loginfo("Executing hard turn #%d (%s) for %.2fs",
                          self.hard_turn_count, msg.turn_direction, hard_turn_duration)
            return

        # offset 超過門檻 → 左右校正；offset > 0 表標誌偏右，車要向右修正 (負角速度)
        if abs(msg.offset) >= self.sign_offset_threshold:
            self.aligning_sign = True
            self.align_angular_z = -self.sign_align_angular if msg.offset > 0 else self.sign_align_angular
        else:
            self.aligning_sign = False

    def _publish(self, linear_x: float, angular_z: float) -> None:
        twist = Twist()  # 未設定欄位預設為 0
        twist.linear.x = linear_x
        twist.angular.z = angular_z
        self.cmd_pub.publish(twist)

    def _scan_angular(self, now: float) -> float:
        """掃描週期：左轉 1s → 右轉 2s → 左轉 1s，循環。"""
        cycle = (now - self.scan_start_time) % 4.0
        if cycle < 1.0 or cycle >= 3.0:
            return self.scan_angular_z
        return -self.scan_angular_z

    def _watchdog_cb(self, _event):
        # 若 lane_detect 還沒送過任何訊息，watchdog 不主動踩煞車（等啟動）
        if self.last_lane_time <= 0.0:
            return
        # 大轉彎進行中由 lane_callback 的計時邏輯掌控，不要被 watchdog 打斷
        now = rospy.Time.now().to_sec()
        if now < self.hard_turn_end_time:
            return
        if (now - self.last_lane_time) > self.lane_data_timeout:
            rospy.logwarn_throttle(
                1.0,
                "lane_detect stale for %.2fs > %.2fs, publishing zero Twist",
                now - self.last_lane_time, self.lane_data_timeout,
            )
            self._publish(0.0, 0.0)

    def lane_callback(self, msg):
        now = rospy.Time.now().to_sec()
        with self.state_lock:
            self.last_lane_time = now

        # 第一優先級：大轉彎進行中
        if now < self.hard_turn_end_time:
            angular = self.active_hard_turn_angular if self.active_hard_turn_dir == 'left' else -self.active_hard_turn_angular
            self._publish(self.base_speed, angular)
            return

        # 路標消失過久 (>0.3s)：解除靠近狀態，進入尋標掃描
        if self.approaching_sign and (now - self.last_sign_time > 0.3):
            self.approaching_sign = False
            self.aligning_sign = False
            self.is_scanning = True
            self.scan_start_time = now

        # 第二優先級：尋標掃描 (停止前進、左右擺動找路標)
        if self.is_scanning:
            # 超過最大掃描時間仍找不到路標：放棄掃描回到一般循線，
            # 避免在路標被遮擋或視野外時無限原地空轉。
            if (now - self.scan_start_time) > self.max_scan_duration:
                rospy.logwarn(
                    "Scan timeout %.2fs exceeded, resuming lane following",
                    self.max_scan_duration,
                )
                self.is_scanning = False
            else:
                self._publish(0.0, self._scan_angular(now))
                return

        # 第三優先級：靠近路標 → 慢速並依 offset 對齊
        if self.approaching_sign:
            angular = self.align_angular_z if self.aligning_sign else 0.0
            self._publish(self.base_speed - 0.2, angular)
            return

        # 第四優先級：正常模糊循線 (輸出 -1~1 → 縮放到最大角速度)
        fuzzy_out = self.fuzzy_controller.compute(msg.offset, msg.angle)
        self._publish(self.base_speed, fuzzy_out * self.max_angular)

if __name__ == '__main__':
    try:
        LaneControllerFuzzy()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
