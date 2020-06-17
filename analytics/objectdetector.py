from enum import Enum
from pathlib import Path
import json
import pycuda.autoinit
import pycuda.driver as cuda
import tensorrt as trt
import numpy as np
import cv2
import time

from .utils import Rect, iou
from .models import ssd
from .configs import decoder

class Detection:
    def __init__(self, bbox, label, conf, tile_id):
        self.bbox = bbox
        self.label = label
        self.conf = conf
        self.tile_id = tile_id

    def __repr__(self):
        return "Detection(bbox=%r, label=%r, conf=%r, tile_id=%r)" % (self.bbox, self.label, self.conf, self.tile_id)

    def __str__(self):
        return "%.2f %s at %s" % (self.conf, ssd.COCO_LABELS[self.label], self.bbox.cv_rect())
    
    def draw(self, frame):
        text = "%s: %.2f" % (ssd.COCO_LABELS[self.label], self.conf) 
        (text_width, text_height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1, 1)
        cv2.rectangle(frame, self.bbox.tl(), self.bbox.br(), (112, 25, 25), 2)
        cv2.rectangle(frame, self.bbox.tl(), (self.bbox.xmin + text_width - 1, self.bbox.ymin - text_height + 1), (112, 25, 25), cv2.FILLED)
        cv2.putText(frame, text, self.bbox.tl(), cv2.FONT_HERSHEY_SIMPLEX, 1, (102, 255, 255), 2, cv2.LINE_AA)


