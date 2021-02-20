from process import *

# VERY experimental feature
simplify_arcs = True
debug_simplify_arcs = False
debug_ramp = False
debug_tabs = False

class OperationProps(object):
   def __init__(self, depth, start_depth = 0, tab_depth = None):
      self.depth = depth
      self.start_depth = start_depth
      self.tab_depth = tab_depth

class Gcode(object):
   def __init__(self):
      self.gcode = []
      self.last_feed = 0
   def add(self, line):
      self.gcode.append(line)
   def reset(self):
      self.add("G17 G21 G90 G40")
   def finish(self):
      self.add("M2")
   def feed(self, feed):
      if feed != self.last_feed:
         self.add("F%0.2f" % feed)
         self.last_feed = feed
   def rapid(self, x=None, y=None, z=None):
      self.add("G0" + self.enc_coords(x, y, z))
   def linear(self, x=None, y=None, z=None):
      self.add("G1" + self.enc_coords(x, y, z))
   def arc_cw(self, x=None, y=None, z=None, i=None, j=None, k=None):
      self.add("G2" + self.enc_coords_arc(x, y, z, i, j, k))
   def arc_ccw(self, x=None, y=None, z=None, i=None, j=None, k=None):
      self.add("G3" + self.enc_coords_arc(x, y, z, i, j, k))
   def arc(self, direction, x=None, y=None, z=None, i=None, j=None, k=None):
      (self.arc_ccw if direction > 0 else self.arc_cw)(x, y, z, i, j, k)
   def enc_coords(self, x=None, y=None, z=None):
      res = ""
      if x is not None:
         res += (" X%0.3f" % x)
      if y is not None:
         res += (" Y%0.3f" % y)
      if z is not None:
         res += (" Z%0.3f" % z)
      return res
   def enc_coords_arc(self, x=None, y=None, z=None, i=None, j=None, k=None):
      res = self.enc_coords(x, y, z)
      if i is not None:
         res += (" I%0.3f" % i)
      if j is not None:
         res += (" J%0.3f" % j)
      if k is not None:
         res += (" K%0.3f" % k)
      return res
   def helix_turn(self, x, y, r, start_z, end_z):
      self.linear(x = x + r, y = y)
      cur_z = start_z
      delta_z = end_z - start_z
      # self.arc_cw(x = x, y = y - r, i = -r, z = cur_z + 0.25 * delta_z)
      # self.arc_cw(x = x - r, y = y, j = r, z = cur_z + 0.5 * delta_z)
      # self.arc_cw(x = x, y = y + r, i = r, z = cur_z + 0.75 * delta_z)
      # self.arc_cw(x = x + r, y = y, j = -r, z = cur_z + delta_z)
      self.arc_cw(x = x - r, y = y, i = -r, z = cur_z + 0.5 * delta_z)
      self.arc_cw(x = x + r, y = y, i = r, z = cur_z + delta_z)
      
   def move_z(self, new_z, old_z, tool, semi_safe_z):
      if new_z == old_z:
         return
      if new_z < old_z:
         self.feed(tool.vfeed)
         if old_z > semi_safe_z:
            self.rapid(z=semi_safe_z)
            old_z = 1
         self.linear(z=new_z)
         self.feed(tool.hfeed)
      else:
         self.rapid(z=new_z)
   def ramped_move_z(self, new_z, old_z, subpath, slope, semi_safe_z):
      if new_z >= old_z:
         self.rapid(z=new_z)
         return
      # XXXKF hack: don't bother ramping above Z=1
      if old_z > semi_safe_z:
         self.rapid(z=semi_safe_z)
         old_z = 1
      # Always positive
      z_diff = old_z - new_z
      xy_diff = z_diff * slope
      tlengths = path_lengths(subpath)
      npasses = xy_diff / tlengths[-1]
      if debug_ramp:
         self.add("(Ramp from %0.2f to %0.2f segment length %0.2f xydiff %0.2f passes %d)" % (old_z, new_z, tlengths[-1], xy_diff, npasses))
      self.linear(x=subpath[0][0], y=subpath[0][1])
      per_level = tlengths[-1] / slope
      for i in range(ceil(npasses)):
         if i == floor(npasses):
            # Last pass, do a shorter one
            newlength = (npasses - floor(npasses)) * tlengths[-1]
            if debug_ramp:
               self.add("(Last pass, shortening to %d)" % newlength)
            subpath = calc_subpath(subpath, 0, newlength)
            tlengths = path_lengths(subpath)
         pass_z = max(new_z, old_z - i * per_level)
         if debug_ramp:
            self.add("(Pass %d base level %0.2f min %0.2f)" % (i, pass_z, pass_z - tlengths[-1] / slope))
         for j in range(1, len(subpath)):
            self.linear(x=subpath[j][0], y=subpath[j][1], z=max(new_z, pass_z - tlengths[j] / slope))
         #self.add("Pass %d reverse" % i)
         for j in range(len(subpath) - 2, -1, -1):
            self.linear(x=subpath[j][0], y=subpath[j][1])

