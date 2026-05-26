cmake_minimum_required(VERSION 3.0.2)
project(dlv_bringup)

find_package(catkin REQUIRED COMPONENTS
  rospy
  roscpp
  sensor_msgs
  std_msgs
  message_generation
  controller_manager
  hardware_interface
  transmission_interface
)

# generate_messages(
#   DEPENDENCIES
#   std_msgs
# )

catkin_package(
  CATKIN_DEPENDS rospy std_srvs message_runtime
)

include_directories(
  ${catkin_INCLUDE_DIRS}
)