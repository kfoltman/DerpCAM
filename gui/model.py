import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

import process
import gcodegen
from propsheet import EnumClass, IntEditableProperty, FloatEditableProperty, EnumEditableProperty, SetEditableProperty
import view
from milling_tool import *

import ezdxf
import json

class DrawingUIMode(object):
    MODE_NORMAL = 0
    MODE_ISLANDS = 1
    MODE_TABS = 2

class OperationsRendererWithSelection(view.OperationsRenderer):
    def __init__(self, owner):
        view.OperationsRenderer.__init__(self, owner.cam)
        self.owner = owner
    def isHighlighted(self, operation):
        return self.owner.isSelected

class CAMTreeItem(QStandardItem):
    def __init__(self, document, name=None):
        QStandardItem.__init__(self, name)
        self.document = document
        self.setEditable(False)
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

class DrawingItemTreeItem(CAMTreeItem):
    defaultGrayPen = QPen(QColor(0, 0, 0, 64), 0)
    defaultDrawingPen = QPen(QColor(0, 0, 0, 255), 0)
    selectedItemDrawingPen = QPen(QColor(0, 64, 128, 255), 2)
    selectedItemDrawingPen2 = QPen(QColor(0, 64, 128, 255), 1)
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
    def penForPath(self, path, modeData):
        if modeData[0] == DrawingUIMode.MODE_ISLANDS:
            if modeData[1].shape_id == self.shape_id:
                return self.defaultDrawingPen
            if self.shape_id in modeData[1].islands:
                return self.selectedItemDrawingPen2
            return self.defaultGrayPen
        if modeData[0] == DrawingUIMode.MODE_TABS:
            if modeData[1].shape_id == self.shape_id:
                return self.defaultDrawingPen
            return self.defaultGrayPen
        return self.selectedItemPenFunc if self.untransformed in path.selection else self.defaultDrawingPen
    def store(self):
        return { '_type' : type(self).__name__, 'shape_id' : self.shape_id }
    @classmethod
    def load(klass, document, dump):
        rtype = dump['_type']
        if rtype == 'DrawingPolyline' or rtype == 'DrawingPolylineTreeItem':
            item = DrawingPolylineTreeItem(document, dump['points'], dump.get('closed', True))
        elif rtype == 'DrawingCircle' or rtype == 'DrawingCircleTreeItem':
            item = DrawingCircleTreeItem(document, (dump['cx'], dump['cy']), dump['r'])
        else:
            raise ValueError("Unexpected type: %s" % rtype)
        item.shape_id = dump['shape_id']
        klass.next_drawing_item_id = max(item.shape_id + 1, klass.next_drawing_item_id)
        return item
    def onPropertyValueSet(self, name):
        self.emitDataChanged()
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(self.textDescription())
        return CAMTreeItem.data(self, role)

