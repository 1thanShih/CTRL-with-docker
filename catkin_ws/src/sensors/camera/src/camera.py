#!/usr/bin/env python

import rospy
import cv2
from sensor_msgs.msg import Image
from std_msgs.msg import String
import base64
from cv_bridge import CvBridge

class Camera:
  def __init__(self):
    rospy.init_node('camera')

    self.camera_id = rospy.get_param('~camera_id', '/dev/video0')
    width  = int(rospy.get_param('~width',  640))
    height = int(rospy.get_param('~height', 480))
    fps    = int(rospy.get_param('~fps',    30))

    self.cap = cv2.VideoCapture(self.camera_id)
    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    self.cap.set(cv2.CAP_PROP_FPS,          fps)

    if self.cap.isOpened():
      actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
      actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
      actual_f = self.cap.get(cv2.CAP_PROP_FPS)
      rospy.loginfo('Camera connected: %s (%dx%d @ %.1f fps requested %dx%d @ %d)',
                    self.camera_id, actual_w, actual_h, actual_f, width, height, fps)
    else :
      rospy.logwarn('Camera not connected: %s', self.camera_id)

    # Standard ROS image publisher
    self.image_pub = rospy.Publisher('/camera/image_raw', Image, queue_size=1)
    # Existing web publish
    self.web_pub = rospy.Publisher('/golfbot/camera_web', String, queue_size=1)

    self.bridge = CvBridge()
    self.rate = rospy.Rate(fps)

  def talker(self):
    while not rospy.is_shutdown():
      ret, frame = self.cap.read()
      if not ret : 
        self.rate.sleep()
        continue
      
      # 1. Publish standard ROS Image
      try:
        img_msg = self.bridge.cv2_to_imgmsg(frame, "bgr8")
        img_msg.header.stamp = rospy.Time.now()
        self.image_pub.publish(img_msg)
      except Exception as e:
        rospy.logerr("CvBridge Error: %s", e)

      # 2. Encode the image for web
      _, buffer = cv2.imencode('.jpg', frame)
      image_as_str = base64.b64encode(buffer).decode('utf-8')

      # Publish the encoded image
      self.web_pub.publish(image_as_str)

      self.rate.sleep()

    self.cap.release()
    cv2.destroyAllWindows()
    
if __name__ == '__main__':
  camera = Camera()
  try:
    camera.talker()
  except rospy.ROSInterruptException:
    pass