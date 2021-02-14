from pyclipper import *
from math import *
from geom import *

class Tab(object):
   def __init__(self, start, end):
      self.start = start
      self.end = end
   def cut(self, slen, elen, tlen):
      if slen >= self.end or elen <= self.start:
         return True
      if slen >= self.start and elen <= self.end:
         return False
      segs = []
      if slen < self.start:
         segs.append((slen, self.start))
      if elen >= self.end:
         segs.append((self.end, elen))
      return segs
   

class Tabs(object):
   def __init__(self, tabs):
      self.tabs = tabs
   def cut(self, slen, elen, tlen):
      result = [(slen, elen)]
      for tab in self.tabs:
         nextres = []
         for slen2, elen2 in result:
            res = tab.cut(slen2, elen2, tlen)
            if res is True:
               nextres.append((slen2, elen2))
            elif res is False:
               pass # Segment removed entirely
            else:
               nextres += res
         result = nextres
         if not result:
            return False
      # Convert to relative
      if result == [(slen, elen)]:
         return True
      fres = []
      l = elen - slen
      for s, e in result:
         fres.append(((s - slen) / l, (e - slen) / l))
      return fres

class Tool(object):
   def __init__(self, diameter, hfeed, vfeed, maxdoc, stepover = 0.6):
      self.diameter = diameter
      self.hfeed = hfeed
      self.vfeed = vfeed
      self.maxdoc = maxdoc
      self.stepover = stepover
      
class Toolpath(object):
   def __init__(self, points, closed, tool):
      self.points = points
      self.closed = closed
      self.tool = tool
      self.bounds = self.calc_bounds()
      self.tlength = 0
      self.lengths = [0]
      for i in range(1, len(self.points)):
         self.tlength += dist(self.points[i - 1], self.points[i])
         self.lengths.append(self.tlength)
      if self.closed:
         self.tlength += dist(self.points[- 1], self.points[0])
         self.lengths.append(self.tlength)
         
   def calc_bounds(self):
      xcoords = [p[0] for p in self.points]
      ycoords = [p[1] for p in self.points]
      tr = 0.5 * self.tool.diameter
      return (min(xcoords) - tr, min(ycoords) - tr, max(xcoords) + tr, max(ycoords) + tr)

   def eliminate_tabs2(self, tabs):
      ptsc = self.points if not self.closed else self.points + [self.points[0]]
      tabs = sorted(tabs.tabs, key=lambda tab: tab.start)
      pos = 0
      res = []
      for tab in tabs:
         if pos < tab.start:
            res.append((False, calc_subpath(ptsc, pos, tab.start)))
         res.append((True, calc_subpath(ptsc, tab.start, tab.end)))
         pos = tab.end
      if pos < self.tlength:
         res.append((False, calc_subpath(ptsc, pos, self.tlength)))
      return res
      
   def eliminate_tabs(self, tabs):
      points = [self.points[0]]
      flags = []
      cur_segment = None
      ptsc = self.points if not self.closed else self.points + [self.points[0]]
      for i in range(1, len(ptsc)):
         res = tabs.cut(self.lengths[i - 1], self.lengths[i], self.tlength)
         p1, p2 = ptsc[i - 1], ptsc[i]
         if res is True:
            points.append(p2)
            flags.append(True)
         elif res is False:
            points.append(p2)
            flags.append(False)
         else: # list of (s, e)
            for s, e in res:
               if s == 0:
                  points.append(weighted(p1, p2, e))
                  flags.append(True)
               else:
                  points.append(weighted(p1, p2, s))
                  flags.append(False)
                  points.append(weighted(p1, p2, e))
                  flags.append(True)
      return points, flags

   def flattened(self):
      return [self]

   def autotabs(self, ntabs, offset=0, width=1):
      tablist = []
      pos = offset
      for i in range(ntabs):
         tablist.append(Tab(pos, pos + self.tool.diameter + width * self.tool.diameter))
         pos += self.tlength / ntabs
      return Tabs(tablist)

class Toolpaths(object):
   def __init__(self, toolpaths):
      self.toolpaths = toolpaths
      self.bounds = self.calc_bounds()
   def flattened(self):
      res = []
      for path in self.toolpaths:
         if isinstance(path, Toolpaths):
            res += path.flattened()
         else:
            res.append(path)
      return res
   def calc_bounds(self):
      return max_bounds(*[tp.bounds for tp in self.toolpaths])

def joinClosePaths(tps):
   last = None
   res = []
   for tp in tps:
      if isinstance(tp, Toolpaths):
         res.append(tp)
         last = None
         continue
      if last is not None and last.tool is tp.tool:
         points = tp.points
         if tp.closed:
            maxdist = None
            closest = 0
            for i, pt in enumerate(points):
               if i == 0 or dist(lastpt, pt) < maxdist:
                  closest = i
                  maxdist = dist(lastpt, pt)
            if closest > 0:
               points = points[closest:] + points[:closest]
         if dist(lastpt, points[0]) <= tp.tool.diameter:
            res[-1] = Toolpath(last.points + (last.points[0:1] if last.closed else []) + points + (points[0:1] if tp.closed else []), False, tp.tool)
            last = res[-1]
            lastpt = last.points[-1]
            continue
      res.append(tp)
      lastpt = tp.points[0 if tp.closed else -1]
      last = tp
   return res

class Shape(object):
   def __init__(self, boundary, closed=True, islands=None):
      self.boundary = boundary
      self.closed = closed
      self.islands = islands or []
      self.bounds = self.calc_bounds()
   def calc_bounds(self):
      xcoords = [p[0] for p in self.boundary]
      ycoords = [p[1] for p in self.boundary]
      return (min(xcoords), min(ycoords), max(xcoords), max(ycoords))
   def contour(self, tool, outside = True, displace = 0):
      dist = (0.5 * tool.diameter + displace) * RESOLUTION
      boundary = PtsToInts(self.boundary)
      pc = PyclipperOffset()
      pc.AddPath(boundary, JT_ROUND, ET_CLOSEDPOLYGON if self.closed else ET_OPENPOLYGON)
      res = pc.Execute(dist if outside else -dist)
      if not res:
         return None
      tps = [Toolpath(PtsFromInts(path), self.closed, tool) for path in res]
      if len(tps) == 1:
         return tps[0]
      return Toolpaths(tps)
   def pocket_contour(self, tool):
      tps = []
      displace = 0.0
      stepover = tool.stepover * tool.diameter
      while True:
         res = self.contour(tool, False, displace)
         if not res:
            break
         displace += stepover
         tps.append(res)
      tps = joinClosePaths(list(reversed(tps)))
      return Toolpaths(tps)
   @staticmethod
   def circle(x, y, r = None, d = None, n = None):
      return Shape(circle(x, y, r if r else 0.5 * d, n), True, None)
   @staticmethod
   def rectangle(sx, sy, ex, ey):
      polygon = [(sx, sy), (ex, sy), (ex, ey), (sx, ey)]
      #polygon = list(reversed(polygon))
      return Shape(polygon, True, None)
   @staticmethod
   def union(*paths):
      pc = Pyclipper()
      for path in paths:
         pc.AddPath(PtsToInts(path.boundary), PT_SUBJECT if path is paths[0] else PT_CLIP, path.closed)
      res = pc.Execute(CT_UNION, fillMode, fillMode)
      if not res:
         return []
      if len(res) == 1:
         return Shape(PtsFromInts(res[0]))
      return [Shape(PtsFromInts(i)) for i in res]

