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
MIN_DIST: float = 0.20        # lowered for more freedom during search (0.25 -> 0.20)
AVOID_DIST: float = 0.40      # start "shying away" from side obstacles (m)
AVOID_KP: float = 0.50        # avoidance steering strength

# ── State machine timeouts ────────────────────
N_MISS_FRAMES: int = 40       # tolerate brief close-range occlusions before SEARCHING
SEARCH_TIMEOUT: float = 600.0 # SEARCHING → WAITING timeout (s)
SEARCH_MIN_DURATION: float = 3.0  # Increased to 3.0 to force longer search turns
WAITING_TIMEOUT: int = 300  # WAITING  → RETURNING timeout (s) — 5분

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


# ── 상태/모드 문자열 상수 ─────────────────────
# SM과 UI/control_service가 공유하는 모드 문자열의 single source of truth.
# 값은 기존 문자열을 그대로 두어 backward-compatible. 비교 시 typo를 방지하고
# grep/IDE 자동완성을 가능하게 한다.
class RobotMode:
    OFFLINE = 'OFFLINE'
    IDLE = 'IDLE'
    CHARGING = 'CHARGING'
    TRACKING = 'TRACKING'
    TRACKING_CHECKOUT = 'TRACKING_CHECKOUT'
    SEARCHING = 'SEARCHING'
    WAITING = 'WAITING'
    GUIDING = 'GUIDING'
    RETURNING = 'RETURNING'
    LOCKED = 'LOCKED'
    HALTED = 'HALTED'


# 카메라 피드를 LCD에 그릴 수 있는 상태들 (vision_manager).
CAMERA_ACTIVE_MODES: frozenset[str] = frozenset({
    RobotMode.IDLE, RobotMode.TRACKING,
    RobotMode.TRACKING_CHECKOUT, RobotMode.SEARCHING,
})

# RETURNING 자동 전이를 트리거할 수 있는 상태들 (robot_manager checkout_zone_enter).
CHECKOUT_AUTO_RETURN_FROM: frozenset[str] = frozenset({
    RobotMode.TRACKING, RobotMode.TRACKING_CHECKOUT,
})
