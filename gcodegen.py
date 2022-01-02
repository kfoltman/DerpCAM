from geom import *
import process
import toolpath

# VERY experimental feature
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
        accuracy = 0.5 / GeometrySettings.RESOLUTION
        self.add("G17 G21 G90 G40 G64 P%0.3f Q%0.3f" % (accuracy, accuracy))
    def prompt_for_tool(self, name):
        name = name.replace("(", "<").replace(")",">")
        self.add(f"M1 ({name})")
        self.reset()
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
                self.arc_ccw(i = -r, z = cur_z + delta_z)
            else:
                self.arc_cw(i = -r, z = cur_z + delta_z)

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
        assert dist(lastpt, subpath[0]) < 1 / GeometrySettings.RESOLUTION
        tdist = 0
        for pt in subpath[1:]:
            if len(pt) > 2:
                # Arc
                tag, spt, ept, c, steps, sangle, sspan = pt
                cdist = (c.cx - spt[0], c.cy - spt[1])
                assert dist(lastpt, spt) < 1 / GeometrySettings.RESOLUTION
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
                if newlength < 1 / GeometrySettings.RESOLUTION:
                    # Very small delta, just plunge down
                    self.linear(z=new_z)
                    break
                if debug_ramp:
                    self.add("(Last pass, shortening to %d)" % newlength)
                subpath = calc_subpath(subpath, 0, newlength)
                real_length = path_length(subpath)
                assert abs(newlength - real_length) < 1 / GeometrySettings.RESOLUTION
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
    @staticmethod
    def simplifySubpathsArcs(subpaths):
        return [subpath.lines_to_arcs() for subpath in subpaths]
    @staticmethod
    def simplifySubpathsLines(subpaths):
        return [subpath.optimize_lines() for subpath in subpaths]
    def __init__(self, path):
        self.subpaths_full = [path.transformed()]
        if GeometrySettings.simplify_arcs:
            self.subpaths_full = self.simplifySubpathsArcs(self.subpaths_full)
        if GeometrySettings.simplify_lines:
            self.subpaths_full = self.simplifySubpathsLines(self.subpaths_full)

class TabbedCutPath2D(CutPath2D):
    def __init__(self, path_notabs, path_withtabs):
        CutPath2D.__init__(self, path_notabs)
        self.subpaths_tabbed = path_withtabs
        if GeometrySettings.simplify_arcs:
            self.subpaths_tabbed = self.simplifySubpathsArcs(self.subpaths_tabbed)
        if GeometrySettings.simplify_lines:
            self.subpaths_tabbed = self.simplifySubpathsLines(self.subpaths_tabbed)

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
        # Not a continuous path, need to jump to a new place
        firstpt = subpaths[0].points[0]
        if self.lastpt is None or dist(self.lastpt, firstpt) > (1 / 1000):
            if layer.force_join:
                gcode.linear(x=firstpt[0], y=firstpt[1])
            else:
                self.go_to_safe_z(gcode)
                # Note: it's not ideal because of the helical entry, but it's
                # good enough.
                gcode.rapid(x=firstpt[0], y=firstpt[1])
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
        points = subpath.points + subpath.points[0:1] if subpath.closed else subpath.points
        assert self.lastpt is not None
        self.lastpt = gcode.apply_subpath(points, self.lastpt)
        self.end_subpath(subpath)

    def enter_or_leave_cut(self, gcode, subpath, newz):
        if newz != self.curz:
            if newz < self.curz:
                self.enter_cut(gcode, subpath, newz)
            else:
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
        z_already_cut_here = self.z_already_cut_here(subpath)
        z_above_cut = z_already_cut_here + self.machine_params.over_tab_safety
        if z_already_cut_here < self.curz:
            if subpath.helical_entry:
                gcode.move_z(z_already_cut_here, self.curz, subpath.tool, self.machine_params.semi_safe_z, z_above_cut)
            else:
                gcode.move_z(z_already_cut_here, self.curz, subpath.tool, self.machine_params.semi_safe_z)
            self.curz = z_already_cut_here
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

    def start_cutpath(self, gcode, cutpath):
        self.curz = self.machine_params.safe_z
        self.depth = self.props.start_depth
        self.lastpt = None

    def end_cutpath(self, gcode, cutpath):
        self.go_to_safe_z(gcode)

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
        return cutpath.subpaths_tabbed if depth < self.tab_depth else cutpath.subpaths_full

    def next_depth(self, depth):
        if depth <= self.props.depth:
            return None
        doc = self.doc(depth)
        # Is there a tab depth in between the current and the new depth?
        if depth > self.tab_depth and depth - doc < self.tab_depth:
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
        return self.over_tab_z if subpath.is_tab else self.depth

    def start_subpath(self, subpath):
        if subpath.is_tab and debug_tabs:
            gcode.add("(tab start)")

    def end_subpath(self, subpath):
        if subpath.is_tab and debug_tabs:
            gcode.add("(tab end)")

