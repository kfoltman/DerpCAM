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

    def apply_vcarve_subpath(self, subpath, lastpt, tool, base_z, target_z):
        self.section_info("Start vcarve subpath")
        first = True
        for lastpt, pt in PathSegmentIterator(subpath):
            assert isinstance(pt.speed_hint, toolpath.DesiredDiameter)
            assert isinstance(lastpt.speed_hint, toolpath.DesiredDiameter)
            assert not pt.is_arc()
            assert base_z is not None
            if first:
                start_z = max(target_z, base_z + tool.dia2depth(lastpt.speed_hint.diameter))
                self.linear(z=start_z)
                first = False
            end_z = max(target_z, base_z + tool.dia2depth(pt.speed_hint.diameter))
            self.linear(x=pt.x, y=pt.y, z=end_z)
        lastpt = pt.seg_end()
        self.section_info("End vcarve subpath")
        return lastpt

    def apply_subpath(self, subpath, lastpt, new_z=None, old_z=None, tlength=None, subject=None):
        self.section_info("Start subpath" if not subject else f"Start {subject} subpath")
        assert isinstance(lastpt, PathPoint)
        assert dist(lastpt, subpath.seg_start()) < 1 / GeometrySettings.RESOLUTION, f"lastpt={lastpt} != firstpt={subpath.seg_start()}"
        tdist = 0
        for lastpt, pt in PathSegmentIterator(subpath):
            if new_z is not None:
                tdist += pt.length() if pt.is_arc() else dist(lastpt, pt) # Need to use arc length even if the arc was replaced with a line segment
                ramp_end = tdist / tlength
            else:
                ramp_end = 1
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
                dest_z = old_z + (new_z - old_z) * ramp_end if new_z is not None else None
                self.arc(arc_dir, x=arc.p2.x, y=arc.p2.y, i=cdist.x, j=cdist.y, z=dest_z)
            else:
                pt = pt.seg_end() # in case this was a short arc approximated with a line
                if new_z is not None:
                    self.linear(x=pt.x, y=pt.y, z=old_z + (new_z - old_z) * ramp_end)
                elif not GeometrySettings.paranoid_mode and pt.speed_hint is toolpath.RapidMove:
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

    def helical_move_z(self, new_z, old_z, helical_entry, tool, semi_safe_z, already_cut_z=None, from_top=False, top_z=None):
        if from_top:
            self.section_info(f"Start from-top helical move from {top_z:0.3f} to {new_z:0.3f}")
            self.rapid(z=top_z)
            old_z = top_z
            already_cut_z = top_z
        else:
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
    def correct_helical_entry(self, subpaths):
        if self.props.allow_helical_entry:
            for tp in subpaths:
                if tp.helical_entry is None and self.helical_entry_func is not None:
                    tp.helical_entry = self.helical_entry_func(tp.path)
            if subpaths and subpaths[0].helical_entry:
                subpaths[0].helical_from_top = False
        else:
            for tp in subpaths:
                tp.helical_entry = None

# Simple 2D case, just follow the same toolpath level after level.
class CutPath2D(BaseCutPath):
    def __init__(self, machine_params, props, tool, helical_entry_func, path):
        BaseCutPath.__init__(self, machine_params, props, tool, helical_entry_func)
        self.subpaths_full = [path.transformed()]
        self.correct_helical_entry(self.subpaths_full)
        self.generate_preview(self.subpaths_full)
        self.cut_layers = self.to_layers()
    def subpaths_for_layer(self, layer):
        return self.subpaths_full
    def to_preview(self):
        preview = []
        for i in self.subpaths_full:
            preview.append((self.props.depth, i))
        return preview

# A wrapper/adapter to allow using CutLayerTree for preview paths
# Takes depth and Toolpath/Toolpaths and pretends to be a CutLayer.
class PreviewSubpath(object):
    def __init__(self, max_depth, path):
        self.max_depth = max_depth
        self.path = path
        self.bounds = path.bounds
        self.children = []
        self.linked = []
    def overlaps(self, another):
        return bounds_overlap(self.bounds, another.bounds)

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
                    subpaths = []
                    for path in path_output.paths:
                        subpaths.append(path.optimize())
                        pbpaths = path_output.piggybacked_paths_dict.get(path, [])
                        subpaths += [pbpath.optimize() for pbpath in pbpaths]
                    self.correct_helical_entry(subpaths)
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
                    # Untrochoidify and remove helical entry from top of stock if needed
                    assert layer.tab_status == LayerInfo.TAB_BELOW
                    subpaths = [subpath.for_tab_below() for subpath in subpaths]
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
        # Sort cuts by areas
        layer_tree = CutLayerTree()
        last_depth = None
        layers_by_depth = list(sorted(list(self.requested_layers), key=lambda layer: -layer.max_depth))
        for cs in layers_by_depth:
            if cs.max_depth != last_depth:
                if last_depth is not None:
                    layer_tree.finish_level()
                last_depth = cs.max_depth
            for i in cs.subpaths:
                layer_tree.add(PreviewSubpath(cs.max_depth, i))
        layer_tree.finish_level()
        flattened = layer_tree.flatten()
        preview = []
        for cs in flattened:
            sp = cs.path
            if isinstance(sp, toolpath.Toolpath):
                preview.append((self.props.actual_tab_depth() if sp.is_tab else cs.max_depth, sp))
            elif isinstance(sp, toolpath.Toolpaths):
                for i in sp.toolpaths:
                    preview.append((self.props.actual_tab_depth() if i.is_tab else cs.max_depth, i))
            else:
                assert False
        #self.dump_preview(preview)
        return preview
    def dump_preview(self, preview):
        print ("Dump preview start")
        for depth, path in preview:
            if path is None:
                print ("---")
            else:
                b = path.bounds
                print (depth, f"({b[0]:0.3f}, {b[1]:0.3f}) - ({b[2]:0.3f}, {b[3]:0.3f})", path.helical_entry)
        print ("Dump preview end")

