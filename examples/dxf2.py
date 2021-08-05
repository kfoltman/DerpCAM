import sys
sys.path += '..'

from process import *
from geom import *
from gcodegen import *
from view import *
from propsheet import *
import ezdxf
import json

default_props = OperationProps(depth=-12)

class ConfigSettings(object):
    def __init__(self):
        self.resolution = GeometrySettings.RESOLUTION
        self.simplify_arcs = GeometrySettings.simplify_arcs
        self.load()
    def load(self):
        settings = QSettings("kfoltman", "DerpCAM")
        settings.sync()
        self.resolution = int(settings.value("geometry/resolution", self.resolution))
        self.simplify_arcs = settings.value("geometry/simplify_arcs", self.simplify_arcs) == 'true'
    def save(self):
        settings = QSettings("kfoltman", "DerpCAM")
        settings.setValue("geometry/resolution", self.resolution)
        settings.setValue("geometry/simplify_arcs", self.simplify_arcs)
        settings.sync()
    def update(self):
        GeometrySettings.resolution = self.resolution
        GeometrySettings.simplify_arcs = self.simplify_arcs

configSettings = ConfigSettings()
configSettings.update()

class DrawingItem(object):
    defaultDrawingPen = QPen(QColor(0, 0, 0, 255), 0)
    selectedItemDrawingPen = QPen(QColor(0, 64, 128, 255), 2)
    next_drawing_item_id = 1
    def __init__(self):
        self.shape_id = DrawingItem.next_drawing_item_id
        DrawingItem.next_drawing_item_id += 1
    def store(self):
        return { '_type' : type(self).__name__, 'shape_id' : self.shape_id }
    @classmethod
    def load(klass, dump):
        rtype = dump['_type']
        if rtype == 'DrawingPolyline':
            item = DrawingPolyline(dump['points'], dump.get('closed', True))
        elif rtype == 'DrawingCircle':
            item = DrawingCircle((dump['cx'], dump['cy']), dump['r'])
        else:
            raise ValueError("Unexpected type: %s" % rtype)
        item.shape_id = dump['shape_id']
        klass.next_drawing_item_id = max(item.shape_id + 1, klass.next_drawing_item_id)
        return item
    def selectedItemPenFunc(self, item, scale):
        # avoid draft behaviour of thick lines
        return QPen(self.selectedItemDrawingPen.color(), self.selectedItemDrawingPen.widthF() / scale), False
    def penForPath(self, path):
        return self.selectedItemPenFunc if self.untransformed in path.selection else self.defaultDrawingPen

class DrawingCircle(DrawingItem):
    def __init__(self, centre, r, untransformed = None):
        DrawingItem.__init__(self)
        self.centre = (centre[0], centre[1])
        self.r = r
        self.calcBounds()
        self.untransformed = untransformed if untransformed is not None else self
    def calcBounds(self):
        self.bounds = (self.centre[0] - self.r, self.centre[1] - self.r,
            self.centre[0] + self.r, self.centre[1] + self.r)
    def distanceTo(self, pt):
        return abs(dist(self.centre, pt) - self.r)
    def renderTo(self, path, modeData):
        path.addLines(self.penForPath(path), circle(self.centre[0], self.centre[1], self.r), True)
    def textDescription(self):
        return "CIRCLE(X=%0.2f, Y=%0.2f, D=%0.2f)" % (*self.centre, 2 * self.r)
    def toShape(self):
        return Shape.circle(*self.centre, self.r)
    def translated(self, dx, dy):
        return DrawingCircle(translate_point(self.centre, dx, dy), self.r, self.untransformed)
    def scaled(self, cx, cy, scale):
        return DrawingCircle(scale_point(self.centre, cx, cy, scale), self.r * scale, self.untransformed)
    def store(self):
        res = DrawingItem.store(self)
        res['cx'] = self.centre[0]
        res['cy'] = self.centre[1]
        res['r'] = self.r
        return res

