-- ShopPinkki Seed Data (PostgreSQL 17)

-- ZONE
INSERT INTO zone (zone_id, zone_name, zone_type, waypoint_x, waypoint_y, waypoint_theta) VALUES
(1,   '가전제품',  'product',  0.619, -0.007,  0.0),
(2,   '과자',     'product',  0.950, -0.007,  0.0),
(3,   '해산물',   'product',  1.151, -0.300,  3.1416),
(4,   '육류',     'product',  1.151, -0.752,  3.1416),
(5,   '채소',     'product',  1.151, -1.224,  3.1416),
(6,   '음료',     'product',  0.704, -0.899,  0.0),
(7,   '베이커리', 'product',  0.622, -0.300,  0.0),
(8,   '음식',     'product',  0.624, -0.606,  0.0),
(100, '화장실',   'special',  0.812, -1.586,  1.5708),
(110, '입구',     'special', 0.0, -0.007,  0.0),
(120, '출구',     'special', 0.0, -1.597,  0.0),
(140, '충전소_18(P1)','special', 0.0, -0.606, 0.0),
(141, '충전소_54(P2)','special', 0.0, -0.899, 0.0),
(150, '결제 구역','special',  0.186, -1.594,  1.5708)
ON CONFLICT (zone_id) DO UPDATE SET
    zone_name      = EXCLUDED.zone_name,
    zone_type      = EXCLUDED.zone_type,
    waypoint_x     = EXCLUDED.waypoint_x,
    waypoint_y     = EXCLUDED.waypoint_y,
    waypoint_theta = EXCLUDED.waypoint_theta;

-- PRODUCT
INSERT INTO product (product_name, zone_id, price) VALUES
('TV',       1, 990000), ('냉장고',   1, 1290000), ('에어컨',   1, 1590000),
('쌀과자',   2,   2000), ('포카칩',   2,    1800), ('오레오',   2,    2500),
('연어',     3,  12000), ('새우',     3,    9000), ('오징어',   3,    8000),
('소고기',   4,  15000), ('돼지고기', 4,    9000), ('닭고기',   4,    7000),
('당근',     5,   1500), ('브로콜리', 5,    2500), ('상추',     5,    2000),
('콜라',     6,   1500), ('커피',     6,    3000), ('오렌지주스', 6,   3500),
('식빵',     7,   2800), ('크루아상', 7,    3200), ('머핀',     7,    3000), ('케이크',   7,   35000),
('볶음밥',   8,   5500), ('라면',     8,    4500), ('떡볶이',   8,    5000)
ON CONFLICT (product_name) DO UPDATE SET
    zone_id = EXCLUDED.zone_id,
    price   = EXCLUDED.price;

