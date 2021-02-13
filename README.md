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

# Supported milling operations

Only these operation types are currently supported:

* part/cutout milling (the tool on the outside or the inside of the shape) with auto-placed tabs only; tabs can be full or partial depth

* contour-aligned pocketing with no support for islands

* helical milling of holes, with two modes:

    * "true" helical, with each pass running a helix to full depth, each pass at
    an increasing diameter

    * helical entry and radial expansion, first running a helix at initial diameter
at full depth, then successively expanding the hole, at full depth, up to the final
diameter

Currently the entry into the material is done using ramping when possible, to
avoid straight plunges that may be detrimental to tool life. This is done
both for the initial entry and for re-entry after leaving the space for a holding
tab.

I'm trying to aim at milling harder materials on hobby grade machines, so some
emphasis is placed on trying to prevent premature tool wear and breakage. On
the other hand, this is a one-person spare-time project, so watch out for bugs!

# Known problems and limitations

* Things are not really tested well! There is very little in terms of automated
testing, either. So make sure to use your favorite G-Code
previewer to check for bugs. This is early, experimental code and it is likely
to break stuff.

* This is not aimed at any mass production whatsoever. The paths will never be
as good as anything generated by commercial CAM software, no matter the metric
used. In fact, they can be demonstrably stupid much of the time. It's my
spare-time hobby project to make a few nice looking custom parts a month, if
even that.

* There is no UI for creating/editing the shapes or toolpaths. Everything is
created via Python API. See an example in examples/nema24.py. More examples to follow.

* The API is not finalized yet. It is a minimum viable implementation that
allows me to test my machine, but any convenience features are currently missing.

* UI feature: there is only a 2D, Qt5 based path preview. It doesn't display
the generated g-code, but the path used to generate it, which can be good or
bad depending on the specific goals. Use something else, like CAMotics, to
preview the actual output.

* Paths are not optimized. They contain lots of line segments, and might run
quite badly on Grbl based machines with short motion buffers and slow serial
ports. This is something I want to improve in near future.

* There is no support for islands yet. This is simple to add and I'll probably
add it as soon as I need it.

* No axis-aligned pocketing. I don't like it enough to bother. I may add it later
if there is a good reason.

* No manual tab placing, it will currently place a desired number of tabs equally
spaced around the perimeter.

* No support for corner overcut

* No trochoidal or adaptive paths (may be added in future)

More to follow...

