import hsm_nibble.geometry
import hsm_nibble.voronoi_centers
from DerpCAM.common import geom, guiutils
from . import shapes, toolpath, milling_tool
import math, threading
import pyclipper
from shapely.geometry import Polygon, GeometryCollection, MultiPolygon, LinearRing, LineString, Point

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
    return tps

def calculate_tool_margin(shape, tool, displace, outer_margin):
    boundary = geom.IntPath(shape.boundary)
    boundary_transformed = [ geom.IntPath(i, True) for i in shapes.Shape._offset(boundary.int_points, True, (-tool.diameter * 0.5 - displace + outer_margin) * geom.GeometrySettings.RESOLUTION) ]
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

def pts2path(pts, orientation):
    path = geom.Path(pts, True)
    if path.orientation() != orientation:
        return path.reverse()
    return path

def finish_contour(tps, tool, boundary_transformed, islands_transformed, islands_transformed_nonoverlap, finish_outer_contour):
    if finish_outer_contour:
        for b in boundary_transformed:
            expected_orientation = pyclipper.Orientation(b.int_points)
            for d in shapes.Shape._difference(b, *islands_transformed, return_ints=True):
                pts = geom.PtsFromInts(d.int_points)
                if pyclipper.Orientation(d.int_points) == expected_orientation:
                    tps.append(toolpath.Toolpath(pts2path(pts, tool.climb), tool))
    for h in islands_transformed_nonoverlap:
        for pts in shapes.Shape._intersection(h, *boundary_transformed):
            tps.append(toolpath.Toolpath(pts2path(pts, not tool.climb), tool))

def contour_parallel(shape, tool, displace=0, roughing_offset=0, finish_outer_contour=True, outer_margin=0):
    if not shape.closed:
        raise ValueError("Cannot mill pockets of open polylines")
    expected_size = min(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1]) / 2.0
    tps_islands = []
    boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap = calculate_tool_margin(shape, tool, displace + roughing_offset, outer_margin)
    for path in islands_transformed_nonoverlap:
        for ints in shapes.Shape._intersection(path, *boundary_transformed):
            # diff with other islands
            tps_islands += [toolpath.Toolpath(geom.Path(ints, True), tool)]
    displace_now = displace + roughing_offset
    stepover = tool.stepover * tool.diameter

    levels = []
    while True:
        if geom.is_calculation_cancelled():
            return None
        geom.set_calculation_progress(abs(displace_now), expected_size)
        res = calc_contour(shape, tool, False, displace_now, subtract=islands_transformed)
        if not res:
            break
        displace_now += stepover
        levels.append(res)
    tps = []
    for level in levels[::-1]:
        tps += level
    if not tps:
        return []
    tps = toolpath.joinClosePaths(tps_islands + tps)
    if roughing_offset:
        boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap = calculate_tool_margin(shape, tool, displace, 0)
        tps_finish = []
        finish_contour(tps_finish, tool, boundary_transformed, islands_transformed, islands_transformed_nonoverlap, finish_outer_contour)
        tps += tps_finish
    toolpath.findHelicalEntryPoints(tps, tool, shape.boundary, shape.islands, displace)
    geom.set_calculation_progress(expected_size, expected_size)
    return tps

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

def axis_parallel(shape, tool, angle, margin, zigzag, roughing_offset=0, finish_outer_contour=True, outer_margin=0):
    offset_dist = (0.5 * tool.diameter - margin) * geom.GeometrySettings.RESOLUTION
    boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap = calculate_tool_margin(shape, tool, margin + roughing_offset, outer_margin)

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
    tps = process_rows(rows, tool)
    if not tps:
        raise ValueError("Milled area is empty")
    if roughing_offset:
        # Recalculate final shapes without the roughing offset
        boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap = calculate_tool_margin(shape, tool, margin, 0)
    # Add a final pass around the perimeter
    finish_contour(tps, tool, boundary_transformed, islands_transformed, islands_transformed_nonoverlap, finish_outer_contour)
    return tps