class DrawingCircleTreeItem(DrawingItemTreeItem):
    prop_x = FloatEditableProperty("Centre X", "x", "%0.2f mm", min=0, max=100, allow_none=False)
    prop_y = FloatEditableProperty("Centre Y", "y", "%0.2f mm", min=0, max=100, allow_none=False)
    prop_dia = FloatEditableProperty("Diameter", "diameter", "%0.2f mm", min=0, max=100, allow_none=False)
    prop_radius = FloatEditableProperty("Radius", "radius", "%0.2f mm", min=0, max=100, allow_none=False)
    def __init__(self, document, centre, r, untransformed = None):
        DrawingItemTreeItem.__init__(self, document)
        self.centre = (centre[0], centre[1])
        self.r = r
        self.calcBounds()
        self.untransformed = untransformed if untransformed is not None else self
    def properties(self):
        return [self.prop_x, self.prop_y, self.prop_dia, self.prop_radius]
    def getPropertyValue(self, name):
        if name == 'x':
            return self.centre[0]
        elif name == 'y':
            return self.centre[1]
        elif name == 'radius':
            return self.r
        elif name == 'diameter':
            return 2 * self.r
        else:
            assert False, "Unknown property: " + name
    def setPropertyValue(self, name, value):
        if name == 'x':
            self.centre = (value, self.centre[1])
        elif name == 'y':
            self.centre = (self.centre[0], value)
        elif name == 'radius':
            self.r = value
        elif name == 'diameter':
            self.r = value / 2.0
        else:
            assert False, "Unknown property: " + name
        self.emitDataChanged()
    def calcBounds(self):
        self.bounds = (self.centre[0] - self.r, self.centre[1] - self.r,
            self.centre[0] + self.r, self.centre[1] + self.r)
    def distanceTo(self, pt):
        return abs(dist(self.centre, pt) - self.r)
    def renderTo(self, path, modeData):
        path.addLines(self.penForPath(path, modeData), circle(self.centre[0], self.centre[1], self.r), True)
    def label(self):
        return "Circle%d" % self.shape_id
    def textDescription(self):
        return self.label() + ("(X=%0.2f, Y=%0.2f, D=%0.2f)" % (*self.centre, 2 * self.r))
    def toShape(self):
        return process.Shape.circle(*self.centre, self.r)
    def translated(self, dx, dy):
        cti = DrawingCircleTreeItem(self.document, translate_point(self.centre, dx, dy), self.r, self.untransformed)
        cti.shape_id = self.shape_id
        return cti
    def scaled(self, cx, cy, scale):
        return DrawingCircleTreeItem(self.document, scale_point(self.centre, cx, cy, scale), self.r * scale, self.untransformed)
    def store(self):
        res = DrawingItemTreeItem.store(self)
        res['cx'] = self.centre[0]
        res['cy'] = self.centre[1]
        res['r'] = self.r
        return res

class DrawingPolylineTreeItem(DrawingItemTreeItem):
    def __init__(self, document, points, closed, untransformed = None):
        DrawingItemTreeItem.__init__(self, document)
        self.points = points
        if points:
            xcoords = [p[0] for p in self.points if len(p) == 2]
            ycoords = [p[1] for p in self.points if len(p) == 2]
            self.bounds = (min(xcoords), min(ycoords), max(xcoords), max(ycoords))
        else:
            self.bounds = None
        self.closed = closed
        self.untransformed = untransformed if untransformed is not None else self
    def store(self):
        res = DrawingItemTreeItem.store(self)
        res['points'] = [ i for i in self.points ]
        res['closed'] = self.closed
        return res
    def distanceTo(self, pt):
        if not self.points:
            return None
        mindist = None
        for i in range(len(self.points)):
            dist = None
            if self.closed or i > 0:
                if len(self.points[i - 1]) == 2 and len(self.points[i]) == 2:
                    dist = dist_line_to_point(self.points[i - 1], self.points[i], pt)
                # XXXKF arcs
            if dist is not None:
                if mindist is None:
                    mindist = dist
                else:
                    mindist = min(dist, mindist)
        return mindist
    def translated(self, dx, dy):
        pti = DrawingPolylineTreeItem(self.document, [translate_gen_point(p, dx, dy) for p in self.points], self.closed, self.untransformed)
        pti.shape_id = self.shape_id
        return pti
    def scaled(self, cx, cy, scale):
        return DrawingPolylineTreeItem(self.document, [scale_gen_point(p, cx, cy, scale) for p in self.points], self.closed, self.untransformed)
    def renderTo(self, path, modeData):
        path.addLines(self.penForPath(path, modeData), CircleFitter.interpolate_arcs(self.points, False, path.scalingFactor()), self.closed)
    def label(self):
        if len(self.points) == 2:
            if len(self.points[1]) == 2:
                return "Line%d" % self.shape_id
            else:
                return "Arc%d" % self.shape_id
        return "Polyline%d" % self.shape_id
    def textDescription(self):
        if len(self.points) == 2:
            if len(self.points[1]) == 2:
                return self.label() + ("(%0.2f, %0.2f)-(%0.2f, %0.2f)" % (*self.points[0], *self.points[1]))
            elif len(self.points[1]) == 7:
                arc = self.points[1]
                c = arc[3]
                return self.label() + "(X=%0.2f, Y=%0.2f, R=%0.2f, start=%0.2f, span=%0.2f" % (c.cx, c.cy, c.r, arc[5] * 180 / pi, arc[6] * 180 / pi)
        return self.label() + "(%0.2f, %0.2f)-(%0.2f, %0.2f)" % self.bounds
    def toShape(self):
        return process.Shape(CircleFitter.interpolate_arcs(self.points, False, 1.0), self.closed)
        
