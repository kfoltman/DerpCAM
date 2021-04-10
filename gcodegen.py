from process import *

# VERY experimental feature
simplify_arcs = False
debug_simplify_arcs = False
debug_ramp = False
debug_tabs = False

class OperationProps(object):
   def __init__(self, depth, start_depth = 0, tab_depth = None, margin = 0):
      self.depth = depth
      self.start_depth = start_depth
      self.tab_depth = tab_depth
      self.margin = margin
   def clone(self, **attrs):
      res = OperationProps(self.depth, self.start_depth, self.tab_depth, self.margin)
      for k, v in attrs.items():
         assert hasattr(res, k), "Unknown attribute %s" % k
         setattr(res, k, v)
      return res
   def with_finish_pass(self, margin = 0):
      return self.clone(start_depth=self.depth, margin=margin)

class Gcode(object):
   def __init__(self):
      self.gcode = []
      self.last_feed = 0
   def add(self, line):
      self.gcode.append(line)
   def reset(self):
      accuracy = 0.5 / RESOLUTION
      self.add("G17 G21 G90 G40 G64 P%0.3f Q%0.3f" % (accuracy, accuracy))
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
   def dwell(self, millis):
      self.add("G4 P%0.0f" % millis)

   def helix_turn(self, x, y, r, start_z, end_z):
      self.linear(x = x + r, y = y)
      cur_z = start_z
      delta_z = end_z - start_z
      if False: # generate 4 quadrants for a circle - seems unnecessary
         self.arc_ccw(x = x, y = y + r, i = -r, z = cur_z + 0.25 * delta_z)
         self.arc_ccw(x = x - r, y = y, j = -r, z = cur_z + 0.5 * delta_z)
         self.arc_ccw(x = x, y = y - r, i = r, z = cur_z + 0.75 * delta_z)
         self.arc_ccw(x = x + r, y = y, j = r, z = cur_z + delta_z)
      else:
         ccw = True
         if ccw:
            self.arc_ccw(i = -r, z = cur_z + 0.5 * delta_z)
         else:
            self.arc_cw(i = -r, z = cur_z + 0.5 * delta_z)
      
   def move_z(self, new_z, old_z, tool, semi_safe_z, already_cut_z=None):
      if new_z == old_z:
         return
      if new_z < old_z:
         if old_z > semi_safe_z:
            self.rapid(z=semi_safe_z)
            old_z = semi_safe_z
         if already_cut_z is not None:
            # Plunge at hfeed mm/min right above the cut to avoid taking ages
            if new_z < already_cut_z and old_z > already_cut_z:
               self.feed(tool.hfeed)
               self.linear(z=already_cut_z)
               old_z = already_cut_z
         # Use plunge rate for the last part
         self.feed(tool.vfeed)
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

   def prepare_move_z(self, new_z, old_z, semi_safe_z, already_cut_z):
      if old_z > semi_safe_z:
         self.rapid(z=semi_safe_z)
         old_z = semi_safe_z
      if already_cut_z is not None and new_z < already_cut_z and old_z > already_cut_z:
         self.linear(z=already_cut_z)
         old_z = already_cut_z
      return old_z

   def helical_move_z(self, new_z, old_z, helical_entry, tool, semi_safe_z, already_cut_z=None):
      x, y, r = helical_entry
      if new_z >= old_z:
         self.rapid(z=new_z)
         return
      old_z = self.prepare_move_z(new_z, old_z, semi_safe_z, already_cut_z)
      cur_z = old_z
      while cur_z > new_z:
         next_z = max(new_z, cur_z - 2 * pi * r / tool.slope())
         self.helix_turn(x, y, r, cur_z, next_z)
         cur_z = next_z
      self.helix_turn(x, y, r, next_z, next_z)
      self.linear(x=x, y=y, z=new_z)
      return (x, y)

   def ramped_move_z(self, new_z, old_z, subpath, tool, semi_safe_z, already_cut_z, lastpt):
      if False:
         # If doing it properly proves to be too hard
         subpath = CircleFitter.interpolate_arcs(subpath, False, 1)
      if new_z >= old_z:
         self.rapid(z=new_z)
         return lastpt
      old_z = self.prepare_move_z(new_z, old_z, semi_safe_z, already_cut_z)
      # Always positive
      z_diff = old_z - new_z
      xy_diff = z_diff * tool.slope()
      tlengths = path_lengths(subpath)
      max_ramp_length = max(20, 10 * tool.diameter)
      if tlengths[-1] > max_ramp_length:
         subpath = calc_subpath(subpath, 0, max_ramp_length)
         tlengths = path_lengths(subpath)
      npasses = xy_diff / tlengths[-1]
      if debug_ramp:
         self.add("(Ramp from %0.2f to %0.2f segment length %0.2f xydiff %0.2f passes %d)" % (old_z, new_z, tlengths[-1], xy_diff, npasses))
      subpath_reverse = reverse_path(subpath)
      self.linear(x=subpath[0][0], y=subpath[0][1])
      lastpt = subpath[0]
      per_level = tlengths[-1] / tool.slope()
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
         if False:
            # Simple progressive ramping (not tested!). It does not do lifting,
            # so it's probably no better for non-centre cutting tools than the
            # simple one.
            dz = next_z - cur_z
            lastpt = self.apply_subpath(subpath, lastpt, cur_z + dz * 0.5, cur_z, tlengths[-1])
            lastpt = self.apply_subpath(subpath_reverse, lastpt, cur_z + dz, cur_z + dz * 0.5, tlengths[-1])
            cur_z = next_z
         else:
            # This is one of the possible strategies: ramp at an angle, then
            # come back straight. This is not ideal, especially for the non-centre
            # cutting tools.
            lastpt = self.apply_subpath(subpath, lastpt, next_z, cur_z, tlengths[-1])
            cur_z = next_z
            lastpt = self.apply_subpath(subpath_reverse, lastpt)
      return lastpt

