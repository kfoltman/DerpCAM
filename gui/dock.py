import argparse
import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from gui import propsheet, canvas, model, inventory

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
            elif item.operation == OperationType.OUTSIDE_PEEL:
                menu.addAction("Contours").triggered.connect(self.operationIslands)
            else:
                return
        elif isinstance(item, model.CycleTreeItem):
            menu.addAction("Set as current").triggered.connect(lambda: self.cycleSetAsCurrent(item))
        elif isinstance(item, model.ToolPresetTreeItem):
            action = menu.addAction("Set as default")
            action.setCheckable(True)
            action.setChecked(item.isDefault())
            action.setEnabled(not item.isDefault())
            action.triggered.connect(lambda: self.toolPresetSetAsCurrent(item))
            action = menu.addAction("Save to inventory")
            action.triggered.connect(lambda: self.toolPresetSaveToInventory(item))
            action.setEnabled(item.isNewObject() and not item.parent().isNewObject())
            action = menu.addAction("Update in inventory")
            action.triggered.connect(lambda: self.toolPresetSaveToInventory(item))
            action.setEnabled(item.isModifiedStock() and not item.parent().isNewObject())
            action = menu.addAction("Reload from inventory")
            action.triggered.connect(lambda: self.toolPresetRevertFromInventory(item))
            action.setEnabled(item.isModifiedStock())
            menu.addSeparator()
            action = menu.addAction("Delete from project")
            action.triggered.connect(lambda: self.toolPresetDelete(item))
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
            menu.addSeparator()
            action = menu.addAction("Delete from project")
            action.triggered.connect(lambda: self.toolDelete(item))
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
    def onCutterSelected(self, cutter_cycle):
        if cutter_cycle:
            self.operTree.expand(cutter_cycle.index())
    def toolRevertFromInventory(self, item):
        if item.inventory_tool.base_object:
            self.document.opRevertTool(item)
            item.inventory_tool.resetTo(item.inventory_tool.base_object)
            self.document.refreshToolList()
            self.shapeTree.expandAll()
    def toolDelete(self, item):
        cycle = self.document.cycleForCutter(item.inventory_tool)
        if QMessageBox.question(self, "Delete cutter from project",
            "This will delete the cutter, its presets and all the operations that use that cutter from the project. Continue?") == QMessageBox.Yes:
            self.document.opDeleteCycle(cycle)
    def toolPresetSetAsCurrent(self, item):
        self.document.selectPresetAsDefault(item.inventory_preset.toolbit, item.inventory_preset)
    def toolPresetRevertFromInventory(self, item):
        if item.inventory_preset.base_object:
            self.document.opRevertPreset(item)
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
    def toolPresetDelete(self, item):
        if QMessageBox.question(self, "Delete preset from project", "This will delete the preset from the project. Continue?") == QMessageBox.Yes:
            self.document.opDeletePreset(item.inventory_preset)
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

