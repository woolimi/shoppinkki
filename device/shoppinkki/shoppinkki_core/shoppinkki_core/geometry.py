"""기하 변환 헬퍼.

Z축 회전만 사용하는 모바일 로봇이라 평면 yaw ↔ 단위 쿼터니언 변환만 필요하다.
``tf_transformations`` 의존성을 피하기 위해 inline 수식을 사용한다.
"""

from __future__ import annotations

import math


def yaw_to_quat(theta: float) -> tuple[float, float, float, float]:
    """yaw(rad) → (qx, qy, qz, qw). Z축 회전만 있는 단위 쿼터니언."""
    return (0.0, 0.0, math.sin(theta / 2.0), math.cos(theta / 2.0))


def quat_to_yaw(qx: float, qy: float, qz: float, qw: float) -> float:
    """단위 쿼터니언에서 yaw(rad)만 추출. Z축 회전 가정."""
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)
