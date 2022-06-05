import os
import sys
import unittest

sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from DerpCAM.common.geom import *
from DerpCAM.cam.toolpath import Tab, Tabs

def prepare(ranges):
    res = []
    for s, e in ranges:
        res.append((int(s * 64), int(e * 64)))
    return res

def close_enough(a, b, eps=0.001):
    return abs(a - b) < eps
def close_enough_tuple(a, b, eps=0.001):
    return all([close_enough(a[i], b[i], eps) for i in range(max(len(a), len(b)))])

class GeomTest(unittest.TestCase):
    def assertNear(self, v1, v2, places=3, msg=None):
        self.assertAlmostEqual(v1, v2, places=places, msg=msg)

    def assertCloseEnoughTuple(self, a, b, places=3):
        self.assertEqual(len(a), len(b))
        for i in range(len(a)):
            self.assertNear(a[i], b[i], msg=f"{i}", places=places)

    def testPathPoint(self):
        a = PathPoint(10, 0)
        b = PathPoint(20, 0)
        self.assertEqual(a, PathPoint(10, 0))
        self.assertNotEqual(a, PathPoint(20, 0))
        self.assertEqual(b, PathPoint(20, 0))
        self.assertNotEqual(b, PathPoint(10, 0))
        self.assertEqual(a.translated(10, 0), PathPoint(20, 0))
        self.assertEqual(a.translated(10, 10), PathPoint(20, 10))
        self.assertEqual(a.scaled(5, 0, 2), PathPoint(15, 0))
        self.assertEqual(a.scaled(0, 0, 2), PathPoint(20, 0))
        self.assertEqual(a.scaled(10, -10, 2), PathPoint(10, 10))
        self.assertEqual(a.dist(b), 10)
        self.assertEqual(a.dist(PathPoint(10, -20)), 20)

    def testPathArc(self):
        r = PathArc(PathPoint(10, 0), PathPoint(0, 10), CandidateCircle(0, 0, 10), 10, 0, pi / 2)
        r2 = r.reversed()
        self.assertEqual(r2.p1, r.p2)
        self.assertEqual(r2.p2, r.p1)
        self.assertEqual(r2.sstart, r.sspan)
        self.assertEqual(r2.sspan, -r.sspan)

        r3 = r.scaled(0, 0, 2)
        self.assertEqual(r3.p1, PathPoint(20, 0))
        self.assertEqual(r3.p2, PathPoint(0, 20))
        self.assertEqual(r3.c.cx, r.c.cx)
        self.assertEqual(r3.c.cy, r.c.cy)
        self.assertEqual(r3.c.r, r.c.r * 2)
        self.assertEqual(r3.sstart, r.sstart)
        self.assertEqual(r3.sspan, r.sspan)

        r4 = r.cut(0.25, 0.75)[1]
        self.assertLess(abs(r4.p1.x - 10 * cos(pi / 8)), 0.001)
        self.assertLess(abs(r4.p1.y - 10 * sin(pi / 8)), 0.001)
        self.assertLess(abs(r4.p2.x - 10 * cos(3 * pi / 8)), 0.001)
        self.assertLess(abs(r4.p2.y - 10 * sin(3 * pi / 8)), 0.001)
        self.assertLess(abs(r4.sstart - pi / 8), 0.001)
        self.assertLess(abs(r4.sspan - pi / 4), 0.001)

        r5 = r.scaled(5, 0, 2)
        self.assertEqual(r5.p1, PathPoint(15, 0))
        self.assertEqual(r5.p2, PathPoint(-5, 20))

        r6 = r.translated(10, 5)
        self.assertEqual(r6.p1, PathPoint(20, 5))
        self.assertEqual(r6.p2, PathPoint(10, 15))
        self.assertEqual(r6.c.centre(), PathPoint(10, 5))

        r = PathArc(PathPoint(0, 10), PathPoint(-10, 0), CandidateCircle(0, 0, 10), 10, pi / 2, pi / 2)
        r2 = PathArc.from_tuple(r.as_tuple())
        self.assertEqual(r.p1, r2.p1)
        self.assertEqual(r.p2, r2.p2)
        self.assertEqual(r.c.centre(), r2.c.centre())
        self.assertEqual(r.c.r, r2.c.r)
        self.assertEqual(r.steps, r2.steps)
        self.assertEqual(r.sstart, r2.sstart)
        self.assertEqual(r.sspan, r2.sspan)

        r4 = r.cut(0.25, 0.75)[1]
        self.assertLess(abs(r4.sstart - 5 * pi / 8), 0.001)
        self.assertLess(abs(r4.sspan - pi / 4), 0.001)

        for i in range(4):
            base = pi / 4 + i * pi / 2
            r = PathArc.xyra(0, 0, 10, base, pi / 6)
            self.assertEqual(r.quadrant_seps(), [])
            r = PathArc.xyra(0, 0, 10, base, pi / 2)
            self.assertEqual(r.quadrant_seps(), [r.c.at_angle((i + 1) * pi / 2)])
            r = PathArc.xyra(0, 0, 10, base, pi)
            self.assertEqual(r.quadrant_seps(), [r.c.at_angle((i + 1) * pi / 2), r.c.at_angle((i + 2) * pi / 2)])
            r = PathArc.xyra(0, 0, 10, base, 3 * pi / 2)
            self.assertEqual(r.quadrant_seps(), [r.c.at_angle((i + 1) * pi / 2), r.c.at_angle((i + 2) * pi / 2), r.c.at_angle((i + 3) * pi / 2)])
            r = PathArc.xyra(0, 0, 10, base, 2 * pi - pi / 8)
            self.assertEqual(r.quadrant_seps(), [r.c.at_angle((i + 1) * pi / 2), r.c.at_angle((i + 2) * pi / 2), r.c.at_angle((i + 3) * pi / 2), r.c.at_angle((i + 4) * pi / 2)])
            #
            r = PathArc.xyra(0, 0, 10, base, -pi / 6)
            self.assertEqual(r.quadrant_seps(), [])
            r = PathArc.xyra(0, 0, 10, base, -pi / 2)
            self.assertEqual(r.quadrant_seps(), [r.c.at_angle(i * pi / 2)])
            r = PathArc.xyra(0, 0, 10, base, -pi)
            self.assertEqual(r.quadrant_seps(), [r.c.at_angle((i - 1) * pi / 2), r.c.at_angle(i * pi / 2)])
            r = PathArc.xyra(0, 0, 10, base, -3 * pi / 2)
            self.assertEqual(r.quadrant_seps(), [r.c.at_angle((i - 2) * pi / 2), r.c.at_angle((i - 1) * pi / 2), r.c.at_angle(i * pi / 2)])
            r = PathArc.xyra(0, 0, 10, base, -(2 * pi - pi / 8))
            self.assertEqual(r.quadrant_seps(), [r.c.at_angle((i - 3) * pi / 2), r.c.at_angle((i - 2) * pi / 2), r.c.at_angle((i - 1) * pi / 2), r.c.at_angle(i * pi / 2)])

    def testPath(self):
        # point_at
        p = Path([ PathPoint(0, 0), PathPoint(100, 0), PathPoint(100, 100), PathPoint(0, 100) ], True)
        self.assertEqual(p.point_at(50), PathPoint(50, 0))
        self.assertEqual(p.point_at(150), PathPoint(100, 50))
        self.assertEqual(p.point_at(250), PathPoint(50, 100))
        self.assertEqual(p.point_at(350), PathPoint(0, 50))

        # length/lengths
        lenquad10 = 2 * pi * 10 / 4 # length of a quadrant of a circle of radius 10

        p = Path([ PathPoint(0, 0), PathPoint(100, 0), PathPoint(100, 100), PathPoint(0, 100) ], True)
        self.assertNear(p.length(), 400)
        self.assertEqual(p.lengths(), [0, 100.0, 200.0, 300.0, 400.0])
        self.assertEqual(p.reverse().lengths(), [0, 100.0, 200.0, 300.0, 400.0])

        p = Path([ PathPoint(10, 0), PathArc(PathPoint(10, 0), PathPoint(0, 10), CandidateCircle(0, 0, 10), 10, 0, pi / 2), PathPoint(0, 0) ], True)
        self.assertNear(p.length(), 20 + lenquad10)
        self.assertCloseEnoughTuple(p.lengths(), [0, lenquad10, lenquad10 + 10, lenquad10 + 20])
        # A bit of a quirk causing different number of items for forward vs reverse
        self.assertCloseEnoughTuple(p.reverse().lengths(), [0, 10.0, 20.0, 20.0 + lenquad10, 20 + lenquad10])

        path = [PathPoint(50, 0), PathArc(PathPoint(50, 0), PathPoint(-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi)]
        self.assertNear(Path(path + [PathPoint(-50, 0)], False).length(), pi * 50)
        self.assertNear(Path(path + [PathPoint(-50, -50)], False).length(), pi * 50 + 50)

        path = [PathPoint(50, 0), PathArc(PathPoint(50, 0), PathPoint(0, 50), CandidateCircle(0, 0, 50), 50, 0, pi / 2)]
        self.assertNear(Path(path + [PathPoint(0, 50)], False).length(), pi * 25)
        self.assertNear(Path([PathPoint(0, 0)] + path, False).length(), pi * 25 + 50)
        self.assertNear(Path([PathPoint(100, 0)] + path, False).length(), pi * 25 + 50)
        self.assertNear(Path([PathPoint(50, -50)] + path, False).length(), pi * 25 + 50)

        path = [PathPoint(50, 0), PathArc(PathPoint(50, 0), PathPoint(-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi), PathPoint(-50, 0)]
        self.assertNear(Path(path, False).length(), pi * 50)
        self.assertNear(Path(path, False).reverse().length(), pi * 50)

        path = [PathPoint(0, 0), PathPoint(50, 0), PathArc(PathPoint(50, 0), PathPoint(-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi), PathPoint(0, 0)]
        self.assertNear(Path(path, False).length(), pi * 50 + 100)
        self.assertNear(Path(path, False).reverse().length(), pi * 50 + 100)

        arc = PathArc(PathPoint(50, 0), PathPoint(-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi)
        self.assertNear(Path(arc.cut(0, 0.5), False).length(), pi * 25)
        self.assertNear(Path(arc.cut(0.5, 1), False).length(), pi * 25)
        self.assertNear(Path(arc.cut(0.25, 0.75), False).length(), pi * 25)

        arc = PathArc.xyra(100, 20, 20, pi / 4, pi / 2)
        b = Path([arc.p1, arc], False).bounds()
        self.assertNear(b[0], 100 + 20 * cos(pi / 4 + pi / 2))
        self.assertNear(b[1], 20 + 20 * sin(pi / 4))
        self.assertNear(b[2], 100 + 20 * cos(pi / 4))
        self.assertNear(b[3], 40)

        arc = PathArc.xyra(100, 20, 20, pi / 4 + pi, pi / 2)
        b = Path([arc.p1, arc], False).bounds()
        self.assertNear(b[0], 100 + 20 * cos(pi / 4 + pi / 2))
        self.assertNear(b[1], 0)
        self.assertNear(b[2], 100 + 20 * cos(pi / 4))
        self.assertNear(b[3], 20 - 20 * sin(pi / 4))

        arc = PathArc.xyra(100, 20, 20, pi / 4 + pi / 2, pi / 2)
        b = Path([arc.p1, arc], False).bounds()
        self.assertNear(b[0], 80)
        self.assertNear(b[1], 20 - 20 * cos(pi / 4))
        self.assertNear(b[2], 100 - 20 * sin(pi / 4))
        self.assertNear(b[3], 20 + 20 * cos(pi / 4))

        arc = PathArc.xyra(100, 20, 20, -pi / 4, pi / 2)
        b = Path([arc.p1, arc], False).bounds()
        self.assertNear(b[0], 100 + 20 * cos(pi / 4))
        self.assertNear(b[1], 20 - 20 * sin(pi / 4))
        self.assertNear(b[2], 120)
        self.assertNear(b[3], 20 + 20 * sin(pi / 4))

    def testClosestPoint(self):
        # closest_point
        p = Path([ PathPoint(0, 0), PathPoint(100, 0), PathPoint(100, 100), PathPoint(0, 100) ], True)
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(50, -10)), (50, 10))
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(50, 10)), (50, 10))
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(-10, 50)), (350, 10))
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(10, 50)), (350, 10))
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(-10, -10)), (0, 10 * sqrt(2)))
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(110, -10)), (100, 10 * sqrt(2)))

        p = Path([ PathPoint(10, 0), PathArc(PathPoint(10, 0), PathPoint(0, 10), CandidateCircle(0, 0, 10), 10, 0, pi / 2), PathPoint(0, 0) ], True)
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(20, 0)), (p.length(), 10))
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(0, 20)), (2 * pi * 10 / 4, 10))
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(10 * sqrt(2) / 2, 10 * sqrt(2) / 2)), (2 * pi * 10 / 8, 0))
        self.assertCloseEnoughTuple(p.closest_point(PathPoint(10, 10)), (2 * pi * 10 / 8, PathPoint(10, 10).dist(PathPoint(10 * sqrt(2) / 2, 10 * sqrt(2) / 2))))

    def testSubpath(self):
        path = Path([PathPoint(0, 0), PathPoint(10, 0), PathPoint(20, 0), PathPoint(20, 0), PathPoint(30, 0)], False)
        self.assertEqual(path.length(), 30)
        self.assertEqual(path.subpath(-5, 11), Path([PathPoint(0, 0), PathPoint(10, 0), PathPoint(11, 0)], False))
        self.assertEqual(path.subpath(0, 11), Path([PathPoint(0, 0), PathPoint(10, 0), PathPoint(11, 0)], False))
        self.assertEqual(path.subpath(11, 25), Path([PathPoint(11, 0), PathPoint(20, 0), PathPoint(25, 0)], False))
        self.assertEqual(path.subpath(25, 40), Path([PathPoint(25, 0), PathPoint(30, 0)], False))

