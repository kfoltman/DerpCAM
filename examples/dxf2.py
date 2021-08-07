import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from process import *
from geom import *
from gcodegen import *
from view import *
from propsheet import *
from gui.model import *
import ezdxf
import json

class ConfigSettings(object):
    def __init__(self):
        self.resolution = GeometrySettings.RESOLUTION
        self.simplify_arcs = GeometrySettings.simplify_arcs
        self.grid_resolution = 50
        self.load()
    def load(self):
        settings = QSettings("kfoltman", "DerpCAM")
        settings.sync()
        self.resolution = int(settings.value("geometry/resolution", self.resolution))
        self.simplify_arcs = settings.value("geometry/simplify_arcs", self.simplify_arcs) == 'true'
        self.grid_resolution = int(settings.value("display/grid_resolution", self.grid_resolution))
    def save(self):
        settings = QSettings("kfoltman", "DerpCAM")
        settings.setValue("geometry/resolution", self.resolution)
        settings.setValue("geometry/simplify_arcs", self.simplify_arcs)
        settings.setValue("geometry/grid_resolution", self.grid_resolution)
        settings.sync()
    def update(self):
        GeometrySettings.resolution = self.resolution
        GeometrySettings.simplify_arcs = self.simplify_arcs

configSettings = ConfigSettings()
configSettings.update()

class DocumentRenderer(object):
    def __init__(self, document):
        self.document = document
    def bounds(self):
        return self.document.drawing.bounds()
    def renderDrawing(self, owner):
        #PathViewer.renderDrawing(self)
        modeData = None
        self.document.drawing.renderTo(owner, modeData)
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
        self.dragging = False
        self.rubberband_rect = None
        self.start_point = None
        PathViewer.__init__(self, DocumentRenderer(document))
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Base)
    def paintGrid(self, e, qp):
        size = self.size()

        gridPen = QPen(QColor(224, 224, 224))
        qp.setPen(gridPen)
        grid = configSettings.grid_resolution
        if grid > 0 and grid < 1000:
            gridm = grid * self.scalingFactor()
            gridres = 2 + int(size.height() / gridm)
            gridfirst = int(self.unproject(QPointF(0, size.height())).y() / grid)
            for i in range(gridres):
                pt = self.project(QPointF(0, (i + gridfirst) * grid))
                qp.drawLine(QLineF(0.0, pt.y(), size.width(), pt.y()))
            gridfirst = int(self.unproject(QPointF(0, 0)).x() / grid)
            gridres = 2 + int(size.width() / gridm)
            for i in range(gridres):
                pt = self.project(QPointF((i + gridfirst) * grid, 0))
                qp.drawLine(QLineF(pt.x(), 0, pt.x(), size.height()))

        zeropt = self.project(QPointF())
        qp.setPen(QPen(QColor(192, 192, 192)))
        qp.drawLine(QLineF(0.0, zeropt.y(), size.width(), zeropt.y()))
        qp.drawLine(QLineF(zeropt.x(), 0.0, zeropt.x(), size.height()))
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
            objs = self.document.drawing.objectsNear(pos, 8 / self.scalingFactor())
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
            if dist.manhattanLength() > QApplication.startDragDistance():
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
            objs = self.document.drawing.objectsWithin(pt1.x(), pt1.y(), pt2.x(), pt2.y())
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
    def updateShapeSelection(self, selection):
        item_selection = QItemSelection()
        for idx, item in enumerate(self.document.drawing.items()):
            if item in selection:
                item_idx = self.document.drawing.child(idx).index()
                item_selection.select(item_idx, item_idx)
        self.shapeTree.setExpanded(self.document.shapeModel.indexFromItem(self.document.drawing), True)
        self.shapeTree.selectionModel().select(item_selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current)
        if item_selection.indexes():
            self.shapeTree.scrollTo(item_selection.indexes()[0])
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
        self.gridSpin = QSpinBox()
        self.gridSpin.setRange(0, 1000)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.form.addRow("&Resolution (pixels per mm):", self.resolutionSpin)
        self.form.addRow(self.simplifyArcsCheck)
        self.form.addRow("&Display grid (mm):", self.gridSpin)
        self.form.addRow(self.buttonBox)
        self.resolutionSpin.setValue(self.config.resolution)
        self.simplifyArcsCheck.setChecked(self.config.simplify_arcs)
        self.gridSpin.setValue(self.config.grid_resolution)
    def accept(self):
        self.config.resolution = self.resolutionSpin.value()
        self.config.simplify_arcs = self.simplifyArcsCheck.isChecked()
        self.config.grid_resolution = self.gridSpin.value()
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
        self.projectDW.selectionChanged.connect(self.shapeTreeSelectionChanged)
        self.addDockWidget(Qt.RightDockWidgetArea, self.projectDW)
        self.propsDW = CAMPropertiesDockWidget()
        self.propsDW.propsheet.propertyChanged.connect(self.propertyChanged)
        self.document.shapeModel.dataChanged.connect(self.shapeModelChanged)
        self.document.operModel.dataChanged.connect(self.operChanged)
        self.document.operModel.rowsRemoved.connect(self.operRemoved)
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
    def propertyChanged(self, property, objects):
        shapesChanged = False
        for item in objects:
            if isinstance(item, DrawingItemTreeItem):
                shapesChanged = True
        if shapesChanged:
            self.document.updateCAM()
            self.viewer.majorUpdate()
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
    def operRemoved(self):
        self.viewer.majorUpdate()
    def updateSelection(self):
        selType, items = self.projectDW.activeSelection()
        if selType == 's':
            self.viewer.setSelection([item for item in items if isinstance(item, DrawingItemTreeItem)])
            self.propsDW.setSelection(items)
        else:
            self.propsDW.setSelection(items)
    def editDelete(self):
        selType, items = self.projectDW.activeSelection()
        if selType == 'o':
            for item in items:
                self.document.operModel.removeItem(item)
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
        anyLeft = False
        for i in selection:
            shape = i.translated(*translation).toShape()
            if checkFunc(i, shape):
                item = CAMTreeItem.load(self.document, { '_type' : 'OperationTreeItem', 'shape_id' : i.shape_id, 'operation' : operType })
                self.document.operModel.appendRow(item)
                index = self.document.operModel.index(rowCount, 0)
                newSelection.select(index, index)
                rowCount += 1
                newItems += 1
                self.projectDW.shapeTree.selectionModel().select(i.index(), QItemSelectionModel.Deselect)
            else:
                anyLeft = True
        if newItems == 0:
            QMessageBox.warning(self, None, "No objects created")
            return
        if not anyLeft:
            self.projectDW.selectTab(self.projectDW.OPERATIONS_TAB)
            self.projectDW.operTree.selectionModel().select(newSelection, QItemSelectionModel.ClearAndSelect)
            if rowCount:
                self.projectDW.operTree.scrollTo(newSelection.indexes()[0])
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
        self.millSelectedShapes(lambda item, shape: isinstance(item, DrawingCircleTreeItem), OperationType.INTERPOLATED_HOLE)
    def canvasMouseMove(self, x, y):
        self.coordLabel.setText("X=%0.2f Y=%0.2f" % (x, y))
    def importDrawing(self, fn):
        self.document.importDrawing(fn)
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
        if self.document.drawingFilename:
            path = os.path.splitext(self.document.drawingFilename)[0] + ".ngc"
        elif self.document.filename:
            path = os.path.splitext(self.document.filename)[0] + ".ngc"
        else:
            path = ''
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
