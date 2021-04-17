import sys
sys.path += '..'

from process import *
from geom import *
from gcodegen import *
from view import *

tool = Tool(diameter = 4, hfeed = 300, vfeed = 50, maxdoc = 0.2)
depth = -12
recess = -6
tab_depth = -10
# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
machine_params = MachineParams(safe_z = safe_z, semi_safe_z = semi_safe_z)

size = 50
hsize = size / 2
smargin = 4
dmargin = smargin / sqrt(2)

outside_points = [(-smargin, -smargin), (size + smargin, -smargin), (size + smargin, size + smargin), (-smargin, size + smargin)]

pockets = [
    [(dmargin, 0), (size - dmargin, 0), (hsize, hsize - dmargin)],
    [(size, dmargin), (size, size - dmargin), (hsize + dmargin, hsize)],
    [(dmargin, size), (size - dmargin, size), (hsize, hsize + dmargin)],
    [(0, dmargin), (0, size - dmargin), (hsize - dmargin, hsize)],
]
draft_angle_deg = 10
layer_height = 0.2
layer_height_outside = 0.4

props = OperationProps(depth=depth)
props_contour = props.clone(tab_depth=tab_depth)
props_recess = props.clone(depth=recess)
operations = Operations(machine_params=machine_params, tool=tool, props=props)
for pocket_points in pockets:
    pocket_points = list(reversed(pocket_points))
    operations.pocket_with_draft(Shape(pocket_points), draft_angle_deg, layer_height, props = props_recess)
    #operations.pocket(Shape(pocket_points))
operations.outside_contour_with_draft(Shape(outside_points), draft_angle_deg, layer_height_outside, tabs = 5, props = props_contour)
operations.to_gcode_file("mold.ngc")

viewer_modal(operations)
