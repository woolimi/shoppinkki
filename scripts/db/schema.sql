-- ShopPinkki Central DB Schema
-- MySQL 8.x  |  Database: shoppinkki

CREATE DATABASE IF NOT EXISTS shoppinkki
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE shoppinkki;

-- ──────────────────────────────────────────────
-- 사용자 / 카드
-- ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS USER (
    user_id       VARCHAR(50)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS CARD (
    card_id    INT          NOT NULL AUTO_INCREMENT,
    user_id    VARCHAR(50)  NOT NULL,
    card_alias VARCHAR(50)  NOT NULL DEFAULT '기본 카드',
    PRIMARY KEY (card_id),
    FOREIGN KEY (user_id) REFERENCES USER(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ──────────────────────────────────────────────
-- 구역 / 상품
-- ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ZONE (
    zone_id      INT          NOT NULL,
    zone_name    VARCHAR(100) NOT NULL,
    zone_type    VARCHAR(20)  NOT NULL COMMENT 'product | special',
    waypoint_x   DOUBLE       NOT NULL DEFAULT 0.0,
    waypoint_y   DOUBLE       NOT NULL DEFAULT 0.0,
    waypoint_theta DOUBLE     NOT NULL DEFAULT 0.0,
    PRIMARY KEY (zone_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS PRODUCT (
    product_id   INT          NOT NULL AUTO_INCREMENT,
    product_name VARCHAR(100) NOT NULL,
    zone_id      INT          NOT NULL,
    PRIMARY KEY (product_id),
    FOREIGN KEY (zone_id) REFERENCES ZONE(zone_id)
) ENGINE=InnoDB;

-- ──────────────────────────────────────────────
-- 경계 설정
-- ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS BOUNDARY_CONFIG (
    id          INT          NOT NULL AUTO_INCREMENT,
    description VARCHAR(100) NOT NULL,
    x_min       DOUBLE       NOT NULL,
    x_max       DOUBLE       NOT NULL,
    y_min       DOUBLE       NOT NULL,
    y_max       DOUBLE       NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB;

-- ──────────────────────────────────────────────
-- 로봇
-- ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ROBOT (
    robot_id        VARCHAR(10)  NOT NULL,
    ip_address      VARCHAR(15)  NOT NULL,
    current_mode    VARCHAR(30)  NOT NULL DEFAULT 'OFFLINE'
        COMMENT 'CHARGING|IDLE|TRACKING|TRACKING_CHECKOUT|GUIDING|SEARCHING|WAITING|LOCKED|RETURNING|HALTED|OFFLINE',
    pos_x           DOUBLE       NOT NULL DEFAULT 0.0,
    pos_y           DOUBLE       NOT NULL DEFAULT 0.0,
    battery_level   INT          NOT NULL DEFAULT 100,
    last_seen       DATETIME     NULL,
    active_user_id  VARCHAR(50)  NULL,
    is_locked_return TINYINT(1)  NOT NULL DEFAULT 0,
    PRIMARY KEY (robot_id),
    FOREIGN KEY (active_user_id) REFERENCES USER(user_id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ──────────────────────────────────────────────
-- 직원 호출 로그
-- ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS STAFF_CALL_LOG (
    log_id      INT          NOT NULL AUTO_INCREMENT,
    robot_id    VARCHAR(10)  NOT NULL,
    user_id     VARCHAR(50)  NULL,
    event_type  VARCHAR(20)  NOT NULL COMMENT 'LOCKED|HALTED',
    occurred_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME     NULL COMMENT 'NULL = 미처리',
    PRIMARY KEY (log_id),
    FOREIGN KEY (robot_id) REFERENCES ROBOT(robot_id)
) ENGINE=InnoDB;

-- ──────────────────────────────────────────────
-- 이벤트 로그
-- ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS EVENT_LOG (
    event_id     INT          NOT NULL AUTO_INCREMENT,
    robot_id     VARCHAR(10)  NOT NULL,
    user_id      VARCHAR(50)  NULL,
    event_type   VARCHAR(30)  NOT NULL
        COMMENT 'SESSION_START|SESSION_END|FORCE_TERMINATE|LOCKED|HALTED|STAFF_RESOLVED|PAYMENT_SUCCESS|MODE_CHANGE|OFFLINE|ONLINE',
    event_detail TEXT         NULL,
    occurred_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (event_id),
    FOREIGN KEY (robot_id) REFERENCES ROBOT(robot_id)
) ENGINE=InnoDB;

-- ──────────────────────────────────────────────
-- 세션 / 장바구니
-- ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS SESSION (
    session_id  INT          NOT NULL AUTO_INCREMENT,
    robot_id    VARCHAR(10)  NOT NULL,
    user_id     VARCHAR(50)  NOT NULL,
    is_active   TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at  DATETIME     NOT NULL,
    PRIMARY KEY (session_id),
    FOREIGN KEY (robot_id) REFERENCES ROBOT(robot_id),
    FOREIGN KEY (user_id)  REFERENCES USER(user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS CART (
    cart_id    INT NOT NULL AUTO_INCREMENT,
    session_id INT NOT NULL,
    PRIMARY KEY (cart_id),
    FOREIGN KEY (session_id) REFERENCES SESSION(session_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS CART_ITEM (
    item_id      INT          NOT NULL AUTO_INCREMENT,
    cart_id      INT          NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    price        INT          NOT NULL DEFAULT 0,
    scanned_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_paid      TINYINT(1)   NOT NULL DEFAULT 0,
    PRIMARY KEY (item_id),
    FOREIGN KEY (cart_id) REFERENCES CART(cart_id) ON DELETE CASCADE
) ENGINE=InnoDB;
