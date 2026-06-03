---
name: rosdebug
description: >-
  Debug and fix ROS1 (Noetic, Ubuntu 20.04) problems that occur inside Docker
  containers, in an environment where Claude can run diagnostic commands
  directly in the container and read their output. Use this whenever the user
  hits any ROS1 error or unexpected behavior: catkin_make / catkin build
  failures, CMake "Could not find a package configuration file" errors, nodes
  that crash or won't start, topics that appear in `rostopic list` but carry no
  data, cross-container communication problems (ROS_MASTER_URI / ROS_IP /
  ROS_HOSTNAME), rosdep or apt dependency and GPG-key failures, roslaunch
  errors, or environment / sourcing issues (setup.bash not sourced). Trigger it
  even when the user just pastes a red CMake error, a Python traceback, or says
  things like "my node can't talk to the master" or "rostopic echo just hangs"
  without explicitly naming ROS or Docker.
---

# ROS1-in-Docker Debugging

You can execute commands inside the target container (e.g. via `docker exec`,
or you are already in a shell in it). Your job is to find the **root cause** of
a ROS1 Noetic problem, fix it, and prove the fix worked — not to guess from the
error message alone.

## Starting the session

This skill is often invoked explicitly (e.g. the user types a slash command)
*before* describing a concrete failure. Adapt to what you have:

- **A specific error or symptom is already given** (a pasted CMake error, a
  traceback, "echo hangs," a screenshot of red text) → classify it with the
  triage table and start the loop. Don't re-ask what's already clear.
- **No concrete problem yet** → ask one focused question to get moving: what's
  failing right now (build / a node / cross-container comms / install), and how
  you reach the container (the `docker exec` target or that you're already in a
  shell). Offer to run the snapshot immediately as the first step. Don't
  interrogate the user with a long checklist — one good question, then act.

## The one idea that solves most cases

A large share of "ROS bugs" inside Docker are not ROS bugs at all — they are
**container-boundary bugs**: environment not sourced in a fresh `docker exec`
shell, `ROS_IP` / `ROS_HOSTNAME` advertising an address the other container
can't route to, a master that isn't reachable across the docker network, or a
clock/`use_sim_time` mismatch. So before blaming a node or a build, check the
boundary. The triage table below routes you there fast.

## Operating principles

- **Establish ground truth before theorizing.** The error text tells you the
  symptom, not the cause. Run commands to see what is *actually* running, what
  the environment *actually* is, and what the master *actually* knows. Assume
  nothing about `ROS_MASTER_URI`, sourcing, or which build tool was used.
- **Change one variable at a time.** ROS failures are often a chain (env →
  master → registration → connection). If you change three things at once you
  learn nothing from the result.
- **Default to non-destructive.** Diagnosis is read-only. Anything that deletes
  or rebuilds (`rm -rf build devel`, `catkin clean`, reinstalling packages,
  editing source) you propose first and run only after the user agrees, because
  it can cost them a long rebuild or lose local changes.
- **Always verify the fix against the original symptom.** If the complaint was
  "echo hangs," re-run `rostopic echo` and confirm data flows. A fix you didn't
  verify is a hypothesis.
- **Explain the why.** State the root cause in one or two sentences so the user
  understands the mechanism, not just the magic command. This is what stops the
  bug from recurring.
- **Source the file that matches the shell.** Check the active shell (`echo $0`)
  before sourcing. ROS ships `setup.bash`, `setup.zsh`, and `setup.sh`;
  sourcing `setup.bash` under zsh errors out. Use `setup.zsh` in zsh,
  `setup.bash` in bash — and remember each fresh `docker exec` is a new shell
  with nothing sourced yet.

## The debugging loop