class DrawingTreeItem(CAMTreeItem):
    prop_x_offset = FloatEditableProperty("X offset", "x_offset", "%0.2f mm")
    prop_y_offset = FloatEditableProperty("Y offset", "y_offset", "%0.2f mm")
    def __init__(self, document):
        CAMTreeItem.__init__(self, document, "Drawing")
        self.reset()
    def reset(self):
        self.removeRows(0, self.rowCount())
        self.resetProperties()
    def resetProperties(self):
        self.x_offset = 0
        self.y_offset = 0
        self.emitDataChanged()
    def items(self):
        i = 0
        while i < self.rowCount():
            yield self.child(i)
            i += 1
    def bounds(self):
        b = None
        for item in self.items():
            if b is None:
                b = item.bounds
            else:
                b = max_bounds(b, item.bounds)
        if b is None:
            return (-1, -1, 1, 1)
        margin = 5
        return (b[0] - self.x_offset - margin, b[1] - self.y_offset - margin, b[2] - self.x_offset + margin, b[3] - self.y_offset + margin)
    def importDrawing(self, name):
        doc = ezdxf.readfile(name)
        self.reset()
        msp = doc.modelspace()
        for entity in msp:
            dxftype = entity.dxftype()
            if dxftype == 'LWPOLYLINE':
                points, closed = dxf_polyline_to_points(entity)
                self.addItem(DrawingPolylineTreeItem(self.document, points, closed))
            elif dxftype == 'LINE':
                start = tuple(entity.dxf.start)[0:2]
                end = tuple(entity.dxf.end)[0:2]
                self.addItem(DrawingPolylineTreeItem(self.document, [start, end], False))
            elif dxftype == 'CIRCLE':
                self.addItem(DrawingCircleTreeItem(self.document, entity.dxf.center, entity.dxf.radius))
            elif dxftype == 'ARC':
                start = tuple(entity.start_point)[0:2]
                end = tuple(entity.end_point)[0:2]
                centre = tuple(entity.dxf.center)[0:2]
                c = CandidateCircle(*centre, entity.dxf.radius)
                sangle = entity.dxf.start_angle * pi / 180
                eangle = entity.dxf.end_angle * pi / 180
                if eangle < sangle:
                    sspan = eangle - sangle + 2 * pi
                else:
                    sspan = eangle - sangle
                tag = "ARC_CCW"
                # tag, p1, p2, c, points, sstart, sspan
                points = [start, ( tag, start, end, c, 50, sangle, sspan)]
                self.addItem(DrawingPolylineTreeItem(self.document, points, False))
            else:
                print ("Ignoring DXF entity: %s" % dxftype)
    def renderTo(self, path, modeData):
        # XXXKF convert
        for i in self.items():
            i.translated(-self.x_offset, -self.y_offset).renderTo(path, modeData)
    def addItem(self, item):
        self.appendRow(item)
        # self.items.append(item)
        # self.items_by_id[item.shape_id] = item
    def itemById(self, shape_id):
        # XXXKF slower than before
        for i in self.items():
            if i.shape_id == shape_id:
                return i
    def objectsNear(self, pos, margin):
        xy = (pos.x() + self.x_offset, pos.y() + self.y_offset)
        found = []
        for item in self.items():
            if point_inside_bounds(expand_bounds(item.bounds, margin), xy):
                distance = item.distanceTo(xy)
                if distance is not None and distance < margin:
                    found.append(item)
        return found
    def objectsWithin(self, xs, ys, xe, ye):
        xs += self.x_offset
        ys += self.y_offset
        xe += self.x_offset
        ye += self.y_offset
        bounds = (xs, ys, xe, ye)
        found = []
        for item in self.items():
            if inside_bounds(item.bounds, bounds):
                found.append(item)
        return found        
    def properties(self):
        return [self.prop_x_offset, self.prop_y_offset]
    def translation(self):
        return (-self.x_offset, -self.y_offset)
    def onPropertyValueSet(self, name):
        self.document.drawing.origin = (self.x_offset, self.y_offset)
        self.emitDataChanged()
        