class DrawingPolyline(DrawingItem):
    def __init__(self, points, closed, untransformed = None):
        DrawingItem.__init__(self)
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
        res = DrawingItem.store(self)
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
        return DrawingPolyline([translate_gen_point(p, dx, dy) for p in self.points], self.closed, self.untransformed)
    def scaled(self, cx, cy, scale):
        return DrawingPolyline([scale_gen_point(p, cx, cy, scale) for p in self.points], self.closed, self.untransformed)
    def renderTo(self, path, modeData):
        path.addLines(self.penForPath(path), CircleFitter.interpolate_arcs(self.points, False, path.scalingFactor()), self.closed)
    def textDescription(self):
        if len(self.points) == 2:
            if len(self.points[1]) == 2:
                return "LINE(%0.2f, %0.2f)-(%0.2f, %0.2f)" % (*self.points[0], *self.points[1])
            elif len(self.points[1]) == 7:
                arc = self.points[1]
                c = arc[3]
                return "ARC(X=%0.2f, Y=%0.2f, R=%0.2f, start=%0.2f, span=%0.2f" % (c.cx, c.cy, c.r, arc[5] * 180 / pi, arc[6] * 180 / pi)
        return "POLYGON(%0.2f, %0.2f)-(%0.2f, %0.2f)" % self.bounds
    def toShape(self):
        return Shape(CircleFitter.interpolate_arcs(self.points, False, 1.0), self.closed)

class SourceDrawing(object):
    def __init__(self):
        self.reset()
    def bounds(self):
        b = None
        for item in self.items:
            if b is None:
                b = item.bounds
            else:
                b = max_bounds(b, item.bounds)
        if b is None:
            return (-1, -1, 1, 1)
        margin = 5
        return (b[0] - self.origin[0] - margin, b[1] - self.origin[1] - margin, b[2] - self.origin[0] + margin, b[3] - self.origin[1] + margin)
    def reset(self):
        self.items = []
        self.items_by_id = {}
        self.origin = (0, 0)
    def addItem(self, item):
        self.items.append(item)
        self.items_by_id[item.shape_id] = item
    def itemById(self, shape_id):
        return self.items_by_id.get(shape_id, None)
    def renderTo(self, path, modeData):
        for i in self.items:
            i.translated(-self.origin[0], -self.origin[1]).renderTo(path, modeData)
    def objectsNear(self, pos, margin):
        xy = (pos.x() + self.origin[0], pos.y() + self.origin[1])
        found = []
        for item in self.items:
            if point_inside_bounds(expand_bounds(item.bounds, margin), xy):
                distance = item.distanceTo(xy)
                if distance is not None and distance < margin:
                    found.append(item)
        return found
    def objectsWithin(self, xs, ys, xe, ye):
        xs += self.origin[0]
        ys += self.origin[1]
        xe += self.origin[0]
        ye += self.origin[1]
        bounds = (xs, ys, xe, ye)
        found = []
        for item in self.items:
            if inside_bounds(item.bounds, bounds):
                found.append(item)
        return found
    def importDrawing(self, name):
        doc = ezdxf.readfile(name)
        self.reset()
        msp = doc.modelspace()
        for entity in msp:
            dxftype = entity.dxftype()
            if dxftype == 'LWPOLYLINE':
                points, closed = polyline_to_points(entity)
                self.addItem(DrawingPolyline(points, closed))
            elif dxftype == 'LINE':
                start = tuple(entity.dxf.start)[0:2]
                end = tuple(entity.dxf.end)[0:2]
                self.addItem(DrawingPolyline([start, end], False))
            elif dxftype == 'CIRCLE':
                self.addItem(DrawingCircle(entity.dxf.center, entity.dxf.radius))
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
                self.addItem(DrawingPolyline(points, False))
            else:
                print ("Ignoring DXF entity: %s" % dxftype)

class DocumentRenderer(object):
    def __init__(self, document):
        self.document = document
        # Operations(machine_params=machine_params, tool=document.gcode_tool, props=default_props)        
    def bounds(self):
        return self.document.drawing.drawing.bounds()
    def renderDrawing(self, owner):
        #PathViewer.renderDrawing(self)
        modeData = None
        self.document.drawing.drawing.renderTo(owner, modeData)
        self.document.forEachOperation(lambda item: item.renderer.renderToolpaths(owner))
        self.document.forEachOperation(lambda item: item.renderer.renderNotTabs(owner))
        self.lastpt = (0, 0)
        self.document.forEachOperation(lambda item: self.renderRapids(item.renderer, owner))
    def renderRapids(self, renderer, owner):
        self.lastpt = renderer.renderRapids(owner, self.lastpt)

class OperationsRendererWithSelection(OperationsRenderer):
    def __init__(self, owner):
        OperationsRenderer.__init__(self, owner.cam)
        self.owner = owner
    def isHighlighted(self, operation):
        return self.owner.isSelected

