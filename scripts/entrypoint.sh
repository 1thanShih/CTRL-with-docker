#!/bin/zsh

# Start the SSH daemon in the background
/usr/sbin/sshd

# Compile the project
source /opt/ros/noetic/setup.zsh
catkin_make
source /root/catkin_ws/devel/setup.zsh
cd /root/catkin_ws

# Setup USB connection
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

exec "$@"
