import hsm_nibble.voronoi_centers
from DerpCAM.common import geom
from DerpCAM.cam.pocket import sort_polygons, shape_to_polygons, linestring2path, objects_to_polygons
from . import shapes, toolpath, milling_tool
import math, threading
from shapely.geometry import LineString, Point, MultiPolygon
import shapely.affinity, shapely.ops

pyvlock = threading.RLock()

class CarveGraphVertex:
    def __init__(self, point, edges):
        self.point = point
        self.edges = edges
        self.visited = False
        self.strings = []

class CarveGraph:
    def __init__(self, polygon):
        with pyvlock:
            voronoi = hsm_nibble.voronoi_centers.VoronoiCenters(polygon, preserve_edge=True)
        self.voronoi = voronoi
        self.edges = voronoi.edges # int -> LineString
        self.v2e = voronoi.vertex_to_edges # Vertex -> List[int]
        self.e2v = voronoi.edge_to_vertex # int -> (Vertex, Vertex)
        self.edge2maxdia = {}
        self.point2dia = {}
        self.overall_maxdia = 0
        for eid, e in self.edges.items():
            maxdia = 0
            for p in e.coords:
                dia = self.point2dia.get(p)
                if dia is None:
                    dia = self.point2dia[p] = 2 * self.voronoi.distance_from_geom(Point(*p))
                maxdia = max(maxdia, dia)
            self.edge2maxdia[eid] = maxdia
            self.overall_maxdia = max(self.overall_maxdia, maxdia)

    def trim_loops(self, path, min_width):
        # Find sequences of non-cuts, find and delete loops
        start = 0
        i = 0
        while i < len(path):
            point = path[i]
            if point.speed_hint.diameter > min_width:
                if i > start + 1 and self.trim_loop_in(path, start, i):
                    i = start
                    continue
                start = i + 1
            i += 1
        while len(path) > start + 1 and self.trim_loop_in(path, start, len(path)):
            pass
    def trim_loop_in(self, path, start, end):
        first = {}
        for i in range(start, end):
            first_pt = (path[i].x, path[i].y)
            if first_pt not in first:
                first[first_pt] = i
        for i in range(start, end):
            last_pt = (path[i].x, path[i].y)
            if last_pt in first:
                prev = first[last_pt]
                if prev < i:
                    del path[prev : i]
                    return True
        return False
        
    def compute(self, min_width, return_to_start, last_point):
        self.edges_visited = set()
        self.vertexes_visited = set()
        self.vertexes_completed = set()
        start = None
        if last_point is not None:
            for v, e in self.v2e.items():
                if last_point.dist(geom.PathPoint(v[0], v[1])) < 0.001:
                    start = v
                    break
        if start is None:
            for v, e in self.v2e.items():
                if len(e) == 1:
                    start = v
                    break
            else:
                for v, e in self.v2e.items():
                    start = v
                    break
        path = []
        self.handle_vertex(path, min_width, start)
        if not return_to_start:
            while path and path[-1][0] == False:
                path.pop()
        return path
    def opposite(self, eid, vertex):
        vv = self.e2v[eid]
        assert vertex == vv[0] or vertex == vv[1]
        return (vv[1], 1) if vertex == vv[0] else (vv[0], 0)
    def handle_vertex(self, path, min_width, vertex):
        self.vertexes_visited.add(vertex)
        # Handle dead ends first
        for eid in self.v2e[vertex]:
            if eid in self.edges_visited:
                continue
            opposite, orientation = self.opposite(eid, vertex)
            if opposite in self.vertexes_completed or len(self.v2e[opposite]) == 1:
                self.edges_visited.add(eid)
                if self.edge2maxdia[eid] < min_width:
                    continue
                line = self.edges[eid]
                rev_line = LineString(line.coords[::-1])
                if orientation == 0:
                    line, rev_line = rev_line, line
                path.append((True, line))
                path.append((False, rev_line))
        for eid in self.v2e[vertex]:
            if eid in self.edges_visited:
                continue
            opposite, orientation = self.opposite(eid, vertex)
            self.edges_visited.add(eid)
            line = self.edges[eid]
            rev_line = LineString(list(line.coords[::-1]))
            if orientation == 0:
                line, rev_line = rev_line, line
            path.append((self.edge2maxdia[eid] > min_width, line))
            self.handle_vertex(path, min_width, opposite)
            path.append((False, rev_line))
        self.vertexes_completed.add(vertex)
    def to_path(self, min_width, last_point=None):
        path = self.compute(min_width, False, last_point)
        points = []
        for cut, linestring in path:
            for p in linestring.coords:
                points.append(geom.PathPoint(p[0], p[1], toolpath.DesiredDiameter(self.point2dia[p] if cut else 0)))
        self.trim_loops(points, min_width)
        return geom.Path(points, False)

def vcarve(shape, tool, thickness):
    if not shape.closed:
        raise ValueError("Cannot v-carve open polylines")
    if not (tool.tip_angle >= 1 and tool.tip_angle <= 179):
        raise ValueError("V-carving is only supported using tapered tools")
    slope = 0.5 / math.tan((tool.tip_angle * math.pi / 180) / 2)
    max_diameter = min(tool.diameter, thickness / slope + tool.tip_diameter)
    all_inputs = MultiPolygon(shape_to_polygons(shape, tool, -0.5 * tool.diameter, False))
    outputs = []
    while not all_inputs.is_empty:
        patterned_areas = all_inputs.buffer(-max_diameter)
        edges = all_inputs.difference(patterned_areas)
        outputs += [CarveGraph(polygon) for polygon in objects_to_polygons(edges)]
        all_inputs = all_inputs.buffer(-max_diameter * tool.stepover)
    return outputs

