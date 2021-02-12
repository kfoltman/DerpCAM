from pyclipper import *
from math import *

RESOLUTION = 25.0
fillMode = PFT_POSITIVE

def PtsToInts(points):
   return [(int(x * RESOLUTION), int(y * RESOLUTION)) for x, y in points]

def PtsFromInts(points):
   return [(x / RESOLUTION, y / RESOLUTION) for x, y in points]
   
def circle(x, y, r, n = None):
   if n is None:
      n = 3.0 * r * RESOLUTION
   n = ceil(n)
   res = []
   for i in range(n):
      a = i * 2 * pi / n
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
