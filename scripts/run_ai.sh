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

echo "[ai_server] Docker 이미지 빌드 및 기동 중..."
echo "  YOLO  → TCP:5005"
echo "  LLM   → REST:8000"
cd "$AI_DIR"

# --build: 코드 변경 시 자동 재빌드
docker compose up --build "$@"