-- PRODUCT_TEXT_EMBEDDING
INSERT INTO product_text_embedding (product_id, text, model_name)
SELECT p.product_id, v.text, 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
FROM (
  VALUES
  ('TV',         '큰 화면으로 드라마, 영화, 방송 같은 영상 콘텐츠를 시청하는 전자기기이다. 거실이나 방에서 시청용으로 많이 사용한다.'),
  ('냉장고',     '음식과 음료를 차갑게 보관해 신선도를 유지하는 가전제품이다. 과일, 반찬, 음료수 같은 식품 보관에 사용한다.'),
  ('에어컨',     '실내를 시원하게 유지하고 냉방이나 제습에 사용하는 가전제품이다. 더운 날씨에 실내 온도를 낮추는 데 사용한다.'),
  ('쌀과자',     '쌀을 원료로 만든 과자로 담백하고 바삭한 간식에 해당한다. 가볍게 먹는 과자나 부담이 적은 간식으로 찾는 경우가 많다.'),
  ('포카칩',     '감자를 얇게 썰어 만든 과자로 짭짤하고 바삭한 감자칩 간식이다. 간단한 스낵이나 바삭한 과자를 찾을 때 자주 선택된다.'),
  ('오레오',     '초코 쿠키와 크림으로 구성된 과자로 달콤한 디저트 간식에 해당한다. 초콜릿 맛이나 단 간식을 찾을 때 함께 떠올리기 쉽다.'),
  ('연어',       '부드럽고 고소한 생선류 식품으로 회, 샐러드, 구이 재료로 사용한다. 해산물 메뉴나 샐러드 재료를 찾을 때 자주 사용된다.'),
  ('새우',       '탱글한 식감의 갑각류 식품으로 볶음, 튀김, 파스타 재료로 사용한다. 해물 요리나 튀김 재료를 찾는 상황과 잘 연결된다.'),
  ('오징어',     '쫄깃한 식감의 연체류 식품으로 볶음, 구이, 안주 재료로 사용한다. 해산물 반찬이나 안주용 재료를 찾을 때 자주 언급된다.'),
  ('소고기',     '풍미가 진한 육류로 구이, 스테이크, 국거리 재료로 사용한다. 고기 요리나 진한 맛의 식재료를 찾을 때 연결될 수 있다.'),
  ('돼지고기',   '고소한 맛의 육류로 삼겹살, 구이, 볶음 요리에 사용한다. 구이나 볶음용 고기를 찾는 상황에서 자주 선택된다.'),
  ('닭고기',     '담백한 육류로 구이, 볶음, 샐러드 재료로 사용한다. 비교적 가벼운 육류나 단백질 식재료를 찾을 때 자주 사용된다.'),
  ('당근',       '아삭한 뿌리채소로 샐러드, 볶음, 주스 재료로 사용한다. 채소 반찬이나 주스 재료를 찾는 경우와 잘 연결된다.'),
  ('브로콜리',   '식감이 단단한 채소로 데침, 볶음, 샐러드 재료로 사용한다. 건강식이나 샐러드용 채소를 찾을 때 자주 언급된다.'),
  ('상추',       '신선한 잎채소로 쌈이나 샐러드에 사용하는 채소이다. 고기와 함께 먹는 쌈 채소를 찾는 상황에 어울린다.'),
  ('콜라',       '차갑게 마시는 탄산음료로 단맛과 탄산감이 있는 음료이다. 시원한 음료나 탄산이 있는 마실 것을 찾을 때 연결된다.'),
  ('커피',       '원두를 추출해 만드는 음료로 따뜻하게 또는 차갑게 마시며 카페인이 포함된다. 잠을 깨거나 카페인 음료를 찾는 상황과 관련된다.'),
  ('오렌지주스', '오렌지 과즙으로 만든 음료로 상큼한 과일 맛이 나는 주스이다. 과일 음료나 상큼한 마실 것을 찾을 때 떠올리기 쉽다.'),
  ('식빵',       '밀가루 반죽을 구워 만든 빵으로 토스트나 샌드위치에 사용한다. 아침 식사나 간단한 빵을 찾을 때 잘 연결된다.'),
  ('크루아상',   '버터를 넣은 페이스트리 빵으로 결이 겹겹이 나고 바삭한 식감이 있다. 베이커리류나 버터 풍미가 있는 빵을 찾을 때 어울린다.'),
  ('머핀',       '작은 케이크 형태의 빵으로 달콤한 간식이나 디저트로 먹는다. 달콤한 빵이나 간단한 디저트를 찾는 경우와 잘 맞는다.'),
  ('케이크',     '생일이나 기념일, 파티를 축하하기 위해 먹는 달콤하고 예쁜 케이크이다. 생크림, 초코 등 다양한 종류가 있으며 축하 상황에서 필수적인 베이커리이다.'),
  ('볶음밥',     '밥과 재료를 함께 볶아 만드는 음식으로 든든한 한 끼 식사에 해당한다. 간편하지만 포만감 있는 식사를 찾을 때 연결된다.'),
  ('라면',       '면과 스프를 끓여 만드는 음식으로 뜨거운 국물과 매운맛을 포함할 수 있다. 따뜻한 국물 음식이나 매운 음식을 찾는 경우와 가깝다.'),
  ('떡볶이',     '떡을 양념 소스에 조리한 음식으로 매콤달콤한 분식 메뉴에 해당한다. 분식이나 매콤한 간식을 찾을 때 자주 연결된다.')
) AS v(product_name, text)
JOIN product p ON p.product_name = v.product_name
ON CONFLICT (product_id) DO NOTHING;

