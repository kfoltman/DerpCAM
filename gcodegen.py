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
      if False: # generate 4 quadrants for a circle - seems unnecessary
         self.arc_cw(x = x, y = y - r, i = -r, z = cur_z + 0.25 * delta_z)
         self.arc_cw(x = x - r, y = y, j = r, z = cur_z + 0.5 * delta_z)
         self.arc_cw(x = x, y = y + r, i = r, z = cur_z + 0.75 * delta_z)
         self.arc_cw(x = x + r, y = y, j = -r, z = cur_z + delta_z)
      else:
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

   def apply_subpath(self, subpath, lastpt, new_z=None, old_z=None, tlength=None):
      assert dist(lastpt, subpath[0]) < 1 / RESOLUTION
      tdist = 0
      for pt in subpath[1:]:
         if len(pt) > 2:
            # Arc
            tag, spt, ept, c, steps, sangle, sspan = pt
            cdist = (c.cx - spt[0], c.cy - spt[1])
            assert dist(lastpt, spt) < 1 / RESOLUTION
            tdist += arc_length(pt)
            if new_z is not None:
               self.arc(1 if sspan > 0 else -1, x=ept[0], y=ept[1], i=cdist[0], j=cdist[1], z=old_z + (new_z - old_z) * tdist / tlength)
            else:
               self.arc(1 if sspan > 0 else -1, x=ept[0], y=ept[1], i=cdist[0], j=cdist[1])
            lastpt = ept
         else:
            if new_z is not None:
               tdist += dist(lastpt, pt)
               self.linear(x=pt[0], y=pt[1], z=old_z + (new_z - old_z) * tdist / tlength)
            else:
               self.linear(x=pt[0], y=pt[1])
            lastpt = pt
      return lastpt

   def ramped_move_z(self, new_z, old_z, subpath, slope, semi_safe_z):
      if False:
         # If doing it properly proves to be too hard
         subpath = CircleFitter.interpolate_arcs(subpath, False, 1)
      if new_z >= old_z:
         self.rapid(z=new_z)
         # ???
         return
      if old_z > semi_safe_z:
         self.rapid(z=semi_safe_z)
         old_z = semi_safe_z
      # Always positive
      z_diff = old_z - new_z
      xy_diff = z_diff * slope
      tlengths = path_lengths(subpath)
      npasses = xy_diff / tlengths[-1]
      if debug_ramp:
         self.add("(Ramp from %0.2f to %0.2f segment length %0.2f xydiff %0.2f passes %d)" % (old_z, new_z, tlengths[-1], xy_diff, npasses))
      subpath_reverse = reverse_path(subpath)
      self.linear(x=subpath[0][0], y=subpath[0][1])
      lastpt = subpath[0]
      per_level = tlengths[-1] / slope
      cur_z = old_z
      for i in range(ceil(npasses)):
         if i == floor(npasses):
            # Last pass, do a shorter one
            newlength = (npasses - floor(npasses)) * tlengths[-1]
            if newlength < 1 / RESOLUTION:
               # Very small delta, just plunge down
               self.linear(z=new_z)
               break
            if debug_ramp:
               self.add("(Last pass, shortening to %d)" % newlength)
            subpath = calc_subpath(subpath, 0, newlength)
            real_length = path_length(subpath)
            assert abs(newlength - real_length) < 1 / RESOLUTION
            subpath_reverse = reverse_path(subpath)
            tlengths = path_lengths(subpath)
         pass_z = max(new_z, old_z - i * per_level)
         next_z = max(new_z, pass_z - per_level)
         if debug_ramp:
            self.add("(Pass %d base level %0.2f min %0.2f)" % (i, pass_z, next_z))
         lastpt = self.apply_subpath(subpath, lastpt, next_z, cur_z, tlengths[-1])
         cur_z = next_z
         lastpt = self.apply_subpath(subpath_reverse, lastpt)
      return lastpt

