from DerpCAM.common import geom
from DerpCAM.cam.pocket import sort_polygons, shape_to_polygons
from . import shapes, toolpath, milling_tool
import math
from sortedcontainers import SortedDict
from shapely.geometry import Polygon, GeometryCollection, MultiPolygon, LinearRing, LineString, MultiLineString, Point, MultiPoint
import shapely.affinity, shapely.ops

class PatternFillSegment:
    def __init__(self, fill, line):
        self.line = line
        self.start_outline, self.start_t = fill.find_outline_and_pos(line.coords[0])
        self.end_outline, self.end_t = fill.find_outline_and_pos(line.coords[-1])
    def side(self, key):
        if key == (self.start_outline, self.start_t):
            return 0
        if key == (self.end_outline, self.end_t):
            return 1
        assert False
    def end(self, side):
        if side == 1:
            return (self.end_outline, self.end_t)
        if side == 0:
            return (self.start_outline, self.start_t)
        assert False
    def to_coords(self, side):
        if side == 0:
            return self.line.coords
        else:
            return list(self.line.coords[::-1])

class PatternFillSegmentCollection(SortedDict):
    def add_segment(self, segment):
        #print (segment.start_outline, segment.start_t, segment.end_outline, segment.end_t)
        self.half_add(segment, segment.start_outline, segment.start_t)
        self.half_add(segment, segment.end_outline, segment.end_t)
    def half_add(self, segment, outline, t):
        key = (outline, t)
        container = self.get(key)
        if container is None:
            container = self[key] = set()
        container.add(segment)
    def remove_segment(self, segment):
        key1 = (segment.start_outline, segment.start_t)
        container1 = self[key1]
        container1.remove(segment)
        if not container1:
            del self[key1]
        key2 = (segment.end_outline, segment.end_t)
        if key1 == key2:
            return
        container2 = self[key2]
        container2.remove(segment)
        if not container2:
            del self[key2]
    def find_near(self, outline, t):
        mid = self.bisect((outline, t))
        items = self.items()
        left = items[mid - 1] if mid > 0 else None
        right = items[mid] if mid < len(items) else None
        if left is not None and left[0][0] != outline:
            left = None
        if right is not None and right[0][0] != outline:
            right = None
        if left is not None and right is not None:
            if abs(t - left[0][1]) < abs(t - right[0][1]):
                return left
            else:
                return right
        return left if left is not None else right
    def any_segment(self):
        if not self:
            return None
        container = self.items()[0][1]
        assert container
        return next(iter(container))

class PatternFillOutline:
    def __init__(self, ring, is_outside):
        self.ring = ring
        self.is_outside = is_outside

class PatternFillGenerator:
    def __init__(self, polygon, hatch):
        self.polygon = polygon
        self.outlines = [PatternFillOutline(self.polygon.exterior, True)]
        for interior in self.polygon.interiors:
            self.outlines.append(PatternFillOutline(interior, False))
        self.segments = []
        for line in hatch:
            self.segments.append(PatternFillSegment(self, line))
        self.segments_sorted = PatternFillSegmentCollection()
        for segment in self.segments:
            self.segments_sorted.add_segment(segment)
        self.linestrings = []
        while self.segments_sorted:
            segment = self.segments_sorted.any_segment()
            side = 0
            coords = []
            while segment is not None:
                self.output_segment(coords, segment, side)
                self.segments_sorted.remove_segment(segment)
                end_outline, end_t = segment.end(1 - side)
                found = self.segments_sorted.find_near(end_outline, end_t)
                if found:
                    nextpos, nextsegs = found
                    self.output_outline(coords, (end_outline, end_t), nextpos)
                    nextseg = next(iter(nextsegs))
                    side = nextseg.side(nextpos)
                    segment = nextseg
                else:
                    segment = None
            if coords:
                self.linestrings.append(LineString(coords))
    def output_segment(self, coords, segment, side):
        coords += segment.to_coords(side)
        #print ("SEG", segment.end(side), segment.end(1 - side))
    def output_outline(self, coords, start, end):
        assert start[0] == end[0]
        if start != end:
            coords += shapely.ops.substring(self.outlines[start[0]].ring, start[1], end[1]).coords
        #print ("OTL", start, end)
    def find_outline_and_pos(self, point_coords):
        point = Point(*point_coords)
        mindist = None
        best = None
        eps = 0.01
        for i, outline in enumerate(self.outlines):
            dist = outline.ring.distance(point)
            if mindist is None or dist < mindist:
                mindist = dist
                best = i
        if best is None or mindist >= eps:
            assert False, f"Clipped lines don't reach the outline, check the pattern coverage, dist={mindist}"
            return None, None
        outline = self.outlines[best]
        return best, outline.ring.project(point)
    def to_paths(self):
        paths = []
        for line in self.linestrings:
            points = [geom.PathPoint(p[0], p[1]) for p in line.coords]
            paths.append(geom.Path(points, False))
        for outline in self.outlines:
            points = [geom.PathPoint(p[0], p[1]) for p in outline.ring.coords]
            paths.append(geom.Path(points, True))
        return paths