-- ZONE_TEXT_EMBEDDING
INSERT INTO zone_text_embedding (zone_id, text, model_name)
SELECT z.zone_id, v.text, 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
FROM (
  VALUES
  ('입구', '쇼핑센터 마트로 들어오는 시작 구간, 입구, 시작, 환영합니다.'),
  ('출구', '쇼핑을 마치고 밖으로 나가는 구간, 퇴장, 안녕히 가세요.'),
  ('화장실', '생리 현상을 해결하는 곳, 화장실, 손 씻기, restroom, toilet'),
  ('결제 구역', '물건을 다 사고 돈을 내고 계산하는 곳, 캐셔, 계산대, 카운터'),
  ('가전제품', 'TV, 냉장고, 에어컨, 거실 꾸미기, 인테리어, 생활 가전제품을 파는 구역.'),
  ('과자', '과자, 스낵, 칩, 초콜릿, 입이 심심할 때, 주전부리, 간식거리가 있는 구역.'),
  ('해산물', '바다에서 나온 신선한 생선, 연어, 새우, 물고기가 있는 구역.'),
  ('육류', '고기, 돼지고기, 소고기, 치킨, 정육점이 있는 구역.'),
  ('채소', '신선한 야채, 브로콜리, 상추, 양파, 버섯이 있는 구역.'),
  ('음료', '목이 마를 때 마시는 물, 주스, 콜라, 커피가 있는 구역.'),
  ('베이커리', '갓 구운 빵, 식빵, 크루아상이 있는 구역. 간단히 먹고 싶을 때, 가벼운 간식, 디저트, 빵류.'),
  ('음식', '냉동식품, 라면, 볶음밥 등 간편식이 있는 구역. 배고플 때, 든든한 식사, 식사 대용, 포만감.')
) AS v(zone_name, text)
JOIN zone z ON z.zone_name = v.zone_name
ON CONFLICT (zone_id) DO NOTHING;

-- BOUNDARY_CONFIG
INSERT INTO boundary_config (description, x_min, x_max, y_min, y_max) VALUES
('결제 구역',    -0.10,  0.40, -1.70, -1.20),
('맵 외곽 경계', -0.20,  1.35, -1.80,  0.20)
ON CONFLICT (description) DO UPDATE SET
    x_min = EXCLUDED.x_min,
    x_max = EXCLUDED.x_max,
    y_min = EXCLUDED.y_min,
    y_max = EXCLUDED.y_max;

-- ROBOT (active_user_id NULL — users 나중에 삽입)
INSERT INTO robot (robot_id, ip_address, current_mode) VALUES
('54', '192.168.102.54', 'CHARGING'),
('18', '192.168.102.18', 'CHARGING')
ON CONFLICT (robot_id) DO UPDATE SET
    ip_address   = EXCLUDED.ip_address,
    current_mode = EXCLUDED.current_mode;

-- users (customer_web 데모: test01/test02 비밀번호 1234)
INSERT INTO users (user_id, password_hash) VALUES
('test01', '$2b$12$6n0jg8wVxTMyXXqw0dksG.GukfhfTZis31aqnEDjsTmn8FxJ3.UDi'),
('test02', '$2b$12$6n0jg8wVxTMyXXqw0dksG.GukfhfTZis31aqnEDjsTmn8FxJ3.UDi')
ON CONFLICT (user_id) DO UPDATE SET
    password_hash = EXCLUDED.password_hash;

INSERT INTO card (user_id, card_alias) VALUES
('test01', '신한카드 1234'),
('test02', '국민카드 5678')
ON CONFLICT (user_id, card_alias) DO NOTHING;

