# Guardian
- Real-time object detection and tracking for highly constrained systems on drone (e.g. Jetson Nano)
- Flight control for drone that tracks targets using GPS signal and computer vision
- Guardian is an appliation to alleviate elephant-human conflict common in Africa and Asia

### Dependencies
- OpenCV (Built with Gstreamer)
- Numpy
- Scipy
- PyCuda
- TensorRT
- DJI OSDK

### Example runs
- With camera: `python3 main.py -a`
- Input video: `python3 main.py -a -i video.mp4`
- Use `-h` for detailed descriptions about other flags like saving output and visualization
