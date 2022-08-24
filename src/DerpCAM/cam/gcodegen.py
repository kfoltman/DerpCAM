import threading
from DerpCAM.common.geom import *
from DerpCAM import cam
import DerpCAM.cam.contour
import DerpCAM.cam.peel
import DerpCAM.cam.pocket

from DerpCAM.cam import shapes, toolpath

# VERY experimental feature
debug_simplify_arcs = False
debug_ramp = False
debug_tabs = False
debug_sections = True
# Old trochoidal code didn't guarantee the same path for tabbed and non-tabbed
# versions, so the non-tabbed version had to be cut all the way to the tab depth.
old_trochoidal_code = False

class OperationProps(object):
    def __init__(self, depth, start_depth=0, tab_depth=None, margin=0, zigzag=False, angle=0):
        self.depth = depth
        self.start_depth = start_depth
        self.tab_depth = tab_depth
        self.margin = margin
        self.zigzag = zigzag
        self.angle = angle
        self.rpm = None
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
        self.inch_mode = GeometrySettings.gcode_inches
        self.gcode = []
        self.last_feed = 0
        self.last_feed_index = None
        self.rpm = None
        self.last_rpm = None
        self.last_coords = None
    def add(self, line):
        self.gcode.append(line)
    def add_dedup(self, line):
        if self.gcode and self.gcode[-1] == line:
            return
        self.gcode.append(line)
    def comment(self, comment):
        comment = comment.replace("(", "<").replace(")",">")
        self.add(f"({comment})")
    def section_info(self, comment):
        if debug_sections:
            self.comment(comment)
    def reset(self):
        accuracy = 0.5 / GeometrySettings.RESOLUTION
        unit_mode = "G20" if self.inch_mode else "G21"
        # Grbl doesn't understand G64
        accuracy_mode = "" if GeometrySettings.grbl_output else f" G64 P{accuracy:0.3f} Q{accuracy:0.3f}"
        self.add(f"G17 G90 G40 {unit_mode}{accuracy_mode}")
    def spindle_start(self):
        if GeometrySettings.spindle_control:
            if self.rpm is not None:
                self.add(f"M3 S{self.rpm}")
                if self.last_rpm != self.rpm:
                    self.dwell(GeometrySettings.spindle_warmup)
                    self.last_rpm = self.rpm
            else:
                self.add("M3")
    def spindle_stop(self):
        if GeometrySettings.spindle_control:
            self.add("M5")
            self.last_rpm = None
    def prompt_for_tool(self, name):
        self.spindle_stop()
        name = name.replace("(", "<").replace(")",">")
        self.add(f"M1 ({name})")
        self.reset()
    def finish(self):
        self.spindle_stop()
        self.add("M2")
    def begin_section(self, rpm=None):
        self.last_feed = None
        self.rpm = rpm
        if self.rpm is not None:
            self.spindle_start()
    def feed(self, feed):
        if feed != self.last_feed:
            if self.last_feed_index == len(self.gcode) - 1:
                self.gcode[-1] = self.enc_feed(feed)
            else:
                self.add(self.enc_feed(feed))
            self.last_feed = feed
            self.last_feed_index = len(self.gcode) - 1
    def add_dedup_g0g1(self, cmd, x=None, y=None, z=None):
        coords = self.enc_coords(x, y, z)
        if coords == self.last_coords:
            return
        self.add_dedup(cmd + coords)
        self.last_coords = coords
    def rapid(self, x=None, y=None, z=None):
        self.add_dedup_g0g1("G0", x, y, z)
    def linear(self, x=None, y=None, z=None):
        self.add_dedup_g0g1("G1", x, y, z)
    def arc_cw(self, x=None, y=None, z=None, i=None, j=None, k=None):
        self.add("G2" + self.enc_coords_arc(x, y, z, i, j, k))
        self.last_coords = self.enc_coords(x, y, z)
    def arc_ccw(self, x=None, y=None, z=None, i=None, j=None, k=None):
        self.add("G3" + self.enc_coords_arc(x, y, z, i, j, k))
        self.last_coords = self.enc_coords(x, y, z)
    def arc(self, direction, x=None, y=None, z=None, i=None, j=None, k=None):
        (self.arc_ccw if direction > 0 else self.arc_cw)(x, y, z, i, j, k)
    def dwell(self, delay):
        self.add(f"G4 P{delay:0.2f}")
    def enc_feed(self, feed):
        if self.inch_mode:
            return f"F{feed / 25.4:0.3f}"
        else:
            return f"F{feed:0.2f}"
    def enc_coord(self, letter, value):
        if self.inch_mode:
            return (" %s%0.4f" % (letter, value / 25.4)).rstrip("0").rstrip(".")
        else:
            return (" %s%0.3f" % (letter, value)).rstrip("0").rstrip(".")
    def enc_coords(self, x=None, y=None, z=None):
        res = ""
        if x is not None:
            res += self.enc_coord('X', x)
        if y is not None:
            res += self.enc_coord('Y', y)
        if z is not None:
            res += self.enc_coord('Z', z)
        return res
    def enc_coords_arc(self, x=None, y=None, z=None, i=None, j=None, k=None):
        res = self.enc_coords(x, y, z)
        if i is not None:
            res += self.enc_coord('I', i)
        if j is not None:
            res += self.enc_coord('J', j)
        if k is not None:
            res += self.enc_coord('K', k)
        return res

    def helix_turn(self, x, y, r, start_z, end_z, angle=0, climb=True):
        i = -r * cos(angle)
        j = -r * sin(angle)
        sx = x - i
        sy = y - j
        self.linear(x = sx, y = sy)
        cur_z = start_z
        delta_z = end_z - start_z
        arc_dir = direction=1 if climb else -1
        if GeometrySettings.grbl_output:
            sx2 = x + i
            sy2 = y + j
            self.arc(arc_dir, x = sx2, y = sy2, i = i, j = j, z = cur_z + delta_z / 2.0)
            self.arc(arc_dir, x = sx, y = sy, i = -i, j = -j, z = cur_z + delta_z)
        else:
            self.arc(arc_dir, x = sx, i = i, j = j, z = cur_z + delta_z)

    def move_z(self, new_z, old_z, tool, semi_safe_z, already_cut_z=None):
        if new_z == old_z:
            return
        if new_z > old_z:
            # Retract from the cut - can always use rapids, no questions asked
            self.rapid(z=new_z)
            return
        if new_z >= semi_safe_z:
            # Z above material, rapids are safe
            self.rapid(z=new_z)
            return
        if GeometrySettings.paranoid_mode:
            self.rapid(z=semi_safe_z)
            # Everything from semi_safe_z down is done slowly out of paranoia
            not_very_paranoid = False
            if not_very_paranoid and already_cut_z is not None and already_cut_z < semi_safe_z:
                # Use XY feed for vertical entry into already-cut stock,
                # It's a compromise between very slow Z rate and G0 speed.
                # But it's probably not paranoid enough
                self.feed(tool.hfeed)
                self.linear(z=already_cut_z)
            self.feed(tool.vfeed)
            self.linear(z=new_z)
            return
        if already_cut_z is None:
            already_cut_z = semi_safe_z
        if new_z >= already_cut_z:
            # Above the previous cut line? Use rapid speed.
            self.rapid(z=new_z)
            return
        # Continue slowly into the stock - using this to actually enter the
        # material (and not just as a precautionary measure for the last bit
        # just above the uncut stock) is not recommended for any hard materials
        # like metals.
        self.rapid(z=already_cut_z)
        self.feed(tool.vfeed)
        self.linear(z=new_z)
        self.feed(tool.hfeed)

    def apply_subpath(self, subpath, lastpt, new_z=None, old_z=None, tlength=None):
        self.section_info(f"Start subpath")
        assert isinstance(lastpt, PathPoint)
        assert dist(lastpt, subpath.seg_start()) < 1 / GeometrySettings.RESOLUTION, f"lastpt={lastpt} != firstpt={subpath.seg_start()}"
        tdist = 0
        for lastpt, pt in PathSegmentIterator(subpath):
            if pt.is_arc() and pt.length() > 1 / GeometrySettings.RESOLUTION and pt.c.r > 1 / GeometrySettings.RESOLUTION:
                arc = pt
                assert dist(lastpt, arc.p1) < 1 / GeometrySettings.RESOLUTION
                cdist = PathPoint(arc.c.cx - arc.p1.x, arc.c.cy - arc.p1.y)
                arc_dir = 1 if arc.sspan > 0 else -1
                if GeometrySettings.grbl_output and abs(arc.sspan) >= 3 * pi / 2:
                    # Grbl has some issues with full circles, so replace anything longer than a
                    # 270 degree arc with two half-circles
                    subarc = arc.cut(0, 0.5)[1]
                    subtdist = tdist + subarc.length()
                    dest_z = old_z + (new_z - old_z) * subtdist / tlength if new_z is not None else None
                    self.arc(arc_dir, x=subarc.p2.x, y=subarc.p2.y, i=cdist.x, j=cdist.y, z=dest_z)
                    cdist = PathPoint(subarc.c.cx - subarc.p2.x, subarc.c.cy - subarc.p2.y)
                tdist += arc.length()
                dest_z = old_z + (new_z - old_z) * tdist / tlength if new_z is not None else None
                self.arc(arc_dir, x=arc.p2.x, y=arc.p2.y, i=cdist.x, j=cdist.y, z=dest_z)
            else:
                pt = pt.seg_end() # in case this was an arc
                if new_z is not None:
                    tdist += pt.length() if pt.is_arc() else dist(lastpt, pt) # Need to use arc length even if the arc was replaced with a line segment
                    self.linear(x=pt.x, y=pt.y, z=old_z + (new_z - old_z) * tdist / tlength)
                else:
                    if pt.speed_hint is toolpath.RapidMove:
                        self.rapid(x=pt.x, y=pt.y)
                    else:
                        self.linear(x=pt.x, y=pt.y)
        lastpt = pt.seg_end()
        self.section_info(f"End subpath")
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
        self.section_info(f"Start helical move from {old_z} to {new_z}")
        c, r = helical_entry.point, helical_entry.r
        if new_z >= old_z:
            self.rapid(z=new_z)
            self.section_info(f"End helical move - upward direction detected")
            return
        old_z = self.prepare_move_z(new_z, old_z, semi_safe_z, already_cut_z)
        cur_z = old_z
        while cur_z > new_z:
            next_z = max(new_z, cur_z - 2 * pi * r / tool.slope())
            self.helix_turn(c.x, c.y, r, cur_z, next_z, helical_entry.angle, helical_entry.climb)
            cur_z = next_z
        self.helix_turn(c.x, c.y, r, cur_z, cur_z, helical_entry.angle, helical_entry.climb)
        self.linear(z=new_z)
        self.section_info(f"End helical move")
        return helical_entry.start

    def ramped_move_z(self, new_z, old_z, subpath, tool, semi_safe_z, already_cut_z, lastpt):
        self.section_info(f"Start ramped move from {old_z} to {new_z}")
        if new_z >= old_z:
            self.rapid(z=new_z)
            self.section_info(f"End ramped move - upward direction detected")
            return lastpt
        old_z = self.prepare_move_z(new_z, old_z, semi_safe_z, already_cut_z)
        # Always positive
        z_diff = old_z - new_z
        xy_diff = z_diff * tool.slope()
        tlengths = subpath.lengths()
        max_ramp_length = tool.max_ramp_length(z_diff)
        if tlengths[-1] > max_ramp_length:
            subpath = subpath.subpath(0, max_ramp_length)
            tlengths = subpath.lengths()
        npasses = xy_diff / tlengths[-1]
        if debug_ramp:
            self.add("(Ramp from %0.2f to %0.2f segment length %0.2f xydiff %0.2f passes %d)" % (old_z, new_z, tlengths[-1], xy_diff, npasses))
        subpath_reverse = subpath.reverse()
        lastpt = subpath.seg_start()
        self.linear(x=lastpt.x, y=lastpt.y)
        per_level = tlengths[-1] / tool.slope()
        cur_z = old_z
        for i in range(ceil(npasses)):
            if i == floor(npasses):
                # Last pass, do a shorter one
                newlength = (npasses - floor(npasses)) * tlengths[-1]
                if newlength < 1 / GeometrySettings.RESOLUTION:
                    # Very small delta, just plunge down
                    feed = self.last_feed
                    self.feed(tool.vfeed)
                    self.linear(z=new_z)
                    self.feed(feed)
                    break
                if debug_ramp:
                    self.add("(Last pass, shortening to %d)" % newlength)
                subpath = subpath.subpath(0, newlength)
                real_length = subpath.length()
                assert abs(newlength - real_length) < 1 / GeometrySettings.RESOLUTION
                subpath_reverse = subpath.reverse()
                tlengths = subpath.lengths()
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
        self.section_info(f"End ramped move - upward direction detected")
        self.feed(tool.hfeed)
        return lastpt