class Cut2DWithDraft(BaseCut2D):
    def __init__(self, machine_params, props, tool, shape, toolpaths_func, outside, draft_angle_deg, layer_thickness):
        BaseCut2D.__init__(self, machine_params, props, tool, None)
        self.shape = shape
        self.outside = outside
        self.draft_angle_deg = draft_angle_deg
        self.layer_thickness = layer_thickness
        self.draft = tan(draft_angle_deg * pi / 180)
        max_height = self.props.start_depth - self.props.depth
        toolpaths = toolpaths_func(self.shape, self.tool, self.props.margin + max_height * self.draft)
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
            contour = self.shape.contour(self.tool, self.outside, displace=self.props.margin+draftval)
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
    def __init__(self, shape, tool, props, paths):
        Operation.__init__(self, shape, tool, props)
        self.paths = paths
        self.flattened = paths.flattened() if paths else None
    def to_gcode(self, gcode, machine_params):
        for path in self.flattened:
            BaseCut2D(machine_params, self.props, self.tool, path).build(gcode)
    def to_preview(self):
        return [(self.props.depth, i) for i in self.flattened]

class Engrave(UntabbedOperation):
    def __init__(self, shape, tool, props):
        UntabbedOperation.__init__(self, shape, tool, props, shape.engrave(tool))

class FaceMill(UntabbedOperation):
    def __init__(self, shape, angle, margin, zigzag, tool, props):
        UntabbedOperation.__init__(self, shape, tool, props, shape.face_mill(tool, angle, margin, zigzag))

class Pocket(UntabbedOperation):
    def __init__(self, shape, tool, props):
        UntabbedOperation.__init__(self, shape, tool, props, shape.pocket_contour(tool, displace=props.margin))

class PocketWithDraft(UntabbedOperation):
    def __init__(self, shape, tool, props, draft_angle_deg, layer_thickness):
        UntabbedOperation.__init__(self, shape, tool, props, shape.pocket_contour(tool, displace=props.margin))
        self.draft_angle_deg = draft_angle_deg
        self.layer_thickness = layer_thickness
    def to_gcode(self, gcode, machine_params):
        Cut2DWithDraft(machine_params, self.props, self.tool, self.shape, lambda shape, tool, margin: shape.pocket_contour(tool, margin), False, self.draft_angle_deg, self.layer_thickness).build(gcode)

class TabbedOperation(Operation):
    def __init__(self, shape, tool, props, paths, tabs):
        Operation.__init__(self, shape, tool, props)
        self.paths = paths
        self.flattened = paths.flattened() if paths else None
        self.tabbed_for_path = {}
        if tabs:
            for i in self.flattened:
                tab_inst = i.usertabs(tabs[i], width=self.tabs_width())
                self.tabbed_for_path[i] = i.cut_by_tabs(tab_inst)
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

