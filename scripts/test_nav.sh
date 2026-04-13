#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Nav2 / RMF 테스트 도구 (GUIDING / RETURNING / 파라미터 조정)
# 사용법:  bash scripts/test_nav.sh [로봇번호]   (기본: 54)
# ─────────────────────────────────────────────────────────────
set -eo pipefail

# ── ROS 환경 ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_ros_env.sh"

ROBOT_ID="${1:-54}"
API="http://localhost:8081"
NS="robot_${ROBOT_ID}"
RVIZ_PID=""

# ── 구역 목록 (번호, x, y, theta, 이름, RMF waypoint) ────────
ZONES=(
  "1   0.619  -0.12   0.0     가전제품    가전제품1"
  "2   0.950  -0.12   0.0     과자        과자1"
  "3   1.05   -0.300  3.1416  해산물      해산물2"
  "4   1.05   -0.752  3.1416  육류        육류1"
  "5   1.05   -1.224  3.1416  채소        채소1"
  "6   0.76   -0.899  0.0     음료        음료1"
  "7   0.42   -0.300  0.0     베이커리    빵1"
  "8   0.42   -0.606  0.0     음식        가공식품2"
)

# 로봇별 충전소 waypoint
declare -A CHARGER_WP
CHARGER_WP[54]="P2"
CHARGER_WP[18]="P1"

# ── 색상 ──────────────────────────────────────────────────────
R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; C='\033[0;36m'; NC='\033[0m'

hr() { echo -e "${C}──────────────────────────────────────────${NC}"; }

# ── REST 명령 전송 ────────────────────────────────────────────
send_cmd() {
  curl -s -X POST "${API}/robot/${ROBOT_ID}/cmd" \
    -H "Content-Type: application/json" \
    -d "$1"
  echo
}

# ── RMF task 전송 ────────────────────────────────────────────
rmf_dispatch_waypoint() {
  local robot_name="pinky_${ROBOT_ID}"
  local waypoint="$1"
  echo -e "${G}>> RMF task: ${robot_name} → ${waypoint}${NC}"
  python3 "${SCRIPT_DIR}/rmf_dispatch.py" --robot "$robot_name" --waypoint "$waypoint"
}

rmf_dispatch_zone() {
  local robot_name="pinky_${ROBOT_ID}"
  local zone="$1"
  echo -e "${G}>> RMF task: ${robot_name} → 구역 [${zone}] (빈 자리 자동)${NC}"
  python3 "${SCRIPT_DIR}/rmf_dispatch.py" --robot "$robot_name" --zone "$zone"
}

# ── 파라미터 조회/설정 ────────────────────────────────────────
get_param() {
  ros2 param get "$1" "$2" 2>/dev/null || echo "(조회 실패)"
}

set_param_val() {
  ros2 param set "$1" "$2" "$3" 2>/dev/null
}

# ── 기능 함수 ─────────────────────────────────────────────────

show_zones() {
  hr
  printf "  ${Y}%-4s %-8s %-8s %-8s %-10s %s${NC}\n" "번호" "X" "Y" "Theta" "구역명" "RMF WP"
  hr
  for z in "${ZONES[@]}"; do
    read -r zid zx zy ztheta zname zwp <<< "$z"
    printf "  %-4s %-8s %-8s %-8s %-10s %s\n" "$zid" "$zx" "$zy" "$ztheta" "$zname" "$zwp"
  done
  hr
}

# ── RMF 기반 이동 ────────────────────────────────────────────
do_navigate_rmf() {
  show_zones
  read -rp "구역 번호 (1-8): " zid
  for z in "${ZONES[@]}"; do
    read -r id zx zy ztheta zname zwp <<< "$z"
    if [[ "$id" == "$zid" ]]; then
      echo -e "${G}>> [RMF] 안내이동 → ${zname} (빈 자리 자동 선택)${NC}"
      rmf_dispatch_zone "$zname"
      return
    fi
  done
  echo -e "${R}잘못된 구역 번호${NC}"
}

do_return_rmf() {
  local wp="${CHARGER_WP[$ROBOT_ID]:-P2}"
  echo -e "${G}>> [RMF] 충전소 복귀 → ${wp}${NC}"
  rmf_dispatch_waypoint "$wp"
}

# ── Nav2 직접 이동 (기존) ────────────────────────────────────
do_navigate_nav2() {
  show_zones
  read -rp "구역 번호 (1-8): " zid
  for z in "${ZONES[@]}"; do
    read -r id zx zy ztheta zname zwp <<< "$z"
    if [[ "$id" == "$zid" ]]; then
      echo -e "${G}>> [Nav2] 안내이동(GUIDING) → ${zname} (${zx}, ${zy})${NC}"
      send_cmd "{\"cmd\":\"navigate_to\",\"zone_id\":${zid},\"x\":${zx},\"y\":${zy},\"theta\":${ztheta}}"
      return
    fi
  done
  echo -e "${R}잘못된 구역 번호${NC}"
}

