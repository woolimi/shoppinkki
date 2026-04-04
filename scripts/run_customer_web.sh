#!/usr/bin/env bash
# customer_web — Flask + SocketIO 고객 웹앱 (포트 8501)
#
# 지원 환경: macOS+conda / Ubuntu+apt / Ubuntu+conda

set -e
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS_WS="$(dirname "$SCRIPTS_DIR")"
APP_DIR="$ROS_WS/services/customer_web"

source "$SCRIPTS_DIR/_ros_env.sh"

echo "[customer_web] 기동 중... (http://localhost:8501)"
cd "$APP_DIR"
ROBOT_ID=${ROBOT_ID:-54} python3 app.py