class DrawingViewer(PathViewer):
    selectionChanged = pyqtSignal()
    def __init__(self, document):
        self.document = document
        self.selection = set([])
        self.dragging = False
        self.rubberband_rect = None
        self.start_point = None
        PathViewer.__init__(self, DocumentRenderer(document))
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Base)
    def paintOverlays(self, e, qp):
        if self.rubberband_rect:
            qp.setOpacity(0.33)
            qp.drawRect(self.rubberband_rect)
            qp.setOpacity(1.0)
    def mousePressEvent(self, e):
        b = e.button()
        if e.button() == Qt.LeftButton:
            self.rubberband_rect = None
            self.dragging = False
            pos = self.unproject(e.localPos())
            objs = self.document.drawing.drawing.objectsNear(pos, 8 / self.scalingFactor())
            if objs:
                if e.modifiers() & Qt.ControlModifier:
                    self.selection ^= set(objs)
                else:
                    self.selection = set(objs)
                self.selectionChanged.emit()
                self.renderDrawing()
                self.repaint()
                self.start_point = e.localPos()
            else:
                self.start_point = e.localPos()
                if self.selection and not (e.modifiers() & Qt.ControlModifier):
                    self.selection = set()
                    self.selectionChanged.emit()
                    self.renderDrawing()
                    self.repaint()
        else:
            PathViewer.mousePressEvent(self, e)
    def mouseMoveEvent(self, e):
        if not self.dragging and self.start_point:
            dist = e.localPos() - self.start_point
            if dist.manhattanLength() > 5:
                self.dragging = True
        if self.dragging:
            self.rubberband_rect = QRectF(self.start_point, e.localPos())
            self.startDeferredRepaint()
            self.repaint()
        PathViewer.mouseMoveEvent(self, e)
    def mouseReleaseEvent(self, e):
        if self.dragging:
            pt1 = self.unproject(self.rubberband_rect.bottomLeft())
            pt2 = self.unproject(self.rubberband_rect.topRight())
            objs = self.document.drawing.drawing.objectsWithin(pt1.x(), pt1.y(), pt2.x(), pt2.y())
            if e.modifiers() & Qt.ControlModifier:
                self.selection ^= set(objs)
            else:
                self.selection = set(objs)
            self.dragging = False
            self.start_point = None
            self.rubberband_rect = None
            self.selectionChanged.emit()
            self.renderDrawing()
            self.repaint()
        else:
            self.dragging = False
            self.start_point = None
            self.rubberband_rect = None
        PathViewer.mouseReleaseEvent(self, e)
    def setSelection(self, selection):
        self.selection = set(selection)
        self.renderDrawing()
        self.repaint()

def polyline_to_points(entity):
    points = []
    lastx, lasty = entity[-1][0:2]
    lastbulge = entity[-1][4]
    for point in entity:
        x, y = point[0:2]
        if lastbulge:
            theta = 4 * atan(lastbulge)
            dx, dy = x - lastx, y - lasty
            mx, my = weighted((lastx, lasty), (x, y), 0.5)
            angle = atan2(dy, dx)
            dist = sqrt(dx * dx + dy * dy)
            d = dist / 2
            r = abs(d / sin(theta / 2))
            c = d / tan(theta / 2)
            cx = mx - c * sin(angle)
            cy = my + c * cos(angle)
            sa = atan2(lasty - cy, lastx - cx)
            ea = sa + theta
            points += circle(cx, cy, r, 1000, sa, ea)
            points.append((x, y))
        else:
            points.append((x, y))
        lastbulge = point[4]
        lastx, lasty = x, y
    return points, entity.closed

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
            raise ValuError("Unexpected type: %s" % rtype)
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
        elif rtype == 'MaterialTreeItem':
            res = MaterialTreeItem(document)
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

class DrawingTreeItem(CAMTreeItem):
    prop_x_offset = FloatEditableProperty("X offset", "x_offset", "%0.2f mm")
    prop_y_offset = FloatEditableProperty("Y offset", "y_offset", "%0.2f mm")
    def __init__(self, document):
        CAMTreeItem.__init__(self, document, "Drawing")
        self.drawing = SourceDrawing()
        self.x_offset = 0
        self.y_offset = 0
    def properties(self):
        return [self.prop_x_offset, self.prop_y_offset]
    def translation(self):
        return (-self.x_offset, -self.y_offset)
    def onPropertyValueSet(self, name):
        self.drawing.origin = (self.x_offset, self.y_offset)
        self.emitDataChanged()
    def updateFromDrawing(self):
        self.removeRows(0, self.rowCount())
        for item in self.drawing.items:
            self.appendRow([DrawingItemTreeItem(self.document, item)])
    def shapeById(self, item_id):
        return self.drawing.itemById(item_id)
        
class DrawingItemTreeItem(CAMTreeItem):
    def __init__(self, document, item=None):
        CAMTreeItem.__init__(self, document)
        self.item = item
    def onPropertyValueSet(self, name):
        self.emitDataChanged()
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(self.item.textDescription())
        return CAMTreeItem.data(self, role)
        
