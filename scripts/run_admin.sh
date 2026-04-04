#!/usr/bin/env bash
# admin_ui — PyQt6 관제 대시보드
#
# 지원 환경: macOS+conda / Ubuntu+apt / Ubuntu+conda

set -e
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

source "$SCRIPTS_DIR/_ros_env.sh"

export ROS_DOMAIN_ID=14

echo "[admin_ui] 관제 앱 기동 중..."
cd "$(dirname "$SCRIPTS_DIR")"
ros2 run admin_ui admin_ui
