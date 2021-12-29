from pyclipper import *
from math import *
from geom import *
from process import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

def sort_polygons(polygons):
    bounds = []
    for i, pts in enumerate(polygons):
        x = [p.x() for p in pts]
        y = [p.y() for p in pts]
        bounds.append((min(x), min(y), max(x), max(y)))

    inside_which = [None] * len(bounds)
    # Not the fastest method, but it works for now. I may improve it if there
    # is a good reason to spend time on it.
    # Also: it handles one level of nesting. Which is fine for simple text, but
    # might run into issues with complex fonts.
    for i, pts in enumerate(bounds):
        for j, pts2 in enumerate(bounds):
            if i == j:
                continue
            if inside_bounds(bounds[i], bounds[j]):
                inside_which[i] = j
                break

    output = []
    for i in range(len(bounds)):
        if inside_which[i] is None:
            islands = []
            for j in range(len(bounds)):
                if inside_which[j] == i:
                    islands.append(polygons[j])
            output.append((polygons[i], islands))
    return output

def text_to_shapes(x, y, width, height, text, font_family, size, weight, italic):
    font = QFont(font_family, size * GeometrySettings.RESOLUTION, weight, italic)
    metrics = QFontMetrics(font)
    twidth = metrics.horizontalAdvance(text) / GeometrySettings.RESOLUTION
    theight = metrics.height() / GeometrySettings.RESOLUTION

    x += width / 2 - twidth / 2
    y += height / 2 - metrics.capHeight() / 2 / GeometrySettings.RESOLUTION

    ppath = QPainterPath()
    ppath.addText(0, 0, font, text)
    polygons = ppath.toSubpathPolygons()

    shapes = []
    for outline, islands in sort_polygons(polygons):
        # print (outline, islands)
        pts = [(x + q.x() / GeometrySettings.RESOLUTION, y - q.y() / GeometrySettings.RESOLUTION) for q in outline]
        islands_out = []
        for i in islands:
            islands_out.append([(x + q.x() / GeometrySettings.RESOLUTION, y - q.y() / GeometrySettings.RESOLUTION) for q in i])
        if pts[0] == pts[-1]:
            shapes.append(Shape(pts[:-1], True, islands_out))
        else:
            shapes.append(Shape(pts, False, islands_out))
    return shapes
