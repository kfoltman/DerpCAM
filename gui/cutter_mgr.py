import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from . import inventory

class CutterListWidget(QTreeWidget):
    def __init__(self, parent, toolbits, document, cutter_type):
        QTreeWidget.__init__(self, parent)
        self.document = document
        self.cutter_type = cutter_type
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

        self.project_toolbits = QTreeWidgetItem(["Project toolbits", "", ""])
        self.project_toolbits.content = None
        self.project_toolbits.setFirstColumnSpanned(True)
        self.project_toolbits.setFont(0, self.larger_font)
        self.insertTopLevelItem(0, self.project_toolbits)

        self.inventory_toolbits = QTreeWidgetItem(["Inventory toolbits", "", ""])
        self.inventory_toolbits.content = None
        self.inventory_toolbits.setFirstColumnSpanned(True)
        self.inventory_toolbits.setFont(0, self.larger_font)
        self.insertTopLevelItem(1, self.inventory_toolbits)

        self.setCurrentItem(self.topLevelItem(0))
        for cycle in self.document.allCycles():
            self.addToolbit(self.project_toolbits, cycle.cutter, cycle)
        for tb in toolbits:
            self.addToolbit(self.inventory_toolbits, tb, tb)

        #self.setRootIsDecorated(False)
        self.expandAll()
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(1)
        self.resizeColumnToContents(2)
    def addToolbit(self, output_list, tb, tb_obj):
        if self.cutter_type is not None and not isinstance(tb, self.cutter_type):
            return
        self.lookup.append(tb)
        cutter = QTreeWidgetItem([tb.cutter_type_name, tb.name, tb.description_only()])
        cutter.content = tb_obj
        self.setItemFont(cutter, self.larger_font)
        currentItem = None
        if tb_obj is self.selected_cycle:
            currentItem = cutter
        for j in tb.presets:
            preset = QTreeWidgetItem(["Preset", j.name, j.description_only()])
            self.setItemFont(preset, self.italic_font)
            preset.content = (tb_obj, j)
            cutter.addChild(preset)
            if j is self.selected_preset:
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
    def initUI(self):
        self.setWindowTitle("Select a tool and a preset for the operation")
        self.cutter = None
        self.form = QFormLayout(self)
        self.selectRadio = QRadioButton("&Select a cutter and a preset", self)
        self.selectRadio.setChecked(True)
        self.selectRadio.clicked.connect(lambda: self.tools.setFocus(Qt.ShortcutFocusReason))
        #label.setBuddy(self.tools)
        self.form.addRow(self.selectRadio)
        toolbits = sorted(inventory.inventory.toolbits, key=lambda item: (item.cutter_type_priority, item.name))
        self.tools = CutterListWidget(self, toolbits, self.document, self.cutter_type)
        self.tools.doubleClicked.connect(self.accept)
        self.tools.itemSelectionChanged.connect(self.toolOrPresetSelected)
        self.form.addRow(self.tools)
        self.addRadio = QRadioButton("&Create a new cutter", self)
        self.form.addRow(self.addRadio)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.form.addRow(self.buttonBox)
        self.tools.setFocus(Qt.PopupFocusReason)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.selectRadio.pressed.connect(lambda: self.tools.setEnabled(True))
        self.addRadio.pressed.connect(lambda: self.tools.setEnabled(False))
        self.toolOrPresetSelected()
    def toolOrPresetSelected(self):
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(self.tools.selectedItem() is not None)
    def accept(self):
        if self.addRadio.isChecked():
            self.choice = Ellipsis
        else:
            self.choice = self.tools.selectedItem()
        QDialog.accept(self)

class CreateCutterDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.initUI()
    def initUI(self):
        self.setWindowTitle("Create a new tool and add it to the project")
        self.cutter = None
        self.form = QFormLayout(self)
        self.nameEdit = QLineEdit()
        self.form.addRow("Name", self.nameEdit)
        self.form.addRow(QLabel("Select the type of a cutter to create"))
        self.emRadio = QRadioButton("&End mill", self)
        self.emRadio.setChecked(True)
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
        self.emRadio.pressed.connect(lambda: self.flutesEdit.setEnabled(True))
        self.drillRadio.pressed.connect(lambda: self.flutesEdit.setEnabled(False))
    def accept(self):
        name = self.nameEdit.text()
        if name == '':
            QMessageBox.critical(self, None, "Name is required")
            self.nameEdit.setFocus()
            return
        if inventory.inventory.toolbitByName(name):
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
            self.cutter = inventory.EndMillCutter.new(None, self.nameEdit.text(), inventory.CutterMaterial.carbide, diameter, length, flutes)
        if self.drillRadio.isChecked():
            self.cutter = inventory.DrillBitCutter.new(None, self.nameEdit.text(), inventory.CutterMaterial.HSS, diameter, length)
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

