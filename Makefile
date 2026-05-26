IMAGE_NAME = ros-noetic-zsh:latest
CONTAINER_NAME = ros-noetic-zsh
HOST_CLAUDE_DIR = $(HOME)/.claude

all: build run

build:
	docker build -t $(IMAGE_NAME) .

run:
	mkdir -p $(HOST_CLAUDE_DIR)
	docker run -it --rm \
		--privileged \
		--net=host \
		--name $(CONTAINER_NAME) \
		--ulimit nofile=1024:524288 \
		--mount type=bind,source=$(shell pwd)/catkin_ws,target=/root/catkin_ws \
		--mount type=bind,source=$(HOST_CLAUDE_DIR),target=/root/.claude \
		$(IMAGE_NAME) /bin/zsh

stop:
	-docker stop $(CONTAINER_NAME)
	-docker rm $(CONTAINER_NAME)

clean: stop
	-docker rmi $(IMAGE_NAME)

attach:
	-docker exec -it $(CONTAINER_NAME) /bin/zsh

logs:
	-docker logs -f $(CONTAINER_NAME)
