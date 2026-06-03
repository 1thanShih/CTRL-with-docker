#!/usr/bin/env bash
# Drive the lane_follower perception->control pipeline with NO hardware.
#
# Feeds a synthetic camera frame into /camera/image_raw and asserts the full
# chain produces output: lane_detect_v2 -> /lane_detect, turn_detect ->
# /turn_detect, lane_controller_fuzzy -> /arduino_vel. Captures the rendered
# debug images to /tmp/lane_out.png and /tmp/turn_out.png on the host.
#
# Usage:  bash .claude/skills/run-lane-follower/smoke.sh
# Leaves the container running; kills only the ROS procs it started.
set -uo pipefail

C=ros-noetic-zsh
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"
SRC='source /root/catkin_ws/devel/setup.bash'
FAIL=0

dexec()  { docker exec "$C" bash -lc "$SRC; $*"; }
dbg()    { echo -e "\n=== $* ==="; }

cleanup() {
  dbg "cleanup"
  docker exec "$C" bash -lc '
    pkill -9 -f "devel/lib/lane_follower" 2>/dev/null
    pkill -9 -f fake_camera 2>/dev/null
    pkill -9 -f rosmaster 2>/dev/null
    pkill -9 -f roscore 2>/dev/null
    pkill -9 -f rosout 2>/dev/null
    true'
  echo "ros procs stopped (container left running)"
}
trap cleanup EXIT

# 0. container up (idempotent)
dbg "ensure container up"
if [ -z "$(docker ps -q -f name=^/${C}$)" ]; then
  ( cd "$REPO_ROOT" && make up )
fi
docker ps --filter "name=^/${C}$" --format '{{.Names}} {{.Status}}'

# 1. push the synthetic camera in
docker cp "$SKILL_DIR/fake_camera.py" "$C:/tmp/fake_camera.py"

# 2. roscore
dbg "start roscore"
docker exec -d "$C" bash -lc "$SRC; roscore"
dexec 'for i in $(seq 1 30); do rostopic list >/dev/null 2>&1 && { echo "roscore up"; exit 0; }; sleep 0.5; done; echo "roscore FAILED"; exit 1' || FAIL=1

# 3. the three production nodes (image_topic override -> subscribe, not /dev/video0)
dbg "launch nodes"
docker exec -d "$C" bash -lc "$SRC; rosrun lane_follower lane_detect_v2.py _image_topic:=/camera/image_raw > /tmp/lane_detect.log 2>&1"
docker exec -d "$C" bash -lc "$SRC; rosrun lane_follower turn_detect.py            > /tmp/turn_detect.log 2>&1"
docker exec -d "$C" bash -lc "$SRC; rosrun lane_follower lane_controller_fuzzy.py   > /tmp/controller.log 2>&1"

# 4. synthetic camera
docker exec -d "$C" bash -lc "$SRC; python3 /tmp/fake_camera.py > /tmp/fake_camera.log 2>&1"
sleep 4

# 5. nodes present?
dbg "rosnode list"
NODES="$(dexec 'rosnode list' 2>&1)"
echo "$NODES"
for n in /lane_detect_node /turn_detect_node /lane_controller_fuzzy /fake_camera; do
  echo "$NODES" | grep -q "$n" || { echo "MISSING NODE $n"; FAIL=1; }
done

# 6. data actually flowing on the three output topics?
check_topic() {  # $1 topic, $2 grep-pattern
  local out; out="$(dexec "timeout 4 rostopic echo -n 1 $1" 2>&1)"
  if echo "$out" | grep -q "$2"; then echo "OK   $1"; else echo "FAIL $1"; echo "$out" | head -5; FAIL=1; fi
}
dbg "output topics"
check_topic /lane_detect  'offset:'
check_topic /turn_detect  'turn_direction:'
check_topic /arduino_vel  'linear:'

# 7. capture rendered debug images (the "screenshot" for a vision pipeline)
dbg "capture debug images"
dexec 'python3 - <<PY
import rospy, cv2
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
rospy.init_node("grab", anonymous=True)
b = CvBridge()
for topic, out in [("/lane_detect/image_out","/tmp/lane_out.png"),
                   ("/turn_detect/image_out","/tmp/turn_out.png")]:
    m = rospy.wait_for_message(topic, Image, timeout=5)
    cv2.imwrite(out, b.imgmsg_to_cv2(m,"bgr8")); print("saved", out, m.width, "x", m.height)
PY'
docker cp "$C:/tmp/lane_out.png" /tmp/lane_out.png && echo "host: /tmp/lane_out.png"
docker cp "$C:/tmp/turn_out.png" /tmp/turn_out.png && echo "host: /tmp/turn_out.png"

dbg "RESULT"
if [ "$FAIL" -eq 0 ]; then echo "PASS — pipeline drove end-to-end, no hardware"; else echo "FAIL — see above"; fi
exit $FAIL
