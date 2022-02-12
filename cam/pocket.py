import geom, process, toolpath
import math, threading
import pyclipper

def calc_contour(shape, tool, outside=True, displace=0, subtract=None):
    dist = (0.5 * tool.diameter + displace) * geom.GeometrySettings.RESOLUTION
    boundary = geom.PtsToInts(shape.boundary)
    res = process.Shape._offset(boundary, shape.closed, dist if outside else -dist)
    if not res:
        return None

    if subtract:
        res2 = []
        for i in res:
            exp_orient = pyclipper.Orientation(i)
            d = process.Shape._difference(geom.IntPath(i, True), *subtract, return_ints=True)
            if d:
                res2 += [j for j in d if pyclipper.Orientation(j.int_points) == exp_orient]
        if not res2:
            return None
        res2 = [geom.SameOrientation(i.int_points, outside ^ tool.climb) for i in res2]
        tps = [toolpath.Toolpath(geom.Path(geom.PtsFromInts(path), shape.closed), tool) for path in res2]
    else:
        res = [geom.SameOrientation(i, outside ^ tool.climb) for i in res]
        tps = [toolpath.Toolpath(geom.Path(geom.PtsFromInts(path), shape.closed), tool) for path in res]
    return toolpath.Toolpaths(tps)

def contour_parallel(shape, tool, displace=0):
    if not shape.closed:
        raise ValueError("Cannot mill pockets of open polylines")
    tps = []
    tps_islands = []
    boundary = geom.IntPath(shape.boundary)
    boundary_transformed = [ geom.IntPath(i, True) for i in process.Shape._offset(boundary.int_points, True, -tool.diameter * 0.5 * geom.GeometrySettings.RESOLUTION) ]
    islands_transformed = []
    islands_transformed_nonoverlap = []
    islands = shape.islands
    expected_size = min(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1]) / 2.0
    for island in islands:
        pc = pyclipper.PyclipperOffset()
        pts = geom.PtsToInts(island)
        if not pyclipper.Orientation(pts):
            pts = list(reversed(pts))
        pc.AddPath(pts, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        res = pc.Execute((tool.diameter * 0.5 + displace) * geom.GeometrySettings.RESOLUTION)
        if not res:
            return None
        res = [geom.IntPath(it, True) for it in res]
        islands_transformed += res
        islands_transformed_nonoverlap += [it for it in res if not geom.run_clipper_simple(pyclipper.CT_DIFFERENCE, [it], boundary_transformed, bool_only=True)]
    if islands_transformed_nonoverlap:
        islands_transformed_nonoverlap = process.Shape._union(*[i for i in islands_transformed_nonoverlap], return_ints=True)
    for path in islands_transformed_nonoverlap:
        for ints in process.Shape._intersection(path, *boundary_transformed):
            # diff with other islands
            tps_islands += [toolpath.Toolpath(geom.Path(ints, True), tool)]
    displace_now = displace
    stepover = tool.stepover * tool.diameter
    # No idea why this was here given the joinClosePaths call later on is
    # already merging the island paths.
    #for island in tps_islands:
    #    mergeToolpaths(tps, island, tool.diameter)
    while True:
        if geom.is_calculation_cancelled():
            return None
        geom.set_calculation_progress(abs(displace_now), expected_size)
        res = calc_contour(shape, tool, False, displace_now, subtract=islands_transformed)
        if not res:
            break
        displace_now += stepover
        process.mergeToolpaths(tps, res, tool.diameter)
    if len(tps) == 0:
        raise ValueError("Empty contour")
    tps = list(reversed(tps))
    tps = process.joinClosePaths(tps_islands + tps)
    process.findHelicalEntryPoints(tps, tool, shape.boundary, shape.islands, displace)
    geom.set_calculation_progress(expected_size, expected_size)
    return toolpath.Toolpaths(tps)

def axis_parallel(shape, tool, angle, margin, zigzag):
    offset_dist = (0.5 * tool.diameter - margin) * geom.GeometrySettings.RESOLUTION
    boundary = geom.PtsToInts(shape.boundary)
    res = process.Shape._offset(boundary, shape.closed, -offset_dist)
    if not res:
        return None
    boundary_paths = [geom.IntPath(bp, True) for bp in res]

    coords = sum(res, [])
    xcoords = [p[0] / geom.GeometrySettings.RESOLUTION for p in coords]
    ycoords = [p[1] / geom.GeometrySettings.RESOLUTION for p in coords]
    sx, sy, ex, ey = min(xcoords), min(ycoords), max(xcoords), max(ycoords)

    stepover = tool.diameter * tool.stepover
    tps = []
    maxlen = geom.dist(geom.PathPoint(sx, sy), geom.PathPoint(ex, ey))
    #p = (ex + tool.diameter / 2 * cos(angle + pi / 2), sy + tool.diameter / 2 * sin(angle + pi / 2))
    p = (ex, sy + 1 / geom.GeometrySettings.RESOLUTION)
    fsteps = maxlen / stepover
    nsteps = int(math.ceil(fsteps))
    for i in range(nsteps):
        p1 = geom.PathPoint(p[0] - maxlen * math.cos(angle), p[1] - maxlen * math.sin(angle))
        p2 = geom.PathPoint(p[0] + maxlen * math.cos(angle), p[1] + maxlen * math.sin(angle))
        if zigzag and (i & 1):
            p2, p1 = p1, p2
        path = geom.IntPath([p1, p2])
        tree = geom.run_clipper_advanced(pyclipper.CT_INTERSECTION, [], boundary_paths, [path])
        for path2 in pyclipper.OpenPathsFromPolyTree(tree):
            tps.append(toolpath.Toolpath(geom.Path(geom.PtsFromInts(path2), False), tool))
        if i == nsteps - 1:
            frac = fsteps - nsteps
            p = (p[0] + frac * stepover * math.cos(angle + math.pi / 2), p[1] + frac * stepover * math.sin(angle + math.pi / 2))
        else:
            p = (p[0] + stepover * math.cos(angle + math.pi / 2), p[1] + stepover * math.sin(angle + math.pi / 2))
    if not tps:
        raise ValueError("Milled area is empty")
    tps = process.joinClosePaths(tps)
    return toolpath.Toolpaths(tps)
