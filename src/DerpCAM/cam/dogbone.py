from DerpCAM.common import geom
from DerpCAM.cam import shapes, toolpath
from DerpCAM.gui import propsheet
import math

class DogboneMode(propsheet.EnumClass):
    DISABLED = 0
    CORNER = 1
    LONG_EDGE = 2
    SHORT_EDGE = 3
    descriptions = [
        (DISABLED, "None"),
        (CORNER, "Corners"),
        (LONG_EDGE, "Long edge"),
        (SHORT_EDGE, "Short edge"),
    ]

def seg_angle(s, e):
    if e.is_arc():
        return None
    else:
        return math.atan2(e.seg_start().y - s.seg_start().y, e.seg_start().x - s.seg_start().x)

def slope(angle):
    return abs(math.sin(angle))

def add_circle(circles, s, m, e, angle, dangle, tool, mode, orientation):
    if dangle >= math.pi:
        return
    d1 = geom.dist(s, m)
    d2 = geom.dist(m, e)
    d = tool.diameter / 2
    if abs(d1 - d2) < 1 / geom.GeometrySettings.RESOLUTION and mode in (DogboneMode.LONG_EDGE, DogboneMode.SHORT_EDGE):
        d1 = slope(angle - dangle)
        d2 = slope(angle)
        if abs(d1 - d2) < 0.01:
            mode = DogboneMode.CORNER
    if mode == DogboneMode.CORNER:
        #a = (angle - (2 * math.pi - (math.pi - dangle)) / 2)
        a = angle + math.pi / 2 - dangle / 2
    elif mode == DogboneMode.LONG_EDGE:
        if d1 >= d2:
            a = angle
        else:
            a = angle - dangle + math.pi
    elif mode == DogboneMode.SHORT_EDGE:
        if d1 <= d2:
            a = angle
        else:
            a = angle - dangle + math.pi
    vx = d * math.cos(a)
    vy = d * math.sin(a)
    circles.append(shapes.Shape.circle(m.x + vx, m.y + vy, tool.diameter * 0.5 + 2 / geom.GeometrySettings.RESOLUTION))

def add_dogbones(shape, tool, outside, mode):
    circles = []
    old_angle = None
    old_s = None
    boundary = geom.Path(shape.boundary, shape.closed)
    orientation = boundary.orientation()
    if not orientation ^ outside:
        boundary = boundary.reverse()
    for s, e in geom.PathSegmentIterator(boundary):
        angle = seg_angle(s, e)
        if old_angle is not None:
            dangle = (angle - old_angle) % (math.pi * 2.0)
            add_circle(circles, old_s, s, e, angle, dangle, tool, mode, orientation)
        old_s = s
        old_angle = angle
    s, e = next(geom.PathSegmentIterator(boundary))
    angle = seg_angle(s, e)
    dangle = (angle - old_angle) % (math.pi * 2.0)
    add_circle(circles, old_s, s, e, angle, dangle, tool, mode, orientation)
    if not orientation:
        shape.boundary = geom.Path(shape.boundary, True).reverse().nodes
    if outside:
        return shapes.Shape.difference2(shape, *circles)
    else:
        return shapes.Shape.union2(shape, *circles)
