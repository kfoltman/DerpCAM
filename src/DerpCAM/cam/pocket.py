from DerpCAM.common import geom
from . import shapes, toolpath, milling_tool
import math, threading
import pyclipper

def calc_contour(shape, tool, outside=True, displace=0, subtract=None):
    dist = (0.5 * tool.diameter + displace) * geom.GeometrySettings.RESOLUTION
    boundary = geom.PtsToInts(shape.boundary)
    res = shapes.Shape._offset(boundary, shape.closed, dist if outside else -dist)
    if not res:
        return None

    if subtract:
        res2 = []
        for i in res:
            exp_orient = pyclipper.Orientation(i)
            d = shapes.Shape._difference(geom.IntPath(i, True), *subtract, return_ints=True)
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
    boundary_transformed = [ geom.IntPath(i, True) for i in shapes.Shape._offset(boundary.int_points, True, (-tool.diameter * 0.5 - displace) * geom.GeometrySettings.RESOLUTION) ]
    islands_transformed = []
    islands_transformed_nonoverlap = []
    boundary_transformed_nonoverlap = boundary_transformed
    if shape.islands:
        islands = shapes.Shape._union(*[geom.IntPath(i).force_orientation(True) for i in shape.islands])
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
            islands_transformed_nonoverlap = shapes.Shape._union(*[i for i in islands_transformed_nonoverlap], return_ints=True)
        tree = geom.run_clipper_advanced(pyclipper.CT_DIFFERENCE,
            subject_polys=[i for i in boundary_transformed],
            clipper_polys=[i for i in islands_transformed])
        if tree:
            boundary_transformed_nonoverlap = [geom.IntPath(i, True) for i in pyclipper.ClosedPathsFromPolyTree(tree)]
        else:
            boundary_transformed_nonoverlap = []
    return boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap

def contour_parallel(shape, tool, displace=0):
    if not shape.closed:
        raise ValueError("Cannot mill pockets of open polylines")
    expected_size = min(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1]) / 2.0
    tps = []
    tps_islands = []
    boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap = calculate_tool_margin(shape, tool, displace)
    for path in islands_transformed_nonoverlap:
        for ints in shapes.Shape._intersection(path, *boundary_transformed):
            # diff with other islands
            tps_islands += [toolpath.Toolpath(geom.Path(ints, True), tool)]
    displace_now = displace
    stepover = tool.stepover * tool.diameter
    # No idea why this was here given the joinClosePaths call later on is
    # already merging the island paths.
    #for island in tps_islands:
    #    toolpath.mergeToolpaths(tps, island, tool.diameter)
    while True:
        if geom.is_calculation_cancelled():
            return None
        geom.set_calculation_progress(abs(displace_now), expected_size)
        res = calc_contour(shape, tool, False, displace_now, subtract=islands_transformed)
        if not res:
            break
        displace_now += stepover
        toolpath.mergeToolpaths(tps, res, tool.diameter)
    if len(tps) == 0:
        raise ValueError("Empty contour")
    tps = list(reversed(tps))
    tps = toolpath.joinClosePaths(tps_islands + tps)
    toolpath.findHelicalEntryPoints(tps, tool, shape.boundary, shape.islands, displace)
    geom.set_calculation_progress(expected_size, expected_size)
    return toolpath.Toolpaths(tps)

class AxisParallelRow(object):
    def __init__(self):
        self.slices = []
        self.areas = []
        self.connectors = []
    def add_slice(self, slice):
        self.slices.append(slice)
    def add_area(self, area):
        self.areas.append(area)
    def add_connector(self, connector):
        self.connectors.append(connector)
    def pop_coll(self, coll, pt, allow_reverse):
        eps = 2.0 / geom.GeometrySettings.RESOLUTION
        for i, c in enumerate(coll):
            if geom.dist(c.seg_start(), pt) <= eps:
                del coll[i]
                return c
            if allow_reverse and geom.dist(c.seg_end(), pt) <= eps:
                del coll[i]
                return c.reverse()
    def pop_slice(self, pt):
        return self.pop_coll(self.slices, pt, False)
    def pop_connector(self, pt):
        return self.pop_coll(self.connectors, pt, True)
    def dump(self):
        if self.areas:
            print ("Begin")
            print ("Slices", self.slices)
            print ("Areas", self.areas)
            print ("Connectors", self.connectors)
            print ("End")

def get_areas(rows, tool):
    tps = []
    for row in rows:
        for area in row.areas:
            tps.append(toolpath.Toolpath(area, tool))
    return tps

def get_slices(rows, tool):
    tps = []
    for row in rows:
        for slice in row.slices:
            tps.append(toolpath.Toolpath(slice, tool))
    return tps