class MachineParams(object):
   def __init__(self, safe_z, semi_safe_z):
      self.safe_z = safe_z
      self.semi_safe_z = semi_safe_z
      self.over_tab_safety = 0.1

class Cut(object):
   def __init__(self, machine_params, props, tool):
      self.machine_params = machine_params
      self.props = props
      self.tool = tool

# A bit unfortunate name, might be changed in future
class CutPath2D(object):
   def __init__(self, p, tabs):
      def simplifySubpaths(subpaths):
         return [subpath.lines_to_arcs() for subpath in subpaths]
      self.subpaths_full = [p.transformed()]
      self.subpaths_tabbed = p.eliminate_tabs2(tabs) if tabs and tabs.tabs else self.subpaths_full
      self.subpaths_tabbed = [subpath.transformed() for subpath in self.subpaths_tabbed]
      if simplify_arcs:
         self.subpaths_tabbed = simplifySubpaths(self.subpaths_tabbed)
         self.subpaths_full = simplifySubpaths(self.subpaths_full)

# Simple tabbed 2D toolpath
class Cut2D(Cut):
   def __init__(self, machine_params, props, tool, toolpaths, tabs):
      Cut.__init__(self, machine_params, props, tool)
      if props.tab_depth is not None and props.tab_depth < props.depth:
         raise ValueError("Tab Z=%0.2fmm below cut Z=%0.2fmm." % (props.tab_depth, props.depth))
      self.tabs = tabs
      self.prepare_paths(toolpaths)
      self.tab_depth = self.props.tab_depth if self.props.tab_depth is not None else self.props.depth
      self.over_tab_z = self.tab_depth + self.machine_params.over_tab_safety

   def prepare_paths(self, toolpaths):
      # Convert to an array of single Toolpath objects
      flattened = toolpaths.flattened() if isinstance(toolpaths, Toolpaths) else [toolpaths]
      self.cutpaths = [CutPath2D(p, self.tabs) for p in flattened]

   def build(self, gcode):
      for cutpath in self.cutpaths:
         self.build_cutpath(gcode, cutpath)

   def build_cutpath(self, gcode, cutpath):
      self.start_cutpath(gcode)
      while self.next_depth():
         self.build_layer(gcode, cutpath)
      self.end_cutpath(gcode)

   def build_layer(self, gcode, cutpath):
      subpaths = cutpath.subpaths_tabbed if self.depth < self.tab_depth else cutpath.subpaths_full
      # Not a continuous path, need to jump to a new place
      firstpt = subpaths[0].points[0]
      if self.lastpt is None or dist(self.lastpt, firstpt) > 1 / RESOLUTION:
         self.go_to_safe_z(gcode)
         # Note: it's not ideal because of the helical entry, but it's
         # good enough.
         gcode.rapid(x=firstpt[0], y=firstpt[1])
         self.lastpt = firstpt
      for subpath in subpaths:
         self.build_subpath(gcode, subpath)

   def build_subpath(self, gcode, subpath):
      # This will always be false for subpaths_full.
      is_tab = subpath.is_tab
      newz = self.over_tab_z if is_tab else self.depth
      if is_tab and debug_tabs:
         gcode.add("(tab start)")
      self.enter_or_leave_cut(gcode, subpath, newz, is_tab)
      points = subpath.points + subpath.points[0:1] if subpath.closed else subpath.points
      assert self.lastpt is not None
      self.lastpt = gcode.apply_subpath(points, self.lastpt)
      if is_tab and debug_tabs:
         gcode.add("(tab end)")

   def enter_or_leave_cut(self, gcode, subpath, newz, is_tab):
      if newz != self.curz:
         if newz < self.curz:
            self.enter_cut(gcode, subpath, newz, is_tab)
         else:
            gcode.move_z(newz, self.curz, subpath.tool, self.machine_params.semi_safe_z)
            self.curz = newz

   def enter_cut(self, gcode, subpath, newz, is_tab):
      # Z slightly above the previous cuts. There will be no ramping or helical
      # entry above that, just a straight plunge. However, the speed of the
      # plunge will be dependent on whether a ramped or helical entry is used
      # for the rest of the descent. In case of ramped entry, we go slow, at
      # plunge feed rate. For helical entry, there is already a hole milled
      # up to prev_depth, so we can descend faster, at horizontal feed rate.

      # For tabs, do not consider anything lower than tab_depth as milled, because
      # it is not, as there is a tab there!
      z_already_cut_here = max(self.tab_depth, self.prev_depth) if is_tab else self.prev_depth
      z_above_cut = z_already_cut_here + self.machine_params.over_tab_safety
      if self.prev_depth < self.curz:
         z_to_plunge_to = max(newz, self.tab_depth if is_tab else self.prev_depth)
         if subpath.helical_entry:
            gcode.move_z(z_to_plunge_to, self.curz, subpath.tool, self.machine_params.semi_safe_z, z_above_cut)
         else:
            gcode.move_z(z_to_plunge_to, self.curz, subpath.tool, self.machine_params.semi_safe_z)
         self.curz = z_to_plunge_to
      gcode.feed(subpath.tool.hfeed)
      if subpath.helical_entry is not None:
         # Descend helically to the indicated helical entry point
         self.lastpt = gcode.helical_move_z(newz, self.curz, subpath.helical_entry, subpath.tool, self.machine_params.semi_safe_z, z_above_cut)
         if subpath.helical_entry != subpath.points[0]:
            # The helical entry ends somewhere else in the pocket, so feed to the right spot
            self.lastpt = subpath.points[0]
            gcode.linear(x=self.lastpt[0], y=self.lastpt[1])
         assert self.lastpt is not None
      else:
         if newz < self.curz:
            self.lastpt = gcode.ramped_move_z(newz, self.curz, subpath.points, subpath.tool, self.machine_params.semi_safe_z, z_above_cut, None)
         assert self.lastpt is not None
      self.curz = newz

   def start_cutpath(self, gcode):
      self.curz = self.machine_params.safe_z
      self.depth = self.props.start_depth
      self.lastpt = None

   def end_cutpath(self, gcode):
      self.go_to_safe_z(gcode)

   def go_to_safe_z(self, gcode):
      gcode.rapid(z=self.machine_params.safe_z)
      self.curz = self.machine_params.safe_z

   def next_depth(self):
      if self.depth == self.props.depth:
         return False
      doc = self.doc(self.depth)
      self.prev_depth = self.depth
      # Is there a tab depth in between the current and the new depth?
      if self.depth > self.tab_depth and self.depth - doc < self.tab_depth:
         # Make sure that the full tab depth is milled with non-interrupted
         # paths before switching to the interrupted (tabbed) path. This is
         # to prevent accidentally using a non-trochoidal path for the last pass
         self.depth = max(self.props.depth, self.tab_depth)
      else:
         self.depth = max(self.props.depth, self.depth - doc)
      return True
   def doc(self, depth):
      # XXXKF add provisions for finish passes here
      return self.tool.maxdoc

