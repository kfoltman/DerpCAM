from example_common import *

width = 250
inner_width = 240
length = 100


tool = Tool(diameter = 1.5, hfeed = 300, vfeed = 50, maxdoc = 0.2)
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

#frame = circle(width / 2, -length, sqrt((width / 2) ** 2 + (2 * length) ** 2), sa = atan2(2 * length, width / 2), ea = pi - atan2(2 * length, width / 2)) + \
#    [( 0, 0), (width, 0)]

outside = Shape.circle(0, 0, width/2)
inner_frame = Shape.circle(0, 0, inner_width / 2)

def curve_transform(x, y):
    pos = 0.5 + 0.5 * x / (inner_width / 2)
    r = width / 2 - 25 + y * 1.4
    angle = (1 - pos) * pi
    return PathPoint(r * cos(angle), r * sin(angle))

#def curve_transform(x, y):
#    ax = x / width - 0.5
#    ay = y / length
#    angle = pi * ax * 1.1
#    bx = ax * cos(angle) + ay * sin(angle)
#    by =-ax * sin(angle) + ay * cos(angle)
#    return width / 2 + width * bx / 2, width * by / 1.6 + 20
    
def curve2_transform(x, y):
    y += 10 * cos((x - width / 2) / (width / 2) * pi)
    return PathPoint(x, y)

init_app()
font = "Gentium"
label = text_to_shapes(-inner_width / 2, -length / 2, inner_width, length, "BLACKPITTS", font, 28, -1, 0)
label2 = text_to_shapes(-inner_width / 2, -length / 2, inner_width, length, "22", font, 120, -1, 0)
label = [shape.warp(curve_transform) for shape in label]

props_fulldepth = OperationProps(depth=depth, tab_depth=tab_depth)
props_engrave = OperationProps(depth=engrave_depth)
operations = Operations(machine_params=machine_params, tool=tool, props=props_fulldepth)
for label_item in label + label2:
    operations.pocket(label_item, props=props_engrave)
operations.engrave(inner_frame, props=props_engrave)
operations.outside_contour(outside, tabs=4)
operations.to_gcode_file("textpath.ngc")
viewer_modal(operations)
