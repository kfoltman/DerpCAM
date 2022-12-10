from pyclipper import *
from math import *
import threading

class GeometrySettings:
    RESOLUTION = 25.0
    fillMode = PFT_POSITIVE
    simplify_arcs = True
    simplify_lines = False
    draw_arrows = False
    dxf_inches = False
    gcode_inches = False
    grbl_output = False
    spindle_control = False
    spindle_warmup = 0
    spindle_min_rpm = None
    spindle_max_rpm = None
    paranoid_mode = False

def PtsToInts(points, res=None):
    res = res or GeometrySettings.RESOLUTION
    return [(round(p.x * res), round(p.y * res)) for p in points]

def PtsFromInts(points, res=None):
    res = res or GeometrySettings.RESOLUTION
    return [PathPoint(x / res, y / res) for x, y in points]
    
def PtsToIntsPos(points):
    res = [(round(p.x * GeometrySettings.RESOLUTION), round(p.y * GeometrySettings.RESOLUTION)) for p in points]
    if Orientation(res) == False:
        res = list(reversed(res))
    return res

def PtsToIntsNeg(points):
    res = [(round(p.x * GeometrySettings.RESOLUTION), round(p.y * GeometrySettings.RESOLUTION)) for p in points]
    if Orientation(res) == True:
        res = list(reversed(res))
    return res

def circle(x, y, r, n=None, sa=0, ea=2*pi):
    if not r:
        return [PathPoint(x, y)]
    if n is None:
        n = pi * r * GeometrySettings.RESOLUTION
    n *= abs((ea - sa) / (2 * pi))
    n = ceil(n)
    res = []
    for i in range(n + 1):
        a = sa + i * (ea - sa) / n
        newpt = PathPoint(x + r * cos(a), y + r * sin(a))
        if not res or newpt != res[-1]:
            res.append(newpt)
    return res

def circle2(x, y, r, n=None, sa=0, ea=2*pi):
    if n is None:
        n = pi * r * GeometrySettings.RESOLUTION
    n *= abs((ea - sa) / (2 * pi))
    n = ceil(n)
    c = CandidateCircle(x, y, r)
    return [c.at_angle(sa), PathArc(c.at_angle(sa), c.at_angle(ea), c, n, sa, ea - sa)]

