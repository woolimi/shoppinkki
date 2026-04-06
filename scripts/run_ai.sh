#!/usr/bin/env bash
# ai_server — Docker Compose (YOLO TCP:5005 + LLM REST:8000)

set -e
ROS_WS="$(cd "$(dirname "$0")/.." && pwd)"
AI_DIR="$ROS_WS/services/ai_server"

# Docker 실행 여부 확인
if ! docker info > /dev/null 2>&1; then
    echo "[ai_server] ❌ Docker가 실행 중이지 않습니다. Docker Desktop을 먼저 실행하세요."
    exit 1
fi

YOLO_CONTAINER="shoppinkki_yolo"
LLM_CONTAINER="shoppinkki_llm"

yolo_running=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c "^${YOLO_CONTAINER}$" || true)
llm_running=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c "^${LLM_CONTAINER}$" || true)

if [ "$yolo_running" -eq 1 ] && [ "$llm_running" -eq 1 ]; then
    echo "[ai_server] YOLO, LLM 컨테이너 이미 실행중 — 스킵"
else
    echo "[ai_server] Docker 이미지 빌드 및 기동 중..."
    echo "  YOLO  → TCP:5005"
    echo "  LLM   → REST:8000"
    cd "$AI_DIR"
    docker compose up --build -d
fi

# 로그 출력
echo "[ai_server] 로그 출력 중... (Ctrl+C로 종료)"
cd "$AI_DIR"
docker compose logs -f