class ToolTreeItem(CAMTreeItem):
    prop_diameter = FloatEditableProperty("Diameter", "diameter", "%0.2f mm", min=0, max=100, allow_none=False)
    prop_flutes = IntEditableProperty("# flutes", "flutes", "%d", min=1, max=100, allow_none=True)
    prop_cel = FloatEditableProperty("Flute length", "cel", "%0.1f mm", min=0.1, max=100, allow_none=True)
    prop_doc = FloatEditableProperty("Cut depth per pass", "depth", "%0.2f mm", min=0.01, max=100, allow_none=True)
    prop_rpm = FloatEditableProperty("RPM", "rpm", "%0.0f/min", min=0.1, max=60000, allow_none=True)
    prop_hfeed = FloatEditableProperty("Feed rate", "hfeed", "%0.1f mm/min", min=0.1, max=10000, allow_none=True)
    prop_vfeed = FloatEditableProperty("Plunge rate", "vfeed", "%0.1f mm/min", min=0.1, max=10000, allow_none=True)
    def __init__(self, document):
        CAMTreeItem.__init__(self, document, "Tool")
        self.setEditable(False)
        self.diameter = 3.2
        self.flutes = 2
        self.cel = 22
        self.depth = None
        self.hfeed = None
        self.vfeed = None
        self.rpm = None
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
        
class EnumClass(object):
    @classmethod
    def toString(classInst, value):
        for data in classInst.descriptions:
            if value == data[0]:
                return data[1]
        return None
    
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

class MaterialTreeItem(CAMTreeItem):
    prop_material = EnumEditableProperty("Material", "material", MaterialType, allow_none=True, none_value="Unknown")
    prop_thickness = FloatEditableProperty("Thickness", "thickness", "%0.2f mm", min=0, max=100, allow_none=True)
    prop_clearance = FloatEditableProperty("Clearance", "clearance", "%0.2f mm", min=0, max=100, allow_none=True)
    prop_safe_entry_z = FloatEditableProperty("Safe entry Z", "safe_entry_z", "%0.2f mm", min=0, max=100, allow_none=True)
    def __init__(self, document):
        CAMTreeItem.__init__(self, document, "Material")
        self.material = MaterialType.WOOD
        self.thickness = 3
        self.clearance = 5
        self.safe_entry_z = 1
    def properties(self):
        return [self.prop_material, self.prop_thickness, self.prop_clearance, self.prop_safe_entry_z]
    def data(self, role):
        if role == Qt.DisplayRole:
            if self.thickness is not None:
                return QVariant("Material: %0.2f mm %s" % (self.thickness, MaterialType.toString(self.material)))
            else:
                return QVariant("Material: ? %s" % (MaterialType.toString(self.material)))
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
        (INTERPOLATED_HOLE, "Helix-interpolated hole"),
    ]

