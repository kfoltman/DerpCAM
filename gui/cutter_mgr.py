import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from . import inventory, model

class CutterListWidget(QTreeWidget):
    def __init__(self, parent, toolbits_func, document, cutter_type, inventory_only=False):
        QTreeWidget.__init__(self, parent)
        self.document = document
        self.toolbits_func = toolbits_func
        self.cutter_type = cutter_type
        self.inventory_only = inventory_only
        self.selected_cycle = self.document.current_cutter_cycle
        if self.selected_cycle is not None:
            self.selected_preset = self.document.default_preset_by_tool.get(self.selected_cycle.cutter, None)
        else:
            self.selected_preset = None
        self.setMinimumSize(800, 400)
        self.setColumnCount(3)
        self.setHeaderItem(QTreeWidgetItem(["Type", "Name", "Description"]))
        self.setAlternatingRowColors(True)
        #self.tools.setHorizontalHeaderLabels(["Name", "Description"])
        items = []
        self.lookup = []
        self.larger_font = QFont()
        self.larger_font.setBold(True)
        #larger.setPointSize(larger.pointSize() * 1.1)
        self.italic_font = QFont()
        self.italic_font.setItalic(True)

        item_idx = 0
        if not self.inventory_only:
            self.project_toolbits = QTreeWidgetItem(["Cutters in the project"])
            self.project_toolbits.content = None
            self.project_toolbits.setFont(0, self.larger_font)
            self.insertTopLevelItem(item_idx, self.project_toolbits)
            self.project_toolbits.setFirstColumnSpanned(True)
            item_idx += 1
        else:
            self.project_toolbits = None

        self.inventory_toolbits = QTreeWidgetItem(["Cutters in the global inventory"])
        self.inventory_toolbits.content = None
        self.inventory_toolbits.setFont(0, self.larger_font)
        self.insertTopLevelItem(item_idx, self.inventory_toolbits)
        self.inventory_toolbits.setFirstColumnSpanned(True)

        self.setCurrentItem(self.topLevelItem(0))
        self.refreshCutters(self.selected_cycle if self.selected_preset is None else self.selected_preset)

        #self.setRootIsDecorated(False)
        self.resizeColumnToContents(0)
        self.setColumnWidth(0, self.columnWidth(0) + 30)
        self.resizeColumnToContents(1)
        self.resizeColumnToContents(2)
    def refreshCutters(self, current_item):
        if self.project_toolbits is not None:
            self.project_toolbits.takeChildren()
        self.inventory_toolbits.takeChildren()
        if not self.inventory_only:
            for cycle in self.document.allCycles():
                self.addToolbit(self.project_toolbits, cycle.cutter, cycle, current_item)
            #self.addVirtualToolbit(self.project_toolbits, "Create a new cutter for this project only")
        for tb in self.toolbits_func():
            self.addToolbit(self.inventory_toolbits, tb, tb, current_item)
        #self.addVirtualToolbit(self.inventory_toolbits, "Create a new cutter in the inventory")
        self.expandAll()
    def addVirtualToolbit(self, parent, command):
        cutter = QTreeWidgetItem([command])
        cutter.setFirstColumnSpanned(True)
        cutter.content = None
        cutter.setForeground(0, QColor(64, 64, 64))
        cutter.setFont(0, self.italic_font)
        parent.addChild(cutter)
    def addToolbit(self, output_list, tb, tb_obj, current_item):
        if self.cutter_type is not None and not isinstance(tb, self.cutter_type):
            return
        is_global = output_list is self.inventory_toolbits
        self.lookup.append(tb)
        cutter = QTreeWidgetItem([tb.cutter_type_name, tb.name, tb.description_only()])
        cutter.is_global = is_global
        cutter.content = tb_obj
        self.setItemFont(cutter, self.larger_font)
        currentItem = None
        if tb_obj is current_item:
            currentItem = cutter
        for j in tb.presets:
            preset = QTreeWidgetItem(["Preset", j.name, j.description_only()])
            preset.is_global = is_global
            self.setItemFont(preset, self.italic_font)
            preset.content = (tb_obj, j)
            cutter.addChild(preset)
            if j is current_item:
                currentItem = preset
        if False:
            addnew = QTreeWidgetItem(["Preset", "<add new>", "Add new preset for this cutter"])
            self.setItemFont(addnew, self.italic_font)
            addnew.setForeground(0, QColor(128, 128, 128))
            addnew.setForeground(1, QColor(128, 128, 128))
            addnew.setForeground(2, QColor(128, 128, 128))
            cutter.addChild(addnew)
        output_list.addChild(cutter)
        if currentItem is not None:
            self.setCurrentItem(currentItem)
    def setItemFont(self, item, font):
        for i in range(3):
            item.setFont(i, font)
    def selectedItem(self):
        item = self.currentItem()
        if item is not None:
            return item.content

