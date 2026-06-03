# Dependencies: rosdep, apt, ROS GPG keys, Noetic EOL

## The normal dependency command

From the workspace root, this installs declared dependencies for everything in
`src/` while skipping the packages you're building yourself:

```bash
rosdep install --from-paths src --ignore-src -r -y
```

If it errors, the problem is usually `rosdep`'s own state or the apt layer
underneath, not your packages.

## `rosdep` not initialized / update fails

Symptoms: `ERROR: cannot download default sources list from ...`, or `rosdep`
complains it isn't initialized.

```bash
sudo rosdep init      # only once per machine; "already exists" is harmless
rosdep update         # run as the normal user, NOT with sudo
```

- Running `rosdep update` with `sudo` writes cache to root's home and then your
  user can't read it — run it unprivileged.
- In a locked-down container, `rosdep init/update` fetches from
  `raw.githubusercontent.com`; if egress is blocked it will fail. Either allow
  that host, or pre-bake the rosdep cache into the image, or point
  `ROSDISTRO_INDEX_URL` at an internal mirror.

## `apt update` fails on a ROS GPG key

The ROS apt signing key was rotated in 2021; images or instructions from before
then carry the expired key and fail with `NO_PUBKEY` / `EXPKEYSIG`. Fix by
installing the current key into a keyring and referencing it from the source
list. The canonical source line for Noetic on Ubuntu 20.04 (focal) is the
`packages.ros.org/ros/ubuntu focal main` repo, signed by the current ROS key
fetched from `raw.githubusercontent.com/ros/rosdistro/master/ros.asc` (or the
`ros-archive-keyring`). After updating the key + source list:

```bash
sudo apt update
```

Confirm the ROS repo line resolves and the key is no longer reported expired.

## `Unable to locate package ros-noetic-...`

- The ROS apt source isn't configured (see the key/source step above), or
- `apt update` hasn't been run since adding it, or
- the package name is wrong — search: `apt-cache search ros-noetic- | grep -i <thing>`.

## Noetic is end-of-life — what that means here

ROS Noetic reached end of life in May 2025. Practically:
- The `packages.ros.org` Noetic/focal repository is generally still reachable,
  so normal installs usually keep working — don't assume EOL is the cause of an
  apt failure; check the key/source first.
- No new upstream fixes ship. If a specific binary has been pulled, you may need
  to build that package from source in the workspace, or pin to a snapshot
  mirror. Treat "build from source" as a fallback, not a first move.
