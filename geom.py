from pyclipper import *
from math import *

RESOLUTION = 25.0
fillMode = PFT_POSITIVE

def PtsToInts(points):
   return [(round(x * RESOLUTION), round(y * RESOLUTION)) for x, y in points]

def PtsFromInts(points):
   return [(x / RESOLUTION, y / RESOLUTION) for x, y in points]
   
def circle(x, y, r, n=None, sa=0, ea=2*pi):
   if n is None:
      n = pi * r * RESOLUTION
   n *= (ea - sa) / (2 * pi)
   n = ceil(n)
   res = []
   for i in range(n + 1):
      a = sa + i * (ea - sa) / n
      newpt = (x + r * cos(a), y + r * sin(a))
      if not res or newpt != res[-1]:
         res.append(newpt)
   return res

def dist(a, b):
   dx = b[0] - a[0]
   dy = b[1] - a[1]
   return sqrt(dx * dx + dy * dy)

def weighted(p1, p2, alpha):
   return p1[0] + (p2[0] - p1[0]) * alpha, p1[1] + (p2[1] - p1[1]) * alpha

def SameOrientation(path, expected):
   return path if Orientation(path) == expected else ReversePath(path)

# Is b1 inside or overlapping b2?
def inside_bounds(b1, b2):
   sx1, sy1, ex1, ey1 = b1
   sx2, sy2, ex2, ey2 = b2
   return sx1 >= sx2 and ex1 <= ex2 and sy1 >= sy2 and ey1 <= ey2

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
   return sum([dist(path[i], path[i + 1]) for i in range(len(path) - 1)])

def path_lengths(path):
   res = [0]
   lval = 0
   for i in range(len(path) - 1):
      lval += dist(path[i], path[i + 1])
      res.append(lval)
   return res   

def calc_subpath(path, start, end):
   res = []
   tlen = 0
   next = None
   i = 0
   # Omit all segments before start
   while i < len(path) - 1:
      p1 = path[i]
      p2 = path[i + 1]
      d = dist(p1, p2)
      if tlen + d > start:
         break
      tlen += d
      i += 1
   if i >= len(path) - 1:
      return []
   if start > tlen:
      # Start is within the first non-omitted segment
      while i < len(path) - 1 and tlen < end:
         p1 = path[i]
         p2 = path[i + 1]
         d = dist(p1, p2)
         if d > 0:
            break
         i += 1
      res.append(weighted(p1, p2, (start - tlen) / d))
      # Perhaps the end is also within the same segment?
      if end <= tlen + d:
         res.append(weighted(p1, p2, (end - tlen) / d))
         return res
   else:
      # The start of the first segment is the start of the output
      if tlen < end:
         res.append(path[i])
   while i < len(path) - 1 and tlen < end:
      p1 = path[i]
      p2 = path[i + 1]
      d = dist(p1, p2)
      if d == 0:
         i += 1
         continue
      if tlen > end:
         break
      if tlen + d >= end:
         res.append(weighted(p1, p2, (end - tlen) / d))
         return res
      else:
         res.append(p2)
      tlen += d
      i += 1
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
   error_threshold = 2.5 / RESOLUTION
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
         pts_out.append(("ARC_CCW" if adir > 0 else "ARC_CW", c.snap(pts[start]), c.snap(pts[end - 1]), (c.cx - pts[start][0], c.cy - pts[start][1]), c, end - start, 1 if adir > 0 else -1))
         last = end
      pts_out += pts[last:]
      return pts_out

   # Old fitter:
   # Fit a circle based on 3 specified points, return match data
   @staticmethod
   def try_fit_circle_old(pts, p1, p2, p3):
      cir = CandidateCircle.from_3(p1, p2, p3)
      if cir is None:
         return
      maxerror = 0
      rmserror = 0
      pangles, nangles = cir.count_angles(pts)
      for p in pts:
         error = abs(cir.dist(p) - cir.r)
         maxerror = max(error, maxerror)
         rmserror += error * error
      rmserror = sqrt(rmserror / len(pts))
      return cir, pangles, nangles, maxerror, rmserror

   # Old fitter:
   # Find runs of short segments that look like they might be quantized arcs.
   # Break a run when a longer segment occurs or when there's a change of a
   # direction in X or Y.
   @staticmethod
   def find_runs_old(pts):
      def sign(value):
         return (1 if value > 0 else -1) if value else 0
      def delta(p1, p2):
         return (p2[1] - p1[1], p2[0] - p1[0])
      deltas = [delta(p1, pts[(i + 1) % len(pts)]) for i, p1 in enumerate(pts)]
      ranges = []
      run_start = None
      # This threshold is dependent on how we subdivide the circles
      threshold = 1 ** 2
      min_count = 4
      for i, delta in enumerate(deltas):
         d2 = delta[0] ** 2 + delta[1] ** 2
         if run_start is None:
            if d2 <= threshold:
               run_start = i
         else:
            if d2 > threshold:
               #print ("At ", i, "too long", sqrt(d2), sqrt(threshold))
               # Too long a segment, so it's not part of a quantized arc
               if i - run_start > min_count:
                  # Don't bother with short ranges
                  ranges.append((run_start, i))
               run_start = None
      if run_start is not None and len(pts) - run_start > min_count:
         ranges.append((run_start, len(pts)))
      return ranges

   @staticmethod
   def simplify_old(pts):
      ranges = CircleFitter.find_runs_old(pts)
      last = 0
      pts2 = []
      #print ("Ranges:", ranges)
      errthr = 2.0 / RESOLUTION
      for start, end in ranges:
         if last > end:
            continue
         if last > start:
            start = last
         pts2 += pts[last:start]

         res = (end > start + 2) and CircleFitter.try_fit_circle(pts[start:end], pts[start], pts[(start + end) // 2], pts[end - 1])
         #res = (end > start + 2) and CircleFitter.try_fit_circle(pts[start:end], pts[start], pts[start + 1], pts[end - 1])
         if res:
            c, pangles, nangles, maxerror, rmserror = res
            cx, cy, radius = c.cx, c.cy, c.r
            if maxerror < errthr:
               p1 = pts[start]
               p2 = pts[end - 1]
               if pangles:
                  pts2.append(("ARC_CCW", p1, p2, (cx - p1[0], cy - p1[1]), c, end - start, 1))
               else:
                  pts2.append(("ARC_CW", p1, p2, (cx - p1[0], cy - p1[1]), c, end - start, -1))
            else:
               print ("Max error too large", maxerror, errthr, rmserror)
               pts2 += pts[start:end]
         last = end
      pts2 += pts[last:]
      return pts2

   @staticmethod
   def interpolate_arcs(points, debug, scaling_factor):
      pts = []
      for p in points:
         if type(p[0]) is str:
            tag, p1, p2, dc, c, steps, sdir = p
            sangle = c.angle(p1)
            eangle = c.angle(p2)

            if not debug:
               steps *= ceil(min(4, max(1, scaling_factor)))
            else:
               steps = 3

            if sdir == 1 and eangle < sangle:
               eangle += 2 * pi
            if sdir == -1 and eangle > sangle:
               eangle -= 2 * pi
            step = (eangle - sangle) / steps
            for i in range(1 + steps):
               pts.append(c.at_angle(sangle + step * i))

            pts.append((p[2][0], p[2][1]))
         else:
            pts.append((p[0], p[1]))
      return pts
