#!/usr/bin/env bash
# 쑈삥끼 서버 스택 — 노트북/서버 PC 실행
#
# 포함: control_service (ROS2 + TCP:8080 + REST:8081) + AI 서버 (Docker)
# 제외: UI (admin_ui, customer_web) → run_ui.sh 별도 실행
#
# 사용법:
#   ./scripts/run_server.sh          # control_service + AI 서버
#   ./scripts/run_server.sh --no-ai  # AI 서버 제외

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS_WS="$(dirname "$SCRIPTS_DIR")"
SESSION="sp_server"
NO_AI=false

for arg in "$@"; do
    [ "$arg" = "--no-ai" ] && NO_AI=true
done

source "$SCRIPTS_DIR/_ros_env.sh"

ROS_ENV="export ROS_DOMAIN_ID=14"

# ── tmux 없을 때 안내 ──────────────────────────────────────────────────────────
if ! command -v tmux &>/dev/null; then
    echo ""
    echo "tmux 가 없습니다. 아래 명령어를 터미널 각각에서 실행하세요."
    echo ""
    echo "  [1] control_service : $TMUX_SRC && $ROS_ENV && cd $ROS_WS && env python3 $ROS_WS/install/control_service/lib/control_service/main"
    [ "$NO_AI" = false ] && \
    echo "  [2] AI 서버         : bash $SCRIPTS_DIR/run_ai.sh"
    echo ""
    exit 0
fi

# ── 기존 세션 정리 ─────────────────────────────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[run_server] 기존 '$SESSION' 세션 종료..."
    tmux kill-session -t "$SESSION"
fi

echo "[run_server] tmux 세션 '$SESSION' 생성 중..."
tmux set-option -g mouse on 2>/dev/null || true

# ── 창 생성 ────────────────────────────────────────────────────────────────────

# 창 0: control_service
tmux new-session -d -s "$SESSION" -n "control"
# ros2 run 은 POSIX 에서 스크립트 shebang(보통 /usr/bin/python3)을 쓰므로 conda pip 가 무시됨.
# PATH 앞선 conda python 으로 동일 엔트리 스크립트를 실행한다.
tmux send-keys -t "${SESSION}:control" \
    "$TMUX_SRC && $ROS_ENV && cd $ROS_WS && env python3 $ROS_WS/install/control_service/lib/control_service/main" Enter

# 창 1: AI 서버
if [ "$NO_AI" = false ]; then
    tmux new-window -t "${SESSION}" -n "ai"
    tmux send-keys -t "${SESSION}:ai" \
        "bash $SCRIPTS_DIR/run_ai.sh" Enter
fi

tmux select-window -t "${SESSION}:control"

# ── 안내 ───────────────────────────────────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────┐"
echo "│         쑈삥끼 서버 스택 기동                       │"
echo "├─────────────────────────────────────────────────────┤"
echo "│  0. control  — control_service (TCP:8080/REST:8081) │"
if [ "$NO_AI" = false ]; then
echo "│  1. ai       — YOLO TCP:5005 / LLM REST:8000        │"
fi
echo "├─────────────────────────────────────────────────────┤"
echo "│  UI 실행 : bash scripts/run_ui.sh                   │"
echo "│  세션 종료: tmux kill-session -t $SESSION           │"
echo "└─────────────────────────────────────────────────────┘"
echo ""

tmux attach-session -t "$SESSION"