class MachineParams(object):
    def __init__(self, safe_z, semi_safe_z):
        self.safe_z = safe_z
        self.semi_safe_z = semi_safe_z
        self.over_tab_safety = 0.2

class Cut(object):
    def __init__(self, machine_params, props, tool):
        self.machine_params = machine_params
        self.props = props
        self.tool = tool

# A bit unfortunate name, might be changed in future
class CutPath2D(object):
    def __init__(self, path):
        self.subpaths_full = [path.transformed()]

class TabbedCutPath2D(CutPath2D):
    def __init__(self, path_notabs, path_withtabs):
        CutPath2D.__init__(self, path_notabs)
        if old_trochoidal_code:
            self.subpaths_tabbed_deep = self.subpaths_tabbed = [(p.transformed() if not p.is_tab else p) for p in path_withtabs]
        else:
            self.subpaths_tabbed = path_withtabs
            self.subpaths_tabbed_deep = [(p.without_circles() if p.is_tab else p) for p in path_withtabs]

class CutLayer2D(object):
    def __init__(self, prev_depth, depth, subpaths, force_join=False):
        self.prev_depth = prev_depth
        self.depth = depth
        self.subpaths = subpaths
        self.force_join = force_join

# Simple tabbed 2D toolpath
class BaseCut2D(Cut):
    def __init__(self, machine_params, props, tool, toolpath):
        Cut.__init__(self, machine_params, props, tool)
        if toolpath is not None:
            self.prepare_paths(toolpath)

    def prepare_paths(self, toolpath):
        self.cutpaths = [CutPath2D(toolpath)]

    def build(self, gcode):
        for cutpath in self.cutpaths:
            self.build_cutpath(gcode, cutpath)

    def build_cutpath(self, gcode, cutpath):
        layers = self.layers_for_cutpath(cutpath)
        self.start_cutpath(gcode, cutpath)
        for layer in layers:
            self.build_layer(gcode, layer, cutpath)
        self.end_cutpath(gcode, cutpath)

    def layers_for_cutpath(self, cutpath):
        layers = []
        prev_depth = self.props.start_depth
        while True:
            depth = self.next_depth(prev_depth)
            if depth is None:
                break
            layers += self.layers_at_depth(prev_depth, depth, cutpath)
            prev_depth = depth
        return layers

    def layers_at_depth(self, prev_depth, depth, cutpath):
        return [CutLayer2D(prev_depth, depth, self.subpaths_for_layer(prev_depth, depth, cutpath))]

    def subpaths_for_layer(self, prev_depth, depth, cutpath):
        return cutpath.subpaths_full

    def build_layer(self, gcode, layer, cutpath):
        self.prev_depth = layer.prev_depth
        self.depth = layer.depth
        subpaths = layer.subpaths
        assert subpaths
        # Not a continuous path, need to jump to a new place
        firstpt = subpaths[0].path.seg_start()
        if subpaths[0].helical_entry:
            firstpt = subpaths[0].helical_entry.start
        # Assuming <1% of tool diameter of a gap is harmless enough. The tolerance
        # needs to be low enough to avoid exceeding cutter engagement specified,
        # but high enough not to be tripped by rasterization errors from
        # pyclipper etc.
        if self.lastpt is None or dist(self.lastpt, firstpt) >= self.tool.diameter / 100.0:
            if layer.force_join:
                gcode.linear(x=firstpt.x, y=firstpt.y)
            else:
                self.go_to_safe_z(gcode)
                # Note: it's not ideal because of the helical entry, but it's
                # good enough.
                gcode.rapid(x=firstpt.x, y=firstpt.y)
            self.lastpt = firstpt
        else:
            # Minor discrepancies might lead to problems with arcs etc. so fix them
            # by adding a simple line segment.
            if dist(self.lastpt, firstpt) >= 0.001:
                gcode.linear(x=firstpt.x, y=firstpt.y)
                self.lastpt = firstpt
        # print ("Layer at %f, %d subpaths" % (self.depth, len(subpaths)))
        for subpath in subpaths:
            # print ("Start", self.lastpt, subpath.points[0])
            self.build_subpath(gcode, subpath)
            # print ("End", self.lastpt, subpath.points[-1])

    def start_subpath(self, subpath):
        pass

    def end_subpath(self, subpath):
        pass

    def build_subpath(self, gcode, subpath):
        # This will always be false for subpaths_full.
        newz = self.z_to_be_cut(subpath)
        self.start_subpath(subpath)
        self.enter_or_leave_cut(gcode, subpath, newz)
        assert self.lastpt is not None
        assert isinstance(self.lastpt, PathPoint)
        self.lastpt = gcode.apply_subpath(subpath.path, self.lastpt)
        assert isinstance(self.lastpt, PathNode)
        self.end_subpath(subpath)

    def enter_or_leave_cut(self, gcode, subpath, newz):
        if newz != self.curz:
            if newz < self.curz:
                self.enter_cut(gcode, subpath, newz)
            else:
                # Leave a cut, always uses a rapid move
                gcode.move_z(newz, self.curz, subpath.tool, self.machine_params.semi_safe_z)
                self.curz = newz

    def z_already_cut_here(self, subpath):
        return self.prev_depth

    def z_to_be_cut(self, subpath):
        return self.depth

    def enter_cut(self, gcode, subpath, newz):
        # Z slightly above the previous cuts. There will be no ramping or helical
        # entry above that, just a straight plunge. However, the speed of the
        # plunge will be dependent on whether a ramped or helical entry is used
        # for the rest of the descent. In case of ramped entry, we go slow, at
        # plunge feed rate. For helical entry, there is already a hole milled
        # up to prev_depth, so we can descend faster, at horizontal feed rate.

        # For tabs, do not consider anything lower than tab_depth as milled, because
        # it is not, as there is a tab there!
        gcode.section_info(f"Start enter cut at {newz}")
        if isinstance(subpath.helical_entry, toolpath.PlungeEntry) and not GeometrySettings.paranoid_mode:
            assert subpath.was_previously_cut
            plunge_entry = subpath.helical_entry
            self.lastpt = plunge_entry.start
            gcode.rapid(z=newz)
            gcode.feed(subpath.tool.hfeed)
        else:
            z_already_cut_here = self.z_already_cut_here(subpath)
            z_above_cut = z_already_cut_here + self.machine_params.over_tab_safety
            if z_already_cut_here < self.curz:
                z_already_cut_here = z_above_cut
                gcode.move_z(z_already_cut_here, self.curz, subpath.tool, self.machine_params.semi_safe_z, z_above_cut)
                self.curz = z_already_cut_here
            speed_ratio = subpath.tool.full_plunge_feed_ratio
            if subpath.was_previously_cut:
                # no plunge penalty
                speed_ratio = 1
            # Compensate for the fact that hfeed is supposed to be the
            # horizontal component of the feed rate. In this case, we're making
            # a 3D move, so some of the programmed feed rate goes into the vertical
            # component instead.
            speed_ratio *= sqrt(subpath.tool.slope() ** 2 + 1) / subpath.tool.slope()
            gcode.feed(subpath.tool.hfeed * speed_ratio)
            if isinstance(subpath.helical_entry, toolpath.HelicalEntry):
                # Descend helically to the indicated helical entry point
                self.lastpt = gcode.helical_move_z(newz, self.curz, subpath.helical_entry, subpath.tool, self.machine_params.semi_safe_z, z_above_cut)
            else:
                if newz < self.curz:
                    self.lastpt = gcode.ramped_move_z(newz, self.curz, subpath.path, subpath.tool, self.machine_params.semi_safe_z, z_above_cut, None)
                assert self.lastpt is not None
            gcode.feed(subpath.tool.hfeed)
        if self.lastpt != subpath.path.seg_start():
            # The helical entry ends somewhere else in the pocket, so feed to the right spot
            self.lastpt = subpath.path.seg_start()
            gcode.linear(x=self.lastpt.x, y=self.lastpt.y)
        assert self.lastpt is not None
        self.curz = newz
        gcode.section_info(f"End enter cut")

    def start_cutpath(self, gcode, cutpath):
        gcode.section_info(f"Start cutpath")
        self.curz = self.machine_params.safe_z
        self.depth = self.props.start_depth
        self.lastpt = None

    def end_cutpath(self, gcode, cutpath):
        self.go_to_safe_z(gcode)
        gcode.section_info(f"End cutpath")

    def go_to_safe_z(self, gcode):
        gcode.rapid(z=self.machine_params.safe_z)
        self.curz = self.machine_params.safe_z

    def next_depth(self, depth):
        if depth <= self.props.depth:
            return None
        doc = self.doc(depth)
        return max(self.props.depth, depth - doc)

    def doc(self, depth):
        # XXXKF add provisions for finish passes here
        return self.tool.maxdoc

