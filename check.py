from process import *
from geom import *
from gcodegen import *

def prepare(ranges):
    res = []
    for s, e in ranges:
        res.append((int(s * 64), int(e * 64)))
    return res

def close_enough(a, b, eps=0.001):
    return abs(a - b) < eps
def close_enough_tuple(a, b, eps=0.001):
    return all([close_enough(a[i], b[i], eps) for i in range(max(len(a), len(b)))])

# PathPoint

a = PathPoint(10, 0)
b = PathPoint(20, 0)
assert a == PathPoint(10, 0)
assert a != PathPoint(20, 0)
assert b == PathPoint(20, 0)
assert b != PathPoint(10, 0)
assert a.translated(10, 0) == PathPoint(20, 0)
assert a.translated(10, 10) == PathPoint(20, 10)
assert a.scaled(5, 0, 2) == PathPoint(15, 0)
assert a.scaled(0, 0, 2) == PathPoint(20, 0)
assert a.scaled(10, -10, 2) == PathPoint(10, 10)
assert a.dist(b) == 10
assert a.dist(PathPoint(10, -20)) == 20

# PathArc

r = PathArc(PathPoint(10, 0), PathPoint(0, 10), CandidateCircle(0, 0, 10), 10, 0, pi / 2)
r2 = r.reversed()
assert r2.p1 == r.p2
assert r2.p2 == r.p1
assert r2.sstart == r.sspan
assert r2.sspan == -r.sspan

r3 = r.scaled(0, 0, 2)
assert r3.p1 == PathPoint(20, 0)
assert r3.p2 == PathPoint(0, 20)
assert r3.c.cx == r.c.cx
assert r3.c.cy == r.c.cy
assert r3.c.r == r.c.r * 2
assert r3.sstart == r.sstart
assert r3.sspan == r.sspan

r4 = r.cut(0.25, 0.75)[1]
assert abs(r4.p1.x - 10 * cos(pi / 8)) < 0.001
assert abs(r4.p1.y - 10 * sin(pi / 8)) < 0.001
assert abs(r4.p2.x - 10 * cos(3 * pi / 8)) < 0.001
assert abs(r4.p2.y - 10 * sin(3 * pi / 8)) < 0.001
assert abs(r4.sstart - pi / 8) < 0.001
assert abs(r4.sspan - pi / 4) < 0.001

r5 = r.scaled(5, 0, 2)
assert r5.p1 == PathPoint(15, 0)
assert r5.p2 == PathPoint(-5, 20)

r6 = r.translated(10, 5)
assert r6.p1 == PathPoint(20, 5)
assert r6.p2 == PathPoint(10, 15)
assert r6.c.centre() == PathPoint(10, 5)

r = PathArc(PathPoint(0, 10), PathPoint(-10, 0), CandidateCircle(0, 0, 10), 10, pi / 2, pi / 2)
r2 = PathArc.from_tuple(r.as_tuple())
assert r.p1 == r2.p1
assert r.p2 == r2.p2
assert r.c.centre() == r2.c.centre()
assert r.c.r == r2.c.r
assert r.steps == r2.steps
assert r.sstart == r2.sstart
assert r.sspan == r2.sspan

r4 = r.cut(0.25, 0.75)[1]
assert abs(r4.sstart - 5 * pi / 8) < 0.001
assert abs(r4.sspan - pi / 4) < 0.001

# path_point

p = [ PathPoint(0, 0), PathPoint(100, 0), PathPoint(100, 100), PathPoint(0, 100) ]
assert path_point(p, 50, closed = True) == PathPoint(50, 0)
assert path_point(p, 150, closed = True) == PathPoint(100, 50)
assert path_point(p, 250, closed = True) == PathPoint(50, 100)
assert path_point(p, 350, closed = True) == PathPoint(0, 50)

# path_length, path_lengths

lenquad10 = 2 * pi * 10 / 4 # length of a quadrant of a circle of radius 10

p = [ PathPoint(0, 0), PathPoint(100, 0), PathPoint(100, 100), PathPoint(0, 100) ]
assert close_enough(path_length(p, True), 400)
assert path_lengths(p + p[0:1]) == [0, 100.0, 200.0, 300.0, 400.0]
assert path_lengths(reverse_path(p + p[0:1])) == [0, 100.0, 200.0, 300.0, 400.0]

p = [ PathPoint(10, 0), PathArc(PathPoint(10, 0), PathPoint(0, 10), CandidateCircle(0, 0, 10), 10, 0, pi / 2), PathPoint(0, 0) ]
assert close_enough(path_length(p, True), 20 + lenquad10)
assert close_enough_tuple(path_lengths(p + p[0:1]), [0, lenquad10, lenquad10 + 10, lenquad10 + 20])
assert close_enough_tuple(path_lengths(reverse_path(p + p[0:1])), [0, 10.0, 20.0, 20.0 + lenquad10])

# closest_point

p = [ PathPoint(0, 0), PathPoint(100, 0), PathPoint(100, 100), PathPoint(0, 100) ]
assert close_enough_tuple(closest_point(p, True, PathPoint(50, -10)), (50, 10))
assert close_enough_tuple(closest_point(p, True, PathPoint(50, 10)), (50, 10))
assert close_enough_tuple(closest_point(p, True, PathPoint(-10, 50)), (350, 10))
assert close_enough_tuple(closest_point(p, True, PathPoint(10, 50)), (350, 10))
assert close_enough_tuple(closest_point(p, True, PathPoint(-10, -10)), (0, 10 * sqrt(2)))
assert close_enough_tuple(closest_point(p, True, PathPoint(110, -10)), (100, 10 * sqrt(2)))

