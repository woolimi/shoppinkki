#!/usr/bin/env bash
# Gazebo 멀티로봇 테스트 — 로봇 54, 18번 + admin_ui 통합
#
# 지원 환경: macOS+conda / Ubuntu+apt / Ubuntu+conda

set -e
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS_WS="$(dirname "$SCRIPTS_DIR")"
SESSION="shoppinkki_gz"

# ── 공통 환경 감지 ─────────────────────────────────────────────────────────────
source "$SCRIPTS_DIR/_ros_env.sh"
# → $TMUX_SRC, $CONDA_BIN, $ROS_SETUP_FILE 변수 설정됨

ROS_ENV="export ROS_DOMAIN_ID=14"

# ── 환경 확인 ──────────────────────────────────────────────────────────────────
if ! command -v tmux &>/dev/null; then
    echo "tmux 필요: brew install tmux  또는  sudo apt install tmux"
    exit 1
fi

# ── 기존 세션 정리 ─────────────────────────────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[gz_test] 기존 '$SESSION' 세션을 종료합니다..."
    tmux kill-session -t "$SESSION"
fi

echo "[gz_test] tmux 세션 '$SESSION' 생성 중..."
tmux set-option -g mouse on 2>/dev/null || true

# ── tmux 창 생성 ───────────────────────────────────────────────────────────────

# 창 0: Gazebo 멀티로봇 launch
tmux new-session -d -s "$SESSION" -n "gz"
tmux send-keys -t "${SESSION}:gz" \
  "$TMUX_SRC && $ROS_ENV && ros2 launch shoppinkki_nav gz_multi_robot.launch.py" Enter

# 창 1: shoppinkki_core 로봇 54
tmux new-window -t "${SESSION}" -n "core54"
tmux send-keys -t "${SESSION}:core54" \
  "$TMUX_SRC && $ROS_ENV && export ROBOT_ID=54 && cd $ROS_WS && ros2 run shoppinkki_core main_node" Enter

# 창 2: shoppinkki_core 로봇 18
tmux new-window -t "${SESSION}" -n "core18"
tmux send-keys -t "${SESSION}:core18" \
  "$TMUX_SRC && $ROS_ENV && export ROBOT_ID=18 && cd $ROS_WS && ros2 run shoppinkki_core main_node" Enter

# 창 3: control_service
tmux new-window -t "${SESSION}" -n "control"
tmux send-keys -t "${SESSION}:control" \
  "$TMUX_SRC && $ROS_ENV && ros2 run control_service main" Enter

# 창 4: admin_ui
tmux new-window -t "${SESSION}" -n "admin"
tmux send-keys -t "${SESSION}:admin" \
  "$TMUX_SRC && $ROS_ENV && ros2 run admin_ui admin_ui" Enter

# 창 5: 디버깅 셸
tmux new-window -t "${SESSION}" -n "shell"
tmux send-keys -t "${SESSION}:shell" \
  "$TMUX_SRC && $ROS_ENV && cd $ROS_WS" Enter

tmux select-window -t "${SESSION}:gz"

# ── 안내 ───────────────────────────────────────────────────────────────────────
echo ""
echo "┌────────────────────────────────────────────────────────────────┐"
echo "│          ShopPinkki 멀티로봇 Gazebo 테스트 기동               │"
echo "├────────────────────────────────────────────────────────────────┤"
echo "│  창 목록 (마우스 클릭 또는 Ctrl+b → 숫자):                    │"
echo "│  0. gz      — Gazebo + Nav2 x2 (로봇 54, 18)                 │"
echo "│  1. core54  — shoppinkki_core 로봇 54번                      │"
echo "│  2. core18  — shoppinkki_core 로봇 18번                      │"
echo "│  3. control — control_service (TCP:8080 / REST:8081)         │"
echo "│  4. admin   — admin_ui 관제 패널                             │"
echo "│  5. shell   — 디버깅 셸                                      │"
echo "├────────────────────────────────────────────────────────────────┤"
echo "│  테스트 순서:                                                  │"
echo "│  ① gz 창 Gazebo 로딩 완료 대기 (~40초)                      │"
echo "│  ② shell 창에서 AMCL 초기 위치 + start_session 전송          │"
echo "│     → $SCRIPTS_DIR/gz_init_robots.sh                         │"
echo "│  ③ admin_ui 맵 클릭 → [이동 명령] → Gazebo 로봇 이동        │"
echo "└────────────────────────────────────────────────────────────────┘"
echo ""

tmux attach-session -t "$SESSION"