def get_connectors(rows, tool):
    tps = []
    for row in rows:
        for conn in row.connectors:
            tps.append(toolpath.Toolpath(conn, tool))
    return tps

def process_rows(rows, tool):
    tps = []
    finished = False
    while not finished:
        finished = True
        path = []
        for row in rows:
            if path:
                slice = row.pop_slice(path[-1].seg_end())
                if slice:
                    path.append(slice)
                else:
                    tps.append(toolpath.Toolpath(geom.Path(sum([i.nodes for i in path], []), False), tool))
                    path = []
            if not path:
                if not row.slices:
                    continue
                slice = row.slices.pop(0)
                path.append(slice)
            conn = row.pop_connector(path[-1].seg_end())
            if conn:
                path.append(conn)
            else:
                tps.append(toolpath.Toolpath(geom.Path(sum([i.nodes for i in path], []), False), tool))
                path = []
            finished = False
        if path:
            tps.append(toolpath.Toolpath(geom.Path(sum([i.nodes for i in path], []), False), tool))
    return tps

def axis_parallel(shape, tool, angle, margin, zigzag):
    offset_dist = (0.5 * tool.diameter - margin) * geom.GeometrySettings.RESOLUTION
    boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap = calculate_tool_margin(shape, tool, margin)

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
    rows = []
    mx = maxlen * math.cos(angle)
    my = maxlen * math.sin(angle)
    dx = stepover * math.cos(angle + math.pi / 2)
    dy = stepover * math.sin(angle + math.pi / 2)
    # Clipper bug workaround! A difference of a horizontal line and a contour that is *above* the line will be null,
    # instead of the whole line.
    subtract_hack = [geom.IntPath([geom.PathPoint(sx, sy - 1), geom.PathPoint(sx + 1, sy - 1), geom.PathPoint(sx, sy - 2)], False)]
    for i in range(nsteps):
        p1 = geom.PathPoint(p[0] - mx, p[1] - my)
        p2 = geom.PathPoint(p[0] + mx, p[1] + my)
        path = geom.IntPath([p2, p1]) if zigzag and (i & 1) else geom.IntPath([p1, p2])
        tree = geom.run_clipper_advanced(pyclipper.CT_INTERSECTION, [], boundary_transformed, [path])
        if islands_transformed:
            treepaths = pyclipper.OpenPathsFromPolyTree(tree)
            tree2 = geom.run_clipper_advanced(pyclipper.CT_DIFFERENCE, subtract_hack, islands_transformed, [geom.IntPath(path2, True) for path2 in treepaths])
        else:
            tree2 = tree
        row = AxisParallelRow()
        for path3 in pyclipper.OpenPathsFromPolyTree(tree2):
            row.add_slice(geom.Path(geom.PtsFromInts(path3), False))
        frac = fsteps - nsteps if i == nsteps - 1 else 1
        p = (p[0] + frac * dx, p[1] + frac * dy)
        p3 = geom.PathPoint(p[0] - mx, p[1] - my)
        p4 = geom.PathPoint(p[0] + mx, p[1] + my)
        slice = geom.IntPath([p1, p2, p4, p3])

        if False: # use for debugging
            tree = geom.run_clipper_advanced(pyclipper.CT_INTERSECTION, [slice], boundary_transformed, [])
            treepaths = pyclipper.ClosedPathsFromPolyTree(tree)
            if islands_transformed:
                tree2 = geom.run_clipper_advanced(pyclipper.CT_DIFFERENCE, [geom.IntPath(path2, True) for path2 in treepaths], islands_transformed, [])
            else:
                tree2 = tree
            for path3 in pyclipper.ClosedPathsFromPolyTree(tree2):
                row.add_area(geom.Path(geom.PtsFromInts(path3), True))
        #tree = geom.run_clipper_advanced(pyclipper.CT_INTERSECTION, [], [slice], [geom.IntPath(path.int_points + path.int_points[0:1], True) for path in boundary_transformed + islands_transformed_nonoverlap])
        if zigzag:
            tree = geom.run_clipper_advanced(pyclipper.CT_INTERSECTION, [], [slice], [geom.IntPath(path.int_points + path.int_points[0:1], True) for path in boundary_transformed_nonoverlap] +
                [geom.IntPath(pyclipper.ReversePath(path.int_points + path.int_points[0:1]), True) for path in islands_transformed_nonoverlap])
            for path3 in pyclipper.OpenPathsFromPolyTree(tree):
                row.add_connector(geom.Path(geom.PtsFromInts(path3), False))
        rows.append(row)
    #return toolpath.Toolpaths(get_slices(rows, tool))
    #return toolpath.Toolpaths(get_areas(rows, tool))
    #return toolpath.Toolpaths(get_connectors(rows, tool))
    tps = process_rows(rows, tool)
    if not tps:
        raise ValueError("Milled area is empty")
    # Add a final pass around the perimeter
    for b in boundary_transformed:
        for d in shapes.Shape._difference(b, *islands_transformed, return_ints=True):
            tps.append(toolpath.Toolpath(geom.Path(geom.PtsFromInts(d.int_points), True), tool))
    for h in islands_transformed_nonoverlap:
        for ints in shapes.Shape._intersection(h, *boundary_transformed):
            tps.append(toolpath.Toolpath(geom.Path(ints, True), tool))
    return toolpath.Toolpaths(tps)