class OperationTreeItem(CAMTreeItem):
    prop_operation = EnumEditableProperty("Operation", "operation", OperationType)
    prop_depth = FloatEditableProperty("Depth", "depth", "%0.2f mm", min=0, max=100, allow_none=True, none_value="full depth")
    prop_start_depth = FloatEditableProperty("Start Depth", "start_depth", "%0.2f mm", min=0, max=100)
    prop_tab_height = FloatEditableProperty("Tab Height", "tab_height", "%0.2f mm", min=0, max=100, allow_none=True, none_value="full height")
    prop_tab_count = IntEditableProperty("Tab Count", "tab_count", "%d", min=0, max=100, allow_none=True, none_value="default")
    prop_offset = FloatEditableProperty("Offset", "offset", "%0.2f mm", min=-20, max=20)
    def __init__(self, document):
        CAMTreeItem.__init__(self, document)
        self.shape_id = None
        self.shape = None
        self.depth = None
        self.start_depth = 0
        self.tab_height = None
        self.tab_count = None
        self.offset = 0
        self.operation = OperationType.OUTSIDE_CONTOUR
        self.isSelected = False
        self.updateCAM()
    def isDropEnabled(self):
        return False
    def isPropertyValid(self, name):
        if self.operation == OperationType.POCKET and name in ['tab_height', 'tab_count']:
            return False
        if self.operation == OperationType.ENGRAVE and name in ['tab_height', 'tab_count', 'offset']:
            return False
        return True
    def store(self):
        dump = CAMTreeItem.store(self)
        dump['shape_id'] = self.shape_id
        return dump
    def class_specific_load(self, dump):
        self.shape_id = dump.get('shape_id', None)
        self.updateCAM()
    def properties(self):
        return [self.prop_operation, self.prop_depth, self.prop_start_depth, self.prop_tab_height, self.prop_tab_count, self.prop_offset]
    def onPropertyValueSet(self, name):
        self.updateCAM()
        self.emitDataChanged()
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(OperationType.toString(self.operation) + ", " + (("%0.2f mm" % self.depth) if self.depth is not None else "full") + " depth")
        return CAMTreeItem.data(self, role)
    def updateCAM(self):
        self.orig_shape = self.document.drawing.shapeById(self.shape_id) if self.shape_id is not None else None
        if self.orig_shape:
            translation = (-self.document.drawing.x_offset, -self.document.drawing.y_offset)
            self.shape = self.orig_shape.translated(*translation).toShape()
        thickness = self.document.material.thickness
        if thickness is None:
            thickness = 0
        depth = self.depth if self.depth is not None else thickness
        start_depth = self.start_depth if self.start_depth is not None else 0
        tab_depth = max(start_depth, depth - self.tab_height) if self.tab_height is not None else start_depth
        self.gcode_props = OperationProps(-depth, -start_depth, -tab_depth, self.offset)
        self.cam = Operations(self.document.gcode_machine_params, self.document.gcode_tool, self.gcode_props)
        self.renderer = OperationsRendererWithSelection(self)
        if self.shape:
            tabs = self.tab_count if self.tab_count is not None else self.shape.default_tab_count(2, 8, 200)
            if self.operation == OperationType.OUTSIDE_CONTOUR:
                self.cam.outside_contour(self.shape, tabs=tabs)
            elif self.operation == OperationType.INSIDE_CONTOUR:
                self.cam.inside_contour(self.shape, tabs=tabs)
            elif self.operation == OperationType.POCKET:
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
                #shape_source = self.document.drawing.drawing.items[i['shape_index']]
                item = CAMTreeItem.load(self.document, i)
                #OperationTreeItem(self.document, shape_source, i['operation'])
                self.insertRow(row, item)
                row += 1
            return True
        return False
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

class DocumentModel(QObject):
    def __init__(self):
        QObject.__init__(self)
        self.material = MaterialTreeItem(self)
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
        data['drawing'] = { 'header' : self.drawing.store(), 'items' : [item.store() for item in self.drawing.drawing.items] }
        data['operations'] = self.forEachOperation(lambda op: op.store())
        return data
    def load(self, data):
        self.material.reload(data['material'])
        self.tool.reload(data['tool'])
        self.drawing.reload(data['drawing']['header'])
        self.drawing.drawing.reset()
        for i in data['drawing']['items']:
            self.drawing.drawing.addItem(DrawingItem.load(i))
        for i in data['operations']:
            operation = CAMTreeItem.load(self, i)
            self.operModel.appendRow(operation)
        self.drawing.updateFromDrawing()
        self.updateCAM()
    def make_machine_params(self):
        self.gcode_machine_params = MachineParams(safe_z = self.material.clearance, semi_safe_z = self.material.safe_entry_z)
    def make_tool(self):
        self.gcode_material = MaterialType.descriptions[self.material.material][2] if self.material.material is not None else material_plastics
        self.gcode_coating = carbide_uncoated
        self.gcode_tool_orig = standard_tool(self.tool.diameter, self.tool.flutes, self.gcode_material, self.gcode_coating)
        self.gcode_tool = self.gcode_tool_orig.clone_with_overrides(self.tool.hfeed, self.tool.vfeed, self.tool.depth, self.tool.rpm)
    def importDrawing(self, fn):
        self.filename = None
        self.drawingFilename = fn
        self.drawing.drawing.importDrawing(fn)
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

document = DocumentModel()

