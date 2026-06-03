# Build errors: catkin_make / catkin build / CMake

## First, which build tool is this workspace using?

There are two and they are **not compatible in the same workspace**:
- `catkin_make` — the classic tool, builds the whole workspace as one CMake
  project. Leaves `build/` + `devel/` at the workspace root.
- `catkin build` (from `python3-catkin-tools`) — builds each package
  isolated. Leaves a `.catkin_tools/` marker and per-package build spaces.

```bash
ls -a              # .catkin_tools present -> catkin build; plain build/CMakeCache.txt -> catkin_make
```

**Symptom of mixing them:** builds that worked suddenly throw strange CMake or
linker errors after someone ran the other tool. **Fix:** pick one tool, wipe,
rebuild. With catkin_tools: `catkin clean -y`. With catkin_make: `rm -rf build
devel` (propose before running — it forces a full rebuild). Then build with the
chosen tool only.

## `Could not find a package configuration file provided by "X"`

CMake can't find a dependency. Two sub-cases:

1. **Dependency not installed.** Most ROS deps install via the system. Run the
   standard resolver from the workspace root:
   ```bash
   rosdep install --from-paths src --ignore-src -r -y
   ```
   (See `references/dependencies.md` if `rosdep` itself misbehaves.)
2. **Dependency installed but not declared**, so CMake doesn't look for it. The
   package's `CMakeLists.txt` needs the component in
   `find_package(catkin REQUIRED COMPONENTS ... X)` and `package.xml` needs a
   matching `<depend>X</depend>`. Add both, then rebuild.

After fixing, source again before building — use the file matching your shell
(`.zsh` for zsh, `.bash` for bash):
```bash
source /opt/ros/noetic/setup.zsh
```

## Stale cache: errors referencing old/absolute paths

Common after a container is rebuilt, a workspace is copied, or paths moved.
`build/CMakeCache.txt` pins absolute paths from the previous environment.

**Fix:** remove the build artifacts and rebuild (propose first — it's a full
rebuild): `rm -rf build devel` (catkin_make) or `catkin clean -y` (tools).

## `c++: fatal error: Killed signal terminated program cc1plus` / OOM

The compiler was killed by the OOM killer — too many parallel jobs for the
container's memory limit (very common with large packages like PCL/OpenCV in a
memory-capped container).

```bash
free -h                       # see available memory
catkin_make -j1               # or:  catkin build -j1 -p1
```
Limiting parallelism trades speed for not dying. If you control the container,
raising its memory (`docker run -m`) is the other lever.

## Sourcing order matters

Source the file matching your shell (`setup.zsh` for zsh, `setup.bash` for
bash; the wrong one errors out under zsh).

- Before building: source `/opt/ros/noetic/setup.zsh`.
- After building: source the workspace `devel/setup.zsh` so your packages are
  found.
- With overlays (workspace on top of another), source them in dependency order;
  the last one sourced wins on `$PATH`/`$ROS_PACKAGE_PATH`. A wrong order makes
  `roslaunch`/`rosrun` find the wrong package or none.

## Noetic = Python 3

Noetic runs on Python 3. Two frequent build/runtime snags:
- **Shebang:** scripts with `#!/usr/bin/env python` may find Python 2 or
  nothing. Use `#!/usr/bin/env python3`.
- **Installing python nodes:** declare them with `catkin_install_python(...)` in
  `CMakeLists.txt` so they get the right interpreter and the executable bit on
  install.