pyvlock = threading.RLock()

def objects_to_polygons(polygon):
    from shapely.geometry import Polygon, GeometryCollection, MultiPolygon
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
    return inputs

def shape_to_polygons(shape, tool, displace=0, from_outside=False):
    from shapely.geometry import LinearRing, Polygon
    tdist = (0.5 * tool.diameter + displace) * geom.GeometrySettings.RESOLUTION
    if from_outside:
        subpockets = shapes.Shape._offset(geom.PtsToInts(shape.boundary), True, -tdist + tool.diameter * geom.GeometrySettings.RESOLUTION)
    else:
        subpockets = shapes.Shape._offset(geom.PtsToInts(shape.boundary), True, -tdist)
    all_inputs = []
    for subpocket in subpockets:
        boundary_offset = geom.PtsFromInts(subpocket)
        boundary = LinearRing([(p.x, p.y) for p in boundary_offset])
        polygon = Polygon(boundary)
        islands_offset = []
        for island in shape.islands:
            island_offsets = shapes.Shape._offset(geom.PtsToInts(island), True, tdist)
            island_offsets = pyclipper.SimplifyPolygons(island_offsets)
            for island_offset in island_offsets:
                island_offset_pts = geom.PtsFromInts(island_offset)
                islands_offset.append(island_offset_pts)
                ii = LinearRing([(p.x, p.y) for p in island_offset_pts])
                polygon = polygon.difference(Polygon(ii))
        all_inputs += objects_to_polygons(polygon)
    return all_inputs

