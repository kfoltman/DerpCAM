import argparse
import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

import process
import gcodegen
import view
from gui import propsheet, settings, canvas, model, inventory, dock, cutter_mgr
import json

OperationType = model.OperationType

class CAMMainWindow(QMainWindow):
    def __init__(self, document, config):
        QMainWindow.__init__(self)
        self.document = document
        self.configSettings = config
    def addMenu(self, menuLabel, actions):
        menu = self.menuBar().addMenu(menuLabel)
        for i in actions:
            if i is None:
                menu.addSeparator()
            elif isinstance(i, QAction):
                menu.addAction(i)
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
        def addShortcut(action, shortcut):
            action.setShortcuts(shortcut)
            return action
        self.viewer = canvas.DrawingViewer(self.document, self.configSettings)
        self.viewer.initUI()
        self.viewer.modeChanged.connect(self.operationEditMode)
        self.setCentralWidget(self.viewer)
        self.projectDW = dock.CAMObjectTreeDockWidget(self.document)
        self.projectDW.selectionChanged.connect(self.shapeTreeSelectionChanged)
        self.projectDW.modeChanged.connect(self.operationEditMode)
        self.addDockWidget(Qt.RightDockWidgetArea, self.projectDW)
        self.propsDW = dock.CAMPropertiesDockWidget(self.document)
        self.document.undoStack.cleanChanged.connect(self.cleanFlagChanged)
        self.document.shapeModel.dataChanged.connect(self.shapeModelChanged)
        self.document.operModel.dataChanged.connect(self.operChanged)
        self.document.operModel.rowsInserted.connect(self.operInserted)
        self.document.operModel.rowsRemoved.connect(self.operRemoved)
        self.document.operationsUpdated.connect(self.onOperationsUpdated)
        self.document.tabEditRequested.connect(self.projectDW.operationHoldingTabs)
        self.document.islandsEditRequested.connect(self.projectDW.operationIslands)
        self.document.toolListRefreshed.connect(self.projectDW.onToolListRefreshed)
        self.document.cutterSelected.connect(self.projectDW.onCutterSelected)
        self.document.drawingImported.connect(self.onDrawingImportedOrProjectLoaded)
        self.document.projectLoaded.connect(self.onDrawingImportedOrProjectLoaded)
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
        self.editMenu = self.addMenu("&Edit", [
            addShortcut(self.document.undoStack.createUndoAction(self), QKeySequence("Ctrl+Z")),
            addShortcut(self.document.undoStack.createRedoAction(self), QKeySequence("Ctrl+Y")),
            None,
            ("&Delete", self.editDelete, QKeySequence.Delete, "Delete an item"),
            None,
            ("&Preferences...", self.editPreferences, None, "Set application preferences"),
        ])
        self.operationsMenu = self.addMenu("&Machining", [
            ("&Add tool/preset...", lambda: self.millAddTool(), QKeySequence("Ctrl+T"), "Import cutters and cutting parameters from the inventory to the project"),
            None,
            ("&Outside contour", self.millOutsideContour, QKeySequence("Ctrl+E"), "Mill the outline of a shape as a slotting cut on the outside (part)"),
            ("&Inside contour", self.millInsideContour, QKeySequence("Ctrl+I"), "Mill the outline of a shape as a slotting cut the inside (cutout)"),
            ("&Pocket", self.millPocket, QKeySequence("Ctrl+K"), "Mill a pocket"),
            ("&Engrave", self.millEngrave, QKeySequence("Ctrl+M"), "Follow a line without an offset"),
            ("Interpolated &hole", self.millInterpolatedHole, QKeySequence("Ctrl+H"), "Mill a circular hole wider than the endmill size using helical interpolation"),
            ("Out&side peel", self.millOutsidePeel, QKeySequence("Shift+Ctrl+E"), "Create the part by side milling on the outside of the part"),
            None,
            ("&Drilled hole", self.drillHole, QKeySequence("Ctrl+B"), "Drill a circular hole with a twist drill bit"),
        ])
        self.coordLabel = QLabel("")
        self.statusBar().addPermanentWidget(self.coordLabel)
        self.viewer.coordsUpdated.connect(self.canvasMouseMove)
        self.viewer.coordsInvalid.connect(self.canvasMouseLeave)
        self.viewer.selectionChanged.connect(self.viewerSelectionChanged)
        self.projectDW.operationTouched.connect(self.operationTouched)
        self.projectDW.noOperationTouched.connect(self.noOperationTouched)
        self.updateOperations()
        filename = self.document.filename or self.document.drawing_filename
        if filename:
            self.setWindowFilePath(filename)
        else:
            self.setWindowFilePath("unnamed project")
        self.refreshNeeded = False
        self.resetZoomNeeded = False
        self.idleTimer = self.startTimer(100)
    def cleanFlagChanged(self, clean):
        self.setWindowModified(not clean)
    def timerEvent(self, event):
        if event.timerId() == self.idleTimer:
            progress = self.document.pollForUpdateCAM()
            if progress is not None and progress > 0:
                self.viewer.repaint()
            if self.refreshNeeded:
                self.viewer.majorUpdate(reset_zoom=self.resetZoomNeeded)
                self.refreshNeeded = False
            return
        QMainWindow.timerEvent(self, event)
    def noOperationTouched(self):
        self.viewer.flashHighlight(None)
    def operationTouched(self, item):
        if isinstance(item, model.OperationTreeItem):
            self.viewer.flashHighlight(item)
    def millAddTool(self):
        self.millSelectTool(dlg_type=cutter_mgr.AddCutterDialog)
    def millSelectTool(self, cutter_type=None, dlg_type=cutter_mgr.SelectCutterDialog):
        if not cutter_mgr.selectCutter(self, dlg_type, self.document, cutter_type):
            return False
        cycle = self.document.current_cutter_cycle
        cutter = cycle.cutter
        self.projectDW.shapeTree.expand(self.document.itemForCutter(cutter).index())
        self.projectDW.operTree.selectionModel().reset()
        self.projectDW.operTree.selectionModel().setCurrentIndex(cycle.index(), QItemSelectionModel.SelectCurrent)
        return True
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
    def shapeModelChanged(self, index):
        item = self.document.shapeModel.itemFromIndex(index)
        if type(item) == model.WorkpieceTreeItem:
            self.materialChanged()
        elif type(item) == model.ToolTreeItem:
            self.toolChanged()
        elif type(item) == model.ToolPresetTreeItem:
            self.toolPresetChanged()
        elif type(item) == model.DrawingTreeItem or isinstance(item, model.DrawingItemTreeItem):
            self.drawingChanged()
        self.propsDW.updatePropertiesFor(item)
    def scheduleMajorRedraw(self):
        self.refreshNeeded = True
        self.resetZoomNeeded = True
    def materialChanged(self):
        self.propsDW.updateProperties()
        self.document.startUpdateCAM()
        self.scheduleMajorRedraw()
    def toolChanged(self):
        self.propsDW.updateProperties()
        self.document.startUpdateCAM()
        self.scheduleMajorRedraw()
    def toolPresetChanged(self):
        self.propsDW.updateProperties()
        self.scheduleMajorRedraw()
    def drawingChanged(self):
        self.document.startUpdateCAM()
        self.scheduleMajorRedraw()
    def operChanged(self):
        self.propsDW.updateProperties()
        self.scheduleMajorRedraw()
    def operInserted(self):
        self.scheduleMajorRedraw()
    def operRemoved(self):
        self.scheduleMajorRedraw()
    def operationEditMode(self, mode):
        oldEnabled = self.propsDW.isEnabled()
        selectedOp = self.projectDW.operSelection()[0]
        if mode == canvas.DrawingUIMode.MODE_ISLANDS and not selectedOp.areIslandsEditable():
            QMessageBox.critical(self, None, "Cannot edit islands on text - they are determined based on the holes in glyphs")
            return
        self.projectDW.setEnabled(mode == canvas.DrawingUIMode.MODE_NORMAL)
        self.propsDW.setEnabled(mode == canvas.DrawingUIMode.MODE_NORMAL)
        self.viewer.changeMode(mode, selectedOp)
        if mode == canvas.DrawingUIMode.MODE_NORMAL and not oldEnabled:
            self.propsDW.propsheet.setFocus()
        elif mode != canvas.DrawingUIMode.MODE_NORMAL:
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
        self.projectDW.operationDelete()
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
    def millOutsidePeel(self):
        self.millSelectedShapes(OperationType.OUTSIDE_PEEL)
    def millEngrave(self):
        self.millSelectedShapes(OperationType.ENGRAVE)
    def millInterpolatedHole(self):
        self.millSelectedShapes(OperationType.INTERPOLATED_HOLE)
    def drillHole(self):
        self.millSelectedShapes(OperationType.DRILLED_HOLE)
    def canvasMouseMove(self, x, y):
        self.coordLabel.setText("X=%0.2f Y=%0.2f" % (x, y))
    def canvasMouseLeave(self):
        self.coordLabel.setText("")
    def onDrawingImportedOrProjectLoaded(self, fn):
        self.setWindowFilePath(fn)
        self.viewer.majorUpdate()
        self.updateSelection()
        self.projectDW.shapeTree.expandAll()
        self.projectDW.operTree.expandAll()
    def loadProject(self, fn):
        self.document.loadProject(fn)
    def saveProject(self, fn):
        data = self.document.store()
        f = open(fn, "w")
        json.dump(data, f, indent=2)
        f.close()
    def fileImport(self):
        dlg = QFileDialog(self, "Import a drawing", filter="Drawings (*.dxf);;All files (*)")
        input_dir = self.configSettings.input_directory or self.configSettings.last_input_directory
        if input_dir:
            dlg.setDirectory(input_dir)
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fn = dlg.selectedFiles()[0]
            self.document.importDrawing(fn)
            self.configSettings.last_input_directory = os.path.split(fn)[0]
            self.configSettings.save()
    def fileOpen(self):
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
        if self.document.drawing_filename is not None:
            path = os.path.splitext(self.document.drawing_filename)[0] + ".dcp"
            dlg.selectFile(path)
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
        with view.Spinner():
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
    def fileExit(self):
        self.close()
    def closeEvent(self, e):
        if not self.document.undoStack.isClean():
            answer = QMessageBox.question(self, "Unsaved changes", "Project has unsaved changes. Save?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                e.ignore()
                return
            if answer == QMessageBox.Discard:
                return
            if answer == QMessageBox.Save:
                self.fileSave()
                return
        QWidget.closeEvent(self, e)