def oldPathToGcode(gcode, path, machine_params, start_depth, end_depth, doc, tabs, tab_depth):
   def simplifySubpaths(subpaths):
      return [subpath.lines_to_arcs() for subpath in subpaths]
   z_margin = machine_params.semi_safe_z - start_depth
   paths = path.flattened() if isinstance(path, Toolpaths) else [path]
   prev_depth = machine_params.semi_safe_z
   if tab_depth is not None and tab_depth < end_depth:
      raise ValueError("Tab Z=%0.2fmm below cut Z=%0.2fmm." % (tab_depth, end_depth))
   depth = max(start_depth - doc, end_depth)
   curz = machine_params.safe_z
   lastpt = None
   paths_out = []
   for p in paths:
      subpaths_full = [p.transformed()]
      subpaths_tabbed = p.eliminate_tabs2(tabs) if tabs and tabs.tabs else subpaths_full
      subpaths_tabbed = [subpath.transformed() for subpath in subpaths_tabbed]
      if simplify_arcs:
         subpaths_tabbed = simplifySubpaths(subpaths_tabbed)
         subpaths_full = simplifySubpaths(subpaths_full)
      paths_out.append((subpaths_tabbed, subpaths_full))
   while True:
      for subpaths_tabbed, subpaths_full in paths_out:
         subpaths = subpaths_tabbed if depth < tab_depth else subpaths_full
         # Not a continuous path, need to jump to a new place
         firstpt = subpaths[0].points[0]
         if lastpt is None or dist(lastpt, firstpt) > 1 / RESOLUTION:
            gcode.rapid(z=machine_params.safe_z)
            curz = machine_params.safe_z
            # Note: it's not ideal because of the helical entry, but it's
            # good enough.
            gcode.rapid(x=firstpt[0], y=firstpt[1])
            lastpt = firstpt
         for subpath in subpaths:
            is_tab = subpath.is_tab
            newz = tab_depth + machine_params.over_tab_safety if is_tab else depth
            if is_tab and debug_tabs:
               gcode.add("(tab start)")
            if newz != curz:
               z_above_cut = prev_depth + z_margin
               if newz < curz:
                  if not is_tab and prev_depth < curz:
                     # Go back faster (at horizontal feed rate) when there is
                     # a helical entry hole already made during the previous
                     # passes
                     if subpath.helical_entry:
                        gcode.move_z(prev_depth, curz, p.tool, machine_params.semi_safe_z, z_above_cut)
                     else:
                        gcode.move_z(prev_depth, curz, p.tool, machine_params.semi_safe_z)
                     curz = prev_depth
                  gcode.feed(p.tool.hfeed)
                  if subpath.helical_entry:
                     lastpt = gcode.helical_move_z(newz, curz, subpath.helical_entry, p.tool, machine_params.semi_safe_z, z_above_cut)
                     if subpath.helical_entry != subpath.points[0]:
                        # The helical entry ends somewhere else in the pocket, so feed to the right spot
                        lastpt = subpath.points[0]
                        gcode.linear(x=lastpt[0], y=lastpt[1])
                  else:
                     lastpt = gcode.ramped_move_z(newz, curz, subpath.points, p.tool, machine_params.semi_safe_z, z_above_cut)
               else:
                  gcode.move_z(newz, curz, p.tool, machine_params.semi_safe_z)
               curz = newz
            # First point was either equal to the most recent one, or
            # was reached using a rapid move, so omit it here.
            if subpath.closed:
               lastpt = gcode.apply_subpath(subpath.points + subpath.points[0:1], lastpt)
            else:
               lastpt = gcode.apply_subpath(subpath.points, lastpt)
            if is_tab and debug_tabs:
               gcode.add("(tab end)")
      if depth == end_depth:
         break
      prev_depth = depth
      # Make sure that the full tab depth is milled with non-interrupted
      # paths before switching to the interrupted (tabbed) path. This is
      # to prevent accidentally using a non-trochoidal path for the last pass
      if depth > tab_depth:
         depth = max(depth - doc, tab_depth)
      else:
         depth = max(depth - doc, end_depth)
   gcode.rapid(z=machine_params.safe_z)
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
         self.tabbed = self.flattened[0].eliminate_tabs2(self.tabs)
      else:
         self.tabs = Tabs([])
         self.tabbed = self.flattened
   def tabs_width(self):
      return 1
   def to_gcode(self, gcode, machine_params):
      tab_depth = self.props.tab_depth
      if tab_depth is None:
         tab_depth = self.props.depth
      for path in self.flattened:
         Cut2D(machine_params, self.props, self.tool, path, self.tabs).build(gcode)
         #pathToGcode(gcode, path=path, machine_params=machine_params,
         #   start_depth=self.props.start_depth, end_depth=self.props.depth,
         #   doc=self.tool.maxdoc, tabs=self.tabs, tab_depth=tab_depth)

