from pyclipper import *
from math import *
from ..common.geom import *
from .milling_tool import *

class RapidMove(object):
    pass

class Tab(object):
    def __init__(self, start, end, helical_entry=None):
        self.start = start
        self.end = end
        # Entry into the part after the tab
        self.helical_entry = helical_entry
    def cut(self, slen, elen, tlen):
        if slen >= self.end or elen <= self.start:
            return True
        if slen >= self.start and elen <= self.end:
            return False
        segs = []
        if slen < self.start:
            segs.append((slen, self.start))
        if elen >= self.end:
            segs.append((self.end, elen))
        return segs
    # Start and end point coordinates
    def coords(self, path):
        return (path_point(path, self.start), path_point(path, self.end))
    def __repr__(self):
        return f"Tab({self.start}, {self.end})"

class Tabs(object):
    def __init__(self, tabs):
        last = 0
        last_tab = None
        newtabs = []
        # Merge overlapping tabs
        for tab in sorted(tabs, key=lambda tab: tab.start):
            if last_tab is not None and tab.start < last_tab.end:
                last_tab.end = max(last_tab.end, tab.end)
            else:
                newtabs.append(tab)
                last_tab = tab
        self.tabs = newtabs
    def cut(self, slen, elen, tlen):
        result = [(slen, elen)]
        for tab in self.tabs:
            nextres = []
            for slen2, elen2 in result:
                res = tab.cut(slen2, elen2, tlen)
                if res is True:
                    nextres.append((slen2, elen2))
                elif res is False:
                    pass # Segment removed entirely
                else:
                    nextres += res
            result = nextres
            if not result:
                return False
        # Convert to relative
        if result == [(slen, elen)]:
            return True
        fres = []
        l = elen - slen
        for s, e in result:
            fres.append(((s - slen) / l, (e - slen) / l))
        return fres
    def roll(self, amount, tlength):
        for i in self.tabs:
            if i.end <= amount:
                i.start = tlength + i.start - amount
                i.end = tlength + i.end - amount
            else:
                i.start -= amount
                i.end -= amount
        self.tabs = sorted(self.tabs, key=lambda tab: tab.start)
    # Start and end point coordinates
    def coords(self, path):
        return [tab.coords(path) for tab in self.tabs]

class TabMaker(object):
    def __init__(self, tab_locations, max_tab_distance, tab_length):
        self.tab_locations = tab_locations
        self.max_tab_distance = max_tab_distance
        self.tab_length = tab_length
    def tabify(self, cut_path, path_notabs):
        tab_inst = path_notabs.usertabs(self.tab_locations, self.max_tab_distance, width=self.tab_length)
        # Make sure the original path starts right after a tab, to eliminate the
        # need for additional re-entry at the start of the path
        breakpoint = path_notabs.roll_breakpoint(tab_inst)
        path_notabs.roll_by_tabs(breakpoint, cut_path.helical_entry_func)
        tab_inst.roll(breakpoint, path_notabs.tlength)
        # Create a tabbed version of the rolled path (it starts right after the tab)
        paths_withtabs = path_notabs.cut_by_tabs(tab_inst, cut_path.helical_entry_func)
        cut_path.correct_helical_entry(paths_withtabs)
        paths_withtabs = [p.with_helical_from_top(not p.is_tab and i != 0) for i, p in enumerate(paths_withtabs)]
        cut_path.generate_preview(paths_withtabs)
        return paths_withtabs

class PlungeEntry(object):
    def __init__(self, point):
        self.start = point

class HelicalEntry(object):
    def __init__(self, point, r, angle=0, climb=True):
        self.point = point
        self.r = r
        self.angle = angle
        self.start = PathPoint(point.x + r * cos(angle), point.y + r * sin(angle))
        self.climb = climb

