import sys
sys.path += '..'

from process import *
from geom import *
from gcodegen import *
from view import *
from propsheet import *
import ezdxf
import json

# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
machine_params = MachineParams(safe_z = safe_z, semi_safe_z = semi_safe_z)
default_props = OperationProps(depth=-12)

if len(sys.argv) < 2:
    print ("Usage: python3 examples/dxf.py <input.dxf> [<output.ngc>]")
    sys.exit(0)

class DrawingItem(object):
    defaultDrawingPen = QPen(QColor(0, 0, 0, 255), 0)
    selectedDrawingPen = QPen(QColor(255, 0, 255, 255), 0)
    def penForPath(self, path):
        return self.selectedDrawingPen if self.untransformed in path.selection else self.defaultDrawingPen

class DrawingCircle(DrawingItem):
    def __init__(self, centre, r, untransformed = None):
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

class DrawingPolyline(DrawingItem):
    def __init__(self, points, closed, untransformed = None):
        self.points = points
        if points:
            xcoords = [p[0] for p in self.points if len(p) == 2]
            ycoords = [p[1] for p in self.points if len(p) == 2]
            self.bounds = (min(xcoords), min(ycoords), max(xcoords), max(ycoords))
        else:
            self.bounds = None
        self.closed = closed
        self.untransformed = untransformed if untransformed is not None else self
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
        self.items = []
        self.origin = (0, 0)
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
    def addItem(self, item):
        self.items.append(item)
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
    def loadFile(self, name):
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

class DrawingViewer(PathViewer):
    selectionChanged = pyqtSignal()
    def __init__(self, document):
        self.document = document
        self.selection = set([])
        PathViewer.__init__(self, DocumentRenderer(document))
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Base)
    def mousePressEvent(self, e):
        b = e.button()
        if e.button() == Qt.LeftButton:
            pos = self.unproject(e.localPos())
            objs = self.document.drawing.drawing.objectsNear(pos, 8 / self.scalingFactor())
            if e.modifiers() & Qt.ControlModifier:
                self.selection ^= set(objs)
            else:
                self.selection = set(objs)
            self.selectionChanged.emit()
            self.renderDrawing()
            self.repaint()
        else:
            PathViewer.mousePressEvent(self, e)
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
    def __init__(self, name=None):
        QStandardItem.__init__(self, name)
        self.setEditable(False)
    def properties(self):
        return []

class DrawingTreeItem(CAMTreeItem):
    prop_x_offset = FloatEditableProperty("X offset", "x_offset", "%0.2f mm")
    prop_y_offset = FloatEditableProperty("Y offset", "y_offset", "%0.2f mm")
    def __init__(self):
        CAMTreeItem.__init__(self, "Drawing")
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
            self.appendRow([DrawingItemTreeItem(item)])
        
class DrawingItemTreeItem(CAMTreeItem):
    def __init__(self, item):
        CAMTreeItem.__init__(self)
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
        CAMTreeItem.__init__(self, "Tool")
        self.setEditable(False)
        self.document = document
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
    def __init__(self, document):
        CAMTreeItem.__init__(self, "Material")
        self.document = document
        self.material = MaterialType.WOOD
        self.thickness = 3
    def properties(self):
        return [self.prop_material, self.prop_thickness]
    def data(self, role):
        if role == Qt.DisplayRole:
            if self.thickness is not None:
                return QVariant("Material: %0.2f mm %s" % (self.thickness, MaterialType.toString(self.material)))
            else:
                return QVariant("Material: ? %s" % (MaterialType.toString(self.material)))
        return CAMTreeItem.data(self, role)
    def getPropertyValue(self, name):
        if name == 'thickness':
            return self.thickness
        if name == 'material':
            return self.material
        assert False, "Unknown attribute: " + repr(name)
    def setPropertyValue(self, name, value):
        if name == 'thickness':
            self.thickness = value
        elif name == 'material':
            self.material = value
            self.document.make_tool()
        else:
            assert False, "Unknown attribute: " + repr(name)
        self.emitDataChanged()


