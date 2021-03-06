# Jetpack 4.4 (OpenCV, CUDA, TensorRT) is required before running this script
DIR=$HOME
BASEDIR=$(dirname "$0")

# export CUDA paths
echo 'export PATH=/usr/local/cuda/bin${PATH:+:${PATH}}' >> ~/.bashrc 
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}' >> ~/.bashrc 
source ~/.bashrc

# install python dependencies
sudo apt-get update
sudo apt-get install python3-pip libhdf5-serial-dev hdf5-tools
sudo pip3 install cython numpy scipy pycuda
sudo pip3 install --no-cache-dir --extra-index-url https://developer.download.nvidia.com/compute/redist/jp/v44 tensorflow==1.15.2+nv20.4

# prepare INT8 calibration data
source $BASEDIR/analytics/models/prepare_calib_data.sh $BASEDIR/analytics/models