class Contour(Operation):
   def __init__(self, shape, outside, tool, props, tabs):
      Operation.__init__(self, shape, tool, shape.contour(tool, outside=outside, displace=props.margin), props, tabs=tabs)

class TrochoidalContour(Operation):
   def __init__(self, shape, outside, tool, props, nrad, nspeed, tabs):
      nrad *= 0.5 * tool.diameter
      self.nrad = nrad
      self.nspeed = nspeed
      if not outside:
         nrad = -nrad
      contour = shape.contour(tool, outside=outside, displace=nrad + props.margin)
      trochoidal_func = lambda contour: trochoidal_transform(contour, nrad, nspeed)
      contour = Toolpath(contour.points, contour.closed, tool, transform=trochoidal_func)
      Operation.__init__(self, shape, tool, contour, props, tabs=tabs)
   def tabs_width(self):
      # This needs tweaking
      return 1 + self.nrad

class Pocket(Operation):
   def __init__(self, shape, tool, props):
      Operation.__init__(self, shape, tool, shape.pocket_contour(tool, displace=props.margin), props)

class Engrave(Operation):
   def __init__(self, shape, tool, props):
      Operation.__init__(self, shape, tool, shape.engrave(tool), props)

class FaceMill(Operation):
   def __init__(self, shape, angle, margin, zigzag, tool, props):
      Operation.__init__(self, shape, tool, shape.face_mill(tool, angle, margin, zigzag), props)

