from pyclipper import *
from math import *
from geom import *
from milling_tool import *
from toolpath import *
import threading

def findPathNesting(tps):
    nestings = []
    for tp in tps:
        contours = tp.toolpaths if isinstance(tp, Toolpaths) else [tp]
        for subtp in contours:
            for children in nestings:
                if inside_bounds(children[-1].bounds, subtp.bounds):
                    # subtp contains this chain of contours
                    children.append(subtp)
                    break
            else:
                # Doesn't contain any earlier contour, so start a nesting.
                nestings.append([subtp])
    return nestings

def fixPathNesting(tps):
    nestings = findPathNesting(tps)
    res = []
    nestings = sorted(nestings, key=len)
    for nesting in nestings:
        res += nesting
    return res

# XXXKF this may cut corners sometimes, need to add collision checking
def joinClosePaths(tps):
    def findClosest(points, lastpt, diameter):
        mindist = None
        closest = 0
        for i, pt in enumerate(points):
            if i == 0 or dist(lastpt, pt) < mindist:
                closest = i
                mindist = dist(lastpt, pt)
        if closest > 0 and mindist <= diameter:
            points = points[closest:] + points[:closest]
        return points, mindist

    tps = fixPathNesting(tps)
    last = None
    res = []
    for tp in tps:
        if isinstance(tp, Toolpaths):
            res.append(tp)
            last = None
            continue
        if last is not None and last.tool is tp.tool:
            points = tp.path.nodes
            found = False
            if tp.path.closed:
                points, mindist = findClosest(points, lastpt, tp.tool.diameter)
                if mindist > tp.tool.diameter:
                    # Desperate second-chance joining by retracing the already milled path
                    # XXXKF this is rather bad, O(N^2), needs rethinking
                    for j in range(len(last.path.nodes) - 1, 0, -1):
                        points, mindist = findClosest(points, last.path.nodes[j], tp.tool.diameter)
                        if mindist <= tp.tool.diameter:
                            print ("Found a backtrack")
                            res[-1] = Toolpath(Path(last.path.nodes + list(reversed(last.path.nodes[j:])) + points + points[0:1], False), tp.tool)
                            last = res[-1]
                            lastpt = last.path.nodes[-1]
                            found = True
                            break
            if found:
                continue
            if dist(lastpt, points[0]) <= tp.tool.diameter:
                res[-1] = Toolpath(Path(last.path.nodes + (last.path.nodes[0:1] if last.path.closed else []) + points + (points[0:1] if tp.path.closed else []), False), tp.tool)
                last = res[-1]
                lastpt = last.path.nodes[-1]
                continue
        res.append(tp)
        lastpt = tp.path.seg_end()
        last = tp
    return res

class HelicalEntry(object):
    def __init__(self, point, r, angle=0, climb=True):
        self.point = point
        self.r = r
        self.angle = angle
        self.start = PathPoint(point.x + r * cos(angle), point.y + r * sin(angle))
        self.climb = climb

def findHelicalEntryPoints(toolpaths, tool, boundary, islands, margin):
    boundary_path = IntPath(boundary)
    boundary_path = boundary_path.force_orientation(True)
    island_paths = [IntPath(i).force_orientation(True) for i in islands]
    for toolpath in toolpaths:
        if type(toolpath) is Toolpaths:
            findHelicalEntryPoints(toolpath.toolpaths, tool, boundary, islands, margin)
            continue
        candidates = [toolpath.path.nodes[0]]
        if len(toolpath.path.nodes) > 1 and False:
            p1 = toolpath.path.nodes[0]
            p2 = toolpath.path.nodes[1]
            mid = p1
            angle = atan2(p2[1] - p1[1], p2[0] - p1[0]) + pi / 2
            d = tool.diameter * 0.5
            candidates.append((mid[0] + cos(angle) * d, mid[1] + sin(angle) * d))
            d = tool.diameter * -0.5
            candidates.append((mid[0] + cos(angle) * d, mid[1] + sin(angle) * d))
        for start in candidates:
            # Size of the helical entry hole
            d = tool.diameter * (1 + 2 * tool.stepover) + margin
            c = IntPath(circle(start.x, start.y, d / 2))
            # Check if it sticks outside of the final shape
            # XXXKF could be optimized by doing a simple bounds check first
            if run_clipper_simple(CT_DIFFERENCE, [c], [boundary_path], bool_only=True):
                continue
            # Check for collision with islands
            if islands and any([run_clipper_simple(CT_INTERSECTION, [i], [c], bool_only=True) for i in island_paths]):
                continue
            toolpath.helical_entry = HelicalEntry(start, tool.diameter * tool.stepover / 2)
            break

