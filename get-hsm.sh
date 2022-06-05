#!/bin/sh
if [ -d HSM_experiment ]; then
    (cd HSM_experiment; git pull) || exit 1
else
    git clone https://github.com/mrdunk/HSM_experiment || exit 1
    (cd HSM_experiment; git checkout -b development --track origin/development) || exit 1
fi
if [ -f HSM_experiment/src/geometry.py ]; then
    cd src/DerpCAM/cam
    for i in geometry helpers voronoi_centers; do
        rm $i.py
        ln -s ../../../HSM_experiment/src/$i.py $i.py || exit 1
    done
    echo Files linked successfully.
else
    exit 1
fi
