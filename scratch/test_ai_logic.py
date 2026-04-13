import requests
import json
import time

BASE_URL = "http://localhost:8000/query"

test_cases = [
    # 1. 12개 구역 기본 검색
    {"name": "가전제품", "desc": "구역1: 가전제품"},
    {"name": "과자 코너", "desc": "구역2: 과자"},
    {"name": "해산물", "desc": "구역3: 해산물"},
    {"name": "육류", "desc": "구역4: 육류"},
    {"name": "채소", "desc": "구역5: 채소"},
    {"name": "음료 어디야?", "desc": "구역6: 음료"},
    {"name": "빵 사고 싶어", "desc": "구역7: 베이커리"},
    {"name": "배고픈데 뭐 먹지?", "desc": "구역8: 음식 (상태 포함)"},
    {"name": "화장실 어디에요?", "desc": "구역100: 화장실"},
    {"name": "입구로 가줘", "desc": "구역110: 입구"},
    {"name": "나갈래", "desc": "구역120: 출구"},
    {"name": "계산하고 싶어요", "desc": "구역150: 결제 구역"},

    # 2. 방금 고친 폴백/무의미 쿼리
    {"name": "fsfsdf", "desc": "무의미 영문"},
    {"name": "ㄱㄴㄷㄹ", "desc": "무의미 한글 자음"},
    {"name": "록타르 오가르!!!!", "desc": "관련 없는 한국어 (게임 대사)"},
    {"name": "우리 집 강아지는 복슬강아지", "desc": "매장과 무관한 문장"},

    # 3. 추가된 상태 라우팅
    {"name": "너무 목말라", "desc": "신체 상태: 갈증"},
    {"name": "오늘 너무 우울해", "desc": "감정 상태: 우울"},
    {"name": "잠 깨고 싶어", "desc": "신체 상태: 피로"}
]

print(f"{'유형':<15} | {'입력':<20} | {'결과 구역':<10} | {'메시지(Answer)'}")
print("-" * 100)

for case in test_cases:
    try:
        start_time = time.time()
        resp = requests.get(BASE_URL, params={"name": case["name"]}, timeout=15)
        elapsed = time.time() - start_time
        data = resp.json()
        
        zone_name = data.get("zone_name", "N/A")
        answer = data.get("answer", "N/A")
        error = data.get("error", "")
        
        if error == "not_found":
            zone_display = "FAILED"
        else:
            zone_display = zone_name
            
        print(f"{case['desc']:<15} | {case['name']:<20} | {zone_display:<10} | {answer[:50]}...")
    except Exception as e:
        print(f"{case['desc']:<15} | {case['name']:<20} | ERROR      | {str(e)}")

print("-" * 100)
