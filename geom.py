from pyclipper import *
from math import *

class GeometrySettings:
    RESOLUTION = 25.0
    fillMode = PFT_POSITIVE
    simplify_arcs = False

def PtsToInts(points):
    return [(round(x * GeometrySettings.RESOLUTION), round(y * GeometrySettings.RESOLUTION)) for x, y in points]

def PtsFromInts(points):
    return [(x / GeometrySettings.RESOLUTION, y / GeometrySettings.RESOLUTION) for x, y in points]
    
def PtsToIntsPos(points):
    res = [(round(x * GeometrySettings.RESOLUTION), round(y * GeometrySettings.RESOLUTION)) for x, y in points]
    if Orientation(res) == False:
        res = list(reversed(res))
    return res

def circle(x, y, r, n=None, sa=0, ea=2*pi):
    if n is None:
        n = pi * r * GeometrySettings.RESOLUTION
    n *= abs((ea - sa) / (2 * pi))
    n = ceil(n)
    res = []
    for i in range(n + 1):
        a = sa + i * (ea - sa) / n
        newpt = (x + r * cos(a), y + r * sin(a))
        if not res or newpt != res[-1]:
            res.append(newpt)
    return res

def arc_length(arc):
    # tag, p1, p2, c, steps, sangle, sspan = arc
    return abs(arc[6]) * arc[3].r

