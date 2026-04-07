-- ShopPinkki Seed Data
USE shoppinkki;

-- ──────────────────────────────────────────────
-- ZONE (상품 구역 1~8, 특수 구역)
-- ──────────────────────────────────────────────

INSERT INTO ZONE (zone_id, zone_name, zone_type, waypoint_x, waypoint_y, waypoint_theta) VALUES
-- 상품 구역
(1,   '가전제품',  'product', 0.0, 0.0, 0.0),
(2,   '과자',     'product', 0.0, 0.0, 0.0),
(3,   '해산물',   'product', 0.0, 0.0, 0.0),
(4,   '육류',     'product', 0.0, 0.0, 0.0),
(5,   '채소',     'product', 0.0, 0.0, 0.0),
(6,   '음료',     'product', 0.0, 0.0, 0.0),
(7,   '베이커리', 'product', 0.0, 0.0, 0.0),
(8,   '음식',     'product', 0.0, 0.0, 0.0),
-- 특수 구역
(100, '화장실',   'special', 0.0, 0.0, 0.0),
(110, '입구',     'special', 0.0, 0.0, 0.0),
(120, '출구',     'special', 0.0, 0.0, 0.0),
(140, '충전소 P1','special', 0.699, 0.100, 1.5708),
(141, '충전소 P2','special', 0.939, 0.100, 1.5708),
(150, '결제 구역','special', 0.0, 0.0, 0.0)
ON DUPLICATE KEY UPDATE zone_name=VALUES(zone_name);

-- ──────────────────────────────────────────────
-- PRODUCT
-- ──────────────────────────────────────────────

INSERT INTO PRODUCT (product_name, zone_id, price) VALUES
('TV',       1, 990000), ('냉장고',   1, 1290000), ('에어컨',   1, 1590000),
('쌀과자',   2,   2000), ('포카칩',   2,    1800), ('오레오',   2,    2500),
('연어',     3,  12000), ('새우',     3,    9000), ('오징어',   3,    8000),
('소고기',   4,  15000), ('돼지고기', 4,    9000), ('닭고기',   4,    7000),
('당근',     5,   1500), ('브로콜리', 5,    2500), ('상추',     5,    2000),
('콜라',     6,   1500), ('커피',     6,    3000), ('오렌지주스', 6,   3500),
('식빵',     7,   2800), ('크루아상', 7,    3200), ('머핀',     7,    3000),
('볶음밥',   8,   5500), ('라면',     8,    4500), ('떡볶이',   8,    5000)
ON DUPLICATE KEY UPDATE zone_id=VALUES(zone_id), price=VALUES(price);

-- ──────────────────────────────────────────────
-- PRODUCT_TEXT_EMBEDDING (text seed only; embedding is filled later)
-- ──────────────────────────────────────────────