class Contour(TabbedOperation):
    def __init__(self, shape, outside, tool, props, tabs, extra_width=0):
        assert shape.closed
        extra_width *= tool.diameter / 2 
        contours = shape.contour(tool, outside=outside, displace=props.margin).flattened()
        if isinstance(tabs, int):
            newtabs = []
            for contour in contours:
                newtabs += contour.autotabs(tool, tabs, width=self.tabs_width())
        else:
            # Offset the tabs
            newtabs = []
            for pt in tabs:
                pos, dist = closest_point(shape.boundary, True, pt)
                pt2 = offset_point_on_path(shape.boundary, pos, tool.diameter / 2 * (1 if outside else -1))
                newtabs.append(pt2)
        tabs = newtabs
        tabs_dict = {}
        if extra_width:
            widen_func = lambda contour: self.widen(contour, tool, extra_width)
            res = []
            for contour in contours:
                widened = toolpath.Toolpath(contour.points, contour.closed, tool, transform=widen_func).transformed()
                if isinstance(widened, toolpath.Toolpath):
                    moretabs = []
                    for pt in tabs:
                        pos, dist = closest_point(contour.points, contour.closed, pt)
                        if dist < tool.diameter * sqrt(2):
                            pt2 = offset_point_on_path(contour.points, pos, extra_width)
                            moretabs.append(pt)
                            moretabs.append(pt2)
                    tabs_dict[widened] = moretabs
                res.append(widened)
            contours = toolpath.Toolpaths(res)
        else:
            contours = toolpath.Toolpaths(contours)
        for i in contours.flattened():
            if i not in tabs_dict:
                # Filter by distance
                thistabs = []
                for t in tabs:
                    pos, dist = closest_point(i.points, True, t)
                    if dist < tool.diameter * sqrt(2):
                        thistabs.append(t)
                tabs_dict[i] = thistabs
        TabbedOperation.__init__(self, shape, tool, props, contours, tabs=tabs_dict)
        self.outside = outside
    def operation_name(self):
        return "Contour/Outside" if self.outside else "Contour/Inside"
    def widen(self, contour, tool, extension):
        if not contour.closed:
            return contour
        points = contour.points
        offset = process.Shape._offset(PtsToInts(points), True, GeometrySettings.RESOLUTION * extension)
        if len(offset) == 1:
            extension = toolpath.Toolpath(PtsFromInts(offset[0]), True, tool)
            if process.startWithClosestPoint(extension, points[0], tool.diameter):
                if SameOrientation(points, extension.points):
                    extension.points = reverse_path(extension.points)
                points = extension.points + points + points[0:1] + extension.points[0:1]
                return toolpath.Toolpath(points, contour.closed, tool)
        widened = []
        for path in offset:
            widened.append(toolpath.Toolpath(PtsFromInts(path), True, tool))
        widened.append(toolpath.Toolpath(points, contour.closed, tool))
        return toolpath.Toolpaths(widened)

class TrochoidalContour(TabbedOperation):
    def __init__(self, shape, outside, tool, props, nrad, nspeed, tabs):
        nrad *= 0.5 * tool.diameter
        self.nrad = nrad
        self.nspeed = nspeed
        if not outside:
            nrad = -nrad
        contour = shape.contour(tool, outside=outside, displace=nrad + props.margin)
        trochoidal_func = lambda contour: trochoidal_transform(contour, nrad, nspeed)
        contour = Toolpath(contour.points, contour.closed, tool, transform=trochoidal_func)
        TabbedOperation.__init__(self, shape, tool, props, contour, tabs=tabs)
    def tabs_width(self):
        # This needs tweaking
        return 1 + self.nrad

