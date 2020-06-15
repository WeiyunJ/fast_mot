import ctypes
from enum import Enum
from pathlib import Path
import json
import pycuda.autoinit
import pycuda.driver as cuda
import tensorrt as trt
import numpy as np
import cv2

from .utils import Rect
from .models import ssd
from .configs import decoder

class Detection:
    def __init__(self, bbox, label, conf):
        self.bbox = bbox
        self.label = label
        self.conf = conf

    def __repr__(self):
        return "Detection(bbox=%r, label=%r, conf=%r)" % (self.bbox, self.label, self.conf)

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
        # ctypes.CDLL(Path(__file__).parent / 'lib' / 'libflattenconcat.so')
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

        # batching tiles
        # for i, tile in enumerate(self.tiles):
        #     tile = tile.crop(frame)
        #     tile = cv2.cvtColor(tile, cv2.COLOR_BGR2RGB)
        #     tile = tile * (2 / 255) - 1 # Normalize to [-1.0, 1.0] interval (expected by model)
        #     tile = np.transpose(tile, (2, 0, 1)) # HWC -> CHW
        #     self.input_batch[i] = tile.ravel()

        tile = self.cur_tile.crop(frame)
        tile = cv2.cvtColor(tile, cv2.COLOR_BGR2RGB)
        tile = tile * (2 / 255) - 1 # Normalize to [-1.0, 1.0] interval (expected by model)
        tile = np.transpose(tile, (2, 0, 1)) # HWC -> CHW
        self.input_batch[-1] = tile.ravel()

        np.copyto(self.host_inputs[0], self.input_batch.ravel())

    def infer_async(self):
        # inference
        cuda.memcpy_htod_async(self.cuda_inputs[0], self.host_inputs[0], self.stream)
        self.context.execute_async(batch_size=self.batch_size, bindings=self.bindings, stream_handle=self.stream.handle)
        cuda.memcpy_dtoh_async(self.host_outputs[1], self.cuda_outputs[1], self.stream)
        cuda.memcpy_dtoh_async(self.host_outputs[0], self.cuda_outputs[0], self.stream)

    def postprocess(self):
        # # filter out tracks and detections not in tile
        # sx = sy = 1 - overlap
        # scaled_tile = tile.scale(sx, sy)
        # tracks, track_ids, boundary_tracks = ([] for i in range(3))
        # use_maha_cost = True
        # for track_id, track in self.tracks.items():
        #     if self.acquire != acquire:
        #         # reset age when mode toggles
        #         track.age = 0
        #     track.age += 1
        #     if track.bbox.center() in scaled_tile or tile.contains_rect(track.bbox): 
        #         if track_id not in self.kalman_filters:
        #             use_maha_cost = False
        #         track_ids.append(track_id)
        #         tracks.append(track)
        #     elif iou(track.bbox, tile) > 0:
        #         boundary_tracks.append(track)

        self.stream.synchronize()
        output = self.host_outputs[0]
        detections = []
        for det_idx in range(self.max_det):
            offset = det_idx * self.model.OUTPUT_LAYOUT
            # index = int(output[offset])
            label = int(output[offset + 1])
            conf = output[offset + 2]
            if conf > self.conf_threshold and label in self.classes:
                xmin = int(round(output[offset + 3] * self.cur_tile.size[0])) + self.cur_tile.xmin
                ymin = int(round(output[offset + 4] * self.cur_tile.size[1])) + self.cur_tile.ymin
                xmax = int(round(output[offset + 5] * self.cur_tile.size[0])) + self.cur_tile.xmin
                ymax = int(round(output[offset + 6] * self.cur_tile.size[1])) + self.cur_tile.ymin
                bbox = Rect(tf_rect=(xmin, ymin, xmax, ymax))
                detections.append(Detection(bbox, label, conf))
                # print('[Detector] Detected: %s' % det)
        return detections

    def detect_sync(self, frame, tracks={}, track_id=None):
        self.preprocess(frame, tracks, track_id)
        self.infer_async()
        return self.postprocess()

    def get_tiling_region(self):
        assert self.detector_type == ObjectDetector.Type.ACQUISITION and len(self.tiles) > 0
        return Rect(tf_rect=(self.tiles[0].xmin, self.tiles[0].ymin, self.tiles[-1].xmax, self.tiles[-1].ymax))

    def draw_cur_tile(self, frame):
        cv2.rectangle(frame, self.cur_tile.tl(), self.cur_tile.br(), 0, 2)

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