class SelectCutterDialog(QDialog):
    def __init__(self, parent, document, cutter_type=None):
        QDialog.__init__(self, parent)
        self.document = document
        self.cutter_type = cutter_type
        self.initUI()
    def setTitle(self):
        self.setWindowTitle("Select a tool and a preset for the operation")
        self.prompt = "&Select or create a cutter and an optional preset to use for the cutting operation"
    def getCutters(self):
        return sorted(inventory.inventory.toolbits, key=lambda item: (item.cutter_type_priority, item.name))
    def cutterList(self):
        return CutterListWidget(self, self.getCutters, self.document, self.cutter_type)
    def initUI(self):
        self.setTitle()
        self.cutter = None
        self.form = QFormLayout(self)
        label = QLabel(self.prompt)
        self.form.addRow(label)
        #self.selectRadio = QRadioButton(self.prompt, self)
        #self.selectRadio.setChecked(True)
        #self.selectRadio.clicked.connect(lambda: self.tools.setFocus(Qt.ShortcutFocusReason))
        #self.form.addRow(self.selectRadio)
        self.tools = self.cutterList()
        label.setBuddy(self.tools)
        self.tools.doubleClicked.connect(self.accept)
        self.tools.itemSelectionChanged.connect(self.toolOrPresetSelected)
        self.form.addRow(self.tools)
        self.actionLayout = QHBoxLayout()
        self.newButton = QPushButton()
        self.editButton = QPushButton()
        self.deleteButton = QPushButton()
        self.newButton.clicked.connect(self.newAction)
        self.editButton.clicked.connect(self.editAction)
        self.deleteButton.clicked.connect(self.deleteAction)
        self.actionLayout.addWidget(self.newButton)
        self.actionLayout.addWidget(self.editButton)
        self.actionLayout.addWidget(self.deleteButton)
        self.form.addRow(self.actionLayout)
        self.buttonBox = QDialogButtonBox()
        self.buttonBox.addButton(QDialogButtonBox.Ok)
        self.buttonBox.addButton(QDialogButtonBox.Cancel)
        self.form.addRow(self.buttonBox)
        self.tools.setFocus(Qt.PopupFocusReason)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.toolOrPresetSelected()
    def toolOrPresetSelected(self):
        def setButtons(newText, editText, deleteText):
            self.newButton.setText(newText or "New...")
            self.editButton.setText(editText or "Modify...")
            self.deleteButton.setText(deleteText or "Delete")
            self.newButton.setEnabled(newText is not None)
            self.editButton.setEnabled(editText is not None)
            self.deleteButton.setEnabled(deleteText is not None)
        item = self.tools.currentItem()
        if item is None:
            setButtons(None, None, None)
        elif item is self.tools.project_toolbits:
            setButtons("&Add a cutter (project)...", None, None)
        elif item is self.tools.inventory_toolbits:
            setButtons("&Add a cutter (inventory)...", None, None)
        elif isinstance(item.content, inventory.CutterBase):
            setButtons("&Create preset...", "&Modify cutter...", "&Delete cutter")
        elif isinstance(item.content, model.CycleTreeItem):
            setButtons("&Create preset...", "&Modify cutter...", "&Delete cycle/cutter")
        elif isinstance(item.content, tuple):
            setButtons("&Create preset...", "&Modify preset...", "&Delete preset")
        else:
            setButtons(None, None, None)
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(self.tools.selectedItem() is not None)
    def newAction(self):
        item = self.tools.currentItem()
        if item is None:
            return
        elif item is self.tools.project_toolbits:
            self.newCutterAction(is_global=False)
        elif item is self.tools.inventory_toolbits:
            self.newCutterAction(is_global=True)
        elif isinstance(item.content, inventory.CutterBase) or isinstance(item.content, model.CycleTreeItem):
            self.newPresetAction(item.content, item.is_global)
        elif isinstance(item.content, tuple):
            self.newPresetAction(item.content[1], item.is_global)
    def newCutterAction(self, is_global):
        dlg = CreateEditCutterDialog(self.parent(), None)
        if dlg.exec_():
            cutter = dlg.cutter
            if is_global:
                inventory.inventory.toolbits.append(cutter)
                saveInventory()
            else:
                self.document.opAddCutter(cutter)
            self.tools.refreshCutters(cutter)
    def newPresetAction(self, cutter, is_global):
        QMessageBox.critical(self, "New preset", "Not implemented yet")
    def editAction(self):
        item = self.tools.currentItem()
        if item is None:
            return
        elif isinstance(item.content, inventory.CutterBase) or isinstance(item.content, model.CycleTreeItem):
            self.editCutterAction(item.content, item.is_global)
        elif isinstance(item.content, tuple):
            self.editPresetAction(item.content[1], item.is_global)
    def editCutterAction(self, cutter_or_cycle, is_global):
        cutter = cutter_or_cycle if is_global else cutter_or_cycle.cutter
        dlg = CreateEditCutterDialog(self.parent(), cutter)
        if dlg.exec_():
            modified_cutter = dlg.cutter
            cutter.name = modified_cutter.name
            cutter.resetTo(modified_cutter)
            if is_global:
                saveInventory()
                # XXXKF check the project for a local version of this cutter
                # 1. If renamed, offer updating the local name?
                # 2. If modified, offer resetting? (or only if unmodified? only changed values?)
            self.tools.refreshCutters(cutter)
            self.document.refreshToolList()
    def editPresetAction(self, cutter, is_global):
        QMessageBox.critical(self, "Edit preset", "Not implemented yet")
    def deleteAction(self):
        item = self.tools.currentItem()
        if item is None:
            return
        elif isinstance(item.content, inventory.CutterBase) or isinstance(item.content, model.CycleTreeItem):
            self.deleteCutterAction(item.content, item.is_global)
        elif isinstance(item.content, tuple):
            self.deletePresetAction(item.content[1], item.is_global)
    def deleteCutterAction(self, cutter_or_cycle, is_global):
        if is_global:
            cutter = cutter_or_cycle
            if QMessageBox.question(self, "Delete inventory cutter", "This will delete the cutter from the global inventory. Continue?") == QMessageBox.Yes:
                inventory.deleteCutter(cutter)
                self.document.opUnlinkInventoryCutter(cutter)
                saveInventory()
                self.tools.refreshCutters(toolbit)
        else:
            cycle = cutter_or_cycle
            if QMessageBox.question(self, "Delete cutting cycle", "This will delete the cutter and the associated cutting cycle from the project. Continue?") == QMessageBox.Yes:
                self.document.opDeleteCycle(cycle)
                self.tools.refreshCutters(None)
    def deletePresetAction(self, preset, is_global):
        if is_global:
            if QMessageBox.question(self, "Delete inventory preset", "This will delete the preset from the global inventory. Continue?") == QMessageBox.Yes:
                toolbit = preset.toolbit
                toolbit.deletePreset(preset)
                self.document.opUnlinkInventoryPreset(preset)
                saveInventory()
                self.tools.refreshCutters(toolbit)
            return
        else:
            if QMessageBox.question(self, "Delete project preset", "This will delete the preset from the project. Continue?") == QMessageBox.Yes:
                toolbit = preset.toolbit
                self.document.opDeletePreset(preset)
                self.tools.refreshCutters(toolbit)
    def accept(self):
        self.choice = self.tools.selectedItem()
        if self.choice:
            QDialog.accept(self)