class Cut2DWithTabs(BaseCut2D):
    def __init__(self, machine_params, props, tool, toolpath_notabs, toolpath_withtabs):
        if props.tab_depth is not None and props.tab_depth < props.depth:
            raise ValueError("Tab Z=%0.2fmm below cut Z=%0.2fmm." % (props.tab_depth, props.depth))
        self.toolpath_notabs = toolpath_notabs
        self.toolpath_withtabs = toolpath_withtabs
        self.tab_depth = props.tab_depth if props.tab_depth is not None else props.depth
        self.over_tab_z = self.tab_depth + machine_params.over_tab_safety
        BaseCut2D.__init__(self, machine_params, props, tool, (toolpath_notabs, toolpath_withtabs))

    def prepare_paths(self, toolpath):
        toolpath_notabs, toolpath_withtabs = toolpath
        self.cutpaths = [TabbedCutPath2D(toolpath_notabs, toolpath_withtabs)]

    def subpaths_for_layer(self, prev_depth, depth, cutpath):
        if depth >= self.tab_depth:
            return cutpath.subpaths_full
        if prev_depth > self.tab_depth:
            # First pass through the tabs, potentially need to use trochoidal to cut the tabs
            return cutpath.subpaths_tabbed
        # Further passes through the tabs, use simplified paths without circles to save time
        return cutpath.subpaths_tabbed_deep

    def next_depth(self, depth):
        if depth <= self.props.depth:
            return None
        doc = self.doc(depth)
        # Is there a tab depth in between the current and the new depth?
        if old_trochoidal_code and depth > self.tab_depth and depth - doc < self.tab_depth:
            # Make sure that the full tab depth is milled with non-interrupted
            # paths before switching to the interrupted (tabbed) path. This is
            # to prevent accidentally using a non-trochoidal path for the last pass
            depth = max(self.props.depth, self.tab_depth)
        else:
            depth = max(self.props.depth, depth - doc)
        return depth

    def z_already_cut_here(self, subpath):
        return max(self.tab_depth, self.prev_depth) if subpath.is_tab else self.prev_depth

    def z_to_be_cut(self, subpath):
        if not subpath.is_tab:
            return self.depth
        # First cut of the tab should be at exact tab depth, the next ones can be at
        # over_tab_z because the tab is already cut and there's no point in rubbing the
        # cutter against the bottom of the cut.
        return self.over_tab_z if self.prev_depth < self.tab_depth else self.tab_depth

    def start_subpath(self, subpath):
        if subpath.is_tab and debug_tabs:
            gcode.add("(tab start)")

    def end_subpath(self, subpath):
        if subpath.is_tab and debug_tabs:
            gcode.add("(tab end)")