1. **Snapshot the environment.** Run the bundled diagnostic to get a full
   read-only picture in one shot instead of issuing fifteen separate commands:

   ```bash
   bash scripts/ros1_doctor.sh
   ```

   (Copy it into the container if needed, e.g.
   `docker cp scripts/ros1_doctor.sh <container>:/tmp/ && docker exec <container> bash /tmp/ros1_doctor.sh`.)
   It reports env vars, ROS install, workspace state, master reachability, the
   live ROS graph, listening sockets, `/etc/hosts`, apt/ROS sources, and recent
   error log lines. Read its WARNING/NOTE lines first.

2. **Classify the failure** into one of the rows in the triage table and open
   the matching reference file. Don't read all references — read the one that
   fits.

3. **Isolate to the smallest failing unit.** One node, one topic pair, one
   build target, one package. Reproduce the failure on that unit before
   theorizing about the whole system.

4. **Form a hypothesis and test it cheaply.** Prefer a quick probe (`rosnode
   ping`, `nc -z`, `rostopic hz`, `roswtf`) over an expensive action (full
   rebuild). Confirm or kill the hypothesis, then move on.

5. **Apply the fix, then verify.** Re-run the exact thing the user complained
   about. Then do a quick sanity check that you didn't break a neighbor
   (`roswtf`, `rostopic list`).

6. **Report:** root cause (1-2 sentences) → the fix you applied (exact commands
   or file diff) → the verification output that proves it. Reply in the user's
   language.

## Fast triage table

| Symptom | Most likely cause | Go to |
| --- | --- | --- |
| `rosrun` / `roslaunch` says *command not found* or *package not found* in a fresh shell | ROS setup file (`setup.zsh`/`setup.bash`) not sourced in this `docker exec` session, or workspace not built | `references/runtime-launch.md` |
| Topic shows in `rostopic list` but `rostopic echo` hangs / no data | Cross-container `ROS_IP`/`ROS_HOSTNAME` not routable; TCPROS connection can't be made | `references/networking.md` |
| `Unable to register with master node` / `Couldn't find an AF_INET address` / connection refused on 11311 | `ROS_MASTER_URI` wrong/unreachable, roscore not running, or docker network isolation | `references/networking.md` |
| TF: *extrapolation into the future/past*, *message removed because it is too old* | Clock or `use_sim_time` mismatch between containers | `references/networking.md` |
| CMake: *Could not find a package configuration file provided by ...* | Missing dependency (not installed, or not declared) | `references/build.md` |
| Build breaks right after switching build tools, or weird stale CMake errors | Mixed `catkin_make` + `catkin build`, or stale `CMakeCache.txt` | `references/build.md` |
| Compiler *Killed (signal 9)* / OOM during build | Too many parallel jobs for the container's memory | `references/build.md` |
| `rosdep init/update` fails, or `apt update` fails on a ROS GPG key | rosdep not initialized / network blocked / expired ROS apt key | `references/dependencies.md` |
| Node starts then dies; segfault; exception; params missing | Runtime crash — needs logs and isolation | `references/runtime-launch.md` |
| `.launch` XML error, missing arg, node won't spawn | launch file or env problem | `references/runtime-launch.md` |

When in doubt, `roswtf` is ROS's own built-in checker and a strong first probe —
run it inside the sourced environment and read its warnings.

## Reference files

- `references/networking.md` — master reachability, `ROS_MASTER_URI` /
  `ROS_IP` / `ROS_HOSTNAME`, cross-container topic flow, docker networks, time sync.
- `references/build.md` — `catkin_make` vs `catkin build`, CMake/dependency
  errors, stale caches, OOM, Python3 specifics.
- `references/dependencies.md` — `rosdep`, apt sources, ROS GPG keys, Noetic EOL.
- `references/runtime-launch.md` — reading logs, node crashes, `roslaunch`,
  environment / sourcing in `docker exec` shells.

## When the fix is destructive

Rebuilding a workspace, deleting `build/`+`devel/`, reinstalling system
packages, or editing the user's source files can cost real time or lose work.
For these: explain what you want to do and why, show the exact command, and let
the user confirm. The diagnostic script and all `ros*` query commands are safe
to run without asking.