class ToolTreeItem(CAMTreeItem):
    prop_diameter = FloatEditableProperty("Diameter", "diameter", "%0.2f mm", min=0, max=100, allow_none=False)
    prop_flutes = IntEditableProperty("# flutes", "flutes", "%d", min=1, max=100, allow_none=False)
    prop_cel = FloatEditableProperty("Flute length", "cel", "%0.1f mm", min=0.1, max=100, allow_none=True)
    prop_doc = FloatEditableProperty("Cut depth per pass", "depth", "%0.2f mm", min=0.01, max=100, allow_none=True)
    prop_rpm = FloatEditableProperty("RPM", "rpm", "%0.0f/min", min=0.1, max=60000, allow_none=True)
    prop_hfeed = FloatEditableProperty("Feed rate", "hfeed", "%0.1f mm/min", min=0.1, max=10000, allow_none=True)
    prop_vfeed = FloatEditableProperty("Plunge rate", "vfeed", "%0.1f mm/min", min=0.1, max=10000, allow_none=True)
    def __init__(self, document):
        CAMTreeItem.__init__(self, document, "Tool")
        self.setEditable(False)
        self.resetProperties()
    def resetProperties(self):
        self.diameter = 3.2
        self.flutes = 2
        self.cel = 22
        self.depth = None
        self.hfeed = None
        self.vfeed = None
        self.rpm = None
        self.emitDataChanged()
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant("Tool: " + self.document.gcode_tool.short_info)
        return CAMTreeItem.data(self, role)
    def properties(self):
        return [self.prop_diameter, self.prop_flutes, self.prop_cel, self.prop_doc, self.prop_hfeed, self.prop_vfeed, self.prop_rpm]
    def getDefaultPropertyValue(self, name):
        if name == 'depth':
            return self.document.gcode_tool_orig.maxdoc
        if name == 'hfeed':
            return self.document.gcode_tool.hfeed
        if name == 'vfeed':
            return self.document.gcode_tool.vfeed
        if name == 'rpm':
            return self.document.gcode_tool.rpm
        return None
    def getPropertyValue(self, name):
        if name == 'diameter':
            return self.diameter
        if name == 'flutes':
            return self.flutes
        if name == 'cel':
            return self.cel
        if name == 'depth':
            return self.depth
        if name == 'hfeed':
            return self.hfeed
        if name == 'vfeed':
            return self.vfeed
        if name == 'rpm':
            return self.rpm
        assert False, "Unknown attribute: " + repr(name)
    def setPropertyValue(self, name, value):
        if name == 'diameter':
            self.diameter = value
        elif name == 'flutes':
            self.flutes = value
        elif name == 'cel':
            self.cel = value
        elif name == 'depth':
            self.depth = value
        elif name == 'hfeed':
            self.hfeed = value
        elif name == 'vfeed':
            self.vfeed = value
        elif name == 'rpm':
            self.rpm = value
        else:
            assert False, "Unknown attribute: " + repr(name)
        self.document.make_tool()
        self.emitDataChanged()
        
