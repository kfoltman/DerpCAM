# DerpCAM

A very quick and dirty set of tools for creating toolpaths for hobby 3-axis
CNC routers and mills.

This is not meant to be on par with commercial CAM packages, even the
inexpensive ones, it's basically a bare minimum needed to allow cutting simple
mechanical components like brackets or mounting plates.

Use Pyclipper for polygon clipping and offsetting, and Qt5 for the preview.

The toolpaths are currently unoptimized as far as arcs go, so they will work
better with machine controllers that can process lots of short line segments,
like LinuxCNC. It is possible to use them with Grbl, but they may stutter,
depending on the serial port speed and other factors.

More to follow...

