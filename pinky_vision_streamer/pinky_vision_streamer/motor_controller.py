#!/usr/bin/env python3
"""
motor_controller.py
핑키의 몸통 회전 전용(Rotation Only) 모터 제어 노드.
PC의 서버 트래커가 보내는 주인의 좌/우 중심 좌표를 받아,
카메라 시야 정중앙(0.5)에 오도록 회전(Angular Z) 속도만 퍼블리시합니다.
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point, Twist

class MotorControllerNode(Node):
    def __init__(self):
        super().__init__('motor_controller')

        # 회전(Rotation) 파라미터
        self.declare_parameter('kp_z', 2.0)
        self.declare_parameter('deadzone_z', 0.1) # 좌우 10% 이내면 정지
        
        # 직진(Follow) 파라미터
        self.declare_parameter('enable_follow', False) # 너무 위험할 수 있으니 기본 OFF
        self.declare_parameter('kp_x', 1.5)            # 전진/후진 비례상수
        self.declare_parameter('target_ratio', 0.5)    # 주인이 카메라 세로 길이의 50%를 차지할 때의 거리를 유지
        self.declare_parameter('deadzone_x', 0.05)     # 비율 5% 차이는 무시

        self.declare_parameter('timeout_sec', 0.5) # 타겟 소실 시 정지

        self.sub_target = self.create_subscription(
            Point, '/tracker/target_position', self._cb_target, 10)
        self.pub_cmd_vel = self.create_publisher(Twist, '/cmd_vel', 10)

        timeout = self.get_parameter('timeout_sec').value
        self.timer = self.create_timer(timeout, self._cb_timeout)
        self.last_target_time = self.get_clock().now()

        self.get_logger().info("🚀 모터 제어 노드 시작 (제자리 회전 ON, 전진/후진 OFF)")

    def _cb_target(self, msg):
        self.last_target_time = self.get_clock().now()
        
        twist = Twist()

        # --- 1. 좌/우 제자리 회전 (Rotation) 제어 ---
        error_z = 0.5 - float(msg.x)
        kp_z = self.get_parameter('kp_z').value
        deadzone_z = self.get_parameter('deadzone_z').value

        if abs(error_z) > deadzone_z:
            twist.angular.z = error_z * kp_z
        else:
            twist.angular.z = 0.0

        # --- 2. 전/후진 거리 유지 제어 (Follow) ---
        enable_follow = self.get_parameter('enable_follow').value
        target_ratio = self.get_parameter('target_ratio').value
        kp_x = self.get_parameter('kp_x').value
        deadzone_x = self.get_parameter('deadzone_x').value
        
        # msg.z는 목표의 Bounding Box 세로가 화면 높이에서 차지하는 비율
        # error_x가 양수(목표비율보다 작음, 멀리있음)면 전진, 음수면 후진
        error_x = target_ratio - float(msg.z)

        if enable_follow:
            if abs(error_x) > deadzone_x:
                twist.linear.x = error_x * kp_x
            else:
                twist.linear.x = 0.0
        else:
            twist.linear.x = 0.0

        self.pub_cmd_vel.publish(twist)

    def _cb_timeout(self):
        # 마지막 타겟 수신 후 timeout 초가 지났으면 정지
        elapsed = (self.get_clock().now() - self.last_target_time).nanoseconds / 1e9
        if elapsed > self.get_parameter('timeout_sec').value:
            # 정지 명령 퍼블리시
            self.pub_cmd_vel.publish(Twist())

def main(args=None):
    rclpy.init(args=args)
    node = MotorControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 종료 시 무조건 로봇 정지
        node.pub_cmd_vel.publish(Twist())
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