INSERT INTO PRODUCT_TEXT_EMBEDDING (product_id, text, embedding, model_name)
SELECT p.product_id, v.text, NULL, 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
FROM (
  SELECT 'TV' AS product_name, '큰 화면으로 드라마, 영화, 방송 같은 영상 콘텐츠를 시청하는 전자기기이다. 거실이나 방에서 시청용으로 많이 사용한다.' AS text
  UNION ALL SELECT '냉장고', '음식과 음료를 차갑게 보관해 신선도를 유지하는 가전제품이다. 과일, 반찬, 음료수 같은 식품 보관에 사용한다.'
  UNION ALL SELECT '에어컨', '실내를 시원하게 유지하고 냉방이나 제습에 사용하는 가전제품이다. 더운 날씨에 실내 온도를 낮추는 데 사용한다.'
  UNION ALL SELECT '쌀과자', '쌀을 원료로 만든 과자로 담백하고 바삭한 간식에 해당한다. 가볍게 먹는 과자나 부담이 적은 간식으로 찾는 경우가 많다.'
  UNION ALL SELECT '포카칩', '감자를 얇게 썰어 만든 과자로 짭짤하고 바삭한 감자칩 간식이다. 간단한 스낵이나 바삭한 과자를 찾을 때 자주 선택된다.'
  UNION ALL SELECT '오레오', '초코 쿠키와 크림으로 구성된 과자로 달콤한 디저트 간식에 해당한다. 초콜릿 맛이나 단 간식을 찾을 때 함께 떠올리기 쉽다.'
  UNION ALL SELECT '연어', '부드럽고 고소한 생선류 식품으로 회, 샐러드, 구이 재료로 사용한다. 해산물 메뉴나 샐러드 재료를 찾을 때 자주 사용된다.'
  UNION ALL SELECT '새우', '탱글한 식감의 갑각류 식품으로 볶음, 튀김, 파스타 재료로 사용한다. 해물 요리나 튀김 재료를 찾는 상황과 잘 연결된다.'
  UNION ALL SELECT '오징어', '쫄깃한 식감의 연체류 식품으로 볶음, 구이, 안주 재료로 사용한다. 해산물 반찬이나 안주용 재료를 찾을 때 자주 언급된다.'
  UNION ALL SELECT '소고기', '풍미가 진한 육류로 구이, 스테이크, 국거리 재료로 사용한다. 고기 요리나 진한 맛의 식재료를 찾을 때 연결될 수 있다.'
  UNION ALL SELECT '돼지고기', '고소한 맛의 육류로 삼겹살, 구이, 볶음 요리에 사용한다. 구이나 볶음용 고기를 찾는 상황에서 자주 선택된다.'
  UNION ALL SELECT '닭고기', '담백한 육류로 구이, 볶음, 샐러드 재료로 사용한다. 비교적 가벼운 육류나 단백질 식재료를 찾을 때 자주 사용된다.'
  UNION ALL SELECT '당근', '아삭한 뿌리채소로 샐러드, 볶음, 주스 재료로 사용한다. 채소 반찬이나 주스 재료를 찾는 경우와 잘 연결된다.'
  UNION ALL SELECT '브로콜리', '식감이 단단한 채소로 데침, 볶음, 샐러드 재료로 사용한다. 건강식이나 샐러드용 채소를 찾을 때 자주 언급된다.'
  UNION ALL SELECT '상추', '신선한 잎채소로 쌈이나 샐러드에 사용하는 채소이다. 고기와 함께 먹는 쌈 채소를 찾는 상황에 어울린다.'
  UNION ALL SELECT '콜라', '차갑게 마시는 탄산음료로 단맛과 탄산감이 있는 음료이다. 시원한 음료나 탄산이 있는 마실 것을 찾을 때 연결된다.'
  UNION ALL SELECT '커피', '원두를 추출해 만드는 음료로 따뜻하게 또는 차갑게 마시며 카페인이 포함된다. 잠을 깨거나 카페인 음료를 찾는 상황과 관련된다.'
  UNION ALL SELECT '오렌지주스', '오렌지 과즙으로 만든 음료로 상큼한 과일 맛이 나는 주스이다. 과일 음료나 상큼한 마실 것을 찾을 때 떠올리기 쉽다.'
  UNION ALL SELECT '식빵', '밀가루 반죽을 구워 만든 빵으로 토스트나 샌드위치에 사용한다. 아침 식사나 간단한 빵을 찾을 때 잘 연결된다.'
  UNION ALL SELECT '크루아상', '버터를 넣은 페이스트리 빵으로 결이 겹겹이 나고 바삭한 식감이 있다. 베이커리류나 버터 풍미가 있는 빵을 찾을 때 어울린다.'
  UNION ALL SELECT '머핀', '작은 케이크 형태의 빵으로 달콤한 간식이나 디저트로 먹는다. 달콤한 빵이나 간단한 디저트를 찾는 경우와 잘 맞는다.'
  UNION ALL SELECT '볶음밥', '밥과 재료를 함께 볶아 만드는 음식으로 든든한 한 끼 식사에 해당한다. 간편하지만 포만감 있는 식사를 찾을 때 연결된다.'
  UNION ALL SELECT '라면', '면과 스프를 끓여 만드는 음식으로 뜨거운 국물과 매운맛을 포함할 수 있다. 따뜻한 국물 음식이나 매운 음식을 찾는 경우와 가깝다.'
  UNION ALL SELECT '떡볶이', '떡을 양념 소스에 조리한 음식으로 매콤달콤한 분식 메뉴에 해당한다. 분식이나 매콤한 간식을 찾을 때 자주 연결된다.'
) v
JOIN PRODUCT p ON p.product_name = v.product_name;

-- ──────────────────────────────────────────────
-- BOUNDARY_CONFIG
-- ──────────────────────────────────────────────

INSERT INTO BOUNDARY_CONFIG (description, x_min, x_max, y_min, y_max) VALUES
('결제 구역',     1.0,  1.8,  -0.3, 0.5),
('맵 외곽 경계',  -0.3, 1.6,  -1.7, 0.3)
ON DUPLICATE KEY UPDATE description=VALUES(description);

-- ──────────────────────────────────────────────
-- ROBOT
-- ──────────────────────────────────────────────

INSERT INTO ROBOT (robot_id, ip_address, current_mode) VALUES
('54', '192.168.102.54', 'CHARGING'),
('18', '192.168.102.18', 'CHARGING')
ON DUPLICATE KEY UPDATE ip_address=VALUES(ip_address), current_mode='CHARGING';

-- ──────────────────────────────────────────────
-- USER / CARD (테스트 계정, password = 'test1234' bcrypt)
-- ──────────────────────────────────────────────

INSERT INTO USER (user_id, password_hash) VALUES
('test01', '$2b$12$KIXbVqfTz0iYa.W9P1qG3OQvK6T8m2zN5cLnRjpFdS4AyXeUvHwMi'),
('test02', '$2b$12$KIXbVqfTz0iYa.W9P1qG3OQvK6T8m2zN5cLnRjpFdS4AyXeUvHwMi')
ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash);

INSERT INTO CARD (user_id, card_alias) VALUES
('test01', '신한카드 1234'),
('test02', '국민카드 5678')
ON DUPLICATE KEY UPDATE card_alias=VALUES(card_alias);
