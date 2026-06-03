#!/bin/zsh

# Start the SSH daemon if it's actually installed (Dockerfile doesn't install
# openssh-server by default — guard so we don't spew "command not found").
if command -v sshd >/dev/null 2>&1; then
    /usr/sbin/sshd
fi

# Always source the base ROS env so $@ has a working environment.
source /opt/ros/noetic/setup.zsh

# Compile the project — only when catkin_ws is actually bind-mounted in.
# `make login` mounts only the Claude volume, so /root/catkin_ws is empty there;
# skip catkin_make / devel sourcing instead of failing loudly.
if ls /root/catkin_ws/src/*/package.xml >/dev/null 2>&1; then
    catkin_make
    source /root/catkin_ws/devel/setup.zsh
    cd /root/catkin_ws
else
    echo "[entrypoint] /root/catkin_ws/src not mounted — skipping catkin_make."
fi

# Setup USB connection — only when a serial device is actually present and we
# have the privilege to touch udev. `make login` runs without --privileged / /dev,
# so this whole block is skipped there (avoids `service udev restart` hanging).
if [ -e /dev/ttyUSB0 ] || [ -e /dev/ttyACM0 ]; then
    echo "Remap the serial port(ttyUSBX, ttyACMX) to custom name"
    echo " "

    echo "Arduino usb connection as /dev/arduino"
    echo "Camera usb connection as /dev/camera"
    echo " "

    echo "Check these using the command : ls -l /dev|grep ttyUSB"
    echo "Check the detail of the connection, using the command: udevadm info --attribute-walk /dev/ttyUSBX"
    echo "(replace the /dev/ttyUSBX with your target device)"
    echo " "

    echo "Start copy rule files in scripts, to /etc/udev/rules.d/"
    cp /root/scripts/arduino.rules /etc/udev/rules.d
    cp /root/scripts/camera.rules /etc/udev/rules.d
    echo " "

    echo "Restarting udev"
    service udev restart
    udevadm control --reload-rules
    udevadm trigger
    echo " "

    echo "Finish usb port setup"
    echo " "
else
    echo "[entrypoint] no /dev/ttyUSB0 or /dev/ttyACM0 — skipping udev remap."
fi

exec "$@"
