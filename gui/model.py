import os.path
import sys
import threading
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

import process
import gcodegen
import view
from milling_tool import *

from . import canvas, inventory
from .propsheet import EnumClass, IntEditableProperty, FloatEditableProperty, \
    EnumEditableProperty, SetEditableProperty, RefEditableProperty, StringEditableProperty

import ezdxf
import json

def overrides(*data):
    for i in data:
        if i is not None:
            return i

class CAMTreeItem(QStandardItem):
    def __init__(self, document, name=None):
        QStandardItem.__init__(self, name)
        self.document = document
        self.setEditable(False)
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
        if modeData[0] == canvas.DrawingUIMode.MODE_ISLANDS:
            if modeData[1].shape_id == self.shape_id:
                return self.defaultDrawingPen
            if self.shape_id in modeData[1].islands:
                return self.selectedItemDrawingPen2
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
            points = [PathPoint.from_tuple(i) for i in dump['points']]
            item = DrawingPolylineTreeItem(document, points, dump.get('closed', True))
        elif rtype == 'DrawingCircle' or rtype == 'DrawingCircleTreeItem':
            item = DrawingCircleTreeItem(document, PathPoint(dump['cx'], dump['cy']), dump['r'])
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
    prop_x = FloatEditableProperty("Centre X", "x", "%0.2f", unit="mm", min=0, max=100, allow_none=False)
    prop_y = FloatEditableProperty("Centre Y", "y", "%0.2f", unit="mm", min=0, max=100, allow_none=False)
    prop_dia = FloatEditableProperty("Diameter", "diameter", "%0.2f", unit="mm", min=0, max=100, allow_none=False)
    prop_radius = FloatEditableProperty("Radius", "radius", "%0.2f", unit="mm", min=0, max=100, allow_none=False)
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
            self.centre = PathPoint(value, self.centre.y)
        elif name == 'y':
            self.centre = PathPoint(self.x, value)
        elif name == 'radius':
            self.r = value
        elif name == 'diameter':
            self.r = value / 2.0
        else:
            assert False, "Unknown property: " + name
        self.emitDataChanged()
    def calcBounds(self):
        self.bounds = (self.centre.x - self.r, self.centre.y - self.r,
            self.centre.x + self.r, self.centre.y + self.r)
    def distanceTo(self, pt):
        return abs(dist(self.centre, pt) - self.r)
    def renderTo(self, path, modeData):
        path.addLines(self.penForPath(path, modeData), circle(self.centre.x, self.centre.y, self.r), True)
    def label(self):
        return "Circle%d" % self.shape_id
    def textDescription(self):
        return self.label() + (" (%0.2f, %0.2f) \u2300%0.2f" % (self.centre.x, self.centre.y, 2 * self.r))
    def toShape(self):
        return process.Shape.circle(self.centre.x, self.centre.y, self.r)
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

class DrawingPolylineTreeItem(DrawingItemTreeItem):
    def __init__(self, document, points, closed, untransformed = None):
        DrawingItemTreeItem.__init__(self, document)
        self.points = points
        if points:
            xcoords = [p.x for p in self.points if p.is_point()]
            ycoords = [p.y for p in self.points if p.is_point()]
            self.bounds = (min(xcoords), min(ycoords), max(xcoords), max(ycoords))
        else:
            self.bounds = None
        self.closed = closed
        self.untransformed = untransformed if untransformed is not None else self
    def store(self):
        res = DrawingItemTreeItem.store(self)
        res['points'] = [ i.as_tuple() for i in self.points ]
        res['closed'] = self.closed
        return res
    def distanceTo(self, pt):
        if not self.points:
            return None
        mindist = None
        for i in range(len(self.points)):
            dist = None
            if self.closed or i > 0:
                if self.points[i - 1].is_point() and self.points[i].is_point():
                    dist = dist_line_to_point(self.points[i - 1], self.points[i], pt)
                # XXXKF arcs - use closest_point?
            if dist is not None:
                if mindist is None:
                    mindist = dist
                else:
                    mindist = min(dist, mindist)
        return mindist
    def translated(self, dx, dy):
        pti = DrawingPolylineTreeItem(self.document, [p.translated(dx, dy) for p in self.points], self.closed, self.untransformed)
        pti.shape_id = self.shape_id
        return pti
    def scaled(self, cx, cy, scale):
        return DrawingPolylineTreeItem(self.document, [p.scaled(cx, cy, scale) for p in self.points], self.closed, self.untransformed)
    def renderTo(self, path, modeData):
        path.addLines(self.penForPath(path, modeData), CircleFitter.interpolate_arcs(self.points, False, path.scalingFactor()), self.closed)
    def label(self):
        if len(self.points) == 2:
            if self.points[1].is_point():
                return "Line%d" % self.shape_id
            else:
                return "Arc%d" % self.shape_id
        return "Polyline%d" % self.shape_id
    def textDescription(self):
        if len(self.points) == 2:
            if self.points[1].is_point():
                return self.label() + ("(%0.2f, %0.2f)-(%0.2f, %0.2f)" % (self.points[0].x, self.points[0].y, self.points[1].x, self.points[1].y))
            else:
                assert self.points[1].is_arc()
                arc = self.points[1]
                c = arc.c
                return self.label() + "(X=%0.2f, Y=%0.2f, R=%0.2f, start=%0.2f, span=%0.2f" % (c.cx, c.cy, c.r, arc.sstart * 180 / pi, arc.sspan * 180 / pi)
        return self.label() + "(%0.2f, %0.2f)-(%0.2f, %0.2f)" % self.bounds
    def toShape(self):
        return process.Shape(CircleFitter.interpolate_arcs(self.points, False, 1.0), self.closed)
        