class MaterialType(EnumClass):
    WOOD = 0
    PLASTICS = 1
    ALU = 2
    STEEL = 3
    descriptions = [
        (WOOD, "Wood/MDF", material_wood),
        (PLASTICS, "Plastics", material_plastics),
        (ALU, "Aluminium", material_aluminium),
        (STEEL, "Mild steel", material_mildsteel),
    ]

class WorkpieceTreeItem(CAMTreeItem):
    prop_material = EnumEditableProperty("Material", "material", MaterialType, allow_none=True, none_value="Unknown")
    prop_thickness = FloatEditableProperty("Thickness", "thickness", "%0.2f mm", min=0, max=100, allow_none=True)
    prop_clearance = FloatEditableProperty("Clearance", "clearance", "%0.2f mm", min=0, max=100, allow_none=True)
    prop_safe_entry_z = FloatEditableProperty("Safe entry Z", "safe_entry_z", "%0.2f mm", min=0, max=100, allow_none=True)
    def __init__(self, document):
        CAMTreeItem.__init__(self, document, "Workpiece")
        self.resetProperties()
    def resetProperties(self):
        self.material = MaterialType.WOOD
        self.thickness = 3
        self.clearance = 5
        self.safe_entry_z = 1
        self.emitDataChanged()
    def properties(self):
        return [self.prop_material, self.prop_thickness, self.prop_clearance, self.prop_safe_entry_z]
    def data(self, role):
        if role == Qt.DisplayRole:
            if self.thickness is not None:
                return QVariant("Workpiece: %0.2f mm %s" % (self.thickness, MaterialType.toString(self.material)))
            else:
                return QVariant("Workpiece: ? %s" % (MaterialType.toString(self.material)))
        return CAMTreeItem.data(self, role)
    def onPropertyValueSet(self, name):
        if name == 'material':
            self.document.make_tool()
        if name in ('clearance', 'safe_entry_z'):
            self.document.make_machine_params()
        self.emitDataChanged()


class OperationType(EnumClass):
    OUTSIDE_CONTOUR = 1
    INSIDE_CONTOUR = 2
    POCKET = 3
    ENGRAVE = 4
    INTERPOLATED_HOLE = 5
    descriptions = [
        (OUTSIDE_CONTOUR, "Outside contour"),
        (INSIDE_CONTOUR, "Inside contour"),
        (POCKET, "Pocket"),
        (ENGRAVE, "Engrave"),
        (INTERPOLATED_HOLE, "H-Hole"),
    ]

