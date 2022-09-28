import threading
from DerpCAM.common.geom import *
from DerpCAM import cam
import DerpCAM.cam.contour
import DerpCAM.cam.peel
import DerpCAM.cam.pocket
from DerpCAM.cam.wall_profile import PlainWallProfile

from DerpCAM.cam import shapes, toolpath

# VERY experimental feature
debug_simplify_arcs = False
debug_ramp = False
debug_tabs = False
debug_sections = True

class OperationProps(object):
    def __init__(self, depth, start_depth=0, tab_depth=None, margin=0, zigzag=False, angle=0, roughing_offset=0, allow_helical_entry=True, wall_profile=None, sublayer_thickness=0.1, offset_tolerance=0.2):
        self.depth = depth
        self.start_depth = start_depth
        self.tab_depth = tab_depth
        self.margin = margin
        self.roughing_offset = roughing_offset
        self.zigzag = zigzag
        self.angle = angle
        self.rpm = None
        self.allow_helical_entry = allow_helical_entry
        self.wall_profile = wall_profile or PlainWallProfile()
        self.sublayer_thickness = sublayer_thickness
        self.offset_tolerance = offset_tolerance
    def clone(self, **attrs):
        res = OperationProps(self.depth, self.start_depth, self.tab_depth, self.margin, self.zigzag, self.angle, self.roughing_offset, self.allow_helical_entry, self.wall_profile, self.sublayer_thickness, self.offset_tolerance)
        for k, v in attrs.items():
            assert hasattr(res, k), "Unknown attribute %s" % k
            setattr(res, k, v)
        return res
    def with_finish_pass(self, margin=0, vmargin=0.1):
        return self.clone(start_depth=min(self.start_depth, self.depth - vmargin), margin=margin)
    def actual_tab_depth(self):
        return self.tab_depth if self.tab_depth is not None else self.depth

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

    def apply_subpath(self, subpath, lastpt, new_z=None, old_z=None, tlength=None, subject=None):
        self.section_info("Start subpath" if not subject else f"Start {subject} subpath")
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
                    if not GeometrySettings.paranoid_mode and pt.speed_hint is toolpath.RapidMove:
                        self.rapid(x=pt.x, y=pt.y)
                    else:
                        self.linear(x=pt.x, y=pt.y)
        lastpt = pt.seg_end()
        self.section_info("End subpath" if not subject else f"End {subject} subpath")
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
        self.section_info(f"Start helical move from {old_z:0.3f} to {new_z:0.3f}")
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
        self.section_info(f"Start ramped move from {old_z:0.3f} to {new_z:0.3f}")
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
                lastpt = self.apply_subpath(subpath, lastpt, cur_z + dz * 0.5, cur_z, tlengths[-1], subject="ramp")
                lastpt = self.apply_subpath(subpath_reverse, lastpt, cur_z + dz, cur_z + dz * 0.5, tlengths[-1], subject="ramp")
                cur_z = next_z
            else:
                # This is one of the possible strategies: ramp at an angle, then
                # come back straight. This is not ideal, especially for the non-centre
                # cutting tools.
                lastpt = self.apply_subpath(subpath, lastpt, next_z, cur_z, tlengths[-1], subject="ramp-in")
                cur_z = next_z
                lastpt = self.apply_subpath(subpath_reverse, lastpt, subject="ramp-back")
        self.section_info(f"End ramped move - upward direction detected")
        self.feed(tool.hfeed)
        return lastpt

class MachineParams(object):
    def __init__(self, safe_z, semi_safe_z, min_rpm=None, max_rpm=None):
        self.safe_z = safe_z
        self.semi_safe_z = semi_safe_z
        self.min_rpm = min_rpm
        self.max_rpm = max_rpm
        self.over_tab_safety = 0.2

# 2D model, from inputs to outputs:
#
# OffsetRange is a range of offset (margin) values for a certain depth.
#
# LayerInfo describes a single Z-axis slice, either primary (rough cut)
# or secondary (sublayers, used for wall profiles - a rough cut is refined using
# a series of finer passes that progress upwards by a small amount until the
# previous primary layer and extend the cut according to the wall profile,
# this is faster than achieving the same outcome using full primary layers,
# especially for wide pockets - the only part cut in secondary layers is the
# outside)
#
# BaseCutPath derived classes store the toolpath(s) to be used for the entire
# depth. This can be the basic toolpath for untabbed cuts, or basic toolpath
# and tab related variants for tabbed cuts.
#
# CutLayer2D is a single uninterrupted toolpath instance (tabbed or not) at a
# certain depth. It is produced by CutPath classes based on the shape
# provided from outside, series of LayerInfo objects and optionally OffsetRange
# when CutPathWallProfile is used. CalculatedSubpaths is the intermediate
# stage.

class CutLayer2D(object):
    def __init__(self, prev_depth, depth, subpaths, force_join=False, helical_from_top=False):
        self.prev_depth = prev_depth
        self.depth = depth
        self.subpaths = subpaths
        self.force_join = force_join
        self.helical_from_top = helical_from_top
        self.bounds = toolpath.Toolpaths(self.subpaths).bounds
        self.parent = None
        self.children = []
        self.linked = []
        if subpaths and subpaths[0]:
            lastpt = subpaths[0].path.seg_start()
            for i in subpaths:
                assert i.path.seg_start().dist(lastpt) < 1e-6
                lastpt = i.path.seg_end()
    def overlaps(self, another):
        return bounds_overlap(self.bounds, another.bounds)

