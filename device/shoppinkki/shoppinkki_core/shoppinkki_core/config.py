"""Global constants for ShopPinkki.

All tuneable parameters are centralised here.
Edit this file to change robot behaviour without touching logic code.
"""

# ── P-Control (tracking) ──────────────────────
TARGET_SIZE: float = 220.0    # stop farther from owner to reduce close-range loss
IMAGE_WIDTH: int = 640        # camera horizontal resolution (px)
KP_ANGLE: float = 0.002       # proportional gain for angular velocity
KP_DIST: float = 0.0015       # proportional gain for linear velocity (per px) (Reduced for smooth accel)

# ── Velocity limits ───────────────────────────
LINEAR_X_MAX: float = 0.12    # max linear  velocity (m/s) — (Reduced for safety)
ANGULAR_Z_MAX: float = 1.0    # max angular velocity (rad/s)

# ── Obstacle avoidance (LiDAR) ────────────────
MIN_DIST: float = 0.25        # min obstacle distance before stopping (m)

# ── State machine timeouts ────────────────────
N_MISS_FRAMES: int = 16       # tolerate brief close-range occlusions before SEARCHING
SEARCH_TIMEOUT: float = 30.0  # SEARCHING → WAITING timeout (s)
WAITING_TIMEOUT: int = 300    # WAITING  → RETURNING timeout (s)

# ── Battery ───────────────────────────────────
BATTERY_THRESHOLD: int = 20          # battery % below which HALTED triggers
                                     # (raise to 90 for bench testing)
CHARGING_COMPLETE_THRESHOLD: int = 80  # battery % above which CHARGING → IDLE

# ── Charger zone IDs (DB zone 테이블 참조) ─────────
# robot_id → zone_id  (seed_data.sql 기준)
CHARGER_ZONE_IDS: dict[str, int] = {
    '11': 140,   # 충전소_11(P1)
    '54': 141,   # 충전소_54(P2)
    '18': 140,   # 충전소_18(P1)
}

# ── Robot connectivity ────────────────────────
ROBOT_TIMEOUT_SEC: int = 30   # seconds without /status → OFFLINE

# ── Session ───────────────────────────────────
SESSION_DURATION_HOURS: int = 4   # session expires_at = now + 4h