class OperationTreeItem(CAMTreeItem):
    prop_operation = EnumEditableProperty("Operation", "operation", OperationType)
    prop_depth = FloatEditableProperty("Depth", "depth", "%0.2f mm", min=0, max=100, allow_none=True, none_value="full depth")
    prop_start_depth = FloatEditableProperty("Start Depth", "start_depth", "%0.2f mm", min=0, max=100)
    prop_tab_height = FloatEditableProperty("Tab Height", "tab_height", "%0.2f mm", min=0, max=100, allow_none=True, none_value="full height")
    prop_tab_count = IntEditableProperty("Tab Count", "tab_count", "%d", min=0, max=100, allow_none=True, none_value="default")
    prop_offset = FloatEditableProperty("Offset", "offset", "%0.2f mm", min=-20, max=20)
    prop_extra_width = FloatEditableProperty("Extra width", "extra_width", "%0.2f %%", min=0, max=100)
    prop_user_tabs = SetEditableProperty("Tab Locations", "user_tabs", format_func=lambda value: ", ".join(["(%0.2f, %0.2f)" % (i[0], i[1]) for i in value]))
    prop_islands = SetEditableProperty("Islands", "islands")
    def __init__(self, document):
        CAMTreeItem.__init__(self, document)
        self.shape_id = None
        self.orig_shape = None
        self.shape = None
        self.depth = None
        self.start_depth = 0
        self.tab_height = None
        self.tab_count = None
        self.offset = 0
        self.extra_width = 0
        self.islands = set()
        self.user_tabs = set()
        self.operation = OperationType.OUTSIDE_CONTOUR
        self.isSelected = False
        self.updateCAM()
    def isDropEnabled(self):
        return False
    def isPropertyValid(self, name):
        if self.operation == OperationType.POCKET and name in ['tab_height', 'tab_count', 'extra_width']:
            return False
        if self.operation != OperationType.POCKET and name == 'islands':
            return False
        if self.operation != OperationType.OUTSIDE_CONTOUR and self.operation != OperationType.INSIDE_CONTOUR and name == 'user_tabs':
            return False
        if self.operation == OperationType.ENGRAVE and name in ['tab_height', 'tab_count', 'offset', 'extra_width']:
            return False
        if self.operation == OperationType.INTERPOLATED_HOLE and name in ['tab_height', 'tab_count', 'extra_width']:
            return False
        return True
    def getValidEnumValues(self, name):
        if name == 'operation':
            if isinstance(self.orig_shape, DrawingCircleTreeItem):
                return [OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR, OperationType.POCKET, OperationType.ENGRAVE, OperationType.INTERPOLATED_HOLE]
            if isinstance(self.orig_shape, DrawingPolylineTreeItem):
                if self.shape.closed:
                    return [OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR, OperationType.POCKET, OperationType.ENGRAVE]
                else:
                    return [OperationType.ENGRAVE]
    def store(self):
        dump = CAMTreeItem.store(self)
        dump['shape_id'] = self.shape_id
        dump['islands'] = list(sorted(self.islands))
        dump['user_tabs'] = list(sorted(self.user_tabs))
        return dump
    def class_specific_load(self, dump):
        self.shape_id = dump.get('shape_id', None)
        self.islands = set(dump.get('islands', []))
        self.user_tabs = set((i[0], i[1]) for i in dump.get('user_tabs', []))
        self.updateCAM()
    def properties(self):
        return [self.prop_operation, self.prop_depth, self.prop_start_depth, self.prop_tab_height, self.prop_tab_count, self.prop_offset, self.prop_extra_width, self.prop_islands, self.prop_user_tabs]
    def onPropertyValueSet(self, name):
        self.updateCAM()
        self.emitDataChanged()
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(OperationType.toString(self.operation) +": " + self.orig_shape.label() + ", " + (("%0.2f mm" % self.depth) if self.depth is not None else "full") + " depth")
        return CAMTreeItem.data(self, role)
    def updateCAM(self):
        self.orig_shape = self.document.drawing.itemById(self.shape_id) if self.shape_id is not None else None
        if self.orig_shape:
            translation = (-self.document.drawing.x_offset, -self.document.drawing.y_offset)
            self.shape = self.orig_shape.translated(*translation).toShape()
        else:
            self.shape = None
        thickness = self.document.material.thickness
        if thickness is None:
            thickness = 0
        depth = self.depth if self.depth is not None else thickness
        start_depth = self.start_depth if self.start_depth is not None else 0
        tab_depth = max(start_depth, depth - self.tab_height) if self.tab_height is not None else start_depth
        self.gcode_props = gcodegen.OperationProps(-depth, -start_depth, -tab_depth, self.offset)
        self.cam = gcodegen.Operations(self.document.gcode_machine_params, self.document.gcode_tool, self.gcode_props)
        self.renderer = OperationsRendererWithSelection(self)
        if self.shape:
            if len(self.user_tabs):
                tabs = self.user_tabs
            else:
                tabs = self.tab_count if self.tab_count is not None else self.shape.default_tab_count(2, 8, 200)
            if self.operation == OperationType.OUTSIDE_CONTOUR:
                self.cam.outside_contour(self.shape, tabs=tabs, widen=self.extra_width / 50.0)
            elif self.operation == OperationType.INSIDE_CONTOUR:
                self.cam.inside_contour(self.shape, tabs=tabs, widen=self.extra_width / 50.0)
            elif self.operation == OperationType.POCKET:
                for island in self.islands:
                    item = self.document.drawing.itemById(island).translated(*translation).toShape()
                    if item.closed:
                        self.shape.add_island(item.boundary)
                self.cam.pocket(self.shape)
            elif self.operation == OperationType.ENGRAVE:
                self.cam.engrave(self.shape)
            elif self.operation == OperationType.INTERPOLATED_HOLE:
                self.cam.helical_drill(self.orig_shape.centre[0] + translation[0], self.orig_shape.centre[1] + translation[1], 2 * self.orig_shape.r)