def startWithClosestPoint(path, pt, dia):
    mindist = None
    mdpos = None
    for j, pt2 in enumerate(path.path.nodes):
        d = dist(pt, pt2)
        if mindist is None or d < mindist:
            mindist = d
            mdpos = j
    if mindist <= dia:
        path.path.nodes = path.path.nodes[mdpos:] + path.path.nodes[:mdpos + 1]
        return True
    return False

def mergeToolpaths(tps, new, dia):
    if type(new) is Toolpath:
        new = [new]
    else:
        new = new.toolpaths
    if not tps:
        tps.insert(0, Toolpaths(new))
        return
    last = tps[-1]
    new2 = []
    for i in new:
        assert i.path.closed
        pt = i.path.seg_start()
        found = False
        new_toolpaths = []
        for l in last.toolpaths:
            if found:
                new_toolpaths.append(l)
                continue
            if startWithClosestPoint(l, pt, dia):
                new_toolpaths.append(i)
                new_toolpaths.append(l)
                found = True
            else:
                new_toolpaths.append(l)
        if not found:
            new_toolpaths.append(i)
        last.toolpaths = new_toolpaths

class Shape(object):
    def __init__(self, boundary, closed=True, islands=None):
        for i in boundary:
            assert isinstance(i, PathPoint)
        self.boundary = boundary
        self.closed = closed
        self.islands = list(islands) if islands is not None else []
        self.bounds = self.calc_bounds()
    def add_island(self, island):
        self.islands.append(island)
    def calc_bounds(self):
        xcoords = [p.seg_end().x for p in self.boundary]
        ycoords = [p.seg_end().y for p in self.boundary]
        return (min(xcoords), min(ycoords), max(xcoords), max(ycoords))
    def default_tab_count(self, min_tabs, max_tabs, distance):
        plen = Path(self.boundary, self.closed).length()
        return int(max(min_tabs, min(max_tabs, plen // distance)))
    def engrave(self, tool):
        tps = [Toolpath(Path(self.boundary, self.closed), tool)] + [
            Toolpath(Path(island, True), tool) for island in self.islands ]
        return Toolpaths(tps)
    @staticmethod
    def _offset(points, closed, dist):
        if abs(dist) > 10 * GeometrySettings.RESOLUTION:
            res = Shape._offset(points, closed, int(dist / 2))
            if not res:
                return
            res2 = []
            for contour in res:
                offset = Shape._offset(contour, closed, dist - int(dist / 2))
                if offset:
                    res2 += offset
            return res2
        pc = PyclipperOffset()
        pc.AddPath(points, JT_ROUND, ET_CLOSEDPOLYGON if closed else ET_OPENROUND)
        return pc.Execute(dist)
    def contour(self, tool, outside=True, displace=0, subtract=None):
        dist = (0.5 * tool.diameter + displace) * GeometrySettings.RESOLUTION
        boundary = PtsToInts(self.boundary)
        res = Shape._offset(boundary, self.closed, dist if outside else -dist)
        if not res:
            return None

        if subtract:
            res2 = []
            for i in res:
                exp_orient = Orientation(i)
                d = Shape._difference(IntPath(i, True), *subtract, return_ints=True)
                if d:
                    res2 += [j for j in d if Orientation(j.int_points) == exp_orient]
            if not res2:
                return None
            res2 = [SameOrientation(i.int_points, outside ^ tool.climb) for i in res2]
            tps = [Toolpath(Path(PtsFromInts(path), self.closed), tool) for path in res2]
        else:
            res = [SameOrientation(i, outside ^ tool.climb) for i in res]
            tps = [Toolpath(Path(PtsFromInts(path), self.closed), tool) for path in res]
        return Toolpaths(tps)
    def pocket_contour(self, tool, displace=0):
        if not self.closed:
            raise ValueError("Cannot mill pockets of open polylines")
        tps = []
        tps_islands = []
        boundary = IntPath(self.boundary)
        boundary_transformed = [ IntPath(i, True) for i in Shape._offset(boundary.int_points, True, -tool.diameter * 0.5 * GeometrySettings.RESOLUTION) ]
        islands_transformed = []
        islands_transformed_nonoverlap = []
        islands = self.islands
        expected_size = min(self.bounds[2] - self.bounds[0], self.bounds[3] - self.bounds[1]) / 2.0
        for island in islands:
            pc = PyclipperOffset()
            pts = PtsToInts(island)
            if not Orientation(pts):
                pts = list(reversed(pts))
            pc.AddPath(pts, JT_ROUND, ET_CLOSEDPOLYGON)
            res = pc.Execute((tool.diameter * 0.5 + displace) * GeometrySettings.RESOLUTION)
            if not res:
                return None
            res = [IntPath(it, True) for it in res]
            islands_transformed += res
            islands_transformed_nonoverlap += [it for it in res if not run_clipper_simple(CT_DIFFERENCE, [it], boundary_transformed, bool_only=True)]
        if islands_transformed_nonoverlap:
            islands_transformed_nonoverlap = Shape._union(*[i for i in islands_transformed_nonoverlap], return_ints=True)
        for path in islands_transformed_nonoverlap:
            for ints in Shape._intersection(path, *boundary_transformed):
                # diff with other islands
                tps_islands += [Toolpath(Path(ints, True), tool)]
        displace_now = displace
        stepover = tool.stepover * tool.diameter
        # No idea why this was here given the joinClosePaths call later on is
        # already merging the island paths.
        #for island in tps_islands:
        #    mergeToolpaths(tps, island, tool.diameter)
        while True:
            if is_calculation_cancelled():
                return None
            set_calculation_progress(abs(displace_now), expected_size)
            res = self.contour(tool, False, displace_now, subtract=islands_transformed)
            if not res:
                break
            displace_now += stepover
            mergeToolpaths(tps, res, tool.diameter)
        if len(tps) == 0:
            raise ValueError("Empty contour")
        tps = list(reversed(tps))
        tps = joinClosePaths(tps_islands + tps)
        findHelicalEntryPoints(tps, tool, self.boundary, self.islands, displace)
        set_calculation_progress(expected_size, expected_size)
        return Toolpaths(tps)
    def face_mill(self, tool, angle, margin, zigzag):
        offset_dist = (0.5 * tool.diameter - margin) * GeometrySettings.RESOLUTION
        boundary = PtsToInts(self.boundary)
        res = Shape._offset(boundary, self.closed, -offset_dist)
        if not res:
            return None
        boundary_paths = [IntPath(bp, True) for bp in res]

        coords = sum(res, [])
        xcoords = [p[0] / GeometrySettings.RESOLUTION for p in coords]
        ycoords = [p[1] / GeometrySettings.RESOLUTION for p in coords]
        sx, sy, ex, ey = min(xcoords), min(ycoords), max(xcoords), max(ycoords)

        stepover = tool.diameter * tool.stepover
        tps = []
        maxlen = dist(PathPoint(sx, sy), PathPoint(ex, ey))
        #p = (ex + tool.diameter / 2 * cos(angle + pi / 2), sy + tool.diameter / 2 * sin(angle + pi / 2))
        p = (ex, sy + 1 / GeometrySettings.RESOLUTION)
        fsteps = maxlen / stepover
        nsteps = int(ceil(fsteps))
        for i in range(nsteps):
            p1 = PathPoint(p[0] - maxlen * cos(angle), p[1] - maxlen * sin(angle))
            p2 = PathPoint(p[0] + maxlen * cos(angle), p[1] + maxlen * sin(angle))
            if zigzag and (i & 1):
                p2, p1 = p1, p2
            path = IntPath([p1, p2])
            tree = run_clipper_advanced(CT_INTERSECTION, [], boundary_paths, [path])
            for path2 in OpenPathsFromPolyTree(tree):
                tps.append(Toolpath(Path(PtsFromInts(path2), False), tool))
            if i == nsteps - 1:
                frac = fsteps - nsteps
                p = (p[0] + frac * stepover * cos(angle + pi / 2), p[1] + frac * stepover * sin(angle + pi / 2))
            else:
                p = (p[0] + stepover * cos(angle + pi / 2), p[1] + stepover * sin(angle + pi / 2))
        if not tps:
            raise ValueError("Milled area is empty")
        tps = joinClosePaths(tps)
        return Toolpaths(tps)
    def warp(self, transform):
        def interpolate(pts):
            res = []
            for i, p1 in enumerate(pts):
                p2 = pts[(i + 1) % len(pts)]
                segs = max(1, ceil(dist(p1, p2)))
                for i in range(segs):
                    res.append(weighted(p1, p2, i / segs))
            return res
        return Shape([transform(p.x, p.y) for p in interpolate(self.boundary)], self.closed,
            [[transform(p.x, p.y) for p in interpolate(island)] for island in self.islands])
    @staticmethod
    def _rotate_points(points, angle, x=0, y=0):
        def rotate(x, y, cosv, sinv, sx, sy):
            x -= sx
            y -= sy
            return PathPoint(sx + x * cosv - y * sinv, sy + x * sinv + y * cosv)
        return [rotate(p.x, p.y, cos(angle), sin(angle), x, y) for p in points]
    def rotated(self, angle, x, y):
        return Shape(self._rotate_points(self.boundary, angle, x, y), self.closed, [self._rotate_points(island, angle, x, y) for island in self.islands])
    @staticmethod
    def _scale_points(points, mx, my=None, sx=0, sy=0):
        if my is None:
            my = mx
        return [PathPoint(sx + (p.x - sx) * mx, sy + (p.y - sy) * my) for p in points]
    def scaled(self, mx, my=None, sx=0, sy=0):
        return Shape(self._scale_points(self.boundary, mx, my, sx, sy), self.closed, [self._scale_points(island, mx, my, sx, sy) for island in self.islands])
    @staticmethod
    def _translate_points(points, dx, dy):
        return [p.translated(dx, dy) for p in points]
    def translated(self, dx, dy):
        return Shape(self._translate_points(self.boundary, dx, dy), self.closed, [self._translate_points(island, dx, dy) for island in self.islands])
    @staticmethod
    def circle(x, y, r=None, d=None, n=None, sa=0, ea=2 * pi):
        return Shape(circle(x, y, r if r else 0.5 * d, n, sa, ea), True, None)
    @staticmethod
    def rectangle(sx, sy, ex, ey):
        polygon = [PathPoint(sx, sy), PathPoint(ex, sy), PathPoint(ex, ey), PathPoint(sx, ey)]
        #polygon = list(reversed(polygon))
        return Shape(polygon, True, None)
    def round_rectangle(sx, sy, ex, ey, r):
        polygon = circle(sx + r, sy + r, r=r, sa=pi, ea=3 * pi / 2) + \
          circle(ex - r, sy + r, r=r, sa=3 * pi / 2, ea=2 * pi) + \
          circle(ex - r, ey - r, r=r, sa=0, ea=pi / 2) + \
          circle(sx + r, ey - r, r=r, sa=pi / 2, ea=pi)
        return Shape(polygon, True, None)
    @staticmethod
    def _from_clipper_res(orig_orient_path, res):
        orig_orientation = Orientation(PtsToInts(orig_orient_path.boundary))
        if not res:
            return []
        if len(res) == 1:
            return Shape(PtsFromInts(res[0]))
        shapes = []
        for i in res:
            if Orientation(i) == orig_orientation:
                shapes.append(Shape(PtsFromInts(i), True, []))
            else:
                # XXXKF find the enclosing shape
                shapes[-1].islands.append(PtsFromInts(i))
        if len(shapes) == 1:
            return shapes[0]
        else:
            return shapes
    @staticmethod
    def union(*paths):
        pc = Pyclipper()
        for path in paths:
            pc.AddPath(PtsToInts(path.boundary), PT_SUBJECT if path is paths[0] else PT_CLIP, path.closed)
        res = pc.Execute(CT_UNION, GeometrySettings.fillMode, GeometrySettings.fillMode)
        return Shape._from_clipper_res(paths[0], res)
    @staticmethod
    def difference(*paths):
        pc = Pyclipper()
        for path in paths:
            pc.AddPath(PtsToInts(path.boundary), PT_SUBJECT if path is paths[0] else PT_CLIP, path.closed)
        res = pc.Execute(CT_DIFFERENCE, GeometrySettings.fillMode, GeometrySettings.fillMode)
        return Shape._from_clipper_res(paths[0], res)
    # This works on lists of points
    @staticmethod
    def _difference(*paths, return_ints=False):
        return run_clipper_simple(CT_DIFFERENCE, paths[0:1], paths[1:], return_ints=return_ints)
    # This works on lists of points
    @staticmethod
    def _intersection(*paths, return_ints=False):
        return run_clipper_simple(CT_INTERSECTION, paths[0:1], paths[1:], return_ints=return_ints)
    # This works on lists of points
    @staticmethod
    def _union(*paths, return_ints=False):
        return run_clipper_simple(CT_UNION, paths[0:1], paths[1:], return_ints=return_ints)

def interpolate_path(path):
    lastpt = path[0]
    res = [lastpt]
    for pt in path:
        d = maxaxisdist(lastpt, pt)
        subdiv = ceil(d * GeometrySettings.RESOLUTION + 1)
        for i in range(subdiv):
            if i > 0 and lastpt == pt:
                continue
            res.append(weighted(lastpt, pt, i / subdiv))
        lastpt = pt
    res.append(path[-1])
    return res

def trochoidal_transform(contour, nrad, nspeed):
    path = contour.path.nodes
    if contour.path.closed:
        path = path + [path[0]]
    path = interpolate_path(path)
    res = [path[0]]
    lastpt = path[0]
    t = 0
    for pt in path:
        x, y = pt.x, pt.y
        d = lastpt.dist(pt)
        t += d
        x += nrad*cos(t * nspeed * 2 * pi)
        y += nrad*sin(t * nspeed * 2 * pi)
        res.append(PathPoint(x, y))
        lastpt = pt
    res.append(path[-1])
    if res and contour.path.closed:
        assert res[-1] == res[0]
        return Toolpath(path=Path(res[:-1], True), tool=contour.tool, helical_entry=HelicalEntry(path[0], nrad), is_tab=contour.is_tab)
    else:
        return Toolpath(path=Path(res, False), tool=contour.tool, helical_entry=HelicalEntry(path[0], nrad), is_tab=contour.is_tab)