p = [ PathPoint(10, 0), PathArc(PathPoint(10, 0), PathPoint(0, 10), CandidateCircle(0, 0, 10), 10, 0, pi / 2), PathPoint(0, 0) ]
assert close_enough_tuple(closest_point(p, True, PathPoint(20, 0)), (0, 10)) or close_enough_tuple(closest_point(p, True, PathPoint(20, 0)), (path_length(p, True), 10))
assert close_enough_tuple(closest_point(p, True, PathPoint(0, 20)), (2 * pi * 10 / 4, 10))
assert close_enough_tuple(closest_point(p, True, PathPoint(10 * sqrt(2) / 2, 10 * sqrt(2) / 2)), (2 * pi * 10 / 8, 0))
assert close_enough_tuple(closest_point(p, True, PathPoint(10, 10)), (2 * pi * 10 / 8, PathPoint(10, 10).dist(PathPoint(10 * sqrt(2) / 2, 10 * sqrt(2) / 2))))

# Tabs / cut

tabs = Tabs([Tab(16, 32)])

assert prepare(tabs.cut(0, 64, 64)) == [(0, 16), (32, 64)]

tabs = Tabs([Tab(8, 16), Tab(32, 40)])
assert prepare(tabs.cut(0, 64, 64)) == [(0, 8), (16, 32), (40, 64)]

path = [PathPoint(0, 0), PathPoint(10, 0), PathPoint(20, 0), PathPoint(20, 0), PathPoint(30, 0)]
assert path_length(path) == 30
assert calc_subpath(path, -5, 11) == [PathPoint(0, 0), PathPoint(10, 0), PathPoint(11, 0)]
assert calc_subpath(path, 0, 11) == [PathPoint(0, 0), PathPoint(10, 0), PathPoint(11, 0)]
assert calc_subpath(path, 11, 25) == [PathPoint(11, 0), PathPoint(20, 0), PathPoint(25, 0)]
assert calc_subpath(path, 25, 40) == [PathPoint(25, 0), PathPoint(30, 0)]

def check_near(v1, v2):
    return abs(v1 - v2) < 0.001

path = [PathPoint(50, 0), PathArc(PathPoint(50, 0), PathPoint(-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi)]

assert check_near(path_length(path + [PathPoint(-50, 0)]), pi * 50)
assert check_near(path_length(path + [PathPoint(-50, -50)]), pi * 50 + 50)

path = [PathPoint(50, 0), PathArc(PathPoint(50, 0), PathPoint(0, 50), CandidateCircle(0, 0, 50), 50, 0, pi / 2)]

assert check_near(path_length(path + [PathPoint(0, 50)]), pi * 25)
assert check_near(path_length([PathPoint(0, 0)] + path), pi * 25 + 50)
assert check_near(path_length([PathPoint(100, 0)] + path), pi * 25 + 50)
assert check_near(path_length([PathPoint(50, -50)] + path), pi * 25 + 50)

path = [PathPoint(50, 0), PathArc(PathPoint(50, 0), PathPoint(-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi), PathPoint(-50, 0)]
assert check_near(path_length(path), pi * 50)
assert check_near(path_length(reverse_path(path)), pi * 50)

path = [PathPoint(0, 0), PathPoint(50, 0), PathArc(PathPoint(50, 0), PathPoint(-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi), PathPoint(0, 0)]
assert check_near(path_length(path), pi * 50 + 100)
assert check_near(path_length(reverse_path(path)), pi * 50 + 100)

arc = PathArc(PathPoint(50, 0), PathPoint(-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi)
assert check_near(path_length(arc.cut(0, 0.5)), pi * 25)
assert check_near(path_length(arc.cut(0.5, 1)), pi * 25)
assert check_near(path_length(arc.cut(0.25, 0.75)), pi * 25)

# ---------------------------------------------------------------------

def verify_path_circles(path):
    def roundpt(pt):
        res = 1000
        return PathPoint(int(pt.x * res) / res, int(pt.y * res) / res)
    lastpt = None
    for item in path:
        if item.is_point():
            lastpt = item
        else:
            assert item.is_arc()
            arc = item
            assert arc.p1 == lastpt
            lastpt = arc.p2
            cc = roundpt(PathPoint(arc.c.cx, arc.c.cy))
            (arc.c.cx, arc.c.cy) = (cc.x, cc.y)
            startpt = roundpt(arc.p1)
            endpt = roundpt(arc.p2)
            sdist = arc.c.dist(startpt)
            edist = arc.c.dist(endpt)
            assert abs(sdist - edist) < 0.002

for i in range(1, 100):
    c = circle(0, 0, 0.3 * i, None, 0, 2 * pi / 3)
    c2 = CircleFitter.simplify(c)
    verify_path_circles(c2)
    assert len(c2) == 2

for i in range(10, 100):
    c = circle(0, 0, i)
    c2 = CircleFitter.simplify(c)
    verify_path_circles(c2)
    assert len(c2) == 4