do_navigate_custom() {
  read -rp "X 좌표: " cx
  read -rp "Y 좌표: " cy
  read -rp "각도 Theta (기본 0.0): " ctheta
  ctheta="${ctheta:-0.0}"
  echo -e "${G}>> [Nav2] 안내이동(GUIDING) → (${cx}, ${cy}, ${ctheta})${NC}"
  send_cmd "{\"cmd\":\"navigate_to\",\"zone_id\":0,\"x\":${cx},\"y\":${cy},\"theta\":${ctheta}}"
}

do_return_nav2() {
  echo -e "${G}>> [Nav2] 충전소 복귀(RETURNING)${NC}"
  send_cmd '{"cmd":"return_to_charger"}'
}

do_admin_goto() {
  read -rp "X 좌표: " gx
  read -rp "Y 좌표: " gy
  read -rp "각도 Theta (기본 0.0): " gtheta
  gtheta="${gtheta:-0.0}"
  echo -e "${G}>> 관리자 이동 (${gx}, ${gy}, ${gtheta})${NC}"
  send_cmd "{\"cmd\":\"admin_goto\",\"x\":${gx},\"y\":${gy},\"theta\":${gtheta}}"
}

show_params() {
  hr
  echo -e "  ${Y}로봇: ${NS}${NC}"
  hr
  echo -n "  로컬 costmap  inflation_radius : "
  get_param "/${NS}/local_costmap/local_costmap" "inflation_layer.inflation_radius"
  echo -n "  글로벌 costmap inflation_radius : "
  get_param "/${NS}/global_costmap/global_costmap" "inflation_layer.inflation_radius"
  echo -n "  로컬 costmap  footprint_padding : "
  get_param "/${NS}/local_costmap/local_costmap" "footprint_padding"
  echo -n "  글로벌 costmap footprint_padding : "
  get_param "/${NS}/global_costmap/global_costmap" "footprint_padding"
  echo -n "  충돌 감지 (collision_detection)  : "
  get_param "/${NS}/controller_server" "FollowPath.use_collision_detection"
  echo -n "  목표 도달 허용오차 (xy_tolerance): "
  get_param "/${NS}/controller_server" "general_goal_checker.xy_goal_tolerance"
  echo -n "  전방 탐색 거리 (lookahead_dist)  : "
  get_param "/${NS}/controller_server" "FollowPath.lookahead_dist"
  echo -n "  목표 선속도 (desired_linear_vel) : "
  get_param "/${NS}/controller_server" "FollowPath.desired_linear_vel"
  echo -n "  cost_scaling_factor (로컬)       : "
  get_param "/${NS}/local_costmap/local_costmap" "inflation_layer.cost_scaling_factor"
  hr
}

do_set_inflation() {
  read -rp "inflation_radius 값: " val
  set_param_val "/${NS}/local_costmap/local_costmap" "inflation_layer.inflation_radius" "$val"
  set_param_val "/${NS}/global_costmap/global_costmap" "inflation_layer.inflation_radius" "$val"
  echo -e "${G}>> inflation_radius → ${val}${NC}"
}

do_set_collision() {
  read -rp "충돌 감지 (true/false): " val
  set_param_val "/${NS}/controller_server" "FollowPath.use_collision_detection" "$val"
  echo -e "${G}>> use_collision_detection → ${val}${NC}"
}

do_set_footprint_padding() {
  read -rp "footprint_padding 값: " val
  set_param_val "/${NS}/local_costmap/local_costmap" "footprint_padding" "$val"
  set_param_val "/${NS}/global_costmap/global_costmap" "footprint_padding" "$val"
  echo -e "${G}>> footprint_padding → ${val}${NC}"
}

do_set_cost_scaling() {
  read -rp "cost_scaling_factor 값: " val
  set_param_val "/${NS}/local_costmap/local_costmap" "inflation_layer.cost_scaling_factor" "$val"
  set_param_val "/${NS}/global_costmap/global_costmap" "inflation_layer.cost_scaling_factor" "$val"
  echo -e "${G}>> cost_scaling_factor → ${val}${NC}"
}

do_set_custom_param() {
  echo -e "  ${Y}예: /${NS}/controller_server FollowPath.desired_linear_vel 0.15${NC}"
  read -rp "노드 이름: " node
  read -rp "파라미터 이름: " param
  read -rp "값: " val
  set_param_val "$node" "$param" "$val"
  echo -e "${G}>> ${node} ${param} → ${val}${NC}"
}

show_status() {
  hr
  echo -e "  ${Y}로봇 ${ROBOT_ID} 상태${NC}"
  hr
  curl -s "${API}/robot/${ROBOT_ID}/status" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  (응답 없음)"
  hr
}