class RetractSchedule(object):
   pass

class RetractToSemiSafe(RetractSchedule):
   def get(self, z, props, semi_safe_z):
      return max(z, semi_safe_z)

class RetractToStart(RetractSchedule):
   def get(self, z, props, semi_safe_z):
      return max(z, props.start_depth)

class RetractBy(RetractSchedule):
   def __init__(self, peck_depth):
      self.peck_depth = peck_depth
   def get(self, z, props, semi_safe_z):
      return min(z + self.peck_depth, props.start_depth)

class PeckDrill(Operation):
   def __init__(self, x, y, tool, props, dwell_bottom=0, dwell_retract=0, retract=None, slow_retract=False):
      shape = Shape.circle(x, y, r=0.5 * tool.diameter)
      Operation.__init__(self, shape, tool, Toolpath([(x, y)], True, tool), props)
      self.x = x
      self.y = y
      self.dwell_bottom = dwell_bottom
      self.dwell_retract = dwell_retract
      self.retract = retract or RetractToSemiSafe()
      self.slow_retract = slow_retract
   def to_gcode(self, gcode, machine_params):
      gcode.rapid(z=machine_params.semi_safe_z)
      gcode.feed(self.tool.vfeed)
      curz = self.props.start_depth
      doc = self.tool.maxdoc
      while curz > self.props.depth:
         nextz = max(curz - doc, self.props.depth)
         gcode.linear(z=nextz)
         if self.dwell_bottom:
            gcode.dwell(1000 * self.dwell_bottom)
         retrz = self.retract.get(nextz, self.props, machine_params.semi_safe_z)
         if self.slow_retract:
            gcode.linear(z=retrz)
         else:
            gcode.rapid(z=retrz)
         if self.dwell_retract:
            gcode.dwell(1000 * self.dwell_retract)
         curz = nextz

