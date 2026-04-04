#!/usr/bin/env bash
# ShopPinkki — DB 시딩 스크립트 (Docker MySQL)
# 실행 위치: ros_ws 루트에서  ./scripts/seed.sh

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="shoppinkki_mysql"
DB="shoppinkki"
USER="shoppinkki"
PASS="shoppinkki"
SCHEMA="$ROOT/scripts/db/schema.sql"
SEED="$ROOT/scripts/db/seed_data.sql"

# ── MySQL 실행 헬퍼 ─────────────────────────────
run_sql() {
    docker exec -i "$CONTAINER" \
        mysql -u"$USER" -p"$PASS" "$DB" "$@"
}

# ── 컨테이너 상태 확인 ──────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "⚠️  MySQL 컨테이너가 실행 중이지 않습니다."
    echo "    다음 명령으로 먼저 시작하세요:"
    echo ""
    echo "    cd $ROOT && docker compose up -d mysql"
    echo ""
    exit 1
fi

echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│    ShopPinkki  DB  시딩                      │"
echo "├─────────────────────────────────────────────┤"
echo "│  1) reset   DB 초기화 후 재시딩              │"
echo "│             (스키마 변경 시 사용)             │"
echo "│  2) replace 기존 행 덮어쓰기                 │"
echo "│             (데이터 값 변경 시 사용)          │"
echo "│  3) (기본)  새 행만 추가                     │"
echo "└─────────────────────────────────────────────┘"
echo ""
read -r "choice?선택 [1/2/3]: "

case "$choice" in
    1)
        echo "[seed.sh] DB 초기화 후 재시딩 ..."
        # DROP 후 재생성
        docker exec -i "$CONTAINER" \
            mysql -u"$USER" -p"$PASS" \
            -e "DROP DATABASE IF EXISTS $DB; CREATE DATABASE $DB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        run_sql < "$SCHEMA"
        run_sql < "$SEED"
        echo "✅ 완료 (reset)"
        ;;
    2)
        echo "[seed.sh] 기존 행 덮어쓰기 ..."
        run_sql < "$SEED"
        echo "✅ 완료 (replace — ON DUPLICATE KEY UPDATE 적용)"
        ;;
    3|"")
        echo "[seed.sh] 새 행만 추가 ..."
        run_sql < "$SEED"
        echo "✅ 완료"
        ;;
    *)
        echo "올바른 번호를 입력하세요 (1, 2, 3)."
        exit 1
        ;;
esac
