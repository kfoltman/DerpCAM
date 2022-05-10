from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from geom import GeometrySettings

class ConfigSettings(object):
    def __init__(self):
        self.settings = self.createSettingsObj()
        self.resolution = GeometrySettings.RESOLUTION
        self.simplify_arcs = GeometrySettings.simplify_arcs
        self.simplify_lines = GeometrySettings.simplify_lines
        self.draw_arrows = GeometrySettings.draw_arrows
        self.grid_resolution = 50
        self.input_directory = ''
        self.gcode_directory = ''
        self.last_input_directory = ''
        self.last_gcode_directory = ''
        self.load()
    def createSettingsObj(self):
        return QSettings("kfoltman", "DerpCAM")
    def load(self):
        settings = self.settings
        settings.sync()
        self.resolution = int(settings.value("geometry/resolution", self.resolution))
        self.simplify_arcs = settings.value("geometry/simplify_arcs", self.simplify_arcs) == 'true'
        self.simplify_lines = settings.value("geometry/simplify_lines", self.simplify_lines) == 'true'
        self.draw_arrows = settings.value("display/draw_arrows", self.draw_arrows) == 'true'
        self.grid_resolution = int(settings.value("display/grid_resolution", self.grid_resolution))
        self.input_directory = settings.value("paths/input", self.input_directory)
        self.last_input_directory = settings.value("paths/last_input", self.last_input_directory)
        self.gcode_directory = settings.value("paths/gcode", self.gcode_directory)
        self.last_gcode_directory = settings.value("paths/last_gcode", self.last_gcode_directory)
    def save(self):
        settings = self.settings
        settings.setValue("geometry/resolution", self.resolution)
        settings.setValue("geometry/simplify_arcs", "true" if self.simplify_arcs else "false")
        settings.setValue("geometry/simplify_lines", "true" if self.simplify_lines else "false")
        settings.setValue("display/draw_arrows", "true" if self.draw_arrows else "false")
        settings.setValue("display/grid_resolution", self.grid_resolution)
        settings.setValue("paths/input", self.input_directory)
        settings.setValue("paths/last_input", self.last_input_directory)
        settings.setValue("paths/gcode", self.gcode_directory)
        settings.setValue("paths/last_gcode", self.last_gcode_directory)
        settings.sync()
    def update(self):
        GeometrySettings.RESOLUTION = self.resolution
        GeometrySettings.simplify_arcs = self.simplify_arcs
        GeometrySettings.simplify_lines = self.simplify_lines
        GeometrySettings.draw_arrows = self.draw_arrows

class DirectorySelector(QWidget):
    def __init__(self):
        QWidget.__init__(self)
        self.setLayout(QHBoxLayout())
        self.layout().setSpacing(5)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.default_value = ''
        self.edit = QLineEdit()
        self.selectButton = QPushButton(self.style().standardIcon(QStyle.SP_DirOpenIcon), "")
        self.selectButton.clicked.connect(self.selectDir)
        self.layout().addWidget(self.edit, 1)
        self.layout().addWidget(self.selectButton, 0)
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumWidth(QFontMetrics(self.edit.font()).size(Qt.TextSingleLine, "9" * 40).width())
    def selectDir(self):
        dlg = QFileDialog(self)
        dlg.setFileMode(QFileDialog.FileMode.Directory)
        if self.value():
            dlg.setDirectory(self.value())
        elif self.default_value:
            dlg.setDirectory(self.default_value)
        if dlg.exec_():
            self.setValue(dlg.directory().absolutePath())
    def value(self):
        return self.edit.text()
    def setValue(self, value, default_value):
        self.edit.setText(value)
        self.default_value = default_value

class PreferencesDialog(QDialog):
    def __init__(self, parent, config):
        QDialog.__init__(self, parent)
        self.config = config
    def initUI(self):
        self.form = QFormLayout(self)
        self.resolutionSpin = QSpinBox()
        self.resolutionSpin.setRange(10, 200)
        self.simplifyArcsCheck = QCheckBox("&Convert lines to arcs")
        self.simplifyLinesCheck = QCheckBox("&Merge short segments (experimental)")
        self.drawArrowsCheck = QCheckBox("Draw &arrows on toolpaths (experimental)")
        self.gridSpin = QSpinBox()
        self.gridSpin.setRange(0, 1000)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.inputDirEdit = DirectorySelector()
        self.gcodeDirEdit = DirectorySelector()
        self.form.addRow("&Resolution (pixels per mm):", self.resolutionSpin)
        self.form.addRow(self.simplifyArcsCheck)
        self.form.addRow(self.simplifyLinesCheck)
        self.form.addRow(self.drawArrowsCheck)
        self.form.addRow("&Display grid (mm):", self.gridSpin)
        self.form.addRow("&Input directory:", self.inputDirEdit)
        self.form.addRow("&Gcode directory:", self.gcodeDirEdit)
        self.form.addRow(self.buttonBox)

        spinWidth = QFontMetrics(self.resolutionSpin.font()).size(Qt.TextSingleLine, "999999").width()
        self.resolutionSpin.setMaximumWidth(spinWidth)
        self.gridSpin.setMaximumWidth(spinWidth)
        self.resolutionSpin.setValue(self.config.resolution)
        self.simplifyArcsCheck.setChecked(self.config.simplify_arcs)
        self.simplifyLinesCheck.setChecked(self.config.simplify_lines)
        self.drawArrowsCheck.setChecked(self.config.draw_arrows)
        self.gridSpin.setValue(self.config.grid_resolution)
        self.inputDirEdit.setValue(self.config.input_directory, self.config.last_input_directory)
        self.gcodeDirEdit.setValue(self.config.gcode_directory, self.config.last_gcode_directory)
    def accept(self):
        self.config.resolution = self.resolutionSpin.value()
        self.config.simplify_arcs = self.simplifyArcsCheck.isChecked()
        self.config.simplify_lines = self.simplifyLinesCheck.isChecked()
        self.config.draw_arrows = self.drawArrowsCheck.isChecked()
        self.config.grid_resolution = self.gridSpin.value()
        self.config.input_directory = self.inputDirEdit.value()
        self.config.gcode_directory = self.gcodeDirEdit.value()
        QDialog.accept(self)

