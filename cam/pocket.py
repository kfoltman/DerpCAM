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

def calculate_tool_margin(shape, tool, displace):
    boundary = geom.IntPath(shape.boundary)
    boundary_transformed = [ geom.IntPath(i, True) for i in process.Shape._offset(boundary.int_points, True, (-tool.diameter * 0.5 - displace) * geom.GeometrySettings.RESOLUTION) ]
    islands = process.Shape._union(*[geom.IntPath(i) for i in shape.islands])
    islands_transformed = []
    islands_transformed_nonoverlap = []
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
    return boundary_transformed, islands_transformed, islands_transformed_nonoverlap

def contour_parallel(shape, tool, displace=0):
    if not shape.closed:
        raise ValueError("Cannot mill pockets of open polylines")
    expected_size = min(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1]) / 2.0
    tps = []
    tps_islands = []
    boundary_transformed, islands_transformed, islands_transformed_nonoverlap = calculate_tool_margin(shape, tool, displace)
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
    boundary_transformed, islands_transformed, islands_transformed_nonoverlap = calculate_tool_margin(shape, tool, margin)

    coords = sum([i.int_points for i in boundary_transformed], [])
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
        tree = geom.run_clipper_advanced(pyclipper.CT_INTERSECTION, [], boundary_transformed, [path])
        treepaths = pyclipper.OpenPathsFromPolyTree(tree)
        tree2 = geom.run_clipper_advanced(pyclipper.CT_DIFFERENCE, [], islands_transformed, [geom.IntPath(path2, True) for path2 in treepaths])
        for path3 in pyclipper.OpenPathsFromPolyTree(tree2):
            tps.append(toolpath.Toolpath(geom.Path(geom.PtsFromInts(path3), False), tool))
        if i == nsteps - 1:
            frac = fsteps - nsteps
            p = (p[0] + frac * stepover * math.cos(angle + math.pi / 2), p[1] + frac * stepover * math.sin(angle + math.pi / 2))
        else:
            p = (p[0] + stepover * math.cos(angle + math.pi / 2), p[1] + stepover * math.sin(angle + math.pi / 2))
    if not tps:
        raise ValueError("Milled area is empty")
    tps = process.joinClosePaths(tps)
    # Add a final pass around the perimeter
    for b in boundary_transformed:
        for d in process.Shape._difference(b, *islands_transformed, return_ints=True):
            tps.append(toolpath.Toolpath(geom.Path(geom.PtsFromInts(d.int_points), True), tool))
    for h in islands_transformed_nonoverlap:
        for ints in process.Shape._intersection(h, *boundary_transformed):
            tps.append(toolpath.Toolpath(geom.Path(ints, True), tool))
    return toolpath.Toolpaths(tps)

pyvlock = threading.RLock()

def hsm_peel(shape, tool, displace=0):
    from shapely.geometry import LineString, MultiLineString, LinearRing, Polygon, GeometryCollection, MultiPolygon
    from shapely.ops import linemerge, nearest_points
    import cam.geometry
    dist = (0.5 * tool.diameter + displace) * geom.GeometrySettings.RESOLUTION
    res = process.Shape._offset(geom.PtsToInts(shape.boundary), True, -dist)
    if len(res) != 1:
        raise ValueError("Empty or multiple subpockets not supported yet")
    boundary_offset = geom.PtsFromInts(res[0])
    boundary = LinearRing([(p.x, p.y) for p in boundary_offset])
    polygon = Polygon(boundary)
    islands_offset = []
    for island in shape.islands:
        island_offsets = process.Shape._offset(geom.PtsToInts(island), True, dist)
        island_offsets = pyclipper.SimplifyPolygons(island_offsets)
        for island_offset in island_offsets:
            island_offset_pts = geom.PtsFromInts(island_offset)
            islands_offset.append(island_offset_pts)
            ii = LinearRing([(p.x, p.y) for p in island_offset_pts])
            polygon = polygon.difference(Polygon(ii))
    inputs = []
    if isinstance(polygon, Polygon):
        inputs.append(polygon)
    elif isinstance(polygon, MultiPolygon):
        inputs += polygon.geoms
    elif isinstance(polygon, GeometryCollection):
        for i in polygon.geoms:
            if isinstance(i, Polygon):
                inputs.append(i)
            elif isinstance(i, MultiPolygon):
                inputs += i.geoms
    tps = []
    for polygon in inputs:
        step = 0.5 * tool.diameter * tool.stepover
        with pyvlock:
            v = cam.voronoi_centers.VoronoiCenters(polygon, tolerence = step)
        tp = cam.geometry.ToolPath(polygon, step, cam.geometry.ArcDir.CW, voronoi=v, generate=True)
        generator = tp._get_arcs(100)
        try:
            while not geom.is_calculation_cancelled():
                progress = max(0, min(1000, next(generator)))
                geom.set_calculation_progress(progress, 1000)
        except StopIteration:
            pass
        gen_path = []
        x, y = tp.start_point.x, tp.start_point.y
        r = 0
        rt = tp.start_radius
        while r < rt:
            r = min(rt, r + 0.5 * tool.diameter * tool.stepover)
            gen_path += [geom.PathPoint(x + r, y), geom.PathArc(geom.PathPoint(x + r, y), geom.PathPoint(x + r, y), geom.CandidateCircle(x, y, r), int(2 * math.pi * r), 0, 2 * math.pi)]
        for item in tp.joined_path_data:
            if isinstance(item, cam.geometry.LineData):
                if not item.safe:
                    if geom.Path(gen_path, False).length():
                        tps.append(toolpath.Toolpath(geom.Path(gen_path, False), tool))
                    gen_path = []
                else:
                    gen_path += [geom.PathPoint(x, y) for x, y in item.path.coords]
            elif isinstance(item, cam.geometry.ArcData):
                steps = max(1, math.ceil(item.radius * abs(item.span_angle)))
                cc = geom.CandidateCircle(item.origin.x, item.origin.y, item.radius)
                sa = math.pi / 2 - item.start_angle
                span = -item.span_angle
                sp = cc.at_angle(sa)
                ep = cc.at_angle(sa + span)
                # Fix slight inaccuracies with line segments
                gen_path += [geom.PathPoint(item.start.x, item.start.y), sp, geom.PathArc(sp, ep, geom.CandidateCircle(item.origin.x, item.origin.y, item.radius), steps, sa, span), geom.PathPoint(item.end.x, item.end.y)]
        if geom.Path(gen_path, False).length():
            tps.append(toolpath.Toolpath(geom.Path(gen_path, False), tool))
        # Add a final pass around the perimeter
        def ls2path(ls):
            return geom.Path([geom.PathPoint(x, y) for x, y in ls.coords], True)
        for i in inputs:
            tps.append(toolpath.Toolpath(ls2path(i.exterior), tool))
            for h in i.interiors:
                tps.append(toolpath.Toolpath(ls2path(h), tool))
    return toolpath.Toolpaths(tps)
