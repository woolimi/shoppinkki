#!/usr/bin/env bash
# 쑈삥끼 시뮬레이션 — 노트북 실행 (Gazebo + shoppinkki_core)
#
# 포함: Gazebo + Nav2 x2 + shoppinkki_core (로봇 54, 18)
# 제외: control_service, admin_ui, customer_web → run_server.sh / run_ui.sh 별도 실행
#
# 전체 개발 워크플로우 (시뮬):
#   터미널 A: bash scripts/run_server.sh
#   터미널 B: bash scripts/run_ui.sh
#   터미널 C: bash scripts/run_sim.sh          ← 이 스크립트
#
# 사용법:
#   ./scripts/run_sim.sh

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS_WS="$(dirname "$SCRIPTS_DIR")"
SESSION="sp_sim"

source "$SCRIPTS_DIR/_ros_env.sh"

ROS_ENV="$TMUX_ROS_ENV"

# ── 환경 확인 ──────────────────────────────────────────────────────────────────
if ! command -v tmux &>/dev/null; then
    echo "tmux 필요: brew install tmux  또는  sudo apt install tmux"
    exit 1
fi

# ── 기존 세션 정리 ─────────────────────────────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[run_sim] 기존 '$SESSION' 세션 종료..."
    tmux kill-session -t "$SESSION"
fi

echo "[run_sim] tmux 세션 '$SESSION' 생성 중..."
tmux set-option -g mouse on 2>/dev/null || true

# ── 창 생성 ────────────────────────────────────────────────────────────────────

# 창 0: Gazebo + Nav2 x2
tmux new-session -d -s "$SESSION" -n "gz"
tmux send-keys -t "${SESSION}:gz" \
    "$TMUX_SRC && $ROS_ENV && cd $ROS_WS && ros2 launch shoppinkki_nav gz_multi_robot.launch.py" Enter

# 창 1–2: shoppinkki_core (ros2 run 은 shebang 시스템 python → conda pip 무시; env python3)
_SHOP_CORE_MAIN="$ROS_WS/install/shoppinkki_core/lib/shoppinkki_core/main_node"

# 창 1: shoppinkki_core 로봇 54
tmux new-window -t "${SESSION}" -n "core54"
tmux send-keys -t "${SESSION}:core54" \
    "$TMUX_SRC && $ROS_ENV && ROBOT_ID=54 env python3 $_SHOP_CORE_MAIN --ros-args -p use_sim_time:=true" Enter

# 창 2: shoppinkki_core 로봇 18
tmux new-window -t "${SESSION}" -n "core18"
tmux send-keys -t "${SESSION}:core18" \
    "$TMUX_SRC && $ROS_ENV && ROBOT_ID=18 env python3 $_SHOP_CORE_MAIN --ros-args -p use_sim_time:=true" Enter

tmux select-window -t "${SESSION}:gz"

# ── 안내 ───────────────────────────────────────────────────────────────────────
echo ""
echo "┌──────────────────────────────────────────────────────────────┐"
echo "│         쑈삥끼 시뮬레이션 기동                               │"
echo "├──────────────────────────────────────────────────────────────┤"
echo "│  0. gz      — Gazebo + Nav2 (로봇 54, 18)                   │"
echo "│  1. core54  — shoppinkki_core 로봇 54                       │"
echo "│  2. core18  — shoppinkki_core 로봇 18                       │"
echo "├──────────────────────────────────────────────────────────────┤"
echo "├──────────────────────────────────────────────────────────────┤"
echo "│  실행 순서:                                                   │"
echo "│  ① gz 창 — Gazebo 로딩 대기 (~60초)                         │"
echo "│  ② admin_ui — 각 로봇 [위치 초기화] 버튼 클릭               │"
echo "│  ③ customer_web (?robot_id=54/18) 로그인 → IDLE 전환        │"
echo "│  ④ [시뮬레이션 모드] 버튼으로 추종 없이 쇼핑 테스트          │"
echo "├──────────────────────────────────────────────────────────────┤"
echo "│  서버: bash scripts/run_server.sh                            │"
echo "│  UI  : bash scripts/run_ui.sh                                │"
echo "│  세션 종료: tmux kill-session -t $SESSION                    │"
echo "└──────────────────────────────────────────────────────────────┘"
echo ""

tmux attach-session -t "$SESSION"
