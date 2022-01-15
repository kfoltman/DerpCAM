# This is EMBARASSINGLY slow and produces some mind-boggingly stupid G-Code.
# At the time being, it is mostly a benchmark case to allow future improvements
# in areas like pocket milling or arc finding.

import sys
sys.path += '..'

from process import *
from geom import *
from gcodegen import *
from view import *

width = 250
inner_width = 240
length = 100

tool = Tool(diameter = 5, hfeed = 300, vfeed = 50, maxdoc = 0.2)
depth = -4
engrave_depth = -0.2
tab_depth = -2
# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
machine_params = MachineParams(safe_z = safe_z, semi_safe_z = semi_safe_z)

outside = Shape.circle(0, 0, width/2)
inner_frame = Shape.circle(0, 0, inner_width / 2)

def curve_transform(x, y):
    pos = 0.5 + 0.5 * x / (inner_width / 2)
    r = width / 2 - 29 + y * 1.5
    angle = (1 - pos) * pi
    return PathPoint(r * cos(angle), r * sin(angle))

from ptext import *
init_app()
font = "Gentium"
label = text_to_shapes(-inner_width / 2, -length / 2, inner_width, length, "BLACKPITTS", font, 28, -1, 0)
label2 = text_to_shapes(-inner_width / 2, -length / 2, inner_width, length, "22", font, 120, -1, 0)
label = [shape.warp(curve_transform) for shape in label]

props_fulldepth = OperationProps(depth=depth, tab_depth=tab_depth)
props_engrave = OperationProps(depth=engrave_depth)
operations = Operations(machine_params=machine_params, tool=tool, props=props_fulldepth)
inner_frame_emboss = Shape(inner_frame.boundary, True, [shape.boundary for shape in label + label2])
print ("pocket")
operations.pocket(inner_frame_emboss, props=props_engrave)
for label_item in label + label2:
    for island in label_item.islands:
        operations.pocket(Shape(island, True, []), props=props_engrave)
operations.outside_contour(outside, tabs=4)
print ("to gcode")
operations.to_gcode_file("textemboss.ngc")
print ("display")
viewer_modal(operations)
