from process import *
from geom import *
from gcodegen import *

def prepare(ranges):
   res = []
   for s, e in ranges:
      res.append((int(s * 64), int(e * 64)))
   return res

tabs = Tabs([Tab(16, 32)])

assert prepare(tabs.cut(0, 64, 64)) == [(0, 16), (32, 64)]

tabs = Tabs([Tab(8, 16), Tab(32, 40)])
assert prepare(tabs.cut(0, 64, 64)) == [(0, 8), (16, 32), (40, 64)]

path = [(0, 0), (10, 0), (20, 0), (20, 0), (30, 0)]
assert path_length(path) == 30
assert calc_subpath(path, -5, 11) == [(0, 0), (10, 0), (11, 0)]
assert calc_subpath(path, 0, 11) == [(0, 0), (10, 0), (11, 0)]
assert calc_subpath(path, 11, 25) == [(11, 0), (20, 0), (25, 0)]
assert calc_subpath(path, 25, 40) == [(25, 0), (30, 0)]

def check_near(v1, v2):
   return abs(v1 - v2) < 0.001

path = [(50, 0), ("ARC_CCW", (50, 0), (-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi)]

assert check_near(path_length(path + [(-50, 0)]), pi * 50)
assert check_near(path_length(path + [(-50, -50)]), pi * 50 + 50)

path = [(50, 0), ("ARC_CCW", (50, 0), (0, 50), CandidateCircle(0, 0, 50), 50, 0, pi / 2)]

assert check_near(path_length(path + [(0, 50)]), pi * 25)
assert check_near(path_length([(0, 0)] + path), pi * 25 + 50)
assert check_near(path_length([(100, 0)] + path), pi * 25 + 50)
assert check_near(path_length([(50, -50)] + path), pi * 25 + 50)

path = [(50, 0), ("ARC_CCW", (50, 0), (-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi), (-50, 0)]
assert check_near(path_length(path), pi * 50)
assert check_near(path_length(reverse_path(path)), pi * 50)

path = [(0, 0), (50, 0), ("ARC_CCW", (50, 0), (-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi), (0, 0)]
assert check_near(path_length(path), pi * 50 + 100)
assert check_near(path_length(reverse_path(path)), pi * 50 + 100)

arc = ("ARC_CCW", (50, 0), (-50, 0), CandidateCircle(0, 0, 50), 100, 0, pi)
assert check_near(path_length(cut_arc(arc, 0, 0.5)), pi * 25)
assert check_near(path_length(cut_arc(arc, 0.5, 1)), pi * 25)
assert check_near(path_length(cut_arc(arc, 0.25, 0.75)), pi * 25)

# ---------------------------------------------------------------------

def verify_path_circles(path):
   def roundpt(pt):
      res = 1000
      return (int(pt[0] * res) / res, int(pt[1] * res) / res)
   lastpt = None
   for item in path:
      if len(item) == 2:
         lastpt = item
      else:
         arcdir, startpt, endpt, circ, res, sangle, sspan = item
         assert startpt == lastpt
         lastpt = endpt
         assert len(item) == 7
         (circ.cx, circ.cy) = roundpt((circ.cx, circ.cy))
         startpt = roundpt(startpt)
         endpt = roundpt(endpt)
         sdist = circ.dist(startpt)
         edist = circ.dist(endpt)
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