def pathToGcode(gcode, path, safe_z, semi_safe_z, start_depth, end_depth, doc, tabs, tab_depth):
   paths = path.flattened() if isinstance(path, Toolpaths) else [path]
   prev_depth = start_depth
   depth = max(start_depth - doc, end_depth)
   curz = safe_z
   lastpt = None
   slope = max(1, int(path.tool.hfeed / path.tool.vfeed))
   while True:
      for p in paths:
         if depth < tab_depth:
            subpaths = p.eliminate_tabs2(tabs)
         else:
            #subpaths = p.eliminate_tabs2(Tabs([]))
            subpaths = [(False, p.points + ([p.points[0]] if p.closed else []))]
         # Not a continuous path, need to jump to a new place
         firstpt = subpaths[0][1][0]
         if lastpt is None or dist(lastpt, firstpt) > 1 / RESOLUTION:
            gcode.rapid(z=safe_z)
            curz = safe_z
            gcode.rapid(x=firstpt[0], y=firstpt[1])
            lastpt = firstpt
         for is_tab, subpath in subpaths:
            newz = tab_depth if is_tab else depth
            if is_tab and debug_tabs:
               gcode.add("(tab start)")
            if newz != curz:
               if newz < curz:
                  if not is_tab and prev_depth < curz:
                     gcode.move_z(prev_depth, curz, p.tool, semi_safe_z)
                     curz = prev_depth
                  gcode.feed(p.tool.hfeed)
                  # XXXKF add support for arc finding
                  gcode.ramped_move_z(newz, curz, subpath, slope, semi_safe_z)
               else:
                  gcode.move_z(newz, curz, p.tool, semi_safe_z)
               curz = newz
            # First point was either equal to the most recent one, or
            # was reached using a rapid move, so omit it here.
            assert dist(lastpt, subpath[0]) < 1 / RESOLUTION
            subpath2 = CircleFitter.simplify(subpath) if simplify_arcs else subpath
            for pt in subpath2:
               if len(pt) > 2:
                  # Arc
                  tag, spt, ept, cdist, c, steps, direction = pt
                  gcode.linear(x=spt[0], y=spt[1])
                  gcode.arc(direction, x=ept[0], y=ept[1], i=cdist[0], j=cdist[1])
                  lastpt = ept
               else:
                  gcode.linear(x=pt[0], y=pt[1])
                  lastpt = pt
            if is_tab and debug_tabs:
               gcode.add("(tab end)")
      if depth == end_depth:
         break
      prev_depth = depth
      depth = max(depth - doc, end_depth)
   gcode.rapid(z=safe_z)
   return gcode

class Operation(object):
   def __init__(self, shape, tool, paths, props, tabs=None):
      self.shape = shape
      self.tool = tool
      self.paths = paths
      self.props = props
      self.flattened = paths.flattened()
      if tabs:
         assert len(self.flattened) == 1
         self.tabs = self.flattened[0].autotabs(tabs)
      else:
         self.tabs = Tabs([])
   def to_gcode(self, gcode, safe_z, semi_safe_z):
      tab_depth = self.props.tab_depth
      if tab_depth is None:
         tab_depth = self.props.depth
      for path in self.flattened:
         pathToGcode(gcode, path=path, safe_z=safe_z, semi_safe_z=semi_safe_z,
            start_depth=self.props.start_depth, end_depth=self.props.depth,
            doc=self.tool.maxdoc, tabs=self.tabs, tab_depth=tab_depth)

class HelicalDrill(Operation):
   def __init__(self, x, y, d, tool, props):
      shape = Shape.circle(x, y, r=0.5*d)
      Operation.__init__(self, shape, tool, shape.pocket_contour(tool), props)
      self.x = x
      self.y = y
      self.d = d

   def to_gcode(self, gcode, safe_z, semi_safe_z):
      if self.d < 2 * self.tool.diameter * self.tool.stepover:
         self.to_gcode_ring(gcode, safe_z, self.d, semi_safe_z)
      else:
         d = 2 * self.tool.diameter * self.tool.stepover
         while d < self.d:
            self.to_gcode_ring(gcode, safe_z, d, semi_safe_z)
            d += self.tool.diameter * self.tool.stepover
         self.to_gcode_ring(gcode, safe_z, self.d, semi_safe_z)
      gcode.rapid(z=safe_z)
         
   def to_gcode_ring(self, gcode, safe_z, d, semi_safe_z):
      r = max(0, (d - self.tool.diameter) / 2)
      gcode.rapid(z=safe_z)
      gcode.rapid(x=self.x + r, y=self.y)
      curz = semi_safe_z
      gcode.rapid(z=semi_safe_z)
      gcode.feed(self.tool.hfeed)
      while curz > self.props.depth:
         nextz = max(curz - self.tool.maxdoc, self.props.depth)
         gcode.helix_turn(self.x, self.y, r, curz, nextz)
         curz = nextz
      gcode.helix_turn(self.x, self.y, r, curz, curz)

# First make a helical entry and then enlarge to the target diameter
# by side milling
class HelicalDrill2(HelicalDrill):
   def to_gcode(self, gcode, safe_z, semi_safe_z):
      if self.d < 2 * self.tool.diameter * self.tool.stepover:
         self.to_gcode_ring(gcode, safe_z, self.d, semi_safe_z)
      else:
         d = 2 * self.tool.diameter * self.tool.stepover
         self.to_gcode_ring(gcode, safe_z, d, semi_safe_z)
         while d < self.d:
            r = max(0, (d - self.tool.diameter) / 2)
            gcode.linear(x=self.x + r, y=self.y)
            gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth)
            d += self.tool.diameter * self.tool.stepover
         r = max(0, (self.d - self.tool.diameter) / 2)
         gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth)
      gcode.rapid(z=safe_z)
         

def gcodeFromOperations(operations, safe_z, semi_safe_z):
   gcode = Gcode()
   gcode.reset()
   gcode.rapid(z=safe_z)
   gcode.rapid(x=0, y=0)
   for operation in operations:
      operation.to_gcode(gcode, safe_z, semi_safe_z)
   gcode.rapid(x=0, y=0)
   gcode.finish()
   return gcode
