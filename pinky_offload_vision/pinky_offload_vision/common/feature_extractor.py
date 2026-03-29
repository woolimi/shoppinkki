import cv2
import numpy as np

def extract_features(image, box):
    x1, y1, x2, y2 = map(int, box)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
    crop = image[y1:y2, x1:x2]
    
    if crop.size == 0:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    
    # 상의(상단 50%), 하의(하단 50%) 분리 특징 추출
    h, w = hsv.shape[:2]
    top_half = hsv[0:h//2, :]
    bottom_half = hsv[h//2:h, :]

    hist_top = cv2.calcHist([top_half], [0, 1], None, [16, 16], [0, 180, 0, 256])
    cv2.normalize(hist_top, hist_top, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    
    hist_bottom = cv2.calcHist([bottom_half], [0, 1], None, [16, 16], [0, 180, 0, 256])
    cv2.normalize(hist_bottom, hist_bottom, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

    features = np.concatenate([hist_top.flatten(), hist_bottom.flatten()])
    return features


def compare_features(feat1, feat2):
    if feat1 is None or feat2 is None:
        return 1.0
    return cv2.compareHist(feat1, feat2, cv2.HISTCMP_BHATTACHARYYA)
