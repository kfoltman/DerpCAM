import sys
sys.path += '..'

from process import *
from geom import *
from gcodegen import *
from view import *
import ezdxf

# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1

if len(sys.argv) < 2:
    print ("Usage: python3 examples/dxf.py <input.dxf> [<output.ngc>]")
    sys.exit(0)

doc = ezdxf.readfile(sys.argv[1])

msp = doc.modelspace()

for entity in msp:
    if entity.dxftype() not in ("LWPOLYLINE", "CIRCLE", "TEXT"):
        print ("Unhandled entity type", entity)

def get_props(s):
    tokens = s.split()
    props = {}
    for t in tokens[1:]:
        pos = t.index("=")
        props[t[:pos]] = t[pos+1:]
    return tokens[0], props

def get_dimension(dim):
    if dim.endswith("mm"):
        return float(dim[:-2])
    elif dim.endswith("cm"):
        return float(dim[:-2]) * 10
    elif dim.endswith("m"):
        return float(dim[:-2]) * 1000
    elif dim.endswith("in"):
        return float(dim[:-2]) * 25.4
    else:
        raise ValueError("Unknown dimension unit: %s" % dim)

material_depth_mm = None
tab_depth_mm = None
tool = None

engrave_depths = {}

def get_entity_color(entity):
    color = entity.dxf.color
    if color == 256: # ByLayer
        color = doc.layers.get(entity.dxf.layer).dxf.color
    return color

texts = msp.query("TEXT")
for entity in texts:
    if entity.dxf.layer == "CAM":
        text = entity.dxf.text
        color = get_entity_color(entity)
        keyword, props = get_props(text)
        if keyword == "material":
            material_depth_mm = get_dimension(props['depth'])
        elif keyword == "tab":
            tab_depth_mm = get_dimension(props['depth'])
        elif keyword == "engrave":
            engrave_depths[color] = get_dimension(props['depth'])
        elif keyword == "tool":
            hfeed = get_dimension(props['hfeed'])
            maxdoc = get_dimension(props['doc'])
            if 'vfeed' in props:
                vfeed = get_dimension(props['vfeed'])
            else:
                vfeed = Tool.calc_vfeed(hfeed, float(props['ramp_angle']))
            tool = Tool(diameter = get_dimension(props['diameter']), hfeed = hfeed, vfeed = vfeed, maxdoc = maxdoc)
        else:
            raise ValueError("Unknown CAM keyword: " + text)

if tab_depth_mm is None:
    tab_depth_mm = max(0, material_depth_mm - 2)
if tool is None:
    raise ValueError("Tool not specified in the CAM layer.")

props_fulldepth = OperationProps(depth=-material_depth_mm, tab_depth=-tab_depth_mm)

operations = Operations(safe_z=safe_z, semi_safe_z=semi_safe_z, tool=tool, props=props_fulldepth)

def polyline_to_points(entity):
    points = []
    lastx, lasty = entity[-1][0:2]
    lastbulge = entity[-1][4]
    for point in entity:
        x, y = point[0:2]
        if lastbulge:
            theta = 4 * atan(lastbulge)
            dx, dy = x - lastx, y - lasty
            mx, my = weighted((lastx, lasty), (x, y), 0.5)
            angle = atan2(dy, dx)
            dist = sqrt(dx * dx + dy * dy)
            d = dist / 2
            r = abs(d / sin(theta / 2))
            c = d / tan(theta / 2)
            cx = mx - c * sin(angle)
            cy = my + c * cos(angle)
            sa = atan2(lasty - cy, lastx - cx)
            ea = sa + theta
            points += circle(cx, cy, r, 1000, sa, ea)
            points.append((x, y))
        else:
            points.append((x, y))
        lastbulge = point[4]
        lastx, lasty = x, y
    return points, entity.closed

polylines = msp.query("LWPOLYLINE")

polygons = []
engrave_paths = []
for entity in polylines:
    points, closed = polyline_to_points(entity)
    color = get_entity_color(entity)
    if closed and color not in engrave_depths:
        polygons.append((points, entity))
    else:
        if color not in engrave_depths:
            raise ValueError("Engraving depth not specified for color %s" % color)
        engrave_paths.append((points, entity.closed, engrave_depths[color], entity))

for points, closed, depth, entity in engrave_paths:
    # XXXKF start depth
    props = OperationProps(depth=-depth, tab_depth=None)
    operations.engrave(Shape(points, closed, []), props = props)

circles = msp.query("CIRCLE")
for entity in circles:
    center = entity.dxf.center
    operations.helical_drill(center[0], center[1], 2 * entity.dxf.radius)

for npass in (1, 2, ):
    for points, entity in polygons:
        shape = Shape(points, True, [])
        linetype = entity.dxf.linetype
        if linetype == 'ByLayer':
            layer = doc.layers.get(entity.dxf.layer)
            linetype = layer.dxf.linetype
            #linetype = entity.dxf.layer
        ntabs = int(min(6, max(2, path_length(points) // 100)))
        if linetype == 'DOTTINY':
            if npass == 1:
                operations.inside_contour(shape, tabs=ntabs)
        elif linetype == 'CONTINUOUS':
            if npass == 2:
                operations.outside_contour(shape, tabs=ntabs)
        elif linetype == 'BORDER':
            if npass == 1:
                operations.pocket(shape)
        else:
            print ("Unknown line type", linetype, "- must be CONTINUOUS (outside), DOTTINY (inside) or BORDER (pocket)")
            #operations.pocket(shape)
            operations.outside_contour(shape, tabs=0)

if len(sys.argv) >= 3:
    operations.to_gcode_file(sys.argv[2])
viewer_modal(operations)

