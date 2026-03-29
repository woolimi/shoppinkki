import cv2
import numpy as np
import pickle
import os

try:
    import mediapipe as mp
    HAS_MEDIAPIPE = True
except ImportError:
    HAS_MEDIAPIPE = False

POSE_HOLD_FRAMES = 5
POSE_HOLD_FRAMES_FALLBACK = 20  # MediaPipe가 없을 때

CALIBRATION_SEQUENCE = ['FRONT', 'RIGHT', 'BACK', 'LEFT']
POSE_INSTRUCTIONS = {
    'FRONT': "1. Stand FACE forward",
    'RIGHT': "2. Turn RIGHT",
    'BACK':  "3. Turn BACK",
    'LEFT':  "4. Turn LEFT"
}

class Calibrator:
    def __init__(self, template_path="owner_server_template.pkl"):
        self.template_path = os.path.join(os.getcwd(), template_path)
        
        if HAS_MEDIAPIPE:
            self.mp_pose = mp.solutions.pose
            self.mp_drawing = mp.solutions.drawing_utils
            self.pose = self.mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
        else:
            self.pose = None

        self.is_owner_registered = False
        self.owner_templates = []
        
        self.is_calibrating = False
        self._current_step = 0
        self._hold_count = 0
        self._message = ""

        # 기존 템플릿 로드
        if os.path.exists(self.template_path):
            try:
                with open(self.template_path, 'rb') as f:
                    self.owner_templates = pickle.load(f)
                    if len(self.owner_templates) > 0:
                        self.is_owner_registered = True
            except Exception:
                pass

    def start(self):
        self.is_calibrating = True
        self._current_step = 0
        self._hold_count = 0
        self.owner_templates = []
        self.is_owner_registered = False
        self._message = "Get ready for Calibration (Front)"

    def clear(self):
        self.owner_templates = []
        self.is_owner_registered = False
        self.is_calibrating = False
        if os.path.exists(self.template_path):
            os.remove(self.template_path)
        self._message = ""

    def process_best_person(self, frame, target):
        if not self.is_calibrating:
            return

        if self._current_step >= len(CALIBRATION_SEQUENCE):
            # 완료
            with open(self.template_path, 'wb') as f:
                pickle.dump(self.owner_templates, f)
            self.is_owner_registered = True
            self.is_calibrating = False
            self._message = "Owner Registered!"
            return

        expected_pose = CALIBRATION_SEQUENCE[self._current_step]
        box = target['box']
        detected_pose = self._detect_pose_direction(frame, box[0], box[1], box[2], box[3])

        if detected_pose == expected_pose:
            self._hold_count += 1
            hold_required = POSE_HOLD_FRAMES if self.pose else POSE_HOLD_FRAMES_FALLBACK
            self._message = f"{POSE_INSTRUCTIONS[expected_pose]} ({self._hold_count}/{hold_required})"

            if self._hold_count >= hold_required:
                self.owner_templates.append(target['features'])
                self._current_step += 1
                self._hold_count = 0
        else:
            self._hold_count = max(0, self._hold_count - 1)
            self._message = f"{POSE_INSTRUCTIONS[expected_pose]} (Hold Pose...)"

    def _detect_pose_direction(self, frame, x1, y1, x2, y2):
        if not self.pose:
            h, w = frame.shape[:2]
            expected = CALIBRATION_SEQUENCE[self._current_step]
            cv2.putText(frame, f"[AUTO] {expected}", (w//2-80, h//2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 3)
            return expected

        h, w = frame.shape[:2]
        crop_x1 = max(0, int(x1) - 20)
        crop_y1 = max(0, int(y1) - 20)
        crop_x2 = min(w, int(x2) + 20)
        crop_y2 = min(h, int(y2) + 20)
        
        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        if crop.size == 0:
            return CALIBRATION_SEQUENCE[self._current_step]

        rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        results = self.pose.process(rgb_crop)

        if results.pose_landmarks:
            # 원본 프레임에 스켈레톤 그리기 (좌표 보정)
            for lm in results.pose_landmarks.landmark:
                lm.x = (lm.x * crop.shape[1] + crop_x1) / w
                lm.y = (lm.y * crop.shape[0] + crop_y1) / h
            try:
                self.mp_drawing.draw_landmarks(frame, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)
            except Exception:
                pass # 구/신버전 호환성 에러 방지

            landmarks = results.pose_landmarks.landmark
            l_shoulder = landmarks[11]
            r_shoulder = landmarks[12]

            vis_threshold = 0.5
            l_vis = l_shoulder.visibility > vis_threshold
            r_vis = r_shoulder.visibility > vis_threshold

            if l_vis and r_vis:
                diff = l_shoulder.x - r_shoulder.x
                if abs(diff) < 0.15:
                    return 'RIGHT' if l_shoulder.z < r_shoulder.z else 'LEFT'
                elif diff > 0.05: return 'FRONT'
                elif diff < -0.05: return 'BACK'
            elif l_vis and not r_vis:
                return 'RIGHT'
            elif r_vis and not l_vis:
                return 'LEFT'

        # 판별 불가시 현재 예상 자세 리턴 (Fallback)
        return CALIBRATION_SEQUENCE[self._current_step]

    def draw_progress(self, frame):
        if not self.is_calibrating:
            return

        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0,0), (w, 50), (0,0,0), -1)
        cv2.putText(frame, self._message, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        
        # ProgressBar
        total_steps = len(CALIBRATION_SEQUENCE)
        bar_width = w // total_steps
        for i in range(total_steps):
            color = (0, 255, 0) if i < self._current_step else (100, 100, 100)
            if i == self._current_step: color = (0, 165, 255)
            cv2.rectangle(frame, (i * bar_width, 0), ((i+1) * bar_width, 10), color, -1)
            cv2.line(frame, (i * bar_width, 0), (i * bar_width, 10), (255,255,255), 1)
