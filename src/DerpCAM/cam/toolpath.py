from pyclipper import *
from math import *
from ..common.geom import *
from .milling_tool import *

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

class Tabs(object):
    def __init__(self, tabs):
        self.tabs = tabs
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
    # Start and end point coordinates
    def coords(self, path):
        return [tab.coords(path) for tab in self.tabs]

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
    def __init__(self, path, tool, transform=None, helical_entry=None, bounds=None, is_tab=False, segmentation=None, was_previously_cut=False, is_cleanup=False):
        assert isinstance(path, Path)
        self.path = path
        self.tool = tool
        self.transform = transform if not is_tab else None
        self.is_tab = is_tab
        self.transformed_cache = None
        self.lines_to_arcs_cache = None
        self.optimize_lines_cache = None
        self.segmentation = segmentation
        self.was_previously_cut = was_previously_cut
        self.is_cleanup = is_cleanup
        if segmentation and helical_entry is None and segmentation[0][0] == 0 and isinstance(segmentation[0][2], HelicalEntry):
            helical_entry = segmentation[0][2]
        self.helical_entry = helical_entry
        # Allow borrowing bounds from the non-simplified shape to avoid calculating arc bounds
        self.bounds = self.calc_bounds() if bounds is None else bounds
        self.lengths = path.lengths()
        self.tlength = self.lengths[-1]

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
            self.lines_to_arcs_cache = Toolpath(Path(CircleFitter.simplify(self.path.nodes), self.path.closed), self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab, was_previously_cut=self.was_previously_cut, is_cleanup=self.is_cleanup)
        return self.lines_to_arcs_cache

    def optimize_lines(self):
        if self.optimize_lines_cache is None:
            self.optimize_lines_cache = Toolpath(Path(LineOptimizer.simplify(self.path.nodes), self.path.closed), self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab, was_previously_cut=self.was_previously_cut, is_cleanup=self.is_cleanup)
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
        tp = Toolpath(path, self.tool, transform=self.transform, helical_entry=helical_entry, is_tab=is_tab, was_previously_cut=self.was_previously_cut and start == 0, is_cleanup=self.is_cleanup)
        return tp

    def without_circles(self):
        assert self.is_tab
        return Toolpath(self.path.without_circles(), self.tool, helical_entry=self.helical_entry, is_tab=self.is_tab, was_previously_cut=self.was_previously_cut, is_cleanup=self.is_cleanup)

    def cut_by_tabs(self, tabs):
        tabs = sorted(tabs.tabs, key=lambda tab: tab.start)
        pos = 0
        res = []
        helical_entry = self.helical_entry
        for tab in tabs:
            assert tab.start <= tab.end
            if pos < tab.start:
                res.append(self.subpath(pos, tab.start, is_tab=False, helical_entry=helical_entry))
            res.append(self.subpath(tab.start, tab.end, is_tab=True))
            helical_entry = tab.helical_entry
            # No transform on tabs, so that no time is wasted doing trochoidal
            # milling of empty space above the tab
            pos = tab.end
        if pos < self.tlength:
            res.append(self.subpath(pos, self.tlength, is_tab=False, helical_entry=helical_entry))
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
            tablist.append(self.path.point_at(pos + tabw / 2))
        return tablist

    def usertabs(self, tab_locations, width=1):
        tablist = []
        tabw = self.tool.diameter * (1 + width)
        for tab in tab_locations:
            pos, dist = self.path.closest_point(tab)
            pos = pos - tabw / 2
            if pos >= 0:
                if pos + tabw <= self.tlength:
                    tablist.append(self.align_tab_to_segments(pos, pos + tabw))
                else:
                    tablist.append(Tab(pos, self.tlength))
                    tablist.append(Tab(0, pos + tabw - self.tlength))
            else:
                tablist.append(Tab(0, pos + tabw))
                tablist.append(Tab(self.tlength + pos, self.tlength))
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
    def render_as_outlines(self):
        points = CircleFitter.interpolate_arcs(self.path.nodes, False, 2)
        intsFull = PtsToInts(points)
        if self.path.closed:
            intsFull += [intsFull[0]]
        outlines = []
        step = 50
        for i in range(0, len(intsFull), step):
            ints = intsFull[i : i + step + 1]
            ints += ints[::-1]
            pc = PyclipperOffset()
            pc.AddPath(ints, JT_ROUND, ET_OPENROUND)
            #outlines = pc.Execute(res * pen.widthF() / 2)
            initv = min(GeometrySettings.RESOLUTION * self.tool.diameter / 2, 3)
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
            outlines2 += pc.Execute(GeometrySettings.RESOLUTION * self.tool.diameter / 2 - initv)
        outlines = outlines2
        pc = Pyclipper()
        for o in outlines:
            pc.AddPath(o, PT_SUBJECT, True)
        outlines = pc.Execute(CT_UNION, PFT_NONZERO, PFT_NONZERO)
        return [PtsFromInts(ints) for ints in outlines]

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
            d = (tool.diameter + 2 * mr) + margin
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

