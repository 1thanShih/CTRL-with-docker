---
name: run-lane-follower
description: Build, launch, drive, and screenshot the lane_follower ROS pipeline (DLV autonomous car) in Docker. Use to run the lane detector / turn detector / fuzzy controller, smoke-test the perception->control chain with no hardware, or capture debug images. Triggers on "run the lane follower / the robot / the car", "screenshot lane detect", "test the ROS pipeline".
---

# Run: lane_follower (DLV lane-following pipeline)

A Dockerized ROS Noetic workspace. Three nodes form the chain:
`lane_detect_v2` (`/camera/image_raw` → `/lane_detect`), `turn_detect`
(`/camera/image_raw` → `/turn_detect`), `lane_controller_fuzzy`
(`/lane_detect`+`/turn_detect` → `/arduino_vel` Twist). Everything runs
**inside** the `ros-noetic-zsh` container — the host has no ROS.

The agent path needs **no camera and no Arduino**: the driver feeds a
synthetic frame into `/camera/image_raw` and asserts the whole chain
produces output, capturing the rendered debug images.

All paths below are relative to the repo root (`<unit>/`). The driver
lives at `.claude/skills/run-lane-follower/`.

## Prerequisites

Host needs Docker only (verified: Docker 28.4.0). All ROS / OpenCV /
Python deps are baked into the image by the `Dockerfile` — nothing to
`apt-get` on the host.

```bash
docker --version          # any modern Docker
```

## Build (one-time, slow on ARM/Pi)

```bash
make build                # docker build -t ros-noetic-zsh:latest .
```

The container's entrypoint runs `catkin_make` and sources the workspace
on start; it does **not** start roscore. `make up` (idempotent) starts
the container detached — the driver calls it for you.

## Run (agent path) — THIS IS THE ONE TO USE

```bash
bash .claude/skills/run-lane-follower/smoke.sh
```

What it does (no hardware required):
1. `make up` if the container isn't already running.
2. `docker cp` the synthetic camera (`fake_camera.py`) into the container.
3. Starts `roscore`, then the three production nodes, then the fake camera.
4. Asserts `/lane_detect_node /turn_detect_node /lane_controller_fuzzy
   /fake_camera` are alive.
5. Asserts data flows on `/lane_detect`, `/turn_detect`, `/arduino_vel`.
6. Captures the rendered debug images and copies them to the host.
7. Kills the ROS procs it started (leaves the container running).

Expected tail: `PASS — pipeline drove end-to-end, no hardware`.

**Screenshots land on the host at `/tmp/lane_out.png` and
`/tmp/turn_out.png`.** `lane_out.png` shows the tracked lanes (red/left,
blue/right), ROI line, anchor, and an `offset=… yaw=… status=ok` overlay;
`turn_out.png` shows `State: DETECTED` with the bounded triangle and its
area/offset. Open them to confirm the pipeline did real work — a blank
gray frame means the detector saw nothing.

To poke topics by hand while the driver's nodes are up, drop into the
container: `make shell`, then `rostopic echo /arduino_vel`.

## Run (real hardware) — on the Pi with camera + Arduino plugged in

```bash
make shell
roslaunch lane_follower lane_detect_bringup.launch          # single camera
roslaunch lane_follower lane_detect_bringup.launch dual_camera:=true
```

This bringup additionally starts `camera.py` (opens `/dev/video0`) and
`rosserial` to the Arduino (`/dev/ttyUSB0`) — both **fail without the
hardware**, so do not use it for the headless smoke test. Plug the camera
in **before** `roslaunch` (see CLAUDE.md notes); hot-plug works at the
`/dev/video0` level but a node started before the device exists won't
recover on its own.

## Test (unit/build sanity)

```bash
make shell
cd /root/catkin_ws && catkin_make        # rebuild after C++/msg changes
```

## Gotchas (battle scars — all hit this session)

- **`lane_detect_v2.py` defaults `image_topic` to `/dev/video0`** and
  opens it as *hardware* (`cv2.VideoCapture`). To make it **subscribe**
  to a topic you must pass `_image_topic:=/camera/image_raw`. Without it
  the node logs `Failed to open video port: /dev/video0` and never
  subscribes. `turn_detect.py` defaults to `/camera/image_raw` and
  subscribes — the two nodes are **asymmetric**, easy to trip on.
- **Nodes run from `devel/lib/lane_follower/*.py`,** not the source path.
  `pkill -f lane_detect_v2` from the source name misses them — match
  `devel/lib/lane_follower`. (The driver does this.)
- **`roscore` is not auto-started.** The entrypoint only does
  `catkin_make` + drops to a shell. `rosrun` without a running master
  gives `Unable to communicate with master!`. Start `roscore` (or use
  `roslaunch`, which starts one).
- **`docker exec` shells don't inherit the workspace env.** Always
  `source /root/catkin_ws/devel/setup.bash` inside `bash -lc` before any
  `ros*` command, or `rospack`/`rosrun` won't find `lane_follower`.
- **The detector assumes dark lines on a light floor** (`THRESH_BINARY_INV`).
  A synthetic frame must be dark lanes on a light background or the
  detector finds nothing and `/lane_detect` shows `status` other than ok.
- **Headless image:** `opencv-python-headless`, no X. Keep
  `show_window:=false`; never add `cv2.imshow`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Unable to communicate with master!` | roscore not running, or you didn't `source devel/setup.bash` in that shell. |
| `Failed to open video port: /dev/video0` in `/tmp/lane_detect.log` | You launched `lane_detect_v2.py` without `_image_topic:=/camera/image_raw`. |
| `/lane_detect` empty but nodes alive | Check `/tmp/fake_camera.log` in the container — likely no frames being published, or a `cv_bridge` encoding error. |
| Debug PNG is blank gray | Detector saw no lanes — frame isn't dark-on-light, or ROI/threshold params off. |
| `make up` errors on missing image | Run `make build` first (one-time). |