class OffsetRange(object):
    def __init__(self, start_offset, end_offset, increment):
        assert start_offset <= end_offset
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.increment = increment
    def values(self):
        res = []
        i = self.start_offset
        while i < self.end_offset:
            res.append(i)
            i += self.increment
        res.append(self.end_offset)
        return res

class LayerInfo(object):
    TAB_ABOVE = 0
    TAB_FIRST = 1
    TAB_BELOW = 2
    def __init__(self, prev_depth, depth, offsets, is_sublayer, tab_status):
        self.prev_depth = prev_depth
        self.depth = depth
        self.offsets = offsets
        self.is_sublayer = is_sublayer
        self.tab_status = tab_status

class LayerSchedule(object):
    def __init__(self, machine_params, props, tool, has_tabs):
        self.machine_params = machine_params
        self.props = props
        self.tool = tool
        self.has_tabs = has_tabs
    def depth_of_cut(self, depth):
        # Axial engagement
        # XXXKF add provisions for finish passes here
        return self.tool.maxdoc
    def next_depth(self, prev_depth):
        if prev_depth <= self.props.depth:
            return None
        depth_of_cut = self.depth_of_cut(prev_depth)
        new_depth = max(self.props.depth, prev_depth - depth_of_cut)
        tab_depth = self.props.actual_tab_depth()
        return round(new_depth, 3)
    def major_layer_list(self):
        # Start by rough milling from the top down
        layers = []
        prev_depth = self.props.start_depth
        total_depth = self.props.start_depth - self.props.depth
        layer_start_offset = self.props.wall_profile.offset_at_depth(0, total_depth)
        end_offset = self.props.wall_profile.offset_at_depth(total_depth, total_depth)
        stepover = self.tool.stepover * self.tool.diameter
        while True:
            depth = self.next_depth(prev_depth)
            if depth is None:
                break
            layer_end_offset = self.props.wall_profile.offset_at_depth(self.props.start_depth - depth, total_depth)
            layer = self.layer_info(prev_depth, depth, OffsetRange(layer_end_offset, end_offset, stepover), False)
            layers.append(layer)
            if layer_end_offset < layer_start_offset:
                raise ValueError("Wall profile undercuts are not permitted")
            prev_depth = depth
            layer_start_offset = layer_end_offset
        depth = self.props.depth
        # Refine from the bottom up
        sublayers = []
        for layer in layers[::-1]:
            depth = round(layer.depth + self.props.sublayer_thickness, 3)
            prev_depth = layer.prev_depth
            layer_start_offset = self.props.wall_profile.offset_at_depth(self.props.start_depth - prev_depth, total_depth)
            if depth < prev_depth and layer_start_offset < layer_end_offset:
                sublayer_end_offset = layer_end_offset
                sublayer_start = round(depth + self.props.sublayer_thickness, 3)
                sublayer_end = depth
                while sublayer_end < prev_depth:
                    sublayer_start_offset = self.props.wall_profile.offset_at_depth(self.props.start_depth - sublayer_end, total_depth)
                    if sublayer_start_offset < sublayer_end_offset - self.props.offset_tolerance:
                        offsets = OffsetRange(sublayer_start_offset, max(sublayer_end_offset - stepover, sublayer_start_offset), stepover)
                        sublayers.append(self.layer_info(sublayer_start, sublayer_end, offsets, True))
                        sublayer_end_offset = sublayer_start_offset
                    sublayer_end = sublayer_start
                    sublayer_start = min(prev_depth, round(sublayer_end + self.props.sublayer_thickness, 3))
            layer_end_offset = layer_start_offset
        layers += sublayers
        return layers
    def layer_info(self, top, bottom, offsets, is_subpath):
        return LayerInfo(top, bottom, offsets, is_subpath, self.tab_status(top, bottom, is_subpath))
    def tab_status(self, prev_depth, depth, is_subpath):
        tab_depth = self.props.actual_tab_depth()
        if not self.has_tabs or depth >= tab_depth:
            return LayerInfo.TAB_ABOVE
        if not is_subpath and depth < tab_depth and prev_depth >= tab_depth:
            return LayerInfo.TAB_FIRST
        return LayerInfo.TAB_BELOW

class CutLayerTree(object):
    def __init__(self):
        self.roots = []
        self.last_layer = []
        self.this_layer = []
    def add(self, cutlayer):
        for i in self.this_layer:
            if i.overlaps(cutlayer):
                i.linked.append(cutlayer)
                i.bounds = max_bounds(i.bounds, cutlayer.bounds)
                #cutlayer.force_join = True # XXXKF must at least verify the "inside shape" condition
                return
        else:
            self.this_layer.append(cutlayer)
        for i in self.last_layer:
            if i.bounds == cutlayer.bounds:
                cutlayer.parent = i
                i.children.append(cutlayer)
                return
        for i in self.last_layer:
            if i.overlaps(cutlayer):
                cutlayer.parent = i
                i.children.append(cutlayer)
                return
    def finish_level(self):
        self.last_layer = self.this_layer
        self.this_layer = []
        if not self.roots:
            self.roots = self.last_layer
    def flatten(self):
        # self.dump()
        return sum([self.flatten_from(i) for i in self.roots], [])
    def flatten_from(self, cutlayer):
        return sum([self.flatten_from(i) for i in cutlayer.children], cutlayer.linked + [cutlayer])
    def dump(self):
        print ("---")
        for i in self.roots:
            self.dump_from(i, 0)
        print ("---")
    def dump_from(self, parent, level):
        print (f"{'   ' * level}{parent.bounds} at {parent.depth}")
        for i in parent.children:
            self.dump_from(i, level + 1)

