#!/usr/bin/env bash
# ros1_doctor.sh — read-only diagnostic snapshot for ROS1 (Noetic) in Docker.
# Run this INSIDE the target container. It changes nothing and is safe to repeat.
# Every probe is time-limited so a dead master can't make it hang.
set +e

line() { printf '\n==== %s ====\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
run()  { echo "\$ $*"; timeout 5 "$@" 2>&1; echo; }

line "HOST / CONTAINER"
echo "date:        $(date 2>/dev/null)"
echo "hostname:    $(hostname 2>/dev/null)"
echo "hostname -I: $(hostname -I 2>/dev/null)"
echo "uname:       $(uname -a 2>/dev/null)"
echo "login shell: ${SHELL:-unknown}  (source the matching setup.* : zsh->setup.zsh, bash->setup.bash)"

line "ROS ENVIRONMENT"
env | grep -iE '^ROS_|^CMAKE_PREFIX_PATH=|^LD_LIBRARY_PATH=|^PYTHONPATH=' | sort
echo "--- key vars ---"
for v in ROS_MASTER_URI ROS_IP ROS_HOSTNAME ROS_DISTRO ROS_PACKAGE_PATH; do
  echo "$v=${!v}"
done
if [ -z "$ROS_MASTER_URI" ]; then
  echo "WARNING: ROS_MASTER_URI is empty -> the ROS setup file is almost certainly not sourced in this shell (source setup.zsh for zsh, setup.bash for bash)."
fi
if [ -z "$ROS_IP" ] && [ -z "$ROS_HOSTNAME" ]; then
  echo "NOTE: neither ROS_IP nor ROS_HOSTNAME is set. Fine with --net=host on one host,"
  echo "      but a very common cause of cross-container 'topic lists but no data' failures."
fi

line "ROS INSTALL"
[ -d /opt/ros ] && echo "distros under /opt/ros: $(ls /opt/ros 2>/dev/null | tr '\n' ' ')"
have rosversion && run rosversion -d
echo -n "setup files: "; ls /opt/ros/*/setup.* 2>/dev/null | tr '\n' ' '; echo
ls /opt/ros/*/setup.bash >/dev/null 2>&1 || echo "  (no setup.bash found under /opt/ros/*/ — is ROS installed there?)"

line "WORKSPACE"
found_ws=0
for ws in "$PWD" "$HOME/catkin_ws" /catkin_ws /root/catkin_ws /workspace "$HOME/ws"; do
  if [ -d "$ws/src" ] || ls "$ws"/devel/setup.* >/dev/null 2>&1; then
    found_ws=1
    echo "candidate workspace: $ws"
    if ls "$ws"/devel/setup.* >/dev/null 2>&1; then
      echo "  devel/setup.* present: $(ls "$ws"/devel/setup.* 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')"
    else
      echo "  devel/setup.*: MISSING (workspace not built yet?)"
    fi
    tools=0
    if [ -e "$ws/.catkin_tools" ]; then echo "  built with: catkin build (catkin_tools)"; tools=1; fi
    if [ -f "$ws/build/CMakeCache.txt" ]; then echo "  build/CMakeCache.txt: present (catkin_make-style or cmake)"; fi
    if [ "$tools" = 1 ] && [ -f "$ws/build/CMakeCache.txt" ] && ! [ -d "$ws/build/.built_by" ]; then
      echo "  WARNING: signs of BOTH catkin build and catkin_make in one workspace."
      echo "           This corrupts the workspace. Pick ONE tool, then 'catkin clean' or rm -rf build devel and rebuild."
    fi
  fi
done
[ "$found_ws" = 0 ] && echo "no obvious catkin workspace in cwd or common locations"

line "MASTER REACHABILITY"
if [ -n "$ROS_MASTER_URI" ]; then
  mhost=$(echo "$ROS_MASTER_URI" | sed -E 's#^https?://##; s#:.*$##')
  mport=$(echo "$ROS_MASTER_URI" | sed -E 's#.*:##; s#/.*$##'); mport=${mport:-11311}
  echo "master host: $mhost   port: $mport"
  if have getent; then
    echo "resolve $mhost:"; getent hosts "$mhost" || echo "  NOT RESOLVABLE -> fix /etc/hosts, use an IP, share a user-defined docker network, or use --net=host"
  fi
  have ping && run ping -c1 -W1 "$mhost"
  if have nc; then
    echo "\$ tcp check ${mhost}:${mport}"
    if timeout 3 nc -z "$mhost" "$mport" 2>/dev/null; then echo "  reachable"; else echo "  NOT reachable on TCP (master down, wrong host, or blocked by docker network)"; fi
    echo
  fi
else
  echo "ROS_MASTER_URI empty -> cannot check master."
fi

line "ROS GRAPH (5s timeouts)"
have rosnode    && run rosnode list
have rostopic   && run rostopic list
have rosservice && run rosservice list
have rosparam   && run rosparam list

line "LISTENING SOCKETS (looking for master :11311)"
if have ss; then
  ss -tlnp 2>/dev/null | grep -E ':11311' || { echo "(no listener on 11311 in this netns)"; ss -tlnp 2>/dev/null | head -15; }
elif have netstat; then
  netstat -tlnp 2>/dev/null | grep ':11311' || netstat -tlnp 2>/dev/null | head -15
else
  echo "neither ss nor netstat available"
fi

line "/etc/hosts"
cat /etc/hosts 2>/dev/null

line "APT / ROS SOURCES"
ls /etc/apt/sources.list.d/ 2>/dev/null
grep -rhiE 'packages\.ros\.org|ros' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null | sed '/^#/d' | sort -u
echo "(if apt update fails on a key: the ROS apt key was rotated in 2021; see references/dependencies.md)"

line "RECENT ROS ERROR LOG LINES"
logdir="${ROS_LOG_DIR:-$HOME/.ros/log}"
if [ -d "$logdir" ]; then
  latest=$(ls -1dt "$logdir"/*/ 2>/dev/null | head -1)
  echo "latest log dir: ${latest:-none}"
  if [ -n "$latest" ]; then
    echo "--- last error/fatal/exception lines ---"
    grep -rhiE 'error|fail|exception|fatal|traceback' "$latest" 2>/dev/null | tail -30
  fi
else
  echo "no log dir at $logdir (no node has run yet, or ROS_LOG_DIR points elsewhere)"
fi

line "DONE"
echo "Snapshot complete. Nothing was modified. Read the WARNING/NOTE lines above first."