class Toolpath(object):
    def __init__(self, path, tool, transform=None, helical_entry=None, bounds=None, is_tab=False, segmentation=None, was_previously_cut=False, is_cleanup=False, helical_from_top=False, tab_maker=None):
        assert isinstance(path, Path)
        assert path.nodes
        self.path = path
        self.tool = tool
        self.transform = transform if not is_tab else None
        self.is_tab = is_tab
        self.transformed_cache = None
        self.lines_to_arcs_cache = None
        self.optimize_lines_cache = None
        self.segmentation = segmentation
        self.was_previously_cut = was_previously_cut
        self.helical_from_top = helical_from_top
        self.is_cleanup = is_cleanup
        if segmentation and helical_entry is None and segmentation[0][0] == 0 and isinstance(segmentation[0][2], HelicalEntry):
            helical_entry = segmentation[0][2]
        self.helical_entry = helical_entry
        # Allow borrowing bounds from the non-simplified shape to avoid calculating arc bounds
        self.bounds = self.calc_bounds() if bounds is None else bounds
        self.lengths = path.lengths()
        self.tlength = self.lengths[-1]
        self.tab_maker = tab_maker

    def transformed(self):
        if self.transform is None:
            return self
        if self.transformed_cache is None:
            self.transformed_cache = self.transform(self)
        return self.transformed_cache

    def calc_bounds(self):
        if self.path.is_empty():
            return None
        xcoords = [p.x for p in self.path.nodes if p.is_point()]
        ycoords = [p.y for p in self.path.nodes if p.is_point()]
        tr = 0.5 * self.tool.diameter
        return (min(xcoords) - tr, min(ycoords) - tr, max(xcoords) + tr, max(ycoords) + tr)

    def lines_to_arcs(self):
        if self.lines_to_arcs_cache is None:
            self.lines_to_arcs_cache = Toolpath(Path(CircleFitter.simplify(self.path.nodes), self.path.closed), self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab, was_previously_cut=self.was_previously_cut, is_cleanup=self.is_cleanup, helical_from_top=self.helical_from_top, tab_maker=self.tab_maker)
        return self.lines_to_arcs_cache

    def optimize_lines(self):
        if self.optimize_lines_cache is None:
            self.optimize_lines_cache = Toolpath(Path(LineOptimizer.simplify(self.path.nodes), self.path.closed), self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab, was_previously_cut=self.was_previously_cut, is_cleanup=self.is_cleanup, helical_from_top=self.helical_from_top, tab_maker=self.tab_maker)
        return self.optimize_lines_cache

    def optimize(self):
        path = self
        if GeometrySettings.simplify_arcs:
            path = path.lines_to_arcs()
        if GeometrySettings.simplify_lines:
            path = path.optimize_lines()
        return path

    def subpath(self, start, end, is_tab=False, helical_entry=None):
        path = self.path.subpath(start, end)
        if path is None:
            return None
        tp = Toolpath(path, self.tool, transform=self.transform, helical_entry=helical_entry, is_tab=is_tab, was_previously_cut=self.was_previously_cut and start == 0, is_cleanup=self.is_cleanup, tab_maker=self.tab_maker)
        return tp

    def for_tab_below(self):
        return self.without_circles() if self.is_tab else self.with_helical_from_top(False)

    def without_circles(self):
        assert self.is_tab
        return Toolpath(self.path.without_circles(), self.tool, helical_entry=self.helical_entry, is_tab=self.is_tab, was_previously_cut=self.was_previously_cut, is_cleanup=self.is_cleanup, helical_from_top=False, tab_maker=self.tab_maker)

    def with_helical_from_top(self, value=True):
        assert not value or not self.is_tab
        if self.helical_from_top == value:
            return self
        return Toolpath(self.path, self.tool, helical_entry=self.helical_entry, is_tab=self.is_tab, was_previously_cut=self.was_previously_cut, is_cleanup=self.is_cleanup, helical_from_top=value, tab_maker=self.tab_maker)

    def roll_breakpoint(self, tabs):
        if not tabs.tabs:
            return
        return tabs.tabs[0].end

    def roll_by_tabs(self, breakpoint, helical_entry_func):
        if not breakpoint:
            return
        self.path = self.path.subpath(breakpoint, self.tlength).joined(self.path.subpath(0, breakpoint))
        self.helical_entry = helical_entry_func(self.path) if helical_entry_func else None
        # No need for entry from the top for the untabbed part of the path
        self.helical_from_top = False

    def cut_by_tabs(self, tabs, helical_entry_func):
        tabs = sorted(tabs.tabs, key=lambda tab: tab.start)
        pos = 0
        res = []
        def add_subpath(sp):
            if sp is not None and not sp.is_empty():
                res.append(sp)
        helical_entry = self.helical_entry
        for tab in tabs:
            assert tab.start <= tab.end
            if pos < tab.start:
                add_subpath(self.subpath(pos, tab.start, is_tab=False, helical_entry=helical_entry))
            add_subpath(self.subpath(tab.start, tab.end, is_tab=True))
            helical_entry = tab.helical_entry
            # No transform on tabs, so that no time is wasted doing trochoidal
            # milling of empty space above the tab
            pos = tab.end
        if pos < self.tlength:
            add_subpath(self.subpath(pos, self.tlength, is_tab=False, helical_entry=helical_entry))
        if helical_entry_func:
            for i in res:
                if i.helical_entry is None and not i.is_tab:
                    i.helical_entry = helical_entry_func(i.path)
        return res

    def flattened(self):
        return [self]

    def autotabs(self, tool, ntabs, width=1):
        if not ntabs:
            return []
        orient = self.path.orientation()
        tlength = self.path.length()
        offset = tlength / (2 * ntabs)
        tablist = []
        tabw = tool.diameter * (1 + width)
        for i in range(ntabs):
            pos = offset + i * tlength / ntabs
            if orient:
                pos = tlength - pos
            tablist.append(self.path.point_at(pos))
        return tablist

    def usertabs(self, tab_locations, maxdist, width=1):
        tablist = []
        tabw = self.tool.diameter * (1 + width)
        if 2 * tabw < self.tlength:
            for tab in tab_locations:
                pos, dist = self.path.closest_point(tab)
                if dist <= maxdist:
                    start = pos - tabw / 2
                    end = pos + tabw / 2
                    if start < 0:
                        start += self.tlength
                    if end > self.tlength:
                        end -= self.tlength
                    inc = tabw / 8
                    for i in range(4):
                        p1 = self.path.point_at(start)
                        p2 = self.path.point_at(end)
                        if p1.dist(p2) <= 0.99 * tabw:
                            start -= inc
                            end += inc
                            if start < 0:
                                start += self.tlength
                            if end > self.tlength:
                                end -= self.tlength
                        else:
                            break
                    if start < end:
                        tablist.append(self.align_tab_to_segments(start, end))
                    else:
                        tablist.append(self.align_tab_to_segments(start, self.tlength))
                        tablist.append(self.align_tab_to_segments(0, end))
        return Tabs(tablist)

    def align_tab_to_segments(self, spos, epos):
        helical_entry = None
        if self.segmentation:
            cspos = 0
            cepos = None
            for pos1, pos2, he in self.segmentation:
                if pos2 < spos:
                    cspos = pos2
                if cepos is None and pos1 >= epos:
                    cepos = pos1
                    helical_entry = he
            if cepos is None:
                cepos = epos
            #print (spos, epos, '->', cspos, cepos)
            spos, epos = cspos, cepos
        return Tab(spos, epos, helical_entry)

    def tabify(self, cutpath):
        if not self.tab_maker:
            return self
        return Toolpaths(self.tab_maker.tabify(cutpath, self))

    def render_as_outlines(self):
        points = CircleFitter.interpolate_arcs(self.path.nodes, False, 2)
        resolution = GeometrySettings.RESOLUTION
        offset = resolution * self.tool.diameter / 2
        if offset > 200:
            resolution *= 200 / offset
            offset = resolution * self.tool.diameter / 2
        intsFull = PtsToInts(points, resolution)
        if self.path.closed:
            intsFull += [intsFull[0]]
        outlines = []
        step = 50
        for i in range(0, len(intsFull), step):
            ints = intsFull[i : i + step + 1]
            ints += ints[::-1]
            pc = PyclipperOffset()
            pc.AddPath(ints, JT_ROUND, ET_OPENROUND)
            initv = min(offset, 3)
            res = pc.Execute(initv)
            if res:
                outlines += res

        if is_calculation_cancelled():
            return []
        pc = Pyclipper()
        for o in outlines:
            pc.AddPath(o, PT_SUBJECT, True)
        outlines = pc.Execute(CT_UNION, PFT_NONZERO, PFT_NONZERO)
        outlines2 = []
        for o in outlines:
            if is_calculation_cancelled():
                return []
            pc = PyclipperOffset()
            pc.AddPath(o, JT_ROUND, ET_CLOSEDLINE)
            outlines2 += pc.Execute(offset - initv)
        outlines = outlines2
        pc = Pyclipper()
        for o in outlines:
            pc.AddPath(o, PT_SUBJECT, True)
        outlines = pc.Execute(CT_UNION, PFT_NONZERO, PFT_NONZERO)
        return [PtsFromInts(ints, resolution) for ints in outlines]
    def is_empty(self):
        return self.path.is_empty()