class BaseCutPath(object):
    def __init__(self, machine_params, props, tool, helical_entry_func):
        self.machine_params = machine_params
        self.props = props
        self.tool = tool
        self.helical_entry_func = helical_entry_func
        self.over_tab_z = self.props.actual_tab_depth() + machine_params.over_tab_safety
    def generate_preview(self, subpaths):
        for subpath in subpaths:
            if is_calculation_cancelled():
                return
            subpath.rendered_outlines = subpath.render_as_outlines()
    def to_layers(self):
        layer_schedule = LayerSchedule(self.machine_params, self.props, self.tool, True).major_layer_list()
        layer_tree = CutLayerTree()
        last_depth = None
        for layer in layer_schedule:
            if layer.depth != last_depth:
                if last_depth is not None:
                    layer_tree.finish_level()
                last_depth = layer.depth
            for cutlayer in self.cutlayers_for_layer(layer):
                layer_tree.add(cutlayer)
        if last_depth is not None:
            layer_tree.finish_level()
        return layer_tree.flatten()
    def cutlayers_for_layer(self, layer):
        return [CutLayer2D(layer.prev_depth, layer.depth, self.subpaths_for_layer(layer))]
    def z_already_cut_here(self, layer, subpath):
        return max(self.props.actual_tab_depth(), layer.prev_depth) if subpath.is_tab else layer.prev_depth
    def z_to_be_cut(self, layer, subpath):
        if not subpath.is_tab:
            return layer.depth
        # First cut of the tab should be at exact tab depth, the next ones can be at
        # over_tab_z because the tab is already cut and there's no point in rubbing the
        # cutter against the bottom of the cut.
        tab_depth = self.props.actual_tab_depth()
        return self.over_tab_z if layer.prev_depth < tab_depth else tab_depth
    def adjust_helical_entry(self, subpaths):
        allow_helical_entry = self.props.allow_helical_entry
        for tp in subpaths:
            if allow_helical_entry and tp.helical_entry is None and self.helical_entry_func is not None:
                tp.helical_entry = self.helical_entry_func(tp.path)
            if not allow_helical_entry and tp.helical_entry is not None:
                tp.helical_entry = None

# Simple 2D case, just follow the same toolpath level after level.
class CutPath2D(BaseCutPath):
    def __init__(self, machine_params, props, tool, helical_entry_func, path):
        BaseCutPath.__init__(self, machine_params, props, tool, helical_entry_func)
        self.subpaths_full = [path.transformed()]
        self.adjust_helical_entry(self.subpaths_full)
        self.generate_preview(self.subpaths_full)
        self.cut_layers = self.to_layers()
    def subpaths_for_layer(self, layer):
        return self.subpaths_full
    def to_preview(self):
        preview = []
        for i in self.subpaths_full:
            preview.append((self.props.depth, i))
        return preview

class CalculatedSubpaths(object):
    def __init__(self, subpaths, max_depth):
        self.subpaths = subpaths
        self.max_depth = max_depth

# Single toolpath + variable margin, Z dependent
class CutPathWallProfile(BaseCutPath):
    def __init__(self, machine_params, props, tool, helical_entry_func, build_layer_func, is_pocket):
        BaseCutPath.__init__(self, machine_params, props, tool, helical_entry_func)
        self.build_layer_func = build_layer_func
        self.is_pocket = is_pocket
        self.calculated_layers = {}
        self.requested_layers = set()
        self.cut_layers = self.to_layers()
    def cutlayers_for_layer(self, layer):
        return self.cutlayers_for_sublayer(layer)
    def cutlayers_for_sublayer(self, layer):
        if self.is_pocket and not layer.is_sublayer:
            # Use pocket logic for the entire thing
            return self.cutlayers_for_margin(layer, layer.offsets.start_offset)
        else:
            cutlayers = []
            for offset in layer.offsets.values():
                cutlayers += self.cutlayers_for_margin(layer, offset)
            return cutlayers
    def cutlayers_for_margin(self, layer, margin):
        key = (margin, layer.is_sublayer, layer.tab_status)
        layer_depth = layer.depth
        csubpaths = self.calculated_layers.get(key)
        if csubpaths is not None:
            if layer_depth < csubpaths.max_depth:
                csubpaths.max_depth = layer_depth
            subpaths = csubpaths.subpaths
        else:
            # Continuous (non-tab) version first, need it for everything else
            key2 = (margin, layer.is_sublayer, LayerInfo.TAB_ABOVE)
            csubpaths = self.calculated_layers.get(key2)
            if csubpaths is None:
                path_output = self.build_layer_func(margin, layer.is_sublayer)
                if path_output is None:
                    subpaths = []
                else:
                    assert isinstance(path_output, PathOutput)
                    subpaths = [path.optimize() for path in path_output.paths]
                    self.adjust_helical_entry(subpaths)
                self.generate_preview(subpaths)
                csubpaths = CalculatedSubpaths(subpaths, layer.depth)
                self.calculated_layers[key2] = csubpaths
            else:
                subpaths = csubpaths.subpaths
            if key2 != key:
                # Split by tabs but without "untrochoidifying" yet
                key3 = (margin, layer.is_sublayer, LayerInfo.TAB_FIRST)
                csubpaths = self.calculated_layers.get(key3)
                if csubpaths is None:
                    subpaths = [subpath.tabify(self) for subpath in subpaths]
                    csubpaths = CalculatedSubpaths(subpaths, layer.depth)
                    self.calculated_layers[key3] = csubpaths
                else:
                    subpaths = csubpaths.subpaths
                if key3 != key:
                    # Untrochoidify if needed
                    assert layer.tab_status == LayerInfo.TAB_BELOW
                    subpaths = [subpath.untrochoidify() for subpath in subpaths]
                    csubpaths = CalculatedSubpaths(subpaths, layer.depth)
                    self.calculated_layers[key] = csubpaths
        self.requested_layers.add(csubpaths)
        res = []
        if subpaths:
            for subpath in subpaths:
                if isinstance(subpath, toolpath.Toolpath):
                    # Single contour
                    res.append(CutLayer2D(layer.prev_depth, layer.depth, [subpath]))
                elif isinstance(subpath, toolpath.Toolpaths):
                    # Single contour but split into tabs
                    res.append(CutLayer2D(layer.prev_depth, layer.depth, subpath.flattened()))
                else:
                    assert False
        return res
    def to_preview(self):
        preview = []
        for cs in self.requested_layers:
            for sp in cs.subpaths:
                if isinstance(sp, toolpath.Toolpath):
                    preview.append((self.props.actual_tab_depth() if sp.is_tab else cs.max_depth, sp))
                elif isinstance(sp, toolpath.Toolpaths):
                    for i in sp.toolpaths:
                        preview.append((self.props.actual_tab_depth() if i.is_tab else cs.max_depth, i))
                else:
                    assert False
        return preview

