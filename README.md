<p align="center">
  <img src="demo.gif" width="720" height="405" />
</p>

- [x] Real-time detection and tracking for resource-constrained embedded systems
  - Support all classes in the COCO dataset
  - Robust against moderate camera movement
  - Work best on 1280 x 720 input resolution and medium/small objects
  - Speed on Jetson Nano: 32 FPS

### Dependencies
- CUDA
- OpenCV (Built with Gstreamer)
- Numpy
- Scipy
- PyCuda
- TensorRT  

#### Install dependencies for Jetson platforms
- OpenCV, CUDA, and TensorRT can be installed from NVIDIA JetPack:    
https://developer.nvidia.com/embedded/jetpack
- `bash install_jetson.sh`

### Run tracking
- With camera: `python3 vision.py --mot`
- Input video: `python3 vision.py --input video.mp4 --mot`
- Use `-h` for detailed descriptions about other flags like saving output and visualization
- Edit analytics/configs/config.json to configure parameters and change object classes

### References
- SORT: https://arxiv.org/abs/1602.00763  
- Deep SORT: https://arxiv.org/pdf/1703.07402.pdf 