class Cut2DWithDraft(BaseCut2D):
    def __init__(self, machine_params, props, tool, shape, toolpaths_func, outline_func, outside, draft_angle_deg, layer_thickness):
        BaseCut2D.__init__(self, machine_params, props, tool, None)
        self.shape = shape
        self.outside = outside
        self.draft_angle_deg = draft_angle_deg
        self.layer_thickness = layer_thickness
        self.draft = tan(draft_angle_deg * pi / 180)
        self.outline_func = outline_func
        max_height = self.props.start_depth - self.props.depth
        toolpaths = toolpaths_func(self.props.margin + max_height * self.draft)
        if isinstance(toolpaths, tuple):
            toolpaths = toolpaths[0]
        self.flattened = toolpaths.flattened() if isinstance(toolpaths, toolpath.Toolpaths) else [toolpaths]
        self.cutpaths = [CutPath2D(p) for p in self.flattened]
    def layers_at_depth(self, prev_depth, depth, cutpath):
        base_layers = [CutLayer2D(prev_depth, depth, self.subpaths_for_layer(prev_depth, depth, cutpath))]
        if depth > self.props.depth:
            return base_layers
        nslices = ceil((self.props.start_depth - self.props.depth) / self.layer_thickness)
        draft_layers = []
        max_height = self.props.start_depth - self.props.depth
        prev_depth = self.props.depth
        for i in range(nslices):
            height = min(self.layer_thickness * (nslices - i), max_height)
            depth = self.props.start_depth - height
            draftval = self.draft * height
            contour = self.outline_func(self.props.margin + draftval)
            flattened = contour.flattened() if isinstance(contour, toolpath.Toolpaths) else [contour]
            paths = [CutPath2D(p) for p in flattened]
            assert len(paths) == 1
            draft_layers += [CutLayer2D(prev_depth, depth, paths[0].subpaths_full, force_join=True)]
            prev_depth = depth
        return base_layers + draft_layers
    def subpaths_for_layer(self, prev_depth, depth, cutpath):
        return cutpath.subpaths_full

