import numpy as np
import cv2
import math


class Rect:
    def __init__(self, tf_rect=None, cv_rect=None):
        if tf_rect is not None:
            self.xmin, self.ymin, self.xmax, self.ymax = tf_rect
            self.size = (self.xmax - self.xmin + 1, self.ymax - self.ymin + 1)
        elif cv_rect is not None:
            self.xmin, self.ymin = cv_rect[:2]
            self.size = tuple(cv_rect[2:])
            self.xmax = self.size[0] - 1 + self.xmin
            self.ymax = self.size[1] - 1 + self.ymin
        
    def __repr__(self):
        return "Rect(tf_rect=(%r, %r, %r, %r))" % (self.xmin, self.ymin, self.xmax, self.ymax)

    def __contains__(self, point):
        assert isinstance(point, tuple) and len(point) == 2
        return point[0] >= self.xmin and point[1] >= self.ymin and point[0] <= self.xmax and point[1] <= self.ymax

    def __and__(self, other):
        xmin = max(self.xmin, other.xmin)
        ymin = max(self.ymin, other.ymin)
        xmax = min(self.xmax, other.xmax)
        ymax = min(self.ymax, other.ymax)
        inter_rect = Rect(tf_rect=(xmin, ymin, xmax, ymax))
        if inter_rect.size[0] <= 0 or inter_rect.size[1] <= 0:
            return None
        return inter_rect

    def __or__(self, other):
        xmin = min(self.xmin, other.xmin)
        ymin = min(self.ymin, other.ymin)
        xmax = max(self.xmax, other.xmax)
        ymax = max(self.ymax, other.ymax)
        return Rect(tf_rect=(xmin, ymin, xmax, ymax))

    def contains_rect(self, other):
        return other.xmin >= self.xmin and other.ymin >= self.ymin and other.xmax <= self.xmax and other.ymax <= self.ymax

    def tf_rect(self):
        return (self.xmin, self.ymin, self.xmax, self.ymax)
    
    def cv_rect(self):
        return (self.xmin, self.ymin, self.size[0], self.size[1])

    def tl(self):
        return (self.xmin, self.ymin)

    def br(self):
        return (self.xmax, self.ymax)

    def center(self):
        return ((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2)

    def area(self):
        return self.size[0] * self.size[1]

    def crop(self, image):
        return image[self.ymin:self.ymax + 1, self.xmin:self.xmax + 1]

    def scale(self, sx, sy):
        half_size = (self.size * np.array([sx, sy]) - 1) / 2
        xmin, ymin = np.int_(np.round(self.center() - half_size))
        xmax, ymax = np.int_(np.round(self.center() + half_size))
        return Rect(tf_rect=(xmin, ymin, xmax, ymax))
    
    def draw(self, frame):
        cv2.rectangle(frame, self.tl(), self.br(), 0, 2)
    

def iou(rect1, rect2):
    inter_xmin = max(rect1.xmin, rect2.xmin) 
    inter_ymin = max(rect1.ymin, rect2.ymin)
    inter_xmax = min(rect1.xmax, rect2.xmax)
    inter_ymax = min(rect1.ymax, rect2.ymax)
    inter_area = max(0, inter_xmax - inter_xmin + 1) * max(0, inter_ymax - inter_ymin + 1)
    iou = inter_area / (rect1.area() + rect2.area() - inter_area)
    return iou


def l2_dist(point1, point2):
    return math.sqrt(np.sum((np.asarray(point1) - point2)**2))


coco_labels = [
    'unlabeled',
    'person',
    'bicycle',
    'car',
    'motorcycle',
    'airplane',
    'bus',
    'train',
    'truck',
    'boat',
    'traffic light',
    'fire hydrant',
    'street sign',
    'stop sign',
    'parking meter',
    'bench',
    'bird',
    'cat',
    'dog',
    'horse',
    'sheep',
    'cow',
    'elephant',
    'bear',
    'zebra',
    'giraffe',
    'hat',
    'backpack',
    'umbrella',
    'shoe',
    'eye glasses',
    'handbag',
    'tie',
    'suitcase',
    'frisbee',
    'skis',
    'snowboard',
    'sports ball',
    'kite',
    'baseball bat',
    'baseball glove',
    'skateboard',
    'surfboard',
    'tennis racket',
    'bottle',
    'plate',
    'wine glass',
    'cup',
    'fork',
    'knife',
    'spoon',
    'bowl',
    'banana',
    'apple',
    'sandwich',
    'orange',
    'broccoli',
    'carrot',
    'hot dog',
    'pizza',
    'donut',
    'cake',
    'chair',
    'couch',
    'potted plant',
    'bed',
    'mirror',
    'dining table',
    'window',
    'desk',
    'toilet',
    'door',
    'tv',
    'laptop',
    'mouse',
    'remote',
    'keyboard',
    'cell phone',
    'microwave',
    'oven',
    'toaster',
    'sink',
    'refrigerator',
    'blender',
    'book',
    'clock',
    'vase',
    'scissors',
    'teddy bear',
    'hair drier',
    'toothbrush',
]
