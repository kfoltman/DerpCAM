import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from gui.model import *

class CutterListWidget(QTreeWidget):
    def __init__(self, parent, toolbits):
        QTreeWidget.__init__(self, parent)
        self.setMinimumSize(600, 200)
        self.setColumnCount(3)
        self.setHeaderItem(QTreeWidgetItem(["Type", "Name", "Description"]))
        #self.tools.setHorizontalHeaderLabels(["Name", "Description"])
        items = []
        self.lookup = []
        for i, tb in enumerate(toolbits):
            self.lookup.append(tb)
            items.append(QTreeWidgetItem([tb.cutter_type_name, tb.name, tb.description_only()]))
        self.setRootIsDecorated(False)
        self.insertTopLevelItems(0, items)
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(1)
        self.resizeColumnToContents(2)
        self.setCurrentItem(self.topLevelItem(0))
    def selectedItem(self):
        row = self.tools.indexFromItem(self.tools.currentItem()).row()
        if row >= 0:
            return self.lookup[row]
        return None

class AddCutterDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.initUI()
    def initUI(self):
        self.cutter = None
        self.form = QFormLayout(self)
        self.selectRadio = QRadioButton("&Select an existing cutter", self)
        self.selectRadio.setChecked(True)
        self.selectRadio.clicked.connect(lambda: self.tools.setFocus(Qt.ShortcutFocusReason))
        #label.setBuddy(self.tools)
        self.form.addRow(self.selectRadio)
        toolbits = sorted(inventory.inventory.toolbits, key=lambda item: (item.cutter_type_priority, item.name))
        self.tools = CutterListWidget(self, toolbits)
        self.tools.doubleClicked.connect(self.accept)
        self.form.addRow(self.tools)
        self.addRadio = QRadioButton("&Add a new cutter", self)
        self.form.addRow(self.addRadio)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.form.addRow(self.buttonBox)
        self.tools.setFocus(Qt.PopupFocusReason)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.selectRadio.pressed.connect(lambda: self.tools.setEnabled(True))
        self.addRadio.pressed.connect(lambda: self.tools.setEnabled(False))
    def accept(self):
        if self.addRadio.isChecked():
            self.cutter = Ellipsis
        else:
            self.cutter = self.tools.selectedItem()
        QDialog.accept(self)

class CreateCutterDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.initUI()
    def initUI(self):
        self.cutter = None
        self.form = QFormLayout(self)
        self.form.addRow(QLabel("Select the type of a cutter to create"))
        self.emRadio = QRadioButton("&End mill", self)
        self.emRadio.setChecked(True)
        self.form.addRow(self.emRadio)
        self.drillRadio = QRadioButton("&Drill bit", self)
        self.form.addRow(self.drillRadio)
        self.nameEdit = QLineEdit()
        self.form.addRow("Name", self.nameEdit)
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
    def __init__(self, parent, cutter):
        QDialog.__init__(self, parent)
        self.cutter = cutter
        self.preset = None
        self.initUI()
    def initUI(self):
        self.form = QFormLayout(self)
        self.selectRadio = QRadioButton("&Select an existing preset", self)
        self.selectRadio.setChecked(True)
        self.selectRadio.clicked.connect(lambda: self.tools.setFocus(Qt.ShortcutFocusReason))
        self.form.addRow(self.selectRadio)
        self.presets = QTreeWidget(self)
        self.presets.setMinimumSize(600, 200)
        self.presets.setColumnCount(2)
        self.presets.setHeaderItem(QTreeWidgetItem(["Name", "Description"]))
        items = []
        self.lookup = []
        for i, preset in enumerate(self.cutter.presets):
            self.lookup.append(preset)
            items.append(QTreeWidgetItem([preset.name, preset.description_only()]))
        self.presets.setRootIsDecorated(False)
        self.presets.insertTopLevelItems(0, items)
        self.presets.resizeColumnToContents(0)
        self.presets.resizeColumnToContents(1)
        self.presets.doubleClicked.connect(self.accept)
        self.form.addRow(self.presets)
        self.addRadio = QRadioButton("&Add a new preset", self)
        self.form.addRow(self.addRadio)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.form.addRow(self.buttonBox)
        self.presets.setCurrentItem(self.presets.topLevelItem(0))
        self.presets.setFocus(Qt.PopupFocusReason)
        self.selectRadio.pressed.connect(lambda: self.presets.setEnabled(True))
        self.addRadio.pressed.connect(lambda: self.presets.setEnabled(False))
    def accept(self):
        if self.addRadio.isChecked():
            self.preset = Ellipsis
        else:
            row = self.presets.indexFromItem(self.presets.currentItem()).row()
            if row >= 0:
                self.preset = self.lookup[row]
        QDialog.accept(self)

def loadInventory():
    toolsFile = QStandardPaths.locate(QStandardPaths.DataLocation, "tools.json")
    if toolsFile != '':
        inventory.inventory.readFrom(toolsFile)
    else:
        inventory.inventory.createStdCutters()

def saveInventory():
    inventory.inventory.writeTo(QStandardPaths.writableLocation(QStandardPaths.DataLocation), "tools.json")

