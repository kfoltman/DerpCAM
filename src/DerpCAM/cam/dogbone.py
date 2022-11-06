from DerpCAM.common import geom
from DerpCAM.cam import shapes, toolpath
from DerpCAM.gui import propsheet
import math

class DogboneMode(propsheet.EnumClass):
    DISABLED = 0
    CORNER = 1
    LONG_EDGE = 2
    SHORT_EDGE = 3
    VERTICAL = 4
    HORIZONTAL = 5
    descriptions = [
        (DISABLED, "None"),
        (CORNER, "Corners"),
        (LONG_EDGE, "Long edge"),
        (SHORT_EDGE, "Short edge"),
        (VERTICAL, "Vertical"),
        (HORIZONTAL, "Horizontal"),
    ]

def seg_angle(s, e):
    if e.is_arc():
        if e.sspan >= 0:
            return e.sstart + math.pi / 2, e.sstart + e.sspan + math.pi / 2
        else:
            return e.sstart - math.pi / 2, e.sstart + e.sspan - math.pi / 2
    else:
        a = math.atan2(e.seg_start().y - s.seg_start().y, e.seg_start().x - s.seg_start().x)
        return a, a

def slope(angle):
    return abs(math.sin(angle))

def add_circle(circles, s, m, e, old_angle, angle, tool, mode, orientation, shape, is_refine):
    dangle = (angle - old_angle)
    if math.sin(dangle) < 0.001:
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
        if dangle < 0:
            a = angle + math.pi / 2 + (2 * math.pi - dangle) / 2
        else:
            a = angle + math.pi / 2 - dangle / 2
        eangle = 2 * math.pi - (angle - a) % (2 * math.pi)
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
    elif mode == DogboneMode.HORIZONTAL or mode == DogboneMode.VERTICAL:
        if d1 <= d2:
            a = angle
        else:
            a = angle - dangle + math.pi
        threshold = 0.01
        if abs(math.sin(a) if mode == DogboneMode.VERTICAL else math.cos(a)) > threshold:
            if d1 >= d2:
                a = angle
            else:
                a = angle - dangle + math.pi
            if abs(math.sin(a) if mode == DogboneMode.VERTICAL else math.cos(a)) > threshold:
                return
    eangle = 2 * math.pi - (angle - a) % (2 * math.pi)
    # Arbitrary cutoffs to avoid weird isolated circles - will ignore
    # for very acute angles and create a sausage for milder ones
    # Note that this is the half-angle of the corner
    if eangle < math.pi / 8:
        return
    if eangle < math.pi / 3:
        is_refine = True
    vx = d * math.cos(a)
    vy = d * math.sin(a)
    r = tool.diameter * 0.5 + 2 / geom.GeometrySettings.RESOLUTION
    if is_refine:
        circles.append(shapes.Shape.sausage(m.x + vx * 2, m.y + vy * 2, m.x + vx, m.y + vy, r))
    else:
        circles.append(shapes.Shape.circle(m.x + vx, m.y + vy, r))

def r2d(radians):
    return (180 * radians / math.pi) % 360.0

def add_dogbones(shape, tool, outside, mode, is_refine):
    circles = []
    old_angle = None
    old_s = None
    boundary = geom.Path(shape.boundary, shape.closed).lines_to_arcs()
    orientation = boundary.orientation()
    if not orientation ^ outside:
        boundary = boundary.reverse()
    boundary = boundary.lines_to_arcs()
    for s, e in geom.PathSegmentIterator(boundary):
        angle, next_angle = seg_angle(s, e)
        valid = False
        if old_angle is not None and (s.dist(e) >= 0.01 or e.is_arc()):
            valid = True
            if e.is_arc():
                next_s = geom.PathPoint(s.x + 5 * math.cos(angle), s.y + 5 * math.sin(angle))
                add_circle(circles, old_s, s, next_s, old_angle, angle, tool, mode, orientation, shape, is_refine)
                s = geom.PathPoint(e.p2.x - 5 * math.cos(next_angle), e.p2.y - 5 * math.sin(next_angle))
            else:
                add_circle(circles, old_s, s, e, old_angle, angle, tool, mode, orientation, shape, is_refine)
        old_s = s
        if old_angle is None or valid:
            old_angle = next_angle
    if old_angle is not None:
        s, e = next(geom.PathSegmentIterator(boundary))
        angle, next_angle = seg_angle(s, e)
        dangle = (angle - old_angle) % (math.pi * 2.0)
        add_circle(circles, old_s, s, e, old_angle, angle, tool, mode, orientation, shape, is_refine)
    if not orientation:
        shape.boundary = geom.Path(shape.boundary, True).reverse().nodes
    if outside:
        return shapes.Shape.difference2(shape, *circles)
    else:
        return shapes.Shape.union2(shape, *circles)
