#!/bin/bash
# xacro 실행 후 type="lidar" → type="gpu_lidar" 패치
# Gazebo Harmonic에서 type="lidar"는 sensors system에서 발행되지 않는 버그
xacro "$@" | sed 's/type="lidar"/type="gpu_lidar"/g'
