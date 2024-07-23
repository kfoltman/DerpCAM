from example_common import *

width = 30
length = 60

tool = Tool(diameter = 2.5, hfeed = 300, vfeed = 50, maxdoc = 0.2)
depth = -4
tab_depth = -2
# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
machine_params = MachineParams(safe_z = safe_z, semi_safe_z = semi_safe_z)

hole_diameter = 4.2

outside = Shape.union2(
    Shape.rectangle(0, 0, width, length - width / 2),
    Shape.circle(width / 2, length - width / 2, d = width)
)
holes = [
    PathPoint(width / 2, length - width / 4),
    PathPoint(width / 4, length - width / 2 - hole_diameter / 2),
    PathPoint(3 * width / 4, length - width / 2 - hole_diameter / 2),
]

# Rotate everything by 45 degrees
angle = -pi / 4
rx, ry = width / 2, 0
outside = outside.rotated(angle, rx, ry)
holes = Shape._rotate_points(holes, angle, rx, ry)

# Make (0, 0) actual left bottom corner of the final shape (not the cut)
bounds = outside.bounds
outside = outside.translated(-bounds[0], -bounds[1])
holes = Shape._translate_points(holes, -bounds[0], -bounds[1])

# Add 3% in each direction for the (hypothetical) shrinkage.
shrinkage = 0.03
outside = outside.scaled(1 + shrinkage)
holes = Shape._scale_points(holes, 1 + shrinkage)

props_fulldepth = OperationProps(depth=depth, tab_depth=tab_depth)

operations = Operations(machine_params=machine_params, tool=tool, props=props_fulldepth)
for p in holes:
    operations.helical_drill(x=p.x, y=p.y, d=hole_diameter)
operations.outside_contour(outside, tabs=4)

operations.to_gcode_file("halfbracket.ngc")

viewer_modal(operations)
