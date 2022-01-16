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
from gui import propsheet, settings, canvas, model, inventory
from gui.cutter_mgr import SelectCutterDialog, AddPresetDialog, CreateCutterDialog, loadInventory, saveInventory
import ezdxf
import json
from typing import Optional

OperationType = model.OperationType
document = model.DocumentModel()
OperationType = model.OperationType

class TreeViewWithAltArrows(QTreeView):
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Down or event.key() == Qt.Key_Up) and (event.modifiers() & Qt.AltModifier) == Qt.AltModifier:
            event.setAccepted(False)
        else:
            return QTreeView.keyPressEvent(self, event)

class CAMObjectTreeDockWidget(QDockWidget):
    selectionChanged = pyqtSignal([])
    modeChanged = pyqtSignal([int])
    INPUTS_TAB = 0
    OPERATIONS_TAB = 1
    def __init__(self, document):
        QDockWidget.__init__(self, "Project content")
        self.document = document
        self.setFeatures(self.features() & ~QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        # screen() is Qt 5.14 and up
        if hasattr(self, 'screen'):
            screen_width = self.screen().size().width()
            self.setMinimumSize(max(300, screen_width // 4), 100)
        else:
            self.setMinimumSize(300, 100)
        self.tabs = QTabWidget()
        
        tree = TreeViewWithAltArrows()
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tree.setModel(self.document.shapeModel)
        tree.selectionModel().selectionChanged.connect(self.shapeSelectionChanged)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(self.customContextMenu)
        tree.expandAll()
        self.shapeTree = tree
        self.tabs.addTab(tree, "&Input")
        
        tree = TreeViewWithAltArrows()
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tree.setModel(self.document.operModel)
        tree.selectionModel().selectionChanged.connect(self.operationSelectionChanged)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(self.customContextMenu)
        self.operTree = tree
        self.tabs.addTab(tree, "&Operations")
        self.tabs.setTabPosition(QTabWidget.South)
        self.tabs.currentChanged.connect(self.tabSelectionChanged)
        self.setWidget(self.tabs)
    def onCutterChanged(self, cutter):
        self.shapeTree.repaint()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
            self.returnKeyPressed(self.activeSelection())
        elif (event.key() == Qt.Key_Down or event.key() == Qt.Key_Up) and (event.modifiers() & Qt.AltModifier) == Qt.AltModifier:
            self.altArrowPressed(self.activeSelection(), -1 if event.key() == Qt.Key_Up else +1)
        else:
            QDockWidget.keyPressEvent(self, event)
    def altArrowPressed(self, selection, direction):
        mode, items = selection
        if len(items) == 1:
            item = items[0]
            if hasattr(item, 'reorderItem'):
                index = item.reorderItem(direction)
                if index is None:
                    return
                tree = self.activeTree()
                tree.selectionModel().setCurrentIndex(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current)
                tree.selectionModel().select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current)
    def returnKeyPressed(self, selection):
        mode, items = selection
        if len(items) == 1:
            item = items[0]
            if hasattr(item, 'returnKeyPressed'):
                item.returnKeyPressed()
            return
        print (selection)
    def customContextMenu(self, point):
        mode, items = self.activeSelection()
        if len(items) != 1:
            return
        item = items[0]
        if mode == 's':
            point = self.shapeTree.mapToGlobal(point)
        else:
            point = self.operTree.mapToGlobal(point)
        menu = QMenu(self)
        if isinstance(item, model.OperationTreeItem):
            if item.operation == OperationType.OUTSIDE_CONTOUR or item.operation == OperationType.INSIDE_CONTOUR:
                menu.addAction("Holding tabs").triggered.connect(self.operationHoldingTabs)
            elif item.operation == OperationType.POCKET:
                menu.addAction("Islands").triggered.connect(self.operationIslands)
            else:
                return
        elif isinstance(item, model.CycleTreeItem):
            menu.addAction("Set as current").triggered.connect(lambda: self.cycleSetAsCurrent(item))
        elif isinstance(item, model.ToolPresetTreeItem):
            menu.addAction("Set as default").triggered.connect(lambda: self.toolPresetSetAsCurrent(item))
            action = menu.addAction("Save to inventory")
            action.triggered.connect(lambda: self.toolPresetSaveToInventory(item))
            action.setEnabled(item.isLocal() and not item.parent().isLocal())
            action = menu.addAction("Reload from inventory")
            action.triggered.connect(lambda: self.toolPresetRevertFromInventory(item))
            action.setEnabled(item.isModifiedStock())
        elif isinstance(item, model.ToolTreeItem):
            action = menu.addAction("Save to inventory")
            action.triggered.connect(lambda: self.toolSaveToInventory(item))
            action.setEnabled(item.isNewObject())
            action = menu.addAction("Update in inventory")
            action.triggered.connect(lambda: self.toolUpdateInInventory(item))
            action.setEnabled(item.isModifiedStock())
            action = menu.addAction("Reload from inventory")
            action.triggered.connect(lambda: self.toolRevertFromInventory(item))
            action.setEnabled(item.isModifiedStock())
        menu.exec_(point)
    def toolSaveToInventory(self, item):
        if not item.inventory_tool.base_object:
            tool_copy = item.inventory_tool.newInstance()
            tool_copy.presets = [i.newInstance() for i in item.inventory_tool.presets]
            for i in tool_copy.presets:
                i.toolbit = tool_copy
            inventory.inventory.toolbits.append(tool_copy)
            saveInventory()
            item.inventory_tool.base_object = tool_copy
            self.document.refreshToolList()
    def toolUpdateInInventory(self, item):
        if item.inventory_tool.base_object:
            item.inventory_tool.base_object.resetTo(item.inventory_tool)
            saveInventory()
            self.document.refreshToolList()
    def onToolListRefreshed(self):
        self.shapeTree.expandAll()
    def toolRevertFromInventory(self, item):
        # XXXKF undo
        if item.inventory_tool.base_object:
            item.inventory_tool.resetTo(item.inventory_tool.base_object)
            self.document.refreshToolList()
            self.shapeTree.expandAll()
    def toolPresetSetAsCurrent(self, item):
        self.document.selectPresetAsDefault(item.inventory_preset.toolbit, item.inventory_preset)
    def toolPresetRevertFromInventory(self, item):
        # XXXKF undo
        if item.inventory_preset.base_object:
            item.inventory_preset.resetTo(item.inventory_preset.base_object)
            item.inventory_preset.toolbit = item.parent().inventory_tool
            self.document.refreshToolList()
            self.shapeTree.expandAll()
    def toolPresetSaveToInventory(self, item):
        inv_toolbit = item.inventory_preset.toolbit.base_object
        if inv_toolbit is None:
            return
        inv_preset = inv_toolbit.presetByName(item.inventory_preset.name)
        if inv_preset is None:
            preset_copy = item.inventory_preset.newInstance()
            preset_copy.toolbit = inv_toolbit
            item.inventory_preset.base_object = preset_copy
            inv_toolbit.presets.append(preset_copy)
        else:
            inv_preset.resetTo(item.inventory_preset)
            inv_preset.toolbit = inv_toolbit
        saveInventory()
        self.document.refreshToolList()
        self.shapeTree.expandAll()
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
        if self.tabs.currentIndex() == 0:
            self.shapeTree.setFocus()
        elif self.tabs.currentIndex() == 1:
            self.operTree.setFocus()
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
    def activeTree(self):
        if self.tabs.currentIndex() == 0:
            return self.shapeTree
        if self.tabs.currentIndex() == 1:
            return self.operTree
        assert False
    def operationHoldingTabs(self):
        self.modeChanged.emit(canvas.DrawingUIMode.MODE_TABS)
    def operationIslands(self):
        self.modeChanged.emit(canvas.DrawingUIMode.MODE_ISLANDS)
    def cycleSetAsCurrent(self, item):
        self.document.selectCutterCycle(item)

class CAMPropertiesDockWidget(QDockWidget):
    def __init__(self, document):
        QDockWidget.__init__(self, "Properties")
        self.setFeatures(self.features() & ~QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumSize(400, 100)
        self.propsheet = propsheet.PropertySheetWidget([], document)
        self.setWidget(self.propsheet)
        self.updateModel()
    def updateModel(self):
        self.propsheet.setObjects([])
    def updateProperties(self):
        self.propsheet.refreshAll()
    def updatePropertiesFor(self, object):
        if object in self.propsheet.objects:
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
        self.configSettings = settings.ConfigSettings()
        self.configSettings.update()
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
        self.projectDW = CAMObjectTreeDockWidget(self.document)
        self.projectDW.selectionChanged.connect(self.shapeTreeSelectionChanged)
        self.projectDW.modeChanged.connect(self.operationEditMode)
        self.addDockWidget(Qt.RightDockWidgetArea, self.projectDW)
        self.propsDW = CAMPropertiesDockWidget(self.document)
        self.document.shapeModel.dataChanged.connect(self.shapeModelChanged)
        self.document.operModel.dataChanged.connect(self.operChanged)
        self.document.operModel.rowsInserted.connect(self.operInserted)
        self.document.operModel.rowsRemoved.connect(self.operRemoved)
        self.document.tabEditRequested.connect(self.projectDW.operationHoldingTabs)
        self.document.islandsEditRequested.connect(self.projectDW.operationIslands)
        self.document.toolListRefreshed.connect(self.projectDW.onToolListRefreshed)
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
            #("&Add tool...", lambda: self.millAddTool(), QKeySequence("Ctrl+T"), "Add a milling cutter or a drill bit to the project"),
            #None,
            ("&Outside contour", self.millOutsideContour, QKeySequence("Ctrl+E"), "Mill the outline of a shape from the outside (part)"),
            ("&Inside contour", self.millInsideContour, QKeySequence("Ctrl+I"), "Mill the outline of a shape from the inside (cutout)"),
            ("&Pocket", self.millPocket, QKeySequence("Ctrl+K"), "Mill a pocket"),
            ("&Engrave", self.millEngrave, QKeySequence("Ctrl+M"), "Follow a line without an offset"),
            ("Interpolated &hole", self.millInterpolatedHole, QKeySequence("Ctrl+H"), "Mill a circular hole wider than the endmill size using helical interpolation"),
            None,
            ("&Drilled hole", self.drillHole, QKeySequence("Ctrl+B"), "Drill a circular hole with a twist drill bit"),
        ])
        self.coordLabel = QLabel("")
        self.statusBar().addPermanentWidget(self.coordLabel)
        self.viewer.coordsUpdated.connect(self.canvasMouseMove)
        self.viewer.coordsInvalid.connect(self.canvasMouseLeave)
        self.viewer.selectionChanged.connect(self.viewerSelectionChanged)
        self.updateOperations()
    def millSelectTool(self, cutter_type=None):
        dlg = SelectCutterDialog(self, document=self.document, cutter_type=cutter_type)
        preset = None
        if dlg.exec_():
            if dlg.choice is Ellipsis:
                dlg = CreateCutterDialog(self)
                if dlg.exec_():
                    cutter = dlg.cutter
                    # inventory.inventory.toolbits.append(cutter)
                    # saveInventory()
                else:
                    return False
            else:
                if isinstance(dlg.choice, model.CycleTreeItem):
                    # project's tool/cycle
                    self.document.selectCutterCycle(dlg.choice)
                    self.document.selectPresetAsDefault(dlg.choice.cutter, None)
                    return True
                elif isinstance(dlg.choice, inventory.CutterBase):
                    # inventory tool
                    cutter = dlg.choice.newInstance()
                else:
                    assert isinstance(dlg.choice, tuple)
                    parent, parent_preset = dlg.choice
                    if isinstance(parent, model.CycleTreeItem):
                        # project's preset
                        self.document.selectCutterCycle(parent)
                        self.document.selectPresetAsDefault(parent.cutter, parent_preset)
                        return True
                    else:
                        cutter, preset, add = self.document.opAddLibraryPreset(parent_preset)
                        if not add:
                            if self.document.current_cutter_cycle.cutter is not cutter:
                                for i in self.document.allCycles():
                                    if i.cutter is cutter:
                                        self.document.selectCutterCycle(i)
                                        break
                            self.document.selectPresetAsDefault(cutter, preset)
                            self.projectDW.shapeTree.expand(self.document.itemForCutter(cutter).index())
                            return True
        else:
            return False
        cycle = self.document.opAddCutter(cutter)
        if preset:
            self.document.selectPresetAsDefault(cycle.cutter, preset)
        self.projectDW.shapeTree.expand(self.document.itemForCutter(cutter).index())
        self.projectDW.operTree.selectionModel().reset()
        self.projectDW.operTree.selectionModel().setCurrentIndex(cycle.index(), QItemSelectionModel.SelectCurrent)
        return True
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
        if type(item) == model.WorkpieceTreeItem:
            self.materialChanged()
        elif type(item) == model.ToolTreeItem:
            self.toolChanged()
        elif type(item) == model.DrawingTreeItem:
            self.drawingChanged()
        self.propsDW.updatePropertiesFor(item)
    def materialChanged(self):
        self.propsDW.updateProperties()
        self.document.updateCAM()
        self.viewer.majorUpdate()
    def toolChanged(self):
        self.propsDW.updateProperties()
        self.document.updateCAM()
        self.viewer.majorUpdate()
    def drawingChanged(self):
        self.document.updateCAM()
        self.viewer.majorUpdate()
    def operChanged(self):
        self.propsDW.updateProperties()
        self.viewer.majorUpdate()
    def operInserted(self):
        self.viewer.majorUpdate()
    def operRemoved(self):
        self.viewer.majorUpdate()
    def operationEditMode(self, mode):
        oldEnabled = self.propsDW.isEnabled()
        self.projectDW.setEnabled(mode == canvas.DrawingUIMode.MODE_NORMAL)
        self.propsDW.setEnabled(mode == canvas.DrawingUIMode.MODE_NORMAL)
        self.viewer.changeMode(mode, self.projectDW.operSelection()[0])
        if mode == canvas.DrawingUIMode.MODE_NORMAL and not oldEnabled:
            self.propsDW.propsheet.setFocus()
        elif mode != canvas.DrawingUIMode.MODE_NORMAL:
            self.viewer.setFocus()
    def updateSelection(self):
        selType, items = self.projectDW.activeSelection()
        if selType == 's':
            self.viewer.setSelection([item for item in items if isinstance(item, model.DrawingItemTreeItem)])
            self.propsDW.setSelection(items)
        else:
            self.propsDW.setSelection(items)
    def editDelete(self):
        selType, items = self.projectDW.activeSelection()
        if selType == 'o':
            self.document.opDeleteOperations(items)
    def editPreferences(self):
        dlg = settings.PreferencesDialog(self, self.configSettings)
        self.prefDlg = dlg
        dlg.initUI()
        if dlg.exec():
            self.configSettings.update()
            self.document.updateCAM()
            self.viewer.renderDrawing()
            self.viewer.repaint()
            #self.viewer.majorUpdate()
            self.configSettings.save()
    def millSelectedShapes(self, checkFunc, operType):
        selection = self.viewer.selection
        translation = self.document.drawing.translation()
        anyLeft = False
        shapeIds = []
        if not selection:
            QMessageBox.critical(self, None, "No objects selected")
            return
        if operType == OperationType.DRILLED_HOLE and not self.needDrillBit():
            return
        elif operType != OperationType.DRILLED_HOLE and not self.needEndMill():
            return
        for i in selection:
            shape = i.translated(*translation).toShape()
            if checkFunc(i, shape):
                shapeIds.append(i.shape_id)
                self.projectDW.shapeTree.selectionModel().select(i.index(), QItemSelectionModel.Deselect)
            else:
                anyLeft = True
        if not shapeIds:
            QMessageBox.warning(self, None, "No objects created")
            return
        rowCount, cycle, operations = self.document.opCreateOperation(shapeIds, operType)
        # The logic behind this is a bit iffy
        if not anyLeft:
            self.projectDW.selectTab(self.projectDW.OPERATIONS_TAB)
            newSelection = QItemSelection()
            for index in operations:
                newSelection.select(index, index)
            self.projectDW.operTree.selectionModel().select(newSelection, QItemSelectionModel.ClearAndSelect)
            if rowCount:
                if len(newSelection.indexes()):
                    self.projectDW.operTree.scrollTo(newSelection.indexes()[0])
        self.updateOperations()
        self.propsDW.updateProperties()
    def needEndMill(self):
        return self.needCutterType(inventory.EndMillCutter, "an end mill")
    def needDrillBit(self):
        return self.needCutterType(inventory.DrillBitCutter, "a drill bit")
    def needCutterType(self, cutter_type, name):
        if not self.millSelectTool(cutter_type=cutter_type):
            return False
        if not self.document.current_cutter_cycle:
            QMessageBox.critical(self, None, "No tool selected")
            return False
        if not isinstance(self.document.current_cutter_cycle.cutter, cutter_type):
            QMessageBox.critical(self, None, f"Current tool is not {name}")
            return False
        return True
    def millOutsideContour(self):
        self.millSelectedShapes(lambda item, shape: shape.closed, OperationType.OUTSIDE_CONTOUR)
    def millInsideContour(self):
        self.millSelectedShapes(lambda item, shape: shape.closed, OperationType.INSIDE_CONTOUR)
    def millPocket(self):
        self.millSelectedShapes(lambda item, shape: shape.closed, OperationType.POCKET)
    def millEngrave(self):
        self.millSelectedShapes(lambda item, shape: True, OperationType.ENGRAVE)
    def millInterpolatedHole(self):
        self.millSelectedShapes(lambda item, shape: isinstance(item, model.DrawingCircleTreeItem), OperationType.INTERPOLATED_HOLE)
    def drillHole(self):
        self.millSelectedShapes(lambda item, shape: isinstance(item, model.DrawingCircleTreeItem), OperationType.DRILLED_HOLE)
    def canvasMouseMove(self, x, y):
        self.coordLabel.setText("X=%0.2f Y=%0.2f" % (x, y))
    def canvasMouseLeave(self):
        self.coordLabel.setText("")
    def importDrawing(self, fn):
        self.document.importDrawing(fn)
        self.viewer.majorUpdate()
        self.updateSelection()
        self.setWindowFilePath(fn)
        self.projectDW.shapeTree.expandAll()
    def loadProject(self, fn):
        f = open(fn, "r")
        data = json.load(f)
        f.close()
        self.document.filename = fn
        self.document.drawingFilename = None
        self.document.load(data)
        self.drawingChanged()
        self.projectDW.shapeTree.expandAll()
        self.projectDW.operTree.expandAll()
        self.setWindowFilePath(fn)
    def saveProject(self, fn):
        data = self.document.store()
        f = open(fn, "w")
        json.dump(data, f, indent=2)
        f.close()
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
            self.loadProject(fn)
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
            self.setWindowFilePath(fn)
    def fileSave(self):
        if self.document.filename is None:
            self.fileSaveAs()
        else:
            self.saveProject(self.document.filename)
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
        class OpExporter(object):
            def __init__(self, document):
                self.operations = gcodegen.Operations(document.gcode_machine_params)
                self.all_cutters = set([])
                self.cutter = None
                document.forEachOperation(self.add_cutter)
                document.forEachOperation(self.process_operation)
            def add_cutter(self, item):
                self.all_cutters.add(item.cutter)
            def process_operation(self, item):
                if item.cutter != self.cutter and len(self.all_cutters) > 1:
                    self.operations.add(gcodegen.ToolChangeOperation(item.cutter))
                    self.cutter = item.cutter
                if item.cam:
                    self.operations.add_all(item.cam.operations)
            def write(self, fn):
                self.operations.to_gcode_file(fn)
        exporter = OpExporter(self.document)
        exporter.write(fn)
    def fileExit(self):
        self.close()

parser = argparse.ArgumentParser(description="Generate G-Code from DXF data")
parser.add_argument('input', type=str, help="File to load on startup")
parser.add_argument('--export-gcode', nargs=1, metavar='OUTPUT_FILENAME', help="Convert a project file to G-Code and exit")

QCoreApplication.setOrganizationName("kfoltman")
QCoreApplication.setApplicationName("DerpCAM")

app = QApplication(sys.argv)
app.setApplicationDisplayName("My CAM experiment")

args = parser.parse_args()

loadInventory()

w = CAMMainWindow(document)
w.initUI()
if args.input:
    fn = args.input
    fnl = fn.lower()
    if fnl.endswith(".dxf"):
        w.importDrawing(fn)
    elif fnl.endswith(".dcp"):
        w.loadProject(fn)
if args.export_gcode:
    if not args.input or not args.input.endswith(".dcp"):
        sys.stderr.write("Error: Input file not specified\n")
        retcode = 1
    elif args.export_gcode[0].endswith(".dcp") or args.export_gcode[0].endswith(".dxf"):
        sys.stderr.write("Error: Output filename has an extension that would suggest it is an input file\n")
        retcode = 1
    else:
        try:
            w.document.validateForOutput()
            w.exportGcode(args.export_gcode[0])
            retcode = 0
        except ValueError as e:
            sys.stderr.write(str(e) + "\n")
            retcode = 2
else:
    w.showMaximized()
    retcode = app.exec_()
    del w
    del app

    saveInventory()

sys.exit(retcode)
