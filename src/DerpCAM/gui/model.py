import os.path
import math
import sys
import threading
import time
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import pyclipper
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.common import geom
from DerpCAM.common.guiutils import Format, Spinner, is_gui_application
from DerpCAM import cam
from DerpCAM.cam import dogbone, gcodegen, shapes, milling_tool

from . import canvas, inventory
from .propsheet import EnumClass, IntEditableProperty, \
    FloatDistEditableProperty, EnumEditableProperty, SetEditableProperty, \
    RefEditableProperty, StringEditableProperty, FontEditableProperty

import ezdxf
import json

debug_inventory_matching = False

class InvalidateAspect:
    PROPERTIES = 1
    CAM = 2

class CAMTreeItem(QStandardItem):
    def __init__(self, document, name=None):
        QStandardItem.__init__(self, name)
        self.document = document
        self.setEditable(False)
    def emitPropertyChanged(self, name=""):
        self.document.propertyChanged.emit(self, name)
    def format_item_as(self, role, def_value, bold=None, italic=None, color=None):
        if role == Qt.FontRole:
            font = QFont()
            if bold is not None:
                font.setBold(bold)
            if italic is not None:
                font.setItalic(italic)
            return QVariant(font)
        if color is not None and role == Qt.TextColorRole:
            return QVariant(color)
        return def_value

    def store(self):
        dump = {}
        dump['_type'] = type(self).__name__
        for prop in self.properties():
            dump[prop.attribute] = getattr(self, prop.attribute)
        return dump
    def class_specific_load(self, dump):
        pass
    def reload(self, dump):
        rtype = dump['_type']
        if rtype != type(self).__name__:
            if not (rtype == 'MaterialTreeItem' and isinstance(self, WorkpieceTreeItem)):
                raise ValueError("Unexpected type: %s" % rtype)
        for prop in self.properties():
            if prop.attribute in dump:
                setattr(self, prop.attribute, dump[prop.attribute])
        self.class_specific_load(dump)

    @staticmethod
    def load(document, dump):
        rtype = dump['_type']
        if rtype == 'DrawingTreeItem':
            res = DrawingTreeItem(document)
        elif rtype == 'DrawingItemTreeItem':
            res = DrawingItemTreeItem(document)
        elif rtype == 'MaterialTreeItem' or rtype == 'WorkpieceTreeItem':
            res = WorkpieceTreeItem(document)
        elif rtype == 'ToolTreeItem':
            res = ToolTreeItem(document)
        elif rtype == 'OperationTreeItem':
            res = OperationTreeItem(document)
        else:
            raise ValueError("Unexpected item type: %s" % rtype)
        res.reload(dump)
        return res
    def properties(self):
        return []
    def reorderItemImpl(self, direction, parent):
        row = self.row()
        if direction < 0 and row > 0:
            self.document.opMoveItem(parent, self, parent, row - 1)
            return self.index()
        elif direction > 0 and row < parent.rowCount() - 1:
            self.document.opMoveItem(parent, self, parent, row + 1)
            return self.index()
        return None
    def items(self):
        i = 0
        while i < self.rowCount():
            yield self.child(i)
            i += 1
    def __hash__(self):
        return id(self)
    def __eq__(self, other):
        return other is self
    def __ne__(self, other):
        return other is not self

class DrawingItemTreeItem(CAMTreeItem):
    defaultGrayPen = QPen(QColor(0, 0, 0, 64), 0)
    defaultDrawingPen = QPen(QColor(0, 0, 0, 255), 0)
    selectedItemDrawingPen = QPen(QColor(0, 64, 128, 255), 2)
    selectedItemDrawingPen2 = QPen(QColor(0, 64, 128, 255), 2)
    next_drawing_item_id = 1
    def __init__(self, document):
        CAMTreeItem.__init__(self, document)
        self.shape_id = DrawingItemTreeItem.next_drawing_item_id
        DrawingItemTreeItem.next_drawing_item_id += 1
    def __hash__(self):
        return hash(self.shape_id)
    def selectedItemPenFunc(self, item, scale):
        # avoid draft behaviour of thick lines
        return QPen(self.selectedItemDrawingPen.color(), self.selectedItemDrawingPen.widthF() / scale), False
    def selectedItemPen2Func(self, item, scale):
        return QPen(self.selectedItemDrawingPen2.color(), self.selectedItemDrawingPen2.widthF() / scale), False
    def penForPath(self, path, modeData):
        if modeData[0] == canvas.DrawingUIMode.MODE_ISLANDS:
            if modeData[1].shape_id == self.shape_id:
                return self.defaultDrawingPen
            if self.shape_id in modeData[1].islands:
                return self.selectedItemPen2Func
            if geom.bounds_overlap(self.bounds, modeData[1].orig_shape.bounds):
                return self.defaultDrawingPen
            return self.defaultGrayPen
        if modeData[0] == canvas.DrawingUIMode.MODE_TABS:
            if modeData[1].shape_id == self.shape_id:
                return self.defaultDrawingPen
            return self.defaultGrayPen
        return lambda item, scale: self.selectedItemPenFunc(item, scale) if self.untransformed in path.selection else (self.defaultDrawingPen, False)
    def store(self):
        return { '_type' : type(self).__name__, 'shape_id' : self.shape_id }
    @classmethod
    def load(klass, document, dump):
        rtype = dump['_type']
        if rtype == 'DrawingPolyline' or rtype == 'DrawingPolylineTreeItem':
            points = [geom.PathNode.from_tuple(i) for i in dump['points']]
            item = DrawingPolylineTreeItem(document, points, dump.get('closed', True))
        elif rtype == 'DrawingCircle' or rtype == 'DrawingCircleTreeItem':
            item = DrawingCircleTreeItem(document, geom.PathPoint(dump['cx'], dump['cy']), dump['r'])
        elif rtype == 'DrawingTextTreeItem':
            item = DrawingTextTreeItem(document, geom.PathPoint(dump['x'], dump['y']), dump.get('target_width', None),
                DrawingTextStyle(dump['height'], dump['width'], dump['halign'], dump['valign'], dump['angle'], dump['font'], dump.get('spacing', 0)), dump['text'])
        else:
            raise ValueError("Unexpected type: %s" % rtype)
        item.shape_id = dump['shape_id']
        klass.next_drawing_item_id = max(item.shape_id + 1, klass.next_drawing_item_id)
        return item
    def onPropertyValueSet(self, name):
        self.emitPropertyChanged(name)
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(self.textDescription())
        return CAMTreeItem.data(self, role)
    def invalidatedObjects(self, aspect):
        if aspect == InvalidateAspect.CAM:
            return set([self] + self.document.allOperations(lambda item: item.usesShape(self.shape_id)))
        # Settings of operations are not affected and don't need to be refreshed
        return set([self])

class DrawingCircleTreeItem(DrawingItemTreeItem):
    prop_x = FloatDistEditableProperty("Centre X", "x", Format.coord, unit="mm", allow_none=False)
    prop_y = FloatDistEditableProperty("Centre Y", "y", Format.coord, unit="mm", allow_none=False)
    prop_dia = FloatDistEditableProperty("Diameter", "diameter", Format.coord, unit="mm", min=0, allow_none=False)
    prop_radius = FloatDistEditableProperty("Radius", "radius", Format.coord, unit="mm", min=0, allow_none=False)
    def __init__(self, document, centre, r, untransformed = None):
        DrawingItemTreeItem.__init__(self, document)
        self.centre = centre
        self.r = r
        self.calcBounds()
        self.untransformed = untransformed if untransformed is not None else self
    def properties(self):
        return [self.prop_x, self.prop_y, self.prop_dia, self.prop_radius]
    def getPropertyValue(self, name):
        if name == 'x':
            return self.centre.x
        elif name == 'y':
            return self.centre.y
        elif name == 'radius':
            return self.r
        elif name == 'diameter':
            return 2 * self.r
        else:
            assert False, "Unknown property: " + name
    def setPropertyValue(self, name, value):
        if name == 'x':
            self.centre = geom.PathPoint(value, self.centre.y)
        elif name == 'y':
            self.centre = geom.PathPoint(self.centre.x, value)
        elif name == 'radius':
            self.r = value
        elif name == 'diameter':
            self.r = value / 2.0
        else:
            assert False, "Unknown property: " + name
        self.emitPropertyChanged(name)
    def calcBounds(self):
        self.bounds = (self.centre.x - self.r, self.centre.y - self.r,
            self.centre.x + self.r, self.centre.y + self.r)
    def distanceTo(self, pt):
        return abs(geom.dist(self.centre, pt) - self.r)
    def renderTo(self, path, modeData):
        path.addLines(self.penForPath(path, modeData), geom.circle(self.centre.x, self.centre.y, self.r), True)
    def label(self):
        return "Circle%d" % self.shape_id
    def textDescription(self):
        return self.label() + (f" {Format.point(self.centre)} \u2300{Format.coord(2 * self.r)}")
    def toShape(self):
        return shapes.Shape.circle(self.centre.x, self.centre.y, self.r)
    def translated(self, dx, dy):
        cti = DrawingCircleTreeItem(self.document, self.centre.translated(dx, dy), self.r, self.untransformed)
        cti.shape_id = self.shape_id
        return cti
    def scaled(self, cx, cy, scale):
        return DrawingCircleTreeItem(self.document, self.centre.scaled(cx, cy, scale), self.r * scale, self.untransformed)
    def store(self):
        res = DrawingItemTreeItem.store(self)
        res['cx'] = self.centre.x
        res['cy'] = self.centre.y
        res['r'] = self.r
        return res
    def startEndPos(self):
        p = geom.PathPoint(self.centre.x + self.r, self.centre.y)
        return (p, p)

class DrawingPolylineTreeItem(DrawingItemTreeItem):
    def __init__(self, document, points, closed, untransformed=None, src_name=None):
        DrawingItemTreeItem.__init__(self, document)
        self.points = points
        self.closed = closed
        self.untransformed = untransformed if untransformed is not None else self
        self.src_name = src_name
        self.calcBounds()
    def store(self):
        res = DrawingItemTreeItem.store(self)
        res['points'] = [ i.as_tuple() for i in self.points ]
        res['closed'] = self.closed
        return res
    def distanceTo(self, pt):
        if not self.points:
            return None
        path = geom.Path(self.points, self.closed)
        closest, mindist = path.closest_point(pt)
        return mindist
    def translated(self, dx, dy):
        pti = DrawingPolylineTreeItem(self.document, [p.translated(dx, dy) for p in self.points], self.closed, self.untransformed)
        pti.shape_id = self.shape_id
        return pti
    def scaled(self, cx, cy, scale):
        return DrawingPolylineTreeItem(self.document, [p.scaled(cx, cy, scale) for p in self.points], self.closed, self.untransformed)
    def renderTo(self, path, modeData):
        path.addLines(self.penForPath(path, modeData), geom.CircleFitter.interpolate_arcs(self.points, False, path.scalingFactor()), self.closed)
    def calcBounds(self):
        if self.points:
            self.bounds = geom.Path(self.points, self.closed).bounds()
        else:
            self.bounds = None
    def label(self):
        if len(self.points) == 2:
            if self.points[1].is_point():
                return "Line%d" % self.shape_id
            else:
                return "Arc%d" % self.shape_id
        if self.src_name is not None:
            return self.src_name + str(self.shape_id)
        return "Polyline%d" % self.shape_id
    def textDescription(self):
        if len(self.points) == 2:
            if self.points[1].is_point():
                return self.label() + (f"{Format.point(self.points[0], brief=True)}-{Format.point(self.points[1], brief=True)}")
            else:
                assert self.points[1].is_arc()
                arc = self.points[1]
                c = arc.c
                return self.label() + "(X=%s, Y=%s, R=%s, start=%0.2f\u00b0, span=%0.2f\u00b0" % (Format.coord(c.cx, brief=True), Format.coord(c.cy, brief=True), Format.coord(c.r, brief=True), arc.sstart * 180 / math.pi, arc.sspan * 180 / math.pi)
        return self.label() + f"{Format.point_tuple(self.bounds[:2], brief=True)}-{Format.point_tuple(self.bounds[2:], brief=True)}"
    def toShape(self):
        return shapes.Shape(geom.CircleFitter.interpolate_arcs(self.points, False, 1.0), self.closed)
    @staticmethod
    def ellipse(document, centre, major, ratio, start_param, end_param):
        zero = geom.PathPoint(0, 0)
        if end_param < start_param:
            end_param += 2 * math.pi
        major_r = zero.dist(major)
        major_angle = major.angle_to(zero)
        n = int((end_param - start_param) * major_r * geom.GeometrySettings.RESOLUTION)
        points = []
        limit = n + 1
        closed = False
        if end_param - start_param >= 2 * math.pi - 0.001:
            limit = n
            closed = True
        for i in range(n + 1):
            angle = start_param + (end_param - start_param) * i / n
            x1 = major_r * math.cos(angle)
            y1 = major_r * ratio * math.sin(angle)
            x2 = centre.x + x1 * math.cos(major_angle) - y1 * math.sin(major_angle)
            y2 = centre.y + y1 * math.cos(major_angle) + x1 * math.sin(major_angle)
            points.append(geom.PathPoint(x2, y2))
        return DrawingPolylineTreeItem(document, points, closed, src_name="Ellipse")
    def startEndPos(self):
        if self.closed:
            return (self.points[0], self.points[0])
        else:
            return (self.points[0].seg_start(), self.points[-1].seg_end())
        
class DrawingTextStyleHAlign(EnumClass):
    LEFT = 0
    CENTRE = 1
    RIGHT = 2
    ALIGNED = 3
    MIDDLE = 4
    FIT = 5
    descriptions = [
        (LEFT, "Left"),
        (CENTRE, "Centre"),
        (RIGHT, "Right"),
        (ALIGNED, "Aligned"),
        (MIDDLE, "Middle"),
        (FIT, "Fit"),
    ]

class DrawingTextStyleVAlign(EnumClass):
    BASELINE = 0
    BOTTOM = 1
    MIDDLE = 2
    TOP = 3
    descriptions = [
        (BASELINE, "Baseline"),
        (BOTTOM, "Bottom"),
        (MIDDLE, "Middle"),
        (TOP, "Top"),
    ]

class DrawingTextStyle(object):
    def __init__(self, height, width, halign, valign, angle, font_name, spacing):
        self.height = height
        self.width = width
        self.halign = halign
        self.valign = valign
        self.angle = angle
        self.font_name = font_name
        self.spacing = spacing