MIMETYPE = 'application/x-derpcam-operations'

class OperationsModel(QStandardItemModel):
    def __init__(self, document):
        QStandardItemModel.__init__(self)
        self.document = document
    def supportedDropActions(self):
        return Qt.MoveAction
    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(MIMETYPE)
    def dropMimeData(self, data, action, row, column, parent):
        if data.hasFormat(MIMETYPE):
            data = json.loads(data.data(MIMETYPE).data())
            if row == -1:
                row = self.rowCount(parent)
            for i in data:
                item = CAMTreeItem.load(self.document, i)
                self.insertRow(row, item)
                row += 1
            return True
        return False
    def findItem(self, item):
        index = self.indexFromItem(item)
        return index.row()
    def removeItemAt(self, row):
        self.takeRow(row)
        # XXXKF Not sure why this was previously necessary
        # self.rowsRemoved.emit(index.parent(), row, row)
        return row
    def mimeData(self, indexes):
        data = []
        for i in indexes:
            data.append(self.itemFromIndex(i).store())
        mime = QMimeData()
        mime.setData(MIMETYPE, json.dumps(data).encode("utf-8"))
        return mime
    def flags(self, index):
        defaultFlags = QStandardItemModel.flags(self, index) &~ Qt.ItemIsDropEnabled
        if index.isValid():
            return Qt.ItemIsDragEnabled | defaultFlags
        else:
            return Qt.ItemIsDropEnabled | defaultFlags

class AddOperationUndoCommand(QUndoCommand):
    def __init__(self, document, item, row):
        QUndoCommand.__init__(self, "Create " + OperationType.toString(item.operation))
        self.document = document
        self.item = item
        self.row = row
    def undo(self):
        self.document.operModel.removeItemAt(self.row)
    def redo(self):
        self.document.operModel.insertRow(self.row, self.item)

class DeleteOperationUndoCommand(QUndoCommand):
    def __init__(self, document, item, row):
        QUndoCommand.__init__(self, "Delete " + OperationType.toString(item.operation))
        self.document = document
        self.item = item
        self.row = row
    def undo(self):
        self.document.operModel.insertRow(self.row, self.item)
    def redo(self):
        self.document.operModel.removeItemAt(self.row)

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

