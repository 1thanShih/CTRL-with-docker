#!/usr/bin/env python3
"""Synthetic camera for driving the lane_follower pipeline without hardware.

Publishes a 640x480 BGR frame to /camera/image_raw at 15 Hz: a light floor
with two dark near-vertical lane lines (matching the repo's "dark line on
light floor" assumption) plus a dark right-pointing triangle sign, so both
lane_detect_v2 and turn_detect have something real to process. Lets the run
skill exercise the full perception->control pipeline with zero hardware.
"""
import rospy
import numpy as np
import cv2
from sensor_msgs.msg import Image
from cv_bridge import CvBridge


def make_frame(t):
    h, w = 480, 640
    frame = np.full((h, w, 3), 200, np.uint8)          # light floor
    # two dark lane lines, slightly swaying so offset/angle vary over time
    sway = int(40 * np.sin(t))
    cv2.line(frame, (180 + sway, h), (260 + sway, 0), (30, 30, 30), 12)
    cv2.line(frame, (460 + sway, h), (380 + sway, 0), (30, 30, 30), 12)
    # a dark right-pointing triangle (turn sign) top-right
    tri = np.array([[500, 60], [500, 160], [590, 110]], np.int32)
    cv2.fillPoly(frame, [tri], (20, 20, 20))
    return frame


def main():
    rospy.init_node("fake_camera")
    pub = rospy.Publisher("/camera/image_raw", Image, queue_size=1)
    bridge = CvBridge()
    rate = rospy.Rate(15)
    t0 = rospy.get_time()
    rospy.loginfo("fake_camera publishing to /camera/image_raw")
    while not rospy.is_shutdown():
        t = rospy.get_time() - t0
        msg = bridge.cv2_to_imgmsg(make_frame(t), encoding="bgr8")
        msg.header.stamp = rospy.Time.now()
        pub.publish(msg)
        rate.sleep()


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass
