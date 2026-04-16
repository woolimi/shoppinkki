"""Global constants for ShopPinkki.

All tuneable parameters are centralised here.
Edit this file to change robot behaviour without touching logic code.

WAITING timeout (single source of truth)
----------------------------------------
``WAITING_TIMEOUT`` (seconds) drives:
  - BT3 ``WaitAndAvoid`` timeout (``shoppinkki_nav.bt_waiting`` imports this module),
  - ``/robot_<id>/status`` JSON field ``waiting_timeout_sec``,
  - ``control_service`` RobotState default until the first status arrives,
  - ``customer_web`` initial countdown (import, or parse this file if the package is not on ``PYTHONPATH``).

Change **only** ``WAITING_TIMEOUT`` here to retune everywhere that reads it.
"""

# ── P-Control (tracking) ──────────────────────
TARGET_SIZE: float = 360.0    # Backed off slightly for better camera visibility
IMAGE_WIDTH: int = 640        # camera horizontal resolution (px)
KP_ANGLE: float = 0.0010      # Very gentle turning to stop "skiing"
KI_ANGLE: float = 0.0
KD_ANGLE: float = 0.0
ANGLE_DEADZONE: float = 45.0  # (px) Don't turn if doll is near center

KP_DIST: float = 0.0030       # Smooth approach
KI_DIST: float = 0.0001
KD_DIST: float = 0.0

# ── Velocity limits ───────────────────────────
LINEAR_X_MAX: float = 0.12    # max linear  velocity (m/s)
ANGULAR_Z_MAX: float = 0.60   # Lowered to 0.60 to prevent overshooting turns

# ── Obstacle avoidance (LiDAR) ────────────────
MIN_DIST: float = 0.25        # min obstacle distance before stopping (m)

# ── State machine timeouts ────────────────────
N_MISS_FRAMES: int = 16       # tolerate brief close-range occlusions before SEARCHING
SEARCH_TIMEOUT: float = 30.0  # SEARCHING → WAITING timeout (s)
WAITING_TIMEOUT: int = 5      # WAITING timeout for test (restore to 300 for production)

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