pyvlock = threading.RLock()

def sort_polygons(polygons):
    if len(polygons) <= 1:
        return polygons
    output = [polygons.pop(0)]
    # Basic unoptimized greedy algo for now
    while polygons:
        last = output[-1]
        if isinstance(last, Polygon):
            last = Point(*last.exterior.coords[-1])
        best = 0
        bestd = polygons[0].distance(last)
        for j in range(1, len(polygons)):
            d = polygons[j].distance(last)
            if d < bestd:
                bestd = d
                best = j
        output.append(polygons.pop(best))
    return output

def objects_to_polygons(polygon):
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
    inputs = [i for i in inputs if not i.is_empty]
    return inputs

def shape_to_polygons(shape, tool, displace=0, from_outside=False, tool_diameter_override=None):
    if tool_diameter_override is None:
        tool_diameter_override = tool.diameter
    tdist = (0.5 * tool_diameter_override + displace) * geom.GeometrySettings.RESOLUTION
    if from_outside:
        subpockets = shapes.Shape._offset(geom.PtsToInts(shape.boundary), True, -tdist + tool_diameter_override * geom.GeometrySettings.RESOLUTION)
    else:
        subpockets = shapes.Shape._offset(geom.PtsToInts(shape.boundary), True, -tdist)
    all_inputs = []
    for subpocket in subpockets:
        boundary_offset = geom.PtsFromInts(subpocket)
        boundary = LinearRing([(p.x, p.y) for p in boundary_offset])
        polygon = Polygon(boundary)
        islands_offset = []
        holes = []
        for island in shape.islands:
            island_offsets = shapes.Shape._offset(geom.PtsToInts(island), True, tdist)
            island_offsets = pyclipper.SimplifyPolygons(island_offsets)
            for island_offset in island_offsets:
                island_offset_pts = geom.PtsFromInts(island_offset)
                islands_offset.append(island_offset_pts)
                ii = LinearRing([(p.x, p.y) for p in island_offset_pts])
                if not from_outside:
                    polygon = polygon.difference(Polygon(ii))
                else:
                    holes.append(Polygon(ii))
        if not polygon.is_empty:
            if from_outside:
                all_inputs.append((polygon, holes))
            else:
                all_inputs += objects_to_polygons(polygon)
    return all_inputs

# only works for closed linestrings
def linestring2path(ls, orientation):
    path = geom.Path([geom.PathPoint(x, y) for x, y in ls.coords], True)
    if orientation is not None and path.orientation() != orientation:
        return path.reverse()
    return path

def linestring2path_open(ls):
    return geom.Path([geom.PathPoint(x, y) for x, y in ls.coords], False)

def add_arcdata(gen_path, item):
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
    return oep

def polygon_to_shape(polygon):
    exterior = linestring2path(polygon.exterior, None)
    interiors = [linestring2path(i, None).nodes for i in polygon.interiors]
    return shapes.Shape(exterior.nodes, True, interiors)

def add_outer_passes2(polygon, tool):
    tps = []
    interiors = MultiPolygon([Polygon(i) for i in polygon.interiors])
    while True:
        outside_pass = polygon.exterior
        exterior = Polygon(polygon.exterior).buffer(-tool.diameter * tool.stepover)
        if not exterior.contains(interiors):
            break
        tps.append(toolpath.Toolpath(linestring2path(outside_pass, None), tool))
        polygon = exterior.difference(interiors)
    return polygon, tps

def add_outer_passes(polygon, tool):
    tps = []
    exterior = Polygon(polygon.exterior)
    interiors = MultiPolygon([Polygon(i) for i in polygon.interiors])
    while True:
        new_exterior = exterior.buffer(-tool.diameter * tool.stepover)
        if not new_exterior.contains(interiors):
            break
        tps.append(toolpath.Toolpath(linestring2path(exterior.exterior, None), tool))
        exterior = new_exterior
    polygon = exterior.difference(interiors)
    return polygon, tps