class HelicalDrill(Operation):
   def __init__(self, x, y, d, tool, props):
      self.min_dia = tool.diameter + tool.min_helix_diameter
      if d < self.min_dia:
         raise ValueError("Diameter %0.3f smaller than the minimum %0.3f" % (d, self.min_dia))
      shape = Shape.circle(x, y, r=0.5*d)
      Operation.__init__(self, shape, tool, shape.pocket_contour(tool), props)
      self.x = x
      self.y = y
      self.d = d

   def to_gcode(self, gcode, machine_params):
      if self.d < 2 * self.tool.diameter * self.tool.stepover:
         self.to_gcode_ring(gcode, self.d, machine_params)
      else:
         d = 2 * self.tool.diameter * self.tool.stepover
         while d < self.d:
            self.to_gcode_ring(gcode, d, machine_params)
            d += self.tool.diameter * self.tool.stepover
         self.to_gcode_ring(gcode, self.d, machine_params)
      gcode.rapid(z=machine_params.safe_z)
         
   def to_gcode_ring(self, gcode, d, machine_params):
      r = max(self.tool.diameter * self.tool.stepover / 2, (d - self.tool.diameter) / 2)
      gcode.rapid(z=machine_params.safe_z)
      gcode.rapid(x=self.x + r, y=self.y)
      curz = machine_params.semi_safe_z
      gcode.rapid(z=machine_params.semi_safe_z)
      gcode.feed(self.tool.hfeed)
      dist = 2 * pi * r
      doc = min(self.tool.maxdoc, dist / self.tool.slope())
      while curz > self.props.depth:
         nextz = max(curz - doc, self.props.depth)
         gcode.helix_turn(self.x, self.y, r, curz, nextz)
         curz = nextz
      gcode.helix_turn(self.x, self.y, r, curz, curz)

