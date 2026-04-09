"""Global constants for ShopPinkki.

All tuneable parameters are centralised here.
Edit this file to change robot behaviour without touching logic code.
"""

# ── P-Control (tracking) ──────────────────────
TARGET_AREA: int = 40000      # target bbox area (px²) — sets follow distance
IMAGE_WIDTH: int = 640        # camera horizontal resolution (px)
KP_ANGLE: float = 0.002       # proportional gain for angular velocity
KP_DIST: float = 0.0001       # proportional gain for linear velocity (per px²)

# ── Velocity limits ───────────────────────────
LINEAR_X_MAX: float = 0.3     # max linear  velocity (m/s)
ANGULAR_Z_MAX: float = 1.0    # max angular velocity (rad/s)

# ── Obstacle avoidance (LiDAR) ────────────────
MIN_DIST: float = 0.25        # min obstacle distance before stopping (m)

# ── State machine timeouts ────────────────────
N_MISS_FRAMES: int = 30       # consecutive miss frames before SEARCHING
SEARCH_TIMEOUT: float = 30.0  # SEARCHING → WAITING timeout (s)
WAITING_TIMEOUT: int = 300    # WAITING  → RETURNING timeout (s)

# ── Battery ───────────────────────────────────
BATTERY_THRESHOLD: int = 20          # battery % below which HALTED triggers
                                     # (raise to 90 for bench testing)
CHARGING_COMPLETE_THRESHOLD: int = 80  # battery % above which CHARGING → IDLE

# ── Charger zone IDs (DB zone 테이블 참조) ─────────
# robot_id → zone_id  (seed_data.sql 기준)
# 실제 좌표는 시작 시 /zones fetch 캐시(self._zones)에서 가져온다
CHARGER_ZONE_IDS: dict[str, int] = {
    '54': 141,   # 충전소_54(P2)
    '18': 140,   # 충전소_18(P1)
}

# ── Robot connectivity ────────────────────────
ROBOT_TIMEOUT_SEC: int = 30   # seconds without /status → OFFLINE

# ── Session ───────────────────────────────────
SESSION_DURATION_HOURS: int = 4   # session expires_at = now + 4h