class CAMObjectTreeDockWidget(QDockWidget):
    selectionChanged = pyqtSignal([])
    INPUTS_TAB = 0
    OPERATIONS_TAB = 1
    def __init__(self, document):
        QDockWidget.__init__(self, "Project content")
        self.document = document
        self.setFeatures(self.features() & ~QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumSize(400, 100)
        self.tabs = QTabWidget()
        
        tree = QTreeView()
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tree.setModel(self.document.shapeModel)
        tree.selectionModel().selectionChanged.connect(self.shapeSelectionChanged)
        self.shapeTree = tree
        self.tabs.addTab(tree, "&Input")
        
        tree = QTreeView()
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tree.setModel(self.document.operModel)
        tree.setDragEnabled(True)
        #tree.setAcceptDrops(True)
        tree.setDropIndicatorShown(True)
        tree.setDragDropOverwriteMode(False)
        tree.setDragDropMode(QAbstractItemView.InternalMove)
        tree.selectionModel().selectionChanged.connect(self.operationSelectionChanged)
        self.operTree = tree
        self.tabs.addTab(tree, "&Operations")
        self.tabs.setTabPosition(QTabWidget.South)
        self.tabs.currentChanged.connect(self.tabSelectionChanged)
        self.setWidget(self.tabs)
    def updateFromDrawing(self):
        self.document.drawing.updateFromDrawing()
    def updateShapeSelection(self, selection):
        item_selection = QItemSelection()
        for idx, item in enumerate(self.document.drawing.drawing.items):
            if item in selection:
                item_idx = self.document.drawing.child(idx).index()
                item_selection.select(item_idx, item_idx)
        self.shapeTree.setExpanded(self.document.shapeModel.indexFromItem(self.document.drawing), True)
        self.shapeTree.selectionModel().select(item_selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current)
    def tabSelectionChanged(self):
        self.selectionChanged.emit()
    def shapeSelectionChanged(self):
        self.selectionChanged.emit()
    def operationSelectionChanged(self):
        self.selectionChanged.emit()
    def selectTab(self, tabIndex):
        self.tabs.setCurrentIndex(tabIndex)
    def shapeSelection(self):
        return [self.document.shapeModel.itemFromIndex(idx) for idx in self.shapeTree.selectionModel().selectedIndexes()]
    def operSelection(self):
        return [self.document.operModel.itemFromIndex(idx) for idx in self.operTree.selectionModel().selectedIndexes()]
    def activeSelection(self):
        if self.tabs.currentIndex() == 0:
            return "s", self.shapeSelection()
        if self.tabs.currentIndex() == 1:
            return "o", self.operSelection()
        assert False

class CAMPropertiesDockWidget(QDockWidget):
    def __init__(self):
        QDockWidget.__init__(self, "Properties")
        self.setFeatures(self.features() & ~QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumSize(400, 100)
        self.propsheet = PropertySheetWidget([])
        self.setWidget(self.propsheet)
        self.updateModel()
    def updateModel(self):
        self.propsheet.setObjects([])
    def updateProperties(self):
        self.propsheet.refreshAll()
    def setSelection(self, selection):
        properties = []
        seen = set([])
        all_have = None
        for i in selection:
            item_props = i.properties()
            for p in item_props:
                if p not in seen:
                    properties.append(p)
                    seen.add(p)
            seen |= set(item_props)
            if all_have is None:
                all_have = set(item_props)
            else:
                all_have &= set(item_props)
        if seen:
            properties = [p for p in properties if p in all_have]
        self.propsheet.setObjects(selection, properties)

class PreferencesDialog(QDialog):
    def __init__(self, parent, config):
        QDialog.__init__(self, parent)
        self.config = config
    def initUI(self):
        self.form = QFormLayout(self)
        self.resolutionSpin = QSpinBox()
        self.resolutionSpin.setRange(10, 100)
        self.simplifyArcsCheck = QCheckBox("&Convert lines to arcs (experimental)")
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.form.addRow("&Resolution (pixels per mm):", self.resolutionSpin)
        self.form.addRow(self.simplifyArcsCheck)
        self.form.addRow(self.buttonBox)
        self.resolutionSpin.setValue(self.config.resolution)
        self.simplifyArcsCheck.setChecked(self.config.simplify_arcs)
    def accept(self):
        self.config.resolution = self.resolutionSpin.value()
        self.config.simplify_arcs = self.simplifyArcsCheck.isChecked()
        QDialog.accept(self)

class CAMMainWindow(QMainWindow):
    def __init__(self, document):
        QMainWindow.__init__(self)
        self.document = document
    def addMenu(self, menuLabel, actions):
        menu = self.menuBar().addMenu(menuLabel)
        for i in actions:
            if i is None:
                menu.addSeparator()
            else:
                label, fn, shortcut, tip = i
                action = QAction(label, self)
                if shortcut:
                    action.setShortcuts(shortcut)
                if tip:
                    action.setStatusTip(tip)
                action.triggered.connect(fn)
                menu.addAction(action)
        return menu
    def initUI(self):
        self.viewer = DrawingViewer(self.document)
        self.viewer.initUI()
        self.setCentralWidget(self.viewer)
        self.projectDW = CAMObjectTreeDockWidget(self.document)
        self.projectDW.updateFromDrawing()
        self.projectDW.selectionChanged.connect(self.shapeTreeSelectionChanged)
        self.addDockWidget(Qt.RightDockWidgetArea, self.projectDW)
        self.propsDW = CAMPropertiesDockWidget()
        self.document.shapeModel.dataChanged.connect(self.shapeModelChanged)
        self.document.operModel.dataChanged.connect(self.operChanged)
        self.addDockWidget(Qt.RightDockWidgetArea, self.propsDW)
        self.fileMenu = self.addMenu("&File", [
            ("&Import DXF...", self.fileImport, QKeySequence("Ctrl+L"), "Load a drawing file"),
            None,
            ("&Open project...", self.fileOpen, QKeySequence.Open, "Open a project file"),
            ("&Save project", self.fileSave, QKeySequence.Save, "Save a project file"),
            ("Save project &as...", self.fileSaveAs, QKeySequence.SaveAs, "Save a project file under a different name"),
            None,
            ("&Export G-Code...", self.fileExportGcode, QKeySequence("Ctrl+G"), "Generate and export the G-Code"),
            None,
            ("E&xit", self.fileExit, QKeySequence.Quit, "Quit application"),
        ])
        self.fileMenu = self.addMenu("&Edit", [
            ("&Delete", self.editDelete, QKeySequence.Delete, "Delete an item"),
            None,
            ("&Preferences...", self.editPreferences, None, "Set application preferences"),
        ])
        self.millMenu = self.addMenu("&Mill", [
            ("&Outside contour", self.millOutsideContour, QKeySequence("Ctrl+E"), "Mill the outline of a shape from the outside (part)"),
            ("&Inside contour", self.millInsideContour, QKeySequence("Ctrl+I"), "Mill the outline of a shape from the inside (cutout)"),
            ("&Pocket", self.millPocket, QKeySequence("Ctrl+K"), "Mill a pocket"),
            ("&Engrave", self.millEngrave, QKeySequence("Ctrl+M"), "Follow a line without an offset"),
            ("Interpolated &hole", self.millInterpolatedHole, QKeySequence("Ctrl+H"), "Mill a circular hole wider than the endmill size using helical interpolation"),
        ])
        self.coordLabel = QLabel("X=? Y=?")
        self.statusBar().addPermanentWidget(self.coordLabel)
        self.viewer.coordsUpdated.connect(self.canvasMouseMove)
        self.viewer.selectionChanged.connect(self.viewerSelectionChanged)
        self.updateOperations()
    def updateOperations(self):
        self.viewer.majorUpdate()
        #self.projectDW.updateFromOperations(self.viewer.operations)
        self.updateSelection()
    def viewerSelectionChanged(self):
        self.projectDW.updateShapeSelection(self.viewer.selection)
    def shapeTreeSelectionChanged(self):
        self.updateSelection()
        if self.document.setOperSelection(self.projectDW.operSelection()):
            self.viewer.majorUpdate()
    def shapeModelChanged(self, index):
        item = self.document.shapeModel.itemFromIndex(index)
        if type(item) == MaterialTreeItem:
            self.materialChanged()
        elif type(item) == ToolTreeItem:
            self.toolChanged()
        elif type(item) == DrawingTreeItem:
            self.drawingChanged()
    def materialChanged(self):
        if self.document.material.thickness is not None:
            default_props.depth = -self.document.material.thickness
        else:
            default_props.depth = 0
        self.document.tool.model().itemChanged.emit(self.document.tool)
    def toolChanged(self):
        self.propsDW.updateProperties()
        self.document.updateCAM()
        self.viewer.majorUpdate()
    def drawingChanged(self):
        self.document.updateCAM()
        self.viewer.majorUpdate()
    def operChanged(self):
        self.viewer.majorUpdate()
    def updateSelection(self):
        selType, items = self.projectDW.activeSelection()
        if selType == 's':
            self.viewer.setSelection([item.item for item in items if isinstance(item, DrawingItemTreeItem)])
            self.propsDW.setSelection(items)
        else:
            self.propsDW.setSelection(items)
    def editDelete(self):
        selType, items = self.projectDW.activeSelection()
        if selType == 'o':
            for item in items:
                index = self.document.operModel.indexFromItem(item)
                self.document.operModel.removeRow(index.row())
            self.viewer.majorUpdate()
    def editPreferences(self):
        dlg = PreferencesDialog(self, configSettings)
        self.prefDlg = dlg
        dlg.initUI()
        if dlg.exec():
            configSettings.update()
            self.document.updateCAM()
            self.viewer.majorUpdate()
            configSettings.save()
    def millSelectedShapes(self, checkFunc, operType):
        selection = self.viewer.selection
        newSelection = QItemSelection()
        rowCount = self.document.operModel.rowCount()
        translation = self.document.drawing.translation()
        newItems = 0
        for i in selection:
            shape = i.translated(*translation).toShape()
            if checkFunc(i, shape):
                item = CAMTreeItem.load(self.document, { '_type' : 'OperationTreeItem', 'shape_id' : i.shape_id, 'operation' : operType })
                self.document.operModel.appendRow(item)
                index = self.document.operModel.index(rowCount, 0)
                newSelection.select(index, index)
                rowCount += 1
                newItems += 1
        if newItems == 0:
            QMessageBox.warning(self, None, "No objects created")
            return
        self.projectDW.selectTab(self.projectDW.OPERATIONS_TAB)
        self.projectDW.operTree.selectionModel().select(newSelection, QItemSelectionModel.ClearAndSelect)
        self.updateOperations()
        self.propsDW.updateProperties()
    def millOutsideContour(self):
        self.millSelectedShapes(lambda item, shape: shape.closed, OperationType.OUTSIDE_CONTOUR)
    def millInsideContour(self):
        self.millSelectedShapes(lambda item, shape: shape.closed, OperationType.INSIDE_CONTOUR)
    def millPocket(self):
        self.millSelectedShapes(lambda item, shape: shape.closed, OperationType.POCKET)
    def millEngrave(self):
        self.millSelectedShapes(lambda item, shape: True, OperationType.ENGRAVE)
    def millInterpolatedHole(self):
        self.millSelectedShapes(lambda item, shape: isinstance(item, DrawingCircle), OperationType.INTERPOLATED_HOLE)
    def canvasMouseMove(self, x, y):
        self.coordLabel.setText("X=%0.2f Y=%0.2f" % (x, y))
    def importDrawing(self, fn):
        self.document.importDrawing(fn)
        self.projectDW.updateFromDrawing()
        self.viewer.majorUpdate()
        self.updateSelection()
        self.setWindowFilePath(fn)
    def fileImport(self):
        dlg = QFileDialog(self, "Import a drawing", filter="Drawings (*.dxf);;All files (*)")
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.importDrawing(fn)
    def fileOpen(self):
        dlg = QFileDialog(self, "Open a project", filter="DerpCAM project (*.dcp);;All files (*)")
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.openProject(fn)
    def fileSaveAs(self):
        dlg = QFileDialog(self, "Save a project", filter="DerpCAM project (*.dcp);;All files (*)")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setFileMode(QFileDialog.AnyFile)
        if self.document.drawingFilename is not None:
            path = self.document.drawingFilename.replace(".dxf", ".dcp") # XXXKF too crude
            dlg.selectFile(path)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.document.filename = fn
            self.saveProject(fn)
    def fileSave(self):
        if self.document.filename is None:
            self.fileSaveAs()
        else:
            self.saveProject(self.document.filename)
    def saveProject(self, fn):
        data = self.document.store()
        f = open(fn, "w")
        json.dump(data, f, indent=2)
        f.close()
    def loadProject(self, fn):
        f = open(fn, "r")
        data = json.load(f)
        f.close()
        self.document.filename = fn
        self.document.drawingFilename = None
        self.document.load(data)
        self.drawingChanged()
    def fileExportGcode(self):
        try:
            self.document.validateForOutput()
        except ValueError as e:
            QMessageBox.critical(self, None, str(e))
            return
        self.document.updateCAM()
        dlg = QFileDialog(self, "Export the G-Code", filter="G-Code (*.ngc);;All files (*)")
        path = self.windowFilePath()
        path = path.replace(".dxf", ".ngc") # XXXKF too crude
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setFileMode(QFileDialog.AnyFile)
        dlg.setDefaultSuffix(".ngc")
        dlg.selectFile(path)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.exportGcode(fn)
    def exportGcode(self, fn):
        operations = Operations(self.document.gcode_machine_params)
        self.document.forEachOperation(lambda item: operations.add_all(item.cam.operations))
        operations.to_gcode_file(fn)
    def fileExit(self):
        self.close()

QCoreApplication.setOrganizationName("kfoltman")
QCoreApplication.setApplicationName("DerpCAM")

app = QApplication(sys.argv)
app.setApplicationDisplayName("My CAM experiment")
w = CAMMainWindow(document)
w.initUI()
if len(sys.argv) > 1:
    fn = sys.argv[1]
    fnl = fn.lower()
    if fnl.endswith(".dxf"):
        w.importDrawing(fn)
    elif fnl.endswith(".dcp"):
        w.loadProject(fn)

w.show()
retcode = app.exec_()
w = None
app = None
sys.exit(retcode)
