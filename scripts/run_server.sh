#!/usr/bin/env bash
# 쑈삥끼 서버 PC 통합 실행기
#
# 지원 환경: macOS+conda / Ubuntu+apt / Ubuntu+conda
#
# 사용법:
#   ./scripts/run_server.sh          # 전체 실행
#   ./scripts/run_server.sh --no-ai  # AI 서버 제외

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION="shoppinkki"
NO_AI=false

for arg in "$@"; do
    [ "$arg" = "--no-ai" ] && NO_AI=true
done

# ── 공통 환경 감지 ─────────────────────────────────────────────────────────────
source "$SCRIPTS_DIR/_ros_env.sh"

ROS_ENV="export ROS_DOMAIN_ID=14"
ROS_WS="$(dirname "$SCRIPTS_DIR")"

# ── tmux 없을 때 안내 ──────────────────────────────────────────────────────────
if ! command -v tmux &>/dev/null; then
    echo ""
    echo "┌──────────────────────────────────────────────────────┐"
    echo "│  tmux 가 없어 통합 실행을 할 수 없습니다.            │"
    echo "│  터미널을 여러 개 열고 아래 명령어를 각각 실행하세요. │"
    echo "└──────────────────────────────────────────────────────┘"
    echo ""
    echo "  [1] 관제 앱    :  $SCRIPTS_DIR/run_admin.sh"
    echo "  [2] 고객 웹앱  :  $SCRIPTS_DIR/run_customer_web.sh"
    [ "$NO_AI" = false ] && echo "  [3] AI 서버    :  $SCRIPTS_DIR/run_ai.sh"
    echo ""
    echo "  tmux 설치: macOS → brew install tmux / Ubuntu → sudo apt install tmux"
    echo ""
    exit 0
fi

# ── 기존 세션 정리 ─────────────────────────────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[run_server] 기존 '$SESSION' 세션을 종료합니다..."
    tmux kill-session -t "$SESSION"
fi

echo "[run_server] tmux 세션 '$SESSION' 생성 중..."
tmux set-option -g mouse on 2>/dev/null || true

# ── 창 생성 ────────────────────────────────────────────────────────────────────

# 창 0: control_service
tmux new-session -d -s "$SESSION" -n "control"
tmux send-keys -t "${SESSION}:control" \
  "$TMUX_SRC && $ROS_ENV && ros2 run control_service main" Enter

# 창 1: admin_ui
tmux new-window -t "${SESSION}" -n "admin"
tmux send-keys -t "${SESSION}:admin" \
  "bash $SCRIPTS_DIR/run_admin.sh" Enter

# 창 2: customer_web
tmux new-window -t "${SESSION}" -n "customer_web"
tmux send-keys -t "${SESSION}:customer_web" \
  "bash $SCRIPTS_DIR/run_customer_web.sh" Enter

# 창 3: AI 서버 (--no-ai 옵션 없을 때만)
if [ "$NO_AI" = false ]; then
    tmux new-window -t "${SESSION}" -n "ai_server"
    tmux send-keys -t "${SESSION}:ai_server" \
      "bash $SCRIPTS_DIR/run_ai.sh" Enter
fi

# 창 4: 디버깅 셸
tmux new-window -t "${SESSION}" -n "shell"
tmux send-keys -t "${SESSION}:shell" \
  "$TMUX_SRC && $ROS_ENV && cd $ROS_WS" Enter

tmux select-window -t "${SESSION}:admin"

# ── 안내 ───────────────────────────────────────────────────────────────────────
echo ""
echo "┌──────────────────────────────────────────────────────┐"
echo "│         쑈삥끼 서버 스택 기동 완료                   │"
echo "├──────────────────────────────────────────────────────┤"
echo "│  0. control    — control_service                     │"
echo "│  1. admin      — 관제 앱                             │"
echo "│  2. customer_web — 고객 웹앱 http://localhost:8501   │"
[ "$NO_AI" = false ] && \
echo "│  3. ai_server  — YOLO TCP:5005 / LLM REST:8000      │"
echo "│  $([ "$NO_AI" = false ] && echo 4 || echo 3). shell       — 디버깅 셸                          │"
echo "├──────────────────────────────────────────────────────┤"
echo "│  마우스 클릭 또는 Ctrl+b → 숫자로 창 전환            │"
echo "│  세션 종료: tmux kill-session -t $SESSION            │"
echo "└──────────────────────────────────────────────────────┘"
echo ""

tmux attach-session -t "$SESSION"
