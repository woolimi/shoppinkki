#!/usr/bin/env bash
# 쑈삥끼 실물 로봇 — Pi 5 실행
#
# 포함: bringup (모터/IMU) + Navigation (Nav2+AMCL) + shoppinkki_core (SM+BT)
#
# 전체 개발 워크플로우 (실물):
#   [노트북] bash scripts/run_server.sh
#   [노트북] bash scripts/run_ui.sh
#   [Pi 5 ] bash scripts/run_robot.sh          ← 이 스크립트
#
# 환경 변수:
#   ROBOT_ID   로봇 번호 (기본 54, 인자로도 지정 가능)
#
# 사용법:
#   ./scripts/run_robot.sh        # ROBOT_ID=54
#   ./scripts/run_robot.sh 18     # ROBOT_ID=18

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS_WS="$(dirname "$SCRIPTS_DIR")"
ROBOT_ID="${1:-${ROBOT_ID:-54}}"
SESSION="sp_robot"

source "$SCRIPTS_DIR/_ros_env.sh"

ROS_ENV="$TMUX_ROS_ENV"

# ── 환경 확인 ──────────────────────────────────────────────────────────────────
if ! command -v tmux &>/dev/null; then
    echo "tmux 필요: sudo apt install tmux"
    exit 1
fi

# ── 기존 세션 정리 ─────────────────────────────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[run_robot] 기존 '$SESSION' 세션 종료..."
    tmux kill-session -t "$SESSION"
fi

echo "[run_robot] tmux 세션 '$SESSION' 생성 (ROBOT_ID=$ROBOT_ID)..."
tmux set-option -g mouse on 2>/dev/null || true

# ── 창 생성 ────────────────────────────────────────────────────────────────────

# 창 0: bringup (Dynamixel 모터 + odometry + TF)
tmux new-session -d -s "$SESSION" -n "bringup"
tmux send-keys -t "${SESSION}:bringup" \
    "$TMUX_SRC && $ROS_ENV && cd $ROS_WS && ros2 launch pinky_bringup bringup_robot.launch.xml" Enter

# 창 1: navigation (Nav2 + AMCL + slam_toolbox)
# bringup 안정화 대기 후 실행 (10초)
tmux new-window -t "${SESSION}" -n "nav"
tmux send-keys -t "${SESSION}:nav" \
    "$TMUX_SRC && $ROS_ENV && cd $ROS_WS && sleep 10 && ros2 launch shoppinkki_nav navigation.launch.py" Enter

# 창 2: shoppinkki_core (SM + BT + HW)
# Nav2 초기화 대기 후 실행 (30초)
tmux new-window -t "${SESSION}" -n "core"
tmux send-keys -t "${SESSION}:core" \
    "$TMUX_SRC && $ROS_ENV && export ROBOT_ID=$ROBOT_ID && sleep 30 && ros2 run shoppinkki_core main_node" Enter

# 창 3: 디버깅 셸
tmux new-window -t "${SESSION}" -n "shell"
tmux send-keys -t "${SESSION}:shell" \
    "$TMUX_SRC && $ROS_ENV && cd $ROS_WS" Enter

tmux select-window -t "${SESSION}:bringup"

# ── 안내 ───────────────────────────────────────────────────────────────────────
echo ""
echo "┌──────────────────────────────────────────────────────────────┐"
echo "│         쑈삥끼 실물 로봇 기동 (ROBOT_ID=$ROBOT_ID)            │"
echo "├──────────────────────────────────────────────────────────────┤"
echo "│  0. bringup — 모터/IMU/TF (즉시 시작)                       │"
echo "│  1. nav     — Nav2 + AMCL (10초 후 자동 시작)               │"
echo "│  2. core    — shoppinkki_core SM+BT (30초 후 자동 시작)      │"
echo "│  3. shell   — 디버깅 셸                                      │"
echo "├──────────────────────────────────────────────────────────────┤"
echo "│  노트북에서 실행:                                             │"
echo "│    bash scripts/run_server.sh                                │"
echo "│    bash scripts/run_ui.sh                                    │"
echo "├──────────────────────────────────────────────────────────────┤"
echo "│  세션 종료: tmux kill-session -t $SESSION                    │"
echo "└──────────────────────────────────────────────────────────────┘"
echo ""

tmux attach-session -t "$SESSION"