class Toolpaths(object):
    def __init__(self, toolpaths):
        self.set_toolpaths(toolpaths)
    def set_toolpaths(self, toolpaths):
        self.toolpaths = toolpaths
        self.bounds = self.calc_bounds()
        self.flattened_cache = self.calc_flattened()
    def flattened(self):
        return self.flattened_cache
    def calc_flattened(self):
        res = []
        for path in self.toolpaths:
            if isinstance(path, Toolpaths):
                res += path.flattened()
            elif isinstance(path, Toolpath):
                res.append(path)
            else:
                assert False, f"Unexpected type: {type(path)}"
        return res
    def calc_bounds(self):
        return max_bounds(*[tp.bounds for tp in self.toolpaths])
    def lines_to_arcs(self):
        return Toolpaths([tp.lines_to_arcs() for tp in self.toolpaths])
    def optimize_lines(self):
        return Toolpaths([tp.optimize_lines() for tp in self.toolpaths])
    def optimize(self):
        return Toolpaths([tp.optimize() for tp in self.toolpaths])
    def is_empty(self):
        return all([tp.is_empty() for tp in self.toolpaths])
    def for_tab_below(self):
        return Toolpaths([i.for_tab_below() for i in self.toolpaths])

def findPathNesting(tps):
    nestings = []
    contours = Toolpaths(tps).flattened()
    contours = sorted(contours, key=lambda item: bounds_area(item.bounds))
    for subtp in contours:
        for children in nestings:
            if inside_bounds(children[-1].bounds, subtp.bounds):
                # subtp contains this chain of contours
                children.append(subtp)
                break
        else:
            # Doesn't contain any earlier contour, so start a nesting.
            nestings.append([subtp])
    return nestings

