#!/usr/bin/env bash
# 쑈삥끼 UI — 노트북 실행
#
# 포함: admin_ui (PyQt6 관제) + customer_web (Flask 고객 웹앱)
#
# 사용법:
#   ./scripts/run_ui.sh
#
# 로봇 접속: http://localhost:8501/?robot_id=54  또는  ?robot_id=18

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS_WS="$(dirname "$SCRIPTS_DIR")"
SESSION="sp_ui"

source "$SCRIPTS_DIR/_ros_env.sh"

ROS_ENV="$TMUX_ROS_ENV"

# ── tmux 필수 ─────────────────────────────────────────────────────────────────
if ! command -v tmux &>/dev/null; then
    echo "tmux 필요: brew install tmux  또는  sudo apt install tmux"
    exit 1
fi

# ── 기존 세션 정리 ─────────────────────────────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[run_ui] 기존 '$SESSION' 세션 종료..."
    tmux kill-session -t "$SESSION"
fi

echo "[run_ui] tmux 세션 '$SESSION' 생성 중..."
tmux set-option -g mouse on 2>/dev/null || true

# ── 창 생성 ────────────────────────────────────────────────────────────────────

# 창 0: admin_ui (PyQt6 — GUI 앱)
# ros2 run 은 shebang 으로 시스템 python 을 쓰므로 conda 의 PyQt6 가 안 잡힘 → env python3
tmux new-session -d -s "$SESSION" -n "admin"
tmux send-keys -t "${SESSION}:admin" \
    "$TMUX_SRC && $ROS_ENV && cd $ROS_WS && env python3 $ROS_WS/install/admin_ui/lib/admin_ui/admin_ui" Enter

# 창 1: customer_web (Flask + SocketIO, 포트 8501)
tmux new-window -t "${SESSION}" -n "customer"
tmux send-keys -t "${SESSION}:customer" \
    "$TMUX_SRC && $ROS_ENV && cd $ROS_WS/services/customer_web && python3 app.py" Enter

tmux select-window -t "${SESSION}:admin"

# ── 안내 ───────────────────────────────────────────────────────────────────────
echo ""
echo "┌──────────────────────────────────────────────────────────┐"
echo "│         쑈삥끼 UI 기동                                   │"
echo "├──────────────────────────────────────────────────────────┤"
echo "│  0. admin    — 관제 앱 (PyQt6)                          │"
echo "│  1. customer — 고객 웹앱  http://localhost:8501          │"
echo "├──────────────────────────────────────────────────────────┤"
echo "│  로봇 접속: http://localhost:8501/?robot_id=54            │"
echo "├──────────────────────────────────────────────────────────┤"
echo "│  서버 실행 : bash scripts/run_server.sh                  │"
echo "│  세션 종료 : tmux kill-session -t $SESSION               │"
echo "└──────────────────────────────────────────────────────────┘"
echo ""

tmux attach-session -t "$SESSION"