def finalize_cut(tps, gen_path, was_previously_cut, tool, already_cut, tp):
    path = geom.Path(gen_path, False)
    if path.length():
        tpo = toolpath.Toolpath(path, tool, was_previously_cut=was_previously_cut)
        spt = path.seg_start()
        spt2 = Point(spt.x, spt.y)
        if (already_cut and already_cut.intersection(spt2.buffer(tool.diameter / 20))) or (tp is not None and tp.starting_angle is None):
            tpo.helical_entry = toolpath.PlungeEntry(spt)
            tpo.was_previously_cut = True
        else:
            if tp and tp.starting_angle:
                cc = geom.CandidateCircle(tp.start_point.x, tp.start_point.y, tool.min_helix_diameter / 2)
                a = -tp.starting_angle + math.pi / 2
                tpo.helical_entry = toolpath.HelicalEntry(cc.centre(), cc.r, angle=a, climb=tool.climb)
        tps.append(tpo)
        gen_path = []
        was_previously_cut = True
    return gen_path, was_previously_cut, None

def add_finishing_outlines(tps, polygon, tool, from_outside):
    if not from_outside:
        tps.append(toolpath.Toolpath(linestring2path(polygon.exterior, tool.climb), tool, was_previously_cut=True, is_cleanup=True))
    for h in polygon.interiors:
        tps.append(toolpath.Toolpath(linestring2path(h, not tool.climb), tool, was_previously_cut=True, is_cleanup=True))