class PathOutput(object):
    def __init__(self, paths, paths_for_helical_entry):
        self.paths = paths
        self.paths_for_helical_entry = paths_for_helical_entry

class BaseCut(object):
    def __init__(self, machine_params, props, tool):
        self.machine_params = machine_params
        self.props = props
        self.tool = tool

# Simple tabbed 2D toolpath
class BaseCut2D(BaseCut):
    def __init__(self, machine_params, props, tool, cutpaths):
        BaseCut.__init__(self, machine_params, props, tool)
        self.cutpaths = cutpaths

    def build(self, gcode):
        for cutpath in self.cutpaths:
            self.build_cutpath(gcode, cutpath)

    def build_cutpath(self, gcode, cutpath):
        self.start_cutpath(gcode, cutpath)
        for layer in self.layers_for_cutpath(cutpath):
            self.build_layer(gcode, cutpath, layer)
        self.end_cutpath(gcode, cutpath)

    def layers_for_cutpath(self, cutpath):
        return cutpath.cut_layers

    def build_layer(self, gcode, cutpath, layer):
        subpaths = layer.subpaths
        assert subpaths
        self.start_layer(gcode, layer)
        for subpath in subpaths:
            self.build_subpath(gcode, cutpath, layer, subpath)

    def start_layer(self, gcode, layer):
        subpaths = layer.subpaths
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
                gcode.rapid(x=firstpt.x, y=firstpt.y)
        else:
            # Minor discrepancies might lead to problems with arcs etc. so fix them
            # by adding a simple line segment.
            if dist(self.lastpt, firstpt) >= 1e-6:
                gcode.linear(x=firstpt.x, y=firstpt.y)
        self.lastpt = firstpt

    def start_subpath(self, subpath):
        pass

    def end_subpath(self, subpath):
        pass

    def build_subpath(self, gcode, cutpath, layer, subpath):
        if subpath.path.length() < 0.001:
            return
        # This will always be false for subpaths_full.
        newz = cutpath.z_to_be_cut(layer, subpath)
        self.start_subpath(subpath)
        self.enter_or_leave_cut(gcode, cutpath, layer, subpath, newz)
        assert self.lastpt is not None
        assert isinstance(self.lastpt, PathPoint)
        self.lastpt = gcode.apply_subpath(subpath.path, self.lastpt, subject="tab" if subpath.is_tab else None)
        assert isinstance(self.lastpt, PathNode)
        self.end_subpath(subpath)

    def enter_or_leave_cut(self, gcode, cutpath, layer, subpath, newz):
        if newz != self.curz:
            if newz < self.curz:
                self.enter_cut(gcode, cutpath, layer, subpath, newz)
            else:
                # Leave a cut, always uses a rapid move
                gcode.move_z(newz, self.curz, subpath.tool, self.machine_params.semi_safe_z)
                self.curz = newz

    def enter_cut(self, gcode, cutpath, layer, subpath, newz):
        # Z slightly above the previous cuts. There will be no ramping or helical
        # entry above that, just a straight plunge. However, the speed of the
        # plunge will be dependent on whether a ramped or helical entry is used
        # for the rest of the descent. In case of ramped entry, we go slow, at
        # plunge feed rate. For helical entry, there is already a hole milled
        # up to prev_depth, so we can descend faster, at horizontal feed rate.

        # For tabs, do not consider anything lower than tab_depth as milled, because
        # it is not, as there is a tab there!
        gcode.section_info(f"Start enter cut at {newz:0.3f}")
        if isinstance(subpath.helical_entry, toolpath.PlungeEntry) and not GeometrySettings.paranoid_mode:
            assert subpath.was_previously_cut
            plunge_entry = subpath.helical_entry
            self.lastpt = plunge_entry.start
            gcode.rapid(z=newz)
            gcode.feed(subpath.tool.hfeed)
        else:
            z_already_cut_here = cutpath.z_already_cut_here(layer, subpath)
            if z_already_cut_here >= self.props.start_depth - 0.001:
                # Haven't cut anything yet - be more cautious to avoid crashing
                # into surface of the uncut stuck if it's crooked etc.
                z_above_cut = self.machine_params.semi_safe_z
            else:
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
            speed_ratio *= subpath.tool.diagonal_factor()
            gcode.feed(subpath.tool.hfeed * speed_ratio)
            if isinstance(subpath.helical_entry, toolpath.HelicalEntry):
                # Descend helically to the indicated helical entry point
                # If first layer with tabs, do all helical ramps for post-tab
                # reentry from the very top, because they haven't been cut yet
                curz = self.curz
                if subpath.helical_from_top:
                    curz = max(curz, self.props.start_depth)
                self.lastpt = gcode.helical_move_z(newz, curz, subpath.helical_entry, subpath.tool, self.machine_params.semi_safe_z, z_above_cut)
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

