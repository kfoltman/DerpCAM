from DerpCAM.common import geom
from DerpCAM.cam import shapes, toolpath
import math

def plain_clipper(shape, diameter, outside, displace, climb):
    dist = (0.5 * diameter + displace) * geom.GeometrySettings.RESOLUTION
    boundary = geom.PtsToInts(shape.boundary)
    res = shapes.Shape._offset(boundary, shape.closed, dist if outside else -dist)
    if not res:
        return None
    res = [geom.SameOrientation(i, outside ^ climb) for i in res]
    paths = [geom.Path(geom.PtsFromInts(path), shape.closed) for path in res]
    if geom.GeometrySettings.simplify_arcs:
        paths = [path.lines_to_arcs() for path in paths]
    if geom.GeometrySettings.simplify_lines:
        paths = [path.optimize_lines() for path in paths]
    return paths
    
def plain_shapely(shape, diameter, outside, displace, climb):
    import shapely.geometry
    dist = 0.5 * diameter + displace
    boundary = shapely.geometry.LinearRing([(p.x, p.y) for p in shape.boundary])
    res = boundary.parallel_offset(dist, 'right' if not (outside ^ boundary.is_ccw) else 'left')
    if isinstance(res, shapely.geometry.LineString):
        paths = [geom.Path([geom.PathPoint(x, y) for x, y in res.coords], True)]
    else:
        paths = [geom.Path([geom.PathPoint(x, y) for x, y in item.coords], True) for item in res.geoms]
    return [ path if path.orientation() == climb else path.reverse() for path in paths]
    
def pseudotrochoidise(inside, outside, diameter, stepover, circle_size, dest_orientation, climb, progress, tlength):
    import shapely.geometry
    import shapely.ops
    lasti = 0
    i = 0
    res = []
    step = stepover * diameter
    inside = shapely.geometry.LinearRing([(pt.x, pt.y) for pt in inside.nodes])
    ilen = inside.length
    if inside.is_ccw != dest_orientation:
        inside = shapely.geometry.LinearRing(inside.coords[::-1])
    lastpt2 = None
    lastpt2proj = None
    lastc = None
    lasti = None
    segmentation = []
    outlen = 0
    while i <= ilen:
        if geom.is_calculation_cancelled():
            return None
        step2 = 1
        pt = inside.interpolate(i)
        while True:
            nps = shapely.ops.nearest_points(outside, pt)
            pt2orig = nps[0]
            mr = circle_size * diameter
            if step2 == 1:
                pt2 = geom.PathPoint(nps[0].x, nps[0].y)
            else:
                # Find a closest match on the original outline, then pick something at step2 * 100%
                # distance from it
                if lastpt2proj is None:
                    lastpt2proj = prev = outside.project(lastpt2)
                else:
                    prev = lastpt2proj
                curr = outside.project(pt2orig)
                # Wrap around
                if prev > 0.9 * outside.length and curr < 0.1 * outside.length:
                    curr = outside.length
                pt2s1 = outside.interpolate(prev + (curr - prev) * step2)
                # Another estimate is a weighted average of the last and the current point
                pt2s2 = shapely.geometry.Point(lastpt2.x + (pt2orig.x - lastpt2.x) * step2, lastpt2.y + (pt2orig.y - lastpt2.y) * step2)
                nps = shapely.ops.nearest_points(outside, pt2s2)
                pt2s2 = nps[0]
                # Pick the better of the two
                if abs(pt2s1.distance(pt) - mr) < abs(pt2s2.distance(pt) - mr):
                    pt2 = geom.PathPoint(pt2s1.x, pt2s1.y)
                else:
                    pt2 = geom.PathPoint(pt2s2.x, pt2s2.y)
            pt3 = geom.weighted(pt, pt2, 2) # far end of the circle, opposite pt
            # Shorten the step if the opposite side of the circle is too far
            # away from the corresponding one for the previous step
            if lastc is not None:
                edgedist = lastc.dist(pt3)
                if edgedist > step + 0.5 / geom.GeometrySettings.RESOLUTION and step2 > 0.1:
                    newstep = min(0.95, step / edgedist) * (i - lasti)
                    if newstep < 0.1:
                        # Abrupt turns may cause discontinuities in pt2(i)/pt3(i)
                        # leading to failures of convergence. In those cases, walk
                        # along the outside path instead.
                        step2 *= 0.9
                    else:
                        i = lasti + newstep
                        pt = inside.interpolate(i)
                    continue
            if lasti is not None:
                subpath = geom.Path([geom.PathPoint(x, y) for x, y in shapely.ops.substring(inside, lasti, i).coords], False)
                if geom.GeometrySettings.simplify_arcs:
                    subpath = subpath.lines_to_arcs()
                outlen += subpath.length()
                res += subpath.nodes
            break
        lastpt2 = pt2orig
        lastpt2proj = None
        lastc = pt3
        nexti = min(i + 1.5 * step, ilen)
        mr2 = geom.dist(geom.PathPoint(pt.x, pt.y), pt2)
        if abs(mr - mr2) > 1 / geom.GeometrySettings.RESOLUTION:
            print (f"Warning: possible discrepancy in calculated radius {mr2} vs {mr}")
        mr = mr2
        c = geom.CandidateCircle(pt2.x, pt2.y, mr)
        arclen = 2 * math.pi * mr
        zpt = geom.PathPoint(pt.x, pt.y)
        ma = c.angle(zpt)
        zpt = c.at_angle(ma)
        if res:
            arclen += res[-1].seg_end().dist(zpt)
        res.append(zpt)
        res.append(geom.PathArc(zpt, zpt, c, int(mr * geom.GeometrySettings.RESOLUTION), ma, 2 * math.pi * (1 if climb else -1)))
        segmentation.append((outlen, outlen + arclen, toolpath.HelicalEntry(pt2, mr2, ma, climb)))
        outlen += arclen
        if i == ilen:
            break
        lasti = i
        i = nexti
        geom.set_calculation_progress(progress + i, tlength)
    return geom.Path(res, True), segmentation

