#!/usr/bin/env bash
# Gazebo 테스트 시 로봇 AMCL 초기화 + start_session 전송
#
# 사용법:
#   ./scripts/gz_init_robots.sh          # 로봇 54, 18 모두
#   ./scripts/gz_init_robots.sh 54       # 로봇 54만
#   ./scripts/gz_init_robots.sh 18       # 로봇 18만

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPTS_DIR/_ros_env.sh"
export ROS_DOMAIN_ID=14

CMD_TIMEOUT=90    # /robot_X/cmd 대기 최대 시간(초) — shoppinkki_core 구독
AMCL_TIMEOUT=60  # /robot_X/initialpose 대기 최대 시간(초) — Nav2 AMCL

if [ $# -eq 0 ]; then
    TARGETS="54 18"
else
    TARGETS="$*"
fi

# ── topic 대기 ────────────────────────────────────────────────────────────────
_wait_for_topic() {
    local TOPIC="$1"
    local TIMEOUT="$2"
    local ELAPSED=0
    printf "  %-42s 대기" "$TOPIC"
    while true; do
        if ros2 topic list 2>/dev/null | grep -qxF "$TOPIC"; then
            echo " ✓"
            return 0
        fi
        if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
            echo " ⏭  ${TIMEOUT}초 초과 (skip)"
            return 1
        fi
        printf "."
        sleep 2
        ELAPSED=$((ELAPSED + 2))
    done
}

# ── 1회 발행 (구독자 없으면 3초 후 포기) ─────────────────────────────────────
_pub_once() {
    local TOPIC="$1"
    local TYPE="$2"
    local PAYLOAD="$3"
    # timeout 명령이 없을 수 있으니 백그라운드 + 대기로 구현
    ros2 topic pub --times 1 "$TOPIC" "$TYPE" "$PAYLOAD" 2>/dev/null &
    local PID=$!
    local WAIT=0
    while kill -0 "$PID" 2>/dev/null; do
        sleep 1
        WAIT=$((WAIT + 1))
        if [ "$WAIT" -ge 5 ]; then
            kill "$PID" 2>/dev/null
            wait "$PID" 2>/dev/null
            break
        fi
    done
}

# ── 로봇 초기화 ────────────────────────────────────────────────────────────────
_init_robot() {
    local ID="$1"
    local X="$2"
    local Y="$3"
    local YAW_Z="$4"
    local YAW_W="$5"

    echo ""
    echo "━━ 로봇 ${ID} 초기화 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # [1] AMCL 초기 위치 (선택) — Nav2 가 준비됐을 때만
    echo "[1/2] AMCL 초기 위치 설정 시도 (x=${X}, y=${Y}, yaw=90°)"
    if _wait_for_topic "/robot_${ID}/initialpose" "$AMCL_TIMEOUT"; then
        _pub_once \
            "/robot_${ID}/initialpose" \
            "geometry_msgs/PoseWithCovarianceStamped" \
            "{header: {frame_id: map}, pose: {pose: {position: {x: ${X}, y: ${Y}, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: ${YAW_Z}, w: ${YAW_W}}}, covariance: [0.25,0,0,0,0,0,0,0.25,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.068]}}"
        echo "  ✓ AMCL 초기 위치 발행 완료"
        sleep 1
    else
        echo "  ⚠  AMCL 초기화 건너뜀 (Nav2 미준비 — 맵 위치는 이후에 갱신됨)"
    fi

    # [2] start_session — shoppinkki_core 필수
    echo "[2/2] start_session 전송 (CHARGING → IDLE)"
    if _wait_for_topic "/robot_${ID}/cmd" "$CMD_TIMEOUT"; then
        _pub_once \
            "/robot_${ID}/cmd" \
            "std_msgs/String" \
            "{data: \"{\\\"cmd\\\": \\\"start_session\\\", \\\"user_id\\\": \\\"gz_test\\\"}\"}"
        echo "  ✓ start_session 전송 완료"
    else
        echo "  ✗ /robot_${ID}/cmd 토픽 없음 — shoppinkki_core 가 실행 중인지 확인하세요"
        return 1
    fi

    echo "✓ 로봇 ${ID} 초기화 완료"
}

# ── 실행 ───────────────────────────────────────────────────────────────────────
for TARGET in $TARGETS; do
    case "$TARGET" in
        54) _init_robot 54  0.20  0.20  0.7071  0.7071 ;;
        18) _init_robot 18  0.50  0.20  0.7071  0.7071 ;;
        *)  echo "알 수 없는 로봇 ID: $TARGET  (54 또는 18 만 지원)" ;;
    esac
done

echo ""
echo "완료. admin_ui 에서 로봇이 IDLE 상태로 표시되어야 합니다."
echo "(AMCL 이 건너뛰어진 경우 맵 위치는 Nav2 초기화 후 자동 갱신됩니다)"
