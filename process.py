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
   def __init__(self, diameter, hfeed, vfeed, maxdoc, stepover=0.5, stepover_fulldepth=0.1):
      self.diameter = diameter
      self.hfeed = hfeed
      self.vfeed = vfeed
      self.maxdoc = maxdoc
      self.stepover = stepover
      self.stepover_fulldepth = stepover_fulldepth
      
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
      self.flattened_cache = self.calc_flattened()
   def flattened(self):
      return self.flattened_cache
   def calc_flattened(self):
      res = []
      for path in self.toolpaths:
         if isinstance(path, Toolpaths):
            res += path.flattened()
         else:
            res.append(path)
      return res
   def calc_bounds(self):
      return max_bounds(*[tp.bounds for tp in self.toolpaths])

def fixPathNesting(tps):
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
   res = []
   nestings = sorted(nestings, key=len)
   for nesting in nestings:
      res += nesting
   return res

def joinClosePaths(tps):
   tps = fixPathNesting(tps)
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
   def engrave(self, tool):
      tps = [Toolpath(self.boundary, self.closed, tool)] + [
         Toolpath(island, True, tool) for island in self.islands ]
      if len(tps) == 1:
         return tps[0]
      return Toolpaths(tps)
   @staticmethod
   def _offset(points, closed, dist):
      if abs(dist) > 10 * RESOLUTION:
         res = Shape._offset(points, closed, int(dist / 2))
         if not res:
            return
         res2 = []
         for contour in res:
            res2 += Shape._offset(contour, closed, dist - int(dist / 2))
         return res2
      pc = PyclipperOffset()
      pc.AddPath(points, JT_ROUND, ET_CLOSEDPOLYGON if closed else ET_OPENROUND)
      return pc.Execute(dist)
   def contour(self, tool, outside=True, displace=0, subtract=None):
      dist = (0.5 * tool.diameter + displace) * RESOLUTION
      boundary = PtsToInts(self.boundary)
      res = Shape._offset(boundary, self.closed, dist if outside else -dist)
      if not res:
         return None

      if subtract:
         res2 = []
         for i in res:
            d = Shape._difference(i, *subtract)
            if d:
               res2 += d
         if not res2:
            return None
         res = res2
      tps = [Toolpath(PtsFromInts(path), self.closed, tool) for path in res]
      if len(tps) == 1:
         return tps[0]
      return Toolpaths(tps)
   def pocket_contour(self, tool):
      tps = []
      islands_transformed = []
      for island in self.islands:
         pc = PyclipperOffset()
         pc.AddPath(PtsToInts(island), JT_ROUND, ET_CLOSEDPOLYGON)
         res = pc.Execute(tool.diameter * 0.5 * RESOLUTION)
         if not res:
            return None
         islands_transformed += res
         for path in res:
            for ints in Shape._intersection(path, self.boundary):
               tps += [Toolpath(ints, self.closed, tool)]
      displace = 0.0
      stepover = tool.stepover * tool.diameter
      while True:
         res = self.contour(tool, False, displace, islands_transformed)
         if not res:
            break
         displace += stepover
         tps.append(res)
      if len(tps) == 0:
         raise ValueError("Empty contour")
      tps = joinClosePaths(list(reversed(tps)))
      return Toolpaths(tps)
   def warp(self, transform):
      def interpolate(pts):
         res = []
         for i, p1 in enumerate(pts):
            p2 = pts[(i + 1) % len(pts)]
            segs = max(1, floor(dist(p1, p2)))
            for i in range(segs):
               res.append(weighted(p1, p2, i / segs))
         return res
      return Shape([transform(p[0], p[1]) for p in interpolate(self.boundary)], self.closed,
         [[transform(p[0], p[1]) for p in interpolate(island)] for island in self.islands])
   @staticmethod
   def _rotate_points(points, angle, x=0, y=0):
      def rotate(x, y, cosv, sinv, sx, sy):
         x -= sx
         y -= sy
         return sx + x * cosv - y * sinv, sy + x * sinv + y * cosv
      return [rotate(p[0], p[1], cos(angle), sin(angle), x, y) for p in points]
   def rotated(self, angle, x, y):
      return Shape(self._rotate_points(self.boundary, angle, x, y), self.closed, [self._rotate_points(island, angle, x, y) for island in self.islands])
   @staticmethod
   def _scale_points(points, mx, my=None, sx=0, sy=0):
      if my is None:
         my = mx
      return [(sx + (x - sx) * mx, sy + (y - sy) * my) for x, y in points]
   def scaled(self, mx, my=None, sx=0, sy=0):
      return Shape(self._scale_points(self.boundary, mx, my, sx, sy), self.closed, [self._scale_points(island, mx, my, sx, sy) for island in self.islands])
   @staticmethod
   def _translate_points(points, dx, dy):
      return [(p[0] + dx, p[1] + dy) for p in points]
   def translated(self, dx, dy):
      return Shape(self._translate_points(self.boundary, dx, dy), self.closed, [self._translate_points(island, dx, dy) for island in self.islands])
   @staticmethod
   def circle(x, y, r=None, d=None, n=None, sa=0, ea=2 * pi):
      return Shape(circle(x, y, r if r else 0.5 * d, n, sa, ea), True, None)
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
   # This works on lists of points
   @staticmethod
   def _difference(*paths):
      pc = Pyclipper()
      for path in paths:
         pc.AddPath(PtsToInts(path), PT_SUBJECT if path is paths[0] else PT_CLIP, True)
      res = pc.Execute(CT_DIFFERENCE, fillMode, fillMode)
      if not res:
         return []
      return [PtsFromInts(i) for i in res]
   # This works on lists of points
   @staticmethod
   def _intersection(*paths):
      pc = Pyclipper()
      for path in paths:
         pc.AddPath(PtsToInts(path), PT_SUBJECT if path is paths[0] else PT_CLIP, True)
      res = pc.Execute(CT_INTERSECTION, fillMode, fillMode)
      if not res:
         return []
      return [PtsFromInts(i) for i in res]