class Operation(object):
    def __init__(self, shape, tool, machine_params, props):
        self.shape = shape
        self.tool = tool
        self.machine_params = machine_params
        self.props = props
        self.rpm = props.rpm if props is not None else None
        self.cutpaths = []
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
    def to_gcode(self, gcode):
        BaseCut2D(self.machine_params, self.props, self.tool, self.cutpaths).build(gcode)
    def to_preview(self):
        return sum([path.to_preview() for path in self.cutpaths], [])
    def helical_entry(self, tp, paths_for_helical_entry):
        if not self.props.allow_helical_entry:
            return
        mindist = self.tool.diameter * 0.708
        cp = None
        for tep in paths_for_helical_entry:
            pos, dist = tep.closest_point(tp.seg_start())
            if dist <= mindist:
                mindist = dist
                cp = tep.point_at(pos)
        if cp is not None:
            return toolpath.HelicalEntry(cp, self.tool.min_helix_diameter / 2, cp.angle_to(tp.seg_start()))
        return None

class ToolChangeOperation(Operation):
    def __init__(self, cutter, machine_params):
        Operation.__init__(self, None, None, machine_params, None)
        self.cutter = cutter
    def to_text(self):
        return "Tool change: " + self.cutter.name
    def to_preview(self):
        return []
    def to_gcode(self, gcode):
        gcode.prompt_for_tool(self.cutter.name)

class UntabbedOperation(Operation):
    def __init__(self, shape, tool, machine_params, props, extra_attribs={}):
        Operation.__init__(self, shape, tool, machine_params, props)
        for key, value in extra_attribs.items():
            setattr(self, key, value)
        self.cutpaths = self.build_cutpaths()
    def build_cutpaths(self):
        return self.build_cutpaths_for_margin(0, self.props)
    def build_cutpaths_for_margin(self, margin, props):
        path_output = self.build_paths(margin)
        if not path_output:
            return []
        assert isinstance(path_output, PathOutput)
        return [CutPath2D(self.machine_params, props, self.tool, None, path.optimize()) for path in path_output.paths]

class Engrave(UntabbedOperation):
    def build_paths(self, margin):
        if margin != 0:
            raise ValueError("Offset not supported for engraving")
        return PathOutput(self.shape.engrave(self.tool, self.props.margin).flattened(), None)

class FaceMill(UntabbedOperation):
    def build_paths(self, margin):
        return PathOutput(cam.pocket.axis_parallel(self.shape, self.tool, self.props.angle, self.props.margin + margin, self.props.zigzag, roughing_offset=self.props.roughing_offset).flattened(), None)

class Pocket(UntabbedOperation):
    def build_cutpaths(self):
        return [CutPathWallProfile(self.machine_params, self.props, self.tool, None, self.subpaths_for_margin, True)]
    def build_paths(self, margin):
        return PathOutput(cam.pocket.contour_parallel(self.shape, self.tool, displace=self.props.margin + margin, roughing_offset=self.props.roughing_offset).flattened(), None)
    def subpaths_for_margin(self, margin, is_sublayer):
        if is_sublayer:
            # Edges only (this is used for refining the wall profile after a roughing pass)
            paths = []
            for i in self.shape.islands:
                paths += cam.contour.plain(shapes.Shape(i, True), self.tool.diameter, True, self.props.margin + margin, self.tool.climb)
            paths += cam.contour.plain(self.shape, self.tool.diameter, False, self.props.margin + margin, self.tool.climb)
            return PathOutput([toolpath.Toolpath(path, self.tool) for path in paths], None)
        else:
            # Full pocket (roughing pass)
            return self.build_paths(margin)

class HSMOperation(UntabbedOperation):
    def __init__(self, shape, tool, machine_params, props, shape_to_refine):
        UntabbedOperation.__init__(self, shape, tool, machine_params, props, extra_attribs={ 'shape_to_refine' : shape_to_refine })

class HSMPocket(HSMOperation):
    def build_paths(self, margin):
        return PathOutput(cam.pocket.hsm_peel(self.shape, self.tool, self.props.zigzag, displace=self.props.margin + margin, shape_to_refine=self.shape_to_refine, roughing_offset=self.props.roughing_offset).flattened(), None)

class OutsidePeel(UntabbedOperation):
    def build_paths(self, margin):
        return PathOutput(cam.peel.outside_peel(self.shape, self.tool, displace=self.props.margin + margin).flattened(), None)

class OutsidePeelHSM(HSMOperation):
    def build_paths(self, margin):
        return PathOutput(cam.peel.outside_peel_hsm(self.shape, self.tool, zigzag=self.props.zigzag, displace=self.props.margin + margin, shape_to_refine=self.shape_to_refine).flattened(), None)

