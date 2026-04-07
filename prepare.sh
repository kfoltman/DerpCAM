#!/bin/bash
if ! which cmake >/dev/null; then
  echo 'Warning: CMake may be needed to build the required pyclipr library.'
  sleep 1
fi
if ! which pkg-config >/dev/null; then
  echo 'Warning: pkg-config may be needed to build the required pyclipr library.'
  sleep 1
fi
if ! pkg-config 'eigen3 >= 3.0'; then
  echo 'Warning: Eigen3 library (libeigen3-dev or similar) may be needed to build the required pyclipr library.'
  sleep 1
fi
virtualenv venv || exit 1
source ./venv/bin/activate || exit 1
pip3 install -r requirements.txt --upgrade || exit 1
touch venv/probably_complete
echo ''
echo 'Installation complete! Use ./run.sh command to launch DerpCAM.'
echo ''
