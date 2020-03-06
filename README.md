# Guardian
- Real-time object detection and tracking for highly constrained systems on drone (e.g. Jetson Nano)
- Guardian is an autonomous drone solution for human-elephant conflict common in Africa and Asia

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
