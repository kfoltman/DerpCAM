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
# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
machine_params = MachineParams(safe_z = safe_z, semi_safe_z = semi_safe_z)

points = []

for i in range(20, 250):
    r = 10 + i * 0.12
    a = -0.05 * i
    points.append(PathPoint(r * cos(a), r * sin(a)))
for i in range(249, 20, -1):
    r = 1 + i * 0.12
    a = -0.05 * i
    points.append(PathPoint(r * cos(a), r * sin(a)))
points.append(points[0])

outside = Shape(points)

operations = Operations(machine_params=machine_params, tool=tool, props=OperationProps(depth=depth))
operations.pocket(outside)
operations.to_gcode_file("spiral_pocket.ngc")

viewer_modal(operations)
