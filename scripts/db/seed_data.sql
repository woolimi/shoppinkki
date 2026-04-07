-- ShopPinkki Seed Data
USE shoppinkki;

-- ──────────────────────────────────────────────
-- ZONE (상품 구역 1~8, 특수 구역)
-- ──────────────────────────────────────────────

-- 좌표 기준: shop_nav_graph.yaml (그리드 정렬 적용, 2026-04-07)
INSERT INTO ZONE (zone_id, zone_name, zone_type, waypoint_x, waypoint_y, waypoint_theta) VALUES
-- 상품 구역
(1,   '가전제품',  'product',  0.619, -0.007,  0.0),     -- 가전제품1(0.489)·2(0.749) 중간
(2,   '과자',     'product',  0.950, -0.007,  0.0),     -- 과자1 (노드 8)
(3,   '해산물',   'product',  1.151, -0.300,  3.1416),  -- 해산물2 (노드 10)
(4,   '육류',     'product',  1.151, -0.752,  3.1416),  -- 육류1(−0.606)·2(−0.899) 중간
(5,   '채소',     'product',  1.151, -1.224,  3.1416),  -- 채소1 (노드 13)
(6,   '음료',     'product',  0.704, -0.899,  0.0),     -- 음료1 (노드 22)
(7,   '베이커리', 'product',  0.622, -0.300,  0.0),     -- 빵1(0.494)·2(0.749) 중간
(8,   '음식',     'product',  0.624, -0.606,  0.0),     -- 가공식품1(0.774)·2(0.473) 중간
-- 특수 구역
(100, '화장실',   'special',  0.812, -1.606,  1.5708),  -- 화장실2 (노드 15)
(110, '입구',     'special', -0.056, -0.007,  0.0),     -- 입구1 (노드 0)
(120, '출구',     'special', -0.056, -1.617,  0.0),     -- 출구1 (노드 5)
(140, '충전소 P1','special', -0.056, -0.606,  1.5708),  -- P1 (노드 2, 북향)
(141, '충전소 P2','special', -0.056, -0.899,  1.5708),  -- P2 (노드 3, 북향)
(150, '결제 구역','special',  0.186, -1.614,  1.5708)   -- 결제구역1 (노드 16)
ON DUPLICATE KEY UPDATE
  waypoint_x=VALUES(waypoint_x),
  waypoint_y=VALUES(waypoint_y),
  waypoint_theta=VALUES(waypoint_theta),
  zone_name=VALUES(zone_name);

-- ──────────────────────────────────────────────
-- PRODUCT
-- ──────────────────────────────────────────────

INSERT INTO PRODUCT (product_name, zone_id) VALUES
('TV',       1), ('냉장고',  1), ('에어컨', 1),
('쌀과자',   2), ('포카칩',  2), ('오레오', 2),
('연어',     3), ('새우',    3), ('오징어', 3),
('소고기',   4), ('돼지고기',4), ('닭고기', 4),
('당근',     5), ('브로콜리',5), ('상추',   5),
('콜라',     6), ('커피',    6), ('오렌지주스', 6),
('식빵',     7), ('크루아상',7), ('머핀',   7),
('볶음밥',   8), ('라면',    8), ('떡볶이', 8)
ON DUPLICATE KEY UPDATE zone_id=VALUES(zone_id);

-- ──────────────────────────────────────────────
-- BOUNDARY_CONFIG
-- ──────────────────────────────────────────────

-- 결제구역: 결제구역1(0.186,-1.614) · 결제구역2(0.183,-1.364) 기준 + 여유
-- 맵외곽: origin(-0.183,-1.773) + 149×195px×0.01 = x[−0.18,1.31] y[−1.77,0.18] + 여유
INSERT INTO BOUNDARY_CONFIG (description, x_min, x_max, y_min, y_max) VALUES
('결제 구역',    -0.10,  0.40, -1.70, -1.20),
('맵 외곽 경계', -0.20,  1.35, -1.80,  0.20)
ON DUPLICATE KEY UPDATE
  x_min=VALUES(x_min), x_max=VALUES(x_max),
  y_min=VALUES(y_min), y_max=VALUES(y_max);

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