class Operation(object):
    def __init__(self, shape, tool, props):
        self.shape = shape
        self.tool = tool
        self.props = props
        self.rpm = props.rpm if props is not None else None
    def outline(self, margin):
        contour_paths = cam.contour.plain(self.shape, self.tool.diameter, self.outside, margin, self.tool.climb)
        if contour_paths is None:
            raise ValueError("Empty contour")
        return toolpath.Toolpaths([toolpath.Toolpath(tp, self.tool) for tp in contour_paths])
    def to_text(self):
        if self.props.start_depth != 0:
            return self.operation_name() + ", " + ("%0.2fmm deep at %0.2fmm" % (self.props.start_depth - self.props.depth, -self.props.start_depth))
        else:
            return self.operation_name() + ", " + ("%0.2fmm deep" % (self.props.start_depth - self.props.depth))
    def operation_name(self):
        return self.__class__.__name__

class ToolChangeOperation(Operation):
    def __init__(self, cutter):
        Operation.__init__(self, None, None, None)
        self.cutter = cutter
    def to_text(self):
        return "Tool change: " + self.cutter.name
    def to_preview(self):
        return []
    def to_gcode(self, gcode, machine_params):
        gcode.prompt_for_tool(self.cutter.name)

class UntabbedOperation(Operation):
    def __init__(self, shape, tool, props, extra_attribs={}):
        Operation.__init__(self, shape, tool, props)
        for key, value in extra_attribs.items():
            setattr(self, key, value)
        paths = self.build_paths(0)
        if paths:
            paths = paths.optimize()
        self.paths = paths
        self.flattened = paths.flattened() if paths else None
        if not self.flattened:
            return
        for i in self.flattened:
            if is_calculation_cancelled():
                break
            i.rendered_outlines = i.render_as_outlines()
    def to_gcode(self, gcode, machine_params):
        for path in self.flattened:
            BaseCut2D(machine_params, self.props, self.tool, path).build(gcode)
    def to_preview(self):
        return [(self.props.depth, i) for i in self.flattened]

class Engrave(UntabbedOperation):
    def build_paths(self, margin):
        if margin != 0:
            raise ValueError("Offset not supported for engraving")
        return self.shape.engrave(self.tool, self.props.margin)

class FaceMill(UntabbedOperation):
    def build_paths(self, margin):
        return cam.pocket.axis_parallel(self.shape, self.tool, self.props.angle, self.props.margin + margin, self.props.zigzag)

class Pocket(UntabbedOperation):
    def build_paths(self, margin):
        return cam.pocket.contour_parallel(self.shape, self.tool, displace=self.props.margin + margin)

class HSMOperation(UntabbedOperation):
    def __init__(self, shape, tool, props, shape_to_refine):
        UntabbedOperation.__init__(self, shape, tool, props, extra_attribs={ 'shape_to_refine' : shape_to_refine })

class HSMPocket(HSMOperation):
    def build_paths(self, margin):
        return cam.pocket.hsm_peel(self.shape, self.tool, self.props.zigzag, displace=self.props.margin + margin, shape_to_refine=self.shape_to_refine)

class PocketWithDraft(UntabbedOperation):
    def __init__(self, shape, tool, props, draft_angle_deg, layer_thickness):
        UntabbedOperation.__init__(self, shape, tool, props)
        self.draft_angle_deg = draft_angle_deg
        self.layer_thickness = layer_thickness
        self.outside = False
    def build_paths(self, margin):
        return cam.pocket.contour_parallel(self.shape, self.tool, displace=self.props.margin + margin)
    def to_gcode(self, gcode, machine_params):
        Cut2DWithDraft(machine_params, self.props, self.tool, self.shape, self.build_paths, self.outline, False, self.draft_angle_deg, self.layer_thickness).build(gcode)

class OutsidePeel(UntabbedOperation):
    def build_paths(self, margin):
        return cam.peel.outside_peel(self.shape, self.tool, displace=self.props.margin + margin)

class OutsidePeelHSM(HSMOperation):
    def build_paths(self, margin):
        return cam.peel.outside_peel_hsm(self.shape, self.tool, zigzag=self.props.zigzag, displace=self.props.margin + margin, shape_to_refine=self.shape_to_refine)