class DrawingTextTreeItem(DrawingItemTreeItem):
    prop_x = FloatDistEditableProperty("Insert X", "x", Format.coord, unit="mm", allow_none=False)
    prop_y = FloatDistEditableProperty("Insert Y", "y", Format.coord, unit="mm", allow_none=False)
    prop_text = StringEditableProperty("Text", "text", False)
    prop_font = FontEditableProperty("Font face", "font")
    prop_height = FloatDistEditableProperty("Font size", "height", Format.coord, min=1, unit="mm", allow_none=False)
    prop_width = FloatDistEditableProperty("Stretch", "width", Format.percent, min=10, unit="%", allow_none=False)
    prop_spacing = FloatDistEditableProperty("Letter spacing", "spacing", Format.coord, min=0, allow_none=False)
    prop_angle = FloatDistEditableProperty("Angle", "angle", Format.angle, min=-360, max=360, unit='\u00b0', allow_none=False)
    prop_halign = EnumEditableProperty("Horizontal align", "halign", DrawingTextStyleHAlign, allow_none=False)
    prop_valign = EnumEditableProperty("Vertical align", "valign", DrawingTextStyleVAlign, allow_none=False)
    prop_target_width = FloatDistEditableProperty("Target width", "target_width", Format.coord, unit="mm", allow_none=True, min=0)
    def __init__(self, document, origin, target_width, style, text, untransformed = None):
        DrawingItemTreeItem.__init__(self, document)
        self.untransformed = untransformed if untransformed is not None else self
        self.origin = origin
        self.target_width = target_width
        self.style = style
        self.text = text
        self.closed = True
        self.createPaths()
    def properties(self):
        return [ self.prop_x, self.prop_y, self.prop_text, self.prop_font, self.prop_height, self.prop_width, self.prop_angle, self.prop_spacing, self.prop_halign, self.prop_target_width, self.prop_valign ]
    def isPropertyValid(self, name):
        ha = DrawingTextStyleHAlign
        if name == 'valign':
            return self.style.halign in (ha.LEFT, ha.CENTRE, ha.RIGHT)
        if name == 'target_width':
            return self.style.halign in (ha.ALIGNED, ha.FIT)
        return True
    def store(self):
        return { '_type' : type(self).__name__, 'shape_id' : self.shape_id,
            'text' : self.text, 'x' : self.origin.x, 'y' : self.origin.y,
            'target_width' : self.target_width,
            'height' : self.style.height, 'width' : self.style.width,
            'halign' : self.style.halign, 'valign' : self.style.valign,
            'angle' : self.style.angle,
            'font' : self.style.font_name, 'spacing' : self.style.spacing}
    def getPropertyValue(self, name):
        if name == 'x':
            return self.origin.x
        elif name == 'y':
            return self.origin.y
        elif name == 'target_width':
            return self.target_width
        elif name == 'text':
            return self.text
        elif name == 'font':
            return self.style.font_name
        elif name == 'height':
            return self.style.height
        elif name == 'width':
            return self.style.width * 100
        elif name == 'angle':
            return self.style.angle
        elif name == 'spacing':
            return self.style.spacing
        elif name == 'halign':
            return self.style.halign
        elif name == 'valign':
            return self.style.valign
        else:
            assert False, "Unknown property: " + name
    def setPropertyValue(self, name, value):
        if name == 'x':
            self.origin = geom.PathPoint(value, self.origin.y)
        elif name == 'y':
            self.origin = geom.PathPoint(self.origin.x, value)
        elif name == 'target_width':
            self.target_width = value
        elif name == 'text':
            self.text = value
        elif name == 'font':
            self.style.font_name = value
        elif name == 'height':
            self.style.height = value
        elif name == 'width':
            self.style.width = value / 100
        elif name == 'angle':
            self.style.angle = value
        elif name == 'spacing':
            self.style.spacing = value
        elif name == 'halign':
            self.style.halign = value
        elif name == 'valign':
            self.style.valign = value
        else:
            assert False, "Unknown property: " + name
        self.createPaths()
        self.emitPropertyChanged(name)
    def translated(self, dx, dy):
        tti = DrawingTextTreeItem(self.document, self.origin.translated(dx, dy), self.target_width, self.style, self.text, self.untransformed)
        tti.shape_id = self.shape_id
        return tti
    def toShape(self):
        res = []
        if self.paths:
            first_orientation = self.paths[0].orientation()
            for i, path in enumerate(self.paths):
                if path.orientation() != first_orientation:
                    res[-1].add_island(path.nodes)
                else:
                    res.append(shapes.Shape(path.nodes, path.closed))
        return res
    def renderTo(self, path, modeData):
        for i in self.paths:
            path.addLines(self.penForPath(path, modeData), i.nodes, i.closed)
    def distanceTo(self, pt):
        mindist = None
        for path in self.paths:
            closest, dist = path.closest_point(pt)
            if mindist is None or dist < mindist:
                mindist = dist
        return mindist
    def calcBounds(self):
        bounds = []
        for i in self.paths:
            xcoords = [p.x for p in i.nodes if p.is_point()]
            ycoords = [p.y for p in i.nodes if p.is_point()]
            bounds.append((min(xcoords), min(ycoords), max(xcoords), max(ycoords)))
        self.bounds = geom.max_bounds(*bounds)
    def label(self):
        return "Text%d" % self.shape_id
    def textDescription(self):
        return f"{self.label()}: {self.text}"
    def createPaths(self):
        scale = geom.GeometrySettings.RESOLUTION
        if self.style.height * scale > 1000:
            scale = 1000 / self.style.height
        if not isinstance(QCoreApplication.instance(), QGuiApplication):
            raise Exception("Use --allow-text for converting files using text objects")
        font = QFont(self.style.font_name, 1, 400, False)
        font.setPointSizeF(self.style.height * scale)
        font.setLetterSpacing(QFont.AbsoluteSpacing, self.style.spacing * scale)
        metrics = QFontMetrics(font)
        width = self.style.width
        angle = -self.style.angle
        twidth = metrics.horizontalAdvance(self.text) / scale * self.style.width
        x, y = self.origin.x, self.origin.y
        if self.style.halign == DrawingTextStyleHAlign.RIGHT:
            x -= twidth
        elif self.style.halign == DrawingTextStyleHAlign.CENTRE:
            x -= twidth / 2
        elif self.style.halign == DrawingTextStyleHAlign.ALIGNED:
            if twidth and self.target_width:
                font.setPointSizeF(self.style.height * (self.target_width / (width * twidth) * scale))
                metrics = QFontMetrics(font)
        elif self.style.halign == DrawingTextStyleHAlign.FIT:
            if twidth and self.target_width:
                width *= self.target_width / twidth
        elif self.style.halign == DrawingTextStyleHAlign.MIDDLE:
            x -= twidth / 2
            # This is likely wrong, but I don't have a better idea
            y -= metrics.capHeight() / 2 / scale
        # For non-special H alignment values, use V alignment
        if self.style.halign < DrawingTextStyleHAlign.ALIGNED:
            if self.style.valign == DrawingTextStyleVAlign.BOTTOM:
                y += metrics.descent() / scale
            elif self.style.valign == DrawingTextStyleVAlign.MIDDLE:
                y -= metrics.capHeight() / 2 / scale
            elif self.style.valign == DrawingTextStyleVAlign.TOP:
                y -= metrics.capHeight() / scale
        ppath = QPainterPath()
        ppath.addText(0, 0, font, self.text)
        transform = QTransform().rotate(angle).scale(width, 1)
        polygons = ppath.toSubpathPolygons(transform)
        self.paths = []
        for i in polygons:
            self.paths.append(geom.Path([geom.PathPoint(p.x() / scale + x, -p.y() / scale + y) for p in i], True))
        self.calcBounds()
    def startEndPos(self):
        if self.paths:
            return (self.paths[0].seg_start(), self.paths[-1].seg_end())

class CAMListTreeItem(CAMTreeItem):
    def __init__(self, document, name):
        CAMTreeItem.__init__(self, document, name)
        self.reset()
    def reset(self):
        self.resetProperties()
    def resetProperties(self):
        pass
    
class DrawingTreeItem(CAMListTreeItem):
    prop_x_offset = FloatDistEditableProperty("X origin", "x_offset", Format.coord, unit="mm")
    prop_y_offset = FloatDistEditableProperty("Y origin", "y_offset", Format.coord, unit="mm")
    def __init__(self, document):
        CAMListTreeItem.__init__(self, document, "Drawing")
    def resetProperties(self):
        self.x_offset = 0
        self.y_offset = 0
        self.emitPropertyChanged("x_offset")
        self.emitPropertyChanged("y_offset")
    def bounds(self):
        b = None
        for item in self.items():
            if b is None:
                b = item.bounds
            else:
                b = geom.max_bounds(b, item.bounds)
        if b is None:
            return (-1, -1, 1, 1)
        margin = 5
        return (b[0] - self.x_offset - margin, b[1] - self.y_offset - margin, b[2] - self.x_offset + margin, b[3] - self.y_offset + margin)
    def importDrawing(self, name):
        doc = ezdxf.readfile(name)
        msp = doc.modelspace()
        existing = {}
        for item in self.items():
            itemRepr = item.store()
            del itemRepr['shape_id']
            itemStr = json.dumps(itemRepr)
            existing[itemStr] = item
        itemsToAdd = []
        for entity in msp:
            item = self.importDrawingEntity(entity)
            if item is not None:
                itemRepr = item.store()
                del itemRepr['shape_id']
                itemStr = json.dumps(itemRepr)
                if itemStr not in existing:
                    itemsToAdd.append(item)
        self.document.opAddDrawingItems(itemsToAdd)
        self.document.drawingImported.emit()
    def importDrawingEntity(self, entity):
        dxftype = entity.dxftype()
        inch_mode = geom.GeometrySettings.dxf_inches
        scaling = 25.4 if inch_mode else 1
        def pt(x, y):
            return geom.PathPoint(x * scaling, y * scaling)
        if dxftype == 'LWPOLYLINE':
            points, closed = geom.dxf_polyline_to_points(entity, scaling)
            return DrawingPolylineTreeItem(self.document, points, closed)
        elif dxftype == 'LINE':
            start = tuple(entity.dxf.start)[0:2]
            end = tuple(entity.dxf.end)[0:2]
            return DrawingPolylineTreeItem(self.document, [pt(start[0], start[1]), pt(end[0], end[1])], False)
        elif dxftype == 'ELLIPSE':
            centre = pt(entity.dxf.center[0], entity.dxf.center[1])
            return DrawingPolylineTreeItem.ellipse(self.document, centre, pt(entity.dxf.major_axis[0], entity.dxf.major_axis[1]), entity.dxf.ratio, entity.dxf.start_param, entity.dxf.end_param)
        elif dxftype == 'SPLINE':
            iter = entity.flattening(1.0 / geom.GeometrySettings.RESOLUTION)
            points = [geom.PathPoint(i[0], i[1]) for i in iter]
            return DrawingPolylineTreeItem(self.document, points, entity.closed, src_name="Spline")
        elif dxftype == 'LINE':
            start = tuple(entity.dxf.start)[0:2]
            end = tuple(entity.dxf.end)[0:2]
            return DrawingPolylineTreeItem(self.document, [pt(start[0], start[1]), pt(end[0], end[1])], False)
        elif dxftype == 'CIRCLE':
            centre = pt(entity.dxf.center[0], entity.dxf.center[1])
            return DrawingCircleTreeItem(self.document, centre, entity.dxf.radius * scaling)
        elif dxftype == 'ARC':
            start = pt(entity.start_point[0], entity.start_point[1])
            end = pt(entity.end_point[0], entity.end_point[1])
            centre = (entity.dxf.center[0] * scaling, entity.dxf.center[1] * scaling)
            c = geom.CandidateCircle(*centre, entity.dxf.radius * scaling)
            sangle = entity.dxf.start_angle * math.pi / 180
            eangle = entity.dxf.end_angle * math.pi / 180
            if eangle < sangle:
                sspan = eangle - sangle + 2 * math.pi
            else:
                sspan = eangle - sangle
            points = [start, geom.PathArc(start, end, c, 50, sangle, sspan)]
            return DrawingPolylineTreeItem(self.document, points, False)
        elif dxftype == 'TEXT':
            font = "OpenSans"
            style = DrawingTextStyle(entity.dxf.height * scaling, entity.dxf.width, entity.dxf.halign, entity.dxf.valign, entity.dxf.rotation, font, 0)
            target_width = None
            ap = entity.dxf.align_point
            ip = pt(entity.dxf.insert[0], entity.dxf.insert[1])
            if entity.dxf.align_point is None:
                ap = ip
            else:
                ap = pt(entity.dxf.align_point[0], entity.dxf.align_point[1])
                target_width = ap.dist(ip)
            rp = ip if entity.dxf.halign in (0, 3, 5) else ap
            return DrawingTextTreeItem(self.document, rp, target_width, style, entity.dxf.text)
        else:
            print ("Ignoring DXF entity: %s" % dxftype)
        return None
    def renderTo(self, path, modeData):
        # XXXKF convert
        for i in self.items():
            i.translated(-self.x_offset, -self.y_offset).renderTo(path, modeData)
    def addItem(self, item):
        self.appendRow(item)
    def itemById(self, shape_id):
        # XXXKF slower than before
        for i in self.items():
            if i.shape_id == shape_id:
                return i
            for j in i.items():
                if j.shape_id == shape_id:
                    return j
    def objectsNear(self, pos, margin):
        xy = geom.PathPoint(pos.x() + self.x_offset, pos.y() + self.y_offset)
        found = []
        mindist = margin
        for item in self.items():
            if geom.point_inside_bounds(geom.expand_bounds(item.bounds, margin), xy):
                distance = item.distanceTo(xy)
                if distance is not None and distance < margin:
                    mindist = min(mindist, distance)
                    found.append((item, distance))
        found = sorted(found, key=lambda item: item[1])
        found = [item[0] for item in found if item[1] < mindist * 1.5]
        return found
    def objectsWithin(self, xs, ys, xe, ye):
        xs += self.x_offset
        ys += self.y_offset
        xe += self.x_offset
        ye += self.y_offset
        bounds = (xs, ys, xe, ye)
        found = []
        for item in self.items():
            if geom.inside_bounds(item.bounds, bounds):
                found.append(item)
        return found
    def parseSelection(self, selection, operType):
        translation = self.translation()
        warnings = []
        def pickObjects(selector):
            matched = []
            warnings = []
            for i in selection:
                verdict = selector(i)
                if verdict is True:
                    matched.append(i)
                else:
                    warnings.append(verdict % (i.label(),))
            return matched, warnings
        if operType == OperationType.INTERPOLATED_HOLE or operType == OperationType.DRILLED_HOLE:
            selection, warnings = pickObjects(lambda i: isinstance(i, DrawingCircleTreeItem) or "%s is not a circle")
        elif operType != OperationType.ENGRAVE:
            selection, warnings = pickObjects(lambda i: isinstance(i, DrawingTextTreeItem) or i.toShape().closed or "%s is not a closed shape")
        if operType != OperationType.POCKET and operType != OperationType.OUTSIDE_PEEL:
            return {i.shape_id: set() for i in selection}, selection, warnings
        nonzeros = set()
        zeros = set()
        texts = [ i for i in selection if isinstance(i, DrawingTextTreeItem) ]
        selectionId = [ i.shape_id for i in selection if not isinstance(i, DrawingTextTreeItem) ]
        selectionTrans = [ geom.IntPath(i.translated(*translation).toShape().boundary) for i in selection if not isinstance(i, DrawingTextTreeItem) ]
        for i in range(len(selectionTrans)):
            isi = selectionId[i]
            for j in range(len(selectionTrans)):
                if i == j:
                    continue
                jsi = selectionId[j]
                if not geom.run_clipper_simple(pyclipper.CT_DIFFERENCE, subject_polys=[selectionTrans[i]], clipper_polys=[selectionTrans[j]], bool_only=True, fillMode=pyclipper.PFT_NONZERO):
                    zeros.add((isi, jsi))
        outsides = { i.shape_id: set() for i in selection }
        for isi, jsi in zeros:
            # i minus j = empty set, i.e. i wholly contained in j
            if isi in outsides:
                del outsides[isi]
        for isi, jsi in zeros:
            # i minus j = empty set, i.e. i wholly contained in j
            if jsi in outsides:
                outsides[jsi].add(isi)
        allObjects = set(outsides.keys())
        for outside in outsides:
            islands = outsides[outside]
            redundant = set()
            for i1 in islands:
                for i2 in islands:
                    if i1 != i2 and (i1, i2) in zeros:
                        redundant.add(i1)
            for i in redundant:
                islands.remove(i)
            allObjects |= islands
        for i in texts:
            #glyphs = i.translated(*translation).toShape()
            outsides[i.shape_id] = set()
            allObjects.add(i.shape_id)
        selection = [i for i in selection if i.shape_id in allObjects]
        return outsides, selection, warnings
    def properties(self):
        return [self.prop_x_offset, self.prop_y_offset]
    def translation(self):
        return (-self.x_offset, -self.y_offset)
    def onPropertyValueSet(self, name):
        self.emitPropertyChanged(name)
    def invalidatedObjects(self, aspect):
        if aspect == InvalidateAspect.CAM:
            return set([self] + self.document.allOperations())
        # Properties of operations are not affected
        return set([self])
        
