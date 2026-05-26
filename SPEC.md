# Spec: CTRL-with-docker — Slim Pi-Friendly Refactor

## Objective

Restructure the existing DLV / lane-following workspace so that it runs lean on a Raspberry Pi 4 (4GB) inside the existing `ros:noetic-perception` container, and so that `claude` (Claude Code CLI) is usable from inside the container. Only the code paths actually used in production are kept under `catkin_ws/src/`; unused packages are moved to a `legacy/` folder (preserved but not built). The result is a smaller, clearer, headless container image that is fast to (re)build on the Pi itself.

**Target platform:** Raspberry Pi 4 (4GB), ARM64, headless (no display attached). Runs on a TurtleBot chassis with an Arduino Mega + USB camera. No rviz, no X11.

**Success looks like:**
- `make` builds and starts the container on a Pi 4 without errors.
- `catkin_make` inside the container compiles cleanly with no references to removed packages.
- `roslaunch lane_follower lane_detect_bringup.launch` brings up: camera → lane_detect_v2 → turn_detect → lane_controller_fuzzy → rosserial → Arduino, and the robot drives.
- `claude` works inside the container (login once, persists across container restarts via mounted credential dir).
- Image size measurably smaller than current (target: at least 300MB reduction vs. current `ros:noetic-perception` + extras).
- No package under `catkin_ws/src/` other than the kept set; everything else is under `legacy/` and ignored by `catkin_make`.

## Tech Stack

- **OS / Base image:** `ros:noetic-perception` (ARM64 multi-arch image), Ubuntu 20.04 Focal
- **ROS:** Noetic
- **Languages:** Python 3.8 (ROS nodes), C++ (only where already present), Bash (entrypoint/scripts)
- **Build system:** catkin (`catkin_make`)
- **Python deps:** `opencv-python-headless` (NOT `opencv-python`), `numpy`, `scikit-fuzzy`, `cv_bridge` (apt)
- **Bridge:** `ros-noetic-rosserial-python` for Arduino comms
- **Shell:** zsh (already in use)
- **Dev CLI in container:** Node.js LTS + `@anthropic-ai/claude-code` (npm global)
- **Container runtime:** Docker, `--privileged --net=host`, bind-mount `catkin_ws/`

## Commands

Host-side (Makefile targets):

```bash
make             # docker build + docker run (foreground zsh)
make attach      # exec a second zsh into running container
make stop        # stop + remove container
make clean       # stop container + remove image
make logs        # docker logs -f ros-noetic-zsh
```

Inside container:

```bash
# Build workspace
cd /root/catkin_ws && catkin_make && source devel/setup.zsh

# Run integrated lane-follow stack
roslaunch lane_follower lane_detect_bringup.launch

# Drive forward briefly (smoke test, no perception)
rosrun arduino_mega_ctrl move_straight_5s.py

# Claude Code (creds stored in `ctrl-claude-home` named volume — host's
# ~/.claude is NOT mounted in)
claude              # interactive
claude login        # first run only; or run `make login` from the host
```

Removed: `make rviz` (headless target — no GUI).

## Project Structure

```
CTRL-with-docker/
├── Dockerfile                # slim, ARM64-friendly, Claude Code installed
├── Makefile                  # host-side container lifecycle (no rviz target)
├── CLAUDE.md                 # project guidance (updated to reflect new layout)
├── SPEC.md                   # this file
├── scripts/
│   ├── entrypoint.sh         # catkin_make + source + udev reload
│   ├── arduino.rules         # /dev/arduino symlink
│   └── camera.rules          # /dev/camera symlink
├── catkin_ws/
│   └── src/
│       ├── CMakeLists.txt    # catkin top-level (symlink, unchanged)
│       ├── lane_follower/        # KEPT — perception + fuzzy controller
│       │   ├── scripts/
│       │   │   ├── lane_detect_v2.py
│       │   │   ├── turn_detect.py
│       │   │   └── lane_controller_fuzzy.py
│       │   ├── launch/lane_detect_bringup.launch
│       │   ├── msg/{LaneData.msg, TurnDetect.msg}
│       │   ├── CMakeLists.txt
│       │   └── package.xml
│       ├── arduino_mega_ctrl/    # KEPT — Twist → Arduino helpers
│       ├── sensors/
│       │   └── camera/           # KEPT — publishes /camera/image_raw
│       └── rosserial/            # KEPT placeholder if needed for build deps
└── legacy/                    # NOT built by catkin; reference only
    ├── lane_follower_v1/
    │   ├── lane_detect.py          # old v1 detector
    │   └── lane_controller.py      # old PD controller
    ├── simple_twist_publisher/
    ├── sensors_rplidar_ros/
    └── dlv_bringup/
```

Key invariant: `catkin_ws/src/` contains ONLY packages we actively build and run. `legacy/` is sibling to `catkin_ws/`, never symlinked into the workspace, never sourced.

## Code Style

- **Comments / log messages:** mixed Chinese + English is fine — match the file's existing style. Don't translate existing comments wholesale.
- **Python:** match existing node style (rospy, snake_case, single-class node where there is per-node state). Example:

