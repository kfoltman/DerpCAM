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
      # Minimum diameter of the helix during helical ramps. If 0, this will
      # essentially permit plunge cuts, and if it's too small, then chip
      # evacuation may be a problem. Picking half the diameter just because.
      self.min_helix_diameter = 0.5 * diameter
   @staticmethod
   def calc_vfeed(hfeed, degrees):
      return hfeed * tan(degrees * pi / 180)
   # Path slope for ramp/helical entry
   def slope(self):
      return max(1, int(self.hfeed / self.vfeed))
      
class Toolpath(object):
   def __init__(self, points, closed, tool, transform=None, helical_entry=None, bounds=None, is_tab=False):
      self.points = points
      self.closed = closed
      self.tool = tool
      self.transform = transform if not is_tab else None
      self.is_tab = is_tab
      self.transformed_cache = None
      self.lines_to_arcs_cache = None
      self.helical_entry = helical_entry
      # Allow borrowing bounds from the non-simplified shape to avoid calculating arc bounds
      self.bounds = self.calc_bounds() if bounds is None else bounds
      self.tlength = 0
      self.lengths = [0]
      for i in range(1, len(self.points)):
         self.tlength += dist(self.points[i - 1], self.points[i])
         self.lengths.append(self.tlength)
      if self.closed:
         self.tlength += dist(self.points[- 1], self.points[0])
         self.lengths.append(self.tlength)

   def transformed(self):
      if self.transform is None:
         return self
      if self.transformed_cache is None:
         self.transformed_cache = self.transform(self)
      return self.transformed_cache

   def calc_bounds(self):
      xcoords = [p[0] for p in self.points]
      ycoords = [p[1] for p in self.points]
      tr = 0.5 * self.tool.diameter
      return (min(xcoords) - tr, min(ycoords) - tr, max(xcoords) + tr, max(ycoords) + tr)

   def lines_to_arcs(self):
      if self.lines_to_arcs_cache is None:
         self.lines_to_arcs_cache = Toolpath(CircleFitter.simplify(self.points), self.closed, self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab)
      return self.lines_to_arcs_cache

   def subpath(self, start, end, is_tab=False):
      points = calc_subpath(self.points, start, end, self.closed)
      if points[0] == points[-1]:
         tp = Toolpath(points[:-1], True, self.tool, transform=self.transform, is_tab=is_tab)
      else:
         tp = Toolpath(points, False, self.tool, transform=self.transform, is_tab=is_tab)
      tp.helical_entry = None
      return tp

   def eliminate_tabs2(self, tabs):
      ptsc = self.points if not self.closed else self.points + [self.points[0]]
      tabs = sorted(tabs.tabs, key=lambda tab: tab.start)
      pos = 0
      res = []
      for tab in tabs:
         if pos < tab.start:
            res.append(self.subpath(pos, tab.start, is_tab=False))
         res.append(self.subpath(tab.start, tab.end, is_tab=True))
         # No transform on tabs, so that no time is wasted doing trochoidal
         # milling of empty space above the tab
         pos = tab.end
      if pos < self.tlength:
         res.append(self.subpath(pos, self.tlength, is_tab=False))
      return res
      
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

def findPathNesting(tps):
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
   return nestings

def fixPathNesting(tps):
   nestings = findPathNesting(tps)
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

def findHelicalEntryPoints(toolpaths, tool, boundary, islands):
   boundary_path = IntPath(boundary)
   boundary_path = boundary_path.force_orientation(False)
   for toolpath in toolpaths:
      if type(toolpath) is Toolpaths:
         findHelicalEntryPoints(toolpath.toolpaths)
         continue
      startx, starty = toolpath.points[0]
      # Size of the helical entry hole
      d = tool.diameter * (1 + tool.stepover)
      c = IntPath(circle(startx, starty, d / 2))
      # Check if it sticks outside of the final shape
      # XXXKF could be optimized by doing a simple bounds check first
      if run_clipper_simple(CT_DIFFERENCE, [c], [boundary_path], bool_only=True):
         continue
      # Check for collision with islands
      if islands and any([run_clipper_simple(CT_INTERSECTION, [IntPath(i)], [c], bool_only=True) for i in islands]):
         continue
      toolpath.helical_entry = (startx, starty, (d - tool.diameter) / 2)