class CAMListTreeItem(CAMTreeItem):
    def __init__(self, document, name):
        CAMTreeItem.__init__(self, document, name)
        self.reset()
    def reset(self):
        self.resetProperties()
    def resetProperties(self):
        pass
    
class DrawingTreeItem(CAMListTreeItem):
    prop_x_offset = FloatEditableProperty("X offset", "x_offset", "%0.2f mm")
    prop_y_offset = FloatEditableProperty("Y offset", "y_offset", "%0.2f mm")
    def __init__(self, document):
        CAMListTreeItem.__init__(self, document, "Drawing")
    def resetProperties(self):
        self.x_offset = 0
        self.y_offset = 0
        self.emitDataChanged()
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
                self.addItem(DrawingPolylineTreeItem(self.document, [PathPoint(start[0], start[1]), PathPoint(end[0], end[1])], False))
            elif dxftype == 'CIRCLE':
                centre = PathPoint(entity.dxf.center[0], entity.dxf.center[1])
                self.addItem(DrawingCircleTreeItem(self.document, centre, entity.dxf.radius))
            elif dxftype == 'ARC':
                start = PathPoint(entity.start_point[0], entity.start_point[1])
                end = PathPoint(entity.end_point[0], entity.end_point[1])
                centre = tuple(entity.dxf.center)[0:2]
                c = CandidateCircle(*centre, entity.dxf.radius)
                sangle = entity.dxf.start_angle * pi / 180
                eangle = entity.dxf.end_angle * pi / 180
                if eangle < sangle:
                    sspan = eangle - sangle + 2 * pi
                else:
                    sspan = eangle - sangle
                points = [start, PathArc( start, end, c, 50, sangle, sspan)]
                self.addItem(DrawingPolylineTreeItem(self.document, points, False))
            else:
                print ("Ignoring DXF entity: %s" % dxftype)
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
    def objectsNear(self, pos, margin):
        xy = PathPoint(pos.x() + self.x_offset, pos.y() + self.y_offset)
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
        self.emitDataChanged()
        
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

class ToolTreeItem(CAMListTreeItemWithChildren):
    prop_name = StringEditableProperty("Name", "name", False)
    prop_flutes = IntEditableProperty("# flutes", "flutes", "%d", min=1, max=100, allow_none=False)
    prop_diameter = FloatEditableProperty("Diameter", "diameter", "%0.2f", unit="mm", min=0, max=100, allow_none=False)
    prop_length = FloatEditableProperty("Flute length", "length", "%0.1f mm", min=0.1, max=100, allow_none=True)
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
            return [self.prop_name, self.prop_diameter, self.prop_flutes, self.prop_length]
        elif isinstance(self.inventory_tool, inventory.DrillBitCutter):
            return [self.prop_name, self.prop_diameter, self.prop_length]
        return []
    def resetProperties(self):
        self.emitDataChanged()
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
        self.emitDataChanged()

