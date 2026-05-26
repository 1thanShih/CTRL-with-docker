IMAGE_NAME = ros-noetic-zsh:latest
CONTAINER_NAME = ros-noetic-zsh

# Named volumes — keep container state isolated from the host filesystem.
# Claude credentials and zsh history live here; the host's ~/.claude is never touched.
CLAUDE_VOLUME = ctrl-claude-home
ZSH_VOLUME    = ctrl-zsh-history

# `make` (default) → build (no-op if cached) + start detached + drop into a shell.
# Every shell goes through `docker exec`, so opening more terminals is just
# `make shell` again — closing one terminal never kills the container.
all: build shell

build:
	docker build -t $(IMAGE_NAME) .

# Start the container in the background (detached). Idempotent: does nothing
# if the container is already running. The container stays alive across
# host-terminal close/open until you `make stop` it.
up:
	@if [ -n "$$(docker ps -q -f name=^/$(CONTAINER_NAME)$$)" ]; then \
		echo "[up] $(CONTAINER_NAME) already running"; \
	else \
		if [ -n "$$(docker ps -aq -f name=^/$(CONTAINER_NAME)$$)" ]; then \
			docker rm -f $(CONTAINER_NAME) >/dev/null; \
		fi; \
		docker run -d -it \
			--privileged \
			--net=host \
			--name $(CONTAINER_NAME) \
			--ulimit nofile=1024:524288 \
			--mount type=bind,source=$(shell pwd)/catkin_ws,target=/root/catkin_ws \
			--mount type=volume,source=$(CLAUDE_VOLUME),target=/root/.claude \
			--mount type=volume,source=$(ZSH_VOLUME),target=/root/.zsh-cache \
			$(IMAGE_NAME) >/dev/null && \
		echo "[up] started $(CONTAINER_NAME) (detached). Use 'make shell' to attach."; \
	fi

# Drop into a zsh inside the running container. Safe to run from any number
# of host terminals concurrently — each call is a fresh `docker exec` process.
shell: up
	docker exec -it $(CONTAINER_NAME) /bin/zsh

# Backwards-compat alias.
attach: shell

# Legacy foreground mode: tie the container's lifetime to this terminal
# (--rm exits when the shell exits). Useful for one-off demos; for normal
# dev use `make` / `make shell` instead.
run:
	docker run -it --rm \
		--privileged \
		--net=host \
		--name $(CONTAINER_NAME) \
		--ulimit nofile=1024:524288 \
		--mount type=bind,source=$(shell pwd)/catkin_ws,target=/root/catkin_ws \
		--mount type=volume,source=$(CLAUDE_VOLUME),target=/root/.claude \
		--mount type=volume,source=$(ZSH_VOLUME),target=/root/.zsh-cache \
		$(IMAGE_NAME) /bin/zsh

# One-shot ephemeral container for `claude login`.
# Mounts only the Claude volume — no devices, no host network. Run once; the
# token persists in the volume and is reused by `make` / `make up`.
login:
	docker run -it --rm \
		--mount type=volume,source=$(CLAUDE_VOLUME),target=/root/.claude \
		$(IMAGE_NAME) claude login

stop:
	-docker stop $(CONTAINER_NAME)
	-docker rm $(CONTAINER_NAME)

clean: stop
	-docker rmi $(IMAGE_NAME)

# Nuke the persisted Claude + zsh-history volumes. Forces a re-login next run.
purge-volumes:
	-docker volume rm $(CLAUDE_VOLUME) $(ZSH_VOLUME)

logs:
	-docker logs -f $(CONTAINER_NAME)

# Show whether the container is up.
ps:
	@docker ps -a --filter name=^/$(CONTAINER_NAME)$$ --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

.PHONY: all build up shell attach run login stop clean purge-volumes logs ps