class PatternFillPath:
    def __init__(self, path):
        self.path = path
    def to_path(self, min_width, last_point=None):
        return self.path

def single_hatch_pattern(polygon, angle, spacing, ofx, ofy, line_maker, *line_maker_args):
    minx, miny, maxx, maxy = polygon.bounds
    i = 0
    angle_rad = math.pi * angle / 180
    angle2_rad = angle_rad + math.pi / 2
    # Maximum line length
    dx, dy = maxx - minx, maxy - miny
    maxlen = max(dx, dy, math.sqrt(dx ** 2 + dy ** 2))
    lines = []
    dx2 = maxlen * math.cos(angle_rad)
    dy2 = maxlen * math.sin(angle_rad)
    dx3 = math.cos(angle2_rad)
    dy3 = math.sin(angle2_rad)
    bounds_poly = Polygon(LinearRing([Point(minx, miny), Point(maxx, miny), Point(maxx, maxy), Point(minx, maxy)]))
    # XXXKF this is definitely wrong
    #minx += ofx - minx % spacing
    #miny += ofy - miny % spacing
    midx = (minx + maxx) / 2
    midy = (miny + maxy) / 2
    nlines = int(math.ceil(maxlen / spacing) + 2)
    coords, period = line_maker(2 * maxlen, *line_maker_args)
    for i in range(-nlines - 1, nlines):
        x = midx + i * spacing * dx3
        y = midy + i * spacing * dy3
        p1 = Point(x - dx2, y - dy2)
        p2 = Point(x + dx2, y + dy2)
        ls = shapely.affinity.translate(LineString(coords[i % len(coords)]), ofx % period, ofy % (spacing * len(coords)))
        ls = shapely.affinity.translate(shapely.affinity.rotate(ls, angle_rad, use_radians=True, origin=(0, 0)), p1.x, p1.y)
        ls = ls.intersection(bounds_poly).intersection(polygon)
        if ls is None or ls.is_empty or isinstance(ls, (Point, MultiPoint)):
            pass
        elif isinstance(ls, LineString):
            lines.append(ls)
        elif isinstance(ls, MultiLineString):
            for geom in ls.geoms:
                lines.append(geom)
        else:
            assert False, f"Unexpected geometry: {type(ls)}"
    return lines

def simple_line_maker(d):
    return [[Point(0, 0), Point(d, 0)]], d

