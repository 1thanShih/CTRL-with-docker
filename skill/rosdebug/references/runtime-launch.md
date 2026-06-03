# Runtime, roslaunch, and environment / sourcing

## The fresh-`docker exec` trap (check this first for "command/package not found")

Every `docker exec <c> <shell>` opens a **new non-login, non-interactive
shell**. The interactive rc file (`~/.zshrc` for zsh, `~/.bashrc` for bash)
often does NOT run in that mode, so any sourcing placed there never executes and
the new shell has no ROS environment at all. Symptoms: `rosrun: command not
found`, `roslaunch: command not found`, or `[rospack] Error: package 'X' not
found` even though it's installed and built.

```bash
echo $ROS_MASTER_URI          # empty -> nothing was sourced
echo $ROS_PACKAGE_PATH        # empty/missing your ws -> workspace not sourced
echo $0                       # which shell am I actually in? (zsh / bash)
```

**Source the file that matches the active shell** — this matters, because
`setup.bash` uses bash syntax and errors out under zsh (that's exactly why ROS
ships a separate `setup.zsh`):

```bash
# zsh:
source /opt/ros/noetic/setup.zsh
source ~/catkin_ws/devel/setup.zsh    # if a workspace is involved
# bash equivalent: source the .bash files instead
```

Durable fix: source the matching files from the image's `ENTRYPOINT`, or run
the command through a shell that sources first
(`docker exec <c> zsh -lc 'source /opt/ros/noetic/setup.zsh; <cmd>'`). Relying
on an interactive rc file (`~/.zshrc` / `~/.bashrc`) is the usual root cause.

## Reading what actually went wrong

ROS hides node output by default under roslaunch. Make it visible:
```bash
roslaunch --screen pkg file.launch    # force all node stdout/stderr to console
rosrun pkg node                        # run a single node directly to see its stderr
```
Logs on disk (the diagnostic script already tails these):
```bash
ls -dt ~/.ros/log/*/ | head -1         # newest run's log dir
cat ~/.ros/log/latest/rosout.log       # aggregated rosout
```

## Node starts then dies

Isolate to that one node with `rosrun` (above) so its error reaches the
console, then read the message:
- **Missing parameter** (`KeyError`, "param not set") -> the node read a param
  that wasn't loaded; check load order and the `<rosparam>`/`<param>` in the
  launch file: `rosparam list`, `rosparam get /ns/param`.
- **Python traceback** -> usually a code/import/Python2-vs-3 issue; the traceback
  names the file and line. Check the shebang is `python3`.
- **Segfault / `Killed`** -> for `Killed` check OOM (`dmesg | tail`, `free -h`);
  for a true segfault, an ABI/library mismatch or a bug in C++ code — reproduce
  under `gdb --args <node> ...` and get a backtrace if needed.

## roslaunch errors

- `Invalid roslaunch XML` / parse error -> the launch file is malformed; the
  message gives a line number. Common: unclosed tag, bad `$(arg ...)`,
  `$(find pkg)` for a package that isn't on `ROS_PACKAGE_PATH` (sourcing again).
- `Cannot load command parameter [rosversion]` / env-substitution errors ->
  environment not sourced.
- `required` node died -> roslaunch tears down the whole launch when a node
  marked `required="true"` exits; find that node's own error (use `--screen`).

## roscore / master lifecycle

- `roscore` must be running somewhere reachable before nodes start. `roslaunch`
  will auto-start a master only if one isn't already configured/running.
- Two masters by accident (one from a stray `roscore`, one auto-started) causes
  nodes to split across registries. Check `ss -tlnp | grep 11311` and
  `echo $ROS_MASTER_URI` are consistent across containers.

## roswtf

Run it inside the sourced environment as a broad first/last check — it inspects
the running graph and environment and reports many of the problems above
(unreachable master, env issues, dead nodes) on its own.
