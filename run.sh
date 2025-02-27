#!/bin/bash
if [ ! -d venv ]; then
  echo "Installation environment doesn't exist. Run prepare.sh first in order to create the virtual environment."
  exit 1
fi
if [ ! -f venv/probably_complete ]; then
  echo "Installation environment exists but without all necessary dependencies. Re-run prepare.sh and check for package installation problems."
  exit 1
fi
source ./venv/bin/activate
./DerpCAM