class ObjectDetector:
    class Type(Enum):
        TRACKING = 0
        ACQUISITION = 1

    with open(Path(__file__).parent / 'configs' / 'config.json') as config_file:
        config = json.load(config_file, cls=decoder.decoder)['ObjectDetector']
    runtime = None

    @classmethod
    def init_backend(cls): 
        # initialize TensorRT
        trt_logger = trt.Logger(trt.Logger.INFO)
        trt.init_libnvinfer_plugins(trt_logger, '')
        ObjectDetector.runtime = trt.Runtime(trt_logger)

    def __init__(self, size, classes, detector_type):
        # initialize parameters
        self.size = size
        self.classes = set(classes)
        self.detector_type = detector_type
        self.max_det = ObjectDetector.config['max_det']
        self.batch_size = ObjectDetector.config['batch_size']
        self.tile_overlap = ObjectDetector.config['tile_overlap']
        self.merge_iou_thresh = ObjectDetector.config['merge_iou_thresh']

        self.tiles = None
        self.cur_tile = None
        if self.detector_type == ObjectDetector.Type.ACQUISITION:
            self.conf_threshold = ObjectDetector.config['acquisition']['conf_threshold']
            self.tiling_grid = ObjectDetector.config['acquisition']['tiling_grid']
            self.schedule_tiles = ObjectDetector.config['acquisition']['schedule_tiles']
            self.age_to_object_ratio = ObjectDetector.config['acquisition']['age_to_object_ratio']
            self.model = ssd.InceptionV2 #ssd.MobileNetV1
            self.tile_size = self.model.INPUT_SHAPE[1:][::-1]
            self.tiles = self._generate_tiles()
            self.tile_ages = np.zeros(len(self.tiles))
            self.cur_tile_id = -1
        elif self.detector_type == ObjectDetector.Type.TRACKING:
            self.conf_threshold = ObjectDetector.config['tracking']['conf_threshold']
            self.model = ssd.InceptionV2
            self.tile_size = self.model.INPUT_SHAPE[1:][::-1]
        # ssd.prepare_model(self.model, trt.DataType.HALF, self.batch_size)
        ssd.prepare_model(self.model, trt.DataType.INT8, self.batch_size)

        # load model and create engine
        with open(self.model.PATH, 'rb') as model_file:
            buf = model_file.read()
            self.engine = ObjectDetector.runtime.deserialize_cuda_engine(buf)
        assert self.max_det <= self.model.TOPK
        assert self.batch_size <= self.engine.max_batch_size

        # create buffers
        self.host_inputs  = []
        self.cuda_inputs  = []
        self.host_outputs = []
        self.cuda_outputs = []
        self.bindings = []
        self.stream = cuda.Stream()

        for binding in self.engine:
            size = trt.volume(self.engine.get_binding_shape(binding)) * self.batch_size
            host_mem = cuda.pagelocked_empty(size, np.float32)
            cuda_mem = cuda.mem_alloc(host_mem.nbytes)
            self.bindings.append(int(cuda_mem))
            if self.engine.binding_is_input(binding):
                self.host_inputs.append(host_mem)
                self.cuda_inputs.append(cuda_mem)
            else:
                self.host_outputs.append(host_mem)
                self.cuda_outputs.append(cuda_mem)

        self.context = self.engine.create_execution_context()
        self.input_batch = np.zeros((self.batch_size, trt.volume(self.model.INPUT_SHAPE)))
    
    def preprocess(self, frame, tracks={}, track_id=None):
        if self.batch_size > 1:
            # tile batching
            for i, tile in enumerate(self.tiles):
                frame_tile = tile.crop(frame)
                frame_tile = cv2.cvtColor(frame_tile, cv2.COLOR_BGR2RGB)
                frame_tile = frame_tile * (2 / 255) - 1 # Normalize to [-1.0, 1.0] interval (expected by model)
                frame_tile = np.transpose(frame_tile, (2, 0, 1)) # HWC -> CHW
                self.input_batch[i] = frame_tile.ravel()
        else:
            if self.detector_type == ObjectDetector.Type.ACQUISITION:
                # tile scheduling
                if self.schedule_tiles:
                    sx = sy = 1 - self.tile_overlap
                    tile_num_tracks = np.zeros(len(self.tiles))
                    for tile_id, tile in enumerate(self.tiles):
                        scaled_tile = tile.scale(sx, sy)
                        for track in tracks.values():
                            if track.bbox.center() in scaled_tile or tile.contains_rect(track.bbox):
                                tile_num_tracks[tile_id] += 1
                    tile_scores = self.tile_ages * self.age_to_object_ratio + tile_num_tracks
                    self.cur_tile_id = np.argmax(tile_scores)
                    self.tile_ages += 1
                    self.tile_ages[self.cur_tile_id] = 0
                else:
                    self.cur_tile_id = (self.cur_tile_id + 1) % len(self.tiles)
                self.cur_tile = self.tiles[self.cur_tile_id]
            elif self.detector_type == ObjectDetector.Type.TRACKING:
                assert track_id in tracks
                xmin, ymin = np.int_(np.round(tracks[track_id].bbox.center() - (np.array(self.tile_size) - 1) / 2))
                xmin = max(min(self.size[0] - self.tile_size[0], xmin), 0)
                ymin = max(min(self.size[1] - self.tile_size[1], ymin), 0)
                self.cur_tile = Rect(cv_rect=(xmin, ymin, self.tile_size[0], self.tile_size[1]))
            
            frame_tile = self.cur_tile.crop(frame)
            frame_tile = cv2.cvtColor(tile, cv2.COLOR_BGR2RGB)
            frame_tile = frame_tile * (2 / 255) - 1 # Normalize to [-1.0, 1.0] interval (expected by model)
            frame_tile = np.transpose(frame_tile, (2, 0, 1)) # HWC -> CHW
            self.input_batch[-1] = frame_tile.ravel()

        np.copyto(self.host_inputs[0], self.input_batch.ravel())

    def infer_async(self):
        self.tic = time.perf_counter() 
        # inference
        cuda.memcpy_htod_async(self.cuda_inputs[0], self.host_inputs[0], self.stream)
        self.context.execute_async(batch_size=self.batch_size, bindings=self.bindings, stream_handle=self.stream.handle)
        cuda.memcpy_dtoh_async(self.host_outputs[1], self.cuda_outputs[1], self.stream)
        cuda.memcpy_dtoh_async(self.host_outputs[0], self.cuda_outputs[0], self.stream)

    def postprocess(self):
        self.stream.synchronize()
        print(time.perf_counter() - self.tic)
        output = self.host_outputs[0]
        detections = []
        for tile_idx in range(self.batch_size):
            tile = self.tiles[tile_idx] if self.batch_size > 1 else self.cur_tile
            tile_offset = tile_idx * self.model.TOPK
            for det_idx in range(self.max_det):
                offset = (tile_offset + det_idx) * self.model.OUTPUT_LAYOUT
                # index = int(output[offset])
                label = int(output[offset + 1])
                conf = output[offset + 2]
                if conf > self.conf_threshold and label in self.classes:
                    xmin = int(round(output[offset + 3] * tile.size[0])) + tile.xmin
                    ymin = int(round(output[offset + 4] * tile.size[1])) + tile.ymin
                    xmax = int(round(output[offset + 5] * tile.size[0])) + tile.xmin
                    ymax = int(round(output[offset + 6] * tile.size[1])) + tile.ymin
                    bbox = Rect(tf_rect=(xmin, ymin, xmax, ymax))
                    detections = np.append(detections, Detection(bbox, label, conf, set([tile_idx])))
                    # print('[Detector] Detected: %s' % det)

        # merge detections across different tiles
        merged_detections = []
        merged_det_indices = set()
        for i, det1 in enumerate(detections):
            if i not in merged_det_indices:
                merged_det = Detection(det1.bbox, det1.label, det1.conf, det1.tile_id)
                for j, det2 in enumerate(detections):
                    if j not in merged_det_indices:
                        if merged_det.tile_id.isdisjoint(det2.tile_id) and merged_det.label == det2.label and iou(merged_det.bbox, det2.bbox) > self.merge_iou_thresh:
                            merged_det.bbox |= det2.bbox
                            merged_det.conf = max(merged_det.conf, det2.conf) 
                            merged_det.tile_id |= det2.tile_id
                            merged_det_indices.add(i)
                            merged_det_indices.add(j)
                if i in merged_det_indices:
                    merged_detections.append(merged_det)
        detections = np.delete(detections, list(merged_det_indices))
        detections = np.append(detections, merged_detections)
        return detections

    def detect_sync(self, frame, tracks={}, track_id=None):
        self.preprocess(frame, tracks, track_id)
        self.infer_async()
        return self.postprocess()

    def get_tiling_region(self):
        assert self.detector_type == ObjectDetector.Type.ACQUISITION and len(self.tiles) > 0
        return Rect(tf_rect=(self.tiles[0].xmin, self.tiles[0].ymin, self.tiles[-1].xmax, self.tiles[-1].ymax))

    def draw_tile(self, frame):
        if self.cur_tile is not None:
            cv2.rectangle(frame, self.cur_tile.tl(), self.cur_tile.br(), 0, 2)
        else:
            [cv2.rectangle(frame, tile.tl(), tile.br(), 0, 2) for tile in self.tiles]

    def _generate_tiles(self):
        width, height = self.size
        tile_width, tile_height = self.tile_size
        step_width = (1 - self.tile_overlap) * tile_width
        step_height = (1 - self.tile_overlap) * tile_height
        total_width = (self.tiling_grid[0] - 1) * step_width + tile_width
        total_height = (self.tiling_grid[1] - 1) * step_height + tile_height
        assert total_width <= width and total_height <= height, "Frame size not large enough for %dx%d tiles" % self.tiling_grid
        x_offset = width // 2 - total_width // 2
        y_offset = height // 2 - total_height // 2
        tiles = [Rect(cv_rect=(int(c * step_width + x_offset), int(r * step_height + y_offset), tile_width, tile_height)) for r in range(self.tiling_grid[1]) for c in range(self.tiling_grid[0])]
        return tiles