class TabsTest(unittest.TestCase):
    def testCut(self):
        # Tabs / cut
        tabs = Tabs([Tab(16, 32)])
        self.assertEqual(prepare(tabs.cut(0, 64, 64)), [(0, 16), (32, 64)])

        tabs = Tabs([Tab(8, 16), Tab(32, 40)])
        self.assertEqual(prepare(tabs.cut(0, 64, 64)), [(0, 8), (16, 32), (40, 64)])

# ---------------------------------------------------------------------

res = 100
def roundpt(pt):
    return PathPoint(int(pt.x * res) / res, int(pt.y * res) / res)

class CircleTest(unittest.TestCase):
    def verify_path_circles(self, path):
        lastpt = None
        for item in path:
            if item.is_point():
                lastpt = item
            else:
                self.assertTrue(item.is_arc())
                arc = item
                self.assertEqual(arc.p1, lastpt)
                lastpt = arc.p2
                cc = roundpt(PathPoint(arc.c.cx, arc.c.cy))
                (arc.c.cx, arc.c.cy) = (cc.x, cc.y)
                startpt = roundpt(arc.p1)
                endpt = roundpt(arc.p2)
                sdist = arc.c.dist(startpt)
                edist = arc.c.dist(endpt)
                self.assertLess(abs(sdist - edist), 2 / res)

    def testSimplify(self):
        for i in range(1, 50):
            c = circle(0, 0, 0.3 * i, None, 0, 2 * pi / 3)
            c2 = CircleFitter.simplify(c)
            self.verify_path_circles(c2)
            self.assertEqual(len(c2), 2)

        for i in range(10, 50):
            c = circle(0, 0, i)
            c2 = CircleFitter.simplify(c)
            self.verify_path_circles(c2)
            self.assertEqual(len(c2), 4)

unittest.main()