def fixPathNesting(tps):
    nestings = findPathNesting(tps)
    res = []
    nestings = sorted(nestings, key=len)
    for nesting in nestings:
        res += nesting
    return res

# XXXKF this may cut corners sometimes, need to add collision checking
def joinClosePaths(tps):
    def findClosest(points, lastpt, diameter):
        mindist = None
        closest = 0
        for i, pt in enumerate(points):
            if i == 0 or dist(lastpt, pt) < mindist:
                closest = i
                mindist = dist(lastpt, pt)
        if closest > 0 and mindist <= diameter:
            points = points[closest:] + points[:closest]
        return points, mindist

    tps = fixPathNesting(tps)
    last = None
    res = []
    for tp in tps:
        if isinstance(tp, Toolpaths):
            res.append(tp)
            last = None
            continue
        if last is not None and last.tool is tp.tool:
            points = tp.path.nodes
            found = False
            if tp.path.closed:
                points, mindist = findClosest(points, lastpt, tp.tool.diameter)
                if mindist > tp.tool.diameter:
                    # Desperate second-chance joining by retracing the already milled path
                    # XXXKF this is rather bad, O(N^2), needs rethinking
                    for j in range(len(last.path.nodes) - 1, 0, -1):
                        points, mindist = findClosest(points, last.path.nodes[j], tp.tool.diameter)
                        if mindist <= tp.tool.diameter:
                            res[-1] = Toolpath(Path(last.path.nodes + (last.path.nodes[0:1] if last.path.closed else []) + last.path.nodes[:j - 1:-1] + points + points[0:1], False), tp.tool)
                            last = res[-1]
                            lastpt = last.path.nodes[-1]
                            found = True
                            break
            if found:
                continue
            if dist(lastpt, points[0]) <= tp.tool.diameter:
                res[-1] = Toolpath(Path(last.path.nodes + (last.path.nodes[0:1] if last.path.closed else []) + points + (points[0:1] if tp.path.closed else []), False), tp.tool)
                last = res[-1]
                lastpt = last.path.nodes[-1]
                continue
        res.append(tp)
        lastpt = tp.path.seg_end()
        last = tp
    return res