# First make a helical entry and then enlarge to the target diameter
# by side milling
class HelicalDrillFullDepth(HelicalDrill):
   def to_gcode(self, gcode, machine_params):
      if self.d < self.min_dia:
         self.to_gcode_ring(gcode, self.d, machine_params)
      else:
         # Mill initial hole by helical descent into desired depth
         d = self.min_dia
         self.to_gcode_ring(gcode, d, machine_params)
         # Bore it out at full depth to the final diameter
         while d < self.d:
            r = max(self.tool.diameter * self.tool.stepover / 2, (d - self.tool.diameter) / 2)
            gcode.linear(x=self.x + r, y=self.y)
            gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth)
            d += self.tool.diameter * self.tool.stepover_fulldepth
         r = max(0, (self.d - self.tool.diameter) / 2)
         gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth)
      gcode.rapid(z=machine_params.safe_z)

def makeWithDraft(func, shape, draft_angle_deg, layer_thickness, props):
   draft = tan(draft_angle_deg * pi / 180)
   height = props.start_depth - props.depth
   assert height > 0
   z = props.start_depth
   cut_so_far = 0
   nlayer = 0
   while z > props.depth:
      this_layer = min(layer_thickness, height - cut_so_far)
      end_z = z - this_layer
      func(z, end_z, cut_so_far * draft)
      z = end_z
      cut_so_far += this_layer

class Operations(object):
   def __init__(self, machine_params, tool=None, props=None):
      self.machine_params = machine_params
      self.tool = tool
      self.props = props
      self.operations = []
   def add(self, operation):
      self.operations.append(operation)
   def outside_contour(self, shape, tabs, props=None):
      self.add(Contour(shape, True, self.tool, props or self.props, tabs=tabs))
   def outside_contour_trochoidal(self, shape, nrad, nspeed, tabs, props=None):
      self.add(TrochoidalContour(shape, True, self.tool, props or self.props, nrad=nrad, nspeed=nspeed, tabs=tabs))
   def outside_contour_with_draft(self, shape, draft_angle_deg, layer_thickness, props=None):
      props = props or self.props
      def addWithDraft(z, end_z, draft_margin):
         self.outside_contour(shape, tabs=None, props=props.clone(depth=end_z, margin=props.margin + draft_margin))
      makeWithDraft(addWithDraft, shape, draft_angle_deg, layer_thickness, props)
   def inside_contour(self, shape, tabs, props=None):
      self.add(Contour(shape, False, self.tool, props or self.props, tabs=tabs))
   def engrave(self, shape, props=None):
      self.add(Engrave(shape, self.tool, props or self.props))
   def pocket(self, shape, props=None):
      self.add(Pocket(shape, self.tool, props or self.props))
   def pocket_with_draft(self, shape, draft_angle_deg, layer_thickness, props=None):
      props = props or self.props
      def addWithDraft(z, end_z, draft_margin):
         self.pocket(shape, props.clone(start_depth=z, depth=end_z, margin=props.margin + draft_margin))
      makeWithDraft(addWithDraft, shape, draft_angle_deg, layer_thickness, props)
   def face_mill(self, shape, angle, margin, zigzag, props=None):
      self.add(FaceMill(shape, angle, margin, zigzag, self.tool, props or self.props))
   def peck_drill(self, x, y, props=None):
      self.add(PeckDrill(x, y, self.tool, props or self.props))
   def helical_drill(self, x, y, d, props=None):
      self.add(HelicalDrill(x, y, d, self.tool, props or self.props))
   def helical_drill_full_depth(self, x, y, d, props=None):
      self.add(HelicalDrillFullDepth(x, y, d, self.tool, props or self.props))
   def to_gcode(self):
      gcode = Gcode()
      gcode.reset()
      gcode.rapid(z=self.machine_params.safe_z)
      gcode.rapid(x=0, y=0)
      for operation in self.operations:
         operation.to_gcode(gcode, self.machine_params)
      gcode.rapid(x=0, y=0)
      gcode.finish()
      return gcode
   def to_gcode_file(self, filename):
      glines = self.to_gcode().gcode
      f = open(filename, "w")
      for line in glines:
        f.write(line + '\n')
      f.close()
