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
    
def pseudotrochoidise(inside, outside, diameter, stepover, circle_size):
    import shapely.geometry
    import shapely.ops
    ilen = inside.length
    lasti = 0
    i = 0
    res = []
    step = stepover * diameter
    while i <= ilen:
        pt = inside.interpolate(i)
        nps = shapely.ops.nearest_points(outside, pt)
        pt2 = nps[0]
        mr = circle_size * diameter
        weight = 0.5
        mx = pt.x + (pt2.x - pt.x) * weight
        my = pt.y + (pt2.y - pt.y) * weight
        margin = pt.distance(pt2)
        addcircle = margin < 3 * diameter * circle_size
        if addcircle:
            ma = geom.CandidateCircle(mx, my, mr).angle(geom.PathPoint(pt.x, pt.y))
            zpt = geom.PathPoint(pt.x, pt.y)
            res.append(zpt)
            res.append(geom.PathArc(zpt, zpt, geom.CandidateCircle(mx, my, mr), int(mr * geom.GeometrySettings.RESOLUTION), ma, 2 * geom.pi))
        # XXXKF substring
        nexti = min(i + step, ilen)
        res += [geom.PathPoint(x, y) for x, y in shapely.ops.substring(inside, i, nexti).coords]
        if i == ilen:
            break
        lasti = i
        i = nexti
    return geom.Path(res, True)

# Original curve + a 1/4 diameter circle every stepover * diameter.
def pseudotrochoidal(shape, diameter, outside, displace, climb, stepover, circle_size):
    import shapely.geometry
    import shapely.ops
    dist = 0.5 * diameter + displace
    dist2 = (0.5 + 2 * circle_size) * diameter + displace
    boundary = shapely.geometry.LinearRing([(p.x, p.y) for p in shape.boundary])
    
    orient = 'right' if not (outside ^ boundary.is_ccw) else 'left'
    inside = boundary.parallel_offset(dist, orient)
    outside = boundary.parallel_offset(dist2, orient)

    if isinstance(inside, shapely.geometry.MultiLineString):
        paths = [pseudotrochoidise(geom, outside, diameter, stepover, circle_size) for geom in inside.geoms]
    else:
        paths = [pseudotrochoidise(inside, outside, diameter, stepover, circle_size)]
    return [ path if path.orientation() == climb else path.reverse() for path in paths ]
    
plain = plain_clipper
