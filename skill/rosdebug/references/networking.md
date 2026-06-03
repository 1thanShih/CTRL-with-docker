# Networking: master, ROS_IP/ROS_HOSTNAME, cross-container topics, time

ROS1 uses two channels. The **master** (roscore) speaks XMLRPC on port `11311`
and acts as a name registry only. Actual topic data flows **node-to-node** over
**TCPROS**, on ports the OS picks dynamically. The master never relays data — it
just tells a subscriber the *URI of the publisher*, and the subscriber then
connects directly. This two-stage design is why so many Docker cases show
"topic exists but no data": registration (stage 1) succeeds, the direct
connection (stage 2) fails because the advertised address isn't routable.

## How a node decides the address it advertises

When a node registers, it tells the master "reach me at X". X is chosen in this
order: `ROS_IP` → `ROS_HOSTNAME` → the system hostname. Inside Docker the system
hostname is the container ID, which the *other* container usually cannot
resolve. That is the core trap.

## Case A: `rostopic echo` hangs / topic lists but no data

Confirm the shape of the failure first:

```bash
rostopic list                 # topic is registered -> stage 1 OK
rostopic info /the/topic      # shows publisher node + its advertised URI
rosnode info /publisher_node  # shows the URI the master will hand out
rostopic hz /the/topic        # no messages -> stage 2 (direct connect) failing
```

If `rosnode info` shows a URI like `http://<container-id>:4567/` that the
subscriber's container can't resolve or route to, that's the bug.

**Fixes (pick the one that matches the setup):**

- **Single host, simplest:** run all containers with `--net=host`. They then
  share the host's network stack and `localhost`/host IP just works. Linux only;
  not available on Docker Desktop for Mac/Windows.
- **User-defined docker network (recommended for multi-container):**
  `docker network create rosnet`, run every container with `--network rosnet`,
  and give each a stable name (`--name talker`, `--name listener`). Docker's
  embedded DNS then resolves container names. Set on each node container:
  `export ROS_HOSTNAME=<its-own-container-name>` and
  `export ROS_MASTER_URI=http://<master-container-name>:11311`. Now advertised
  names are resolvable both ways.
- **Explicit IP:** set `ROS_IP` to the container's address on the shared network
  (`hostname -I`), on **both** publisher and subscriber sides. Both sides need a
  routable advertised address because the subscriber connects out to the
  publisher — and some handshakes go the other way too.

Verify: `rostopic echo /the/topic` now prints messages; `rostopic hz` shows a
rate.

## Case B: can't even reach the master

Symptoms: `Unable to register with master node`, `ERROR: Unable to communicate
with master!`, `connection refused`, or `Couldn't find an AF_INET address for
[hostname]`.

```bash
echo $ROS_MASTER_URI                       # is it set and pointing at the right host?
getent hosts <master-host>                 # does the name resolve?
nc -z <master-host> 11311 && echo TCP-OK   # is the port reachable?
ss -tlnp | grep 11311                      # (on the master container) is roscore listening?
```

Causes and fixes:
- **roscore not running** in the master container -> start it (`roscore &` or a
  dedicated container).
- **`ROS_MASTER_URI` points at `localhost`** while the master is in another
  container -> point it at the master container's name/IP on the shared network.
- **Containers on different networks / default bridge with no DNS** -> put them
  on one user-defined network (see Case A).
- **`AF_INET` error** -> the *local* node can't resolve its own
  `ROS_HOSTNAME`/hostname -> set `ROS_IP` to a real IP or add the name to
  `/etc/hosts`.

## Case C: TF / clock errors across containers

Symptoms: `Lookup would require extrapolation into the future/past`, `TF_OLD_DATA
... message removed because it is too old`, transforms intermittently missing.

```bash
rosparam get /use_sim_time          # if true, everything must run on /clock
rostopic hz /clock                  # is a clock being published?
date                                # compare wall clocks across containers
```

Causes and fixes:
- **`use_sim_time` mismatch:** if one node has it `true` and another `false`,
  their timestamps are in different time bases. Make it consistent across all
  nodes (set `/use_sim_time` before any node starts; restart nodes after).
- **No `/clock` publisher** while `use_sim_time=true`: a bag (`rosbag play
  --clock`) or simulator must publish `/clock`, or nothing advances.
- **Genuinely different wall clocks:** rare with shared host kernel, but if
  containers use different time sources, align them; TF tolerances assume a
  common clock.

## Quick reference: env vars

- `ROS_MASTER_URI` — where the master is, e.g. `http://master:11311`. Every node
  container needs this.
- `ROS_IP` — the IP this node advertises. Use when you have a stable IP.
- `ROS_HOSTNAME` — the name this node advertises. Use with docker DNS on a
  user-defined network. If both are set, `ROS_IP` wins.
- `roswtf` — run it sourced; it flags many of the above automatically.
