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

class Toolpath(object):
    def __init__(self, points, closed, tool, transform=None, helical_entry=None, bounds=None, is_tab=False):
        self.points = points
        self.closed = closed
        self.tool = tool
        self.transform = transform if not is_tab else None
        self.is_tab = is_tab
        self.transformed_cache = None
        self.lines_to_arcs_cache = None
        self.helical_entry = helical_entry
        # Allow borrowing bounds from the non-simplified shape to avoid calculating arc bounds
        self.bounds = self.calc_bounds() if bounds is None else bounds
        self.tlength = 0
        self.lengths = [0]
        for i in range(1, len(self.points)):
            self.tlength += dist(self.points[i - 1], self.points[i])
            self.lengths.append(self.tlength)
        if self.closed:
            self.tlength += dist(self.points[- 1], self.points[0])
            self.lengths.append(self.tlength)

    def transformed(self):
        if self.transform is None:
            return self
        if self.transformed_cache is None:
            self.transformed_cache = self.transform(self)
        return self.transformed_cache

    def calc_bounds(self):
        xcoords = [p[0] for p in self.points]
        ycoords = [p[1] for p in self.points]
        tr = 0.5 * self.tool.diameter
        return (min(xcoords) - tr, min(ycoords) - tr, max(xcoords) + tr, max(ycoords) + tr)

    def lines_to_arcs(self):
        if self.lines_to_arcs_cache is None:
            self.lines_to_arcs_cache = Toolpath(CircleFitter.simplify(self.points), self.closed, self.tool, transform=self.transform, helical_entry=self.helical_entry, bounds=self.bounds, is_tab=self.is_tab)
        return self.lines_to_arcs_cache

    def subpath(self, start, end, is_tab=False):
        points = calc_subpath(self.points, start, end, self.closed)
        if points[0] == points[-1]:
            tp = Toolpath(points[:-1], True, self.tool, transform=self.transform, is_tab=is_tab)
        else:
            tp = Toolpath(points, False, self.tool, transform=self.transform, is_tab=is_tab)
        tp.helical_entry = None
        return tp

    def eliminate_tabs2(self, tabs):
        ptsc = self.points if not self.closed else self.points + [self.points[0]]
        tabs = sorted(tabs.tabs, key=lambda tab: tab.start)
        pos = 0
        res = []
        for tab in tabs:
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

    def autotabs(self, ntabs, offset=0, width=1):
        tablist = []
        pos = offset
        tabw = self.tool.diameter * (1 + width)
        for i in range(ntabs):
            tablist.append(Tab(pos, pos + tabw))
            pos += self.tlength / ntabs
        return Tabs(tablist)

    def usertabs(self, tab_locations, width=1):
        tablist = []
        tabw = self.tool.diameter * (1 + width)
        for tab in tab_locations:
            pos, dist = closest_point(self.points, self.closed, tab)
            pos = max(0, pos - tabw / 2)
            tablist.append(Tab(pos, pos + tabw))
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