class AddCutterDialog(SelectCutterDialog):
    def setTitle(self):
        self.setWindowTitle("Add a tool and/or a preset to the project")
        self.prompt = "&Select a cutter and/or a preset from the global inventory to add to the project"
    def getCutters(self):
        return sorted(inventory.inventory.toolbits, key=lambda item: (item.cutter_type_priority, item.name))
    def cutterList(self):
        return CutterListWidget(self, self.getCutters, self.document, self.cutter_type, inventory_only=True)

class CreateEditCutterDialog(QDialog):
    def __init__(self, parent, cutter):
        QDialog.__init__(self, parent)
        self.edit_cutter = cutter
        self.initUI()
    def initUI(self):
        if self.edit_cutter:
            self.setWindowTitle("Modify an existing cutter")
        else:
            self.setWindowTitle("Create a new cutter")
        self.cutter = None
        self.form = QFormLayout(self)
        self.nameEdit = QLineEdit()
        self.form.addRow("Name", self.nameEdit)
        self.form.addRow(QLabel("Select the type of a cutter to create"))
        self.emRadio = QRadioButton("&End mill", self)
        self.form.addRow(self.emRadio)
        self.drillRadio = QRadioButton("&Drill bit", self)
        self.form.addRow(self.drillRadio)
        self.flutesEdit = QLineEdit()
        self.form.addRow("# Flutes (opt.)", self.flutesEdit)
        self.diameterEdit = QLineEdit()
        self.form.addRow("Diameter", self.diameterEdit)
        self.lengthEdit = QLineEdit()
        self.form.addRow("Usable flute length (max depth, opt.)", self.lengthEdit)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.form.addRow(self.buttonBox)
        if self.edit_cutter:
            self.nameEdit.setText(self.edit_cutter.name)
            self.flutesEdit.setText(str(self.edit_cutter.flutes) if self.edit_cutter.flutes else "")
            self.diameterEdit.setText(str(self.edit_cutter.diameter))
            self.lengthEdit.setText(str(self.edit_cutter.length) if self.edit_cutter.length else "")
            if isinstance(self.edit_cutter, inventory.EndMillCutter):
                self.emRadio.setChecked(True)
                self.flutesEdit.setEnabled(True)
            elif isinstance(self.edit_cutter, inventory.DrillBitCutter):
                self.drillRadio.setChecked(True)
                self.flutesEdit.setEnabled(False)
            self.emRadio.setEnabled(False)
            self.drillRadio.setEnabled(False)
        else:
            self.emRadio.setChecked(True)
            self.emRadio.pressed.connect(lambda: self.flutesEdit.setEnabled(True))
            self.drillRadio.pressed.connect(lambda: self.flutesEdit.setEnabled(False))
    def accept(self):
        name = self.nameEdit.text()
        if name == '':
            QMessageBox.critical(self, None, "Name is required")
            self.nameEdit.setFocus()
            return
        existing = inventory.inventory.toolbitByName(name)
        if existing and existing is not self.edit_cutter:
            QMessageBox.critical(self, None, "Name is required to be unique")
            self.nameEdit.setFocus()
            return
        if self.emRadio.isChecked():
            try:
                if self.flutesEdit.text() != '':
                    flutes = float(self.flutesEdit.text())
                    if flutes <= 0 or flutes > 100:
                        raise ValueError("Invalid flutes value")
                else:
                    flutes = None
            except ValueError as e:
                QMessageBox.critical(self, None, "Cutter number of flutes is specified but not valid")
                self.flutesEdit.setFocus()
                return
        try:
            diameter = float(self.diameterEdit.text())
            if diameter <= 0 or diameter > 100:
                raise ValueError("Invalid diameter value")
        except ValueError as e:
            QMessageBox.critical(self, None, "Cutter diameter is not valid")
            self.diameterEdit.setFocus()
            return
        self.diameter = diameter
        try:
            if self.lengthEdit.text() == "":
                self.length = None
            else:
                length = float(self.lengthEdit.text())
                if length <= 0 or length > 500:
                    raise ValueError("Invalid length value")
                self.length = length
        except ValueError as e:
            QMessageBox.critical(self, None, "Cutter length is specified but not a valid number")
            self.lengthEdit.setFocus()
            return
        if self.nameEdit.text() == "":
            QMessageBox.critical(self, None, "Cutter must have a name")
            self.nameEdit.setFocus()
            return
        if self.emRadio.isChecked():
            self.cutter = inventory.EndMillCutter.new(None, self.nameEdit.text(), inventory.CutterMaterial.carbide, diameter, self.length, flutes)
        if self.drillRadio.isChecked():
            self.cutter = inventory.DrillBitCutter.new(None, self.nameEdit.text(), inventory.CutterMaterial.HSS, diameter, self.length)
        QDialog.accept(self)

