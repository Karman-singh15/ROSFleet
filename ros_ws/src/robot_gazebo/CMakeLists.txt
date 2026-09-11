cmake_minimum_required(VERSION 3.0.2)
project(robot_gazebo)

find_package(catkin REQUIRED)

catkin_package()

install(DIRECTORY worlds models launch config
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
  OPTIONAL
)
