from math import *
from DerpCAM.common.geom import *
from . import toolpath
import threading
import shapely.geometry

class Shape(object):
    def __init__(self, boundary, closed=True, islands=None):
        for i in boundary:
            assert isinstance(i, PathPoint)
        if not pyclipr.orientation(PtsToInts(boundary)):
            boundary = boundary[::-1]
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
    def default_tab_count(self, min_tabs, max_tabs, distance, min_length=0):
        plen = Path(self.boundary, self.closed).length()
        if plen < min_length:
            return 0
        return int(max(min_tabs, min(max_tabs, plen // distance)))
    def engrave(self, tool, offset=0):
        def offset_path(boundary, closed, offset):
            if offset == 0:
                return Path(boundary, closed)
            pts = [shapely.geometry.Point(pt.x, pt.y) for pt in boundary]
            if closed:
                ls = shapely.geometry.LinearRing(pts)
            else:
                ls = shapely.geometry.LineString(pts)
            ls = ls.simplify(epsilon())
            lso = ls.parallel_offset(abs(offset), 'right' if offset > 0 else 'left', 4)
            lso = lso.simplify(epsilon())
            return Path([PathPoint(x, y) for x, y in lso.coords], closed)
        tps = [toolpath.Toolpath(offset_path(self.boundary, self.closed, offset), tool)] + [
            toolpath.Toolpath(offset_path(island, True, offset), tool) for island in self.islands ]
        tps = [tp for tp in tps if not tp.is_empty()]
        return tps
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
        return Shape(circle(x, y, r if r is not None else 0.5 * d, n, sa, ea), True, None)
    @staticmethod
    def sausage(x1, y1, x2, y2, r, n=None):
        sa = atan2(y2 - y1, x2 - x1) + pi / 2
        return Shape(circle(x1, y1, r, n, sa, sa + pi) + circle(x2, y2, r, n, sa + pi, sa + 2 * pi), True, None)
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
        # XXXKF maybe use the tree representation here instead
        orig_orientation = pyclipr.orientation(PtsToInts(orig_orient_path.boundary))
        if not res:
            return []
        if len(res) == 1:
            return Shape(res[0])
        shapes = []
        for i in res:
            if pyclipr.orientation(PtsToInts(i)) == orig_orientation:
                shapes.append(Shape(i, True, []))
            else:
                # XXXKF find the enclosing shape
                shapes[-1].islands.append(i)
        if len(shapes) == 1:
            return shapes[0]
        else:
            return shapes
    @staticmethod
    def union2(*paths):
        res = run_clipper_polygons(pyclipr.Union, paths)
        return Shape._from_clipper_res(paths[0], res)
    @staticmethod
    def difference2(*paths):
        res = run_clipper_polygons(pyclipr.Difference, paths)
        return Shape._from_clipper_res(paths[0], res)
    # This works on lists of points
    @staticmethod
    def _difference(*paths, return_ints=False):
        return run_clipper_simple(pyclipr.Difference, paths[0:1], paths[1:], return_ints=return_ints)
    # This works on lists of points
    @staticmethod
    def _intersection(*paths, return_ints=False):
        return run_clipper_simple(pyclipr.Intersection, paths[0:1], paths[1:], return_ints=return_ints)
    # This works on lists of points
    @staticmethod
    def _union(*paths, return_ints=False):
        return run_clipper_simple(pyclipr.Union, paths[0:1], paths[1:], return_ints=return_ints)

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
        return toolpath.Toolpath(path=Path(res[:-1], True), tool=contour.tool, helical_entry=toolpath.HelicalEntry(path[0], nrad), is_tab=contour.is_tab)
    else:
        return toolpath.Toolpath(path=Path(res, False), tool=contour.tool, helical_entry=toolpath.HelicalEntry(path[0], nrad), is_tab=contour.is_tab)

