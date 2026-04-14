import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000/query"

test_cases = [
    # ── 1. 12개 모든 구역 (기본 키워드) ──
    {"type": "구역", "query": "가전제품 어디야?", "expected": "가전제품"},
    {"type": "구역", "query": "과자 코너 고고", "expected": "과자"},
    {"type": "구역", "query": "해산물 파는 곳", "expected": "해산물"},
    {"type": "구역", "query": "육류 구역", "expected": "육류"},
    {"type": "구역", "query": "신선한 채소", "expected": "채소"},
    {"type": "구역", "query": "음료수 마시고 싶어", "expected": "음료"},
    {"type": "구역", "query": "갓 구운 빵 베이커리", "expected": "베이커리"},
    {"type": "구역", "query": "음식 코너", "expected": "음식"},
    {"type": "구역", "query": "화장실 급해", "expected": "화장실"},
    {"type": "구역", "query": "쉬 마려워요", "expected": "화장실"},
    {"type": "구역", "query": "똥 나올 것 같아", "expected": "화장실"},
    {"type": "구역", "query": "마트 입구 어디", "expected": "입구"},
    {"type": "구역", "query": "나가는 출구", "expected": "출구"},
    {"type": "구역", "query": "계산하러 갈래", "expected": "결제 구역"},

    # ── 2. 상품별 상세 검색 (전 품목 대상 샘플링) ──
    {"type": "상품", "query": "TV 사고 싶어", "expected": "가전제품"},
    {"type": "상품", "query": "냉장고 어딨어?", "expected": "가전제품"},
    {"type": "상품", "query": "에어컨 추천해줘", "expected": "가전제품"},
    {"type": "상품", "query": "감자칩 포카칩", "expected": "과자"},
    {"type": "상품", "query": "오레오 쿠키", "expected": "과자"},
    {"type": "상품", "query": "달고 맛있는 쌀과자", "expected": "과자"},
    {"type": "상품", "query": "싱싱한 연어 회", "expected": "해산물"},
    {"type": "상품", "query": "새우 볶음용", "expected": "해산물"},
    {"type": "상품", "query": "고등어나 갈치 있나요", "expected": "해산물"},
    {"type": "상품", "query": "고기 파티 소고기", "expected": "육류"},
    {"type": "상품", "query": "삼겹살 돼지고기", "expected": "육류"},
    {"type": "상품", "query": "닭고기 치킨", "expected": "육류"},
    {"type": "상품", "query": "당근 주스 재료", "expected": "채소"},
    {"type": "상품", "query": "브로콜리랑 상추", "expected": "채소"},
    {"type": "상품", "query": "콜라 탄산음료", "expected": "음료"},
    {"type": "상품", "query": "맥주나 소주 있어?", "expected": "음료"},
    {"type": "상품", "query": "상큼한 오렌지주스", "expected": "음료"},
    {"type": "상품", "query": "아침용 식빵", "expected": "베이커리"},
    {"type": "상품", "query": "달콤한 케이크", "expected": "베이커리"},
    {"type": "상품", "query": "크루아상이나 머핀", "expected": "베이커리"},
    {"type": "상품", "query": "간편한 도시락", "expected": "음식"},
    {"type": "상품", "query": "매콤한 떡볶이", "expected": "음식"},
    {"type": "상품", "query": "라면 끓여 먹게", "expected": "음식"},
    {"type": "상품", "query": "볶음밥 냉동식품", "expected": "음식"},

    # ── 3. 상태 기반/고정 라우팅 (Empathy 로직) ──
    {"type": "상태", "query": "오늘 너무 우울해", "expected": "과자"},
    {"type": "상태", "query": "스트레스 받아서 술 고파", "expected": "음료"},
    {"type": "상태", "query": "잠 깨고 싶어", "expected": "음료"},
    {"type": "상태", "query": "배고파서 쓰러지겠어", "expected": "음식"},
    {"type": "상태", "query": "목말라 죽겠네", "expected": "음료"},
    {"type": "특수", "query": "마트 도착했다!", "expected": "입구"},
    {"type": "특수", "query": "이제 집에 가야지", "expected": "출구"},

    # ── 4. 폴백/거절/무의미 (Nonsense) ──
    {"type": "거절", "query": "ㄱㄴㄷㄹㅁㅂㅅ", "expected": "FAILED"},
    {"type": "거절", "query": "asdfghjkl", "expected": "FAILED"},
    {"type": "거절", "query": "우리 집 강아지는 복슬강아지", "expected": "FAILED"},
    {"type": "거절", "query": "오늘 날씨 알려줘", "expected": "FAILED"},
    {"type": "거절", "query": "안녕? 넌 누구니?", "expected": "FAILED"},
    {"type": "거절", "query": "비트코인 시세 좀 알려줄래?", "expected": "FAILED"},
    {"type": "거절", "query": "롤 티어 올리는 법", "expected": "FAILED"},
    {"type": "거절", "query": "정치 얘기 해보자", "expected": "FAILED"},
    {"type": "거절", "query": "이마트랑 홈플러스 중에 어디가 더 좋아?", "expected": "FAILED"},
    {"type": "거절", "query": "로또 번호 추천해줘", "expected": "FAILED"},
    {"type": "거절", "query": "강아지 사료 말고 강아지 입장이 가능한가요?", "expected": "FAILED"},
]

def run_tests():
    results = []
    print(f"\n🚀 Integrated AI Service Test (Total {len(test_cases)} cases)\n")
    
    for case in test_cases:
        try:
            start_time = time.time()
            response = requests.get(BASE_URL, params={"name": case["query"]}, timeout=10)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                zone = data.get("zone_name", "N/A")
                answer = data.get("answer", "N/A")
                error = data.get("error", "")
                dist = data.get("distance", "N/A")
                
                if error == "not_found":
                    actual = "FAILED"
                else:
                    actual = zone
                
                status = "✅" if actual == case["expected"] else "❌"
                
                results.append([
                    status,
                    case["type"],
                    case["query"],
                    case["expected"],
                    actual,
                    f"{elapsed:.2f}s",
                    answer[:40] + "..." if len(answer) > 40 else answer
                ])
            else:
                results.append(["🔥", case["type"], case["query"], case["expected"], f"HTTP {response.status_code}", "-", "-"])
        except Exception as e:
            results.append(["💥", case["type"], case["query"], case["expected"], "ERROR", "-", str(e)])
        
        time.sleep(0.1) # 서버 부하 조절

    headers = ["P/F", "유형", "질문(Query)", "기대 구역", "실제 구역", "시간", "AI 응답"]
    print(tabulate(results, headers=headers, tablefmt="github"))
    
    passed = sum(1 for r in results if r[0] == "✅")
    total = len(results)
    print(f"\n📊 정답률: {passed}/{total} ({passed/total*100:.1f}%)\n")

def wait_for_server():
    print("⏳ Waiting for server at http://127.0.0.1:8000 ...")
    for _ in range(30):
        try:
            requests.get(BASE_URL, params={"name": "ping"}, timeout=1)
            print("🟢 Server is ready!")
            return True
        except:
            time.sleep(2)
    print("🔴 Server timeout!")
    return False

if __name__ == "__main__":
    if wait_for_server():
        # tabulate 가 없는 환경을 위해 간단한 체크
        try:
            from tabulate import tabulate
        except ImportError:
            def tabulate(data, headers, tablefmt):
                print(" | ".join(headers))
                print("-" * 100)
                for row in data:
                    print(" | ".join(map(str, row)))
                return ""
    
        run_tests()
