"""ShopPinkki LLM 자연어 상품 위치 검색 서버 (채널 D).

REST GET /query?name=<상품명>
→ {"zone_id": 3, "zone_name": "음료 코너"}

검색 전략 (우선순위):
  1) MySQL PRODUCT 테이블에서 product_name LIKE '%name%' → zone_id/zone_name 반환
  2) 정규화 키워드 매핑 (DB 연결 실패 시 fallback)
  3) 미매칭 → 404

환경 변수:
    MYSQL_HOST      기본 host.docker.internal
    MYSQL_PORT      기본 3306
    MYSQL_USER      기본 shoppinkki
    MYSQL_PASSWORD  기본 shoppinkki
    MYSQL_DATABASE  기본 shoppinkki
    HOST            바인드 호스트 (기본 0.0.0.0)
    PORT            바인드 포트 (기본 8000)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from flask import Flask, jsonify, request

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('llm_server')

# ── 환경 변수 ──────────────────────────────────────────────────────────────────
MYSQL_HOST = os.environ.get('MYSQL_HOST', 'host.docker.internal')
MYSQL_PORT = int(os.environ.get('MYSQL_PORT', '3306'))
MYSQL_USER = os.environ.get('MYSQL_USER', 'shoppinkki')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'shoppinkki')
MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE', 'shoppinkki')
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '8000'))

# ── fallback 키워드 맵 (DB 연결 불가 시) ──────────────────────────────────────
# zone_id → (zone_name, [키워드, ...])
# DB의 ZONE 테이블 기준 (product_type=1~8)
_KEYWORD_MAP: list[dict] = [
    {'zone_id': 1, 'zone_name': '과자 코너',   'keywords': ['과자', '스낵', '칩', 'cracker', 'snack', 'chip', '초코', '사탕', '젤리']},
    {'zone_id': 2, 'zone_name': '라면 코너',   'keywords': ['라면', '면', 'ramen', '국수', '우동', '소면', '파스타']},
    {'zone_id': 3, 'zone_name': '음료 코너',   'keywords': ['음료', '콜라', '사이다', '주스', '물', '커피', '차', '에너지', 'cola', 'juice', 'drink', '스파클링']},
    {'zone_id': 4, 'zone_name': '유제품 코너', 'keywords': ['우유', '요거트', '치즈', '버터', 'milk', 'yogurt', 'cheese', '두유', '아이스크림']},
    {'zone_id': 5, 'zone_name': '냉동식품 코너', 'keywords': ['냉동', '얼린', 'frozen', '피자', '만두', '핫도그', '너겟']},
    {'zone_id': 6, 'zone_name': '통조림 코너', 'keywords': ['통조림', '캔', 'can', '참치', '스팸', '햄', '콩', '옥수수']},
    {'zone_id': 7, 'zone_name': '생활용품 코너', 'keywords': ['샴푸', '비누', '세제', '화장지', '휴지', '칫솔', '치약', '샤워']},
    {'zone_id': 8, 'zone_name': '빵 코너',    'keywords': ['빵', '식빵', 'bread', '토스트', '베이글', '크로와상', '케이크', '도넛']},
]


def _normalize(text: str) -> str:
    """검색어 정규화: 소문자, 공백 제거, 특수문자 제거."""
    return re.sub(r'\s+', '', text.strip().lower())


def search_db(name: str) -> Optional[dict]:
    """MySQL PRODUCT·ZONE 테이블에서 상품명 검색."""
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            connection_timeout=3,
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT z.zone_id, z.zone_name
            FROM PRODUCT p
            JOIN ZONE z ON p.zone_id = z.zone_id
            WHERE p.product_name LIKE %s
            LIMIT 1
            """,
            (f'%{name}%',),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return {'zone_id': row['zone_id'], 'zone_name': row['zone_name']}
    except Exception as e:
        logger.warning('DB 검색 실패: %s', e)
    return None


def search_keyword(name: str) -> Optional[dict]:
    """정규화 키워드 매핑으로 구역 검색 (fallback)."""
    norm = _normalize(name)
    for entry in _KEYWORD_MAP:
        for kw in entry['keywords']:
            if _normalize(kw) in norm or norm in _normalize(kw):
                return {'zone_id': entry['zone_id'], 'zone_name': entry['zone_name']}
    return None


# ── Flask 앱 ───────────────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route('/query', methods=['GET'])
def query():
    """
    GET /query?name=콜라
    → 200 {"zone_id": 3, "zone_name": "음료 코너"}
    → 404 {"error": "not_found"}
    """
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name 파라미터 필요'}), 400

    logger.info('검색 요청: "%s"', name)

    # 1) DB 검색
    result = search_db(name)
    if result:
        logger.info('DB 매칭: "%s" → %s', name, result)
        return jsonify(result)

    # 2) 키워드 fallback
    result = search_keyword(name)
    if result:
        logger.info('키워드 매칭: "%s" → %s', name, result)
        return jsonify(result)

    logger.info('미매칭: "%s"', name)
    return jsonify({'error': 'not_found', 'name': name}), 404


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    logger.info('ShopPinkki LLM 서버 시작 (포트 %d)', PORT)
    app.run(host=HOST, port=PORT, debug=False)
