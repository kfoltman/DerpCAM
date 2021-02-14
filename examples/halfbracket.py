import sys
sys.path += '..'

from process import *
from geom import *
from gcodegen import *
from view import *

width = 30
length = 60


tool = Tool(diameter = 4, hfeed = 300, vfeed = 50, maxdoc = 0.2)
depth = -4
tab_depth = -2
# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
hole_diameter = 4.2

outside = Shape.union(
    Shape.rectangle(0, 0, width, length - width / 2),
    Shape.circle(width / 2, length - width / 2, d = width)
)
holes = [
    (width / 2, length - width / 4),
    (width / 4, length - width / 2 - hole_diameter / 2),
    (3 * width / 4, length - width / 2 - hole_diameter / 2),
]

operations = []

operations += [HelicalDrill(x=hole[0], y=hole[1], d=hole_diameter, tool=tool, props=OperationProps(depth=depth)) for hole in holes ]
operations += [Operation(outside, tool, outside.contour(tool, outside=True), OperationProps(depth=depth, tab_depth=tab_depth), tabs=4)]

gcode = gcodeFromOperations(operations, safe_z, semi_safe_z)

glines = gcode.gcode

f = open("halfbracket.ngc", "w")
for line in glines:
  f.write(line + '\n')
f.close()

viewer_modal(operations)
