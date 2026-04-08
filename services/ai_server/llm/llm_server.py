"""ShopPinkki LLM 자연어 상품 위치 검색 서버 (채널 D).

REST GET /query?name=<상품명>
→ {"zone_id": 3, "zone_name": "음료 코너"}
"""

from __future__ import annotations
import logging
import os
import re
import requests
from typing import Optional

from flask import Flask, jsonify, request
from sentence_transformers import SentenceTransformer
import psycopg2
import psycopg2.extras
import numpy as np
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('llm_server')

# ── 환경 변수 ──────────────────────────────────────────────────────────────────
PG_HOST = os.environ.get('PG_HOST', '127.0.0.1')
PG_PORT = int(os.environ.get('PG_PORT', '5432'))
PG_USER = os.environ.get('PG_USER', 'shoppinkki')
PG_PASSWORD = os.environ.get('PG_PASSWORD', 'shoppinkki')
PG_DATABASE = os.environ.get('PG_DATABASE', 'shoppinkki')
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '8000'))

# Ollama 설정 (host 모드 적용으로 127.0.0.1 사용)
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434/api/generate')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:3b')

# ── Sentence-Transformers 모델 로드 ──────────────────────────────
EMBED_MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
logger.info("Sentence-Transformers 모델(%s) 로드 중...", EMBED_MODEL_NAME)
try:
    _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    logger.info("NLP 임베딩 모델 초기화 완료! (384차원)")
except Exception as e:
    logger.error("NLP 임베딩 초기화 에러: %s", e)
    _embed_model = None

def vector_to_string(values: np.ndarray) -> str:
    """PostgreSQL pgvector 형식을 위한 문자열 변환"""
    return "[" + ", ".join(f"{v:.8f}" for v in values) + "]"

def get_db_connection():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DATABASE,
        connect_timeout=3
    )

def ask_qwen(user_query: str, search_result: str) -> str:
    """Ollama를 통해 Qwen 2.5 3B 모델에게 답변 생성 요청"""
    try:
        prompt = (
            f"당신은 ShopPinkki 매장의 친절한 AI 점원입니다. 다음 검색 정보를 참고해서 손님에게 아주 짧고 친절하게 대답해 주세요.\n\n"
            f"매장 정보: {search_result}\n"
            f"손님 질문: {user_query}\n\n"
            f"답변 (한 문장으로):"
        )
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 150, "temperature": 0.7}
            },
            timeout=15
        )
        if response.status_code == 200:
            return response.json().get('response', '').strip()
    except Exception as e:
        logger.warning("Qwen 응답 생성 실패: %s", e)
    return f"네, 찾으시는 상품은 {search_result} 지역에 있습니다."

def search_context_in_db(name: str) -> Optional[dict]:
    """pgvector 기반 벡터 검색"""
    if _embed_model is None: return None
    try:
        query_vector = _embed_model.encode(name, normalize_embeddings=True)
        vec_str = vector_to_string(query_vector)
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        query = """
            SELECT type, display_name, zone_id, zone_name, distance FROM (
                SELECT 'product' as type, p.product_name as display_name, z.zone_id, z.zone_name,
                       (e.embedding <=> %s::vector) as distance
                FROM PRODUCT_TEXT_EMBEDDING e
                JOIN PRODUCT p ON e.product_id = p.product_id
                JOIN ZONE z ON p.zone_id = z.zone_id
                WHERE e.embedding IS NOT NULL
                
                UNION ALL
                
                SELECT 'zone' as type, z.zone_name as display_name, z.zone_id, z.zone_name,
                       (ze.embedding <=> %s::vector) as distance
                FROM ZONE_TEXT_EMBEDDING ze
                JOIN ZONE z ON ze.zone_id = z.zone_id
                WHERE ze.embedding IS NOT NULL
            ) combined
            ORDER BY distance ASC
            LIMIT 1
        """
        cursor.execute(query, (vec_str, vec_str))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        # Cosine Distance가 0.55 이하인 경우 유효 매칭으로 간주
        if row and row['distance'] < 0.55:
            return row
    except Exception as e:
        logger.error('벡터 검색 중 에러: %s', e)
    return None

def extract_keywords(user_query: str) -> list[str]:
    """Ollama를 사용하여 다중 키워드 추출"""
    try:
        prompt = (
            f"당신은 매장 안내 시스템의 언어 분석기입니다. 다음 질문에서 핵심 '상품명'이나 '구역명', '상위 카테고리'를 최대 3개까지만 콤마(,)로 구분하여 추출하세요.\n"
            f"질문: {user_query}\n"
            f"키워드:"
        )
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 30, "temperature": 0.1}
            },
            timeout=8
        )
        if response.status_code == 200:
            raw = response.json().get('response', '').strip()
            return [k.strip() for k in raw.split(',') if k.strip()]
    except Exception as e:
        logger.warning("키워드 추출 실패: %s", e)
    return [user_query]

app = Flask(__name__)
app.json.ensure_ascii = False

@app.route('/query', methods=['GET'])
def query():
    name = request.args.get('name', '').strip()
    if not name: return jsonify({'error': 'name 필요'}), 400
    
    keywords = extract_keywords(name)
    best_result = None
    min_dist = 1.0
    
    for kw in keywords:
        res = search_context_in_db(kw)
        if res and res['distance'] < min_dist:
            min_dist = res['distance']
            best_result = res
            
    if best_result:
        context_info = f"{best_result['display_name']} (구역: {best_result['zone_name']}, 번호: {best_result['zone_id']})"
        answer = ask_qwen(name, context_info)
        return jsonify({
            'zone_id': best_result['zone_id'],
            'zone_name': best_result['zone_name'],
            'display_name': best_result['display_name'],
            'distance': best_result['distance'],
            'answer': answer
        })
    
    return jsonify({'error': 'not_found', 'answer': "죄송합니다. 정보를 찾지 못했습니다."}), 404

if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=False)
