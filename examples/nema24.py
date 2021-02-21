import sys
sys.path += '..'

from process import *
from geom import *
from gcodegen import *
from view import *

# 47.1 or 50 depending on the model
hole_spacing = 50

tool = Tool(diameter = 4, hfeed = 300, vfeed = 50, maxdoc = 0.2)
depth = -7
recess_depth = -2
tab_depth = -5
# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1

outside = Shape.rectangle(0, 0, 60, 60)
holes = [ (30 + hole_spacing * i, 30 + hole_spacing * j, 4.2) for i in (-0.5, 0.5) for j in (-0.5, 0.5)]
recess = Shape.circle(30, 30, d = 38.3)
shaft = Shape.circle(30, 30, d = 8.2)


operations = [
    HelicalDrillFullDepth(x=30, y=30, d=10.2, tool=tool, props=OperationProps(depth=depth)),
    #Operation(shaft, tool, shaft.pocket_contour(tool), props=OperationProps(depth=depth)),
    #HelicalDrill2(x=30, y=30, d=38.3, tool=tool, props=OperationProps(depth=recess_depth))
    Operation(recess, tool, recess.pocket_contour(tool), props=OperationProps(depth=recess_depth))
] + [ HelicalDrill(x=hole[0], y=hole[1], d=4.2, tool=tool, props=OperationProps(depth=depth)) for hole in holes ] + [
    Operation(outside, tool, outside.contour(tool, outside=True), OperationProps(depth=depth, tab_depth=tab_depth), tabs=4),
]

gcode = gcodeFromOperations(operations, safe_z, semi_safe_z)

glines = gcode.gcode

f = open("nema24.ngc", "w")
for line in glines:
  f.write(line + '\n')
f.close()

viewer_modal(operations)