class DocumentModel(QObject):
    def __init__(self):
        QObject.__init__(self)
        self.undoStack = QUndoStack(self)
        self.material = WorkpieceTreeItem(self)
        self.tool = ToolTreeItem(self)
        self.drawing = DrawingTreeItem(self)
        self.filename = None
        self.drawingFilename = None
        self.make_machine_params()
        self.make_tool()

        self.shapeModel = QStandardItemModel()
        self.shapeModel.setHorizontalHeaderLabels(["Input object"])
        self.shapeModel.appendRow(self.material)
        self.shapeModel.appendRow(self.tool)
        self.shapeModel.appendRow(self.drawing)

        self.operModel = OperationsModel(self)
        self.operModel.setHorizontalHeaderLabels(["Operation"])
    def store(self):
        data = {}
        data['material'] = self.material.store()
        data['tool'] = self.tool.store()
        data['drawing'] = { 'header' : self.drawing.store(), 'items' : [item.store() for item in self.drawing.items()] }
        data['operations'] = self.forEachOperation(lambda op: op.store())
        return data
    def load(self, data):
        self.undoStack.clear()
        self.material.reload(data['material'])
        self.tool.reload(data['tool'])
        self.drawing.reload(data['drawing']['header'])
        self.drawing.reset()
        for i in data['drawing']['items']:
            self.drawing.appendRow(DrawingItemTreeItem.load(self, i))
        for i in data['operations']:
            operation = CAMTreeItem.load(self, i)
            if operation.orig_shape is None:
                print ("Warning: dangling reference to shape %d, ignoring the referencing operation" % (operation.shape_id, ))
            else:
                self.operModel.appendRow(operation)
        self.updateCAM()
    def make_machine_params(self):
        self.gcode_machine_params = gcodegen.MachineParams(safe_z = self.material.clearance, semi_safe_z = self.material.safe_entry_z)
    def make_tool(self):
        self.gcode_material = MaterialType.descriptions[self.material.material][2] if self.material.material is not None else material_plastics
        self.gcode_coating = carbide_uncoated
        self.gcode_tool_orig = standard_tool(self.tool.diameter, self.tool.flutes, self.gcode_material, self.gcode_coating)
        self.gcode_tool = self.gcode_tool_orig.clone_with_overrides(self.tool.hfeed, self.tool.vfeed, self.tool.depth, self.tool.rpm)
    def reinitDocument(self):
        self.undoStack.clear()
        self.material.resetProperties()
        self.tool.resetProperties()
        self.drawing.reset()
        self.operModel.removeRows(0, self.operModel.rowCount())
    def importDrawing(self, fn):
        self.reinitDocument()
        self.filename = None
        self.drawingFilename = fn
        self.drawing.importDrawing(fn)
        self.make_tool()
    def forEachOperation(self, func):
        res = []
        for i in range(self.operModel.rowCount()):
            res.append(func(self.operModel.item(i)))
        return res
    def updateCAM(self):
        self.make_machine_params()
        self.make_tool()
        self.forEachOperation(lambda item: item.updateCAM())
    def validateForOutput(self):
        def validateOperation(item):
            if item.depth is None:
                if self.material.thickness is None or self.material.thickness == 0:
                    raise ValueError("Default material thickness not set")
        self.forEachOperation(validateOperation)
        if self.material.material is None:
            raise ValueError("Material type not set")
    def setOperSelection(self, selection):
        changes = []
        def setSelected(operation):
            isIn = (operation in selection)
            if operation.isSelected != isIn:
                operation.isSelected = isIn
                return True
        return any(self.forEachOperation(setSelected))
    def opCreateOperation(self, shapeIds, operationType):
        if len(shapeIds) > 1:
            self.undoStack.beginMacro("Create multiple " + OperationType.toString(operationType))
        try:
            indexes = []
            rowCount = self.operModel.rowCount()
            for i in shapeIds:
                item = CAMTreeItem.load(self, { '_type' : 'OperationTreeItem', 'shape_id' : i, 'operation' : operationType })
                self.undoStack.push(AddOperationUndoCommand(self, item, rowCount))
                indexes.append(self.operModel.index(rowCount, 0))
                rowCount += 1
        finally:
            if len(shapeIds) > 1:
                self.undoStack.endMacro()
        return rowCount, indexes
    def opChangeProperty(self, property, changes):
        if len(changes) > 1:
            self.undoStack.beginMacro("Set " + property.name)
        try:
            for subject, value in changes:
                self.undoStack.push(PropertySetUndoCommand(property, subject, property.getData(subject), value))
        finally:
            if len(changes) > 1:
                self.undoStack.endMacro()
    def opDeleteOperations(self, items):
        if len(items) > 1:
            self.undoStack.beginMacro("Delete %d operations" % (len(items), ))
        try:
            for item in items:
                row = self.operModel.findItem(item)
                self.undoStack.push(DeleteOperationUndoCommand(self, item, row))
        finally:
            if len(items) > 1:
                self.undoStack.endMacro()
