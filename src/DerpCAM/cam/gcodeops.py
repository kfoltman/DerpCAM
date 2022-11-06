import threading
from DerpCAM.common.geom import *
from DerpCAM import cam
import DerpCAM.cam.contour
import DerpCAM.cam.peel
import DerpCAM.cam.pocket
from DerpCAM.cam.wall_profile import PlainWallProfile
from DerpCAM.cam.gcodegen import Gcode, PathOutput, BaseCut2D, CutPath2D, CutPathWallProfile

from DerpCAM.cam import shapes, toolpath

class MachineParams(object):
    def __init__(self, safe_z, semi_safe_z, min_rpm=None, max_rpm=None):
        self.safe_z = safe_z
        self.semi_safe_z = semi_safe_z
        self.min_rpm = min_rpm
        self.max_rpm = max_rpm
        self.over_tab_safety = 0.2

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
        return PathOutput(self.shape.engrave(self.tool, self.props.margin).flattened(), None, {})

class FaceMill(UntabbedOperation):
    def build_paths(self, margin):
        return PathOutput(cam.pocket.axis_parallel(self.shape, self.tool, self.props.angle, self.props.margin + margin, self.props.zigzag, roughing_offset=self.props.roughing_offset).flattened(), None, {})

class Pocket(UntabbedOperation):
    def build_cutpaths(self):
        return [CutPathWallProfile(self.machine_params, self.props, self.tool, None, self.subpaths_for_margin, True)]
    def build_paths(self, margin):
        return PathOutput(cam.pocket.contour_parallel(self.shape, self.tool, displace=self.props.margin + margin, roughing_offset=self.props.roughing_offset).flattened(), None, {})
    def subpaths_for_margin(self, margin, is_sublayer):
        if is_sublayer:
            # Edges only (this is used for refining the wall profile after a roughing pass)
            paths = []
            for i in self.shape.islands:
                paths += cam.contour.plain(shapes.Shape(i, True), self.tool.diameter, True, self.props.margin + margin, self.tool.climb)
            paths += cam.contour.plain(self.shape, self.tool.diameter, False, self.props.margin + margin, self.tool.climb)
            return PathOutput([toolpath.Toolpath(path, self.tool) for path in paths], None, {})
        else:
            # Full pocket (roughing pass)
            return self.build_paths(margin)

class HSMOperation(UntabbedOperation):
    def __init__(self, shape, tool, machine_params, props, shape_to_refine):
        UntabbedOperation.__init__(self, shape, tool, machine_params, props, extra_attribs={ 'shape_to_refine' : shape_to_refine })

class HSMPocket(HSMOperation):
    def build_paths(self, margin):
        return PathOutput(cam.pocket.hsm_peel(self.shape, self.tool, self.props.zigzag, displace=self.props.margin + margin, shape_to_refine=self.shape_to_refine, roughing_offset=self.props.roughing_offset).flattened(), None, {})

class OutsidePeel(UntabbedOperation):
    def build_paths(self, margin):
        return PathOutput(cam.peel.outside_peel(self.shape, self.tool, displace=self.props.margin + margin).flattened(), None, {})

class OutsidePeelHSM(HSMOperation):
    def build_paths(self, margin):
        return PathOutput(cam.peel.outside_peel_hsm(self.shape, self.tool, zigzag=self.props.zigzag, displace=self.props.margin + margin, shape_to_refine=self.shape_to_refine).flattened(), None, {})

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
                res = cam.contour.plain(shapes.Shape(tp.nodes, True), tool.min_helix_diameter, self.outside, 0, tool.climb)
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
            if tab_locations:
                # How would that even work without separate entry/exit point per tab?
                raise ValueError("Cannot use entry/exit with tabs")
            contours, twins = self.apply_entry_exit(contours, twins)
        self.add_tabs_if_close(contours, tabs_dict, tab_locations, tool.diameter * sqrt(2))
        for i in contours:
            if i in tabs_dict:
                i.tab_maker = toolpath.TabMaker(tabs_dict[i], 5 * max_tab_distance, self.tab_length())
                ctwins = twins.get(i, [])
                for j in ctwins:
                    j.tab_maker = toolpath.TabMaker(tabs_dict[i], 5 * max_tab_distance, self.tab_length())
        return PathOutput(contours, paths_for_helical_entry, twins)
    def operation_name(self):
        return "Contour/Outside" if self.outside else "Contour/Inside"
    def apply_entry_exit(self, contours, twins):
        ee = self.entry_exit
        cut_contours = []
        res_twins = {}
        for sp, ep in ee:
            path = contours[0]
            pos, min_dist = path.path.closest_point(sp)
            for j in contours[1:]:
                pos, dist = j.path.closest_point(sp)
                if dist < min_dist:
                    min_dist = dist
                    path = j
            path_and_twins = [path] + twins.get(path, [])
            cur_twins = []
            for i in path_and_twins:
                orig_path = i.path
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
                if i is path:
                    path = toolpath.Toolpath(newpath, path.tool)
                else:
                    cur_twins.append(toolpath.Toolpath(newpath, path.tool))
            cut_contours.append(path)
            if cur_twins:
                res_twins[path] = cur_twins
        return cut_contours, res_twins
    def widened_contours(self, contours, tool, extension, twins, tabs, tabs_dict, paths_for_helical_entry):
        res = []
        for contour in contours:
            points = contour.path.nodes
            if contour.path.has_arcs():
                points = CircleFitter.interpolate_arcs(points, False, 1)
            offset = cam.contour.plain(shapes.Shape(points, True), 0, True, extension, not contour.path.orientation())
            if offset:
                merged = False
                if len(offset) == 1 and not tabs and not self.entry_exit:
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
                    twins[contour] = [toolpath.Toolpath(i, tool) for i in offset]
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
        return PathOutput([toolpath.Toolpath(Path([PathPoint(self.x, self.y)], True), self.tool)], None, {})
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
        return PathOutput([toolpath.Toolpath(Path(coords, False), self.tool)], None, {})
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