class OperationType(EnumClass):
    OUTSIDE_CONTOUR = 1
    INSIDE_CONTOUR = 2
    POCKET = 3
    ENGRAVE = 4
    descriptions = [
        (OUTSIDE_CONTOUR, "Outside contour"),
        (INSIDE_CONTOUR, "Inside contour"),
        (POCKET, "Pocket"),
        (ENGRAVE, "Engrave"),
    ]

class OperationTreeItem(CAMTreeItem):
    prop_operation = EnumEditableProperty("Operation", "operation", OperationType)
    prop_depth = FloatEditableProperty("Depth", "depth", "%0.2f mm", min=0, max=100, allow_none=True, none_value="full depth")
    prop_start_depth = FloatEditableProperty("Start Depth", "start_depth", "%0.2f mm", min=0, max=100)
    prop_tab_depth = FloatEditableProperty("Tab Depth", "tab_depth", "%0.2f mm", min=0, max=100, allow_none=True, none_value="full depth")
    prop_tab_count = IntEditableProperty("Tab Count", "tab_count", "%d", min=0, max=100, allow_none=True, none_value="default")
    prop_offset = FloatEditableProperty("Offset", "offset", "%0.2f mm", min=-20, max=20)
    def __init__(self, document, shape_source, operation):
        CAMTreeItem.__init__(self)
        self.document = document
        self.shape_source = shape_source
        self.shape = shape_source.translated(*self.document.drawing.translation()).toShape()
        self.depth = None
        self.start_depth = 0
        self.tab_depth = None
        self.tab_count = None
        self.offset = 0
        self.operation = operation
        self.updateCAM()
    def isDropEnabled(self):
        return False
    def store(self):
        dump = {}
        dump['shape_index'] = self.document.drawing.drawing.items.index(self.shape_source)
        for prop in self.properties():
            dump[prop.attribute] = getattr(self, prop.attribute)
        return dump
    def load(self, dump):
        for prop in self.properties():
            setattr(self, prop.attribute, dump[prop.attribute])
    def properties(self):
        return [self.prop_operation, self.prop_depth, self.prop_start_depth, self.prop_tab_depth, self.prop_tab_count, self.prop_offset]
    def onPropertyValueSet(self, name):
        self.updateCAM()
        self.emitDataChanged()
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(OperationType.toString(self.operation) + ", " + (("%0.2f mm" % self.depth) if self.depth is not None else "full") + " depth")
        return CAMTreeItem.data(self, role)
    def updateCAM(self):
        thickness = self.document.material.thickness
        if thickness is None:
            thickness = 0
        depth = self.depth if self.depth is not None else thickness
        start_depth = self.start_depth if self.start_depth is not None else 0
        tab_depth = self.tab_depth if self.tab_depth is not None else depth
        self.gcode_props = OperationProps(-depth, -start_depth, -tab_depth, self.offset)
        self.cam = Operations(machine_params, self.document.gcode_tool, self.gcode_props)
        self.renderer = OperationsRenderer(self.cam)
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
                shape_source = self.document.drawing.drawing.items[i['shape_index']]
                item = OperationTreeItem(self.document, shape_source, i['operation'])
                item.load(i)
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
        self.drawing = DrawingTreeItem()
        self.make_tool()

        self.shapeModel = QStandardItemModel()
        self.shapeModel.setHorizontalHeaderLabels(["Input object"])
        self.shapeModel.appendRow(self.material)
        self.shapeModel.appendRow(self.tool)
        self.shapeModel.appendRow(self.drawing)

        self.operModel = OperationsModel(self)
        self.operModel.setHorizontalHeaderLabels(["Operation"])
        
    def make_tool(self):
        self.gcode_material = MaterialType.descriptions[self.material.material][2] if self.material.material is not None else material_plastics
        self.gcode_coating = carbide_uncoated
        self.gcode_tool_orig = standard_tool(self.tool.diameter, self.tool.flutes, self.gcode_material, self.gcode_coating)
        self.gcode_tool = self.gcode_tool_orig.clone_with_overrides(self.tool.hfeed, self.tool.vfeed, self.tool.depth, self.tool.rpm)
    def loadFile(self, fn):
        self.drawing.drawing.loadFile(fn)
        self.make_tool()
    def forEachOperation(self, func):
        for i in range(self.operModel.rowCount()):
            func(self.operModel.item(i))
    def updateCAM(self):
        self.forEachOperation(lambda item: item.updateCAM())

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
    def activeSelection(self):
        if self.tabs.currentIndex() == 0:
            return "s", [self.document.shapeModel.itemFromIndex(idx) for idx in self.shapeTree.selectionModel().selectedIndexes()]
        if self.tabs.currentIndex() == 1:
            return "o", [self.document.operModel.itemFromIndex(idx) for idx in self.operTree.selectionModel().selectedIndexes()]
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
            ("&Open DXF...", self.fileOpen, QKeySequence.Open, "Open a drawing file"),
            None,
            ("&Export G-Code...", self.fileExportGcode, QKeySequence("Ctrl+G"), "Generate and export the G-Code"),
            None,
            ("E&xit", self.fileExit, QKeySequence.Quit, "Quit application"),
        ])
        self.fileMenu = self.addMenu("&Edit", [
            ("&Delete", self.editDelete, QKeySequence.Delete, "Delete an item"),
        ])
        self.millMenu = self.addMenu("&Mill", [
            ("&Outside contour", self.millOutsideContour, QKeySequence("Ctrl+E"), "Mill the outline of a shape from the outside (part)"),
            ("&Inside contour", self.millInsideContour, QKeySequence("Ctrl+I"), "Mill the outline of a shape from the inside (cutout)"),
            ("&Pocket", self.millPocket, QKeySequence("Ctrl+K"), "Mill a pocket"),
            ("&Engrave", self.millEngrave, QKeySequence("Ctrl+M"), "Follow a line without an offset"),
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
    def millSelectedShapes(self, checkFunc, operType):
        selection = self.viewer.selection
        newSelection = QItemSelection()
        rowCount = self.document.operModel.rowCount()
        translation = self.document.drawing.translation()
        for i in selection:
            shape = i.translated(*translation).toShape()
            if checkFunc(shape):
                item = OperationTreeItem(self.document, i, operType)
                self.document.operModel.appendRow(item)
                index = self.document.operModel.index(rowCount, 0)
                newSelection.select(index, index)
                rowCount += 1
        newRowCount = self.document.operModel.rowCount()
        self.projectDW.selectTab(self.projectDW.OPERATIONS_TAB)
        self.projectDW.operTree.selectionModel().select(newSelection, QItemSelectionModel.ClearAndSelect)
        self.updateOperations()
        self.propsDW.updateProperties()
    def millOutsideContour(self):
        self.millSelectedShapes(lambda shape: shape.closed, OperationType.OUTSIDE_CONTOUR)
    def millInsideContour(self):
        self.millSelectedShapes(lambda shape: shape.closed, OperationType.INSIDE_CONTOUR)
    def millPocket(self):
        self.millSelectedShapes(lambda shape: shape.closed, OperationType.POCKET)
    def millEngrave(self):
        self.millSelectedShapes(lambda shape: True, OperationType.ENGRAVE)
    def canvasMouseMove(self, x, y):
        self.coordLabel.setText("X=%0.2f Y=%0.2f" % (x, y))
    def loadFile(self, fn):
        self.document.loadFile(fn)
        self.projectDW.updateFromDrawing()
        self.viewer.majorUpdate()
        self.updateSelection()
        self.setWindowFilePath(fn)
    def fileOpen(self):
        dlg = QFileDialog(self, "Open a drawing", filter="Drawings (*.dxf);;All files (*)")
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.loadFile(fn)
    def fileExportGcode(self):
        if self.document.material.thickness is None or self.document.material.thickness == 0:
            QMessageBox.critical(self, None, "Material thickness not set")
            return
        if self.document.material.material is None:
            QMessageBox.critical(self, None, "Material type not set")
            return
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
        operations = Operations(machine_params)
        self.document.forEachOperation(lambda item: operations.add_all(item.cam.operations))
        operations.to_gcode_file(fn)
    def fileExit(self):
        self.close()

app = QApplication(sys.argv)
app.setApplicationDisplayName("My CAM experiment")
w = CAMMainWindow(document)
w.initUI()
if len(sys.argv) > 1:
    w.loadFile(sys.argv[1])

w.show()
retcode = app.exec_()
w = None
app = None
sys.exit(retcode)
