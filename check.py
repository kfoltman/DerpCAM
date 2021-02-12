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