def hsm_peel(shape, tool, zigzag, displace=0, from_outside=False, shape_to_refine=None, roughing_offset=0):
    already_cut = None
    if not from_outside and shape_to_refine is not None:
        already_cut = MultiPolygon()
        for i in shape_to_refine:
            for j in shape_to_polygons(i, milling_tool.FakeTool(0), 0, False):
                already_cut = already_cut.union(j)
        already_cut = already_cut.buffer(-tool.diameter / 2)
        display_already_cut = False
        if display_already_cut:
            tps = []
            for polygon in objects_to_polygons(already_cut):
                tps.append(toolpath.Toolpath(linestring2path(polygon.exterior, tool.climb), tool, was_previously_cut=True, is_cleanup=True))
            return tps
    alltps = []
    all_inputs = shape_to_polygons(shape, tool, displace + roughing_offset, from_outside)
    if zigzag:
        arc_dir = hsm_nibble.geometry.ArcDir.Closest
    else:
        arc_dir = hsm_nibble.geometry.ArcDir.CCW if tool.climb else hsm_nibble.geometry.ArcDir.CW
    num_polys = len(all_inputs)
    outer_progress = 0
    for polygon in all_inputs:
        if from_outside:
            polygon, islands = polygon
        tps = []
        step = tool.diameter * tool.stepover
        tactic = hsm_nibble.geometry.StartPointTactic.WIDEST
        if from_outside:
            tactic = hsm_nibble.geometry.StartPointTactic.PERIMETER
            adaptive = False
            if adaptive:
                polygon, tps = add_outer_passes(polygon, tool)
            if shape_to_refine:
                outside_poly = Polygon(polygon.exterior)
                stock = outside_poly.buffer(tool.diameter)
                already_cut_outline = MultiPolygon()
                for i in shape_to_refine:
                    for j in shape_to_polygons(i, milling_tool.FakeTool(0), 0, False):
                        already_cut_outline = already_cut_outline.union(j)
                already_cut = already_cut_for_this = stock.difference(already_cut_outline.buffer(tool.diameter / 2))
                polygon = stock.difference(outside_poly)
            else:
                td = tool.diameter
                stock = polygon.buffer(td / 2)
                for i in islands:
                    polygon = polygon.difference(i)
                # Generous margins
                already_cut_for_this = stock.difference(polygon)
                for i in islands:
                    already_cut_for_this = already_cut_for_this.difference(i)
        else:
            already_cut_for_this = already_cut.intersection(polygon) if already_cut else None
        #polygon = polygon.difference(already_cut_for_this)
        with pyvlock:
            tp = hsm_nibble.geometry.Pocket(polygon, step, arc_dir, generate=True, already_cut=already_cut_for_this, starting_point_tactic=tactic, starting_radius=tool.min_helix_diameter/2)
        has_entry_circle = tp.starting_angle is not None
        if already_cut_for_this and already_cut_for_this.contains(tp.start_point):
            has_entry_circle = False
        if has_entry_circle and tp.max_starting_radius < tool.min_helix_diameter / 2:
            raise ValueError(f"Entry location smaller than safe minimum of {guiutils.Format.cutter_dia(tool.min_helix_diameter + tool.diameter)}")
        generator = tp.get_arcs(100)
        try:
            while not geom.is_calculation_cancelled():
                progress = max(0, min(1000, 1000 * next(generator)))
                geom.set_calculation_progress(outer_progress + progress, 1000 * num_polys)
        except StopIteration:
            pass
        hsm_path = tp.path
        if not hsm_path:
            continue
        gen_path = []
        lastpt = None
        was_previously_cut = from_outside
        for item in hsm_path:
            MoveStyle = hsm_nibble.geometry.MoveStyle
            if isinstance(item, hsm_nibble.geometry.LineData):
                #if item.start.distance(item.end) < 1e-6:
                #    continue
                #print (item.move_style, item.start.distance(item.end), item.start)
                if item.move_style == MoveStyle.RAPID_OUTSIDE:
                    gen_path, was_previously_cut, tp = finalize_cut(tps, gen_path, was_previously_cut, tool, already_cut, tp)
                else:
                    gen_path += [geom.PathPoint(x, y, toolpath.RapidMove if item.move_style == MoveStyle.RAPID_INSIDE else None) for x, y in item.path.coords]
            elif isinstance(item, hsm_nibble.geometry.ArcData):
                add_arcdata(gen_path, item)
        gen_path, was_previously_cut, tp = finalize_cut(tps, gen_path, was_previously_cut, tool, already_cut, tp)
        # Add a final pass around the perimeter
        if not roughing_offset:
            add_finishing_outlines(tps, polygon, tool, from_outside)
        else:
            if from_outside:
                for i in islands:
                    add_finishing_outlines(tps, i.buffer(-roughing_offset), tool, False)
            else:
                add_finishing_outlines(tps, polygon.buffer(roughing_offset), tool, from_outside)
        alltps += tps
        outer_progress += 1000
    return alltps

def shape_to_object(shape, tool, displace=0, from_outside=False):
    inputs = shape_to_polygons(shape, tool, displace, from_outside)
    if len(inputs) == 1:
        return inputs[0]
    else:
        return MultiPolygon(inputs)