def joinClosePathsWithCollisionCheck(tps, boundary, islands):
    def findClosest(points, lastpt, diameter):
        mindist = None
        closest = 0
        for i, pt in enumerate(points):
            if i == 0 or dist(lastpt, pt) < mindist:
                closest = i
                mindist = dist(lastpt, pt)
        if closest > 0 and mindist <= diameter:
            points = points[closest:] + points[:closest]
        return points, mindist

    last = None
    res = []
    for tp in tps:
        if isinstance(tp, Toolpaths):
            res.append(tp)
            last = None
            continue
        if last is not None and last.tool is tp.tool:
            points = tp.path.nodes
            found = False
            if tp.path.closed:
                points, mindist = findClosest(points, lastpt, tp.tool.diameter)
                if dist(lastpt, points[0]) <= tp.tool.diameter:
                    new_path = IntPath([lastpt, points[0]])
                    if new_path.int_points[0] == new_path.int_points[1]:
                        res[-1] = Toolpath(Path(last.path.nodes + (last.path.nodes[0:1] if last.path.closed else []) + points + (points[0:1] if tp.path.closed else []), False), tp.tool)
                        last = res[-1]
                        lastpt = last.path.nodes[-1]
                        continue
                    # XXXKF workaround clipper bug
                    if not boundary or not run_clipper_checkpath(CT_DIFFERENCE, subject_polys=[], clipper_polys=boundary, subject_paths=[new_path], fillMode=PFT_NONZERO):
                        if not islands or not run_clipper_checkpath(CT_INTERSECTION, subject_polys=[], clipper_polys=islands, subject_paths=[new_path], fillMode=PFT_NONZERO):
                            res[-1] = Toolpath(Path(last.path.nodes + (last.path.nodes[0:1] if last.path.closed else []) + points + (points[0:1] if tp.path.closed else []), False), tp.tool)
                            last = res[-1]
                            lastpt = last.path.nodes[-1]
                            continue
        res.append(tp)
        lastpt = tp.path.seg_end()
        last = tp
    return res

def findHelicalEntryPoints(toolpaths, tool, boundary, islands, margin):
    boundary_path = IntPath(boundary)
    boundary_path = boundary_path.force_orientation(True)
    island_paths = [IntPath(i).force_orientation(True) for i in islands]
    for tp in toolpaths:
        if type(tp) is Toolpaths:
            findHelicalEntryPoints(tp.toolpaths, tool, boundary, islands, margin)
            continue
        candidates = [tp.path.nodes[0]]
        if len(tp.path.nodes) > 1 and False:
            p1 = tp.path.nodes[0]
            p2 = tp.path.nodes[1]
            mid = p1
            angle = atan2(p2[1] - p1[1], p2[0] - p1[0]) + pi / 2
            d = tool.diameter * 0.5
            candidates.append((mid[0] + cos(angle) * d, mid[1] + sin(angle) * d))
            d = tool.diameter * -0.5
            candidates.append((mid[0] + cos(angle) * d, mid[1] + sin(angle) * d))
        for start in candidates:
            # Size of the helical entry hole
            mr = tool.min_helix_diameter
            d = (tool.diameter + 2 * mr) + 2 * margin
            c = IntPath(circle(start.x, start.y, d / 2))
            # Check if it sticks outside of the final shape
            # XXXKF could be optimized by doing a simple bounds check first
            if run_clipper_simple(CT_DIFFERENCE, [c], [boundary_path], bool_only=True):
                continue
            # Check for collision with islands
            if islands and any([run_clipper_simple(CT_INTERSECTION, [i], [c], bool_only=True) for i in island_paths]):
                continue
            tp.helical_entry = HelicalEntry(start, mr)
            break

def startWithClosestPoint(path, pt, dia):
    mindist = None
    mdpos = None
    for j, pt2 in enumerate(path.path.nodes):
        d = dist(pt, pt2)
        if mindist is None or d < mindist:
            mindist = d
            mdpos = j
    if mindist <= dia:
        path.path.nodes = path.path.nodes[mdpos:] + path.path.nodes[:mdpos + 1]
        return True
    return False

def mergeToolpaths(tps, new, dia):
    if type(new) is Toolpath:
        new = [new]
    else:
        new = new.toolpaths
    if not tps:
        tps.insert(0, Toolpaths(new))
        return
    last = tps[-1]
    new2 = []
    for i in new:
        assert i.path.closed
        pt = i.path.seg_start()
        found = False
        new_toolpaths = []
        for l in last.toolpaths:
            if found:
                new_toolpaths.append(l)
                continue
            if startWithClosestPoint(l, pt, dia):
                new_toolpaths.append(i)
                new_toolpaths.append(l)
                found = True
            else:
                new_toolpaths.append(l)
        if not found:
            new_toolpaths.append(i)
        last.set_toolpaths(new_toolpaths)

