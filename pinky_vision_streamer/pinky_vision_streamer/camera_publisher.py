#!/usr/bin/env python3
"""
camera_publisher.py
핑키(라즈베리파이) 전용 카메라 스트리밍 노드

무거운 AI 연산 없이 순수하게 카메라 프레임만 읽어서 
PC쪽 트래커 노드로 CompressedImage 형태로 전달합니다.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2
import numpy as np
from pinkylib import Camera  # 핑키 하드웨어 전용 라이브러리


class CameraPublisherNode(Node):
    def __init__(self):
        super().__init__('camera_publisher_node')
        
        # JPEG 압축 화질 파라미터 (네트워크 속도 고려)
        self.declare_parameter('jpeg_quality', 80)
        
        # 영상 퍼블리셔 (CompressedImage)
        self.publisher_ = self.create_publisher(
            CompressedImage, 
            '/pinky/camera/compressed', 
            1)
            
        try:
            self.camera = Camera()
            self.camera.start()
            self.get_logger().info("✅ pinkylib.Camera 초기화 및 시작 성공")
        except Exception as e:
            self.get_logger().error(f"❌ 카메라 초기화 실패: {e}")
            raise e

        # 15 FPS로 프레임 퍼블리시
        timer_period = 1.0 / 15.0  
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.get_logger().info("📷 카메라 퍼블리셔 시작 (15 FPS 스트리밍 시작!)")

    def timer_callback(self):
        try:
            # 1. 핑키 카메라 프레임 읽기 (V4L2)
            frame = self.camera.get_frame()
            if frame is None:
                self.get_logger().warning("⚠️ 핑키 카메라 프레임을 읽지 못했습니다.")
                return

            # 2. JPEG로 압축하기
            quality = self.get_parameter('jpeg_quality').value
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            success, encoded_image = cv2.imencode('.jpg', frame, encode_param)

            if not success:
                self.get_logger().warning("⚠️ JPEG 압축에 실패했습니다.")
                return

            # 3. CompressedImage 메시지로 변환 후 퍼블리시
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = 'camera_link'
            msg.format = 'jpeg'
            msg.data = np.array(encoded_image).tobytes()

            self.publisher_.publish(msg)
            
        except Exception as e:
            self.get_logger().error(f"프레임 전송 에러: {e}")


def main(args=None):
    rclpy.init(args=args)
    node = CameraPublisherNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("카메라 퍼블리셔를 종료합니다.")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