class TabbedOperation(Operation):
    def __init__(self, shape, tool, machine_params, props, outside, tabs, extra_attribs):
        Operation.__init__(self, shape, tool, machine_params, props)
        self.outside = outside
        for key, value in extra_attribs.items():
            setattr(self, key, value)
        if isinstance(tabs, int):
            contours_for_tabs = cam.contour.plain(self.shape, tool.diameter, self.outside, self.props.margin, tool.climb)
            newtabs = []
            for contour in contours_for_tabs:
                newtabs += toolpath.Toolpath(contour, tool).autotabs(self.tool, tabs, width=self.tab_length())
            tabs = newtabs
        self.tabs = tabs
        self.cutpaths = self.build_cutpaths(0)
    def build_cutpaths(self, margin):
        path_output = self.build_paths(margin)
        if not path_output or not path_output.paths:
            return []
        cutpaths = []
        helical_entry_func = lambda path: self.helical_entry(path, path_output.paths_for_helical_entry)
        for tp in path_output.paths:
            cutpaths.append(CutPathWallProfile(self.machine_params, self.props, self.tool, helical_entry_func, self.subpaths_for_margin, False))
        return cutpaths
    def subpaths_for_margin(self, margin, is_sublayer):
        return self.build_paths(margin)
    def to_gcode(self, gcode):
        if self.props.actual_tab_depth() < self.props.depth:
            raise ValueError("Tab Z=%0.2fmm below cut Z=%0.2fmm." % (tab_depth, self.props.depth))
        Operation.to_gcode(self, gcode)
    def tab_length(self):
        return 1.5 if self.props.allow_helical_entry else 1
    def add_tabs_if_close(self, contours, tabs_dict, tab_locations, maxd):
        for i in contours:
            if i not in tabs_dict:
                # Filter by distance
                thistabs = []
                for t in tab_locations:
                    pos, dist = i.path.closest_point(t)
                    if dist < maxd:
                        thistabs.append(t)
                tabs_dict[i] = thistabs
    def calc_tab_locations_on_contours(self, contours, margin):
        newtabs = []
        path = Path(self.shape.boundary, self.shape.closed)
        # Offset the tabs
        for pt in self.tabs:
            pos, dist = path.closest_point(pt)
            pt2 = path.offset_point(pos, (margin + self.tool.diameter / 2) * (1 if self.outside else -1))
            newtabs.append(pt2)
        return newtabs

class Contour(TabbedOperation):
    def __init__(self, shape, outside, tool, machine_params, props, tabs, extra_width=0, trc_rate=0, entry_exit=None):
        assert shape.closed
        if trc_rate and extra_width:
            tab_extend = 8 * pi / (tool.diameter * trc_rate)
        else:
            tab_extend = 1
        TabbedOperation.__init__(self, shape, tool, machine_params, props, outside, tabs, { 'extra_width' : extra_width, 'trc_rate' : trc_rate, 'entry_exit' : entry_exit, 'tab_extend' : tab_extend})
    def tab_length(self):
        return self.tab_extend
    def build_paths(self, margin):
        trc_rate = self.trc_rate
        extra_width = self.extra_width
        tool = self.tool
        max_tab_distance = tool.diameter + abs(extra_width)
        paths_for_helical_entry = []
        if trc_rate and extra_width:
            contour_paths = cam.contour.pseudotrochoidal(self.shape, tool.diameter, self.outside, self.props.margin + margin, tool.climb, trc_rate * extra_width, 0.5 * extra_width)
            contours = toolpath.Toolpaths([toolpath.Toolpath(tp, tool, segmentation=segmentation) for tp, segmentation in contour_paths]).flattened() if contour_paths else []
        else:
            toolpaths = []
            contour_paths = cam.contour.plain(self.shape, tool.diameter, self.outside, self.props.margin + margin, tool.climb)
            if not contour_paths:
                return None
            for tp in contour_paths:
                toolpaths.append(toolpath.Toolpath(tp, tool))
                tp = tp.interpolated()
                res = cam.contour.plain(shapes.Shape(tp.nodes, True), tool.min_helix_diameter, self.outside, self.props.margin + margin, tool.climb)
                if res:
                    paths_for_helical_entry += res
            contours = toolpath.Toolpaths(toolpaths).flattened() if contour_paths else []
        if not contours:
            return None
        tab_locations = self.calc_tab_locations_on_contours(contours, margin)
        tabs_dict = {}
        twins = {}
        if extra_width and not trc_rate:
            res = self.widened_contours(contours, tool, extra_width * tool.diameter / 2, twins, tab_locations, tabs_dict, paths_for_helical_entry)
            if not self.entry_exit:
                # For entry_exit, this is handled via twins
                contours = res
        if self.entry_exit:
            if extra_width and trc_rate:
                # This will require handling segmentation
                raise ValueError("Cannot use entry/exit with trochoidal paths yet")
            contours = self.apply_entry_exit(contours, twins)
        self.add_tabs_if_close(contours, tabs_dict, tab_locations, tool.diameter * sqrt(2))
        for i in contours:
            if i in tabs_dict:
                i.tab_maker = toolpath.TabMaker(tabs_dict[i], 5 * max_tab_distance, self.tab_length())
        return PathOutput(contours, paths_for_helical_entry)
    def operation_name(self):
        return "Contour/Outside" if self.outside else "Contour/Inside"
    def apply_entry_exit(self, contours, twins):
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
                if newpath:
                    newpath = Path([sp], False).joined(newpath).joined(Path([ep], False))
                else:
                    newpath = orig_path
                cut_contours.append(toolpath.Toolpath(newpath, path.tool))
        return cut_contours
    def widened_contours(self, contours, tool, extension, twins, tabs, tabs_dict, paths_for_helical_entry):
        res = []
        for contour in contours:
            points = contour.path.nodes
            if contour.path.has_arcs():
                points = CircleFitter.interpolate_arcs(points, False, 1)
            offset = cam.contour.plain(shapes.Shape(points, True), 0, True, extension, not contour.path.orientation())
            if offset:
                merged = False
                if len(offset) == 1:
                    offset_tp = toolpath.Toolpath(offset[0], tool)
                    if toolpath.startWithClosestPoint(offset_tp, points[0], tool.diameter):
                        # Replace with a combination of the original and the offset path
                        orig_contour = contour
                        contour = toolpath.Toolpath(offset_tp.path.joined(contour.path), tool)
                        paths_for_helical_entry.append(contour.path)
                        merged = True
                        # Convert single-contour tabs to pairs
                        moretabs = []
                        for pt in tabs:
                            pos, dist = orig_contour.path.closest_point(pt)
                            if dist < tool.diameter * sqrt(2):
                                pt2 = orig_contour.path.offset_point(pos, extension)
                                pos, dist = offset_tp.path.closest_point(pt2)
                                pt2 = offset_tp.path.point_at(pos)
                                moretabs.append(pt)
                                moretabs.append(pt2)
                        tabs_dict[contour] = moretabs
                if not merged:
                    paths_for_helical_entry += offset
                    offset = [toolpath.Toolpath(i, tool) for i in offset]
                    res += offset
                    res.append(contour)
                    twins[contour] = offset
            res.append(contour)
        return res