def refine_shape_internal(shape, previous, current, min_entry_dia):
    alltps = []
    entire_shape = shape_to_object(shape, milling_tool.FakeTool(0))
    # Toolpath made by the previous tool
    previous_toolpath = shape_to_object(shape, milling_tool.FakeTool(previous))
    # Area cut by that toolpath
    previous_milled = previous_toolpath.buffer(previous / 2)
    safe_entry_to_shape = previous_milled.intersection(entire_shape).buffer(-min_entry_dia - current / 2)
    # What's left to mill
    unmilled = entire_shape.difference(previous_milled)
    unmilled_polygons = objects_to_polygons(unmilled)
    output_polygons = []
    junk_cutoff = max(current / 20, 1.0 / geom.GeometrySettings.RESOLUTION)
    cnt = 0
    for polygon in unmilled_polygons:
        # Skip very tiny shapes
        polygons = polygon.buffer(-junk_cutoff)
        if polygons:
            # Extend each fragment, but only within the target area.
            orig_buffered = polygons.buffer(current + junk_cutoff)
            buffered = orig_buffered.intersection(entire_shape)
            for polygon2 in objects_to_polygons(buffered):
                if polygon2.difference(previous_milled):
                    entry_areas = polygon2.intersection(safe_entry_to_shape)
                    for area in objects_to_polygons(entry_areas):
                        pt = area.centroid
                        if not area.contains(pt):
                            pt = area.representative_point()
                        entry_circle = pt.buffer(current / 2 + min_entry_dia)
                        polygon2 = polygon2.union(entry_circle)
                    output_polygons.append(polygon2)
    output_polygons = objects_to_polygons(MultiPolygon(output_polygons).buffer(0))
    output_shapes = []
    for polygon in sort_polygons(output_polygons):
        exterior = [geom.PathPoint(x, y) for x, y in polygon.exterior.coords]
        interiors = [[geom.PathPoint(x, y) for x, y in interior.coords] for interior in polygon.interiors]
        output_shapes.append(shapes.Shape(exterior, True, interiors))
    return output_shapes

def refine_shape_external(shape, previous, current, min_entry_dia):
    alltps = []
    entire_shape, holes = shape_to_object(shape, milling_tool.FakeTool(0), from_outside=True)
    for i in holes:
        entire_shape = entire_shape.difference(i)
    previous_milled_outline = entire_shape.buffer(previous / 2)
    previous_milled = previous_milled_outline.buffer(-previous / 2)
    mill_slot = previous_milled_outline.difference(previous_milled)
    unmilled = previous_milled.difference(entire_shape)
    unmilled_polygons = objects_to_polygons(unmilled)
    output_polygons = []
    junk_cutoff = max(current / 20, 1.0 / geom.GeometrySettings.RESOLUTION)
    for polygon in unmilled_polygons:
        # Skip very tiny shapes
        polygons = polygon.buffer(-junk_cutoff)
        if polygons:
            polygons = polygons.buffer(current + junk_cutoff).difference(entire_shape)
            for polygon2 in objects_to_polygons(polygons):
                entry_circle = polygon2.intersection(mill_slot).centroid.buffer(current / 2 + min_entry_dia).difference(entire_shape)
                polygon2 = polygon2.union(entry_circle)
            output_polygons.append(polygon2)
    output_polygons = objects_to_polygons(MultiPolygon(output_polygons).buffer(0))
    output_shapes = []
    for polygon in sort_polygons(output_polygons):
        exterior = [geom.PathPoint(x, y) for x, y in polygon.exterior.coords]
        interiors = [[geom.PathPoint(x, y) for x, y in interior.coords] for interior in polygon.interiors]
        output_shapes.append(shapes.Shape(exterior, True, interiors))
    return output_shapes

def shape_to_refine_internal(shape, previous):
    entire_shape = shape_to_object(shape, milling_tool.FakeTool(0))
    previous_milled = entire_shape.buffer(-previous / 2).buffer(previous / 2)
    output_polygons = objects_to_polygons(previous_milled)
    output_shapes = []
    for polygon in sort_polygons(output_polygons):
        exterior = [geom.PathPoint(x, y) for x, y in polygon.exterior.coords]
        interiors = [[geom.PathPoint(x, y) for x, y in interior.coords] for interior in polygon.interiors]
        output_shapes.append(shapes.Shape(exterior, True, interiors))
    return output_shapes

def shape_to_refine_external(shape, previous):
    entire_shape = shape_to_object(shape, milling_tool.FakeTool(0))
    previous_milled = entire_shape.buffer(previous / 2).buffer(-previous / 2)
    output_polygons = objects_to_polygons(previous_milled)
    output_shapes = []
    for polygon in sort_polygons(output_polygons):
        exterior = [geom.PathPoint(x, y) for x, y in polygon.exterior.coords]
        output_shapes.append(shapes.Shape(exterior, True))
    return output_shapes

