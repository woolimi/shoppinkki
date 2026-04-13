import requests
import urllib.parse

base_url = "http://127.0.0.1:8000/query"
# (구역명, 정밀검색어, 모호한표현)
test_cases = [
    ("가전제품", "냉장고", "이사해서 가전제품 새로 맞추고 싶어"),
    ("과자", "포테이토칩", "입이 너무 심심해"),
    ("해산물", "고등어", "저녁에 생선구이 먹고 싶어"),
    ("육류", "삼겹살", "단백질 보충하게 고기 좀 찾을게"),
    ("채소", "상추", "건강하게 샐러드 재료 좀 볼까"),
    ("음료", "콜라", "목말라서 시원한 거 마시고 싶어"),
    ("베이커리", "식빵", "달콤한 빵 냄새 나네"),
    ("음식", "도시락", "배고파서 간단히 먹을 거"),
    ("화장실", "화장실", "너무 급해요"),
    ("입구", "입구", "마트 도착!"),
    ("출구", "출구", "이제 계산 다 했으니 집에 갈래"),
    ("결제", "카드 결제", "계산대 어디야"),
    ("베이커리", "간단히 먹을 거", "출출한데 가벼운 요기거리"),
    ("음식", "너무 배고파", "아침밥 뭐 먹지?"),
    ("알수없음", "dkclaqkq", "asdfghjkl")
]

print(f"{'구역':<8} | {'유형':<5} | {'질문':<15} | {'AI 응답 결과'}")
print("-" * 100)

for zone, specific, vague in test_cases:
    for type_name, q in [("정밀", specific), ("모호", vague)]:
        encoded_q = urllib.parse.quote(q)
        try:
            resp = requests.get(f"{base_url}?name={encoded_q}", timeout=10)
            data = resp.json()
            answer = data.get('answer', 'N/A')
            print(f"{zone:<8} | {type_name:<5} | {q:<15} | {answer}")
        except:
            print(f"{zone:<8} | {type_name:<5} | {q:<15} | ERROR")