-- FLEET_WAYPOINT (shop_nav_graph.yaml 28개 버텍스)
INSERT INTO fleet_waypoint (idx, name, x, y, theta, zone_id, is_charger, is_parking, pickup_zone, holding_point) VALUES
-- 왼쪽 복도 (x=0.0)
( 0, '입구1',          0.0,   -0.007, 0,       110,  false, false, false, false),
( 1, '입구2',          0.0,   -0.300, 0,       NULL, false, false, false, false),
( 2, 'P1',             0.0,   -0.606, 3.1416,  140,  true,  true,  false, false),  -- 서쪽(-x)
( 3, 'P2',             0.0,   -0.899, 3.1416,  141,  true,  true,  false, false),  -- 서쪽(-x)
( 4, '출구2',          0.0,   -1.402, 0,       NULL, false, false, false, false),
( 5, '출구1',          0.0,   -1.597, 0,       120,  false, false, false, false),
-- 위쪽 복도 (y=-0.007)
( 6, '가전제품1',      0.489, -0.007, -1.5708, 1,    false, false, true,  false),
( 7, '가전제품2',      0.749, -0.007, -1.5708, 1,    false, false, true,  false),
( 8, '과자1',          0.950, -0.007, -1.5708, 2,    false, false, true,  false),
( 9, '과자_해산물',    1.151, -0.007, 0,       NULL, false, false, false, false),
-- 오른쪽 복도 (x=1.151)
(10, '해산물2',        1.151, -0.300, 3.1416,  3,    false, false, true,  false),  -- 서쪽(-x)
(11, '육류1',          1.151, -0.606, 3.1416,  4,    false, false, true,  false),  -- 서쪽(-x)
(12, '육류2',          1.151, -0.899, 3.1416,  4,    false, false, true,  false),  -- 서쪽(-x)
(13, '채소1',          1.151, -1.224, 3.1416,  5,    false, false, true,  false),  -- 서쪽(-x)
(14, '채소_화장실',    1.151, -1.586, 0,       NULL, false, false, false, false),
-- 아래쪽 복도
(15, '화장실2',        0.812, -1.586, 1.5708,  100,  false, false, true,  false),  -- 북쪽(+y)
(16, '결제구역1',      0.186, -1.594, 0,       150,  false, false, false, true),
(17, '결제구역2',      0.183, -1.402, 0,       150,  false, false, false, true),
-- 내부 1열 (y=-0.300)
(18, '빵1',            0.494, -0.300, 1.5708,  7,    false, false, true,  false),  -- 북쪽(+y)
(19, '빵2',            0.749, -0.300, 1.5708,  7,    false, false, true,  false),  -- 북쪽(+y)
-- 내부 2열 (y=-0.606)
(20, '가공식품1',      0.749, -0.606, -1.5708, 8,    false, false, true,  false),
(21, '가공식품2',      0.494, -0.606, -1.5708, 8,    false, false, true,  false),
-- 내부 3열 (y=-0.899)
(22, '음료1',          0.749, -0.899, 1.5708,  6,    false, false, true,  false),  -- 북쪽(+y)
(23, '음료2',          0.749, -1.224, -1.5708, 6,    false, false, true,  false),  -- 남쪽(-y)
-- 통로 waypoint
(24, '로비',            0.245, -0.007, 0,       NULL, false, false, false, false),
(25, '1열_입구',        0.245, -0.300, 0,       NULL, false, false, false, false),
(26, '2열_입구',        0.245, -0.606, 0,       NULL, false, false, false, false),
(27, '3열_입구',        0.245, -0.899, 0,       NULL, false, false, false, false),
(28, '1열_출구',        0.950, -0.300, 0,       NULL, false, false, false, false),
(29, '2열_출구',        0.950, -0.606, 0,       NULL, false, false, false, false),
(30, '3열_출구',        0.950, -0.899, 0,       NULL, false, false, false, false),
(31, '4열_중간',        0.950, -1.224, 0,       NULL, false, false, false, false),
(32, '3열_중간',        0.494, -0.899, 0,       NULL, false, false, false, false),
(33, '4열_입구',        0.494, -1.224, 0,       NULL, false, false, false, false),
(34, '하단_중간',       0.494, -1.137, 0,       NULL, false, false, false, false),
(35, '하단_입구',       0.245, -1.137, 0,       NULL, false, false, false, false),
(36, '하단_복도',       0.0,   -1.137, 0,       NULL, false, false, false, false),
(37, '결제구역2_입구',  0.494, -1.402, 0,       NULL, false, false, false, false),
(38, '결제구역1_입구',  0.494, -1.590, 0,       NULL, false, false, false, false)
ON CONFLICT (idx) DO UPDATE SET
    name          = EXCLUDED.name,
    x             = EXCLUDED.x,
    y             = EXCLUDED.y,
    theta         = EXCLUDED.theta,
    zone_id       = EXCLUDED.zone_id,
    is_charger    = EXCLUDED.is_charger,
    is_parking    = EXCLUDED.is_parking,
    pickup_zone   = EXCLUDED.pickup_zone,
    holding_point = EXCLUDED.holding_point;