class PathOutput(object):
    def __init__(self, paths, paths_for_helical_entry, piggybacked_paths_dict):
        self.paths = paths
        self.paths_for_helical_entry = paths_for_helical_entry
        # Additional paths to cut before a given path, at each depth level (used for widened slots)
        self.piggybacked_paths_dict = piggybacked_paths_dict

class BaseCut(object):
    def __init__(self, machine_params, props, tool):
        self.machine_params = machine_params
        self.props = props
        self.tool = tool

class BaseCutLayered(BaseCut):
    def __init__(self, machine_params, props, tool, cutpaths):
        BaseCut.__init__(self, machine_params, props, tool)
        self.cutpaths = cutpaths

    def build(self, gcode):
        self.curz = self.machine_params.safe_z
        for cutpath in self.cutpaths:
            self.build_cutpath(gcode, cutpath)

    def build_cutpath(self, gcode, cutpath):
        self.start_cutpath(gcode, cutpath)
        for layer in self.layers_for_cutpath(cutpath):
            self.build_layer(gcode, cutpath, layer)
        self.end_cutpath(gcode, cutpath)

    def layers_for_cutpath(self, cutpath):
        return cutpath.cut_layers

    def go_to_safe_z(self, gcode):
        gcode.rapid(z=self.machine_params.safe_z)
        self.curz = self.machine_params.safe_z

class VCarveCut(BaseCutLayered):
    def build_cutpath(self, gcode, cutpath):
        gcode.section_info(f"Start v-carve cutpath")
        layers = self.layers_for_cutpath(cutpath)
        self.lastpt = None
        for subpath in cutpath.subpaths_full:
            self.build_subpath(gcode, cutpath, layers, subpath)
        gcode.section_info(f"End v-carve cutpath")
        self.go_to_safe_z(gcode)

    def build_subpath(self, gcode, cutpath, layers, subpath):
        if subpath.path.length() < 0.001:
            return
        reversed = False
        if self.lastpt is None or self.lastpt.dist(subpath.path.seg_start()) > 0.001:
            self.lastpt = subpath.path.seg_start()
            gcode.rapid(x=self.lastpt.x, y=self.lastpt.y)
            gcode.rapid(z=self.machine_params.semi_safe_z)
        gcode.feed(subpath.tool.vfeed)
        for layer in layers:
            if self.is_redundant_pass(subpath, base_z=self.props.start_depth, target_z=layer.depth, prev_z=layer.prev_depth):
                break
            assert isinstance(self.lastpt, PathPoint)
            if reversed:
                self.lastpt = gcode.apply_vcarve_subpath(Path(list(subpath.path.nodes[::-1]), False), self.lastpt, tool=subpath.tool, base_z=self.props.start_depth, target_z=layer.depth)
            else:
                self.lastpt = gcode.apply_vcarve_subpath(subpath.path, self.lastpt, tool=subpath.tool, base_z=self.props.start_depth, target_z=layer.depth)
            assert isinstance(self.lastpt, PathPoint)
            if not subpath.path.closed:
                reversed = not reversed

    def is_redundant_pass(self, subpath, base_z, target_z, prev_z):
        lowest_z = base_z
        for pt in subpath.path.nodes:
            lowest_z = min(lowest_z, base_z + subpath.tool.dia2depth(pt.speed_hint.diameter))
        lowest_z = max(lowest_z, target_z)
        return lowest_z >= prev_z

# Simple tabbed 2D toolpath
class BaseCut2D(BaseCutLayered):
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
        # Assuming <1% of tool diameter of a gap is harmless enough. The tolerance
        # needs to be low enough to avoid exceeding cutter engagement specified,
        # but high enough not to be tripped by rasterization errors from
        # pyclipper etc.
        tolerance = self.tool.diameter * 0.01
        if subpaths[0].helical_entry:
            firstpt = subpaths[0].helical_entry.start
            # Allow up to stepover of discrepancy between the helical entry
            # and the starting point. This is to accommodate corners - the circle
            # cut by helical entry doesn't reach into corners, but it is allowed
            # to make a full cut of up to stepover value in order to get into the
            # corner from the initial circle.
            tolerance = self.tool.diameter * self.tool.stepover
        if self.lastpt is None or dist(self.lastpt, firstpt) >= tolerance:
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
                self.lastpt = gcode.helical_move_z(newz, curz, subpath.helical_entry, subpath.tool, self.machine_params.semi_safe_z, z_above_cut, 
                    from_top = subpath.helical_from_top and curz < self.props.start_depth, top_z=self.props.start_depth)
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


