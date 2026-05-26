# Quick Start

> First, make sure you have docker installed on your machine. If you don't have it, you can download it [here](https://www.docker.com/products/docker-desktop).

```bash
# Clone the repository
git clone <this-repo>

# Build the image, start the container in the background, and drop into a zsh
make

# The container keeps running in the background until you stop it explicitly:
make stop
```

## Open another terminal

The container runs detached, so you can attach as many shells as you want — every `make shell` is a fresh `docker exec`, and closing any one terminal does **not** kill the container.

```bash
# From any host terminal:
make shell        # (alias: make attach)
```

## Claude Code inside the container

Credentials live in a Docker named volume (`ctrl-claude-home`) — your host's `~/.claude` is **not** touched.

```bash
make login        # one-shot ephemeral container to run `claude login`
                  # token persists across `make stop` / `make` cycles
```

## Useful targets

```bash
make ps           # show container status
make logs         # follow container logs
make stop         # stop + remove container (image and volumes survive)
make clean        # stop + remove image
make purge-volumes  # nuke the Claude + zsh-history volumes (forces re-login)
make run          # LEGACY foreground --rm mode (container dies with this terminal)
```
