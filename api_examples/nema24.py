from example_common import *

# 47.1 or 50 depending on the model
hole_spacing = 50

# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
machine_params = MachineParams(safe_z = safe_z, semi_safe_z = semi_safe_z)

tool = Tool(diameter = 2.5, hfeed = 300, vfeed = 50, maxdoc = 0.2)
depth = -7
recess_depth = -2
tab_depth = -5
# Best kept at False, because it's unfinished and untested on a real machine.
use_trochoidal_for_contour = False

outside = Shape.rectangle(0, 0, 60, 60)
holes = [(30 + hole_spacing * i, 30 + hole_spacing * j, 4.2) for i in (-0.5, 0.5) for j in (-0.5, 0.5)]
recess = Shape.circle(30, 30, d = 38.3)
#shaft = Shape.circle(30, 30, d = 8.2)

props_recess = OperationProps(depth=recess_depth)
props_fulldepth = OperationProps(depth=depth, tab_depth=tab_depth)

operations = Operations(machine_params=machine_params, tool=tool, props=props_fulldepth)
operations.helical_drill_full_depth(x=30, y=30, d=10.2)
#operations.pocket(shaft))
#operations.helical_drill_full_depth(x=30, y=30, d=38.3, props=OperationProps(depth=recess_depth))
operations.pocket(recess, props=props_recess)

tabs = [
    PathPoint(30, 0),
    PathPoint(60, 30),
    PathPoint(30, 60),
    PathPoint(0, 30),
]

for x, y, d in holes:
    operations.helical_drill(x=x, y=y, d=d)
if use_trochoidal_for_contour:
    operations.outside_contour_trochoidal(outside, nrad=0.5, nspeed=1, tabs=tabs)
else:
    operations.outside_contour(outside, tabs=tabs)

operations.to_gcode_file("nema24.ngc")

viewer_modal(operations)
