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
    """PostgreSQL pgvector 형식을 위한 문자열 변환 [v1, v2, ...]"""
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

def ask_qwen(user_query: str, search_result: str, zone_type: str = 'product') -> str:
    """Ollama를 통해 Qwen 2.5 3B 모델에게 답변 생성 요청"""
    try:
        if zone_type == 'special':
            # 화장실, 입구, 출구 등 특수 구역은 경로 설명 없이 매우 간결하게 안내
            prompt = (
                f"당신은 ShopPinkki 매장의 안내원입니다.\n"
                f"매장 정보: {search_result}\n"
                f"손님 질문: {user_query}\n\n"
                f"지침:\n"
                f"1. 가는 방법이나 경로(직진, 좌회전 등)를 절대 설명하지 마세요.\n"
                f"2. 불필요한 사족 없이 '해당 위치는 [위치명]입니다. 안내를 시작할까요?'라고만 짧고 친절하게 대답하세요.\n"
                f"3. 반드시 100% 한국어로만 답변하고, 숫자나 기호는 사용하지 마세요.\n\n"
                f"AI 점원의 답변:"
            )
        else:
            # 일반 상품 구역: 질문 유형에 따라 맞춤형 답변
            prompt = (
                f"당신은 ShopPinkki 매장의 친절한 안내원입니다. 제공된 매장 정보만을 근거로 대답하세요.\n"
                f"매장 정보: {search_result}\n"
                f"손님 질문: {user_query}\n\n"
                f"지침:\n"
                f"답변은 반드시 아래 제시된 네 가지 형식 중 하나만 정확하게 선택하세요. 절대 다른 사족을 붙이거나 지어내지 마세요.\n\n"
                f"유형 1. 명확한 상품/구역 검색 (예: 콜라 어딨어?, 고기 찾아):\n    '해당 상품은 [구역명] 코너에 있습니다. 안내를 시작할까요?'\n"
                f"유형 2. 목마름 관련 모호한 질문 (예: 목말라, 마실거):\n    '목마르시죠? [구역명] 코너로 안내해 드릴게요. 안내를 시작할까요?'\n"
                f"유형 3. 배고픔 관련 모호한 질문 (예: 배고파, 너무 굶었어, 식사):\n    '출출하시죠? [구역명] 코너로 안내해 드릴게요. 안내를 시작할까요?'\n"
                f"유형 4. 간단한 간식 관련 모호한 질문 (예: 간단하게 먹을거, 과자, 빵):\n    '간단한 간식을 찾으시나요? [구역명] 코너로 안내해 드릴게요. 안내를 시작할까요?'\n\n"
                f"주의사항:\n"
                f"- 제공된 매장 정보의 위치(구역명) 외에 가상의 아이템(주방, 라떼, 땅콩 등)이나 경로(좌회전 등)는 절대 언급하지 마세요.\n"
                f"- 구역 번호나 불필요한 기호(', \")는 사용하지 마세요.\n\n"
                f"AI 점원의 답변:"
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
        
        # 동의어 처리 (카운터 등 -> 결제 구역)
        synonyms = {'카운터': '결제 구역', '계산대': '결제 구역', '캐셔': '결제 구역'}
        exact_match_name = synonyms.get(name, name)
        
        # 0. 텍스트 완전 일치 검색 (상품명 또는 구역명 우선)
        # 일치할 경우 거리(distance)를 최소값(0.0)으로 해서 즉시 반환
        exact_query = """
            SELECT 'product' as type, p.product_name as display_name, z.zone_id, z.zone_name, z.zone_type, 0.0 as distance,
                   ze.empathy_prefix, ze.required_keywords
            FROM product p
            JOIN zone z ON p.zone_id = z.zone_id
            LEFT JOIN zone_text_embedding ze ON z.zone_id = ze.zone_id
            WHERE p.product_name = %s
            UNION ALL
            SELECT 'zone' as type, z.zone_name as display_name, z.zone_id, z.zone_name, z.zone_type, 0.01 as distance,
                   ze.empathy_prefix, ze.required_keywords
            FROM zone z
            LEFT JOIN zone_text_embedding ze ON z.zone_id = ze.zone_id
            WHERE z.zone_name = %s
            LIMIT 1;
        """
        cursor.execute(exact_query, (exact_match_name, exact_match_name))
        row = cursor.fetchone()
        if row:
            logger.info('텍스트 완전 일치 검색 성공(지능형): "%s" (원본: "%s") -> %s', exact_match_name, name, row['display_name'])
            cursor.close()
            conn.close()
            return row

        query = """
            SELECT type, display_name, zone_id, zone_name, zone_type, distance, empathy_prefix, required_keywords FROM (
                -- 1. 상품명 검색 (해당 구역의 공감 멘트와 필수 키워드 포함)
                SELECT 'product' as type, p.product_name as display_name, z.zone_id, z.zone_name, z.zone_type,
                       (te.embedding <=> %s::vector) as distance,
                       ze.empathy_prefix,
                       ze.required_keywords
                FROM product_text_embedding te
                JOIN product p ON te.product_id = p.product_id
                JOIN zone z ON p.zone_id = z.zone_id
                LEFT JOIN zone_text_embedding ze ON z.zone_id = ze.zone_id
                WHERE (te.embedding <=> %s::vector) < 0.42
                
                UNION ALL
                
                -- 2. 구역 설명 검색
                SELECT 'zone' as type, z.zone_name as display_name, z.zone_id, z.zone_name, z.zone_type,
                       (ze.embedding <=> %s::vector) as distance,
                       ze.empathy_prefix,
                       ze.required_keywords
                FROM zone_text_embedding ze
                JOIN zone z ON ze.zone_id = z.zone_id
                WHERE (ze.embedding <=> %s::vector) < 0.42
            ) as combined_search
            ORDER BY distance ASC
            LIMIT 1;
        """
        cursor.execute(query, (vec_str, vec_str, vec_str, vec_str))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return row
    except Exception as e:
        logger.error('벡터 검색 중 에러: %s', e)
    return None

def extract_keywords(user_query: str) -> list[str]:
    """DB에서 Few-shot 예제를 가져와 동적으로 프롬프트를 생성하고 핵심 키워드 추출"""
    try:
        # 1. DB에서 지능형 예제 로드
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT input_query, output_keywords FROM llm_fewshot_example ORDER BY id ASC")
        examples = cursor.fetchall()
        cursor.close()
        conn.close()

        # 2. 동적 프롬프트 조립
        examples_text = ""
        for ex in examples:
            examples_text += f"예: '{ex['input_query']}' -> '{ex['output_keywords']}'\n"

        prompt = (
            f"당신은 매장 상품 카테고리 분석기입니다. 다음 질문에서 검색에 필요한 핵심 '카테고리 명사'나 '상품명'을 최대 3개만 뽑으세요.\n"
            f"주의 포인트:\n"
            f"1. 반드시 질문 내용에 포함되거나 직접적으로 연관된 단어만 추출하세요.\n"
            f"2. 만약 질문이 매장과 관련이 없거나(예: 게임 대사, 타 분야 질문), 무의미한 말(예: 횡설수설, 외계어)인 경우 반드시!!! '알 수 없음'이라고만 대답하세요. 절대 억지로 구역을 매핑하지 마세요.\n"
            f"3. 질문과 상관없는 구역을 임의로 추가하지 마세요.\n"
            f"4. 오직 키워드만 쉼표로 구분하여 출력하세요. 설명은 필요 없습니다.\n"
            f"매장의 유효한 구역: 화장실, 입구, 출구, 결제 구역, 가전제품, 과자, 해산물, 육류, 채소, 음료, 베이커리, 음식\n"
            f"{examples_text}"
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
            raw = re.sub(r"['\">:\-]|(->)", " ", raw)
            stop_words = {'없어', '있어', '있나요', '찾아줘', '어디', '어디야', '건가요'}
            keywords = [k.strip() for k in re.split(r'[,\n]', raw) if k.strip() and k.strip() not in stop_words]
            return keywords
    except Exception as e:
        logger.warning("DB 기반 동적 프롬프트 추출 실패: %s", e)
    return []

def is_nonsense(text: str) -> bool:
    """무의미한 문자열이나 횡설수설을 탐지"""
    # 1. 공백 제거 후 내용이 없으면 nonsense
    clean_text = re.sub(r'\s+', '', text)
    if not clean_text: 
        logger.info('is_nonsense: 내용 없음')
        return True
    
    # 2. 한글 자음/모음만 나열된 경우 (예: ㄱㄴㄷㄹ, ㅏㅑㅓㅕ)
    # [ㄱ-ㅎ]는 \u3131-\u314E, [ㅏ-ㅣ]는 \u314F-\u3163
    if re.search(r'^[\u3131-\u3163]+$', clean_text):
        logger.info('is_nonsense: 자음/모음 나열 감지')
        return True
    
    # 3. 동일 문자가 너무 많이 반복되는 경우
    if re.search(r'(.)\1{4,}', clean_text):
        logger.info('is_nonsense: 동일 문자 반복 감지')
        return True
        
    # 4. 한글이 없는 경우의 추가 체크
    has_korean = any('\uAC00' <= ch <= '\uD7A3' or '\u3131' <= ch <= '\u3163' for ch in text)
    if not has_korean:
        known_english = {'toilet', 'restroom', 'water', 'coke', 'beer', 'coffee', 'exit', 'entrance', 'snack', 'meat', 'food', 'tv'}
        words = re.findall(r'[a-zA-Z]+', text.lower())
        if words:
            if not any(word in known_english for word in words) and len(clean_text) > 5:
                logger.info('is_nonsense: 무의미한 영문 감지')
                return True
    
    return False

app = Flask(__name__)
app.json.ensure_ascii = False

def get_predefined_routing(user_query: str):
    """
    고정 키워드(감정, 신체 상태, 특수 구역)를 코드 레벨에서 즉시 매핑 (LLM 우회).
    """
    # (키워드 목록, zone_id, zone_name, item_name, empathy_prefix)
    ROUTING_MAP = [
        # 1. 감정 상태
        (["우울", "슬퍼", "슬프다", "눈물", "울고 싶", "기분이 안 좋"],
         2, "과자", "초콜릿", "기분이 조금 가라앉으셨나요? 달콤한 초콜릿으로 기분 전환을 해보시는 건 어떨까요?"),
        (["힘들", "스트레스", "술 생각", "술 한 잔", "고된"],
         6, "음료", "맥주", "오늘 정말 고된 하루를 보내셨군요. 시원한 맥주 한 잔으로 스트레스를 날려버리시는 건 어떨까요?"),
        (["피곤", "졸려", "잠 깨", "잠이 와", "커피 생각", "카페인"],
         6, "음료", "커피", "정신이 번쩍 드는 시원한 커피 한 잔 어떠신가요?"),
        
        # 2. 신체 상태 (허기, 갈증)
        (["배고파", "배고프", "배고픈", "허기", "식사"],
         8, "음식", "도시락", "배가 많이 고프시군요! 든든한 도시락이나 식사류 코너로 안내해 드릴게요."),
        (["목말라", "목이 말", "마실 거", "음료수", "마실것"],
         6, "음료", "시원한 음료", "목이 많이 마르시죠? 시원한 음료는 어떠신가요?"),
         
        # 3. 특수 구역 (직관 매핑)
        (["화장실", "급해", "restroom", "toilet"], 100, "화장실", "화장실", "정말 급하시군요!"),
        (["입구", "들어온", "시작", "입구 어디"], 110, "입구", "입구", "쇼핑의 시작! 마트 입구입니다."),
        (["출구", "나갈", "나가고", "끝", "출구 어디"], 120, "출구", "출구", "오늘 쇼핑은 즐거우셨나요? 출구로 안내해 드릴게요."),
        (["계산", "결제", "카운터", "계산대", "캐셔"], 150, "결제 구역", "결제 구역", "계산을 도와드릴게요."),
    ]
    for keywords, zone_id, zone_name, item_name, empathy in ROUTING_MAP:
        if any(kw in user_query.lower() for kw in keywords):
            logger.info('사전 정의 라우팅 매칭: "%s" -> %s (%s)', user_query, zone_name, item_name)
            return {
                'zone_id': zone_id,
                'zone_name': zone_name,
                'empathy_prefix': empathy
            }, item_name
    return None, None


@app.route('/query', methods=['GET'])
def query():
    name = request.args.get('name', '').strip()
    if not name: return jsonify({'error': 'name 필요'}), 400
    
    logger.info('검색 요청: "%s"', name)

    # ── [0순위] 무의미한 입력 방어 ──
    if is_nonsense(name):
        logger.info('무의미한 입력 차단: "%s"', name)
        return jsonify({
            'answer': "죄송합니다. 요청하신 내용을 이해하지 못했습니다. 다시 말씀해 주시겠어요?",
            'error': 'not_found'
        }), 200

    # ── [1순위] 사전 정의된 라우팅 (감정/상태/특수구역) ──
    pre_zone, pre_item = get_predefined_routing(name)
    if pre_zone:
        zone_name = pre_zone['zone_name']
        empathy   = pre_zone.get('empathy_prefix') or ""
        no_corner_list = ['입구', '출구', '화장실', '결제 구역']
        is_no_corner = any(nc in zone_name for nc in no_corner_list)
        clean_zone = zone_name.strip() if is_no_corner else zone_name.replace(' 구역','').replace('구역','').strip()
        suffix = "" if is_no_corner else " 코너"
        def _josa(w):
            if not w: return "은(는)"
            c = ord(w[-1]) - 44032
            if c < 0 or c > 11171: return "은(는)"
            return "은" if c % 28 > 0 else "는"
        # 특수 구역(item_name == zone_name)이면 중복 방지
        if pre_item == zone_name:
            # empathy에 이미 '안내'가 포함된 경우 그대로, 아니면 추가
            if "안내" in empathy:
                answer = f"{empathy.strip()}"
            else:
                # 한국어 조사 '으로/로' 자동 처리 (ㄹ받침은 '로')
                last_char = clean_zone[-1] if clean_zone else ''
                jongseong = (ord(last_char) - 44032) % 28 if '\uAC00' <= last_char <= '\uD7A3' else 0
                ro = '으로' if jongseong > 0 and jongseong != 8 else '로'
                answer = f"{empathy.strip()} {clean_zone}{ro} 안내해 드릴까요?"
        else:
            answer = f"{empathy.strip()} {pre_item}{_josa(pre_item)} {clean_zone}{suffix}에 있습니다. 안내를 시작할까요?"
        answer = answer.strip()
        logger.info('사전 정의 응답 반환: %s -> zone %s / item %s', name, zone_name, pre_item)
        return jsonify({
            'zone_id':     pre_zone['zone_id'],
            'zone_name':   zone_name,
            'display_name': pre_item,
            'distance':    0.0,
            'answer':      answer,
            'empathy':     empathy
        })

    # 1. 원본 질문을 최우선 순위로, 추출 키워드를 부가 순위로 설정 (순서가 매우 중요)
    extracted_keywords = extract_keywords(name)
    if not extracted_keywords or "알 수 없음" in extracted_keywords:
        extracted_keywords = []
        logger.info('LLM 알 수 없음/빈 키워드 → 원본만으로 벡터 검색: "%s"', name)

    # ── [쓰레기 입력 방어] ──
    # 한글이 전혀 없는 입력(예: asdfghjkl, zzzzz)은 LLM 추출 키워드를 신뢰할 수 없음.
    # LLM이 무의미한 문자열에서 '화장실', '출구' 같은 유효 구역명을 환각할 수 있으므로,
    # 한글이 없으면 원본 쿼리만으로 벡터 검색 → 임계값 초과 → not_found 로 자연스럽게 거절.
    has_korean = any('\uAC00' <= ch <= '\uD7A3' or '\u3131' <= ch <= '\u3163' for ch in name)
    if not has_korean:
        extracted_keywords = []
        logger.info('한글 없는 입력 감지 → LLM 추출 키워드 무시: "%s"', name)

    # 원본 name을 리스트의 맨 처음에 배치하여 LLM 변조 방지 (입구 -> 출구 방어)
    search_candidates = list(dict.fromkeys([name] + extracted_keywords))

    logger.info('검색 후보 키워드: %s', search_candidates)

    best_result = None
    min_dist = 1.0
    
    # 2. 각 후보 키워드별 벡터 검색 수행
    for idx, kw in enumerate(search_candidates):
        res = search_context_in_db(kw)
        if res:
            dist = res['distance']
            zone_id = res['zone_id']
            
            # [특수 구역 방어 로직 - 100% DB 기반] 
            # 필수 키워드가 DB에 정의된 경우, 해당 단어가 검색어에 없으면 페널티 부여
            required_kws = res.get('required_keywords')
            if required_kws:
                is_explicit = any(word in kw for word in required_kws)
                if not is_explicit:
                    dist += 0.3 # 페널티 적용
            
            logger.info('  - 후보 [%d] 키워드 [%s] 매칭 후보: %s (Weight-Dist: %.4f, Original: %.4f)', idx, kw, res['display_name'], dist, res['distance'])
            
            if dist < min_dist and dist < 0.42:
                min_dist = dist
                best_result = res
                
                # [조기 종료 로직 - DB 기반]
                # 원본 질문이 특수 구역 필수 키워드와 함께 매우 낮은 거리로 검색되면 즉시 확정
                if idx == 0 and res.get('required_keywords') and dist < 0.3:
                    logger.info('  - 특수 구역 고정 매칭 발견 (조기 종료): %s', res['display_name'])
                    break
        else:
            logger.info('  - 후보 [%d] 키워드 [%s] 매칭 실패 (임계값 초과)', idx, kw)
            
    if best_result:
        display_name = best_result['display_name']
        zone_name = best_result['zone_name']
        empathy = best_result.get('empathy_prefix')
        
        # ── [100% 데이터 기반 답변 조립] ──
        # 한국어 조사(은/는) 처리 로직
        def get_josa(word):
            if not word: return "은(는)"
            char_code = ord(word[-1]) - 44032
            if char_code < 0 or char_code > 11171: return "은(는)"
            return "은" if char_code % 28 > 0 else "는"

        # ── [지능형 주어(Display Name) 결정 로직] ──
        # 1. 추천 상품이 공감 멘트에 포함되어 있다면 (예: 포카칩), 그 상품을 주어로 사용
        if empathy and "어떠신가요" in empathy:
            import re
            match = re.search(r'([가-힣]+)은 어떠신가요|([가-힣]+)는 어떠신가요', empathy)
            if match:
                display_name = match.group(1) or match.group(2)
        # 2. 질문이 매우 짧고(5자 이내) 공백이 없어야 사용자 원본어 사용 (삼겹살, 콜라 등)
        elif len(name) <= 5 and " " not in name and float(best_result.get('distance', 1.0)) < 0.2:
             display_name = name
        # 3. 그 외 문장이거나 긴 질문이면 AI가 찾은 핵심 명칭(display_name) 사용
        else:
             display_name = best_result['display_name']

        # 구역명에서 '구역'이라는 단어 보존 여부 결정 및 '코너' 접미사 제어
        # 입구, 출구, 화장실, 결제 구역은 '코너'를 붙이지 않음
        no_corner_list = ['입구', '출구', '화장실', '결제 구역']
        is_no_corner = any(nc in zone_name for nc in no_corner_list)
        
        # '코너'를 붙이지 않는 구역이면 원본 명칭 사용, 아니면 '구역' 제거 후 '코너' 붙임
        if is_no_corner:
            clean_zone_name = zone_name.strip()
            suffix = ""
        else:
            clean_zone_name = zone_name.replace(' 구역', '').replace('구역', '').strip()
            suffix = " 코너"
        
        josa_zone = get_josa(clean_zone_name + suffix)
        josa_disp = get_josa(display_name)
        
        # 3. 답변 조립
        # 직접 구역명/상품명을 명시한 경우(정확 일치, distance ≤ 0.01)는 공감 생략
        is_exact_match = float(best_result.get('distance', 1.0)) <= 0.01
        use_empathy = empathy and not is_exact_match
        
        if use_empathy:
            if display_name == clean_zone_name:
                answer = f"{empathy.strip()} {clean_zone_name}{suffix}{josa_zone} 여기에 있습니다."
            else:
                answer = f"{empathy.strip()} {display_name}{josa_disp} {clean_zone_name}{suffix}에 있습니다."
        else:
            if display_name == clean_zone_name:
                # 한국어 조사 '으로/로' 자동 처리 (ㄹ받침은 '로')
                _last = (clean_zone_name + suffix)[-1] if (clean_zone_name + suffix) else ''
                _js = (ord(_last) - 44032) % 28 if '\uAC00' <= _last <= '\uD7A3' else 0
                _ro = '으로' if _js > 0 and _js != 8 else '로'
                answer = f"{clean_zone_name}{suffix}{_ro} 안내해 드릴까요?"
            else:
                answer = f"{display_name}{josa_disp} {clean_zone_name}{suffix}에 있습니다."
        
        # 최종 안내 문구 추가
        if "안내" not in answer:
            answer += " 안내를 시작할까요?"
        
        # 최종 정제 (중복 조사 및 명칭 정리)
        answer = str(answer).replace(' 코너 코너', ' 코너').replace('  ', ' ').replace('"', '').replace("'", "").strip()
        
        return jsonify({
            'zone_id': best_result['zone_id'],
            'zone_name': best_result['zone_name'],
            'display_name': best_result['display_name'],
            'distance': float(best_result['distance']),
            'answer': answer,
            'empathy': empathy
        })
    
    return jsonify({
        'answer': "죄송합니다. 요청하신 상품이나 장소를 저희 매장에서 찾지 못했습니다. 다시 말씀해 주시겠어요?",
        'error': 'not_found'
    }), 200

if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=False)