def dist_fast(a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    return sqrt(dx * dx + dy * dy)

def maxaxisdist(a, b):
    return max(abs(a.x - b.x), abs(a.y - b.y))

class PathNode(object):
    def is_point(self):
        return False
    def is_arc(self):
        return False
    def is_circle(self):
        return False
    def joinable(self, other):
        h1 = self.speed_hint
        h2 = other.speed_hint
        if not (h1 and h2):
            # Simple case - either none have speed hints (that's joinable) or only one has (that's not joinable)
            return not h1 and not h2
        return h1.joinable(h2)
    @staticmethod
    def from_tuple(t):
        l = len(t)
        if l == 2:
            return PathPoint.from_tuple(t)
        elif l == 7:
            return PathArc.from_tuple(t)
        else:
            raise ValueError(f"Invalid number of data items for a path node ({l})")

class PathPoint(PathNode):
    def __init__(self, x, y, speed_hint=None):
        self.x = x
        self.y = y
        self.speed_hint = speed_hint
    def __repr__(self):
        return f"PathPoint({self.x:0.3f},{self.y:0.3f})"
    def seg_start(self):
        return self
    def seg_end(self):
        return self
    def is_point(self):
        return True
    def as_tuple(self):
        return (self.x, self.y)
    def dist(self, other):
        # Note this is not a true 'distance to object', it's to be used for
        # things like path lengths
        other = other.seg_start()
        dx = other.x - self.x
        dy = other.y - self.y
        return sqrt(dx * dx + dy * dy)
    def angle_to(self, p2):
        return atan2(p2.y - self.y, p2.x - self.x)
    @staticmethod
    def from_tuple(t):
        if len(t) != 2:
            raise ValueError("Invalid number of data items in a point record")
        return PathPoint(t[0], t[1])
    def translated(self, dx, dy):
        return PathPoint(self.x + dx, self.y + dy)
    def with_speed_hint(self, speed_hint):
        return PathPoint(self.x, self.y, speed_hint)
    def __eq__(self, other):
        return self.x == other.x and self.y == other.y
    def __ne__(self, other):
        return self.x != other.x or self.y != other.y
    def __hash__(self):
        return (self.x, self.y).__hash__()
    def scaled(self, cx, cy, scale):
        return PathPoint((self.x - cx) * scale + cx, (self.y - cy) * scale + cy)

class PathArc(PathNode):
    def __init__(self, p1, p2, c, steps, sstart, sspan, speed_hint=None):
        self.p1 = p1
        self.p2 = p2
        self.c = c
        self.steps = max(3, steps)
        self.sstart = sstart
        self.sspan = sspan
        self.speed_hint = speed_hint
        cp = c.centre()
        r1 = dist(cp, p1)
        r2 = dist(cp, p2)
        if abs(r1 - r2) > 0.01:
            print ("Warning: r1/r2 don't match")
        if abs(r1 - c.r) > 0.01:
            print ("Warning: r1/r don't match", r1, c.r)
        if abs(r2 - c.r) > 0.01:
            print ("Warning: r2/r don't match", r2, c.r)
        if dist(c.at_angle(sstart), p1) > 0.01:
            print ("Warning: start angle doesn't match")
        if dist(c.at_angle(sstart + sspan), p2) > 0.01:
            print ("Warning: end angle doesn't match")
    @staticmethod
    def xyra(x, y, r, sstart, sspan, steps = 100):
        c = CandidateCircle(x, y, r)
        return PathArc(c.at_angle(sstart), c.at_angle(sstart + sspan), c, steps, sstart, sspan)
    def __repr__(self):
        return f"PathArc({self.p1}, {self.p2}, {self.c!r}, {self.steps}, {self.sstart}, {self.sspan})"
    def is_arc(self):
        return True
    def is_circle(self):
        return abs(abs(self.sspan) - 2 * pi) < 0.001
    def __eq__(self, other):
        angle_eps = 1e-4
        return self.p1 == other.p1 and self.p2 == other.p2 and self.c == other.c and self.steps == other.steps and abs(self.sstart - other.sstart) < angle_eps and abs(self.sspan - other.sspan) < angle_eps
    def seg_start(self):
        return self.p1
    def seg_end(self):
        return self.p2
    def as_tuple(self):
        if self.speed_hint is not None:
            return ("ARC_CW" if self.sspan < 0 else "ARC_CCW", self.p1.as_tuple(), self.p2.as_tuple(), self.c.as_tuple(), self.steps, self.sstart, self.sspan, self.speed_hint)
        return ("ARC_CW" if self.sspan < 0 else "ARC_CCW", self.p1.as_tuple(), self.p2.as_tuple(), self.c.as_tuple(), self.steps, self.sstart, self.sspan)
    @staticmethod
    def from_tuple(t):
        l = len(t)
        if l == 7:
            return PathArc(PathPoint.from_tuple(t[1]), PathPoint.from_tuple(t[2]), CandidateCircle.from_tuple(t[3]), t[4], t[5], t[6])
        if l == 8:
            return PathArc(PathPoint.from_tuple(t[1]), PathPoint.from_tuple(t[2]), CandidateCircle.from_tuple(t[3]), t[4], t[5], t[6], t[7])
        raise ValueError("Invalid number of data items in a point record")
    def angle_at_fraction(self, alpha):
        return self.sstart + self.sspan * alpha
    def at_fraction(self, alpha):
        return self.c.at_angle(self.sstart + self.sspan * alpha)
    def length(self):
        return abs(self.sspan) * self.c.r
    def reversed(self):
        return PathArc(self.p2, self.p1, self.c, self.steps, self.sstart + self.sspan, -self.sspan, self.speed_hint)
    def translated(self, dx, dy):
        return PathArc(self.p1.translated(dx, dy), self.p2.translated(dx, dy), self.c.translated(dx, dy), self.steps, self.sstart, self.sspan, self.speed_hint)
    def scaled(self, cx, cy, scale):
        return PathArc(self.p1.scaled(cx, cy, scale), self.p2.scaled(cx, cy, scale), self.c.scaled(cx, cy, scale), self.steps, self.sstart, self.sspan, self.speed_hint)
    def cut(self, alpha, beta):
        alpha = max(0, alpha)
        beta = min(1, beta)
        if alpha == 0 and beta == 1:
            return [self.p1, self]
        start = self.sstart + self.sspan * alpha
        span = self.sspan * (beta - alpha)
        arc_start = self.c.at_angle(start)
        arc_end = self.c.at_angle(start + span)
        return [arc_start, PathArc(arc_start, arc_end, self.c, self.steps, start, span, self.speed_hint)]
    def quadrant_seps(self):
        # Return extra points (other than start and end) needed to calculate the bounds, i.e. the points separating the quadrants of a circle
        # a1, a2 = angles 0..2*pi, choosen between start and end so that a1 <= a2
        if self.sspan < 0:
            a1 = (self.sstart + self.sspan) % (2 * pi)
            a2 = self.sstart % (2 * pi)
        else:
            a1 = self.sstart % (2 * pi)
            a2 = (self.sstart + self.sspan) % (2 * pi)
        # Convert to quadrant numbers
        q1 = floor(a1 / (pi / 2))
        q2 = floor(a2 / (pi / 2))
        # If a straight wrap around (end < start), or if they're both in the same
        # quadrant but the arc is more than half circle (which is also a wrap
        # around) then compensate by adding 4 (quadrants per circle)
        if q2 < q1 or (q2 == q1 and abs(self.sspan) >= pi):
            q2 += 4
        return [self.c.at_angle((i + 1) * pi / 2) for i in range(q1, q2)]

class MinMax(object):
    def __init__(self):
        self.min = None
        self.max = None
    def feed(self, value):
        if self.min is None:
            self.min = self.max = value
        else:
            self.min = min(self.min, value)
            self.max = max(self.max, value)

class Path(object):
    def __init__(self, nodes, closed):
        self.nodes = nodes
        self.closed = closed
    def __eq__(self, other):
        return other is not None and self.nodes == other.nodes and self.closed == other.closed
    def is_empty(self):
        return len(self.nodes) == 0
    def length(self):
        return sum([(dist(start, end) if end.is_point() else end.length()) for start, end in PathSegmentIterator(self)])
    def lengths(self):
        res = [0]
        lval = 0
        for start, end in PathSegmentIterator(self):
            if end.is_point():
                lval += start.dist(end)
            else:
                assert end.is_arc()
                lval += end.length()
            res.append(lval)
        return res
    def without_circles(self):
        return Path([i for i in self.nodes if not i.is_circle()], self.closed)
    def subpath(self, start, end, hint=None):
        res = []
        if hint is None or hint is Ellipsis:
            it = PathSegmentIterator(self)
            tlen = 0
            prev = hint
        else:
            it, tlen = hint
            prev = None
        while True:
            if hint is not None and tlen < start:
                prev = (it.clone(), tlen)
            try:
                last, p = next(it)
            except StopIteration:
                break
            if p.is_arc():
                assert last.dist(p.p1) < 1 / GeometrySettings.RESOLUTION
                d = p.length()
                if d == 0:
                    continue
                tlen_after = tlen + d
                if tlen_after >= start and tlen <= end:
                    alpha = (start - tlen) / d
                    beta = (end - tlen) / d
                    res += p.cut(alpha, beta)
            else:
                d = dist(last, p)
                if d == 0:
                    continue
                tlen_after = tlen + d
                if tlen_after >= start and tlen <= end:
                    alpha = (start - tlen) / d
                    beta = (end - tlen) / d
                    alpha = max(0, alpha)
                    beta = min(1, beta)
                    res.append(weighted(last, p, alpha) if alpha > 0 else last)
                    res.append(weighted(last, p, beta) if beta < 1 else p)
            tlen = tlen_after
        # Eliminate duplicates
        res = [p for i, p in enumerate(res) if i == 0 or p.is_arc() or res[i - 1].is_arc() or p != res[i - 1]]
        # Zero/single-point paths are considered empty, return None
        if len(res) < 2:
            sp = None
        else:
            if res[0].seg_start() == res[-1].seg_end():
                sp = Path(res, True) if res[-1].is_arc() else Path(res[:-1], True)
            else:
                sp = Path(res, False)
        if hint is None:
            return sp
        else:
            return sp, prev
    def reverse(self):
        res = []
        i = final = len(self.nodes) - 1
        end = 0
        if self.closed:
            res.append(self.nodes[0])
            end = 1
        while i >= end:
            pi = self.nodes[i]
            speed_hint = self.nodes[i + 1].speed_hint if i < final else None
            if not pi.is_arc():
                res.append(pi.with_speed_hint(speed_hint))
            else: # arc
                res.append(pi.p2.with_speed_hint(speed_hint)) # end point
                res.append(pi.reversed())
                # Skip start point, as it is already inside the arc
                i -= 1
                # Verify that it actually was
                if self.nodes[i] != pi.p1:
                    for n, p in enumerate(self.nodes):
                        print ("Item", n, p)
                assert self.nodes[i] == pi.p1
            i -= 1
        # XXXKF not the ideal result for closed paths!
        return Path(res, self.closed)
    # For a path and a given point, find the nearest point on a path.
    # Returns the curve-length to a matching point *on* the path and the distance
    # from that point to the given point.
    def closest_point(self, pt):
        def rotate(x, y, angle):
            cosv, sinv = -cos(angle), sin(angle)
            return x * cosv - y * sinv, x * sinv + y * cosv
        mindist = None
        closest = None
        lengths = self.lengths()
        tlen = 0
        i = 0
        for pt1, pt2 in PathSegmentIterator(self):
            dist1 = pt.dist(pt1)
            if pt2.is_arc():
                arc = pt2
                if mindist is None or dist1 < mindist:
                    mindist = dist1
                    closest = lengths[i - 1]
                dx = pt.x - arc.c.cx
                dy = pt.y - arc.c.cy
                angle = atan2(dy, dx) - arc.sstart
                if arc.sspan < 0:
                    angle = -angle
                angle = (angle) % (2 * pi)
                if angle < abs(arc.sspan):
                    r = sqrt(dx * dx + dy * dy)
                    dist1 = abs(r - arc.c.r)
                    if mindist is None or dist1 < mindist:
                        mindist = dist1
                        closest = lengths[i] + angle * arc.c.r
            else:
                if mindist is None or dist1 < mindist:
                    mindist = dist1
                    closest = lengths[i]
                dx, dy = dist_vec(pt1, pt2)
                d = sqrt(dx * dx + dy * dy)
                lx, ly = dist_vec(pt, pt1)
                mx, my = rotate(lx, ly, atan2(dy, dx))
                if mx >= 0 and mx <= d:
                    if abs(my) < mindist:
                        mindist = abs(my)
                        closest = lengths[i] + (lengths[i + 1] - lengths[i]) * mx / d
            i += 1
        assert closest is None or closest <= lengths[-1]
        return closest, mindist
    # Calculate a point on a path, then offset it by 'dist' (positive = outwards from the shape)
    # Only works for closed paths!
    def offset_point(self, pos, dist):
        assert self.closed
        plength = self.length()
        delta = 0.1
        subpath = self.subpath(pos, min(plength, pos + delta))
        orientation = self.orientation()
        if orientation:
            dist = -dist
        s = subpath.nodes[0].seg_start()
        e = subpath.nodes[-1].seg_end()
        dx, dy = dist_vec(s, e)
        angle = atan2(dy, dx) + pi / 2
        return PathPoint(s.x + dist * cos(angle), s.y + dist * sin(angle))
    def orientation(self):
        assert self.closed
        return IntPath([i.seg_end() for i in self.nodes]).orientation()
    # Return the point at 'pos' position along the path.
    def point_at(self, pos):
        return self.point_at_hint(pos, self.start_hint())[0]
    def start_hint(self):
        return (PathSegmentIterator(self), 0)
    def point_at_hint(self, pos, hint):
        it, tlen = hint
        it = it.clone()
        hint = (it.clone(), tlen)
        assert pos >= tlen
        for last, p in it:
            if pos <= tlen:
                return last, hint
            if p.is_arc():
                tseg = p.length()
            else:
                tseg = last.dist(p)
            if pos < tlen + tseg:
                alpha = (pos - tlen) / tseg
                if p.is_arc():
                    return p.at_fraction(alpha), hint
                else:
                    return weighted(last, p, alpha), hint
            tlen += tseg
            hint = (it.clone(), tlen)
        if self.closed and pos > tlen:
            return self.point_at(pos % tlen), hint
        return last, hint
    def seg_start(self):
        return self.nodes[0]
    def seg_end(self):
        return self.nodes[0] if self.closed else self.nodes[-1].seg_end()
    def __repr__(self):
        return f"Path({','.join(repr(node) for node in self.nodes)}, {repr(self.closed)})"
    def has_arcs(self):
        return any([p.is_arc() for p in self.nodes])
    def lines_to_arcs(self):
        return Path(CircleFitter.simplify(self.nodes), self.closed)
    def optimize_lines(self):
        return Path(LineOptimizer.simplify(self.nodes), self.closed)
    def bounds(self):
        xcoords = MinMax()
        ycoords = MinMax()
        for p in self.nodes:
            if p.is_point():
                xcoords.feed(p.x)
                ycoords.feed(p.y)
            elif p.is_arc():
                xcoords.feed(p.p1.x)
                xcoords.feed(p.p2.x)
                ycoords.feed(p.p1.y)
                ycoords.feed(p.p2.y)
                for q in p.quadrant_seps():
                    xcoords.feed(q.x)
                    ycoords.feed(q.y)
        return (xcoords.min, ycoords.min, xcoords.max, ycoords.max)
    def joined(self, other):
        nodes = self.nodes + (self.nodes[0:1] if self.nodes and self.closed else []) + other.nodes + (other.nodes[0:1] if other.nodes and other.closed else [])
        if nodes and nodes[0].seg_start() == nodes[-1].seg_end():
            if nodes[-1].is_point():
                nodes.pop()
            return Path(nodes, True)
        else:
            return Path(nodes, False)
    def interpolated(self):
        return Path(CircleFitter.interpolate_arcs(self.nodes, False, 1), self.closed)

class PathSegmentIterator(object):
    def __init__(self, path, index=0):
        self.path = path
        self.index = index
        assert not self.path or not self.path.nodes or self.path.nodes[0].is_point()
    def clone(self):
        return PathSegmentIterator(self.path, self.index)
    def __iter__(self):
        return self
    def __next__(self):
        if self.index + 1 < len(self.path.nodes):
            start, end = self.path.nodes[self.index : self.index + 2]
            self.index += 1
            return (start.seg_end(), end)
        if self.path.closed:
            if self.index < len(self.path.nodes):
                start = self.path.nodes[-1].seg_end()
                end = self.path.nodes[0]
                self.index += 1
                return start, end
            else:
                raise StopIteration
        else:
            raise StopIteration

def dist(a, b):
    a = a.seg_end()
    b = b.seg_start()
    dx = b.x - a.x
    dy = b.y - a.y
    return sqrt(dx * dx + dy * dy)

def dist_vec(a, b):
    a = a.seg_end()
    b = b.seg_start()
    return b.x - a.x, b.y - a.y

def weighted(p1, p2, alpha):
    return PathPoint(p1.x + (p2.x - p1.x) * alpha, p1.y + (p2.y - p1.y) * alpha, p2.speed_hint)

def weighted_with_arcs(p1, p2, alpha):
    p1 = p1.seg_end()
    if p2.is_arc():
        return p2.at_fraction(alpha)
    return weighted(p1, p2, alpha)

def SameOrientation(path, expected):
    return path if Orientation(path) == expected else ReversePath(path)

def bounds_area(b):
    sx, sy, ex, ey = b
    return abs(ex - sx) * abs(ey - sy)

# Is b1 inside or overlapping b2?
def inside_bounds(b1, b2):
    sx1, sy1, ex1, ey1 = b1
    sx2, sy2, ex2, ey2 = b2
    return sx1 >= sx2 and ex1 <= ex2 and sy1 >= sy2 and ey1 <= ey2

def bounds_overlap(b1, b2):
    sx1, sy1, ex1, ey1 = b1
    sx2, sy2, ex2, ey2 = b2
    return ex1 >= sx2 and sx1 <= ex2 and ey1 >= sy2 and sy1 <= ey2

def point_inside_bounds(b, p):
    sx, sy, ex, ey = b
    return p.x >= sx and p.x <= ex and p.y >= sy and p.y <= ey

def dist_line_to_point(p1, p2, p):
    assert p1.is_point()
    assert p2.is_point()
    xlen = p2.x - p1.x
    ylen = p2.y - p1.y
    llen2 = xlen ** 2 + ylen ** 2
    dotp = (p.x - p1.x) * xlen + (p.y - p1.y) * ylen
    if llen2 > 0:
        t = min(1, max(0, dotp / llen2))
        pcross = PathPoint(p1.x + t * xlen, p1.y + t * ylen)
    else:
        pcross = p1
    return pcross.dist(p)

def expand_bounds(b1, amount):
    sx, sy, ex, ey = b1
    sx -= amount
    sy -= amount
    ex += amount
    ey += amount
    return (sx, sy, ex, ey)

def max_bounds(*b):
    b = [i for i in b if i is not None]
    if not b:
        return None
    sx, sy, ex, ey = b[0]
    for b2 in b[1:]:
        sx2, sy2, ex2, ey2 = b2
        sx = min(sx, sx2)
        sy = min(sy, sy2)
        ex = max(ex, ex2)
        ey = max(ey, ey2)
    return sx, sy, ex, ey

eps = 1e-6

class CandidateCircle(object):
    def __init__(self, cx, cy, r):
        self.cx = cx
        self.cy = cy
        self.r = r
    def as_tuple(self):
        return (self.cx, self.cy, self.r)
    @staticmethod
    def from_tuple(t):
        return CandidateCircle(*t)
    def __eq__(self, other):
        return self.cx == other.cx and self.cy == other.cy and self.r == other.r
    def dist(self, p):
        return sqrt((p.x - self.cx) ** 2 + (p.y - self.cy) ** 2)
    def angle(self, p):
        return atan2(p.y - self.cy, p.x - self.cx)
    def centre(self):
        return PathPoint(self.cx, self.cy)
    def at_angle(self, angle):
        angle = angle % (2 * pi)
        return PathPoint(self.cx + self.r * cos(angle), self.cy + self.r * sin(angle))
    def translated(self, dx, dy):
        return CandidateCircle(self.cx + dx, self.cy + dy, self.r)
    def scaled(self, cx, cy, scale):
        return CandidateCircle(*self.centre().scaled(cx, cy, scale).as_tuple(), self.r * scale)
    def calc_error(self, points):
        minerr = 0
        maxerr = 0
        for j in points:
            r2 = self.dist(j)
            err = self.r - r2
            if err < minerr: minerr = err
            if err > maxerr: maxerr = err
        return maxerr - minerr
    def calc_error2(self, points):
        maxerr = 0
        for j in points:
            r2 = self.dist(j)
            err = self.r - r2
            maxerr = max(maxerr, abs(err))
        for j in range(len(points) - 1):
            r2 = self.dist(weighted(points[j], points[j + 1], 0.5))
            err = self.r - r2
            maxerr = max(maxerr, abs(err))
        return maxerr
    # Return the number of positive and negative angle delta and the total span
    # (sum of absolute values, assumes angles of one direction only)
    def count_angles(self, points):
        if not points:
            return 0, 0
        langle = self.angle(points[0])
        pangles = nangles = 0
        maxpos = maxneg = 0
        tangle = 0
        for p in points[1:]:
            angle = self.angle(p)
            if angle != langle:
                dangle = (angle - langle) % (2 * pi)
                if dangle >= pi:
                    tangle -= (2 * pi - dangle)
                    nangles += 1
                    maxneg = max(maxneg, 2 * pi - dangle)
                else:
                    tangle += dangle
                    pangles += 1
                    maxpos = max(maxpos, dangle)
                langle = angle
        if pangles and nangles:
            # Correction for quantization noise
            if pangles > 10 * nangles and maxpos > 10 * maxneg:
                pangles += nangles
                nangles = 0
            if nangles > 10 * pangles and maxneg > 10 * maxpos:
                nangles += pangles
                pangles = 0
        return pangles, nangles, abs(tangle)
    def snap(self, pt):
        return self.at_angle(self.angle(pt))
    def __str__(self):
        return "X=%0.3f Y=%0.3f R=%0.3f" % (self.cx, self.cy, self.r)
    def __repr__(self):
        return f"CandidateCircle({self.cx}, {self.cy}, {self.r})"
    @staticmethod
    def from_3(p1, p2, p3):
        # http://www.ambrsoft.com/TrigoCalc/Circle3D.htm
        x1, y1 = p1.x, p1.y
        x2, y2 = p2.x, p2.y
        x3, y3 = p3.x, p3.y
        A = x1 * (y2 - y3) - y1 * (x2 - x3) + x2 * y3  - x3 * y2
        if abs(A) < eps:
            return None
        s1 = x1 ** 2 + y1 ** 2
        s2 = x2 ** 2 + y2 ** 2
        s3 = x3 ** 2 + y3 ** 2
        x = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / (2 * A)
        y = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / (2 * A)
        r = PathPoint(x, y).dist(p1)
        if r < 5 / GeometrySettings.RESOLUTION:
            return None
        return CandidateCircle(x, y, r)

# Incredibly dodgy (but perhaps still useful) lines-to-arc fitter
# Should this be a mostly fake class with only static methods? No idea.
# There's very little state to keep, just the points array I suppose.
class CircleFitter(object):
    error_threshold = 2.0 / GeometrySettings.RESOLUTION
    # Maximum distance between subsequent points to still describe a segment
    # and not just a straight line
    line_segment_threshold = 3.0

    # Replace this with a better method if needed
    @staticmethod
    def fit_circle(pts, start, end):
        c1 = CandidateCircle.from_3(pts[start], pts[(start + end) // 2], pts[end - 1])
        c2 = CandidateCircle.from_3(pts[start], pts[(2 * start + end) // 3], pts[end - 1])
        c3 = CandidateCircle.from_3(pts[start], pts[(start + 2 * end) // 3], pts[end - 1])
        lots = 9e9
        c1error = c1.calc_error2(pts[start:end]) if c1 else lots
        c2error = c2.calc_error2(pts[start:end]) if c2 else lots
        c3error = c3.calc_error2(pts[start:end]) if c3 else lots
        return c1 if c1error < max(c2error, c3error) else (c2 if c2error < c3error else c3)

    # Recursive circle fitter. Subdivide the range until some arcs are found, then
    # merge any adjacent ones.
    @staticmethod
    def fit_arcs1(pts, start, end, recurse=True):
        # Not enough points to describe a circle?
        if end < start + 3:
            return [], -1
        c = CircleFitter.fit_circle(pts, start, end)
        if c and c.r < 100 * pts[start].dist(pts[end - 1]):
            # Reject the match if a mix of positive and negative relative angles
            # or if the total angle span is > 270 degrees
            pangles, nangles, tangle = c.count_angles(pts[start:end])
            if (pangles == 0 or nangles == 0) and tangle <= 1.5 * pi:
                error = c.calc_error2(pts[start:end])
                if error < CircleFitter.error_threshold:
                    return [(start, end, c, error, 1 if pangles else -1)], error
        if not recurse:
            return [], -1
        if not pts[start].joinable(pts[end - 1]):
            return [], -1
        mid = (start + end) // 2
        if not pts[start].joinable(pts[mid - 1]):
            return [], -1
        left, lerror = CircleFitter.fit_arcs1(pts, start, mid)
        right, rerror = CircleFitter.fit_arcs1(pts, mid, end)
        # Coalesce
        while len(left) and len(right) and left[-1][1] == right[0][0] and left[-1][4] != -right[-1][4]:
            coal, cerror = CircleFitter.fit_arcs1(pts, left[-1][0], right[0][1], False)
            if not coal:
                break
            # If coalescing doubles the error, don't do it.
            if cerror > 2 * max(lerror, rerror):
                break
            left[-1] = coal[0]
            right.pop(0)
        while len(left) and len(right) and left[-1][1] < right[0][0]:
            # Extend by one
            lstart, lend, lcircle, lerror, ldir = left[-1]
            coal, cerror = CircleFitter.fit_arcs1(pts, lstart, lend + 1, False)
            if coal and cerror <= lerror:
                left[-1] = coal[0]
                lerror = cerror
                continue
            rstart, rend, rcircle, rerror, rdir = right[0]
            coal, cerror = CircleFitter.fit_arcs1(pts, rstart - 1, rend, False)
            if coal and cerror <= rerror:
                right[0] = coal[0]
                rerror = cerror
                continue
            if rstart - lend > 5:
                coal, cerror = CircleFitter.fit_arcs1(pts, lend, rstart, True)
                if cerror < max(lerror, rerror):
                    left += coal
            break
        return left + right, max(lerror, rerror)

    @staticmethod
    def fit_arcs2(pts, start, end, recurse=True):
        pos = start
        run_start = pos
        res = []
        while pos < end - 1:
            d = pts[pos].dist(pts[pos + 1])
            if d > CircleFitter.line_segment_threshold:
                #print ("Jump at ", pos, d)
                if pos - run_start > 3:
                    arcs, error = CircleFitter.fit_arcs1(pts, run_start, pos)
                    res += arcs
                run_start = pos + 1
            pos += 1
        if end - run_start > 3:
            arcs, error = CircleFitter.fit_arcs1(pts, run_start, end)
            res += arcs
        return res

    @staticmethod
    def simplify(pts):
        if len(pts) < 3:
            return pts
        pts_out = []
        last = 0
        for i, p in enumerate(pts):
            if p.is_arc():
                pts_out += CircleFitter.simplify_noarcs(pts[last:i - 1]) + [p.p1, p]
                last = i + 1
        if pts_out:
            return pts_out + CircleFitter.simplify_noarcs(pts[last:])
        return CircleFitter.simplify_noarcs(pts)
    @staticmethod
    def simplify_noarcs(pts):
        pts_out = []
        arcs = CircleFitter.fit_arcs2(pts, 0, len(pts))
        last = 0
        for start, end, c, error, adir in arcs:
            pts_out += pts[last:start]

            p1, p2 = pts[start], pts[end - 1]
            sstart, eangle = c.angle(p1), c.angle(p2)
            if adir == 1 and eangle < sstart:
                eangle += 2 * pi
            if adir == -1 and eangle > sstart:
                eangle -= 2 * pi

            pts_out.append(c.snap(pts[start]))
            pts_out.append(PathArc(c.snap(pts[start]), c.snap(pts[end - 1]), c, end - start, sstart, eangle - sstart))
            last = end
        pts_out += pts[last:]
        return pts_out

    @staticmethod
    def interpolate_arcs(points, debug, scaling_factor):
        pts = []
        for p in points:
            if p.is_arc():
                #tag, p1, p2, c, steps, sstart, sspan = p
                steps = p.steps
                if not debug:
                    steps *= ceil(min(4, max(1, scaling_factor)))
                else:
                    steps = 3
                for i in range(1 + steps):
                    pts.append(p.at_fraction(i / steps))

                pts.append(p.p2)
            else:
                pts.append(p)
        return pts

class LineOptimizer(object):
    @staticmethod
    def simplify(points):
        last = points[0]
        assert last.is_point()
        # XXXKF make it settable
        # Detection threshold (the shortest line that will initiate coalescing)
        threshold = 1.0
        # Error threshold (coalesce until one of the removed points sticks out by this much)
        threshold2 = 0.2
        run_start = None
        output = points[0:1]
        for i in range(1, len(points)):
            pt = points[i]
            if pt.is_arc():
                # Copy arcs verbatim
                if run_start is not None:
                    output.append(last)
                    run_start = None
                output.append(pt)
                last = pt.seg_end()
                continue
            d = last.dist(pt)
            if d < threshold:
                if run_start is None:
                    run_start = i
                    prev_error = None
                    output.append(pt)
                    last = pt
                    continue
            if run_start is not None:
                ptrs = points[run_start]
                d2 = dist(ptrs, pt)
                if d2 != 0:
                    maxerr = 0
                    # Checks the intermediate points against a straight line from run_start to i
                    runlen = 0
                    for j in range(run_start + 1, i):
                        # Distance to the start point
                        d1 = dist(ptrs, points[j])
                        # Distance to the end point
                        d3 = dist(pt, points[j])
                        if d1 <= d2 and d3 <= d2:
                            papprox = weighted(ptrs, pt, d1/d2)
                            error = papprox.dist(points[j])
                            maxerr = max(maxerr, error)
                        else:
                            error = threshold2
                        if d1 > d2 or error >= threshold2:
                            print (i - 1 - run_start, "items skipped, prev maxerr", preverr, "now", error, "runlen", runlen)
                            if last != output[-1]:
                                output.append(last)
                            run_start = i
                            last = pt
                            break
                        runlen += dist(points[j-1], points[j])
                    preverr = maxerr
            if run_start is None:
                output.append(pt)
            last = pt
        if run_start is not None:
            output.append(last)
        return output

class IntPath(object):
    def __init__(self, real_points, ints_already=False):
        self.int_points = PtsToInts(real_points) if not ints_already else real_points
    def real_points(self):
        return PtsFromInts(self.int_points)
    def orientation(self):
        return Orientation(self.int_points)
    def reversed(self):
        return IntPath(list(reversed(self.int_points)), True)
    def force_orientation(self, orientation):
        if self.orientation() == orientation:
            return self
        else:
            return self.reversed()
    def area(self):
        return Area(self.int_points)

def run_clipper_simple(operation, subject_polys=[], clipper_polys=[], bool_only=False, return_ints=False, fillMode=None):
    if fillMode is None:
        fillMode = GeometrySettings.fillMode
    pc = Pyclipper()
    for path in subject_polys:
        try:
            pc.AddPath(path.int_points, PT_SUBJECT, True)
        except ClipperException:
            pass #print (path.int_points)
    for path in clipper_polys:
        try:
            pc.AddPath(path.int_points, PT_CLIP, True)
        except ClipperException:
            pass #print (path.int_points)
    try:
        res = pc.Execute(operation, fillMode, fillMode)
    except ClipperException:
        res = None
    if bool_only:
        return True if res else False
    if not res:
        return []
    if return_ints:
        return [IntPath(i, True) for i in res]
    else:
        return [PtsFromInts(i) for i in res]

def run_clipper_advanced(operation, subject_polys=[], clipper_polys=[], subject_paths=[], fillMode=None):
    if fillMode is None:
        fillMode = GeometrySettings.fillMode
    pc = Pyclipper()
    if operation == CT_DIFFERENCE and subject_paths and not subject_polys:
        lowest_y = None
        for i in subject_paths:
            p = i.int_points
            i = 0
            j = len(p) - 1
            while i + 1 < len(p) and p[0] == p[i + 1]:
                i += 1
            while j - 1 > i and p[j] == p[-1]:
                j -= 1
            if j == i + 1 and p[i][1] == p[j][1]:
                if lowest_y is None or p[i][1] < lowest_y:
                    lowest_y = p[i][1]
        if lowest_y is not None:
            import traceback
            print ("Warning: CT_DIFFERENCE may trigger a Clipper bug affecting horizontal lines and no workaround geometry has been passed!")
            traceback.print_stack()
    for path in subject_polys:
        pc.AddPath(path.int_points, PT_SUBJECT, True)
    for path in subject_paths:
        pc.AddPath(path.int_points, PT_SUBJECT, False)
    for path in clipper_polys:
        pc.AddPath(path.int_points, PT_CLIP, True)
    tree = pc.Execute2(operation, fillMode, fillMode)
    return tree

def run_clipper_checkpath(operation, subject_polys=[], clipper_polys=[], subject_paths=[], fillMode=None):
    tree = run_clipper_advanced(operation, subject_polys, clipper_polys, subject_paths, fillMode)
    return OpenPathsFromPolyTree(tree)

def arc_from_cad(p1, p2, bulge):
    theta = 4 * atan(bulge)
    dx, dy = p2.x - p1.x, p2.y - p1.y
    mid = weighted(p1, p2, 0.5)
    angle = atan2(dy, dx)
    dist = sqrt(dx * dx + dy * dy)
    d = dist / 2
    r = abs(d / sin(theta / 2))
    c = d / tan(theta / 2)
    cx = mid.x - c * sin(angle)
    cy = mid.y + c * cos(angle)
    sa = atan2(p1.y - cy, p1.x - cx)
    ea = sa + theta
    return circle2(cx, cy, r, 1000, sa, ea)

def dxf_polyline_to_points(entity, scaling=1):
    points = []
    lastx = entity[-1][0] * scaling
    lasty = entity[-1][1] * scaling
    lastbulge = entity[-1][4]
    eps = 0.0001
    for point in entity:
        x = point[0] * scaling
        y = point[1] * scaling
        endp = PathPoint(x, y)
        if lastbulge:
            cn = arc_from_cad(PathPoint(lastx, lasty), PathPoint(x, y), lastbulge)
            # Do not add a zero-length segment.
            if len(points) and points[-1].is_point() and cn[0].dist(PathPoint(lastx, lasty)) <= eps:
                del cn[0]
            points += cn
            if points[-1].p2.dist(endp) > eps:
                points.append(endp)
        elif not points or points[-1].seg_end().dist(endp) > eps:
            points.append(endp)
        lastbulge = point[4]
        lastx, lasty = x, y
    if not entity.closed and len(points) > 3 and points[0].seg_start().dist(points[-1].seg_end()) <= eps:
        # The endpoints are close enough to consider the polyline closed. Eliminate redundant point if any.
        if points[-1].is_point():
            del points[-1]
        return points, True
    return points, entity.closed

def is_calculation_cancelled():
    return getattr(threading.current_thread(), 'cancelled', False)

def set_calculation_progress(amount_done, amount_total):
    setattr(threading.current_thread(), 'progress', (min(amount_done, amount_total - 1), amount_total))