class ToolPresetTreeItem(CAMTreeItem):
    prop_name = StringEditableProperty("Name", "name", False)
    prop_doc = FloatEditableProperty("Cut depth/pass", "depth", "%0.2f", unit="mm", min=0.01, max=100, allow_none=True)
    prop_rpm = FloatEditableProperty("RPM", "rpm", "%0.0f", unit="/min", min=0.1, max=60000, allow_none=True)
    prop_hfeed = FloatEditableProperty("Feed rate", "hfeed", "%0.1f", unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_vfeed = FloatEditableProperty("Plunge rate", "vfeed", "%0.1f", unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_stepover = FloatEditableProperty("Stepover", "stepover", "%0.1f", unit="%", min=1, max=100, allow_none=True)
    prop_direction = EnumEditableProperty("Direction", "direction", inventory.MillDirection, allow_none=False)
    prop_extra_width = FloatEditableProperty("Extra width", "extra_width", "%0.1f", unit="%", min=0, max=100, allow_none=True)
    prop_trc_rate = FloatEditableProperty("Trochoid: step", "trc_rate", "%0.1f", unit="%", min=0, max=100, allow_none=True)

    def __init__(self, document, preset):
        self.inventory_preset = preset
        CAMTreeItem.__init__(self, document, "Tool preset")
        self.setEditable(False)
        self.resetProperties()
    def resetProperties(self):
        self.emitDataChanged()
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
        if isinstance(self.inventory_preset, inventory.EndMillPreset):
            return self.properties_endmill()
        elif isinstance(self.inventory_preset, inventory.DrillBitPreset):
            return self.properties_drillbit()
        return []
    @classmethod
    def properties_endmill(klass):
        return [klass.prop_name, klass.prop_doc, klass.prop_hfeed, klass.prop_vfeed, klass.prop_stepover, klass.prop_direction, klass.prop_rpm, klass.prop_extra_width, klass.prop_trc_rate]
    @classmethod
    def properties_drillbit(klass):
        return [klass.prop_name, klass.prop_doc, klass.prop_vfeed, klass.prop_rpm]
    def getPropertyValue(self, name):
        if name == 'depth':
            return self.inventory_preset.maxdoc
        elif name == 'stepover':
            return 100 * self.inventory_preset.stepover if self.inventory_preset.stepover else None
        elif name == 'extra_width':
            return 100 * self.inventory_preset.extra_width if self.inventory_preset.extra_width is not None else None
        elif name == 'trc_rate':
            return 100 * self.inventory_preset.trc_rate if self.inventory_preset.trc_rate is not None else None
        else:
            return getattr(self.inventory_preset, name)
    def setPropertyValue(self, name, value):
        if name == 'depth':
            self.inventory_preset.maxdoc = value
        elif name == 'stepover':
            self.inventory_preset.stepover = value / 100.0
        elif name == 'extra_width':
            self.inventory_preset.extra_width = value / 100.0
        elif name == 'trc_rate':
            self.inventory_preset.trc_rate = value / 100.0
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
        else:
            assert False, "Unknown attribute: " + repr(name)
        if name == 'extra_width' or name == 'trc_rate' or name == 'stepover':
            self.document.startUpdateCAM(preset=self)
        self.emitDataChanged()
    def returnKeyPressed(self):
        self.document.selectPresetAsDefault(self.inventory_preset.toolbit, self.inventory_preset)

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
    prop_thickness = FloatEditableProperty("Thickness", "thickness", "%0.2f", unit="mm", min=0, max=100, allow_none=True)
    prop_clearance = FloatEditableProperty("Clearance", "clearance", "%0.2f", unit="mm", min=0, max=100, allow_none=True)
    prop_safe_entry_z = FloatEditableProperty("Safe entry Z", "safe_entry_z", "%0.2f", unit="mm", min=0, max=100, allow_none=True)
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
        #if name == 'material':
        #    self.document.make_tool()
        if name in ('clearance', 'safe_entry_z'):
            self.document.make_machine_params()
        self.emitDataChanged()


class OperationType(EnumClass):
    OUTSIDE_CONTOUR = 1
    INSIDE_CONTOUR = 2
    POCKET = 3
    ENGRAVE = 4
    INTERPOLATED_HOLE = 5
    DRILLED_HOLE = 6
    descriptions = [
        (OUTSIDE_CONTOUR, "Outside contour"),
        (INSIDE_CONTOUR, "Inside contour"),
        (POCKET, "Pocket"),
        (ENGRAVE, "Engrave"),
        (INTERPOLATED_HOLE, "H-Hole"),
        (DRILLED_HOLE, "Drill"),
    ]

class CutterAdapter(object):
    def getLookupData(self, items):
        assert items
        if items[0].operation == OperationType.DRILLED_HOLE:
            return items[0].document.getToolbitList(inventory.DrillBitCutter)
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
        self.cutter = cutter
    def toString(self):
        return "Tool cycle"
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

def not_none(*args):
    for i in args:
        if i is not None:
            return True
    return False

class PresetDerivedAttributes(object):
    def __init__(self, operation, preset=None):
        if preset is None:
            preset = operation.tool_preset
        self.operation = operation
        self.rpm = preset and preset.rpm
        self.vfeed = overrides(operation.vfeed, preset and preset.vfeed)
        self.doc = overrides(operation.doc, preset and preset.maxdoc)
        if isinstance(operation.cutter, inventory.EndMillCutter):
            self.hfeed = overrides(operation.hfeed, preset and preset.hfeed)
            self.stepover = overrides(operation.stepover, preset and preset.stepover and 100.0 * preset.stepover)
            self.extra_width = overrides(operation.extra_width, (100.0 * preset.extra_width if preset and preset.extra_width is not None else 0))
            self.trc_rate = overrides(operation.trc_rate, (100.0 * preset.trc_rate if preset and preset.trc_rate is not None else 0))
            self.direction = overrides(operation.direction, preset and preset.direction, inventory.MillDirection.CONVENTIONAL)
            self.dirty = not_none(operation.hfeed, operation.vfeed, operation.doc, operation.stepover, operation.extra_width, operation.trc_rate)
        elif isinstance(operation.cutter, inventory.DrillBitCutter):
            self.dirty = operation.vfeed or operation.doc
    def validate(self, errors):
        if self.vfeed is None:
            errors.append("Plunge rate is not set")
        if self.doc is None:
            errors.append("Maximum depth of cut per pass is not set")
        if isinstance(self.operation.cutter, inventory.EndMillCutter):
            if self.hfeed is None:
                errors.append("Feed rate is not set")
            elif self.hfeed < 0.1 or self.hfeed > 10000:
                errors.append("Feed rate is out of range (0.1-10000)")
            if self.stepover is None or self.stepover < 0.1 or self.stepover > 100:
                if self.operation.operation == OperationType.POCKET:
                    if self.stepover is None:
                        errors.append("Horizontal stepover is not set")
                    else:
                        errors.append("Horizontal stepover is out of range")
                else:
                    # Fake value that is never used
                    self.stepover = 0.5
    def toPreset(self, name):
        def percent(value):
            return value / 100.0 if value is not None else None
        if isinstance(self.operation.cutter, inventory.EndMillCutter):
            return inventory.EndMillPreset.new(None, name, self.operation.cutter, 
                self.rpm, self.hfeed, self.vfeed, self.doc,
                percent(self.stepover), self.direction, percent(self.extra_width), percent(self.trc_rate))
        if isinstance(self.operation.cutter, inventory.DrillBitCutter):
            return inventory.DrillBitPreset.new(None, name, self.operation.cutter, self.rpm, self.vfeed, self.doc)
    def resetPresetDerivedValues(self, target):
        target.hfeed = None
        target.vfeed = None
        target.stepover = None
        target.doc = None
        target.direction = None
        target.extra_width = None
        target.trc_rate = None
        target.emitDataChanged()

class OperationTreeItem(CAMTreeItem):
    prop_operation = EnumEditableProperty("Operation", "operation", OperationType)
    prop_cutter = RefEditableProperty("Cutter", "cutter", CutterAdapter())
    prop_preset = RefEditableProperty("Tool preset", "tool_preset", ToolPresetAdapter(), allow_none=True, none_value="<none>")
    prop_depth = FloatEditableProperty("Depth", "depth", "%0.2f", unit="mm", min=0, max=100, allow_none=True, none_value="full depth")
    prop_start_depth = FloatEditableProperty("Start Depth", "start_depth", "%0.2f", unit="mm", min=0, max=100)
    prop_tab_height = FloatEditableProperty("Tab Height", "tab_height", "%0.2f", unit="mm", min=0, max=100, allow_none=True, none_value="full height")
    prop_tab_count = IntEditableProperty("# Auto Tabs", "tab_count", "%d", min=0, max=100, allow_none=True, none_value="default")
    prop_user_tabs = SetEditableProperty("Tab Locations", "user_tabs", format_func=lambda value: ", ".join(["(%0.2f, %0.2f)" % (i.x, i.y) for i in value]), edit_func=lambda item: item.editTabLocations())
    prop_offset = FloatEditableProperty("Offset", "offset", "%0.2f", unit="mm", min=-20, max=20)
    prop_extra_width = FloatEditableProperty("Extra width", "extra_width", "%0.2f", unit="%", min=0, max=100, allow_none=True)
    prop_islands = SetEditableProperty("Islands", "islands", edit_func=lambda item: item.editIslands())

    prop_hfeed = FloatEditableProperty("Feed rate", "hfeed", "%0.1f", unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_vfeed = FloatEditableProperty("Plunge rate", "vfeed", "%0.1f", unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_stepover = FloatEditableProperty("Stepover", "stepover", "%0.1f", unit="%", min=1, max=100, allow_none=True)
    prop_doc = FloatEditableProperty("Cut depth/pass", "doc", "%0.2f", unit="mm", min=0.01, max=100, allow_none=True)
    prop_trc_rate = FloatEditableProperty("Trochoid: step", "trc_rate", "%0.2f", unit="%", min=0, max=200, allow_none=True)
    prop_direction = EnumEditableProperty("Direction", "direction", inventory.MillDirection, allow_none=True)

    def __init__(self, document):
        CAMTreeItem.__init__(self, document)
        self.setCheckable(True)
        self.shape_id = None
        self.orig_shape = None
        self.shape = None
        self.resetProperties()
        self.isSelected = False
        self.error = None
        self.warning = None
        self.worker = None
        self.startUpdateCAM()
    def resetProperties(self):
        self.setCheckState(True)
        self.cutter = None
        self.tool_preset = None
        self.operation = OperationType.OUTSIDE_CONTOUR
        self.depth = None
        self.start_depth = 0
        self.tab_height = None
        self.tab_count = None
        self.offset = 0
        self.islands = set()
        self.user_tabs = set()
        self.hfeed = None
        self.vfeed = None
        self.doc = None
        self.stepover = None
        self.trc_rate = None
        self.extra_width = None
        self.direction = None
    def editTabLocations(self):
        self.document.tabEditRequested.emit(self)
    def editIslands(self):
        self.document.islandsEditRequested.emit(self)
    def toString(self):
        return OperationType.toString(self.operation)
    def isPropertyValid(self, name):
        if self.operation == OperationType.POCKET and name in ['tab_height', 'tab_count', 'extra_width']:
            return False
        if self.operation != OperationType.POCKET and name == 'islands':
            return False
        if self.operation != OperationType.OUTSIDE_CONTOUR and self.operation != OperationType.INSIDE_CONTOUR and name == 'user_tabs':
            return False
        if self.operation != OperationType.OUTSIDE_CONTOUR and self.operation != OperationType.INSIDE_CONTOUR and name.startswith("trc_"):
            return False
        if (self.operation == OperationType.OUTSIDE_CONTOUR or self.operation == OperationType.INSIDE_CONTOUR) and name == 'stepover':
            return False
        if self.operation == OperationType.ENGRAVE and name in ['tab_height', 'tab_count', 'offset', 'extra_width', 'stepover']:
            return False
        if self.operation == OperationType.INTERPOLATED_HOLE and name in ['tab_height', 'tab_count', 'extra_width']:
            return False
        if self.operation == OperationType.DRILLED_HOLE and name in ['tab_height', 'tab_count', 'offset', 'extra_width', 'hfeed', 'stepover', 'trc_rate', 'direction']:
            return False
        return True
    def getValidEnumValues(self, name):
        if name == 'operation':
            if self.cutter is not None and isinstance(self.cutter, inventory.DrillBitCutter):
                return [OperationType.DRILLED_HOLE]
            if isinstance(self.orig_shape, DrawingCircleTreeItem):
                return [OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR, OperationType.POCKET, OperationType.ENGRAVE, OperationType.INTERPOLATED_HOLE]
            if isinstance(self.orig_shape, DrawingPolylineTreeItem):
                if self.orig_shape.closed:
                    return [OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR, OperationType.POCKET, OperationType.ENGRAVE]
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
        dump['active'] = self.checkState() != 0
        dump['shape_id'] = self.shape_id
        dump['islands'] = list(sorted(self.islands))
        dump['user_tabs'] = list(sorted([(pt.x, pt.y) for pt in self.user_tabs]))
        dump['cutter'] = self.cutter.id
        dump['tool_preset'] = self.tool_preset.id if self.tool_preset else None
        return dump
    def class_specific_load(self, dump):
        self.shape_id = dump.get('shape_id', None)
        self.islands = set(dump.get('islands', []))
        self.user_tabs = set(PathPoint(i[0], i[1]) for i in dump.get('user_tabs', []))
        self.setCheckState(2 if dump.get('active', True) else 0)
    def properties(self):
        return [self.prop_operation, self.prop_cutter, self.prop_preset, 
            self.prop_depth, self.prop_start_depth, 
            self.prop_offset,
            self.prop_tab_height, self.prop_tab_count, self.prop_user_tabs,
            self.prop_extra_width,
            self.prop_islands,
            self.prop_doc, self.prop_hfeed, self.prop_vfeed, self.prop_stepover,
            self.prop_trc_rate, self.prop_direction]
    def setPropertyValue(self, name, value):
        if name == 'tool_preset':
            if isinstance(value, SavePresetOption):
                from . import cutter_mgr
                dlg = cutter_mgr.AddPresetDialog()
                if dlg.exec_():
                    pda = PresetDerivedAttributes(self)
                    self.tool_preset = pda.toPreset(dlg.presetName)
                    self.cutter.presets.append(self.tool_preset)
                    pda.resetPresetDerivedValues(self)
                    self.document.refreshToolList()
                    self.document.selectPresetAsDefault(self.tool_preset.toolbit, self.tool_preset)
                return
            if isinstance(value, LoadPresetOption):
                from . import cutter_mgr
                cutter_type = inventory.DrillBitCutter if self.operation == OperationType.DRILLED_HOLE else inventory.EndMillCutter
                if cutter_mgr.selectCutter(None, cutter_mgr.SelectCutterDialog, self.document, cutter_type):
                    if self.cutter is not self.document.current_cutter_cycle.cutter:
                        self.document.opMoveItem(self.parent(), self, self.document.current_cutter_cycle, 0)
                        self.cutter = self.document.current_cutter_cycle.cutter
                    self.tool_preset = self.document.default_preset_by_tool.get(self.cutter, None)
                    self.startUpdateCAM()
                    self.document.refreshToolList()
                return
        setattr(self, name, value)
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
                return QVariant(self.operationTypeLabel() + ": " + self.orig_shape.label() + ", " + (("%0.2f mm" % self.depth) if self.depth is not None else "full") + f" depth, preset: {self.tool_preset.name if self.tool_preset else 'none'}")
        return CAMTreeItem.data(self, role)
    def addWarning(self, warning):
        if self.warning is None:
            self.warning = ""
        else:
            self.warning += "\n"
        self.warning += warning
    def updateOrigShape(self):
        self.orig_shape = self.document.drawing.itemById(self.shape_id) if self.shape_id is not None else None
    def startUpdateCAM(self):
        with view.Spinner():
            self.updateOrigShape()
            self.error = None
            self.warning = None
            self.cam = None
            self.renderer = None
            self.cancelWorker()
            if not self.cutter:
                self.error = "Cutter not set"
                return
            if self.checkState() == 0:
                # Operation not enabled
                return
            self.updateCAMWork()
    def pollForUpdateCAM(self):
        if self.worker and not self.worker.is_alive():
            self.worker.join()
            self.worker = None
            self.document.operationsUpdated.emit()
        if self.worker is not None:
            return self.worker.progress
    def waitForUpdateCAM(self):
        if self.worker:
            self.worker.join()
            self.worker = None
            self.document.operationsUpdated.emit()
    def cancelWorker(self):
        if self.worker:
            self.worker.cancelled = True
            self.worker.join()
            self.worker = None
    def updateCAMWork(self):
        try:
            errors = []
            if self.orig_shape:
                translation = (-self.document.drawing.x_offset, -self.document.drawing.y_offset)
                self.shape = self.orig_shape.translated(*translation).toShape()
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
            tab_depth = max(start_depth, depth - self.tab_height) if self.tab_height is not None else start_depth
            self.gcode_props = gcodegen.OperationProps(-depth, -start_depth, -tab_depth, self.offset)            

            pda = PresetDerivedAttributes(self)
            pda.validate(errors)
            if errors:
                raise ValueError("\n".join(errors))
            if isinstance(self.cutter, inventory.EndMillCutter):
                tool = Tool(self.cutter.diameter, pda.hfeed, pda.vfeed, pda.doc, climb=(pda.direction == inventory.MillDirection.CLIMB), stepover=pda.stepover / 100.0)
            else:
                tool = Tool(self.cutter.diameter, 0, pda.vfeed, pda.doc)
            self.cam = gcodegen.Operations(self.document.gcode_machine_params, tool, self.gcode_props)
            self.renderer = canvas.OperationsRendererWithSelection(self)
            if self.shape:
                if len(self.user_tabs):
                    tabs = self.user_tabs
                else:
                    tabs = self.tab_count if self.tab_count is not None else self.shape.default_tab_count(2, 8, 200)
                threadFunc = None
                if self.operation == OperationType.OUTSIDE_CONTOUR:
                    if pda.trc_rate:
                        threadFunc = lambda: self.cam.outside_contour_trochoidal(self.shape, pda.extra_width / 100.0, pda.trc_rate / 100.0, tabs=tabs)
                    else:
                        self.cam.outside_contour(self.shape, tabs=tabs, widen=pda.extra_width / 50.0)
                elif self.operation == OperationType.INSIDE_CONTOUR:
                    if pda.trc_rate:
                        threadFunc = lambda: self.cam.inside_contour_trochoidal(self.shape, pda.extra_width / 100.0, pda.trc_rate / 100.0, tabs=tabs)
                    else:
                        self.cam.inside_contour(self.shape, tabs=tabs, widen=pda.extra_width / 50.0)
                elif self.operation == OperationType.POCKET:
                    for island in self.islands:
                        item = self.document.drawing.itemById(island).translated(*translation).toShape()
                        if item.closed:
                            self.shape.add_island(item.boundary)
                    threadFunc = lambda: self.cam.pocket(self.shape)
                elif self.operation == OperationType.ENGRAVE:
                    self.cam.engrave(self.shape)
                elif self.operation == OperationType.INTERPOLATED_HOLE:
                    self.cam.helical_drill(self.orig_shape.centre.x + translation[0], self.orig_shape.centre.y + translation[1], 2 * self.orig_shape.r)
                elif self.operation == OperationType.DRILLED_HOLE:
                    self.cam.peck_drill(self.orig_shape.centre.x + translation[0], self.orig_shape.centre.y + translation[1])
                else:
                    raise ValueError("Unsupported operation")
                if threadFunc:
                    self.worker = threading.Thread(target=threadFunc)
                    self.worker.progress = (0, 1)
                    self.worker.cancelled = False
                    self.worker.start()
            self.error = None
        except Exception as e:
            self.cam = None
            self.renderer = None
            self.error = str(e)
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
        if isinstance(self.item, CycleTreeItem):
            del self.document.project_toolbits[self.item.cutter.name]
            self.item.document.refreshToolList()
    def redo(self):
        self.parent.insertRow(self.row, self.item)
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
        self.was_default = False
    def undo(self):
        self.document.operModel.invisibleRootItem().insertRow(self.row, self.cycle)
        self.document.project_toolbits[self.cycle.cutter.name] = self.cycle.cutter
        if self.was_default:
            self.document.selectCycle(self.cycle)
        self.document.refreshToolList()
    def redo(self):
        self.row = self.cycle.row()
        self.was_default = self.cycle is self.document.current_cutter_cycle
        self.document.operModel.invisibleRootItem().takeRow(self.row)
        del self.document.project_toolbits[self.cycle.cutter.name]
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
        if isinstance(self.item, CycleTreeItem) and self.deleted_cutter:
            self.document.project_toolbits[self.item.cutter.name] = self.deleted_cutter
            self.document.refreshToolList()
        elif isinstance(self.item, OperationTreeItem):
            self.item.startUpdateCAM()
    def redo(self):
        self.parent.takeRow(self.row)
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

class DocumentModel(QObject):
    cutterSelected = pyqtSignal([CycleTreeItem])
    tabEditRequested = pyqtSignal([OperationTreeItem])
    islandsEditRequested = pyqtSignal([OperationTreeItem])
    toolListRefreshed = pyqtSignal([])
    operationsUpdated = pyqtSignal([])
    def __init__(self):
        QObject.__init__(self)
        self.undoStack = QUndoStack(self)
        self.material = WorkpieceTreeItem(self)
        self.make_machine_params()
        self.drawing = DrawingTreeItem(self)
        self.filename = None
        self.drawingFilename = None
        self.current_cutter_cycle = None
        self.project_toolbits = {}
        self.default_preset_by_tool = {}
        self.tool_list = ToolListTreeItem(self)
        self.shapeModel = QStandardItemModel()
        self.shapeModel.setHorizontalHeaderLabels(["Input object"])
        self.shapeModel.appendRow(self.material)
        self.shapeModel.appendRow(self.tool_list)
        self.shapeModel.appendRow(self.drawing)

        self.operModel = OperationsModel(self)
        self.operModel.setHorizontalHeaderLabels(["Operation"])
        self.operModel.itemChanged.connect(self.operItemChanged)

    def reinitDocument(self):
        self.undoStack.clear()
        self.material.resetProperties()
        self.current_cutter_cycle = None
        self.project_toolbits = {}
        self.default_preset_by_tool = {}
        self.refreshToolList()
        self.drawing.reset()
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
            material = MaterialType.descriptions[self.material.material][2] if self.material.material is not None else material_plastics
            tool = data['tool']
            prj_cutter = inventory.EndMillCutter.new(None, "Project tool", inventory.CutterMaterial.carbide, tool['diameter'], tool['cel'], tool['flutes'])
            std_tool = standard_tool(prj_cutter.diameter, prj_cutter.flutes, material, carbide_uncoated).clone_with_overrides(
                tool['hfeed'], tool['vfeed'], tool['rpm'], tool.get('stepover', None))
            prj_preset = inventory.EndMillPreset.new(None, "Project preset", prj_cutter,
                std_tool.rpm, std_tool.hfeed, std_tool.vfeed, std_tool.maxdoc, std_tool.stepover,
                tool.get('direction', 0), 0, 0)
            prj_cutter.presets.append(prj_preset)
            self.opAddCutter(prj_cutter)
            self.default_preset_by_tool[prj_cutter] = prj_preset
            self.refreshToolList()
        add_cycles = 'operation_cycles' not in data
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
                    if std.equals(cutter):
                        print ("Matched library tool", cutter.name)
                    else:
                        print ("Found different library tool with same name", cutter.name)
                    cutter_map[cutter.orig_id] = cutter
                    self.project_toolbits[cutter.name] = cutter
                else:
                    print ("New tool without library prototype", cutter.name)
                    if cutter.orig_id == data.get('current_cutter_id', None):
                        currentCutterCycle = cycle
                    # New tool not present in the inventory
                    self.project_toolbits[cutter.name] = cutter
                if add_cycles:
                    cycle = CycleTreeItem(self, cutter)
                    cycleForCutter[orig_id] = cycle
                    self.operModel.appendRow(cycle)
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
                self.default_preset_by_tool[cutter_map[i['tool_id']]] = preset_map[i['preset_id']]
        #self.tool.reload(data['tool'])
        self.drawing.reload(data['drawing']['header'])
        self.drawing.reset()
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
    def make_machine_params(self):
        self.gcode_machine_params = gcodegen.MachineParams(safe_z = self.material.clearance, semi_safe_z = self.material.safe_entry_z)
    def importDrawing(self, fn):
        self.reinitDocument()
        self.filename = None
        self.drawingFilename = fn
        self.drawing.importDrawing(fn)
    def forEachOperation(self, func):
        res = []
        for i in range(self.operModel.rowCount()):
            cycle : CycleTreeItem = self.operModel.item(i)
            for j in range(cycle.rowCount()):
                operation : OperationTreeItem = cycle.child(j)
                res.append(func(operation))
        return res
    def operItemChanged(self, item):
        if isinstance(item, OperationTreeItem):
            if (item.checkState() == 0 and item.cam is not None) or (item.checkState() != 0 and item.cam is None):
                item.startUpdateCAM()
    def startUpdateCAM(self, preset=None):
        self.make_machine_params()
        if preset is None:
            self.forEachOperation(lambda item: item.startUpdateCAM())
        else:
            self.forEachOperation(lambda item: item.startUpdateCAM() if item.tool_preset is preset.inventory_preset else None)
    def pollForUpdateCAM(self):
        results = self.forEachOperation(lambda item: item.pollForUpdateCAM())
        totaldone = 0
        totaloverall = 0
        for i in results:
            if i is not None:
                totaldone += i[0]
                totaloverall += i[1]
        if totaloverall > 0:
            return totaldone / totaloverall
    def waitForUpdateCAM(self, preset=None):
        self.forEachOperation(lambda item: item.waitForUpdateCAM())
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
    def selectCycle(self, cycle):
        self.current_cutter_cycle = cycle
        self.cutterSelected.emit(self.current_cutter_cycle)
    def opAddCutter(self, cutter: inventory.CutterBase):
        cycle = CycleTreeItem(self, cutter)
        self.undoStack.push(AddOperationUndoCommand(self, cycle, self.operModel.invisibleRootItem(), self.operModel.rowCount()))
        #self.operModel.appendRow(self.current_cutter_cycle)
        self.refreshToolList()
        self.selectCycle(cycle)
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
        if len(shapeIds) > 1:
            self.undoStack.beginMacro("Create multiple " + OperationType.toString(operationType))
        try:
            indexes = []
            rowCount = cycle.rowCount()
            for i in shapeIds:
                item = CAMTreeItem.load(self, { '_type' : 'OperationTreeItem', 'shape_id' : i, 'operation' : operationType })
                item.cutter = cycle.cutter
                item.tool_preset = self.default_preset_by_tool.get(item.cutter, None)
                item.startUpdateCAM()
                self.undoStack.push(AddOperationUndoCommand(self, item, cycle, rowCount))
                indexes.append(item.index())
                rowCount += 1
        finally:
            if len(shapeIds) > 1:
                self.undoStack.endMacro()
        return rowCount, cycle, indexes
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
                parent, row = self.operModel.findItem(item)
                self.undoStack.push(DeleteOperationUndoCommand(self, item, parent, row))
        finally:
            if len(items) > 1:
                self.undoStack.endMacro()
    def opMoveItem(self, oldParent, child, newParent, pos):
        self.undoStack.push(MoveItemUndoCommand(oldParent, child, newParent, pos))
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
