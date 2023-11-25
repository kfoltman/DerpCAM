import json
import os.path
import sys

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.common import guiutils, geom
from DerpCAM.gui import propsheet, settings, canvas, model, dock, cutter_mgr, about, draw, editors, wall_profile_mgr

OperationType = model.OperationType

class MenuItem:
    def __init__(self, label, fn, shortcut, tip, enable_func=None, allow_in_editor=False):
        self.label = label
        self.fn = fn
        self.shortcut = shortcut
        self.tip = tip
        self.enable_func = enable_func
        self.allow_in_editor = allow_in_editor

class CAMMainWindow(QMainWindow):
    def __init__(self, document, config):
        QMainWindow.__init__(self)
        self.document = document
        self.configSettings = config
        self.resetZoomNeeded = False
        self.lastProgress = None
        self.clipboard = None
        self.copyIsCut = None
        self.actionData = {}
    def addMenu(self, menuLabel, actions):
        menu = self.menuBar().addMenu(menuLabel)
        for i in actions:
            if i is None:
                menu.addSeparator()
            elif isinstance(i, QAction):
                menu.addAction(i)
            elif isinstance(i, MenuItem):
                action = QAction(i.label, self)
                if i.shortcut:
                    action.setShortcuts(i.shortcut)
                if i.tip:
                    action.setStatusTip(i.tip)
                action.triggered.connect(i.fn)
                self.actionData[action] = i
                menu.addAction(action)
            else:
                assert False, i
        menu.aboutToShow.connect(lambda: self.refreshMenu(menu))
        return menu
    def refreshMenu(self, menu):
        for i in menu.actions():
            adata = self.actionData.get(i)
            if adata is not None:
                if adata.enable_func is not None:
                    i.setEnabled(adata.enable_func() and (self.viewer.editor is None or adata.allow_in_editor))
                else:
                    i.setEnabled(self.viewer.editor is None or adata.allow_in_editor)
    def initUI(self):
        def addShortcut(action, shortcut):
            action.setShortcuts(shortcut)
            return action
        self.mruList = self.configSettings.loadMru()
        self.viewer = canvas.DrawingViewer(self.document, self.configSettings)
        self.viewer.initUI()
        self.viewer.editorChangeRequest.connect(self.switchToEditor)
        self.viewer.itemEditRequest.connect(self.onDrawingItemDoubleClicked)
        self.setCentralWidget(self.viewer)

        self.projectDW = dock.CAMObjectTreeDockWidget(self.document)
        self.projectDW.selectionChanged.connect(self.shapeTreeSelectionChanged)
        self.projectDW.editorChangeRequest.connect(self.switchToEditor)
        self.projectDW.operationTouched.connect(self.operationTouched)
        self.projectDW.noOperationTouched.connect(self.noOperationTouched)
        self.projectDW.shapeTree.doubleClicked.connect(self.onInputDoubleClicked)
        self.addDockWidget(Qt.RightDockWidgetArea, self.projectDW)

        self.document.undoStack.cleanChanged.connect(self.cleanFlagChanged)
        self.document.propertyChanged.connect(self.itemPropertyChanged)
        self.document.operModel.rowsInserted.connect(self.operInserted)
        self.document.operModel.rowsRemoved.connect(self.operRemoved)
        self.document.shapesCreated.connect(self.onShapesCreated)
        self.document.shapesUpdated.connect(self.onShapesUpdated)
        self.document.shapesDeleted.connect(self.onShapesDeleted)
        self.document.operationsUpdated.connect(self.onOperationsUpdated)
        self.document.tabEditRequested.connect(self.projectDW.operationHoldingTabs)
        self.document.entryExitEditRequested.connect(self.projectDW.operationEntryExitPoints)
        self.document.islandsEditRequested.connect(self.projectDW.operationIslands)
        self.document.polylineEditRequested.connect(self.projectDW.shapeEdit)
        self.document.toolListRefreshed.connect(self.projectDW.onToolListRefreshed)
        self.document.cutterSelected.connect(self.projectDW.onCutterSelected)
        self.document.projectCleared.connect(self.onDrawingImportedOrProjectLoaded)
        self.document.drawingImported.connect(self.onDrawingImportedOrProjectLoaded)
        self.document.projectLoaded.connect(self.onDrawingImportedOrProjectLoaded)

        self.propsDW = dock.CAMPropertiesDockWidget(self.document)
        self.addDockWidget(Qt.RightDockWidgetArea, self.propsDW)

        self.editorDW = dock.CAMEditorDockWidget(self.document)
        self.editorDW.hide()
        self.editorDW.applyClicked.connect(self.onEditorApplyClicked)
        self.addDockWidget(Qt.RightDockWidgetArea, self.editorDW)

        self.fileMenu = self.addMenu("&File", [
            MenuItem("&New project", self.fileNew, QKeySequence.New, "Remove everything and start a new project"),
            MenuItem("&Import DXF...", self.fileImport, QKeySequence("Ctrl+L"), "Load a drawing file into the current project"),
            None,
            MenuItem("&Open project...", self.fileOpen, QKeySequence.Open, "Open a project file"),
            MenuItem("&Save project", self.fileSave, QKeySequence.Save, "Save a project file", allow_in_editor=True),
            MenuItem("Save project &as...", self.fileSaveAs, QKeySequence.SaveAs, "Save a project file under a different name", allow_in_editor=True),
            None,
            MenuItem("&Export G-Code...", self.fileExportGcode, QKeySequence("Ctrl+G"), "Generate and export the G-Code"),
            None,
            MenuItem("E&xit", self.fileExit, QKeySequence.Quit, "Quit application", allow_in_editor=True),
        ])
        self.mruActions = []
        self.exitAction = self.fileMenu.actions()[-1]
        self.editMenu = self.addMenu("&Edit", [
            addShortcut(self.document.undoStack.createUndoAction(self), QKeySequence("Ctrl+Z")),
            addShortcut(self.document.undoStack.createRedoAction(self), QKeySequence("Ctrl+Y")),
            None,
            MenuItem("Cu&t", self.editCut, QKeySequence("Ctrl+X"), "Cut drawing objects to clipboard", enable_func=self.isGeometrySelected),
            MenuItem("&Copy", self.editCopy, QKeySequence("Ctrl+C"), "Copy drawing objects to clipboard", enable_func=self.isGeometrySelected),
            MenuItem("&Paste", self.editPaste, QKeySequence("Ctrl+V"), "Paste drawing objects from clipboard", enable_func=self.isClipboardNonEmpty),
            None,
            MenuItem("&Join lines", self.editJoin, None, "Join line segments or polylines end to end", enable_func=lambda: self.isOpenGeometrySelected(2)),
            MenuItem("&Delete", self.editDelete, QKeySequence.Delete, "Delete the selected item"),
            None,
            MenuItem("P&references...", self.editPreferences, None, "Set application preferences"),
        ])
        self.drawMenu = self.addMenu("&Draw", [
            MenuItem("&Circle", self.drawCircle, None, "Add a circle to the drawing"),
            MenuItem("&Rectangle", self.drawRectangle, None, "Add a rectangle to the drawing"),
            MenuItem("&Polyline", self.drawPolyline, None, "Add a polyline to the drawing"),
            MenuItem("&Text", self.drawText, None, "Add a text to the drawing"),
            None,
            MenuItem("&Set origin", self.drawSetOrigin, None, "Set the origin point of the drawing"),
        ])
        self.operationsMenu = self.addMenu("&Machining", [
            MenuItem("&Add tool/preset...", lambda: self.millAddTool(), QKeySequence("Ctrl+T"), "Import cutters and cutting parameters from the inventory to the project"),
            MenuItem("&Wall profiles...", lambda: self.millWallProfiles(), QKeySequence("Shift+Ctrl+W"), "Create, edit and delete wall profile shapes"),
            None,
            MenuItem("&Outside contour", self.millOutsideContour, QKeySequence("Ctrl+E"), "Mill the outline of a shape as a slotting cut on the outside (part)"),
            MenuItem("&Inside contour", self.millInsideContour, QKeySequence("Ctrl+I"), "Mill the outline of a shape as a slotting cut the inside (cutout)"),
            MenuItem("&Pocket", self.millPocket, QKeySequence("Ctrl+K"), "Mill a pocket"),
            MenuItem("&Face mill", self.millFace, QKeySequence("Shift+Ctrl+F"), "Face-mill (flatten) the top surface only, without refining side edges"),
            MenuItem("&Side mill", self.millOutsidePeel, QKeySequence("Shift+Ctrl+E"), "Create the part by side milling from the outer edges of the part, leaving islands as the final shape"),
            MenuItem("&Engrave", self.millEngrave, QKeySequence("Ctrl+M"), "Follow a line without an offset"),
            MenuItem("&V-carve", self.millVCarve, QKeySequence("Shift+Ctrl+R"), "Use a v-bit at a variable depth of cut to engrave a contour"),
            MenuItem("Pa&ttern fill", self.millPatternFill, QKeySequence("Shift+Ctrl+T"), "Engrave a pattern in a closed shape"),
            MenuItem("Interpolated &hole", self.millInterpolatedHole, QKeySequence("Ctrl+H"), "Mill a circular hole wider than the endmill size using helical interpolation"),
            MenuItem("Internal t&hread", self.millInternalThread, QKeySequence("Shift+Ctrl+H"), "Mill an internal thread in an existing hole using a thread cutter"),
            MenuItem("&Refine", self.millRefine, QKeySequence("Shift+Ctrl+K"), "Mill finer details remaining from a cut with a larger diameter tool"),
            None,
            MenuItem("&Drilled hole", self.drillHole, QKeySequence("Ctrl+B"), "Drill a circular hole with a twist drill bit"),
        ])
        self.helpMenu = self.addMenu("&Help", [
            MenuItem("&About...", lambda: self.helpAbout(), None, "Display project information"),
        ])
        self.coordLabel = QLabel("")
        self.statusBar().addPermanentWidget(self.coordLabel)
        self.viewer.coordsUpdated.connect(self.canvasMouseMove)
        self.viewer.coordsInvalid.connect(self.canvasMouseLeave)
        self.viewer.selectionChanged.connect(self.viewerSelectionChanged)
        self.updateOperations()
        self.updateWindowTitle()
        self.updateFileMenu()
        self.refreshNeeded = False
        self.resetCAMNeeded()
        self.idleTimer = self.startTimer(500)
    def updateFileMenu(self):
        def fileAction(id, filename):
            action = QAction(f"&{id + 1} {filename}", self.fileMenu)
            action.triggered.connect(lambda checked: self.loadProjectIf(filename))
            self.actionData[action] = MenuItem(None, None, None, None, allow_in_editor=False)
            return action
        sep = QAction(self.fileMenu)
        sep.setSeparator(True)
        if self.mruList:
            actions = [fileAction(i, filename) for i, filename in enumerate(self.mruList)] + [sep]
        else:
            actions = []
        while self.mruActions:
            action = self.mruActions.pop()
            if action in self.actionData:
                del self.actionData[action]
            self.fileMenu.removeAction(action)
        self.fileMenu.insertActions(self.exitAction, actions)
        self.mruActions = actions
    def cleanFlagChanged(self, clean):
        self.setWindowModified(not clean)
    def timerEvent(self, event):
        if event.timerId() == self.idleTimer:
            self.doRefreshNow()
            return
        QMainWindow.timerEvent(self, event)
    def doRefreshNow(self):
        progress = self.document.pollForUpdateCAM()
        if (progress is not None and progress > 0) or (progress is None and self.lastProgress is not None):
            self.viewer.repaint()
        self.lastProgress = progress
        if self.refreshNeeded:
            self.viewer.majorUpdate(reset_zoom=self.resetZoomNeeded)
            self.resetZoomNeeded = False
            self.refreshNeeded = False
        if self.newCAMNeeded:
            subset = list(self.newCAMNeeded)
            self.resetCAMNeeded()
            self.document.startUpdateCAM(subset)
    def resetCAMNeeded(self):
        self.newCAMNeeded = set()
    def scheduleCAMUpdate(self, item):
        self.newCAMNeeded |= item
        for i in item:
            if isinstance(i, model.OperationTreeItem):
                i.resetRenderedState()
    def noOperationTouched(self):
        self.viewer.flashHighlight(None)
    def operationTouched(self, item):
        if isinstance(item, model.OperationTreeItem):
            self.viewer.flashHighlight(item)
        else:
            self.viewer.flashHighlight(None)
    def isGeometrySelected(self):
        selType, items = self.projectDW.activeSelection()
        return selType == 's' and len(items) > 0
    def isOpenGeometrySelected(self, min_size):
        selType, items = self.projectDW.activeSelection()
        return selType == 's' and len([i for i in items if isinstance(i, model.DrawingPolylineTreeItem) and not i.closed]) >= min_size
    def isClipboardNonEmpty(self):
        clipboard = QApplication.instance().clipboard()
        mime_data = clipboard.mimeData()
        return mime_data is not None and mime_data.hasFormat("application/x-derpcam-geometry")
    def millAddTool(self):
        self.millSelectTool(dlg_type=cutter_mgr.AddCutterDialog)
    def millWallProfiles(self):
        mgr = wall_profile_mgr.WallProfileManagerDlg(self, self.document)
        if mgr.exec_():
            self.document.opLoadWallProfile(mgr.currentProfile())
    def millSelectTool(self, cutter_type=None, dlg_type=cutter_mgr.SelectCutterDialog):
        if not cutter_mgr.selectCutter(self, dlg_type, self.document, cutter_type):
            return False
        cycle = self.document.current_cutter_cycle
        cutter = cycle.cutter
        self.projectDW.shapeTree.expand(self.document.itemForCutter(cutter).index())
        self.projectDW.operTree.selectionModel().reset()
        self.projectDW.operTree.selectionModel().setCurrentIndex(cycle.index(), QItemSelectionModel.SelectCurrent)
        return True
    def onEditorApplyClicked(self):
        if isinstance(self.viewer.editor, editors.CanvasCopyEditor):
            self.onEditCopyApplyClicked(self.viewer.editor)
        elif isinstance(self.viewer.editor, editors.CanvasPasteEditor):
            self.onEditPasteApplyClicked(self.viewer.editor)
        self.viewer.applyClicked()
    def onEditCopyApplyClicked(self, editor):
        point = editor.mouse_point
        selType, items = self.projectDW.activeSelection()
        clipboard = QApplication.instance().clipboard()
        data = ((point.x + self.document.drawing.x_offset, point.y + self.document.drawing.y_offset), [i.store() for i in items])
        mime_data = QMimeData()
        mime_data.setData("application/x-derpcam-geometry", json.dumps(data).encode("utf-8"))
        clipboard.setMimeData(mime_data)
        if self.copyIsCut:
            self.document.opDeleteDrawingItems(items)
        self.copyIsCut = None
    def onEditPasteApplyClicked(self, editor):
        origin, items_json = self.clipboard
        paste_point = editor.mouse_point
        dx = paste_point.x - origin.x
        dy = paste_point.y - origin.y
        items = [model.DrawingItemTreeItem.load(self.document, item_json).translated(dx, dy).reset_untransformed() for item_json in items_json]
        self.document.opAddDrawingItems(items)
    def onDrawingItemDoubleClicked(self, item):
        if isinstance(item, model.DrawingPolylineTreeItem):
            self.projectDW.shapeEdit(item)
    def onInputDoubleClicked(self, itemModel):
        selType, items = self.projectDW.activeSelection()
        if selType == 's' and len(items) == 1:
            self.onDrawingItemDoubleClicked(items[0])
    def onShapesCreated(self, shapes):
        self.projectDW.updateShapeSelection(shapes)
        self.projectDW.selectTab(0)
    def onShapesDeleted(self, shapes):
        if self.viewer.editor is not None:
            self.viewer.editor.onShapesDeleted(shapes)
    def onShapesUpdated(self):
        self.scheduleMajorRedraw()
        self.doRefreshNow()
        self.updateSelection()
    def onOperationsUpdated(self):
        self.refreshNeeded = True
    def updateOperations(self):
        self.scheduleMajorRedraw()
        #self.projectDW.updateFromOperations(self.viewer.operations)
        self.updateSelection()
    def viewerSelectionChanged(self):
        self.projectDW.updateShapeSelection(self.viewer.selection)
    def shapeTreeSelectionChanged(self):
        self.updateSelection()
        if self.document.setOperSelection(self.projectDW.operSelection()):
            self.viewer.repaint()
    def scheduleMajorRedraw(self, resetZoomNeeded=False):
        self.refreshNeeded = True
        self.resetZoomNeeded = self.resetZoomNeeded or resetZoomNeeded
    def itemPropertyChanged(self, item, name):
        if isinstance(item, (model.ToolTreeItem, model.ToolPresetTreeItem, model.WorkpieceTreeItem, model.DrawingItemTreeItem)):
            item.emitDataChanged()
        self.propsDW.updatePropertiesFor(item.invalidatedObjects(model.InvalidateAspect.PROPERTIES))
        ## Do not re-zoom when tools or presets updated, not much risk of things going off-screen etc.
        self.scheduleMajorRedraw(not isinstance(item, (model.ToolTreeItem, model.ToolPresetTreeItem)))
        self.scheduleCAMUpdate(item.invalidatedObjects(model.InvalidateAspect.CAM))
    def operInserted(self):
        self.scheduleMajorRedraw()
    def operRemoved(self):
        self.scheduleMajorRedraw()
    def switchToEditor(self, editor):
        oldEnabled = self.propsDW.isEnabled()
        self.projectDW.setVisible(editor is None)
        self.propsDW.setVisible(editor is None)
        if editor is None:
            self.propsDW.updateProperties()
        self.editorDW.setEditor(editor, self.viewer)
        self.viewer.setEditor(editor)
        if editor is None and not oldEnabled:
            self.propsDW.propsheet.setFocus()
        elif editor is not None:
            self.viewer.setFocus()
    def updateShapeSelection(self):
        # Update preview regardless
        items = self.projectDW.shapeSelection()
        self.viewer.setSelection([item for item in items if isinstance(item, model.DrawingItemTreeItem)])
        # Update property sheet only if the inputs tab is active
        selType, items = self.projectDW.activeSelection()
        if selType == 's':
            self.propsDW.setSelection(items)
    def updateSelection(self):
        selType, items = self.projectDW.activeSelection()
        if selType == 's':
            self.updateShapeSelection()
        else:
            self.propsDW.setSelection(items)
    def editDelete(self):
        try:
            selType, items = self.projectDW.activeSelection()
            if selType == 's':
                self.document.opDeleteDrawingItems(items)
            else:
                self.projectDW.operationDelete()
        except Exception as e:
            QMessageBox.critical(self, None, str(e))
    def editCut(self):
        self.copyIsCut = True
        selType, items = self.projectDW.activeSelection()
        if selType == 's' and items:
            self.switchToEditor(editors.CanvasCopyEditor(self.document))
    def editCopy(self):
        self.copyIsCut = False
        selType, items = self.projectDW.activeSelection()
        if selType == 's' and items:
            self.switchToEditor(editors.CanvasCopyEditor(self.document))
    def editPaste(self):
        clipboard = QApplication.instance().clipboard()
        mime_data = clipboard.mimeData()
        if not mime_data or not mime_data.hasFormat("application/x-derpcam-geometry"):
            return
        data = json.loads(mime_data.data("application/x-derpcam-geometry").data().decode("utf-8"))
        origin = geom.PathPoint(data[0][0] - self.document.drawing.x_offset, data[0][1] - self.document.drawing.y_offset)
        items_json = data[1]
        self.clipboard = (origin, items_json)
        self.switchToEditor(editors.CanvasPasteEditor(self.document, self.clipboard))
    def editJoin(self):
        self.projectDW.shapeJoin()
    def editPreferences(self):
        dlg = settings.PreferencesDialog(self, self.configSettings)
        self.prefDlg = dlg
        dlg.initUI()
        if dlg.exec():
            self.configSettings.update()
            self.document.startUpdateCAM()
            self.viewer.renderDrawing()
            self.viewer.repaint()
            #self.viewer.majorUpdate()
            self.configSettings.save()
    def drawCircle(self):
        if True:
            self.switchToEditor(editors.CanvasNewCircleEditor(self.document))
        else:
            dlg = draw.DrawCircleDialog(self, self.document)
            if dlg.exec():
                self.document.opAddDrawingItems([dlg.result])
                self.scheduleMajorRedraw(True)
    def drawRectangle(self):
        if True:
            self.switchToEditor(editors.CanvasNewRectangleEditor(self.document))
        else:
            dlg = draw.DrawRectangleDialog(self, self.document)
            if dlg.exec():
                self.document.opAddDrawingItems([dlg.result])
                self.scheduleMajorRedraw(True)
    def drawPolyline(self):
        polyline = model.DrawingPolylineTreeItem(self.document, [], False)
        cancel_index = self.document.undoStack.index()
        self.document.addShapesFromEditor([polyline])
        self.switchToEditor(editors.CanvasNewPolylineEditor(polyline, cancel_index))
    def drawText(self):
        self.switchToEditor(editors.CanvasNewTextEditor(self.document))
    def drawSetOrigin(self):
        self.switchToEditor(editors.CanvasSetOriginEditor(self.document))
    def millSelectedShapes(self, operType):
        selection = self.viewer.selection
        anyLeft = False
        shapeIds = []
        if not selection:
            QMessageBox.critical(self, None, "No objects selected")
            return
        shapeIds, selectionsUsed, warningsList = self.document.drawing.parseSelection(selection, operType)
        warningsText = "\n".join(warningsList)
        if not shapeIds:
            QMessageBox.warning(self, None, f"None of the selected objects are suitable for the operation:\n{warningsText}")
            return
        if not self.needCutterType(model.cutterTypesForOperationType(operType)):
            return
        shapeIds = canvas.sortSelections(selectionsUsed, shapeIds)
        for i in selectionsUsed:
            self.projectDW.shapeTree.selectionModel().select(i.index(), QItemSelectionModel.Deselect)
        rowCount, cycle, operations = self.document.opCreateOperation(shapeIds, operType)
        # The logic behind this is a bit iffy
        if len(selection) - len(selectionsUsed):
            self.projectDW.selectTab(self.projectDW.OPERATIONS_TAB)
            newSelection = QItemSelection()
            for index in operations:
                newSelection.select(index, index)
            self.projectDW.operTree.selectionModel().select(newSelection, QItemSelectionModel.ClearAndSelect)
            if rowCount:
                if len(newSelection.indexes()):
                    self.projectDW.operTree.scrollTo(newSelection.indexes()[0])
            QMessageBox.warning(self, None, f"Some objects did not match the operation:\n{warningsText}")
        self.updateOperations()
        self.updateShapeSelection()
        self.propsDW.updateProperties()
    def needCutterType(self, cutter_type):
        if not self.millSelectTool(cutter_type=cutter_type):
            return False
        if not self.document.current_cutter_cycle:
            QMessageBox.critical(self, None, "No tool selected")
            return False
        return True
    def millOutsideContour(self):
        self.millSelectedShapes(OperationType.OUTSIDE_CONTOUR)
    def millInsideContour(self):
        self.millSelectedShapes(OperationType.INSIDE_CONTOUR)
    def millPocket(self):
        self.millSelectedShapes(OperationType.POCKET)
    def millFace(self):
        self.millSelectedShapes(OperationType.FACE)
    def millOutsidePeel(self):
        self.millSelectedShapes(OperationType.SIDE_MILL)
    def millEngrave(self):
        self.millSelectedShapes(OperationType.ENGRAVE)
    def millVCarve(self):
        self.millSelectedShapes(OperationType.V_CARVE)
    def millPatternFill(self):
        self.millSelectedShapes(OperationType.PATTERN_FILL)
    def millInterpolatedHole(self):
        self.millSelectedShapes(OperationType.INTERPOLATED_HOLE)
    def millInternalThread(self):
        self.millSelectedShapes(OperationType.INSIDE_THREAD)
    def millRefine(self):
        self.millSelectedShapes(OperationType.REFINE)
    def drillHole(self):
        self.millSelectedShapes(OperationType.DRILLED_HOLE)
    def helpAbout(self):
        dlg = about.AboutDlg()
        dlg.initUI()
        dlg.exec_()
    def canvasMouseMove(self, x, y):
        Format = guiutils.Format
        self.coordLabel.setText(f"X={Format.coord(x, brief=True)}{Format.coord_unit()} Y={Format.coord(y, brief=True)}{Format.coord_unit()}")
    def canvasMouseLeave(self):
        self.coordLabel.setText("")
    def updateWindowTitle(self):
        filename = self.document.filename or self.document.drawing_filename
        if filename is not None:
            self.setWindowFilePath(filename)
        else:
            self.setWindowFilePath("unnamed project")
    def onDrawingImportedOrProjectLoaded(self):
        self.updateWindowTitle()
        self.viewer.majorUpdate()
        self.updateSelection()
        self.projectDW.shapeTree.expandAll()
        self.projectDW.operTree.expandAll()
    def loadProjectIf(self, fn):
        if not self.handleUnsaved():
            return
        self.loadProject(fn)
    def addToMru(self, fn):
        self.mruList = [i for i in self.mruList if i != fn]
        self.mruList.insert(0, fn)
        self.configSettings.saveMru(self.mruList)
    def loadProject(self, fn):
        self.viewer.abortEditMode()
        self.document.loadProject(fn)
        self.addToMru(fn)
        self.updateFileMenu()
        self.resetCAMNeeded()
    def saveProject(self, fn):
        data = self.document.store()
        f = open(fn, "w")
        json.dump(data, f, indent=2)
        f.close()
        self.addToMru(fn)
    def fileNew(self):
        if not self.handleUnsaved():
            return
        self.viewer.abortEditMode()
        self.document.newDocument()
    def fileImport(self):
        self.viewer.abortEditMode()
        dlg = QFileDialog(self, "Import a drawing", filter="Drawings (*.dxf);;All files (*)")
        input_dir = self.configSettings.input_directory or self.configSettings.last_input_directory
        if input_dir:
            dlg.setDirectory(input_dir)
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            try:
                self.document.importDrawing(fn)
            except Exception as e:
                QMessageBox.critical(self, None, "Cannot import a drawing: " + str(e))
            self.document.undoStack.resetClean()
            self.configSettings.last_input_directory = os.path.split(fn)[0]
            self.configSettings.save()
    def fileOpen(self):
        self.viewer.abortEditMode()
        dlg = QFileDialog(self, "Open a project", filter="DerpCAM project (*.dcp);;All files (*)")
        input_dir = self.configSettings.input_directory or self.configSettings.last_input_directory
        if input_dir:
            dlg.setDirectory(input_dir)
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.loadProject(fn)
            self.configSettings.last_input_directory = os.path.split(fn)[0]
            self.configSettings.save()
    def fileSaveAs(self):
        dlg = QFileDialog(self, "Save a project", filter="DerpCAM project (*.dcp);;All files (*)")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setFileMode(QFileDialog.AnyFile)
        dlg.setDefaultSuffix(".dcp")
        if self.document.drawing_filename is not None:
            path = os.path.splitext(self.document.drawing_filename)[0] + ".dcp"
            dlg.selectFile(path)
        else:
            input_dir = self.configSettings.input_directory or self.configSettings.last_input_directory
            if input_dir:
                dlg.setDirectory(input_dir)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.document.filename = fn
            self.saveProject(fn)
            self.setWindowFilePath(fn)
            self.document.undoStack.setClean()
            return True
        return False
    def fileSave(self):
        if self.document.filename is None:
            return self.fileSaveAs()
        else:
            self.saveProject(self.document.filename)
            self.document.undoStack.setClean()
            return True
    def fileExportGcode(self):
        try:
            self.document.validateForOutput()
        except ValueError as e:
            QMessageBox.critical(self, None, str(e))
            return
        with guiutils.Spinner():
            self.document.startUpdateCAM()
            if not self.document.waitForUpdateCAM():
                return
        dlg = QFileDialog(self, "Export the G-Code", filter="G-Code (*.ngc);;All files (*)")
        if self.document.drawing_filename:
            path = os.path.splitext(self.document.drawing_filename)[0] + ".ngc"
        elif self.document.filename:
            path = os.path.splitext(self.document.filename)[0] + ".ngc"
        else:
            path = ''
        output_dir = self.configSettings.gcode_directory or self.configSettings.last_gcode_directory
        if output_dir != '':
            old_path, gcode_filename = os.path.split(path)
            path = os.path.join(output_dir, gcode_filename)
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setFileMode(QFileDialog.AnyFile)
        dlg.setDefaultSuffix(".ngc")
        dlg.selectFile(path)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.document.exportGcode(fn)
            self.configSettings.last_gcode_directory = os.path.split(fn)[0]
            self.configSettings.save()
            dlg = None
            self.repaint()
            os.system(self.configSettings.run_after_export + " '" + os.path.abspath(fn) + "'")
    def fileExit(self):
        self.close()
    def handleUnsaved(self):
        if not self.document.undoStack.isClean():
            answer = QMessageBox.question(self, "Unsaved changes", "Project has unsaved changes. Save?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                return False
            if answer == QMessageBox.Save:
                return self.fileSave()
        return True
    def closeEvent(self, e):
        if not self.handleUnsaved():
            e.ignore()
            return
        QWidget.closeEvent(self, e)

