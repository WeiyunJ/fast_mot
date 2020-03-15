# Guardian
Guardian is an appliation for drones to "herd" elephants away in elephant-human conflicts common in Africa and Asia
### Two packages included
- Real-time object detection and tracking for highly constrained systems (Jetson Nano)
- Drone flight control for following targets using both GPS and vision (Work in Progress)


### Dependencies
#### Visual tracking
- OpenCV (Built with Gstreamer)
- Numpy
- Scipy
- PyCuda
- TensorRT
#### Flight control
- DJI OSDK

### Run visual tracking only
- With camera: `python3 vision.py -a`
- Input video: `python3 vision.py -a -i video.mp4`
- Use `-h` for detailed descriptions about other flags like saving output and visualization
### Run the whole systems
- Coming out soon