class TabbedOperation(Operation):
    def __init__(self, shape, tool, props, outside, tabs, extra_attribs):
        Operation.__init__(self, shape, tool, props)
        self.outside = outside
        self.tabs = tabs
        for key, value in extra_attribs.items():
            setattr(self, key, value)
        paths, tabs = self.build_paths(0)
        self.paths = paths
        self.flattened = paths.flattened() if paths else None
        self.tabbed_for_path = {}
        if tabs:
            for i in self.flattened:
                if is_calculation_cancelled():
                    break
                i.rendered_outlines = i.render_as_outlines()
                tab_inst = i.usertabs(tabs[i], width=self.tabs_width())
                self.tabbed_for_path[i] = i.cut_by_tabs(tab_inst)
                for j in self.tabbed_for_path[i]:
                    if is_calculation_cancelled():
                        break
                    j.rendered_outlines = j.render_as_outlines()
    def to_gcode(self, gcode, machine_params):
        tab_depth = self.props.tab_depth
        if tab_depth is None:
            tab_depth = self.props.depth
        for path in self.flattened:
            tabbed = self.tabbed_for_path.get(path, None)
            if tabbed is not None:
                Cut2DWithTabs(machine_params, self.props, self.tool, path, tabbed).build(gcode)
            else:
                BaseCut2D(machine_params, self.props, self.tool, path).build(gcode)
    def tabs_width(self):
        return 1
    def to_preview(self):
        tab_depth = self.props.start_depth if self.props.tab_depth is None else self.props.tab_depth
        preview = []
        for path in self.flattened:
            tabbed = self.tabbed_for_path.get(path, None)
            if tabbed is not None:
                for i in tabbed:
                    preview.append((tab_depth if i.is_tab else self.props.depth, i))
            else:
                preview.append((self.props.depth, path))
        return preview
    def add_tabs_if_close(self, contours, tabs_dict, tabs, maxd):
        for i in contours.flattened():
            if i not in tabs_dict:
                # Filter by distance
                thistabs = []
                for t in tabs:
                    pos, dist = i.path.closest_point(t)
                    if dist < maxd:
                        thistabs.append(t)
                tabs_dict[i] = thistabs
    def calc_tabs(self, contours):
        newtabs = []
        if isinstance(self.tabs, int):
            for contour in contours:
                newtabs += contour.autotabs(self.tool, self.tabs, width=self.tabs_width())
        else:
            path = Path(self.shape.boundary, self.shape.closed)
            # Offset the tabs
            for pt in self.tabs:
                pos, dist = path.closest_point(pt)
                pt2 = path.offset_point(pos, self.tool.diameter / 2 * (1 if self.outside else -1))
                newtabs.append(pt2)
        return newtabs

class Contour(TabbedOperation):
    def __init__(self, shape, outside, tool, props, tabs, extra_width=0, trc_rate=0, entry_exit=None):
        assert shape.closed
        TabbedOperation.__init__(self, shape, tool, props, outside, tabs, { 'extra_width' : extra_width, 'trc_rate' : trc_rate, 'entry_exit' : entry_exit})
    def tabs_width(self):
        return self.tab_extend
    def build_paths(self, margin):
        trc_rate = self.trc_rate
        extra_width = self.extra_width
        tool = self.tool
        if trc_rate and extra_width:
            self.tab_extend = 8 * pi / (tool.diameter * trc_rate)
        else:
            self.tab_extend = 1
        if trc_rate and extra_width:
            contour_paths = cam.contour.pseudotrochoidal(self.shape, tool.diameter, self.outside, self.props.margin + margin, tool.climb, trc_rate * extra_width, 0.5 * extra_width)
            contours = toolpath.Toolpaths([toolpath.Toolpath(tp, tool, segmentation=segmentation) for tp, segmentation in contour_paths]).flattened() if contour_paths else []
        else:
            toolpaths = []
            contour_paths = cam.contour.plain(self.shape, tool.diameter, self.outside, self.props.margin + margin, tool.climb)
            for tp in contour_paths:
                tp = tp.interpolated()
                try_entry_paths = cam.contour.plain(shapes.Shape(tp.nodes, True), tool.min_helix_diameter, self.outside, self.props.margin + margin, tool.climb)
                he = None
                for tep in try_entry_paths:
                    pos, dist = tep.closest_point(tp.seg_start())
                    if dist <= tool.diameter * 0.708:
                        cp = tep.point_at(pos)
                        he = toolpath.HelicalEntry(cp, tool.min_helix_diameter / 2, cp.angle_to(tp.seg_start()))
                        break
                toolpaths.append(toolpath.Toolpath(tp, tool, helical_entry=he))
            contours = toolpath.Toolpaths(toolpaths).flattened() if contour_paths else []
        if not contours:
            return toolpath.Toolpaths(contours), {}
        tabs = self.calc_tabs(contours)
        tabs_dict = {}
        twins = {}
        if extra_width and not trc_rate:
            extra_width *= tool.diameter / 2
            widen_func = lambda contour: self.widen(contour, tool, extra_width)
            res = []
            for contour in contours:
                widened = toolpath.Toolpath(contour.path, tool, transform=widen_func).transformed()
                if isinstance(widened, toolpath.Toolpath):
                    moretabs = []
                    for pt in tabs:
                        pos, dist = contour.path.closest_point(pt)
                        if dist < tool.diameter * sqrt(2):
                            pt2 = contour.path.offset_point(pos, extra_width)
                            moretabs.append(pt)
                            moretabs.append(pt2)
                    tabs_dict[widened] = moretabs
                    res.append(widened)
                    twins[contour] = [widened]
                else:
                    widened = widened.flattened()
                    res += widened
                    twins[contour] = widened
            if not self.entry_exit:
                # For entry_exit, this is handled via twins
                contours = res
        if self.entry_exit:
            if extra_width and trc_rate:
                # This will require handling segmentation
                raise ValueError("Cannot use entry/exit with trochoidal paths yet")
            ee = self.entry_exit
            cut_contours = []
            for sp, ep in ee:
                path = contours[0]
                pos, min_dist = path.path.closest_point(sp)
                for j in contours[1:]:
                    pos, dist = j.path.closest_point(sp)
                    if dist < min_dist:
                        min_dist = dist
                        path = j
                path_and_twins = twins.get(path, [path])
                for path in path_and_twins:
                    orig_path = path.path
                    pos, dist = orig_path.closest_point(sp)
                    pos2, dist2 = orig_path.closest_point(ep)
                    if pos < pos2:
                        newpath = orig_path.subpath(pos, pos2)
                    else:
                        newpath = orig_path.subpath(pos, path.tlength).joined(orig_path.subpath(0, pos2))
                    newpath = Path([sp], False).joined(newpath).joined(Path([ep], False))
                    cut_contours.append(toolpath.Toolpath(newpath, path.tool))
            contours = cut_contours
        contours = toolpath.Toolpaths(contours)
        self.add_tabs_if_close(contours, tabs_dict, tabs, tool.diameter * sqrt(2))
        return contours, tabs_dict
    def operation_name(self):
        return "Contour/Outside" if self.outside else "Contour/Inside"
    def widen(self, contour, tool, extension):
        path = contour.path
        if not path.closed:
            return contour
        points = path.nodes
        if path.has_arcs():
            points = CircleFitter.interpolate_arcs(points, False, 1)
        offset = cam.contour.plain(shapes.Shape(points, True), 0, True, extension, not path.orientation())
        if not offset:
            raise ValueError("Empty contour")
        if len(offset) == 1:
            extension = toolpath.Toolpath(offset[0], tool)
            if toolpath.startWithClosestPoint(extension, points[0], tool.diameter):
                points = offset[0].nodes + points + points[0:1] + [offset[0].seg_start()]
                return toolpath.Toolpath(Path(points, True), tool)
        widened = []
        for ofs in offset:
            widened.append(toolpath.Toolpath(ofs, tool))
        widened.append(toolpath.Toolpath(contour.path, tool))
        return toolpath.Toolpaths(widened)