def pathToGcode(gcode, path, safe_z, semi_safe_z, start_depth, end_depth, doc, tabs, tab_depth):
   def simplifySubpaths(subpaths):
      return [(is_tab, CircleFitter.simplify(subpath)) for is_tab, subpath in subpaths]
   paths = path.flattened() if isinstance(path, Toolpaths) else [path]
   prev_depth = semi_safe_z
   depth = max(start_depth - doc, end_depth)
   curz = safe_z
   lastpt = None
   slope = max(1, int(path.tool.hfeed / path.tool.vfeed))
   paths_out = []
   for p in paths:
      subpaths_full = [(False, p.points + ([p.points[0]] if p.closed else []))]
      subpaths_tabbed = p.eliminate_tabs2(tabs) if tabs and tabs.tabs else subpaths_full
      if simplify_arcs:
         subpaths_tabbed = simplifySubpaths(subpaths_tabbed)
         subpaths_full = simplifySubpaths(subpaths_full)
      paths_out.append((subpaths_tabbed, subpaths_full))
   while True:
      for subpaths_tabbed, subpaths_full in paths_out:
         subpaths = subpaths_tabbed if depth < tab_depth else subpaths_full
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
                  lastpt = gcode.ramped_move_z(newz, curz, subpath, slope, semi_safe_z)
               else:
                  gcode.move_z(newz, curz, p.tool, semi_safe_z)
               curz = newz
            # First point was either equal to the most recent one, or
            # was reached using a rapid move, so omit it here.
            lastpt = gcode.apply_subpath(subpath, lastpt)
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
         self.tabs = self.flattened[0].autotabs(tabs, width=self.tabs_width())
      else:
         self.tabs = Tabs([])
   def tabs_width(self):
      return 1
   def to_gcode(self, gcode, safe_z, semi_safe_z):
      tab_depth = self.props.tab_depth
      if tab_depth is None:
         tab_depth = self.props.depth
      for path in self.flattened:
         pathToGcode(gcode, path=path, safe_z=safe_z, semi_safe_z=semi_safe_z,
            start_depth=self.props.start_depth, end_depth=self.props.depth,
            doc=self.tool.maxdoc, tabs=self.tabs, tab_depth=tab_depth)

class Contour(Operation):
   def __init__(self, shape, outside, tool, props, tabs):
      Operation.__init__(self, shape, tool, shape.contour(tool, outside=outside), props, tabs=tabs)

def trochoidal(path, nrad, nspeed):
   res = []
   lastpt = path[0]
   res.append(lastpt)
   for pt in path:
      d = dist(lastpt, pt)
      subdiv = ceil(max(10, d * RESOLUTION))
      for i in range(subdiv):
         res.append(weighted(lastpt, pt, i / subdiv))
      lastpt = pt
   res.append(path[-1])
   path = res
   res = []
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
   res.append(pt)
   return res

class TrochoidalContour(Operation):
   def __init__(self, shape, outside, tool, props, nrad, nspeed, tabs):
      nrad *= 0.5 * tool.diameter
      self.nrad = nrad
      self.nspeed = nspeed
      if not outside:
         nrad = -nrad
      contour = shape.contour(tool, outside=outside, displace=nrad)
      points = trochoidal(contour.points, nrad, nspeed)
      contour = Toolpath(points, contour.closed, tool)
      Operation.__init__(self, shape, tool, contour, props, tabs=tabs)
   def tabs_width(self):
      # This needs tweaking
      return 4 * pi * self.nspeed

class Pocket(Operation):
   def __init__(self, shape, tool, props):
      Operation.__init__(self, shape, tool, shape.pocket_contour(tool), props)

class Engrave(Operation):
   def __init__(self, shape, tool, props):
      Operation.__init__(self, shape, tool, shape.engrave(tool), props)

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
class HelicalDrillFullDepth(HelicalDrill):
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
            d += self.tool.diameter * self.tool.stepover_fulldepth
         r = max(0, (self.d - self.tool.diameter) / 2)
         gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth)
      gcode.rapid(z=safe_z)
         

class Operations(object):
   def __init__(self, safe_z, semi_safe_z, tool=None, props=None):
      self.safe_z = safe_z
      self.semi_safe_z = semi_safe_z
      self.tool = tool
      self.props = props
      self.operations = []
   def add(self, operation):
      self.operations.append(operation)
   def outside_contour(self, shape, tabs, props=None):
      self.add(Contour(shape, True, self.tool, props or self.props, tabs=tabs))
   def outside_contour_trochoidal(self, shape, nrad, nspeed, tabs, props=None):
      self.add(TrochoidalContour(shape, True, self.tool, props or self.props, nrad=nrad, nspeed=nspeed, tabs=tabs))
   def inside_contour(self, shape, tabs, props=None):
      self.add(Contour(shape, False, self.tool, props or self.props, tabs=tabs))
   def engrave(self, shape, props=None):
      self.add(Engrave(shape, self.tool, props or self.props))
   def pocket(self, shape, props=None):
      self.add(Pocket(shape, self.tool, props or self.props))
   def helical_drill(self, x, y, d, props=None):
      self.add(HelicalDrill(x, y, d, self.tool, props or self.props))
   def helical_drill_full_depth(self, x, y, d, props=None):
      self.add(HelicalDrillFullDepth(x, y, d, self.tool, props or self.props))
   def to_gcode(self):
      gcode = Gcode()
      gcode.reset()
      gcode.rapid(z=self.safe_z)
      gcode.rapid(x=0, y=0)
      for operation in self.operations:
         operation.to_gcode(gcode, self.safe_z, self.semi_safe_z)
      gcode.rapid(x=0, y=0)
      gcode.finish()
      return gcode
   def to_gcode_file(self, filename):
      glines = self.to_gcode().gcode
      f = open(filename, "w")
      for line in glines:
        f.write(line + '\n')
      f.close()