# Original curve + a 1/4 diameter circle every stepover * diameter.
def pseudotrochoidal(shape, diameter, is_outside, displace, climb, stepover, circle_size):
    import shapely.geometry
    import shapely.ops
    dist2 = (0.5 + circle_size) * diameter + displace
    ddist2 = -circle_size * diameter

    # Use much higher resolution here, because the circles are tiny
    resolution = geom.GeometrySettings.RESOLUTION * max(4.0 / circle_size, 4.0 / stepover, 3)
    def PtsToInts(points):
        return [(round(p.x * resolution), round(p.y * resolution)) for p in points]
    def PtsFromInts(points):
        return [geom.PathPoint(x / resolution, y / resolution) for x, y in points]

    res_out = shapes.Shape._offset(PtsToInts(shape.boundary), True, (dist2 if is_outside else -dist2) * resolution)
    if not res_out:
        return None
    outside = shapely.geometry.MultiLineString([[(pt.x, pt.y) for pt in PtsFromInts(path + path[0:1])] for path in res_out])

    res = []
    for i in res_out:
        res_item = shapes.Shape._offset(i, True, (ddist2 if is_outside else -ddist2) * resolution)
        if res_item:
            res += res_item
    if not res:
        return None
    inside = [geom.Path(PtsFromInts(path), shape.closed) for path in res]
    tlength = sum([path.length() for path in inside])

    paths = []
    progress = 0
    for subpath in inside:
        paths.append(pseudotrochoidise(subpath, outside, diameter, stepover, circle_size, is_outside ^ climb, climb, progress, tlength))
        progress += subpath.length()
    geom.set_calculation_progress(progress, tlength)
    if None in paths:
        return None
    return paths
    
plain = plain_clipper
