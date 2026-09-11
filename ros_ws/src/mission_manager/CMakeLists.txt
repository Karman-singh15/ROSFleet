cmake_minimum_required(VERSION 3.0.2)
project(mission_manager)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  geometry_msgs
  actionlib
  actionlib_msgs
  move_base_msgs
  message_generation
)

catkin_python_setup()

add_message_files(
  FILES
  MissionStatus.msg
  MissionEvent.msg
)

add_service_files(
  FILES
  StartMission.srv
  CancelMission.srv
)

generate_messages(
  DEPENDENCIES
  std_msgs
  geometry_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs geometry_msgs actionlib move_base_msgs message_runtime
)

catkin_install_python(PROGRAMS
  scripts/mission_manager_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch config
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
  OPTIONAL
)