class AddPresetDialog(QDialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.initUI()
    def initUI(self):
        self.form = QFormLayout(self)
        self.nameEdit = QLineEdit()
        self.form.addRow("Name", self.nameEdit)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.form.addRow(self.buttonBox)
    def accept(self):
        name = self.nameEdit.text()
        if name == '':
            QMessageBox.critical(self, None, "Name is required")
            self.nameEdit.setFocus()
            return
        self.presetName = name
        QDialog.accept(self)

def loadInventory():
    toolsFile = QStandardPaths.locate(QStandardPaths.DataLocation, "tools.json")
    if toolsFile != '':
        inventory.inventory.readFrom(toolsFile)
    else:
        inventory.inventory.createStdCutters()

def saveInventory():
    inventory.inventory.writeTo(QStandardPaths.writableLocation(QStandardPaths.DataLocation), "tools.json")

def selectCutter(parent, dlg_type, document, cutter_type):
    dlg = dlg_type(parent, document=document, cutter_type=cutter_type)
    preset = None
    if dlg.exec_():
        if dlg.choice is Ellipsis:
            dlg = CreateCutterDialog(parent)
            if dlg.exec_():
                cutter = dlg.cutter
                # inventory.inventory.toolbits.append(cutter)
                # saveInventory()
            else:
                return False
        else:
            if isinstance(dlg.choice, model.CycleTreeItem):
                # project's tool/cycle
                document.selectCutterCycle(dlg.choice)
                document.selectPresetAsDefault(dlg.choice.cutter, None)
                return True
            elif isinstance(dlg.choice, inventory.CutterBase):
                # inventory tool
                cutter = dlg.choice.newInstance()
            else:
                assert isinstance(dlg.choice, tuple)
                parent, parent_preset = dlg.choice
                if isinstance(parent, model.CycleTreeItem):
                    # project's preset
                    document.selectCutterCycle(parent)
                    document.selectPresetAsDefault(parent.cutter, parent_preset)
                    return True
                else:
                    cutter, preset, add = document.opAddLibraryPreset(parent_preset)
                    if not add:
                        if document.current_cutter_cycle.cutter is not cutter:
                            for i in document.allCycles():
                                if i.cutter is cutter:
                                    document.selectCutterCycle(i)
                                    break
                        document.selectPresetAsDefault(cutter, preset)
                        #self.projectDW.shapeTree.expand(document.itemForCutter(cutter).index())
                        return True
    else:
        return False
    cycle = document.opAddCutter(cutter)
    if preset:
        document.selectPresetAsDefault(cycle.cutter, preset)
    return True
