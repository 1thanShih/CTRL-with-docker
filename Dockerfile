FROM ros:noetic-perception

# 指定終端機顏色與設定 apt-get 為非互動模式
ENV TERM=xterm-256color
ENV DEBIAN_FRONTEND=noninteractive

# zsh history 落在 named volume 內 (/root/.zsh-cache)，與 host 完全隔離
ENV HISTFILE=/root/.zsh-cache/.zsh_history

# Pin Node.js major version (LTS)
ARG NODE_MAJOR=20

# 0. 解決 ROS GPG Key 過期問題 (先移除舊源 -> 更新 Ubuntu -> 裝 curl -> 抓新 Key -> 重新加入 ROS 源)
RUN rm -f /etc/apt/sources.list.d/ros*.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates && \
    curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros/ubuntu focal main" | tee /etc/apt/sources.list.d/ros1.list > /dev/null

# 1. 集中安裝系統依賴、ROS 套件，並在同一層清理 apt 快取以大幅縮減 Image 大小
# (cv_bridge / image_transport 等已內含於 ros:noetic-perception 基底，不再重複安裝)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      zsh \
      tmux \
      python3-pip \
      python3-numpy \
      ros-noetic-rosserial \
      ros-noetic-rosserial-arduino \
      ros-noetic-rosserial-python \
      && rm -rf /var/lib/apt/lists/*

# 2. Python deps (headless OpenCV — no X libs)
RUN pip3 install --no-cache-dir \
      opencv-python-headless \
      scikit-fuzzy \
      filterpy

# 3a. Node.js LTS (cache 友善：與 Claude Code 拆層，升級 CLI 不會重裝 Node)
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# 3b. Claude Code CLI (獨立一層；升 npm 套件版本時只重跑這層)
RUN npm install -g @anthropic-ai/claude-code && \
    npm cache clean --force

# 4. 安裝與設定 Zsh, Oh My Zsh 及相關外掛
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended && \
    git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k && \
    git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions && \
    git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting.git ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting && \
    chsh -s $(which zsh)

WORKDIR /root/catkin_ws

# 一次複製所有 dotfiles / cache / scripts (合層減少 image layer 數)
COPY dotfiles/.p10k.zsh /root/.p10k.zsh
COPY dotfiles/.zshrc /root/.zshrc
COPY cachefile/gitstatus /root/.cache/gitstatus
COPY scripts/*.rules /root/scripts/
COPY scripts/entrypoint.sh /root/scripts/entrypoint.sh
RUN chmod +x /root/scripts/entrypoint.sh

# Entry point
ENTRYPOINT ["/root/scripts/entrypoint.sh"]
CMD ["zsh"]