def mergeToolpaths(tps, new, dia):
   if type(new) is Toolpath:
      new = [new]
   else:
      new = new.toolpaths
   if not tps:
      tps.append(Toolpaths(new))
      return
   last = tps[-1]
   new2 = []
   for i in new:
      pt = i.points[0]
      found = False
      for l in last.toolpaths:
         mindist = None
         mdpos = None
         for j, pt2 in enumerate(l.points):
            d = dist(pt, pt2)
            if mindist is None or d < mindist:
               mindist = d
               mdpos = j
         if mindist <= dia:
            l.points = l.points[:mdpos + 1] + i.points + i.points[0:1] + l.points[mdpos:]
            found = True
            break
      if not found:
         new2.append(i)
   if new2:
      tps.append(Toolpaths(new2))


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
            offset = Shape._offset(contour, closed, dist - int(dist / 2))
            if offset:
               res2 += offset
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
            d = Shape._difference(IntPath(i, True), *subtract, return_ints=True)
            if d:
               res2 += d
         if not res2:
            return None
         tps = [Toolpath(path.real_points(), self.closed, tool) for path in res2]
      else:
         tps = [Toolpath(PtsFromInts(path), self.closed, tool) for path in res]
      if len(tps) == 1:
         return tps[0]
      return Toolpaths(tps)
   def pocket_contour(self, tool):
      if not self.closed:
         raise ValueError("Cannot mill pockets of open polylines")
      tps = []
      tps_islands = []
      boundary = IntPath(self.boundary)
      islands_transformed = []
      islands = self.islands
      for island in islands:
         pc = PyclipperOffset()
         pts = PtsToInts(island)
         if not Orientation(pts):
            pts = list(reversed(pts))
         pc.AddPath(pts, JT_ROUND, ET_CLOSEDPOLYGON)
         res = pc.Execute(tool.diameter * 0.5 * RESOLUTION)
         if not res:
            return None
         res = [IntPath(it, True) for it in res]
         islands_transformed += res
      if islands_transformed:
         islands_transformed = Shape._union(*[i for i in islands_transformed], return_ints=True)
      for path in islands_transformed:
         for ints in Shape._intersection(path, boundary):
            # diff with other islands
            tps_islands += [Toolpath(ints, True, tool)]
      displace = 0.0
      stepover = tool.stepover * tool.diameter
      while True:
         res = self.contour(tool, False, displace, islands_transformed)
         if not res:
            break
         displace += stepover
         mergeToolpaths(tps, res, tool.diameter)
      if len(tps) == 0:
         raise ValueError("Empty contour")
      tps = joinClosePaths(tps_islands + list(reversed(tps)))
      if self.closed:
         findHelicalEntryPoints(tps, tool, self.boundary, self.islands)
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
   def _difference(*paths, return_ints=False):
      return run_clipper_simple(CT_DIFFERENCE, paths[0:1], paths[1:], return_ints=return_ints)
   # This works on lists of points
   @staticmethod
   def _intersection(*paths, return_ints=False):
      return run_clipper_simple(CT_INTERSECTION, paths[0:1], paths[1:], return_ints=return_ints)
   # This works on lists of points
   @staticmethod
   def _union(*paths, return_ints=False):
      return run_clipper_simple(CT_UNION, paths[0:1], paths[1:], return_ints=return_ints)

def interpolate_path(path):
   lastpt = path[0]
   res = [lastpt]
   for pt in path:
      d = maxaxisdist(lastpt, pt)
      subdiv = ceil(d * RESOLUTION + 1)
      for i in range(subdiv):
         if i > 0 and lastpt == pt:
            continue
         res.append(weighted(lastpt, pt, i / subdiv))
      lastpt = pt
   res.append(path[-1])
   return res

def trochoidal_transform(contour, nrad, nspeed):
   path = contour.points
   if contour.closed:
      path = path + [path[0]]
   path = interpolate_path(path)
   res = [path[0]]
   lastpt = path[0]
   t = 0
   for pt in path:
      x, y = pt
      d = dist(lastpt, pt)
      t += d
      x += nrad*cos(t * nspeed * 2 * pi)
      y += nrad*sin(t * nspeed * 2 * pi)
      res.append((x, y))
      lastpt = pt
   res.append(path[-1])
   if res and contour.closed:
      assert res[-1] == res[0]
      return Toolpath(points=res[:-1], closed=True, tool=contour.tool, helical_entry=(*path[0], nrad), is_tab=contour.is_tab)
   else:
      return Toolpath(points=res, closed=False, tool=contour.tool, helical_entry=(*path[0], nrad), is_tab=contour.is_tab)

