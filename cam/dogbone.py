import geom, process, toolpath
import math

def seg_angle(s, e):
    if e.is_arc():
        return None
    else:
        return math.atan2(e.seg_start().y - s.seg_start().y, e.seg_start().x - s.seg_start().x)

def add_circle(circles, s, m, e, angle, dangle, tool):
    if dangle >= math.pi:
        return
    d = -tool.diameter / 2
    a = angle - (2 * math.pi - (math.pi - dangle)) / 2
    vx = d * math.cos(a)
    vy = d * math.sin(a)
    circles.append(process.Shape.circle(m.x + vx, m.y + vy, tool.diameter * 0.5 + 2 / geom.GeometrySettings.RESOLUTION))

def add_dogbones(shape, tool, outside):
    circles = []
    old_angle = None
    old_s = None
    boundary = geom.Path(shape.boundary, shape.closed)
    if not boundary.orientation() ^ outside:
        boundary = boundary.reverse()
    for s, e in geom.PathSegmentIterator(boundary):
        angle = seg_angle(s, e)
        if old_angle is not None:
            dangle = (angle - old_angle) % (math.pi * 2.0)
            add_circle(circles, old_s, s, e, angle, dangle, tool)
            #print (f"{dangle * 180 / math.pi:0.1f}")
        old_s = s
        old_angle = angle
    s, e = next(geom.PathSegmentIterator(boundary))
    angle = seg_angle(s, e)
    dangle = (angle - old_angle) % (math.pi * 2.0)
    add_circle(circles, old_s, s, e, angle, dangle, tool)
    #print (f"{dangle * 180 / math.pi:0.1f}")
    if outside:
        return process.Shape.difference(shape, *circles)
    else:
        return process.Shape.union(shape, *circles)