```python
#!/usr/bin/env python3
import rospy
from sensor_msgs.msg import Image
from lane_follower.msg import LaneData

class LaneDetector:
    def __init__(self):
        self.sub = rospy.Subscriber('/camera/image_raw', Image, self.cb, queue_size=1)
        self.pub = rospy.Publisher('lane_detect', LaneData, queue_size=1)

    def cb(self, msg):
        # 取得影像 → 處理 → 發 LaneData
        ...

if __name__ == '__main__':
    rospy.init_node('lane_detect_v2')
    LaneDetector()
    rospy.spin()
```

- **Dockerfile:** group `apt-get install` into one RUN with `--no-install-recommends` and `rm -rf /var/lib/apt/lists/*` at the end of the same layer. Pin Node major version. Keep one logical step per layer.
- **Launch files:** Tunable params (turn thresholds, hard-turn ω/duration, sign-detect threshold, cooldown) stay as `<param>` in `lane_detect_bringup.launch` — this is the primary tuning surface, don't bury them inside Python.
- **Custom msgs:** any change to `LaneData` / `TurnDetect` requires `catkin_make` before Python imports re-resolve.

## Testing Strategy

This is a robotics repo with no test suite today; we do not introduce a unit test framework as part of this refactor. Verification is operational:

1. **Build check (every change):** `catkin_make` inside the container must complete with zero errors and zero "package not found" warnings for the kept set.
2. **Launch smoke (every meaningful change):** `roslaunch lane_follower lane_detect_bringup.launch` starts without missing-node / missing-topic errors. `rostopic list` shows `/camera/image_raw`, `/lane_detect`, `/lane_detect/image_out`, `/turn_detect`-equivalent, and `/arduino_vel`.
3. **Driving smoke (before claiming done):** on the actual Pi/TurtleBot, run the bringup and confirm the robot can follow a straight lane segment (no perception regressions vs. current behavior).
4. **Image size check:** `docker images ros-noetic-zsh:latest` — record before/after. Target ≥300MB reduction.
5. **Claude Code check:** inside container, `claude --version` works; `claude` opens an interactive session.

If any later feature needs real tests, that's a separate spec.

## Boundaries

**Always:**
- Move removed packages into `legacy/` rather than deleting them. Preserve git history (use `git mv`).
- Run `catkin_make` after any `.msg` change before claiming a Python node works.
- Keep `--privileged --net=host` on the container — needed for udev and ROS multicast.
- Use `opencv-python-headless` (NOT `opencv-python`) to avoid pulling X libs.
- Pin Node.js major version in the Dockerfile (don't track "latest").

**Ask first:**
- Changing the base image away from `ros:noetic-perception`.
- Touching node behavior inside `lane_follower/scripts/` — the recent commit history is all behavior tuning; the user owns those parameters.
- Adding any new ROS package or new apt dependency to the image.
- Changing the bind-mount layout for `catkin_ws/`.
- Changing how Claude Code credentials are stored (default: `ctrl-claude-home` named volume, fully isolated from host `~/.claude`).

**Never:**
- Delete `legacy/` contents (even if "obviously unused").
- Commit secrets, Claude auth tokens, or `~/.claude/` contents.
- Rebuild the image on `make attach` (attach must be cheap).
- Add X11 / rviz / GUI dependencies back into the runtime image.
- Modify `lane_detect_v2.py`, `turn_detect.py`, `lane_controller_fuzzy.py` algorithmic logic as part of this refactor — moves/renames only if needed, no behavior changes.
- Use `--no-verify` or skip hooks.

## Success Criteria (testable)

- [ ] `catkin_ws/src/` contains exactly: `lane_follower`, `arduino_mega_ctrl`, `sensors/camera`, `rosserial` (+ top-level `CMakeLists.txt`). Nothing else.
- [ ] `legacy/` exists and contains the old v1 lane code, PD controller, `simple_twist_publisher`, `rplidar_ros`, `dlv_bringup`, preserved with `git mv` history.
- [ ] `make` on a clean Pi 4 produces a running container with a successfully built workspace.
- [ ] `docker images` shows the new image is at least 300MB smaller than the previous one.
- [ ] `claude --version` runs inside the container.
- [ ] In-container Claude state lives in the `ctrl-claude-home` named volume; host `~/.claude` is **not** mounted in. `make login` populates it; the token survives `--rm`.
- [ ] `roslaunch lane_follower lane_detect_bringup.launch` runs end-to-end on the robot, no missing-package errors.
- [ ] `make rviz` target is removed; no X11 packages installed in the image.
- [ ] `CLAUDE.md` updated to reflect the new package set and removed targets.

## Open Questions

1. Should `rosserial/` placeholder package directory under `catkin_ws/src/` stay (it's currently empty — the real rosserial packages come from apt)? My default: **remove the empty dir** since apt provides everything. Confirm or override.
2. Are there any `.rules` files we need to add (`plate.rules`, `realsensecamera.rules`) or can the corresponding `cp` lines just be dropped from `entrypoint.sh`? My default: **drop the dead `cp` lines** since the hardware isn't present.
3. Claude Code auth: how to persist `/root/.claude` across `--rm` runs? **Resolved (2026-05-26):** use a Docker named volume `ctrl-claude-home`, NOT a bind to host `~/.claude`. Host filesystem stays untouched; `make login` populates the volume once.
4. Should we add a `.dockerignore` to keep `legacy/` out of build context (faster builds)? My default: **yes**.

Defaults will be applied unless overridden during Plan phase.
