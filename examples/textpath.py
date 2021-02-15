import sys
sys.path += '..'

from process import *
from geom import *
from gcodegen import *
from view import *

width = 250
length = 100


tool = Tool(diameter = 1.5, hfeed = 300, vfeed = 50, maxdoc = 0.2)
depth = -4
tab_depth = -2
# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
hole_diameter = 4.2

#frame = circle(width / 2, -length, sqrt((width / 2) ** 2 + (2 * length) ** 2), sa = atan2(2 * length, width / 2), ea = pi - atan2(2 * length, width / 2)) + \
#    [( 0, 0), (width, 0)]

frame = circle(0, 0, width / 2)

outside = Shape(frame, True, [])

def curve_transform(x, y):
    pos = 0.5 + 0.5 * x / (width / 2)
    r = width / 2 - 22 + y * 1.4
    angle = (1 - pos) * pi
    return r * cos(angle), r * sin(angle)

#def curve_transform(x, y):
#    ax = x / width - 0.5
#    ay = y / length
#    angle = pi * ax * 1.1
#    bx = ax * cos(angle) + ay * sin(angle)
#    by =-ax * sin(angle) + ay * cos(angle)
#    return width / 2 + width * bx / 2, width * by / 1.6 + 20
    
def curve2_transform(x, y):
    y += 10 * cos((x - width / 2) / (width / 2) * pi)
    return x, y

from ptext import *
init_app()
font = "Gentium"
label = text_to_shapes(-width / 2, -length / 2, width, length, "BLACKPITTS", font, 30, -1, 0)
label2 = text_to_shapes(-width / 2, -length / 2, width, length, "22", font, 120, -1, 0)
label = [shape.warp(curve_transform) for shape in label]

operations = []

engrave_depth = -0.2
operations += [Operation(label_item, tool, label_item.pocket_contour(tool), OperationProps(depth=engrave_depth)) for label_item in label]
operations += [Operation(label_item, tool, label_item.pocket_contour(tool), OperationProps(depth=engrave_depth)) for label_item in label2]
operations += [Operation(outside, tool, outside.contour(tool, outside=True), OperationProps(depth=depth, tab_depth=tab_depth), tabs=4)]

gcode = gcodeFromOperations(operations, safe_z, semi_safe_z)

glines = gcode.gcode

f = open("textpath.ngc", "w")
for line in glines:
  f.write(line + '\n')
f.close()

viewer_modal(operations)
