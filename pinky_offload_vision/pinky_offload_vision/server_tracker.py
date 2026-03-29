#!/usr/bin/env python3
"""
server_tracker.py
PC용 오프로딩 트래커 노드 (YOLOv8 + ByteTrack + ReID + MediaPipe)

핑키가 보낸 `/pinky/camera/compressed`를 받아 AI 연산을 수행한 뒤,
결과 영상(`.debug_image`)과 추적 좌표(`.target_position`)를 생성.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from geometry_msgs.msg import Point
from std_msgs.msg import String

import cv2
import numpy as np
from ultralytics import YOLO
import math

from .common.feature_extractor import extract_features, compare_features
from .common.calibrator import Calibrator


class ServerTrackerNode(Node):
    def __init__(self):
        super().__init__('server_tracker_node')

        self.declare_parameter('imgsz', 640)
        self.declare_parameter('reid_threshold', 0.55)
        self.declare_parameter('tracking_threshold', 0.45)
        self.declare_parameter('reid_confirm_frames', 3)
        self.declare_parameter('jpeg_quality', 80)

        # 수신 (핑키 카메라)
        self.sub_image = self.create_subscription(
            CompressedImage, '/pinky/camera/compressed', self._cb_image, 1)

        # 토픽 명령 수신 (웹 대시보드 명령)
        self.sub_cmd = self.create_subscription(
            String, '/tracker/command', self._cb_command, 10)

        # 퍼블리시
        self.pub_target = self.create_publisher(Point, '/tracker/target_position', 10)
        self.pub_debug = self.create_publisher(CompressedImage, '/tracker/debug_image/compressed', 1)

        self.get_logger().info("🧠 YOLOv8n 모델 로드 중... (PC GPU 최적화 권장)")
        self.model = YOLO("yolov8n.pt")
        self.get_logger().info("✅ YOLO 모델 로드 완료")

        self.calibrator = Calibrator()

        self.owner_locked = self.calibrator.is_owner_registered
        self.prime_owner_id = None
        self.owner_lost_frames = 0
        self.reid_candidate_id = None
        self.reid_valid_count = 0

        self.get_logger().info("🖥️ 서버 트래커 대기 중...")

    def _cb_command(self, msg):
        cmd = msg.data.strip().lower()
        if cmd == 'calibrate':
            self.calibrator.start()
            self.owner_locked = False
            self.prime_owner_id = None
            self.get_logger().info("🎬 [토픽] 캘리브레이션 시작")
        elif cmd == 'clear':
            self.calibrator.clear()
            self.owner_locked = False
            self.prime_owner_id = None
            self.reid_candidate_id = None
            self.reid_valid_count = 0
            self.get_logger().info("🗑️ [토픽] 소유자 초기화")

    def _cb_image(self, msg):
        # 1. 압축 해제
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            return

        # 2. YOLO 추론 (사람 0번 클래스만)
        imgsz = self.get_parameter('imgsz').value
        results = self.model.track(
            frame, persist=True, classes=[0],
            tracker="bytetrack.yaml", verbose=False, imgsz=imgsz
        )
        
        annotated_frame = results[0].plot()

        bboxes = results[0].boxes.xyxy.cpu().numpy()
        ids = results[0].boxes.id.cpu().numpy() if results[0].boxes.id is not None else []
        confidences = results[0].boxes.conf.cpu().numpy()
        
        tracking_candidates = []
        for i, box in enumerate(bboxes):
            if i >= len(ids): continue
            cls_conf = confidences[i]
            if cls_conf < self.get_parameter('tracking_threshold').value:
                continue

            track_id = int(ids[i])
            feat = extract_features(frame, box)
            
            x_center = (box[0] + box[2]) / 2
            y_center = (box[1] + box[3]) / 2
            
            # 중앙 좌표 기준 거리
            h, w = frame.shape[:2]
            dist_to_center = math.hypot(x_center - w/2, y_center - h/2)

            tracking_candidates.append({
                'id': track_id, 'box': box, 'features': feat,
                'center': (x_center, y_center), 'dist': dist_to_center
            })

        # 면적/거리 기준으로 제일 좋은 1명 선택
        best_person = None
        if tracking_candidates:
            best_person = min(tracking_candidates, key=lambda x: x['dist'])

        # 3. 캘리브레이션 모드 진행
        if self.calibrator.is_calibrating:
            if best_person:
                self.calibrator.process_best_person(annotated_frame, best_person)
            else:
                self.calibrator._message = "캘리브레이션 대상을 찾지 못했습니다."
            
            self.calibrator.draw_progress(annotated_frame)
            self._publish_debug(annotated_frame)
            return

        # 4. 소유자 등록 안됨
        if not self.calibrator.is_owner_registered:
            cv2.putText(annotated_frame, "[NO OWNER] Press Calibrate", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)
            self._publish_debug(annotated_frame)
            return

        # 5. 소유자 추적 로직 (ReID & Tracking)
        owner_found = False
        reid_threshold = self.get_parameter('reid_threshold').value
        conf_frames = self.get_parameter('reid_confirm_frames').value

        if self.prime_owner_id is not None:
            for p in tracking_candidates:
                if p['id'] == self.prime_owner_id:
                    owner_found = True
                    self._draw_and_publish(annotated_frame, p, "[OWNER]")
                    break

        if not owner_found:
            self.owner_lost_frames += 1
            if self.owner_lost_frames > 30:
                self.prime_owner_id = None
                
            best_match_id = None
            best_score = 100.0
            best_p = None
            
            for p in tracking_candidates:
                scores = [compare_features(p['features'], t) for t in self.calibrator.owner_templates]
                min_score = min(scores) if scores else 100.0
                if min_score < reid_threshold and min_score < best_score:
                    best_score = min_score
                    best_match_id = p['id']
                    best_p = p
                    
            if best_match_id is not None:
                if best_match_id == self.reid_candidate_id:
                    self.reid_valid_count += 1
                    if self.reid_valid_count >= conf_frames:
                        self.prime_owner_id = best_match_id
                        self.owner_lost_frames = 0
                        self.reid_candidate_id = None
                        self.reid_valid_count = 0
                        owner_found = True
                        self._draw_and_publish(annotated_frame, best_p, "[RE-IDENTIFIED]")
                else:
                    self.reid_candidate_id = best_match_id
                    self.reid_valid_count = 1
            else:
                self.reid_valid_count = 0
                self.reid_candidate_id = None

        if not owner_found:
            cv2.putText(annotated_frame, "Searching Owner...", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,165,255), 2)

        self._publish_debug(annotated_frame)

    def _draw_and_publish(self, frame, person, label):
        x1, y1, x2, y2 = map(int, person['box'])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)
        cv2.putText(frame, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        
        # 좌표 퍼블리시
        h, w = frame.shape[:2]
        pt = Point()
        pt.x = person['center'][0] / w
        pt.y = person['center'][1] / h
        # z값에 Bounding Box 세로 길이의 비율(크기)을 넣어 거리를 추정합니다.
        pt.z = float(person['bbox'][3] - person['bbox'][1]) / h
        self.pub_target.publish(pt)

    def _publish_debug(self, frame):
        quality = self.get_parameter('jpeg_quality').value
        _, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        msg = CompressedImage()
        msg.format = 'jpeg'
        msg.data = np.array(encoded).tobytes()
        self.pub_debug.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = ServerTrackerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