class TrochoidalContour(TabbedOperation):
    def __init__(self, shape, outside, tool, props, nrad, nspeed, tabs):
        TabbedOperation.__init__(self, shape, tool, props, outside, tabs, { 'nrad' : nrad * 0.5 * tool.diameter, 'nspeed' : nspeed})
    def build_paths(self, margin):
        nrad = self.nrad
        nspeed = self.nspeed
        contours = self.shape.contour(self.tool, outside=self.outside, displace=nrad + self.props.margin + margin)
        if not self.outside:
            nrad = -nrad
        trochoidal_func = lambda contour: shapes.trochoidal_transform(contour, nrad, nspeed)
        newtabs = self.calc_tabs(contours)
        contours = toolpath.Toolpaths([toolpath.Toolpath(tp.path, tool, transform=trochoidal_func) for tp in contours.toolpaths])
        return contours, self.nrad, {}
    def tabs_width(self):
        # This needs tweaking
        return 1 + self.nrad

class ContourWithDraft(TabbedOperation):
    def __init__(self, shape, outside, tool, props, draft_angle_deg, layer_thickness):
        TabbedOperation.__init__(self, shape, tool, props, outside, 0, {'draft_angle_deg' : draft_angle_deg, 'layer_thickness' : layer_thickness})
    def build_paths(self, margin):
        contour_paths = cam.contour.plain(self.shape, self.tool.diameter, self.outside, self.props.margin + margin, self.tool.climb)
        contours = toolpath.Toolpaths([toolpath.Toolpath(tp, self.tool) for tp in contour_paths])
        tabs = self.calc_tabs(contours.toolpaths)
        tabs_dict = {}
        self.add_tabs_if_close(contours, tabs_dict, tabs, self.tool.diameter * sqrt(2))
        return contours, tabs_dict
    def to_gcode(self, gcode, machine_params):
        Cut2DWithDraft(machine_params, self.props, self.tool, self.shape, self.build_paths, self.outline, self.outside, self.draft_angle_deg, self.layer_thickness).build(gcode)

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

class PeckDrill(UntabbedOperation):
    def __init__(self, x, y, tool, props, dwell_bottom=0, dwell_retract=0, retract=None, slow_retract=False):
        shape = shapes.Shape.circle(x, y, r=0.5 * tool.diameter)
        self.x = x
        self.y = y
        UntabbedOperation.__init__(self, shape, tool, props)
        self.dwell_bottom = dwell_bottom
        self.dwell_retract = dwell_retract
        self.retract = retract or RetractToSemiSafe()
        self.slow_retract = slow_retract
    def build_paths(self, margin):
        return toolpath.Toolpath(Path([PathPoint(self.x, self.y)], True), self.tool)
    def to_gcode(self, gcode, machine_params):
        gcode.rapid(x=self.x, y=self.y)
        gcode.rapid(z=machine_params.semi_safe_z)
        gcode.feed(self.tool.vfeed)
        curz = self.props.start_depth
        doc = self.tool.maxdoc
        while curz > self.props.depth:
            nextz = max(curz - doc, self.props.depth)
            gcode.linear(z=nextz)
            if self.dwell_bottom:
                gcode.dwell(self.dwell_bottom)
            retrz = self.retract.get(nextz, self.props, machine_params.semi_safe_z)
            if self.slow_retract:
                gcode.linear(z=retrz)
            else:
                gcode.rapid(z=retrz)
            if self.dwell_retract:
                gcode.dwell(self.dwell_retract)
            curz = nextz
        gcode.rapid(z=machine_params.safe_z)

class HelicalDrill(UntabbedOperation):
    def __init__(self, x, y, d, tool, props):
        d -= props.margin
        self.min_dia = tool.diameter + tool.min_helix_diameter
        if d < self.min_dia:
            raise ValueError("Diameter %0.3f smaller than the minimum %0.3f" % (d, self.min_dia))
        self.x = x
        self.y = y
        self.d = d
        self.tool = tool
        shape = shapes.Shape.circle(x, y, r=0.5*self.d)
        UntabbedOperation.__init__(self, shape, tool, props)
    def build_paths(self, margin):
        coords = []
        for cd in self.diameters():
            coords += shapes.Shape.circle(self.x, self.y, r=0.5*(cd - self.tool.diameter)).boundary
        return toolpath.Toolpaths([toolpath.Toolpath(Path(coords, False), self.tool)])
    def diameters(self):
        if self.d < self.min_dia:
            return [self.d]
        else:
            dias = []
            d = self.min_dia
            step = self.tool.diameter * self.tool.stepover
            # XXXKF adjust stepover to make the last pass same as the previous ones
            while d < self.d:
                dias.append(d)
                d += step
            # If the last diameter is very close to the final diameter, just replace it with
            # final diameter instead of making the last pass nearly a spring pass. Now, a spring
            # pass or a finishing pass would be a nice feature to have, but done in a predictable
            # manner and not for some specific diameters and not others.
            if len(dias) and dias[-1] > self.d - self.tool.diameter * self.tool.stepover / 10:
                dias[-1] = self.d
            else:
                dias.append(self.d)
            return dias

    def to_gcode(self, gcode, machine_params):
        rate_factor = self.tool.full_plunge_feed_ratio
        gcode.section_info(f"Start helical drill at {self.x:0.2f}, {self.y:0.2f} diameter {self.d:0.2f} depth {self.props.depth:0.2f}")
        first = True
        for d in self.diameters():
            self.to_gcode_ring(gcode, d, rate_factor if first else 1, machine_params, first)
            first = False
        gcode.feed(self.tool.hfeed)
        # Do not rub against the walls
        gcode.section_info(f"Diagonal exit towards centre/safe Z")
        gcode.rapid(x=self.x, y=self.y, z=machine_params.safe_z)
        gcode.section_info(f"End helical drill")

    def to_gcode_ring(self, gcode, d, rate_factor, machine_params, first):
        r = max(self.tool.diameter * self.tool.stepover / 2, (d - self.tool.diameter) / 2)
        gcode.section_info("Start ring at %0.2f, %0.2f diameter %0.2f overall diameter %0.2f" % (self.x, self.y, 2 * r, 2 * r + self.tool.diameter))
        curz = machine_params.semi_safe_z + self.props.start_depth
        gcode.rapid(z=machine_params.safe_z if first else curz)
        gcode.rapid(x=self.x + r, y=self.y)
        gcode.rapid(z=curz)
        gcode.feed(self.tool.hfeed * rate_factor)
        dist = 2 * pi * r
        doc = min(self.tool.maxdoc, dist / self.tool.slope())
        while curz > self.props.depth:
            nextz = max(curz - doc, self.props.depth)
            gcode.helix_turn(self.x, self.y, r, curz, nextz)
            curz = nextz
        gcode.helix_turn(self.x, self.y, r, curz, curz)
        gcode.section_info("End ring")

