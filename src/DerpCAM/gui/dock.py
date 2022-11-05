import argparse
import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.gui import propsheet, canvas, model, inventory, cutter_mgr

OperationType = model.OperationType

class TreeViewWithAltArrows(QTreeView):
    widgetLeft = pyqtSignal([])
    def leaveEvent(self, event):
        self.widgetLeft.emit()
        return QTreeView.leaveEvent(self, event)
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Down or event.key() == Qt.Key_Up) and (event.modifiers() & Qt.AltModifier) == Qt.AltModifier:
            event.setAccepted(False)
        else:
            return QTreeView.keyPressEvent(self, event)

def defaultDockWidgetWidth(widget):
    # screen() is Qt 5.14 and up
    if hasattr(widget, 'screen'):
        return max(300, widget.screen().size().width() // 4)
    else:
        return 300

class CAMObjectTreeDockWidget(QDockWidget):
    operationTouched = pyqtSignal([QStandardItem])
    noOperationTouched = pyqtSignal([])
    selectionChanged = pyqtSignal([])
    modeChanged = pyqtSignal([int])
    INPUTS_TAB = 0
    OPERATIONS_TAB = 1
    def __init__(self, document):
        QDockWidget.__init__(self, "Project content")
        self.document = document
        self.setFeatures(self.features() & ~QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumSize(defaultDockWidgetWidth(self), 100)
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
        tree.setMouseTracking(True)
        tree.selectionModel().selectionChanged.connect(self.operationSelectionChanged)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(self.customContextMenu)
        tree.entered.connect(self.onOperationEntered)
        tree.viewportEntered.connect(self.onOperationViewportEntered)
        tree.widgetLeft.connect(self.onOperationViewportEntered)
        self.operTree = tree
        self.tabs.addTab(tree, "&Operations")

        self.operToolbar = QToolBar()
        self.operToolbar.addAction(self.style().standardIcon(QStyle.SP_ArrowUp), "Move Earlier", self.operationMoveUp)
        self.operToolbar.addAction(self.style().standardIcon(QStyle.SP_ArrowDown), "Move Later", self.operationMoveDown)
        self.operToolbar.addAction(self.style().standardIcon(QStyle.SP_TrashIcon), "Delete", self.operationDelete)
        self.operToolbar.addAction(self.style().standardIcon(QStyle.SP_MediaPause), "Enable/disable", self.operationEnable)

        self.tabs.setTabPosition(QTabWidget.South)
        self.tabs.currentChanged.connect(self.tabSelectionChanged)
        self.document.operationsUpdated.connect(lambda: self.updateOperationIcons())
        self.setWidget(self.tabs)
    def onCutterChanged(self, cutter):
        self.shapeTree.repaint()
    def onOperationViewportEntered(self):
        self.noOperationTouched.emit()
    def onOperationEntered(self, index):
        item = self.document.operModel.itemFromIndex(index)
        if item:
            self.operationTouched.emit(item)
    def updateOperationIcons(self):
        if any(self.document.checkCAMErrors()):
            self.tabs.setTabIcon(1, self.tabs.style().standardIcon(QStyle.SP_MessageBoxCritical))
        elif any(self.document.checkCAMWarnings()):
            self.tabs.setTabIcon(1, self.tabs.style().standardIcon(QStyle.SP_MessageBoxWarning))
        else:
            self.tabs.setTabIcon(1, QIcon())
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
            self.returnKeyPressed(self.activeSelection())
        elif event.key() == Qt.Key_Down and (event.modifiers() & Qt.AltModifier) == Qt.AltModifier:
            self.operationMoveDown()
        elif event.key() == Qt.Key_Up and (event.modifiers() & Qt.AltModifier) == Qt.AltModifier:
            self.operationMoveUp()
        else:
            QDockWidget.keyPressEvent(self, event)
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
        if mode == 's':
            if len(items) != 1:
                return
            point = self.shapeTree.mapToGlobal(point)
        else:
            point = self.operTree.mapToGlobal(point)
        menu = QMenu(self)
        if mode == 'o':
            action = menu.addAction("Enabled")
            action.setCheckable(True)
            action.setChecked(model.CycleTreeItem.listCheckState(items) != Qt.CheckState.Unchecked)
            action.changed.connect(self.operationEnable)
        if len(items) == 1:
            item = items[0]
            if isinstance(item, model.OperationTreeItem):
                if item.operation == OperationType.OUTSIDE_CONTOUR or item.operation == OperationType.INSIDE_CONTOUR:
                    menu.addAction("Holding tabs").triggered.connect(self.operationHoldingTabs)
                    menu.addAction("Entry/exit points").triggered.connect(self.operationEntryExitPoints)
                elif item.areIslandsEditable():
                    menu.addAction("Islands").triggered.connect(self.operationIslands)
                elif item.operation == OperationType.OUTSIDE_PEEL:
                    menu.addAction("Contours").triggered.connect(self.operationIslands)
            elif isinstance(item, model.CycleTreeItem):
                menu.addAction("Set as current").triggered.connect(lambda: self.cycleSetAsCurrent(item))
            elif isinstance(item, model.ToolPresetTreeItem):
                action = menu.addAction("Set as default")
                action.setCheckable(True)
                action.setChecked(item.isDefault())
                action.setEnabled(not item.isDefault())
                action.triggered.connect(lambda: self.toolPresetSetAsCurrent(item))
                action = menu.addAction("Clone...")
                action.triggered.connect(lambda: self.toolPresetClone(item))
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
                action = menu.addAction("New preset...")
                action.triggered.connect(lambda: self.toolNewPreset(item))
                menu.addSeparator()
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
            elif isinstance(item, model.DrawingPolylineTreeItem):
                action = menu.addAction("Edit")
                action.triggered.connect(lambda: self.polylineEdit(item))
        if menu.isEmpty():
            return
        menu.exec_(point)
    def toolSaveToInventory(self, item):
        if not item.inventory_tool.base_object:
            tool_copy = item.inventory_tool.newInstance()
            tool_copy.presets = [i.newInstance() for i in item.inventory_tool.presets]
            for i in tool_copy.presets:
                i.toolbit = tool_copy
            inventory.inventory.toolbits.append(tool_copy)
            cutter_mgr.saveInventory()
            item.inventory_tool.base_object = tool_copy
            self.document.refreshToolList()
    def toolUpdateInInventory(self, item):
        if item.inventory_tool.base_object:
            item.inventory_tool.base_object.resetTo(item.inventory_tool)
            cutter_mgr.saveInventory()
            self.document.refreshToolList()
    def onToolListRefreshed(self):
        self.shapeTree.expandAll()
        if any([i for i in self.shapeSelection() if isinstance(i, (model.ToolTreeItem, model.ToolPresetTreeItem))]):
            self.selectionChanged.emit()
    def onCutterSelected(self, cutter_cycle):
        if cutter_cycle:
            self.operTree.expand(cutter_cycle.index())
    def toolNewPreset(self, item):
        preset = cutter_mgr.createPresetDialog(self, self.document, item.inventory_tool, False)
        if preset:
            self.document.refreshToolList()
    def toolRevertFromInventory(self, item):
        if item.inventory_tool.base_object:
            self.document.opRevertTool(item)
            item.inventory_tool.resetTo(item.inventory_tool.base_object)
            self.document.refreshToolList()
    def toolDelete(self, item):
        cycle = self.document.cycleForCutter(item.inventory_tool)
        if QMessageBox.question(self, "Delete cutter from project",
            "This will delete the cutter, its presets and all the operations that use that cutter from the project. Continue?") == QMessageBox.Yes:
            self.document.opDeleteCycle(cycle)
    def toolPresetClone(self, item):
        preset = cutter_mgr.createPresetDialog(self, self.document, item.inventory_preset.toolbit, False, item.inventory_preset)
        if preset:
            self.document.refreshToolList()
            self.shapeTree.expandAll()
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
        cutter_mgr.saveInventory()
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
            self.tabs.setCornerWidget(None, Qt.TopRightCorner)
        elif self.tabs.currentIndex() == 1:
            self.tabs.setCornerWidget(self.operToolbar, Qt.TopRightCorner)
            self.operToolbar.show()
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
    def shapeJoin(self):
        selType, items = self.activeSelection()
        if selType == 's':
            for i in items:
                if not isinstance(i, model.DrawingPolylineTreeItem) or i.closed:
                    QMessageBox.critical(self, None, "Only lines, open polylines and arcs can be joined")
                    return
            if not items:
                QMessageBox.critical(self, None, "No items selected")
                return
            self.document.opJoin(items)
    def polylineEdit(self, item):
        self.modeChanged.emit(canvas.DrawingUIMode.MODE_POLYLINE)
    def operationMove(self, selection, direction):
        mode, items = selection
        indexes = self.document.opMoveItems(items, direction)
        if not indexes:
            return
        newSelection = QItemSelection()
        for index in indexes:
            newSelection.select(index, index)
        tree = self.activeTree()
        tree.selectionModel().setCurrentIndex(indexes[-1], QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current)
        tree.selectionModel().select(newSelection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current)
    def operationMoveUp(self):
        self.operationMove(self.activeSelection(), -1)
    def operationMoveDown(self):
        self.operationMove(self.activeSelection(), +1)
    def operationDelete(self):
        selType, items = self.activeSelection()
        if selType == 'o':
            self.document.opDeleteOperations(items)
    def operationEnable(self):
        mode, items = self.activeSelection()
        if mode != 'o' or not items:
            return
        oldState = model.CycleTreeItem.listCheckState(items)
        changes = [(i, oldState != Qt.CheckState.Checked) for i in items]
        self.document.opChangeActive(changes)
    def operationHoldingTabs(self):
        self.modeChanged.emit(canvas.DrawingUIMode.MODE_TABS)
    def operationEntryExitPoints(self):
        self.modeChanged.emit(canvas.DrawingUIMode.MODE_ENTRY)
    def operationIslands(self):
        self.modeChanged.emit(canvas.DrawingUIMode.MODE_ISLANDS)
    def cycleSetAsCurrent(self, item):
        self.document.selectCutterCycle(item)

class CAMPropertiesDockWidget(QDockWidget):
    def __init__(self, document):
        QDockWidget.__init__(self, "Properties")
        self.setFeatures(self.features() & ~QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumSize(defaultDockWidgetWidth(self), 100)
        self.propsheet = propsheet.PropertySheetWidget([], document)
        self.setWidget(self.propsheet)
        self.updateModel()
    def updateModel(self):
        self.propsheet.setObjects([])
    def updateProperties(self):
        self.propsheet.refreshAll()
    def updatePropertiesFor(self, objects):
        if set(objects) & set(self.propsheet.objects):
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

class CAMEditorDockWidget(QDockWidget):
    applyClicked = pyqtSignal([])
    def __init__(self, document):
        QDockWidget.__init__(self, "Editor")
        self.setFeatures(self.features() & ~QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumSize(defaultDockWidgetWidth(self), 100)
        self.setEditorLayout(canvas.DrawingUIMode.MODE_NORMAL, None)
    def setEditorLayout(self, mode, mode_item):
        self.setWidget(QWidget())
        layout = QFormLayout()
        DrawingUIMode = canvas.DrawingUIMode
        if mode != DrawingUIMode.MODE_NORMAL:
            if mode == DrawingUIMode.MODE_TABS:
                self.setWindowTitle("Place holding tabs")
                modeText = "Click on outlines to add/remove preferred locations for holding tabs."
            if mode == DrawingUIMode.MODE_ISLANDS:
                self.setWindowTitle("Select areas to exclude")
                modeText = "Click on outlines to toggle exclusion of areas from the pocket."
            if mode == DrawingUIMode.MODE_ENTRY:
                self.setWindowTitle("Select entry point")
                orientation = mode_item.contourOrientation()
                if orientation:
                    modeText = "Click on desired entry point for the contour running in counter-clockwise direction."
                else:
                    modeText = "Click on desired entry point for the contour running in clockwise direction."
            if mode == DrawingUIMode.MODE_EXIT:
                self.setWindowTitle("Select exit point")
                orientation = mode_item.contourOrientation()
                if orientation:
                    modeText = "Click on desired end of the cut, counter-clockwise from starting point."
                else:
                    modeText = "Click on desired end of the cut, clockwise from starting point."
            if mode == DrawingUIMode.MODE_POLYLINE:
                self.setWindowTitle("Modify a polyline")
                #modeText = f"Drag to add or move a point, double-click to remove, snap={10 ** -self.polylineSnapValue():0.2f} mm"
                modeText = "Drag to add or move a node, double-click to remove."
            if mode == DrawingUIMode.MODE_ADD_POLYLINE:
                self.setWindowTitle("Create a polyline")
                modeText = "Click to add a node. Clicking the first point closes the polyline.\nDrag a line to add a node.\nDrag a node to move it.\nDouble-click a middle point to remove it.\nDouble-click the last point to complete a polyline."
            descriptionLabel = QLabel(modeText)
            descriptionLabel.setFrameShape(QFrame.Panel)
            descriptionLabel.setMargin(5)
            descriptionLabel.setWordWrap(True)
            layout.addWidget(descriptionLabel)
            applyButton = QPushButton(self.style().standardIcon(QStyle.SP_DialogApplyButton), "&Apply")
            applyButton.clicked.connect(lambda: self.applyClicked.emit())
            layout.addWidget(applyButton)
        if self.widget().layout():
            self.widget().setLayout(None)
        self.widget().setLayout(layout)