def hsm_peel(shape, tool, zigzag, displace=0, from_outside=False):
    from DerpCAM import cam
    import DerpCAM.cam.geometry
    alltps = []
    all_inputs = shape_to_polygons(shape, tool, displace, from_outside)
    for polygon in all_inputs:
        tps = []
        step = tool.diameter * tool.stepover
        if zigzag:
            arc_dir = cam.geometry.ArcDir.Closest
        else:
            arc_dir = cam.geometry.ArcDir.CCW if tool.climb else cam.geometry.ArcDir.CW
        with pyvlock:
            if from_outside:
                tp = cam.geometry.OutsidePocketSimple(polygon, step, arc_dir, generate=True)
            else:
                tp = cam.geometry.InsidePocket(polygon, step, arc_dir, generate=True)
        generator = tp._get_arcs(100)
        try:
            while not geom.is_calculation_cancelled():
                progress = max(0, min(1000, 1000 * next(generator)))
                geom.set_calculation_progress(progress, 1000)
        except StopIteration:
            pass
        hsm_path = tp.path
        gen_path = []
        if from_outside:
            x, y = hsm_path[0].start.x, hsm_path[0].start.y
            rt = 0
            x -= rt
        else:
            x, y = tp.start_point.x, tp.start_point.y
            rt = tp.start_radius
        if not from_outside:
            r = 0
            c = geom.CandidateCircle(x, y, rt)
            a = 0
            min_helix_dia = tool.min_helix_diameter
            max_helix_dia = 2 * rt
            if min_helix_dia <= max_helix_dia:
                r = 0.5 * min_helix_dia
            else:
                raise ValueError(f"Entry location smaller than safe minimum of {tool.min_helix_diameter + tool.diameter:0.3f} mm")
            pitch = tool.diameter * tool.stepover
            if False:
                # Old method, uses concentric circles, marginally better tested but has direction changes
                while r < rt:
                    r = min(rt, r + pitch)
                    c = geom.CandidateCircle(x, y, r)
                    cp = c.at_angle(a)
                    gen_path += [cp, geom.PathArc(cp, cp, c, int(2 * math.pi * r), a, 2 * math.pi)]
            else:
                rdiff = rt - r
                if rdiff:
                    turns = math.ceil(rdiff / pitch)
                    pitch = rdiff / turns
                    # Number of arcs per circle
                    res = 4
                    slice = 2 * math.pi / res
                    dr = pitch / (2 * math.sin(slice / 2) * res)
                    sa = math.pi / res + math.pi / 2 + a
                    xc0 = x - dr * math.cos(sa)
                    yc0 = y - dr * math.sin(sa)
                    for i in range(res * turns + 1):
                        t1 = slice * i
                        c = geom.CandidateCircle(xc0 + dr * math.cos(t1 + sa), yc0 + dr * math.sin(t1 + sa), r + pitch * i / res)
                        cp1 = c.at_angle(t1 + a)
                        cp2 = c.at_angle(t1 + a + slice)
                        gen_path += [cp1, geom.PathArc(cp1, cp2, c, int(2 * math.pi * r), t1 + a, slice)]
                c = geom.CandidateCircle(x, y, rt)
                cp = c.at_angle(a)
                gen_path += [cp, geom.PathArc(cp, cp, c, int(2 * math.pi * r), a, 2 * math.pi)]

        lastpt = None
        for item in hsm_path:
            if isinstance(item, cam.geometry.LineData):
                if item.move_style == cam.geometry.MoveStyle.RAPID_OUTSIDE:
                    if geom.Path(gen_path, False).length():
                        tps.append(toolpath.Toolpath(geom.Path(gen_path, False), tool))
                    gen_path = []
                    lastpt = None
                else:
                    gen_path += [geom.PathPoint(x, y) for x, y in item.path.coords]
                    lastpt = geom.PathPoint(item.end.x, item.end.y)
            elif isinstance(item, cam.geometry.ArcData):
                steps = max(1, math.ceil(item.radius * abs(item.span_angle)))
                cc = geom.CandidateCircle(item.origin.x, item.origin.y, item.radius)
                sa = math.pi / 2 - item.start_angle
                span = -item.span_angle
                osp = geom.PathPoint(item.start.x, item.start.y)
                sp = cc.at_angle(sa)
                ep = cc.at_angle(math.pi / 2 - (item.start_angle + item.span_angle))
                oep = geom.PathPoint(item.end.x, item.end.y)
                #assert lastpt is None or geom.dist(lastpt, osp) < 0.1, f"{lastpt} vs {osp}"
                #assert geom.dist(osp, sp) < 0.1
                if geom.dist(sp, osp) >= 0.1:
                    print ("Excessive difference in start point coordinates", sp, osp, geom.dist(osp, sp))
                if geom.dist(ep, oep) >= 0.1:
                    print ("Excessive difference in end point coordinates", ep, oep, geom.dist(oep, ep), (sa + span) % (2 * math.pi), cc.angle(oep) % (2 * math.pi), item.radius, cc.dist(oep))
                #assert geom.dist(oep, ep) < 0.1
                # Fix slight inaccuracies with line segments
                if geom.dist(osp, sp) >= 0.0005:
                    gen_path.append(osp)
                gen_path += [sp, geom.PathArc(sp, ep, geom.CandidateCircle(item.origin.x, item.origin.y, item.radius), steps, sa, span)]
                if geom.dist(ep, oep) >= 0.0005:
                    gen_path.append(oep)
                lastpt = oep
        if geom.Path(gen_path, False).length():
            tpo = toolpath.Toolpath(geom.Path(gen_path, False), tool)
            tps.append(tpo)
        if not from_outside and tps and min_helix_dia <= max_helix_dia:
            tps[0].helical_entry = toolpath.HelicalEntry(tp.start_point, min_helix_dia / 2.0, angle=a, climb=tool.climb)
        # Add a final pass around the perimeter
        def ls2path(ls):
            return geom.Path([geom.PathPoint(x, y) for x, y in ls.coords], True)
        tps.append(toolpath.Toolpath(ls2path(polygon.exterior), tool))
        for h in polygon.interiors:
            tps.append(toolpath.Toolpath(ls2path(h), tool))
        alltps += tps
    return toolpath.Toolpaths(alltps)

def shape_to_object(shape, tool, displace=0, from_outside=False):
    from shapely.geometry import MultiPolygon
    inputs = shape_to_polygons(shape, tool, displace, from_outside)
    if len(inputs) == 1:
        return inputs[0]
    else:
        return MultiPolygon(inputs)

def refine_shape(shape, previous, current):
    alltps = []
    entire_shape = shape_to_object(shape, milling_tool.FakeTool(0))
    previous_tool = milling_tool.FakeTool(previous)
    previous_toolpath = shape_to_object(shape, previous_tool)
    # This is the actual shape that has been milled by the previous tool
    previous_outcome = previous_toolpath.buffer((previous - current) / 2)
    unmilled = entire_shape.difference(previous_outcome)
    unmilled_polygons = objects_to_polygons(unmilled)
    output_shapes = []
    for polygon in unmilled_polygons:
        #polygon = polygon.buffer(current / 2).intersection(entire_shape)
        if polygon.buffer(-current / 2):
            exterior = [geom.PathPoint(x, y) for x, y in polygon.exterior.coords]
            interiors = [[geom.PathPoint(x, y) for x, y in interior.coords] for interior in polygon.interiors]
            output_shapes.append(shapes.Shape(exterior, True, interiors))
    return output_shapes