show_log() {
  local win=$((ROBOT_ID == 54 ? 1 : 2))
  tmux capture-pane -t "sp_sim:${win}" -p 2>/dev/null | tail -25
}

do_rviz() {
  if [[ -n "$RVIZ_PID" ]] && kill -0 "$RVIZ_PID" 2>/dev/null; then
    echo -e "${Y}RViz 이미 실행 중 (PID=${RVIZ_PID})${NC}"
    return
  fi
  local rviz_config="${SCRIPT_DIR}/../device/shoppinkki/shoppinkki_nav/rviz/multi_robot_view.rviz"
  if [[ -f "$rviz_config" ]]; then
    echo -e "${G}>> RViz2 실행 중 (multi_robot_view)...${NC}"
    rviz2 -d "$rviz_config" &>/dev/null &
    RVIZ_PID=$!
  else
    echo -e "${G}>> RViz2 실행 중 (설정 파일 없음)...${NC}"
    rviz2 &>/dev/null &
    RVIZ_PID=$!
  fi
  echo -e "${G}>> RViz2 PID=${RVIZ_PID}${NC}"
}

cleanup() {
  if [[ -n "$RVIZ_PID" ]] && kill -0 "$RVIZ_PID" 2>/dev/null; then
    kill "$RVIZ_PID" 2>/dev/null
  fi
}
trap cleanup EXIT

# ── 메인 메뉴 ─────────────────────────────────────────────────

main() {
  clear
  echo -e "${C}"
  echo "  ╔══════════════════════════════════════╗"
  echo "  ║   쑈삥끼 Nav2/RMF 테스트 도구        ║"
  echo "  ║   로봇: ${ROBOT_ID}  |  도메인: ${ROS_DOMAIN_ID:-0}            ║"
  echo "  ╚══════════════════════════════════════╝"
  echo -e "${NC}"

  while true; do
    hr
    echo -e "  ${Y}[ RMF 기반 이동 — 교통 스케줄 충돌 회피 ]${NC}"
    echo "    1) 구역으로 안내이동 (RMF)"
    echo "    2) 충전소 복귀 (RMF)"
    echo
    echo -e "  ${Y}[ Nav2 직접 이동 — RMF 없이 ]${NC}"
    echo "    3) 구역으로 안내이동 (Nav2)"
    echo "    4) 좌표 직접 입력 이동 (Nav2)"
    echo "    5) 충전소 복귀 (Nav2)"
    echo "    6) 관리자 이동 (IDLE 전용)"
    echo
    echo -e "  ${Y}[ 파라미터 ]${NC}"
    echo "    7) 현재 파라미터 확인"
    echo "    8) inflation_radius 변경"
    echo "    9) 충돌 감지 ON/OFF"
    echo "    f) footprint_padding 변경"
    echo "    c) cost_scaling_factor 변경"
    echo "    p) 기타 파라미터 직접 변경"
    echo
    echo -e "  ${Y}[ 상태 제어 ]${NC}"
    echo "    i) IDLE 모드로 전환 (다음 명령 대기)"
    echo "    a) 전체 로봇 IDLE 전환 (54+18)"
    echo
    echo -e "  ${Y}[ 모니터 ]${NC}"
    echo "    s) 로봇 상태 확인"
    echo "    l) 최근 로그 보기"
    echo "    v) RViz2 열기"
    echo
    echo "    r) 로봇 전환 (54/18)"
    echo "    q) 종료"
    hr
    read -rp "  > " choice

    case "$choice" in
      1) do_navigate_rmf ;;
      2) do_return_rmf ;;
      3) do_navigate_nav2 ;;
      4) do_navigate_custom ;;
      5) do_return_nav2 ;;
      6) do_admin_goto ;;
      7) show_params ;;
      8) do_set_inflation ;;
      9) do_set_collision ;;
      f) do_set_footprint_padding ;;
      c) do_set_cost_scaling ;;
      p) do_set_custom_param ;;
      i) echo -e "${G}>> 로봇 ${ROBOT_ID} IDLE 전환${NC}"; send_cmd '{"cmd":"force_idle"}' ;;
      a)
        echo -e "${G}>> 전체 로봇 IDLE 전환${NC}"
        curl -s -X POST "${API}/robot/54/cmd" -H "Content-Type: application/json" -d '{"cmd":"force_idle"}'; echo
        curl -s -X POST "${API}/robot/18/cmd" -H "Content-Type: application/json" -d '{"cmd":"force_idle"}'; echo
        ;;
      s) show_status ;;
      l) show_log ;;
      v) do_rviz ;;
      r)
        read -rp "  로봇 번호 (54/18): " ROBOT_ID
        NS="robot_${ROBOT_ID}"
        echo -e "${G}>> 로봇 ${ROBOT_ID}번으로 전환${NC}"
        ;;
      q) echo "종료합니다"; exit 0 ;;
      *) echo -e "${R}잘못된 입력${NC}" ;;
    esac
  done
}

main
