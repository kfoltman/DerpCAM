import geom, process, toolpath

def plain_clipper(shape, diameter, outside, displace, climb):
    dist = (0.5 * diameter + displace) * geom.GeometrySettings.RESOLUTION
    boundary = geom.PtsToInts(shape.boundary)
    res = process.Shape._offset(boundary, shape.closed, dist if outside else -dist)
    if not res:
        return None
    res = [geom.SameOrientation(i, outside ^ climb) for i in res]
    return [geom.Path(geom.PtsFromInts(path), shape.closed) for path in res]
    
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
    
def pseudotrochoidise(inside, outside, diameter, stepover, circle_size, dest_orientation, climb):
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
    lastc = None
    lasti = None
    segmentation = []
    outlen = 0
    while i <= ilen:
        step2 = 1
        while True:
            pt = inside.interpolate(i)
            nps = shapely.ops.nearest_points(outside, pt)
            if step2 == 1:
                pt2 = geom.PathPoint(nps[0].x, nps[0].y)
            else:
                # Find a point somewhere in between, then find a closest match on the original outline
                pt2 = geom.weighted(lastpt2, geom.PathPoint(nps[0].x, nps[0].y), step2)
                nps = shapely.ops.nearest_points(outside, shapely.geometry.Point(pt2.x, pt2.y))
                pt2 = geom.PathPoint(nps[0].x, nps[0].y)
            pt3 = geom.weighted(pt, pt2, 2) # far end of the circle, opposite pt
            mr = circle_size * diameter
            # Shorten the step if the opposite side of the circle is too far
            # away from the corresponding one for the previous step
            if lastc is not None and lastc.dist(pt3) > 1.01 * step:
                newstep = 0.9 * (i - lasti)
                if newstep < 0.1:
                    step2 = 0.9 * step2
                    continue
                else:
                    i = lasti + newstep
                    continue
            if lasti is not None:
                outlen += i - lasti
                res += [geom.PathPoint(x, y) for x, y in shapely.ops.substring(inside, lasti, i).coords]
            break
        lastpt2 = pt2
        lastc = pt3
        nexti = min(i + 2 * step, ilen)
        c = geom.CandidateCircle(pt2.x, pt2.y, mr)
        arclen = 2 * geom.pi * mr
        zpt = geom.PathPoint(pt.x, pt.y)
        ma = c.angle(zpt)
        res.append(zpt)
        res.append(geom.PathArc(zpt, zpt, c, int(mr * geom.GeometrySettings.RESOLUTION), ma, 2 * geom.pi * (1 if climb else -1)))
        segmentation.append((outlen, outlen + arclen, process.HelicalEntry(pt2, mr, ma)))
        outlen += arclen
        if i == ilen:
            break
        lasti = i
        i = nexti
    return geom.Path(res, True), segmentation

# Original curve + a 1/4 diameter circle every stepover * diameter.
def pseudotrochoidal(shape, diameter, is_outside, displace, climb, stepover, circle_size):
    import shapely.geometry
    import shapely.ops
    dist2 = (0.5 + circle_size) * diameter + displace
    ddist2 = -circle_size * diameter

    res_out = process.Shape._offset(geom.PtsToInts(shape.boundary), True, (dist2 if is_outside else -dist2) * geom.GeometrySettings.RESOLUTION)
    if not res_out:
        return None
    outside = shapely.geometry.MultiLineString([[(pt.x, pt.y) for pt in geom.PtsFromInts(path + path[0:1])] for path in res_out])

    res = []
    for i in res_out:
        res_item = process.Shape._offset(i, True, (ddist2 if is_outside else -ddist2) * geom.GeometrySettings.RESOLUTION)
        if res_item:
            res += res_item
    if not res:
        return None
    inside = [geom.Path(geom.PtsFromInts(path), shape.closed) for path in res]

    paths = [pseudotrochoidise(geom, outside, diameter, stepover, circle_size, is_outside ^ climb, climb) for geom in inside]
    return paths
    
plain = plain_clipper