def dist_fast(a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return sqrt(dx * dx + dy * dy)

def maxaxisdist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

def seg_start(seg):
    return seg[1] if len(seg) == 7 else seg
def seg_end(seg):
    return seg[2] if len(seg) == 7 else seg

def dist(a, b):
    a = seg_end(a)
    b = seg_start(b)
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return sqrt(dx * dx + dy * dy)

def dist_vec(a, b):
    a = seg_end(a)
    b = seg_start(b)
    return b[0] - a[0], b[1] - a[1]

def weighted(p1, p2, alpha):
    return p1[0] + (p2[0] - p1[0]) * alpha, p1[1] + (p2[1] - p1[1]) * alpha

def weighted_with_arcs(p1, p2, alpha):
    if len(p1) == 7:
        p1 = p1[2]
    if len(p2) == 7:
        return p2[3].at_angle(p2[5] + alpha * p2[6])
    return weighted(p1, p2, alpha)

def SameOrientation(path, expected):
    return path if Orientation(path) == expected else ReversePath(path)

# Is b1 inside or overlapping b2?
def inside_bounds(b1, b2):
    sx1, sy1, ex1, ey1 = b1
    sx2, sy2, ex2, ey2 = b2
    return sx1 >= sx2 and ex1 <= ex2 and sy1 >= sy2 and ey1 <= ey2

def point_inside_bounds(b, p):
    sx, sy, ex, ey = b
    return p[0] >= sx and p[0] <= ex and p[1] >= sy and p[1] <= ey

def point_is_arc(p):
    return len(p) == 7

def dist_line_to_point(p1, p2, p):
    xlen = p2[0] - p1[0]
    ylen = p2[1] - p1[1]
    llen2 = xlen ** 2 + ylen ** 2
    dotp = (p[0] - p1[0]) * xlen + (p[1] - p1[1]) * ylen
    if llen2 > 0:
        t = min(1, max(0, dotp / llen2))
        pcross = (p1[0] + t * xlen, p1[1] + t * ylen)
    else:
        pcross = p1
    return dist(pcross, p)

def expand_bounds(b1, amount):
    sx, sy, ex, ey = b1
    sx -= amount
    sy -= amount
    ex += amount
    ey += amount
    return (sx, sy, ex, ey)

def max_bounds(b1, *b2etc):
    sx, sy, ex, ey = b1
    for b2 in b2etc:
        sx2, sy2, ex2, ey2 = b2
        sx = min(sx, sx2)
        sy = min(sy, sy2)
        ex = max(ex, ex2)
        ey = max(ey, ey2)
    return sx, sy, ex, ey

def path_length(path):
    return sum([dist(path[i], path[i + 1]) for i in range(len(path) - 1)]) + sum([arc_length(arc) for arc in path if len(arc) == 7])

def path_lengths(path):
    res = [0]
    lval = 0
    for i in range(len(path) - 1):
        if len(path[i + 1]) == 2:
            lval += dist(path[i], path[i + 1])
        else:
            lval += arc_length(path[i + 1])
        res.append(lval)
    return res   

def reverse_path(path):
    res = []
    i = len(path) - 1
    while i >= 0:
        pi = path[i]
        if len(pi) == 2:
            res.append(pi)
        else: # arc
            # tag, p1, p2, c, steps, sangle, sspan = p
            res.append(pi[2]) # end point
            res.append(("ARC_CW" if pi[0] == "ARC_CCW" else "ARC_CW", pi[2], pi[1], pi[3], pi[4], pi[5] + pi[6], -pi[6]))
            # Skip start point, as it is already inside the arc
            i -= 1
            # Verify that it actually was
            if path[i] != pi[1]:
                for n, p in enumerate(path):
                    print ("Item", n, p)
            assert path[i] == pi[1]
        i -= 1
    return res

def cut_arc(arc, alpha, beta):
    alpha = max(0, alpha)
    beta = min(1, beta)
    if alpha == 0 and beta == 1:
        return [arc[1], arc]
    c = arc[3]
    start = arc[5] + arc[6] * alpha
    span = arc[6] * (beta - alpha)
    arc_start = c.at_angle(start)
    arc_end = c.at_angle(start + span)
    return [arc_start, (arc[0], arc_start, arc_end, arc[3], arc[4], start, span)]

def calc_subpath(path, start, end, closed=False):
    res = []
    tlen = 0
    if closed:
        # That's a bit wasteful, but we'll live with this for now.
        path = path + path[0:1]
    last = path[0]
    for p in path[1:]:
        if len(p) == 7: # Arc
            tag, p1, p2, c, points, sstart, sspan = p
            assert dist(last, p1) < 1 / GeometrySettings.RESOLUTION
            d = arc_length(p)
            if d == 0:
                continue
            tlen_after = tlen + d
            if tlen_after >= start and tlen <= end:
                alpha = (start - tlen) / d
                beta = (end - tlen) / d
                res += cut_arc(p, alpha, beta)
            last = p2
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
            last = p
        tlen = tlen_after
    # Eliminate duplicates
    res = [p for i, p in enumerate(res) if i == 0 or p != res[i - 1]]
    return res

eps = 1e-6

class CandidateCircle(object):
    def __init__(self, cx, cy, r):
        self.cx = cx
        self.cy = cy
        self.r = r
    def dist(self, p):
        return sqrt((p[0] - self.cx) ** 2 + (p[1] - self.cy) ** 2)
    def angle(self, p):
        return atan2(p[1] - self.cy, p[0] - self.cx)
    def at_angle(self, angle):
        return (self.cx + self.r * cos(angle), self.cy + self.r * sin(angle))
    def translated(self, dx, dy):
        return CandidateCircle(self.cx + dx, self.cy + dy, self.r)
    def scaled(self, cx, cy, scale):
        return CandidateCircle(*scale_point((self.cx, self.cy), cx, cy, scale), self.r * scale)
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
        minerr = 0
        maxerr = 0
        for j in points:
            r2 = self.dist(j)
            err = self.r - r2
            if err < minerr: minerr = err
            if err > maxerr: maxerr = err
        for j in range(len(points) - 1):
            r2 = self.dist(weighted(points[j], points[j + 1], 0.5))
            err = self.r - r2
            if err < minerr: minerr = err
            if err > maxerr: maxerr = err
        return maxerr - minerr
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
    @staticmethod
    def from_3(p1, p2, p3):
        # http://www.ambrsoft.com/TrigoCalc/Circle3D.htm
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        A = x1 * (y2 - y3) - y1 * (x2 - x3) + x2 * y3  - x3 * y2
        if abs(A) < eps:
            return None
        s1 = x1 ** 2 + y1 ** 2
        s2 = x2 ** 2 + y2 ** 2
        s3 = x3 ** 2 + y3 ** 2
        x = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / (2 * A)
        y = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / (2 * A)
        r = dist((x, y), p1)
        return CandidateCircle(x, y, r)

# Incredibly dodgy (but perhaps still useful) lines-to-arc fitter
# Should this be a mostly fake class with only static methods? No idea.
# There's very little state to keep, just the points array I suppose.
class CircleFitter(object):
    error_threshold = 2.5 / GeometrySettings.RESOLUTION
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
        if c:
            # Reject the match if a mix of positive and negative relative angles
            # or if the total angle span is > 270 degrees
            pangles, nangles, tangle = c.count_angles(pts[start:end])
            if (pangles == 0 or nangles == 0) and tangle <= 1.5 * pi:
                error = c.calc_error2(pts[start:end])
                if error < CircleFitter.error_threshold:
                    return [(start, end, c, error, 1 if pangles else -1)], error
        if not recurse:
            return [], -1
        mid = (start + end) // 2
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
            d = dist(pts[pos], pts[pos + 1])
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
        pts_out = []
        arcs = CircleFitter.fit_arcs2(pts, 0, len(pts))
        last = 0
        for start, end, c, error, adir in arcs:
            pts_out += pts[last:start]

            p1, p2 = pts[start], pts[end - 1]
            sangle, eangle = c.angle(p1), c.angle(p2)
            if adir == 1 and eangle < sangle:
                eangle += 2 * pi
            if adir == -1 and eangle > sangle:
                eangle -= 2 * pi

            pts_out.append(c.snap(pts[start]))
            pts_out.append(("ARC_CCW" if adir > 0 else "ARC_CW", c.snap(pts[start]), c.snap(pts[end - 1]), c, end - start, sangle, eangle - sangle))
            last = end
        pts_out += pts[last:]
        return pts_out

    @staticmethod
    def interpolate_arcs(points, debug, scaling_factor):
        pts = []
        for p in points:
            if type(p[0]) is str:
                tag, p1, p2, c, steps, sangle, sspan = p
                if not debug:
                    steps *= ceil(min(4, max(1, scaling_factor)))
                else:
                    steps = 3
                step = sspan / steps
                for i in range(1 + steps):
                    pts.append(c.at_angle(sangle + step * i))

                pts.append((p[2][0], p[2][1]))
            else:
                pts.append((p[0], p[1]))
        return pts

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

def run_clipper_simple(operation, subject_polys=[], clipper_polys=[], bool_only=False, return_ints=False):
    pc = Pyclipper()
    for path in subject_polys:
        pc.AddPath(path.int_points, PT_SUBJECT, True)
    for path in clipper_polys:
        pc.AddPath(path.int_points, PT_CLIP, True)
    res = pc.Execute(operation, GeometrySettings.fillMode, GeometrySettings.fillMode)
    if bool_only:
        return True if res else False
    if not res:
        return []
    if return_ints:
        return [IntPath(i, True) for i in res]
    else:
        return [PtsFromInts(i) for i in res]

def run_clipper_advanced(operation, subject_polys=[], clipper_polys=[], subject_paths=[]):
    pc = Pyclipper()
    for path in subject_polys:
        pc.AddPath(path.int_points, PT_SUBJECT, True)
    for path in subject_paths:
        pc.AddPath(path.int_points, PT_SUBJECT, False)
    for path in clipper_polys:
        pc.AddPath(path.int_points, PT_CLIP, True)
    tree = pc.Execute2(operation, GeometrySettings.fillMode, GeometrySettings.fillMode)
    return tree

def translate_point(point, dx, dy):
    return (point[0] + dx, point[1] + dy)
def translate_gen_point(point, dx, dy):
    if len(point) == 2:
        return (point[0] + dx, point[1] + dy)
    else:
        assert len(point) == 7
        tag, p1, p2, c, points, sstart, sspan = point
        return (tag, translate_point(p1, dx, dy), translate_point(p2, dx, dy), c.translated(dx, dy), points, sstart, sspan)

def scale_point(point, cx, cy, scale):
    return (point[0] - cx) * scale + cx, (point[1] - cy) * scale + cy
def scale_gen_point(point, cx, cy, scale):
    if len(point) == 2:
        return scale_point(point, cx, cy, scale)
    else:
        assert len(point) == 7
        tag, p1, p2, c, points, sstart, sspan = point
        return (tag, scale_point(p1, cx, cy, scale), scale_point(p2, dx, dy), c.scaled(cx, cy, r), points, sstart, sspan)

def dxf_polyline_to_points(entity):
    points = []
    lastx, lasty = entity[-1][0:2]
    lastbulge = entity[-1][4]
    for point in entity:
        x, y = point[0:2]
        if lastbulge:
            theta = 4 * atan(lastbulge)
            dx, dy = x - lastx, y - lasty
            mx, my = weighted((lastx, lasty), (x, y), 0.5)
            angle = atan2(dy, dx)
            dist = sqrt(dx * dx + dy * dy)
            d = dist / 2
            r = abs(d / sin(theta / 2))
            c = d / tan(theta / 2)
            cx = mx - c * sin(angle)
            cy = my + c * cos(angle)
            sa = atan2(lasty - cy, lastx - cx)
            ea = sa + theta
            points += circle(cx, cy, r, 1000, sa, ea)
            points.append((x, y))
        else:
            points.append((x, y))
        lastbulge = point[4]
        lastx, lasty = x, y
    return points, entity.closed

# For a path and a given point, find the nearest point on a path.
# Returns the curve-length to a matching point *on* the path and the distance
# from that point to the given point.
def closest_point(path, closed, pt):
    def rotate(x, y, angle):
        cosv, sinv = -cos(angle), sin(angle)
        return x * cosv - y * sinv, x * sinv + y * cosv
    mindist = None
    closest = None
    if closed:
        path = path + path[0:1]
    lengths = path_lengths(path)
    tlen = 0
    for i in range(len(path) - 1):
        pt1 = seg_end(path[i])
        pt2 = path[i + 1]
        dist1 = dist(pt, pt1)
        if len(pt2) == 7:
            tag, pt1, pt2, c, points, sstart, sspan = pt2
            if mindist is None or dist1 < mindist:
                mindist = dist1
                closest = lengths[i - 1]
            dx = pt[0] - c.cx
            dy = pt[1] - c.cy
            angle = atan2(dy, dx) - sstart
            if sspan < 0:
                angle = -angle
            angle = (angle) % (2 * pi)
            if angle < abs(sspan):
                r = sqrt(dx * dx + dy * dy)
                dist1 = abs(r - c.r)
                if mindist is None or dist1 < mindist:
                    mindist = dist1
                    closest = lengths[i] + angle * c.r
        else:
            if mindist is None or dist1 < mindist:
                mindist = dist1
                closest = lengths[i]
            pt2 = seg_start(path[(i + 1) % len(path)])
            dx, dy = dist_vec(pt1, pt2)
            d = sqrt(dx * dx + dy * dy)
            lx, ly = dist_vec(pt, pt1)
            mx, my = rotate(lx, ly, atan2(dy, dx))
            if mx >= 0 and mx <= d:
                if abs(my) < mindist:
                    mindist = abs(my)
                    closest = lengths[i] + (lengths[i + 1] - lengths[i]) * mx / d
    return closest, mindist

# Calculate a point on a path, then offset it by 'dist' (positive = outwards from the shape)
# Only works for closed paths!
def offset_point_on_path(path, pos, dist):
    plength = path_length(path)
    subpath = calc_subpath(path, pos, min(plength, pos + 0.1))
    orientation = IntPath(path).orientation()
    if orientation:
        dist = -dist
    s = seg_start(subpath[0])
    e = seg_end(subpath[-1])
    x1, y1 = s
    dx, dy = dist_vec(s, e)
    angle = atan2(dy, dx) + pi / 2
    return x1 + dist * cos(angle), y1 + dist * sin(angle)