def repeat_line_maker(d, singles, period):
    res = []
    for single in singles:
        coords = []
        for i in range(int(d // period + 1)):
            sp = i * period
            coords += shapely.affinity.translate(single, period * i, 0).coords
        res.append(LineString(coords).simplify(1.0 / geom.GeometrySettings.RESOLUTION).coords)
    return res, period

def hex_line_maker(d, side):
    c60 = side * math.cos(math.pi / 3)
    s60 = side * math.sin(math.pi / 3)
    period = 2 * (side + c60)
    singles = [
        LineString([Point(0, 0), Point(c60, s60), Point(side + c60, s60), Point(side + 2 * c60, 0), Point(period, 0)]),
        LineString([Point(0, s60), Point(c60, 0), Point(side + c60, 0), Point(side + 2 * c60, s60), Point(period, s60)]),
    ]
    return repeat_line_maker(d, singles, period)

def teeth_line_maker(d, side):
    cs45 = side * math.cos(math.pi / 4)
    period = 2 * cs45
    single = LineString([Point(0, 0), Point(cs45, cs45), Point(period, 0)])
    return repeat_line_maker(d, [single], period)

def brick_line_maker(d, side):
    period = 2 * side
    singles = [
        LineString([Point(0, 0), Point(0, side), Point(side, side), Point(side, 0), Point(period, 0)]),
        LineString([Point(0, side), Point(0, 0), Point(side, 0), Point(side, side), Point(period, side)]),
    ]
    return repeat_line_maker(d, singles, period)

# This is mostly unusable due to line2arc algo making a mess of things
def wave_line_maker(d, phase, side):
    period = side
    npoints = 32
    s = 2 * math.pi / npoints
    single = LineString([Point(i * period / npoints, 0.25 * side * math.sin(i * s)) for i in range(npoints)])
    return repeat_line_maker(d, [single], period)

def pattern_fill(shape, tool, thickness, pattern_type, pattern_angle, pattern_scale, ofx, ofy, tool_diameter_override=None):
    if not shape.closed:
        raise ValueError("Cannot pattern fill open polylines")
    if tool_diameter_override is not None:
        all_inputs = shape_to_polygons(shape, tool, 0, False, tool_diameter_override=tool_diameter_override)
    elif tool.tip_angle >= 1 and tool.tip_angle <= 179:
        slope = 0.5 / math.tan((tool.tip_angle * math.pi / 180) / 2)
        max_diameter = min(tool.diameter, thickness / slope + tool.tip_diameter)
        all_inputs = shape_to_polygons(shape, tool, 0, False, tool_diameter_override=max_diameter)
    else:
        all_inputs = shape_to_polygons(shape, tool, 0, False)
    paths = []
    for polygon in sort_polygons(all_inputs):
        if pattern_type == 'lines':
            hatch = single_hatch_pattern(polygon, pattern_angle, pattern_scale, ofx, ofy, simple_line_maker)
        elif pattern_type == 'cross':
            hatch = single_hatch_pattern(polygon, pattern_angle, pattern_scale, ofx, ofy, simple_line_maker) + single_hatch_pattern(polygon, pattern_angle + 90, pattern_scale, ofx, ofy, simple_line_maker)
        elif pattern_type == 'diamond':
            hatch = single_hatch_pattern(polygon, pattern_angle - 30, pattern_scale, ofx, ofy, simple_line_maker) + single_hatch_pattern(polygon, pattern_angle + 30, pattern_scale, ofx, ofy, simple_line_maker)
        elif pattern_type == 'hex':
            hatch = single_hatch_pattern(polygon, pattern_angle, pattern_scale * math.sin(math.pi / 3), ofx, ofy, hex_line_maker, pattern_scale)
        elif pattern_type == 'teeth':
            hatch = single_hatch_pattern(polygon, pattern_angle, pattern_scale * math.sin(math.pi / 3), ofx, ofy, teeth_line_maker, pattern_scale)
        elif pattern_type == 'brick':
            hatch = single_hatch_pattern(polygon, pattern_angle + 90, pattern_scale, ofx, ofy, brick_line_maker, pattern_scale)
        elif pattern_type == 'wave':
            hatch = single_hatch_pattern(polygon, pattern_angle, pattern_scale, ofx, ofy, wave_line_maker, pattern_scale)
        else:
            raise ValueError(f"Invalid pattern: {pattern_type}")
        paths += PatternFillGenerator(polygon, hatch).to_paths()
    return [PatternFillPath(path) for path in paths]