# First make a helical entry and then enlarge to the target diameter
# by side milling
class HelicalDrillFullDepth(HelicalDrill):
    def to_gcode(self, gcode, machine_params):
        # Do the first pass at a slower rate because of full radial engagement downwards
        rate_factor = self.tool.full_plunge_feed_ratio
        if self.d < self.min_dia:
            self.to_gcode_ring(gcode, self.d, rate_factor, machine_params, True)
        else:
            # Mill initial hole by helical descent into desired depth
            d = self.min_dia
            self.to_gcode_ring(gcode, d, rate_factor, machine_params, True)
            gcode.feed(self.tool.hfeed)
            # Bore it out at full depth to the final diameter
            while d < self.d:
                r = max(self.tool.diameter * self.tool.stepover / 2, (d - self.tool.diameter) / 2)
                gcode.linear(x=self.x + r, y=self.y)
                gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth, False)
                d += self.tool.diameter * self.tool.stepover_fulldepth
            r = max(0, (self.d - self.tool.diameter) / 2)
            gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth, False)
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
    def add_all(self, operations):
        self.operations += operations
    def is_nothing(self):
        for i in self.operations:
            if i.flattened:
                return False
        return True
    def contour_with_draft(self, shape, outside, draft_angle_deg, layer_thickness, tabs, props=None):
        props = props or self.props
        if tabs:
            draft = tan(draft_angle_deg * pi / 180)
            draft_height = props.start_depth - props.tab_depth
            self.add(ContourWithDraft(shape, outside, self.tool, props.clone(depth=props.tab_depth), draft_angle_deg, layer_thickness))
            if props.depth < props.tab_depth:
                self.add(Contour(shape, outside, self.tool, props.clone(start_depth=props.tab_depth, margin=draft * draft_height), tabs=tabs))
        else:
            self.add(ContourWithDraft(shape, outside, self.tool, props, draft_angle_deg, layer_thickness))
    def outside_contour(self, shape, tabs, widen=0, props=None, entry_exit=None):
        if shape.islands:
            for i in shape.islands:
                self.add(Contour(shapes.Shape(i, True), False, self.tool, props or self.props, tabs=0, extra_width=widen))
        self.add(Contour(shape, True, self.tool, props or self.props, tabs=tabs, extra_width=widen, entry_exit=entry_exit))
    def outside_contour_trochoidal(self, shape, nrad, nspeed, tabs, props=None, entry_exit=None):
        if shape.islands:
            for i in shape.islands:
                self.add(Contour(shapes.Shape(i, True), False, self.tool, props or self.props, tabs=tabs, extra_width=nrad, trc_rate=nspeed))
        #self.add(TrochoidalContour(shape, True, self.tool, props or self.props, nrad=nrad, nspeed=nspeed, tabs=tabs))
        self.add(Contour(shape, True, self.tool, props or self.props, tabs=tabs, extra_width=nrad, trc_rate=nspeed, entry_exit=entry_exit))
    def outside_contour_with_draft(self, shape, draft_angle_deg, layer_thickness, tabs, props=None):
        self.contour_with_draft(shape, True, draft_angle_deg, layer_thickness, tabs, props)
    def inside_contour(self, shape, tabs, widen=0, props=None, entry_exit=None):
        self.add(Contour(shape, False, self.tool, props or self.props, tabs=tabs, extra_width=-widen, entry_exit=entry_exit))
    def inside_contour_trochoidal(self, shape, nrad, nspeed, tabs, props=None, entry_exit=None):
        #self.add(TrochoidalContour(shape, False, self.tool, props or self.props, nrad=nrad, nspeed=nspeed, tabs=tabs))
        self.add(Contour(shape, False, self.tool, props or self.props, tabs=tabs, extra_width=nrad, trc_rate=nspeed, entry_exit=entry_exit))
    def inside_contour_with_draft(self, shape, draft_angle_deg, layer_thickness, tabs, props=None):
        self.contour_with_draft(shape, False, draft_angle_deg, layer_thickness, tabs, props)
    def engrave(self, shape, props=None):
        self.add(Engrave(shape, self.tool, props or self.props))
    def pocket(self, shape, props=None):
        self.add(Pocket(shape, self.tool, props or self.props))
    def pocket_hsm(self, shape, props=None, shape_to_refine=None):
        self.add(HSMPocket(shape, self.tool, props or self.props, shape_to_refine))
    def pocket_with_draft(self, shape, draft_angle_deg, layer_thickness, props=None):
        self.add(PocketWithDraft(shape, self.tool, props or self.props, draft_angle_deg, layer_thickness))
    def outside_peel(self, shape, props=None):
        self.add(OutsidePeel(shape, self.tool, props or self.props))
    def outside_peel_hsm(self, shape, props=None, shape_to_refine=None):
        self.add(OutsidePeelHSM(shape, self.tool, props or self.props, shape_to_refine))
    def face_mill(self, shape, props=None):
        self.add(FaceMill(shape, self.tool, props or self.props))
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
            gcode.section_info(f"Start operation: {type(operation).__name__}")
            gcode.begin_section(operation.rpm)
            operation.to_gcode(gcode, self.machine_params)
            gcode.section_info(f"End operation: {type(operation).__name__}")
        gcode.rapid(x=0, y=0)
        gcode.finish()
        return gcode
    def to_gcode_file(self, filename):
        glines = self.to_gcode().gcode
        f = open(filename, "w")
        for line in glines:
          f.write(line + '\n')
        f.close()