class ContourWithDraft(TabbedOperation):
    def __init__(self, shape, outside, tool, props, draft_angle_deg, layer_thickness):
        TabbedOperation.__init__(self, shape, tool, props, shape.contour(tool, outside=outside, displace=props.margin), [])
        self.outside = outside
        self.draft_angle_deg = draft_angle_deg
        self.layer_thickness = layer_thickness
    def to_gcode(self, gcode, machine_params):
        Cut2DWithDraft(machine_params, self.props, self.tool, self.shape, lambda shape, tool, margin: shape.contour(tool, self.outside, margin), self.outside, self.draft_angle_deg, self.layer_thickness).build(gcode)

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
        shape = process.Shape.circle(x, y, r=0.5 * tool.diameter)
        UntabbedOperation.__init__(self, shape, tool, props, toolpath.Toolpath([(x, y)], True, tool))
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

class HelicalDrill(UntabbedOperation):
    def __init__(self, x, y, d, tool, props):
        d -= props.margin
        self.min_dia = tool.diameter + tool.min_helix_diameter
        if d < self.min_dia:
            raise ValueError("Diameter %0.3f smaller than the minimum %0.3f" % (d, self.min_dia))
        shape = process.Shape.circle(x, y, r=0.5*d)
        UntabbedOperation.__init__(self, shape, tool, props, shape.pocket_contour(tool))
        self.x = x
        self.y = y
        self.d = d

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
        for d in self.diameters():
            self.to_gcode_ring(gcode, d, rate_factor, machine_params)
            rate_factor = 1
        gcode.rapid(z=machine_params.safe_z)

    def to_gcode_ring(self, gcode, d, rate_factor, machine_params):
        r = max(self.tool.diameter * self.tool.stepover / 2, (d - self.tool.diameter) / 2)
        gcode.add("(Circle at %0.2f, %0.2f diameter %0.2f overall diameter %0.2f)" % (self.x, self.y, 2 * r, 2 * r + self.tool.diameter))
        gcode.rapid(z=machine_params.safe_z)
        gcode.rapid(x=self.x + r, y=self.y)
        curz = machine_params.semi_safe_z
        gcode.rapid(z=machine_params.semi_safe_z)
        gcode.feed(self.tool.hfeed * rate_factor)
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
        # Do the first pass at a slower rate because of full radial engagement downwards
        rate_factor = self.tool.full_plunge_feed_ratio
        if self.d < self.min_dia:
            self.to_gcode_ring(gcode, self.d, rate_factor, machine_params)
        else:
            # Mill initial hole by helical descent into desired depth
            d = self.min_dia
            self.to_gcode_ring(gcode, d, rate_factor, machine_params)
            gcode.feed(self.tool.hfeed)
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
    def add_all(self, operations):
        self.operations += operations
    def outside_contour(self, shape, tabs, widen=0, props=None):
        self.add(Contour(shape, True, self.tool, props or self.props, tabs=tabs, extra_width=widen))
    def outside_contour_trochoidal(self, shape, nrad, nspeed, tabs, props=None):
        self.add(TrochoidalContour(shape, True, self.tool, props or self.props, nrad=nrad, nspeed=nspeed, tabs=tabs))
    def outside_contour_with_draft(self, shape, draft_angle_deg, layer_thickness, tabs, props=None):
        self.contour_with_draft(shape, True, draft_angle_deg, layer_thickness, tabs, props)
    def inside_contour_with_draft(self, shape, draft_angle_deg, layer_thickness, tabs, props=None):
        self.contour_with_draft(shape, False, draft_angle_deg, layer_thickness, tabs, props)
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
    def inside_contour(self, shape, tabs, widen=0, props=None):
        self.add(Contour(shape, False, self.tool, props or self.props, tabs=tabs, extra_width=-widen))
    def engrave(self, shape, props=None):
        self.add(Engrave(shape, self.tool, props or self.props))
    def pocket(self, shape, props=None):
        self.add(Pocket(shape, self.tool, props or self.props))
    def pocket_with_draft(self, shape, draft_angle_deg, layer_thickness, props=None):
        self.add(PocketWithDraft(shape, self.tool, props or self.props, draft_angle_deg, layer_thickness))
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