class TrochoidalContour(TabbedOperation):
    def __init__(self, shape, outside, tool, machine_params, props, nrad, nspeed, tabs):
        TabbedOperation.__init__(self, shape, tool, machine_params, props, outside, tabs, { 'nrad' : nrad * 0.5 * tool.diameter, 'nspeed' : nspeed})
    def build_paths(self, margin):
        nrad = self.nrad
        nspeed = self.nspeed
        contours = self.shape.contour(self.tool, outside=self.outside, displace=nrad + self.props.margin + margin)
        if not self.outside:
            nrad = -nrad
        trochoidal_func = lambda contour: shapes.trochoidal_transform(contour, nrad, nspeed)
        newtabs = self.calc_tab_locations_on_contours(contours, margin)
        contours = toolpath.Toolpaths([toolpath.Toolpath(tp.path, tool, transform=trochoidal_func) for tp in contours.toolpaths])
        return contours, self.nrad, {}
    def tab_length(self):
        # This needs tweaking
        return 1 + self.nrad

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
    def __init__(self, x, y, tool, machine_params, props, dwell_bottom=0, dwell_retract=0, retract=None, slow_retract=False):
        shape = shapes.Shape.circle(x, y, r=0.5 * tool.diameter)
        self.x = x
        self.y = y
        UntabbedOperation.__init__(self, shape, tool, machine_params, props)
        self.dwell_bottom = dwell_bottom
        self.dwell_retract = dwell_retract
        self.retract = retract or RetractToSemiSafe()
        self.slow_retract = slow_retract
    def build_paths(self, margin):
        return PathOutput([toolpath.Toolpath(Path([PathPoint(self.x, self.y)], True), self.tool)], None)
    def to_gcode(self, gcode):
        gcode.rapid(x=self.x, y=self.y)
        gcode.rapid(z=self.machine_params.semi_safe_z)
        gcode.feed(self.tool.vfeed)
        curz = self.props.start_depth
        doc = self.tool.maxdoc
        while curz > self.props.depth:
            nextz = max(curz - doc, self.props.depth)
            gcode.linear(z=nextz)
            if self.dwell_bottom:
                gcode.dwell(self.dwell_bottom)
            retrz = self.retract.get(nextz, self.props, self.machine_params.semi_safe_z)
            if self.slow_retract:
                gcode.linear(z=retrz)
            else:
                gcode.rapid(z=retrz)
            if self.dwell_retract:
                gcode.dwell(self.dwell_retract)
            curz = nextz
        gcode.rapid(z=self.machine_params.safe_z)

