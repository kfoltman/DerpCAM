from pyclipper import *
from math import *
from geom import *
from milling_tool import *

class Tab(object):
    def __init__(self, start, end):
        self.start = start
        self.end = end
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
    def __init__(self, path, tool, transform=None, helical_entry=None, bounds=None, is_tab=False):
        assert isinstance(path, Path)
        self.path = path
        self.tool = tool
        self.transform = transform if not is_tab else None
        self.is_tab = is_tab
        self.transformed_cache = None
        self.lines_to_arcs_cache = None
        self.optimize_lines_cache = None
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
            self.optimize_lines_cache = Toolpath(LineOptimizer.simplify(self.path.nodes), self.path.closed, self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab)
        return self.optimize_lines_cache

    def subpath(self, start, end, is_tab=False):
        path = self.path.subpath(start, end)
        tp = Toolpath(path, self.tool, transform=self.transform, is_tab=is_tab)
        tp.helical_entry = None
        return tp

    def cut_by_tabs(self, tabs):
        tabs = sorted(tabs.tabs, key=lambda tab: tab.start)
        pos = 0
        res = []
        for tab in tabs:
            assert tab.start <= tab.end
            if pos < tab.start:
                res.append(self.subpath(pos, tab.start, is_tab=False))
            res.append(self.subpath(tab.start, tab.end, is_tab=True))
            # No transform on tabs, so that no time is wasted doing trochoidal
            # milling of empty space above the tab
            pos = tab.end
        if pos < self.tlength:
            res.append(self.subpath(pos, self.tlength, is_tab=False))
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
                    tablist.append(Tab(pos, pos + tabw))
                else:
                    tablist.append(Tab(pos, self.tlength))
                    tablist.append(Tab(0, pos + tabw - self.tlength))
            else:
                tablist.append(Tab(0, pos + tabw))
                tablist.append(Tab(self.tlength + pos, self.tlength))
        return Tabs(tablist)

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