class CAMListTreeItemWithChildren(CAMListTreeItem):
    def __init__(self, document, title):
        # Child items already in a tree
        self.child_items = {}
        # Deleted child items
        self.recycled_items = {}
        CAMListTreeItem.__init__(self, document, title)
    def childList(self):
        # Returns list of data items that map to child nodes in the tree
        assert False
    def createChildItem(self, data):
        # Returns a CAMListTreeItem for a data item
        assert False
    def syncChildren(self):
        expectedChildren = self.childList()
        # Recycle (without deleting) child items deleted from the list
        # (they may still be referenced in undo)
        excess = set(self.child_items.keys()) - set(expectedChildren)
        for child in excess:
            self.recycled_items[child] = self.takeRow(self.child_items.pop(child).row())[0]
        for child in expectedChildren:
            item = self.child_items.get(child, None)
            if item is None:
                item = self.recycled_items.pop(child, None)
                if item is None:
                    item = self.createChildItem(child)
                self.child_items[child] = item
                self.appendRow(item)
            if hasattr(item, 'syncChildren'):
                item.syncChildren()
        self.sortChildren(0)
    def reset(self):
        CAMListTreeItem.reset(self)
        self.syncChildren()

class ToolListTreeItem(CAMListTreeItemWithChildren):
    def __init__(self, document):
        CAMListTreeItemWithChildren.__init__(self, document, "Tool list")
        self.reset()
    def childList(self):
        return sorted(self.document.project_toolbits.values(), key = lambda item: item.name)
    def createChildItem(self, data):
        return ToolTreeItem(self.document, data, True)

class MaterialEnumEditableProperty(EnumEditableProperty):
    def descriptions(self):
        res = []
        mat = inventory.inventory.cutter_materials
        for k, v in mat.items():
            res.append((v, v.name))
        return res

class ToolTreeItem(CAMListTreeItemWithChildren):
    prop_name = StringEditableProperty("Name", "name", False)
    prop_flutes = IntEditableProperty("# flutes", "flutes", "%d", min=1, max=100, allow_none=False)
    prop_diameter = FloatDistEditableProperty("Diameter", "diameter", Format.cutter_dia, unit="mm", min=0, max=100, allow_none=False)
    prop_length = FloatDistEditableProperty("Flute length", "length", Format.cutter_length, unit="mm", min=0.1, max=100, allow_none=True)
    prop_material = MaterialEnumEditableProperty("Material", "material", inventory.CutterMaterial, allow_none=False)
    def __init__(self, document, inventory_tool, is_local):
        self.inventory_tool = inventory_tool
        CAMListTreeItemWithChildren.__init__(self, document, "Tool")
        self.setEditable(False)
        self.reset()
    def isLocal(self):
        return not self.inventory_tool.base_object or not (self.inventory_tool.equals(self.inventory_tool.base_object))
    def isNewObject(self):
        return self.inventory_tool.base_object is None
    def isModifiedStock(self):
        return self.inventory_tool.base_object is not None and not (self.inventory_tool.equals(self.inventory_tool.base_object))
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(self.inventory_tool.description())
        is_local = self.isLocal()
        return self.format_item_as(role, CAMTreeItem.data(self, role), italic=not is_local)
    def childList(self):
        return sorted(self.inventory_tool.presets, key = lambda item: item.name)
    def createChildItem(self, data):
        return ToolPresetTreeItem(self.document, data)
    def properties(self):
        if isinstance(self.inventory_tool, inventory.EndMillCutter):
            return [self.prop_name, self.prop_diameter, self.prop_flutes, self.prop_length, self.prop_material]
        elif isinstance(self.inventory_tool, inventory.DrillBitCutter):
            return [self.prop_name, self.prop_diameter, self.prop_length, self.prop_material]
        return []
    def resetProperties(self):
        self.emitPropertyChanged()
    def getPropertyValue(self, name):
        return getattr(self.inventory_tool, name)
    def setPropertyValue(self, name, value):
        if name == 'name':
            self.inventory_tool.name = value
            self.inventory_tool.base_object = inventory.inventory.toolbitByName(value, type(self.inventory_tool))
        elif hasattr(self.inventory_tool, name):
            setattr(self.inventory_tool, name, value)
        else:
            assert False, "Unknown attribute: " + repr(name)
        self.emitPropertyChanged(name)
    def invalidatedObjects(self, aspect):
        # Need to refresh properties for any default or calculated values updated, tool name etc.
        # Affects both properties and CAM
        return set([self] + self.document.allOperationsPlusRefinements(lambda item: item.cutter is self.inventory_tool))

