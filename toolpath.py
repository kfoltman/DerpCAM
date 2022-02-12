from pyclipper import *
from math import *
from geom import *
from milling_tool import *

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

class Toolpath(object):
    def __init__(self, path, tool, transform=None, helical_entry=None, bounds=None, is_tab=False, segmentation=None):
        assert isinstance(path, Path)
        self.path = path
        self.tool = tool
        self.transform = transform if not is_tab else None
        self.is_tab = is_tab
        self.transformed_cache = None
        self.lines_to_arcs_cache = None
        self.optimize_lines_cache = None
        self.segmentation = segmentation
        if segmentation and not helical_entry and segmentation[0][0] == 0:
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
        assert len(self.path.nodes)
        xcoords = [p.x for p in self.path.nodes if p.is_point()]
        ycoords = [p.y for p in self.path.nodes if p.is_point()]
        tr = 0.5 * self.tool.diameter
        return (min(xcoords) - tr, min(ycoords) - tr, max(xcoords) + tr, max(ycoords) + tr)

    def lines_to_arcs(self):
        if self.lines_to_arcs_cache is None:
            self.lines_to_arcs_cache = Toolpath(Path(CircleFitter.simplify(self.path.nodes), self.path.closed), self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab)
        return self.lines_to_arcs_cache

    def optimize_lines(self):
        if self.optimize_lines_cache is None:
            self.optimize_lines_cache = Toolpath(Path(LineOptimizer.simplify(self.path.nodes), self.path.closed), self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab)
        return self.optimize_lines_cache

    def subpath(self, start, end, is_tab=False, helical_entry=None):
        path = self.path.subpath(start, end)
        tp = Toolpath(path, self.tool, transform=self.transform, helical_entry=helical_entry, is_tab=is_tab)
        return tp

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
        points = CircleFitter.interpolate_arcs(self.path.nodes, False, 1)
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
        #print (len(outlines))
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
            else:
                res.append(path)
        return res
    def calc_bounds(self):
        return max_bounds(*[tp.bounds for tp in self.toolpaths])