class HelicalDrill(UntabbedOperation):
    def __init__(self, x, y, d, tool, machine_params, props):
        d -= props.margin
        self.min_dia = tool.diameter + tool.min_helix_diameter
        if d < self.min_dia:
            raise ValueError("Diameter %0.3f smaller than the minimum %0.3f" % (d, self.min_dia))
        self.x = x
        self.y = y
        self.d = d
        self.tool = tool
        shape = shapes.Shape.circle(x, y, r=0.5*self.d)
        UntabbedOperation.__init__(self, shape, tool, machine_params, props)
    def build_paths(self, margin):
        coords = []
        for cd in self.diameters():
            coords += shapes.Shape.circle(self.x, self.y, r=0.5*(cd - self.tool.diameter)).boundary
        return PathOutput([toolpath.Toolpath(Path(coords, False), self.tool)], None)
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

    def to_gcode(self, gcode):
        rate_factor = self.tool.full_plunge_feed_ratio

        gcode.section_info(f"Start helical drill at {self.x:0.2f}, {self.y:0.2f} diameter {self.d:0.2f} depth {self.props.depth:0.2f}")
        first = True
        for d in self.diameters():
            self.to_gcode_ring(gcode, d, (rate_factor if first else 1) * self.tool.diagonal_factor(), self.machine_params, first)
            first = False
        gcode.feed(self.tool.hfeed)
        # Do not rub against the walls
        gcode.section_info(f"Exit to centre/safe Z")
        gcode.linear(x=self.x, y=self.y)
        gcode.rapid(x=self.x, y=self.y, z=self.machine_params.safe_z)
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
    def to_gcode(self, gcode):
        # Do the first pass at a slower rate because of full radial engagement downwards
        rate_factor = self.tool.full_plunge_feed_ratio
        if self.d < self.min_dia:
            self.to_gcode_ring(gcode, self.d, rate_factor, self.machine_params, True)
        else:
            # Mill initial hole by helical descent into desired depth
            d = self.min_dia
            self.to_gcode_ring(gcode, d, rate_factor, self.machine_params, True)
            gcode.feed(self.tool.hfeed)
            # Bore it out at full depth to the final diameter
            while d < self.d:
                r = max(self.tool.diameter * self.tool.stepover / 2, (d - self.tool.diameter) / 2)
                gcode.linear(x=self.x + r, y=self.y)
                gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth, False)
                d += self.tool.diameter * self.tool.stepover_fulldepth
            r = max(0, (self.d - self.tool.diameter) / 2)
            gcode.helix_turn(self.x, self.y, r, self.props.depth, self.props.depth, False)
        gcode.rapid(z=self.machine_params.safe_z)

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
    def __init__(self, machine_params, tool=None, props=None, thickness=None):
        self.machine_params = machine_params
        self.tool = tool
        self.props = props
        self.thickness = thickness
        self.operations = []
    def add(self, operation):
        self.operations.append(operation)
    def add_all(self, operations):
        self.operations += operations
    def is_nothing(self):
        for i in self.operations:
            if i.cutpaths:
                return False
        return True
    def outside_contour(self, shape, tabs, widen=0, props=None, entry_exit=None):
        if shape.islands:
            for i in shape.islands:
                self.add(Contour(shapes.Shape(i, True), False, self.tool, self.machine_params, props or self.props, tabs=0, extra_width=widen))
        self.add(Contour(shape, True, self.tool, self.machine_params, props or self.props, tabs=tabs, extra_width=widen, entry_exit=entry_exit))
    def outside_contour_trochoidal(self, shape, nrad, nspeed, tabs, props=None, entry_exit=None):
        if shape.islands:
            for i in shape.islands:
                self.add(Contour(shapes.Shape(i, True), False, self.tool, self.machine_params, props or self.props, tabs=tabs, extra_width=nrad, trc_rate=nspeed))
        #self.add(TrochoidalContour(shape, True, self.tool, props or self.props, nrad=nrad, nspeed=nspeed, tabs=tabs))
        self.add(Contour(shape, True, self.tool, self.machine_params, props or self.props, tabs=tabs, extra_width=nrad, trc_rate=nspeed, entry_exit=entry_exit))
    def inside_contour(self, shape, tabs, widen=0, props=None, entry_exit=None):
        self.add(Contour(shape, False, self.tool, self.machine_params, props or self.props, tabs=tabs, extra_width=-widen, entry_exit=entry_exit))
    def inside_contour_trochoidal(self, shape, nrad, nspeed, tabs, props=None, entry_exit=None):
        self.add(Contour(shape, False, self.tool, self.machine_params, props or self.props, tabs=tabs, extra_width=nrad, trc_rate=nspeed, entry_exit=entry_exit))
    def outside_contour_with_profile(self, shape, props=None):
        self.contour_with_profile(shape, True, props)
    def inside_contour_with_profile(self, shape, props=None):
        self.contour_with_profile(shape, False, props)
    def engrave(self, shape, props=None):
        self.add(Engrave(shape, self.tool, self.machine_params, props or self.props))
    def pocket(self, shape, props=None):
        self.add(Pocket(shape, self.tool, self.machine_params, props or self.props))
    def pocket_hsm(self, shape, props=None, shape_to_refine=None):
        self.add(HSMPocket(shape, self.tool, self.machine_params, props or self.props, shape_to_refine))
    def outside_peel(self, shape, props=None):
        self.add(OutsidePeel(shape, self.tool, self.machine_params, props or self.props))
    def outside_peel_hsm(self, shape, props=None, shape_to_refine=None):
        self.add(OutsidePeelHSM(shape, self.tool, self.machine_params, props or self.props, shape_to_refine))
    def face_mill(self, shape, props=None):
        self.add(FaceMill(shape, self.tool, self.machine_params, props or self.props))
    def peck_drill(self, x, y, props=None):
        self.add(PeckDrill(x, y, self.tool, self.machine_params, props or self.props))
    def helical_drill(self, x, y, d, props=None):
        self.add(HelicalDrill(x, y, d, self.tool, self.machine_params, props or self.props))
    def helical_drill_full_depth(self, x, y, d, props=None):
        self.add(HelicalDrillFullDepth(x, y, d, self.tool, self.machine_params, props or self.props))
    def to_gcode(self):
        gcode = Gcode()
        gcode.reset()
        gcode.rapid(z=self.machine_params.safe_z)
        gcode.rapid(x=0, y=0)
        for operation in self.operations:
            gcode.section_info(f"Start operation: {type(operation).__name__}")
            gcode.begin_section(operation.rpm)
            operation.to_gcode(gcode)
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