class ToolPresetTreeItem(CAMTreeItem):
    prop_name = StringEditableProperty("Name", "name", False)
    prop_doc = FloatDistEditableProperty("Cut depth/pass", "doc", Format.depth_of_cut, unit="mm", min=0.01, max=100, allow_none=True)
    prop_rpm = FloatDistEditableProperty("RPM", "rpm", Format.rpm, unit="rpm", min=0.1, max=60000, allow_none=True)
    prop_surf_speed = FloatDistEditableProperty("Surface speed", "surf_speed", Format.surf_speed, unit="m/min", allow_none=True, computed=True)
    prop_chipload = FloatDistEditableProperty("Chipload", "chipload", Format.chipload, unit="mm/tooth", allow_none=True, computed=True)
    prop_hfeed = FloatDistEditableProperty("Feed rate", "hfeed", Format.feed, unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_vfeed = FloatDistEditableProperty("Plunge rate", "vfeed", Format.feed, unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_offset = FloatDistEditableProperty("Offset", "offset", Format.coord, unit="mm", min=-20, max=20, default_value=0)
    prop_stepover = FloatDistEditableProperty("Stepover", "stepover", Format.percent, unit="%", min=1, max=100, allow_none=True)
    prop_direction = EnumEditableProperty("Direction", "direction", inventory.MillDirection, allow_none=False)
    prop_extra_width = FloatDistEditableProperty("Extra width", "extra_width", Format.percent, unit="%", min=0, max=100, allow_none=True)
    prop_trc_rate = FloatDistEditableProperty("Trochoid: step", "trc_rate", Format.percent, unit="%", min=0, max=100, allow_none=True)
    prop_pocket_strategy = EnumEditableProperty("Strategy", "pocket_strategy", inventory.PocketStrategy, allow_none=True)
    prop_axis_angle = FloatDistEditableProperty("Axis angle", "axis_angle", format=Format.angle, unit='\u00b0', min=0, max=90, allow_none=True)
    prop_eh_diameter = FloatDistEditableProperty("Entry helix %dia", "eh_diameter", format=Format.percent, unit='%', min=0, max=100, allow_none=True)
    
    props_percent = set(['stepover', 'extra_width', 'trc_rate', 'eh_diameter'])

    def __init__(self, document, preset):
        self.inventory_preset = preset
        CAMTreeItem.__init__(self, document, "Tool preset")
        self.setEditable(False)
        self.resetProperties()
    def resetProperties(self):
        self.emitPropertyChanged()
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant("Preset: " + self.inventory_preset.description())
        is_default = self.isDefault()
        is_local = self.isLocal()
        return self.format_item_as(role, CAMTreeItem.data(self, role), bold=is_default, italic=not is_local)
    def isDefault(self):
        return self.parent() and self.document.default_preset_by_tool.get(self.parent().inventory_tool, None) is self.inventory_preset
    def isLocal(self):
        return not self.inventory_preset.base_object or not (self.inventory_preset.equals(self.inventory_preset.base_object))
    def isModifiedStock(self):
        return self.parent().inventory_tool.base_object is not None and self.inventory_preset.base_object is not None and not (self.inventory_preset.equals(self.inventory_preset.base_object))
    def isNewObject(self):
        return self.inventory_preset.base_object is None
    def properties(self):
        return self.properties_for_cutter_type(type(self.inventory_preset.toolbit))
    @classmethod
    def properties_for_cutter_type(klass, cutter_type):
        if cutter_type == inventory.EndMillCutter:
            return klass.properties_endmill()
        elif cutter_type == inventory.DrillBitCutter:
            return klass.properties_drillbit()
        return []
    @classmethod
    def properties_endmill(klass):
        return [klass.prop_name, klass.prop_doc, klass.prop_hfeed, klass.prop_vfeed, klass.prop_offset, klass.prop_stepover, klass.prop_direction, klass.prop_rpm, klass.prop_surf_speed, klass.prop_chipload, klass.prop_extra_width, klass.prop_trc_rate, klass.prop_pocket_strategy, klass.prop_axis_angle, klass.prop_eh_diameter]
    @classmethod
    def properties_drillbit(klass):
        return [klass.prop_name, klass.prop_doc, klass.prop_vfeed, klass.prop_rpm, klass.prop_surf_speed, klass.prop_chipload]
    def getDefaultPropertyValue(self, name):
        if name != 'surf_speed' and name != 'chipload':
            attr = PresetDerivedAttributes.attrs[self.inventory_preset.toolbit.__class__][name]
            if attr.def_value is not None:
                return attr.def_value
        return None
    def getPropertyValue(self, name):
        def toPercent(v):
            return v * 100.0 if v is not None else v
        attrs = PresetDerivedAttributes.attrs[type(self.inventory_preset.toolbit)]
        attr = attrs.get(name)
        if attr is not None:
            present, value = attr.resolve(None, self.inventory_preset)
            if present:
                return value
        elif name == 'surf_speed':
            return self.inventory_preset.toolbit.diameter * math.pi * self.inventory_preset.rpm if self.inventory_preset.rpm else None
        elif name == 'chipload':
            if isinstance(self.inventory_preset.toolbit, inventory.EndMillCutter):
                return self.inventory_preset.hfeed / (self.inventory_preset.rpm * (self.inventory_preset.toolbit.flutes or 2)) if self.inventory_preset.hfeed and self.inventory_preset.rpm else None
            elif isinstance(self.inventory_preset.toolbit, inventory.DrillBitCutter):
                return self.inventory_preset.vfeed / self.inventory_preset.rpm if self.inventory_preset.vfeed and self.inventory_preset.rpm else None
        else:
            return getattr(self.inventory_preset, name)
    def setPropertyValue(self, name, value):
        def fromPercent(v):
            return v / 100.0 if v is not None else v
        if name == 'doc':
            self.inventory_preset.maxdoc = value
        elif name in self.props_percent:
            setattr(self.inventory_preset, name, fromPercent(value))
        elif name == 'name':
            self.inventory_preset.name = value
            # Update link to inventory object
            base_tool = self.inventory_preset.toolbit.base_object
            if base_tool:
                self.inventory_preset.base_object = base_tool.presetByName(value)
            else:
                assert self.inventory_preset.base_object is None
        elif hasattr(self.inventory_preset, name):
            setattr(self.inventory_preset, name, value)
        elif name == 'surf_speed':
            if value:
                rpm = value / (self.inventory_preset.toolbit.diameter * math.pi)
                if rpm >= self.prop_rpm.min and rpm <= self.prop_rpm.max:
                    self.inventory_preset.rpm = rpm
            else:
                self.inventory_preset.rpm = None
        elif name == 'chipload':
            if isinstance(self.inventory_preset.toolbit, inventory.EndMillCutter):
                if value and self.inventory_preset.rpm:
                    hfeed = self.inventory_preset.rpm * value * (self.inventory_preset.toolbit.flutes or 2)
                    if hfeed >= self.prop_hfeed.min and hfeed <= self.prop_hfeed.max:
                        self.inventory_preset.hfeed = hfeed
                else:
                    self.inventory_preset.hfeed = None
            elif isinstance(self.inventory_preset.toolbit, inventory.DrillBitCutter):
                if value and self.inventory_preset.rpm:
                    vfeed = self.inventory_preset.rpm * value
                    if vfeed >= self.prop_vfeed.min and vfeed <= self.prop_vfeed.max:
                        self.inventory_preset.vfeed = vfeed
                else:
                    self.inventory_preset.vfeed = None
        else:
            assert False, "Unknown attribute: " + repr(name)
        if name in ['offset', 'stepover', 'direction', 'extra_width', 'trc_rate', 'pocket_strategy', 'axis_angle', 'eh_diameter']:
            # There are other things that might require a recalculation, but do not result in visible changes
            self.document.startUpdateCAM(subset=self.document.allOperations(lambda item: item.tool_preset is self.inventory_preset))
        self.emitPropertyChanged(name)
    def returnKeyPressed(self):
        self.document.selectPresetAsDefault(self.inventory_preset.toolbit, self.inventory_preset)
    def invalidatedObjects(self, aspect):
        # Need to refresh properties for any default or calculated values updated
        return set([self] + self.document.allOperationsPlusRefinements(lambda item: item.tool_preset is self.inventory_preset))

class MaterialType(EnumClass):
    WOOD = 0
    PLASTICS = 1
    ALU = 2
    MILD_STEEL = 3
    ALLOY_STEEL = 4
    TOOL_STEEL = 5
    STAINLESS_STEEL = 6
    CAST_IRON = 7
    MALLEABLE_IRON = 8
    BRASS = 9
    FOAM = 10
    descriptions = [
        (FOAM, "Foam", milling_tool.material_foam),
        (WOOD, "Wood/MDF", milling_tool.material_wood),
        (PLASTICS, "Plastics", milling_tool.material_plastics),
        (ALU, "Aluminium", milling_tool.material_aluminium),
        (BRASS, "Brass", milling_tool.material_brass),
        (MILD_STEEL, "Mild steel", milling_tool.material_mildsteel),
        (ALLOY_STEEL, "Alloy or MC steel", milling_tool.material_alloysteel),
        (TOOL_STEEL, "Tool steel", milling_tool.material_toolsteel),
        (STAINLESS_STEEL, "Stainless steel", milling_tool.material_stainlesssteel),
        (CAST_IRON, "Cast iron - gray", milling_tool.material_castiron),
        (MALLEABLE_IRON, "Cast iron - malleable", milling_tool.material_malleableiron),
    ]

class WorkpieceTreeItem(CAMTreeItem):
    prop_material = EnumEditableProperty("Material", "material", MaterialType, allow_none=True, none_value="Unknown")
    prop_thickness = FloatDistEditableProperty("Thickness", "thickness", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True)
    prop_clearance = FloatDistEditableProperty("Clearance", "clearance", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True)
    prop_safe_entry_z = FloatDistEditableProperty("Safe entry Z", "safe_entry_z", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True)
    def __init__(self, document):
        CAMTreeItem.__init__(self, document, "Workpiece")
        self.resetProperties()
    def resetProperties(self):
        self.material = None
        self.thickness = None
        self.clearance = self.document.config_settings.clearance_z
        self.safe_entry_z = self.document.config_settings.safe_entry_z
        self.emitPropertyChanged()
    def properties(self):
        return [self.prop_material, self.prop_thickness, self.prop_clearance, self.prop_safe_entry_z]
    def data(self, role):
        if role == Qt.DisplayRole:
            mname = MaterialType.toString(self.material) if self.material is not None else "unknown material"
            if self.thickness is not None:
                return QVariant(f"Workpiece: {Format.depth_of_cut(self.thickness)} {mname}")
            elif self.material is not None:
                return QVariant(f"Workpiece: {mname}, unknown thickness")
            else:
                return QVariant(f"Workpiece: unknown material or thickness")
        return CAMTreeItem.data(self, role)
    def onPropertyValueSet(self, name):
        #if name == 'material':
        #    self.document.make_tool()
        if name in ('clearance', 'safe_entry_z'):
            self.document.makeMachineParams()
        self.emitPropertyChanged(name)
    def invalidatedObjects(self, aspect):
        # Depth of cut, mostly XXXKF might check for default value
        return set([self] + self.document.allOperations())

class OperationType(EnumClass):
    OUTSIDE_CONTOUR = 1
    INSIDE_CONTOUR = 2
    POCKET = 3
    ENGRAVE = 4
    INTERPOLATED_HOLE = 5
    DRILLED_HOLE = 6
    OUTSIDE_PEEL = 7
    REFINE = 8
    descriptions = [
        (OUTSIDE_CONTOUR, "Outside contour"),
        (INSIDE_CONTOUR, "Inside contour"),
        (POCKET, "Pocket"),
        (ENGRAVE, "Engrave"),
        (INTERPOLATED_HOLE, "H-Hole"),
        (DRILLED_HOLE, "Drill"),
        (OUTSIDE_PEEL, "Outside peel"),
        (REFINE, "Refine"),
    ]

class CutterAdapter(object):
    def getLookupData(self, items):
        assert items
        if items[0].operation == OperationType.DRILLED_HOLE:
            return items[0].document.getToolbitList((inventory.DrillBitCutter, inventory.EndMillCutter))
        else:
            return items[0].document.getToolbitList(inventory.EndMillCutter)
    def lookupById(self, id):
        return inventory.IdSequence.lookup(id)    

class AltComboOption(object):
    pass

class SavePresetOption(AltComboOption):
    pass

class LoadPresetOption(AltComboOption):
    pass

class ToolPresetAdapter(object):
    def getLookupData(self, item):
        item = item[0]
        res = []
        if item.cutter:
            pda = PresetDerivedAttributes(item)
            if pda.dirty:
                res.append((SavePresetOption(), "<Convert to a preset>"))
            for preset in item.cutter.presets:
                res.append((preset.id, preset.description()))
            res.append((LoadPresetOption(), "<Load a preset>"))
        return res
    def lookupById(self, id):
        if isinstance(id, AltComboOption):
            return id
        return inventory.IdSequence.lookup(id)    

class CycleTreeItem(CAMTreeItem):
    def __init__(self, document, cutter):
        CAMTreeItem.__init__(self, document, "Tool cycle")
        self.setCheckable(True)
        self.setAutoTristate(True)
        self.cutter = cutter
        self.setCheckState(Qt.CheckState.Checked)
    def toString(self):
        return "Tool cycle"
    @staticmethod
    def listCheckState(items):
        allNo = allYes = True
        for i in items:
            if i.checkState() != Qt.CheckState.Unchecked:
                allNo = False
            if i.checkState() != Qt.CheckState.Checked:
                allYes = False
        if allNo:
            return Qt.CheckState.Unchecked
        if allYes:
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked
    def operCheckState(self):
        return CycleTreeItem.listCheckState(self.items())
    def updateCheckState(self):
        if self.items():
            self.setCheckState(self.operCheckState())
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(f"Use tool: {self.cutter.name}")
        if role == Qt.ToolTipRole:
            return QVariant(f"{self.cutter.description()}")
        if (self.document.current_cutter_cycle is not None) and (self is self.document.current_cutter_cycle):
            return self.format_item_as(role, CAMTreeItem.data(self, role), bold=True)
        return CAMTreeItem.data(self, role)
    def returnKeyPressed(self):
        self.document.selectCutterCycle(self)
    def reorderItem(self, direction: int):
        return self.reorderItemImpl(direction, self.model().invisibleRootItem())
    def canAccept(self, child: CAMTreeItem):
        if not isinstance(child, OperationTreeItem):
            return False
        if not self.cutter:
            return False
        if not (self.cutter.__class__ is child.cutter.__class__):
            return False
        if child.tool_preset is not None:
            for preset in self.cutter.presets:
                if preset.name == child.tool_preset.name:
                    break
            else:
                return False
        return True
    def updateItemAfterMove(self, child):
        if child.cutter != self.cutter:
            child.cutter = self.cutter
            if child.tool_preset:
                for preset in self.cutter.presets:
                    if preset.name == child.tool_preset.name:
                        child.tool_preset = preset
                        break
                else:
                    child.tool_preset = None
    def invalidatedObjects(self, aspect):
        return set([self] + self.document.allOperations(lambda item: item.parent() is self))

def not_none(*args):
    for i in args:
        if i is not None:
            return True
    return False

class PresetDerivedAttributeItem(object):
    def __init__(self, name, preset_name=None, preset_scale=None, def_value=None):
        self.name = name
        self.preset_name = preset_name or name
        self.preset_scale = preset_scale
        self.def_value = def_value
    def resolve(self, operation, preset):
        if operation is not None:
            op_value = getattr(operation, self.name)
            if op_value is not None:
                return (True, op_value)
        preset_value = getattr(preset, self.preset_name, None) if preset else None
        if preset_value is not None:
            if self.preset_scale is not None:
                preset_value *= self.preset_scale
            return (operation is None, preset_value)
        return (False, self.def_value)

class PresetDerivedAttributes(object):
    attrs_common = [
        PresetDerivedAttributeItem('rpm'),
        PresetDerivedAttributeItem('vfeed'),
        PresetDerivedAttributeItem('doc', preset_name='maxdoc'),
    ]
    attrs_endmill = [
        PresetDerivedAttributeItem('hfeed'),
        PresetDerivedAttributeItem('offset', def_value=0),
        PresetDerivedAttributeItem('stepover', preset_scale=100),
        PresetDerivedAttributeItem('extra_width', preset_scale=100, def_value=0),
        PresetDerivedAttributeItem('trc_rate', preset_scale=100, def_value=0),
        PresetDerivedAttributeItem('direction', def_value=inventory.MillDirection.CONVENTIONAL),
        PresetDerivedAttributeItem('pocket_strategy', def_value=inventory.PocketStrategy.CONTOUR_PARALLEL),
        PresetDerivedAttributeItem('axis_angle', def_value=0),
        PresetDerivedAttributeItem('eh_diameter', preset_scale=100, def_value=50),
    ]
    attrs_all = attrs_common + attrs_endmill
    attrs = {
        inventory.EndMillCutter : {i.name : i for i in attrs_all},
        inventory.DrillBitCutter : {i.name : i for i in attrs_common},
    }
    def __init__(self, operation, preset=None):
        if preset is None:
            preset = operation.tool_preset
        self.operation = operation
        attrs = self.attrs[operation.cutter.__class__]
        self.dirty = False
        for attr in attrs.values():
            dirty, value = attr.resolve(operation, preset)
            setattr(self, attr.name, value)
            self.dirty = self.dirty or dirty
        # Material defaults
        if operation.document.material.material is not None and operation.cutter is not None and isinstance(operation.cutter, inventory.EndMillCutter):
            m = MaterialType.toTuple(operation.document.material.material)[2]
            t = operation.cutter
            st = milling_tool.standard_tool(t.diameter, t.flutes or 2, m, milling_tool.carbide_uncoated)
            if self.rpm is None:
                self.rpm = st.rpm
            if self.hfeed is None:
                self.hfeed = st.hfeed
            if self.vfeed is None:
                self.vfeed = st.vfeed
            if self.doc is None:
                self.doc = st.maxdoc
    def validate(self, errors):
        if self.vfeed is None:
            errors.append("Plunge rate is not set")
        if self.doc is None:
            errors.append("Maximum depth of cut per pass is not set")
        if isinstance(self.operation.cutter, inventory.EndMillCutter):
            if self.hfeed is None:
                if self.operation.operation != OperationType.DRILLED_HOLE:
                    errors.append("Feed rate is not set")
            elif self.hfeed < 0.1 or self.hfeed > 10000:
                errors.append("Feed rate is out of range (0.1-10000)")
            if self.stepover is None or self.stepover < 0.1 or self.stepover > 100:
                if self.operation.operation == OperationType.POCKET or self.operation.operation == OperationType.OUTSIDE_PEEL or self.operation.operation == OperationType.REFINE:
                    if self.stepover is None:
                        errors.append("Horizontal stepover is not set")
                    else:
                        errors.append("Horizontal stepover is out of range")
                else:
                    # Fake value that is never used
                    self.stepover = 0.5
    @staticmethod
    def valuesFromPreset(preset, cutter_type):
        values = {}
        if preset:
            values['name'] = preset.name
            for attr in PresetDerivedAttributes.attrs[cutter_type].values():
                present, value = attr.resolve(None, preset)
                values[attr.name] = value if present is not None else None
        else:
            for attr in PresetDerivedAttributes.attrs[cutter_type].values():
                if attr.def_value is not None:
                    values[attr.name] = attr.def_value
        return values
    def toPreset(self, name):
        return self.toPresetFromAny(name, self, self.operation.cutter, type(self.operation.cutter))
    @classmethod
    def toPresetFromAny(klass, name, src, cutter, cutter_type):
        kwargs = {}
        is_dict = isinstance(src, dict)
        for attr in klass.attrs[cutter_type].values():
            value = src[attr.name] if is_dict else getattr(src, attr.name)
            if value is not None and attr.preset_scale is not None:
                value /= attr.preset_scale
            kwargs[attr.preset_name] = value
        return cutter_type.preset_type.new(None, name, cutter, **kwargs)
    @classmethod
    def resetPresetDerivedValues(klass, target):
        for attr in klass.attrs_all:
            setattr(target, attr.name, None)
        target.emitPropertyChanged()

class WorkerThread(threading.Thread):
    def __init__(self, parentOp, workerFunc):
        self.worker_func = workerFunc
        self.parent_operation = parentOp
        self.exception = None
        self.exception_text = None
        self.progress = (0, 10000000)
        self.cancelled = False
        threading.Thread.__init__(self, target=self.threadMain)
    def getProgress(self):
        return self.progress
    def cancel(self):
        self.cancelled = True
    def threadMain(self):
        try:
            self.worker_func()
            if self.parent_operation.cam and self.parent_operation.cam.is_nothing():
                self.parent_operation.addWarning("No cuts produced")
            self.progress = (self.progress[1], self.progress[1])
        except Exception as e:
            self.exception = e
            self.exception_text = str(e)
            import traceback
            traceback.print_exc()

class WorkerThreadPack(object):
    def __init__(self, parentOp, workerFuncList):
        self.threads = [WorkerThread(parentOp, workerFunc) for workerFunc in workerFuncList]
        self.exception = None
        self.exception_text = None
    def getProgress(self):
        num = denom = 0
        for thread in self.threads:
            progress = thread.getProgress()
            num += progress[0]
            denom += progress[1]
        return (num, denom)
    def start(self):
        for thread in self.threads:
            thread.start()
    def cancel(self):
        for thread in self.threads:
            thread.cancel()
    def join(self):
        for thread in self.threads:
            thread.join()
        exceptions = ""
        for thread in self.threads:
            if thread.exception is not None:
                self.exception = thread.exception
                break
        for thread in self.threads:
            if thread.exception is not None:
                exceptions += thread.exception_text
        if exceptions:
            self.exception_text = exceptions
    def is_alive(self):
        return any([thread.is_alive() for thread in self.threads])

def cutterTypesForOperationType(operationType):
    return (inventory.DrillBitCutter, inventory.EndMillCutter) if operationType == OperationType.DRILLED_HOLE else inventory.EndMillCutter

class OperationTreeItem(CAMTreeItem):
    prop_operation = EnumEditableProperty("Operation", "operation", OperationType)
    prop_cutter = RefEditableProperty("Cutter", "cutter", CutterAdapter())
    prop_preset = RefEditableProperty("Tool preset", "tool_preset", ToolPresetAdapter(), allow_none=True, none_value="<none>")
    prop_depth = FloatDistEditableProperty("Depth", "depth", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True, none_value="full depth")
    prop_start_depth = FloatDistEditableProperty("Start Depth", "start_depth", Format.depth_of_cut, unit="mm", min=0, max=100, default_value=0)
    prop_tab_height = FloatDistEditableProperty("Tab Height", "tab_height", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True, none_value="full height")
    prop_tab_count = IntEditableProperty("# Auto Tabs", "tab_count", "%d", min=0, max=100, allow_none=True, none_value="default")
    prop_user_tabs = SetEditableProperty("Tab Locations", "user_tabs", format_func=lambda value: ", ".join([f"({Format.coord(i.x)}, {Format.coord(i.y)})" for i in value]), edit_func=lambda item: item.editTabLocations())
    prop_entry_exit = SetEditableProperty("Entry/Exit points", "entry_exit", format_func=lambda value: ("Applied" if value else "Not applied") + " - double-click to edit", edit_func=lambda item: item.editEntryExit())
    prop_islands = SetEditableProperty("Islands", "islands", edit_func=lambda item: item.editIslands(), format_func=lambda value: f"{len(value)} items - double-click to edit")
    prop_dogbones = EnumEditableProperty("Dogbones", "dogbones", cam.dogbone.DogboneMode, allow_none=False)
    prop_pocket_strategy = EnumEditableProperty("Strategy", "pocket_strategy", inventory.PocketStrategy, allow_none=True, none_value="(use preset value)")
    prop_axis_angle = FloatDistEditableProperty("Axis angle", "axis_angle", format=Format.angle, unit='\u00b0', min=0, max=90, allow_none=True)
    prop_eh_diameter = FloatDistEditableProperty("Entry helix %dia", "eh_diameter", format=Format.percent, unit='%', min=0, max=100, allow_none=True)

    prop_hfeed = FloatDistEditableProperty("Feed rate", "hfeed", Format.feed, unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_vfeed = FloatDistEditableProperty("Plunge rate", "vfeed", Format.feed, unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_doc = FloatDistEditableProperty("Cut depth/pass", "doc", Format.depth_of_cut, unit="mm", min=0.01, max=100, allow_none=True)
    prop_offset = FloatDistEditableProperty("Offset", "offset", Format.coord, unit="mm", min=-20, max=20, allow_none=True)
    prop_stepover = FloatDistEditableProperty("Stepover", "stepover", Format.percent, unit="%", min=1, max=100, allow_none=True)
    prop_extra_width = FloatDistEditableProperty("Extra width", "extra_width", Format.percent, unit="%", min=0, max=100, allow_none=True)
    prop_trc_rate = FloatDistEditableProperty("Trochoid: step", "trc_rate", Format.percent, unit="%", min=0, max=200, allow_none=True)
    prop_direction = EnumEditableProperty("Direction", "direction", inventory.MillDirection, allow_none=True, none_value="(use preset value)")
    prop_rpm = FloatDistEditableProperty("RPM", "rpm", Format.rpm, unit="rpm", min=0.1, max=100000, allow_none=True)

    def __init__(self, document):
        CAMTreeItem.__init__(self, document)
        self.setCheckable(True)
        self.shape_id = None
        self.orig_shape = None
        self.shape = None
        self.shape_to_refine = None
        self.resetProperties()
        self.isSelected = False
        self.error = None
        self.warning = None
        self.worker = None
        self.prev_diameter = None
        self.cam = None
        self.renderer = None
        self.error = None
        self.warning = None
    def resetProperties(self):
        self.active = True
        self.updateCheckState()
        self.cutter = None
        self.tool_preset = None
        self.operation = OperationType.OUTSIDE_CONTOUR
        self.depth = None
        self.start_depth = 0
        self.tab_height = None
        self.tab_count = None
        self.offset = 0
        self.islands = set()
        self.dogbones = cam.dogbone.DogboneMode.DISABLED
        self.user_tabs = set()
        self.entry_exit = []
        PresetDerivedAttributes.resetPresetDerivedValues(self)
    def updateCheckState(self):
        if not self.active and self.cam is not None:
            self.cam = None
            self.document.operationsUpdated.emit()
        self.setCheckState(Qt.CheckState.Checked if self.active else Qt.CheckState.Unchecked)
    def editTabLocations(self):
        self.document.tabEditRequested.emit(self)
    def editIslands(self):
        self.document.islandsEditRequested.emit(self)
    def editEntryExit(self):
        self.document.entryExitEditRequested.emit(self)
    def areIslandsEditable(self):
        if self.operation not in (OperationType.POCKET, OperationType.OUTSIDE_PEEL):
            return False
        return not isinstance(self.orig_shape, DrawingTextTreeItem)
    def usesShape(self, shape_id):
        if self.shape_id == shape_id:
            return True
        for i in self.islands:
            if i == shape_id:
                return True
        return False
    def toString(self):
        return OperationType.toString(self.operation)
    def isPropertyValid(self, name):
        is_contour = self.operation in (OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR)
        has_islands = self.operation in (OperationType.POCKET, OperationType.OUTSIDE_PEEL, OperationType.REFINE)
        has_stepover = has_islands or self.operation in (OperationType.INTERPOLATED_HOLE,)
        if not is_contour and name in ['tab_height', 'tab_count', 'extra_width', 'trc_rate', 'user_tabs', 'entry_exit']:
            return False
        if not has_islands and name == 'pocket_strategy':
            return False
        if not self.areIslandsEditable() and name == 'islands':
            return False
        if not has_stepover and name in ['stepover', 'eh_diameter']:
            return False
        if (not has_islands or self.pocket_strategy not in [inventory.PocketStrategy.AXIS_PARALLEL, inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG]) and name == 'axis_angle':
            return False
        if self.operation in (OperationType.ENGRAVE, OperationType.DRILLED_HOLE, OperationType.INTERPOLATED_HOLE) and name == 'dogbones':
            return False
        if self.operation == OperationType.ENGRAVE and name in ['direction']:
            return False
        if self.operation == OperationType.DRILLED_HOLE and name in ['hfeed', 'trc_rate', 'direction']:
            return False
        return True
    def getValidEnumValues(self, name):
        if name == 'pocket_strategy' and self.operation == OperationType.OUTSIDE_PEEL:
            return [inventory.PocketStrategy.CONTOUR_PARALLEL, inventory.PocketStrategy.HSM_PEEL, inventory.PocketStrategy.HSM_PEEL_ZIGZAG]
        if name == 'operation':
            if self.cutter is not None and isinstance(self.cutter, inventory.DrillBitCutter):
                return [OperationType.DRILLED_HOLE]
            if isinstance(self.orig_shape, DrawingCircleTreeItem):
                return [OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR, OperationType.POCKET, OperationType.OUTSIDE_PEEL, OperationType.ENGRAVE, OperationType.INTERPOLATED_HOLE, OperationType.DRILLED_HOLE]
            if isinstance(self.orig_shape, DrawingPolylineTreeItem) or isinstance(self.orig_shape, DrawingTextTreeItem):
                if self.orig_shape.closed:
                    return [OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR, OperationType.POCKET, OperationType.OUTSIDE_PEEL, OperationType.ENGRAVE, OperationType.REFINE]
                else:
                    return [OperationType.ENGRAVE]
    def getDefaultPropertyValue(self, name):
        if isinstance(self.cutter, inventory.DrillBitCutter):
            if name == 'hfeed' or name == 'stepover' or name == 'direction':
                return None
        pda = PresetDerivedAttributes(self)
        return getattr(pda, name, None)
    def store(self):
        dump = CAMTreeItem.store(self)
        dump['active'] = self.active
        dump['shape_id'] = self.shape_id
        dump['islands'] = list(sorted(self.islands))
        dump['user_tabs'] = list(sorted([(pt.x, pt.y) for pt in self.user_tabs]))
        dump['entry_exit'] = [[(pts[0].x, pts[0].y), (pts[1].x, pts[1].y)] for pts in self.entry_exit]
        dump['cutter'] = self.cutter.id
        dump['tool_preset'] = self.tool_preset.id if self.tool_preset else None
        return dump
    def class_specific_load(self, dump):
        self.shape_id = dump.get('shape_id', None)
        self.islands = set(dump.get('islands', []))
        self.user_tabs = set(geom.PathPoint(i[0], i[1]) for i in dump.get('user_tabs', []))
        self.entry_exit = [(geom.PathPoint(i[0][0], i[0][1]), geom.PathPoint(i[1][0], i[1][1])) for i in dump.get('entry_exit', [])]
        self.active = dump.get('active', True)
        self.updateCheckState()
    def properties(self):
        return [self.prop_operation, self.prop_cutter, self.prop_preset, 
            self.prop_depth, self.prop_start_depth, 
            self.prop_tab_height, self.prop_tab_count, self.prop_user_tabs,
            self.prop_entry_exit, self.prop_dogbones,
            self.prop_extra_width,
            self.prop_islands, self.prop_pocket_strategy, self.prop_axis_angle,
            self.prop_direction,
            self.prop_doc, self.prop_hfeed, self.prop_vfeed,
            self.prop_offset,
            self.prop_stepover, self.prop_eh_diameter,
            self.prop_trc_rate, self.prop_rpm]
    def setPropertyValue(self, name, value):
        if name == 'tool_preset':
            if isinstance(value, SavePresetOption):
                from . import cutter_mgr
                pda = PresetDerivedAttributes(self)
                preset = pda.toPreset("")
                if isinstance(self.cutter, inventory.EndMillCutter):
                    dlgclass = cutter_mgr.CreateEditEndMillPresetDialog
                elif isinstance(self.cutter, inventory.DrillBitCutter):
                    dlgclass = cutter_mgr.CreateEditDrillBitPresetDialog
                else:
                    return
                dlg = dlgclass(title="Create a preset from operation attributes", preset=preset)
                if dlg.exec_():
                    self.tool_preset = dlg.result
                    self.tool_preset.toolbit = self.cutter
                    self.cutter.presets.append(self.tool_preset)
                    pda.resetPresetDerivedValues(self)
                    self.document.refreshToolList()
                    self.document.selectPresetAsDefault(self.tool_preset.toolbit, self.tool_preset)
                return
            if isinstance(value, LoadPresetOption):
                from . import cutter_mgr
                cutter_type = cutterTypesForOperationType(self.operation)
                if cutter_mgr.selectCutter(None, cutter_mgr.SelectCutterDialog, self.document, cutter_type):
                    if self.cutter is not self.document.current_cutter_cycle.cutter:
                        self.document.opMoveItem(self.parent(), self, self.document.current_cutter_cycle, 0)
                        self.cutter = self.document.current_cutter_cycle.cutter
                    self.tool_preset = self.document.default_preset_by_tool.get(self.cutter, None)
                    self.startUpdateCAM()
                    self.document.refreshToolList()
                return
        if name == 'direction' and self.entry_exit:
            pda = PresetDerivedAttributes(self)
            old_orientation = pda.direction
        setattr(self, name, value)
        if name == 'direction' and self.entry_exit:
            pda = PresetDerivedAttributes(self)
            if pda.direction != old_orientation:
                self.entry_exit = [(e, s) for s, e in self.entry_exit]
        self.onPropertyValueSet(name)
    def onPropertyValueSet(self, name):
        if name == 'cutter' and self.parent().cutter != self.cutter:
            self.parent().takeRow(self.row())
            cycle = self.document.cycleForCutter(self.cutter)
            if cycle:
                if self.operation == OperationType.OUTSIDE_CONTOUR:
                    cycle.appendRow(self)
                else:
                    cycle.insertRow(0, self)
        if name == 'cutter' and self.tool_preset and self.tool_preset.toolbit != self.cutter:
            # Find a matching preset
            for i in self.cutter.presets:
                if i.name == self.tool_preset.name:
                    self.tool_preset = i
                    break
            else:
                self.tool_preset = None
        self.startUpdateCAM()
        self.emitDataChanged()
    def operationTypeLabel(self):
        if self.operation == OperationType.DRILLED_HOLE:
            if self.cutter:
                if self.orig_shape and self.cutter.diameter < 2 * self.orig_shape.r - 0.2:
                    return f"Pilot Drill {self.cutter.diameter:0.1f}mm" if self.cutter else ""
                if self.orig_shape and self.cutter.diameter > 2 * self.orig_shape.r + 0.2:
                    return f"Oversize Drill {self.cutter.diameter:0.1f}mm" if self.cutter else ""
            return OperationType.toString(self.operation) + (f" {self.cutter.diameter:0.1f}mm" if self.cutter else "")
        return OperationType.toString(self.operation)
    def data(self, role):
        if role == Qt.DisplayRole:
            preset_if = ", " + self.tool_preset.name if self.tool_preset else ", no preset"
            return QVariant(self.operationTypeLabel() + ": " + self.orig_shape.label() + ", " + ((f"{self.depth:0.2f} mm") if self.depth is not None else "full") + f" depth{preset_if}")
        if role == Qt.DecorationRole and self.error is not None:
            return QVariant(QApplication.instance().style().standardIcon(QStyle.SP_MessageBoxCritical))
        if role == Qt.DecorationRole and self.warning is not None:
            return QVariant(QApplication.instance().style().standardIcon(QStyle.SP_MessageBoxWarning))
        if role == Qt.ToolTipRole:
            if self.error is not None:
                return QVariant(self.error)
            elif self.warning is not None:
                return QVariant(self.warning)
            else:
                return QVariant(self.operationTypeLabel() + ": " + self.orig_shape.label() + ", " + ((Format.depth_of_cut(self.depth) + " mm") if self.depth is not None else "full") + f" depth, preset: {self.tool_preset.name if self.tool_preset else 'none'}")
        return CAMTreeItem.data(self, role)
    def addWarning(self, warning):
        if self.warning is None:
            self.warning = ""
        else:
            self.warning += "\n"
        self.warning += warning
        self.emitDataChanged()
    def updateOrigShape(self):
        self.orig_shape = self.document.drawing.itemById(self.shape_id) if self.shape_id is not None else None
    def resetRenderedState(self):
        self.renderer = None
        self.document.operationsUpdated.emit()
    def startUpdateCAM(self):
        with Spinner():
            self.last_progress = (1, 100000)
            self.error = None
            self.warning = None
            self.cam = None
            self.renderer = None
            self.updateOrigShape()
            self.cancelWorker()
            if not self.cutter:
                self.error = "Cutter not set"
                self.last_progress = (1, 1)
                return
            if not self.active:
                self.last_progress = (1, 1)
                # Operation not enabled
                return
            self.updateCAMWork()
    def pollForUpdateCAM(self):
        if not self.worker:
            return self.last_progress
        self.last_progress = self.worker.getProgress()
        if self.worker and not self.worker.is_alive():
            self.worker.join()
            if self.error is None and self.worker.exception is not None:
                self.error = self.worker.exception_text
            self.worker = None
            self.document.operationsUpdated.emit()
            self.emitDataChanged()
        return self.last_progress
    def cancelWorker(self):
        if self.worker:
            self.worker.cancel()
            self.worker.join()
            self.worker = None
            self.last_progress = None
    def operationFunc(self, shape, pda):
        translation = self.document.drawing.translation()
        if len(self.user_tabs):
            tabs = self.user_tabs
        else:
            cs = self.document.config_settings
            tabs = self.tab_count if self.tab_count is not None else shape.default_tab_count(cs.min_tabs, cs.max_tabs, cs.tab_dist, cs.tab_min_length)
        if self.document.checkUpdateSuspended(self):
            return
        if self.operation == OperationType.OUTSIDE_CONTOUR:
            if pda.trc_rate:
                return lambda: self.cam.outside_contour_trochoidal(shape, pda.extra_width / 100.0, pda.trc_rate / 100.0, tabs=tabs, entry_exit=self.entry_exit)
            else:
                return lambda: self.cam.outside_contour(shape, tabs=tabs, widen=pda.extra_width / 50.0, entry_exit=self.entry_exit)
        elif self.operation == OperationType.INSIDE_CONTOUR:
            if pda.trc_rate:
                return lambda: self.cam.inside_contour_trochoidal(shape, pda.extra_width / 100.0, pda.trc_rate / 100.0, tabs=tabs, entry_exit=self.entry_exit)
            else:
                return lambda: self.cam.inside_contour(shape, tabs=tabs, widen=pda.extra_width / 50.0, entry_exit=self.entry_exit)
        elif self.operation == self.operation == OperationType.REFINE and self.shape_to_refine is not None:
            assert pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL or pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL_ZIGZAG
            if self.is_external:
                if isinstance(self.shape_to_refine, dict):
                    return lambda: self.cam.outside_peel_hsm(shape, shape_to_refine=self.shape_to_refine.get(shape, None))
                else:
                    return lambda: self.cam.outside_peel_hsm(shape, shape_to_refine=self.shape_to_refine)
            else:
                if isinstance(self.shape_to_refine, dict):
                    return lambda: self.cam.pocket_hsm(shape, shape_to_refine=self.shape_to_refine.get(shape, None))
                else:
                    return lambda: self.cam.pocket_hsm(shape, shape_to_refine=self.shape_to_refine)
        elif self.operation == OperationType.POCKET or self.operation == OperationType.REFINE:
            if pda.pocket_strategy == inventory.PocketStrategy.CONTOUR_PARALLEL:
                return lambda: self.cam.pocket(shape)
            elif pda.pocket_strategy == inventory.PocketStrategy.AXIS_PARALLEL or pda.pocket_strategy == inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG:
                return lambda: self.cam.face_mill(shape)
            elif pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL or pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL_ZIGZAG:
                return lambda: self.cam.pocket_hsm(shape)
        elif self.operation == OperationType.OUTSIDE_PEEL:
            if pda.pocket_strategy == inventory.PocketStrategy.CONTOUR_PARALLEL:
                return lambda: self.cam.outside_peel(shape)
            elif pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL or pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL_ZIGZAG:
                return lambda: self.cam.outside_peel_hsm(shape)
            else:
                raise ValueError("Strategy not supported for outside cuts")
        elif self.operation == OperationType.ENGRAVE:
            return lambda: self.cam.engrave(shape)
        elif self.operation == OperationType.INTERPOLATED_HOLE:
            return lambda: self.cam.helical_drill(self.orig_shape.centre.x + translation[0], self.orig_shape.centre.y + translation[1], 2 * self.orig_shape.r)
        elif self.operation == OperationType.DRILLED_HOLE:
            return lambda: self.cam.peck_drill(self.orig_shape.centre.x + translation[0], self.orig_shape.centre.y + translation[1])
        raise ValueError("Unsupported operation")
    def shapeToRefine(self, shape, previous, is_external):
        if is_external:
            return cam.pocket.shape_to_refine_external(shape, previous)
        else:
            return cam.pocket.shape_to_refine_internal(shape, previous)
    def refineShape(self, shape, previous, current, min_entry_dia, is_external):
        if is_external:
            return cam.pocket.refine_shape_external(shape, previous, current, min_entry_dia)
        else:
            return cam.pocket.refine_shape_internal(shape, previous, current, min_entry_dia)
    def createShapeObject(self):
        translation = self.document.drawing.translation()
        self.shape = self.orig_shape.translated(*translation).toShape()
        if not isinstance(self.shape, list) and self.operation in (OperationType.POCKET, OperationType.OUTSIDE_PEEL):
            extra_shapes = []
            for island in self.islands:
                item = self.document.drawing.itemById(island).translated(*translation).toShape()
                if isinstance(item, list):
                    for i in item:
                        self.shape.add_island(i.boundary)
                        if i.islands:
                            extra_shapes += [shapes.Shape(j, True) for j in i.islands]
                elif item.closed:
                    self.shape.add_island(item.boundary)
                    if item.islands:
                        extra_shapes += [shapes.Shape(j, True) for j in item.islands]
            if extra_shapes:
                self.shape = [self.shape] + extra_shapes
    def addDogbonesToIslands(self, shape, tool):
        new_islands = []
        for i in shape.islands:
            new_shapes = cam.dogbone.add_dogbones(shapes.Shape(i, True), tool, True, self.dogbones, False)
            if isinstance(new_shapes, list):
                new_islands += [j.boundary for j in new_shapes]
            else:
                new_islands.append(new_shapes.boundary)
        shape.islands = new_islands
    def updateCAMWork(self):
        try:
            translation = self.document.drawing.translation()
            errors = []
            if self.orig_shape:
                self.createShapeObject()
            else:
                self.shape = None
            thickness = self.document.material.thickness
            depth = self.depth if self.depth is not None else thickness
            if depth is None or depth == 0:
                raise ValueError("Neither material thickness nor cut depth is set")
            start_depth = self.start_depth if self.start_depth is not None else 0
            if self.cutter.length and depth > self.cutter.length:
                self.addWarning(f"Cut depth ({depth:0.1f} mm) greater than usable flute length ({self.cutter.length:0.1f} mm)")
            # Only checking for end mills because most drill bits have a V tip and may require going slightly past
            if isinstance(self.cutter, inventory.EndMillCutter) and depth > thickness:
                self.addWarning(f"Cut depth ({depth:0.1f} mm) greater than material thickness ({thickness:0.1f} mm)")
            if self.operation == OperationType.DRILLED_HOLE and self.cutter.diameter > 2 * self.orig_shape.r + 0.01:
                self.addWarning(f"Cutter diameter ({self.cutter.diameter:0.1f} mm) greater than hole diameter ({2 * self.orig_shape.r:0.1f} mm)")
            tab_depth = max(start_depth, depth - self.tab_height) if self.tab_height is not None else start_depth

            pda = PresetDerivedAttributes(self)
            pda.validate(errors)
            if errors:
                raise ValueError("\n".join(errors))
            if isinstance(self.cutter, inventory.EndMillCutter):
                tool = milling_tool.Tool(self.cutter.diameter, pda.hfeed, pda.vfeed, pda.doc, stepover=pda.stepover / 100.0, climb=(pda.direction == inventory.MillDirection.CLIMB), min_helix_ratio=pda.eh_diameter / 100.0)
                zigzag = pda.pocket_strategy in (inventory.PocketStrategy.HSM_PEEL_ZIGZAG, inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG, )
                self.gcode_props = gcodegen.OperationProps(-depth, -start_depth, -tab_depth, pda.offset, zigzag, pda.axis_angle * math.pi / 180)
            else:
                tool = milling_tool.Tool(self.cutter.diameter, 0, pda.vfeed, pda.doc)
                self.gcode_props = gcodegen.OperationProps(-depth, -start_depth, -tab_depth, 0)
            self.gcode_props.rpm = pda.rpm
            if self.dogbones and self.operation == OperationType.OUTSIDE_PEEL and not isinstance(self.shape, list):
                self.addDogbonesToIslands(self.shape, tool)
            if self.dogbones and self.operation not in (OperationType.ENGRAVE, OperationType.DRILLED_HOLE, OperationType.INTERPOLATED_HOLE, OperationType.OUTSIDE_PEEL):
                is_outside = self.operation == OperationType.OUTSIDE_CONTOUR
                is_refine = self.operation == OperationType.REFINE
                is_pocket = self.operation == OperationType.POCKET
                if isinstance(self.shape, list):
                    res = []
                    for i in self.shape:
                        res.append(cam.dogbone.add_dogbones(i, tool, is_outside, self.dogbones, is_refine))
                    if is_pocket:
                        for i in res:
                            self.addDogbonesToIslands(self.shape, tool)
                    self.shape = res
                else:
                    self.shape = cam.dogbone.add_dogbones(self.shape, tool, is_outside, self.dogbones, is_refine)
                    if is_pocket:
                        self.addDogbonesToIslands(self.shape, tool)
            if self.operation == OperationType.REFINE:
                diameter_plus = self.cutter.diameter + 2 * pda.offset
                prev_diameter, prev_operation, islands = self.document.largerDiameterForShape(self.orig_shape, diameter_plus)
                self.prev_diameter = prev_diameter
                if prev_diameter is None:
                    if pda.offset:
                        raise ValueError(f"No matching milling operation to refine with cutter diameter {Format.cutter_dia(self.cutter.diameter)} and offset {Format.coord(pda.offset)}")
                    else:
                        raise ValueError(f"No matching milling operation to refine with cutter diameter {Format.cutter_dia(self.cutter.diameter)}")
                is_hsm = pda.pocket_strategy in (inventory.PocketStrategy.HSM_PEEL, inventory.PocketStrategy.HSM_PEEL_ZIGZAG)
                if prev_operation.operation == OperationType.OUTSIDE_PEEL:
                    # Make up a list of shapes from shape's islands?
                    raise ValueError("Refining outside peel operations is not supported yet")
                self.is_external = (prev_operation.operation == OperationType.OUTSIDE_CONTOUR)
                self.shape_to_refine = None
                if islands and not isinstance(self.shape, list):
                    for island in islands:
                        item = self.document.drawing.itemById(island).translated(*translation).toShape()
                        if item.closed:
                            self.shape.add_island(item.boundary)
                if is_hsm:
                    if isinstance(self.shape, list):
                        self.shape_to_refine = { i : self.shapeToRefine(i, prev_diameter, self.is_external) for i in self.shape }
                    else:
                        self.shape_to_refine = self.shapeToRefine(self.shape, prev_diameter, self.is_external)
                elif isinstance(self.shape, list):
                    res = []
                    for i in self.shape:
                        res += self.refineShape(i, prev_diameter, diameter_plus, tool.min_helix_diameter, self.is_external)
                    self.shape = res
                else:
                    self.shape = self.refineShape(self.shape, prev_diameter, diameter_plus, tool.min_helix_diameter, self.is_external)
            else:
                self.prev_diameter = None
            if isinstance(self.shape, list) and len(self.shape) == 1:
                self.shape = self.shape[0]
            self.cam = gcodegen.Operations(self.document.gcode_machine_params, tool, self.gcode_props)
            self.renderer = canvas.OperationsRendererWithSelection(self)
            if self.shape:
                if isinstance(self.shape, list):
                    threadFuncs = [ self.operationFunc(shape, pda) for shape in self.shape ]
                    threadFuncs = [ fn for fn in threadFuncs if fn is not None]
                    if threadFuncs:
                        self.worker = WorkerThreadPack(self, threadFuncs)
                        self.worker.start()
                else:
                    threadFunc = self.operationFunc(self.shape, pda)
                    if threadFunc:
                        self.worker = WorkerThread(self, threadFunc)
                        self.worker.start()
            self.error = None
        except Exception as e:
            self.cam = None
            self.renderer = None
            self.error = str(e)
            self.document.operationsUpdated.emit()
            if not isinstance(e, ValueError):
                raise
    def reorderItem(self, direction):
        index = self.reorderItemImpl(direction, self.parent())
        if index is not None:
            return index
        if direction < 0:
            parentRow = self.parent().row() - 1
            while parentRow >= 0:
                otherParent = self.model().invisibleRootItem().child(parentRow)
                if otherParent.canAccept(self):
                    self.document.opMoveItem(self.parent(), self, otherParent, otherParent.rowCount())
                    return self.index()
                parentRow -= 1
            return None
        elif direction > 0:
            parentRow = self.parent().row() + 1
            while parentRow < self.model().invisibleRootItem().rowCount():
                otherParent = self.model().invisibleRootItem().child(parentRow)
                if otherParent.canAccept(self):
                    self.document.opMoveItem(self.parent(), self, otherParent, 0)
                    return self.index()
                parentRow += 1
            return None
    def invalidatedObjects(self, aspect):
        if aspect == InvalidateAspect.CAM:
            return set([self] + self.document.refineOpsForShapes(set([self.shape_id])))
        return set([self])
    def contourOrientation(self):
        pda = PresetDerivedAttributes(self)
        if self.operation == OperationType.OUTSIDE_CONTOUR:
            return pda.direction == inventory.MillDirection.CONVENTIONAL
        else:
            return pda.direction == inventory.MillDirection.CLIMB

class OperationsModel(QStandardItemModel):
    def __init__(self, document):
        QStandardItemModel.__init__(self)
        self.document = document
    def findItem(self, item):
        index = self.indexFromItem(item)
        return item.parent() or self.invisibleRootItem(), index.row()
    def removeItemAt(self, row):
        self.takeRow(row)
        return row

class MultipleItemUndoContext(object):
    def __init__(self, document, items, title_func):
        self.document = document
        self.items = items
        self.title_func = title_func
    def __enter__(self):
        if self.items and len(self.items) > 1:
            self.document.undoStack.beginMacro(self.title_func(len(self.items)))
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.items and len(self.items) > 1:
            self.document.undoStack.endMacro()

class AddOperationUndoCommand(QUndoCommand):
    def __init__(self, document, item, parent, row):
        if isinstance(item, OperationTreeItem):
            QUndoCommand.__init__(self, "Create " + item.toString())
        else:
            QUndoCommand.__init__(self, "Add tool cycle")
        self.document = document
        self.item = item
        self.parent = parent
        self.row = row
    def undo(self):
        self.parent.takeRow(self.row)
        self.document.refreshRefineForOpOrCycle(self.item)
        if isinstance(self.item, CycleTreeItem):
            del self.document.project_toolbits[self.item.cutter.name]
            self.item.document.refreshToolList()
    def redo(self):
        self.parent.insertRow(self.row, self.item)
        self.document.refreshRefineForOpOrCycle(self.item)
        if isinstance(self.item, CycleTreeItem):
            self.document.project_toolbits[self.item.cutter.name] = self.item.cutter
            self.item.document.refreshToolList()

class DeletePresetUndoCommand(QUndoCommand):
    def __init__(self, document, preset):
        QUndoCommand.__init__(self, "Delete preset: " + preset.name)
        self.document = document
        self.preset = preset
        self.was_default = False
    def undo(self):
        self.preset.toolbit.presets.append(self.preset)
        if self.was_default:
            self.document.default_preset_by_tool[self.preset.toolbit] = self.preset
        self.document.refreshToolList()
    def redo(self):
        self.preset.toolbit.deletePreset(self.preset)
        if self.document.default_preset_by_tool.get(self.preset.toolbit, None) is self.preset:
            del self.document.default_preset_by_tool[self.preset.toolbit]
            self.was_default = True
        self.document.refreshToolList()

class DeleteCycleUndoCommand(QUndoCommand):
    def __init__(self, document, cycle):
        QUndoCommand.__init__(self, "Delete cycle: " + cycle.cutter.name)
        self.document = document
        self.cycle = cycle
        self.row = None
        self.def_preset = None
        self.was_default = False
    def undo(self):
        self.document.operModel.invisibleRootItem().insertRow(self.row, self.cycle)
        self.document.project_toolbits[self.cycle.cutter.name] = self.cycle.cutter
        if self.was_default:
            self.document.selectCutterCycle(self.cycle)
        if self.def_preset is not None:
            self.document.default_preset_by_tool[self.cycle.cutter] = self.def_preset
        self.document.refreshRefineForOpOrCycle(self.cycle)
        self.document.refreshToolList()
    def redo(self):
        self.row = self.cycle.row()
        self.was_default = self.cycle is self.document.current_cutter_cycle
        self.def_preset = self.document.default_preset_by_tool.get(self.cycle.cutter, None)
        self.document.operModel.invisibleRootItem().takeRow(self.row)
        self.document.refreshRefineForOpOrCycle(self.cycle)
        del self.document.project_toolbits[self.cycle.cutter.name]
        if self.cycle.cutter in self.document.default_preset_by_tool:
            del self.document.default_preset_by_tool[self.cycle.cutter]
        self.document.refreshToolList()

class DeleteOperationUndoCommand(QUndoCommand):
    def __init__(self, document, item, parent, row):
        QUndoCommand.__init__(self, "Delete " + item.toString())
        self.document = document
        self.item = item
        self.deleted_cutter = None
        self.parent = parent
        self.row = row
    def undo(self):
        self.parent.insertRow(self.row, self.item)
        self.document.refreshRefineForOpOrCycle(self.item)
        if isinstance(self.item, CycleTreeItem) and self.deleted_cutter:
            self.document.project_toolbits[self.item.cutter.name] = self.deleted_cutter
            self.document.refreshToolList()
        elif isinstance(self.item, OperationTreeItem):
            self.item.startUpdateCAM()
    def redo(self):
        self.parent.takeRow(self.row)
        self.document.refreshRefineForOpOrCycle(self.item)
        if isinstance(self.item, CycleTreeItem):
            # Check if there are other users of the same tool
            if self.document.cycleForCutter(self.item.cutter) is None:
                self.deleted_cutter = self.document.project_toolbits[self.item.cutter.name]
                del self.document.project_toolbits[self.item.cutter.name]
                self.document.refreshToolList()
        else:
            self.item.cancelWorker()

class PropertySetUndoCommand(QUndoCommand):
    def __init__(self, property, subject, old_value, new_value):
        QUndoCommand.__init__(self, "Set " + property.name)
        self.property = property
        self.subject = subject
        self.old_value = old_value
        self.new_value = new_value
    def undo(self):
        self.property.setData(self.subject, self.old_value)
    def redo(self):
        self.property.setData(self.subject, self.new_value)

class ActiveSetUndoCommand(QUndoCommand):
    def __init__(self, changes):
        QUndoCommand.__init__(self, "Toggle active status")
        self.changes = changes
    def undo(self):
        self.applyChanges(True)
    def redo(self):
        self.applyChanges(False)
    def applyChanges(self, reverse):
        changedOpers = {}
        for item, state in self.changes:
            changedOpers[item.parent().row()] = item.parent()
            item.active = state ^ reverse
            item.updateCheckState()
        for item, state in self.changes:
            item.startUpdateCAM()
        for parent in changedOpers.values():
            parent.updateCheckState()

class MoveItemUndoCommand(QUndoCommand):
    def __init__(self, oldParent, child, newParent, pos):
        QUndoCommand.__init__(self, "Move item")
        self.oldParent = oldParent
        self.oldPos = child.row()
        self.child = child
        self.newParent = newParent
        self.newPos = pos
    def undo(self):
        self.newParent.takeRow(self.newPos)
        self.oldParent.insertRow(self.oldPos, self.child)
        if hasattr(self.newParent, 'updateItemAfterMove'):
            self.oldParent.updateItemAfterMove(self.child)
    def redo(self):
        self.oldParent.takeRow(self.oldPos)
        self.newParent.insertRow(self.newPos, self.child)
        if hasattr(self.newParent, 'updateItemAfterMove'):
            self.newParent.updateItemAfterMove(self.child)

class AddPresetUndoCommand(QUndoCommand):
    def __init__(self, item, preset):
        QUndoCommand.__init__(self, "Create preset")
        self.item = item
        self.preset = preset
    def undo(self):
        self.item.inventory_tool.deletePreset(self.preset)
        self.item.document.refreshToolList()
    def redo(self):
        self.item.inventory_tool.presets.append(self.preset)
        self.item.document.refreshToolList()

class ModifyCutterUndoCommand(QUndoCommand):
    def __init__(self, item, new_data):
        QUndoCommand.__init__(self, "Modify cutter")
        self.item = item
        self.new_data = new_data
        self.old_data = None
    def updateTo(self, data):
        cutter = self.item.inventory_tool
        cutter.resetTo(data)
        cutter.name = data.name
        self.item.emitDataChanged()
        self.item.document.refreshToolList()
    def undo(self):
        self.updateTo(self.old_data)
    def redo(self):
        cutter = self.item.inventory_tool
        self.old_data = cutter.newInstance()
        self.updateTo(self.new_data)

class ModifyPresetUndoCommand(QUndoCommand):
    def __init__(self, item, new_data):
        QUndoCommand.__init__(self, "Modify preset")
        self.item = item
        self.new_data = new_data
        self.old_data = None
    def updateTo(self, data):
        preset = self.item.inventory_preset
        preset.resetTo(data)
        preset.name = data.name
        preset.toolbit = self.item.parent().inventory_tool
        self.item.emitDataChanged()
        self.item.document.refreshToolList()
    def undo(self):
        self.updateTo(self.old_data)
    def redo(self):
        preset = self.item.inventory_preset
        self.old_data = preset.newInstance()
        self.updateTo(self.new_data)

class BaseRevertUndoCommand(QUndoCommand):
    def __init__(self, item):
        QUndoCommand.__init__(self, self.NAME)
        self.item = item
        self.old = None
    def undo(self):
        self.updateTo(self.old)

class RevertPresetUndoCommand(BaseRevertUndoCommand):
    NAME = "Revert preset"
    def updateTo(self, data):
        preset = self.item.inventory_preset
        preset.resetTo(data)
        preset.toolbit = self.item.parent().inventory_tool
        self.item.emitDataChanged()
        self.item.document.refreshToolList()
    def redo(self):
        preset = self.item.inventory_preset
        self.old = preset.newInstance()
        self.updateTo(preset.base_object)

class RevertToolUndoCommand(BaseRevertUndoCommand):
    NAME = "Revert tool"
    def updateTo(self, data):
        tool = self.item.inventory_tool
        tool.resetTo(data)
        self.item.emitDataChanged()
        self.item.document.refreshToolList()
    def redo(self):
        tool = self.item.inventory_tool
        self.old = tool.newInstance()
        self.updateTo(tool.base_object)

class BlockmapEntry(object):
    def __init__(self):
        self.starts = set()
        self.ends = set()

class Blockmap(dict):
    def pt_to_index(self, pt):
        res = geom.GeometrySettings.RESOLUTION
        return (int(pt.x * res), int(pt.y * res))
    def point(self, pt):
        i = self.pt_to_index(pt)
        res = self.get(i, None)
        if res is None:
            res = self[i] = BlockmapEntry()
        return res
    def start_point(self, points):
        return self.point(points[0].seg_start())
    def end_point(self, points):
        return self.point(points[-1].seg_end())

class DeleteDrawingItemsUndoCommand(QUndoCommand):
    def __init__(self, document, items):
        QUndoCommand.__init__(self, "Delete drawing items")
        self.document = document
        self.items = [(self.document.drawing, item.row(), item) for item in items]
        self.items = sorted(self.items, key=lambda item: item[1])
    def undo(self):
        for parent, pos, item in self.items:
            parent.insertRow(pos, item)
        self.document.shapesUpdated.emit()
    def redo(self):
        for parent, pos, item in self.items[::-1]:
            parent.takeRow(pos)
        self.document.shapesUpdated.emit()

class AddDrawingItemsUndoCommand(QUndoCommand):
    def __init__(self, document, items):
        QUndoCommand.__init__(self, "Add drawing items")
        self.document = document
        self.items = items
        self.pos = self.document.drawing.rowCount()
    def undo(self):
        for i in range(len(self.items)):
            self.document.drawing.takeRow(self.pos)
        self.document.shapesUpdated.emit()
    def redo(self):
        self.document.drawing.insertRows(self.pos, self.items)
        self.document.shapesUpdated.emit()

class JoinItemsUndoCommand(QUndoCommand):
    def __init__(self, document, items):
        QUndoCommand.__init__(self, "Join items")
        self.document = document
        self.items = items
        self.original_items = {}
        self.removed_items = []
    def undo(self):
        root = self.document.shapeModel.invisibleRootItem()
        pos = self.document.drawing.row()
        root.takeRow(pos)
        for item, points in self.original_items.items():
            item.untransformed.points = points
            item.closed = False
        for row, item in self.removed_items:
            self.document.drawing.insertRow(row, item)
        root.insertRow(pos, self.document.drawing)
        self.document.shapesUpdated.emit()
    def redo(self):
        def rev(pts):
            return geom.Path(pts, False).reverse().nodes
        def join(p1, p2):
            if not p1[-1].is_arc():
                assert not p2[0].is_arc()
                return p1[:-1] + p2
            else:
                return p1 + p2
        blockmap = Blockmap()
        joined = set()
        edges = set()
        toRemove = set()
        toRecalc = set()
        originals = {}
        for i in self.items:
            points = i.untransformed.points
            originals[i] = points
            start = blockmap.pt_to_index(points[0].seg_start())
            end = blockmap.pt_to_index(points[-1].seg_end())
            if (end, start) in edges or (start, end) in edges:
                # Duplicates
                toRemove.add(i)
                continue
            edges.add((start, end))
            blockmap.start_point(points).starts.add(i)
            blockmap.end_point(points).ends.add(i)
        for bme in blockmap.values():
            while len(bme.starts) >= 1 and len(bme.ends) >= 1:
                i = bme.ends.pop()
                j = bme.starts.pop()
                if i is j:
                    i.untransformed.closed = True
                    del i.untransformed.points[-1:]
                    continue
                i.untransformed.points = join(i.untransformed.points, j.untransformed.points)
                p = blockmap.end_point(j.untransformed.points)
                p.ends.remove(j)
                p.ends.add(i)
                toRecalc.add(i)
                toRemove.add(j)
            while len(bme.starts) >= 2:
                i = bme.starts.pop()
                j = bme.starts.pop()
                if i is j:
                    assert False
                i.untransformed.points = join(rev(j.untransformed.points), i.untransformed.points)
                p = blockmap.end_point(j.untransformed.points)
                p.ends.remove(j)
                p.starts.add(i)
                toRecalc.add(i)
                toRemove.add(j)
            while len(bme.ends) >= 2:
                i = bme.ends.pop()
                j = bme.ends.pop()
                i.untransformed.points = join(i.untransformed.points, rev(j.untransformed.points))
                p = blockmap.start_point(j.untransformed.points)
                p.starts.remove(j)
                p.ends.add(i)
                toRecalc.add(i)
                toRemove.add(j)
        for i in toRecalc:
            i.untransformed.calcBounds()
        root = self.document.shapeModel.invisibleRootItem()
        pos = self.document.drawing.row()
        root.takeRow(pos)
        self.original_items = {k : v for k, v in originals.items() if k in toRecalc}
        self.removed_items = []
        for i in toRemove:
            row = i.row()
            self.removed_items.append((row, self.document.drawing.takeRow(row)))
        self.removed_items = self.removed_items[::-1]
        root.insertRow(pos, self.document.drawing)
        self.document.shapesUpdated.emit()

class DocumentModel(QObject):
    propertyChanged = pyqtSignal([CAMTreeItem, str])
    cutterSelected = pyqtSignal([CycleTreeItem])
    tabEditRequested = pyqtSignal([OperationTreeItem])
    islandsEditRequested = pyqtSignal([OperationTreeItem])
    entryExitEditRequested = pyqtSignal([OperationTreeItem])
    toolListRefreshed = pyqtSignal([])
    operationsUpdated = pyqtSignal([])
    shapesUpdated = pyqtSignal([])
    projectCleared = pyqtSignal([])
    projectLoaded = pyqtSignal([])
    drawingImported = pyqtSignal([])
    def __init__(self, config_settings):
        QObject.__init__(self)
        self.config_settings = config_settings
        self.undoStack = QUndoStack(self)
        self.material = WorkpieceTreeItem(self)
        self.makeMachineParams()
        self.drawing = DrawingTreeItem(self)
        self.filename = None
        self.drawing_filename = None
        self.current_cutter_cycle = None
        self.project_toolbits = {}
        self.default_preset_by_tool = {}
        self.shapes_to_revisit = set()
        self.progress_dialog_displayed = False
        self.update_suspended = None
        self.update_suspended_dirty = False
        self.tool_list = ToolListTreeItem(self)
        self.shapeModel = QStandardItemModel()
        self.shapeModel.setHorizontalHeaderLabels(["Input object"])
        self.shapeModel.appendRow(self.material)
        self.shapeModel.appendRow(self.tool_list)
        self.shapeModel.appendRow(self.drawing)

        self.operModel = OperationsModel(self)
        self.operModel.setHorizontalHeaderLabels(["Operation"])
        self.operModel.dataChanged.connect(self.operDataChanged)
        self.operModel.rowsInserted.connect(self.operRowsInserted)
        self.operModel.rowsRemoved.connect(self.operRowsRemoved)
        self.operModel.rowsAboutToBeRemoved.connect(self.operRowsAboutToBeRemoved)

    def reinitDocument(self):
        self.undoStack.clear()
        self.undoStack.setClean()
        self.material.resetProperties()
        self.makeMachineParams()
        self.current_cutter_cycle = None
        self.project_toolbits = {}
        self.default_preset_by_tool = {}
        self.update_suspended = None
        self.update_suspended_dirty = False
        self.refreshToolList()
        self.drawing.reset()
        self.drawing.removeRows(0, self.drawing.rowCount())
        self.operModel.removeRows(0, self.operModel.rowCount())
    def refreshToolList(self):
        self.tool_list.reset()
        self.toolListRefreshed.emit()
    def allCycles(self):
        return [self.operModel.item(i) for i in range(self.operModel.rowCount())]
    def store(self):
        #cutters = set(self.forEachOperation(lambda op: op.cutter))
        #presets = set(self.forEachOperation(lambda op: op.tool_preset))
        data = {}
        data['material'] = self.material.store()
        data['tools'] = [i.store() for i in self.project_toolbits.values()]
        data['tool_presets'] = [j.store() for i in self.project_toolbits.values() for j in i.presets]
        data['default_presets'] = [{'tool_id' : k.id, 'preset_id' : v.id} for k, v in self.default_preset_by_tool.items()]
        data['drawing'] = { 'header' : self.drawing.store(), 'items' : [item.store() for item in self.drawing.items()] }
        data['operation_cycles'] = [ { 'tool_id' : cycle.cutter.id, 'is_current' : (self.current_cutter_cycle is cycle), 'operations' : [op.store() for op in cycle.items()] } for cycle in self.allCycles() ]
        #data['current_cutter_id'] = self.current_cutter_cycle.cutter.id if self.current_cutter_cycle is not None else None
        return data
    def load(self, data):
        self.reinitDocument()
        self.default_preset_by_tool = {}
        self.material.reload(data['material'])
        currentCutterCycle = None
        cycleForCutter = {}
        if 'tool' in data:
            # Old style singleton tool
            material = MaterialType.toTuple(self.material.material)[2] if self.material.material is not None else material_plastics
            tool = data['tool']
            prj_cutter = inventory.EndMillCutter.new(None, "Project tool", inventory.CutterMaterial.carbide, tool['diameter'], tool['cel'], tool['flutes'])
            std_tool = milling_tool.standard_tool(prj_cutter.diameter, prj_cutter.flutes, material, milling_tool.carbide_uncoated).clone_with_overrides(
                hfeed=tool['hfeed'], vfeed=tool['vfeed'], maxdoc=tool['depth'], rpm=tool['rpm'], stepover=tool.get('stepover', None))
            prj_preset = inventory.EndMillPreset.new(None, "Project preset", prj_cutter,
                std_tool.rpm, std_tool.hfeed, std_tool.vfeed, std_tool.maxdoc, 0, std_tool.stepover,
                tool.get('direction', 0), 0, 0, None, 0, 0.5)
            prj_cutter.presets.append(prj_preset)
            self.opAddCutter(prj_cutter)
            self.default_preset_by_tool[prj_cutter] = prj_preset
            self.refreshToolList()
        add_cycles = 'operation_cycles' not in data
        cycle = None
        if 'tools' in data:
            std_cutters = { i.name : i for i in inventory.inventory.toolbits }
            cutters = [inventory.CutterBase.load(i, default_type='EndMillCutter') for i in data['tools']]
            presets = [inventory.PresetBase.load(i, default_type='EndMillPreset') for i in data['tool_presets']]
            cutter_map = { i.orig_id : i for i in cutters }
            preset_map = { i.orig_id : i for i in presets }
            # Try to map to standard cutters
            for cutter in cutters:
                orig_id = cutter.orig_id
                if cutter.name in std_cutters:
                    std = std_cutters[cutter.name]
                    cutter.base_object = std
                    if debug_inventory_matching:
                        if std.equals(cutter):
                            print ("Matched library tool", cutter.name)
                        else:
                            print ("Found different library tool with same name", cutter.name)
                    cutter_map[cutter.orig_id] = cutter
                    self.project_toolbits[cutter.name] = cutter
                else:
                    if debug_inventory_matching:
                        print ("New tool without library prototype", cutter.name)
                    # New tool not present in the inventory
                    self.project_toolbits[cutter.name] = cutter
                if add_cycles:
                    cycle = CycleTreeItem(self, cutter)
                    cycleForCutter[orig_id] = cycle
                    self.operModel.appendRow(cycle)
                    if cutter.orig_id == data.get('current_cutter_id', None):
                        currentCutterCycle = cycle
                    else:
                        currentCutterCycle = currentCutterCycle or cycle
            # Fixup cutter references (they're initially loaded as ints instead)
            for i in presets:
                i.toolbit = cutter_map[i.toolbit]
                if i.toolbit.base_object is not None:
                    i.base_object = i.toolbit.base_object.presetByName(i.name)
                i.toolbit.presets.append(i)
            self.refreshToolList()
        if 'default_presets' in data:
            for i in data['default_presets']:
                def_tool_id = i['tool_id']
                def_preset_id = i['preset_id']
                if def_tool_id in cutter_map and def_preset_id in preset_map:
                    self.default_preset_by_tool[cutter_map[def_tool_id]] = preset_map[def_preset_id]
                else:
                    print (f"Warning: bogus default preset entry, tool {def_tool_id}, preset {def_preset_id}")
        #self.tool.reload(data['tool'])
        self.drawing.reset()
        self.drawing.reload(data['drawing']['header'])
        for i in data['drawing']['items']:
            self.drawing.appendRow(DrawingItemTreeItem.load(self, i))
        if 'operations' in data:
            for i in data['operations']:
                operation = CAMTreeItem.load(self, i)
                if ('cutter' not in i) and ('tool' in data):
                    cycle = self.operModel.item(0)
                    operation.cutter = prj_cutter
                    operation.tool_preset = prj_preset
                else:
                    cycle = cycleForCutter[operation.cutter]
                    operation.cutter = cutter_map[operation.cutter]
                    operation.tool_preset = preset_map[operation.tool_preset] if operation.tool_preset else None
                operation.updateOrigShape()
                if operation.orig_shape is None:
                    print ("Warning: dangling reference to shape %d, ignoring the referencing operation" % (operation.shape_id, ))
                else:
                    cycle.appendRow(operation)
        elif 'operation_cycles' in data:
            for i in data['operation_cycles']:
                cycle = CycleTreeItem(self, cutter_map[i['tool_id']])
                cycleForCutter[orig_id] = cycle
                self.operModel.appendRow(cycle)
                if i['is_current']:
                    currentCutterCycle = cycle
                for j in i['operations']:
                    operation = CAMTreeItem.load(self, j)
                    operation.cutter = cutter_map[operation.cutter]
                    operation.tool_preset = preset_map[operation.tool_preset] if operation.tool_preset else None
                    cycle.appendRow(operation)
        self.startUpdateCAM()
        if currentCutterCycle:
            self.selectCutterCycle(currentCutterCycle)
        self.undoStack.clear()
        self.undoStack.setClean()
    def loadProject(self, fn):
        f = open(fn, "r")
        data = json.load(f)
        f.close()
        self.filename = fn
        self.drawing_filename = None
        self.load(data)
        self.projectLoaded.emit()
    def makeMachineParams(self):
        self.gcode_machine_params = gcodegen.MachineParams(safe_z = self.material.clearance, semi_safe_z = self.material.safe_entry_z)
    def newDocument(self):
        self.reinitDocument()
        self.filename = None
        self.drawing_filename = None
        self.projectCleared.emit()
    def importDrawing(self, fn):
        if self.drawing_filename is None:
            self.drawing_filename = fn
        self.drawing.importDrawing(fn)
    def allOperationsPlusRefinements(self, func=None):
        ops = set(self.allOperations(func))
        shape_ids = set([op.shape_id for op in ops])
        for op in self.refineOpsForShapes(shape_ids):
            ops.add(op)
        return list(ops)
    def allOperations(self, func=None):
        res = []
        for i in range(self.operModel.rowCount()):
            cycle : CycleTreeItem = self.operModel.item(i)
            for j in range(cycle.rowCount()):
                operation : OperationTreeItem = cycle.child(j)
                if func is None or func(operation):
                    res.append(operation)
        return res
    def forEachOperation(self, func):
        res = []
        for i in range(self.operModel.rowCount()):
            cycle : CycleTreeItem = self.operModel.item(i)
            for j in range(cycle.rowCount()):
                operation : OperationTreeItem = cycle.child(j)
                res.append(func(operation))
        return res
    def largerDiameterForShape(self, shape, min_size):
        candidates = []
        for operation in self.forEachOperation(lambda operation: operation):
            pda = PresetDerivedAttributes(operation)
            diameter_plus = operation.cutter.diameter + 2 * pda.offset
            if (operation.shape_id is shape.shape_id) and (diameter_plus > min_size):
                candidates.append((diameter_plus, operation))
        if not candidates:
            return None, None, None
        islands = None
        candidates = list(sorted(candidates, key = lambda item: item[0]))
        for diameter_plus, operation in candidates:
            if operation.areIslandsEditable() and operation.islands:
                islands = operation.islands
                break
        return candidates[0][0], candidates[0][1], islands
    def operDataChanged(self, topLeft, bottomRight, roles):
        if not roles or (Qt.CheckStateRole in roles):
            changes = []
            for row in range(topLeft.row(), bottomRight.row() + 1):
                item = topLeft.model().itemFromIndex(topLeft.siblingAtRow(row))
                if isinstance(item, OperationTreeItem):
                    active = item.checkState() != Qt.CheckState.Unchecked
                    if active != item.active:
                        changes.append((item, active))
                if isinstance(item, CycleTreeItem):
                    reqState = item.checkState()
                    itemState = item.operCheckState()
                    if reqState != itemState:
                        reqActive = reqState != Qt.CheckState.Unchecked
                        for i in item.items():
                            if i.active != reqActive:
                                changes.append((i, reqActive))
            if changes:
                self.opChangeActive(changes)
        if not roles or (Qt.DisplayRole in roles):
            shape_ids = set()
            for row in range(topLeft.row(), bottomRight.row() + 1):
                item = topLeft.model().itemFromIndex(topLeft.siblingAtRow(row))
                if isinstance(item, OperationTreeItem):
                    shape_ids.add(item.shape_id)
            self.updateRefineOps(shape_ids)
    def operRowsInserted(self, parent, first, last):
        item = self.operModel.itemFromIndex(parent)
        if isinstance(item, CycleTreeItem):
            item.updateCheckState()
            self.updateRefineOps(self.shapesForOperationRange(item, first, last))
    def operRowsAboutToBeRemoved(self, parent, first, last):
        item = self.operModel.itemFromIndex(parent)
        if isinstance(item, CycleTreeItem):
            self.shapes_to_revisit |= self.shapesForOperationRange(item, first, last)
    def operRowsRemoved(self, parent, first, last):
        item = self.operModel.itemFromIndex(parent)
        if isinstance(item, CycleTreeItem):
            item.updateCheckState()
        if self.shapes_to_revisit:
            self.updateRefineOps(self.shapes_to_revisit)
            self.shapes_to_revisit = set()
    def shapesForOperationRange(self, parent, first, last):
        shape_ids = set()
        for row in range(first, last + 1):
            item = parent.child(row)
            shape_ids.add(item.shape_id)
        return shape_ids
    def updateRefineOps(self, shape_ids):
        self.forEachOperation(lambda item: self.updateRefineOp(item, shape_ids))
    def updateRefineOp(self, operation, shape_ids):
        if operation.operation == OperationType.REFINE and operation.shape_id in shape_ids and operation.orig_shape:
            pda = PresetDerivedAttributes(operation)
            diameter_plus = operation.cutter.diameter + 2 * pda.offset
            prev_diameter, prev_operation, islands = self.largerDiameterForShape(operation.orig_shape, diameter_plus)
            if prev_diameter != operation.prev_diameter:
                operation.startUpdateCAM()
    def startUpdateCAM(self, subset=None):
        self.makeMachineParams()
        if subset is None:
            self.forEachOperation(lambda item: item.startUpdateCAM())
        else:
            self.forEachOperation(lambda item: item.startUpdateCAM() if item in subset else None)
    def cancelAllWorkers(self):
        self.forEachOperation(lambda item: item.cancelWorker())
    def pollForUpdateCAM(self):
        has_workers = any(self.forEachOperation(lambda item: item.worker))
        if not has_workers:
            return
        results = self.forEachOperation(lambda item: item.pollForUpdateCAM())
        totaldone = 0
        totaloverall = 0
        for i in results:
            if i is not None:
                totaldone += i[0]
                totaloverall += i[1]
        if totaloverall > 0:
            return totaldone / totaloverall
    def waitForUpdateCAM(self):
        if self.pollForUpdateCAM() is None:
            return True
        if is_gui_application():
            try:
                self.progress_dialog_displayed = True
                progress = QProgressDialog()
                progress.show()
                progress.setWindowModality(Qt.WindowModal)
                progress.setLabelText("Calculating toolpaths")
                cancelled = False
                while True:
                    if progress.wasCanceled():
                        self.cancelAllWorkers()
                        cancelled = True
                        break
                    pollValue = self.pollForUpdateCAM()
                    if pollValue is None:
                        break
                    progress.setValue(int(pollValue * 100))
                    QGuiApplication.sync()
                    time.sleep(0.25)
            finally:
                self.progress_dialog_displayed = False
        else:
            cancelled = False
            while self.pollForUpdateCAM() is not None:
                time.sleep(0.25)
        return not cancelled
    def checkCAMErrors(self):
        return self.forEachOperation(lambda item: item.error)
    def checkCAMWarnings(self):
        return self.forEachOperation(lambda item: item.warning)
    def getToolbitList(self, data_type: type):
        res = [(tb.id, tb.description()) for tb in self.project_toolbits.values() if isinstance(tb, data_type)]
        #res += [(tb.id, tb.description()) for tb in inventory.inventory.toolbits if isinstance(tb, data_type) and tb.presets]
        return res
    def validateForOutput(self):
        def validateOperation(item):
            if item.depth is None:
                if self.material.thickness is None or self.material.thickness == 0:
                    raise ValueError("Default material thickness not set")
            if item.error is not None:
                raise ValueError(item.error)
        self.forEachOperation(validateOperation)
    def setOperSelection(self, selection):
        changes = []
        def setSelected(operation):
            isIn = (operation in selection)
            if operation.isSelected != isIn:
                operation.isSelected = isIn
                return True
        return any(self.forEachOperation(setSelected))
    def cycleForCutter(self, cutter: inventory.CutterBase):
        for i in range(self.operModel.rowCount()):
            cycle: CycleTreeItem = self.operModel.item(i)
            if cycle.cutter == cutter:
                return cycle
        return None
    def selectCutterCycle(self, cycle):
        old = self.current_cutter_cycle
        self.current_cutter_cycle = cycle
        self.current_cutter_cycle.emitDataChanged()
        if old:
            old.emitDataChanged()
        self.cutterSelected.emit(cycle)
    def selectPresetAsDefault(self, toolbit, preset):
        old = self.default_preset_by_tool.get(toolbit, None)
        self.default_preset_by_tool[toolbit] = preset
        if old:
            self.itemForPreset(old).emitDataChanged()
        if preset:
            self.itemForPreset(preset).emitDataChanged()
    def itemForCutter(self, cutter):
        for i in range(self.tool_list.rowCount()):
            tool = self.tool_list.child(i)
            if tool.inventory_tool is cutter:
                return tool
    def itemForPreset(self, preset):
        tool = self.itemForCutter(preset.toolbit)
        for i in range(tool.rowCount()):
            p = tool.child(i)
            if p.inventory_preset is preset:
                return p
    def refineOpsForShapes(self, shape_ids):
        return self.allOperations(lambda item: item.operation == OperationType.REFINE and item.shape_id in shape_ids)
    def refreshRefineForOpOrCycle(self, item):
        shape_ids = set()
        if isinstance(item, CycleTreeItem):
            for i in item.items():
                self.refreshRefineForOpOrCycle(i)
        elif isinstance(item, OperationTreeItem):
            shape_ids.add(item.shape_id)
        refineOps = self.refineOpsForShapes(shape_ids)
        for i in refineOps:
            i.startUpdateCAM()
    def checkUpdateSuspended(self, item):
        if self.update_suspended is item:
            self.update_suspended_dirty = True
            return True
        return False
    def setUpdateSuspended(self, item):
        if self.update_suspended is item:
            return
        was_suspended = self.update_suspended if self.update_suspended_dirty else None
        self.update_suspended = item
        self.update_suspended_dirty = False
        if was_suspended is not None:
            was_suspended.startUpdateCAM()
    def exportGcode(self, fn):
        with Spinner():
            OpExporter(self).write(fn)
    def opAddCutter(self, cutter: inventory.CutterBase):
        cycle = CycleTreeItem(self, cutter)
        self.undoStack.push(AddOperationUndoCommand(self, cycle, self.operModel.invisibleRootItem(), self.operModel.rowCount()))
        #self.operModel.appendRow(self.current_cutter_cycle)
        self.refreshToolList()
        self.selectCutterCycle(cycle)
        return cycle
    def opAddProjectPreset(self, cutter: inventory.CutterBase, preset: inventory.PresetBase):
        item = self.itemForCutter(cutter)
        self.undoStack.push(AddPresetUndoCommand(item, preset))
    def opAddLibraryPreset(self, library_preset: inventory.PresetBase):
        # XXXKF undo
        for cutter in self.project_toolbits.values():
            if cutter.base_object is library_preset.toolbit:
                preset = library_preset.newInstance()
                preset.toolbit = cutter
                cutter.presets.append(preset)
                self.refreshToolList()
                return cutter, preset, False
        else:
            preset = library_preset.newInstance()
            cutter = library_preset.toolbit.newInstance()
            preset.toolbit = cutter
            cutter.presets.append(preset)
            return cutter, preset, True
    def opCreateOperation(self, shapeIds, operationType, cycle=None):
        if cycle is None:
            cycle = self.current_cutter_cycle
            if cycle is None:
                raise ValueError("Cutter not selected")
        with MultipleItemUndoContext(self, shapeIds, lambda count: f"Create {count} of {OperationType.toString(operationType)}"):
            indexes = []
            rowCount = cycle.rowCount()
            for i in shapeIds:
                item = CAMTreeItem.load(self, { '_type' : 'OperationTreeItem', 'shape_id' : i, 'operation' : operationType })
                item.cutter = cycle.cutter
                item.tool_preset = self.default_preset_by_tool.get(item.cutter, None)
                item.islands = shapeIds[i]
                item.startUpdateCAM()
                self.undoStack.push(AddOperationUndoCommand(self, item, cycle, rowCount))
                indexes.append(item.index())
                rowCount += 1
        return rowCount, cycle, indexes
    def opChangeProperty(self, property, changes):
        with MultipleItemUndoContext(self, changes, lambda count: f"Set {property.name} on {count} items"):
            for subject, value in changes:
                self.undoStack.push(PropertySetUndoCommand(property, subject, property.getData(subject), value))
    def opChangeActive(self, changes):
        self.undoStack.push(ActiveSetUndoCommand(changes))
    def opDeleteOperations(self, items):
        with MultipleItemUndoContext(self, items, lambda count: f"Delete {count} cycles/operations"):
            for item in items:
                parent, row = self.operModel.findItem(item)
                if isinstance(item, OperationTreeItem):
                    self.undoStack.push(DeleteOperationUndoCommand(self, item, parent, row))
                elif isinstance(item, CycleTreeItem):
                    self.undoStack.push(DeleteCycleUndoCommand(self, item))
    def opMoveItem(self, oldParent, child, newParent, pos):
        self.undoStack.push(MoveItemUndoCommand(oldParent, child, newParent, pos))
    def opMoveItems(self, items, direction):
        itemsToMove = []
        for item in items:
            if hasattr(item, 'reorderItem'):
                itemsToMove.append(item)
        if not itemsToMove:
            return
        indexes = []
        itemsToMove = list(sorted(itemsToMove, key=lambda item: -item.row() * direction))
        dir_text = "down" if direction > 0 else "up"
        with MultipleItemUndoContext(self, itemsToMove, lambda count: f"Move {count} operations {dir_text}"):
            for item in itemsToMove:
                index = item.reorderItem(direction)
                if index is not None:
                    indexes.append(index)
        return indexes
    def opDeletePreset(self, preset):
        self.undoStack.beginMacro(f"Delete preset: {preset.name}")
        try:
            changes = []
            self.forEachOperation(lambda operation: changes.append((operation, None)) if operation.tool_preset is preset else None)
            self.opChangeProperty(OperationTreeItem.prop_preset, changes)
            self.undoStack.push(DeletePresetUndoCommand(self, preset))
        finally:
            self.undoStack.endMacro()
    def opDeleteCycle(self, cycle):
        self.undoStack.beginMacro(f"Delete cycle: {cycle.cutter.name}")
        try:
            self.undoStack.push(DeleteCycleUndoCommand(self, cycle))
        finally:
            self.undoStack.endMacro()
    def opUnlinkInventoryCutter(self, cutter):
        for tb in self.project_toolbits:
            if tb.base_object is preset:
                tb.base_object = None
    def opUnlinkInventoryPreset(self, preset):
        for tb in self.project_toolbits.values():
            for p in tb.presets:
                if p.base_object is preset:
                    p.base_object = None
    def opRevertPreset(self, item):
        self.undoStack.push(RevertPresetUndoCommand(item))
    def opRevertTool(self, item):
        self.undoStack.push(RevertToolUndoCommand(item))
    def opModifyPreset(self, preset, new_data):
        item = self.itemForPreset(preset)
        self.undoStack.push(ModifyPresetUndoCommand(item, new_data))
    def opModifyCutter(self, cutter, new_data):
        item = self.itemForCutter(cutter)
        self.undoStack.push(ModifyCutterUndoCommand(item, new_data))
    def opJoin(self, items):
        self.undoStack.push(JoinItemsUndoCommand(self, items))
    def opAddDrawingItems(self, items):
        self.undoStack.push(AddDrawingItemsUndoCommand(self, items))
    def opDeleteDrawingItems(self, shapes):
        for i in shapes:
            if not isinstance(i, DrawingItemTreeItem):
                raise ValueError("Cannot delete an item of type: " + str(i.__class__.__name__))
        self.undoStack.push(DeleteDrawingItemsUndoCommand(self, shapes))
    def undo(self):
        self.undoStack.undo()
    def redo(self):
        self.undoStack.redo()

class OpExporter(object):
    def __init__(self, document):
        document.waitForUpdateCAM()
        self.operations = gcodegen.Operations(document.gcode_machine_params)
        self.all_cutters = set([])
        self.cutter = None
        document.forEachOperation(self.add_cutter)
        document.forEachOperation(self.process_operation)
    def add_cutter(self, item):
        if item.cam:
            self.all_cutters.add(item.cutter)
    def process_operation(self, item):
        if item.cam:
            if item.cutter != self.cutter and len(self.all_cutters) > 1:
                self.operations.add(gcodegen.ToolChangeOperation(item.cutter))
                self.cutter = item.cutter
            self.operations.add_all(item.cam.operations)
    def write(self, fn):
        self.operations.to_gcode_file(fn)
