#!/bin/sh
if [ -d HSM_experiment ]; then
    (cd HSM_experiment; git pull) || exit 1
else
    git clone git://github.com/mrdunk/HSM_experiment || exit 1
fi
if [ -f HSM_experiment/src/geometry.py ]; then
    for i in geometry helpers voronoi_centers; do
        cp -v HSM_experiment/src/$i.py cam/ || exit 1
    done
    echo Files copied successfully.
else
    exit 1
fi