-- FLEET_LANE (shop_nav_graph.yaml 레인 — 단방향 쌍)
INSERT INTO fleet_lane (from_idx, to_idx) VALUES
-- 외곽 루프 — 왼쪽 복도
(0,1),(1,0),(2,3),(3,2),(36,4),(4,36),(4,5),(5,4),
-- 외곽 루프 — 위쪽 복도
(0,24),(24,0),(24,6),(6,24),(6,7),(7,6),(7,8),(8,7),(8,9),(9,8),
-- 외곽 루프 — 오른쪽 복도
(9,10),(10,9),(10,11),(11,10),(11,12),(12,11),(12,13),(13,12),(13,14),(14,13),
-- 외곽 루프 — 아래쪽 복도
(14,15),(15,14),(15,38),(38,15),(38,16),(16,38),(16,5),(5,16),
-- 하단_출구↔결제_입구 수직
(37,38),(38,37),
-- 내부 1열 (y=-0.300)
(1,25),(25,1),(25,18),(18,25),(18,19),(19,18),(19,28),(28,19),(28,10),(10,28),
-- 내부 2열 (y=-0.606)
(2,26),(26,2),(26,21),(21,26),(21,20),(20,21),(20,29),(29,20),(29,11),(11,29),
-- 내부 3열 (y=-0.899)
(3,27),(27,3),(27,32),(32,27),(32,22),(22,32),(22,30),(30,22),(30,12),(12,30),
-- 내부 4열 (y=-1.224)
(23,33),(33,23),(33,31),(31,33),(31,13),(13,31),
-- 수직 통로 중 (가공식품2↔3열↔하단↔4열)
(21,32),(32,21),(32,34),(34,32),(34,33),(33,34),
-- 하단 수평 (하단_복도↔하단_입구↔하단_중간)
(36,35),(35,36),(35,34),(34,35),
-- 하단_입구↔3열_입구 수직
(27,35),(35,27),
-- 수직 통로 좌 (로비↔1열↔2열↔3열)
(24,25),(25,24),(25,26),(26,25),(26,27),(27,26),
-- 수직 통로 우 (과자1↔1열↔2열↔3열↔4열)
(8,28),(28,8),(28,29),(29,28),(29,30),(30,29),(30,31),(31,30),
-- y=-1.402
(4,17),(17,4),(33,37),(37,33),(37,17),(17,37),
-- 6↔18 수직 연결
(6,18),(18,6),
-- 7↔19 수직, 20↔22 수직
(7,19),(19,7),(20,22),(22,20),
-- 음료2 → 화장실2
(23,15),(15,23),
-- 결제구역 수직 연결
(16,17),(17,16)
ON CONFLICT (from_idx, to_idx) DO NOTHING;
