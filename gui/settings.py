from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from geom import GeometrySettings

class ConfigSettings(object):
    def __init__(self):
        self.resolution = GeometrySettings.RESOLUTION
        self.simplify_arcs = GeometrySettings.simplify_arcs
        self.simplify_lines = GeometrySettings.simplify_lines
        self.grid_resolution = 50
        self.load()
    def load(self):
        settings = QSettings("kfoltman", "DerpCAM")
        settings.sync()
        self.resolution = int(settings.value("geometry/resolution", self.resolution))
        self.simplify_arcs = settings.value("geometry/simplify_arcs", self.simplify_arcs) == 'true'
        self.simplify_lines = settings.value("geometry/simplify_lines", self.simplify_lines) == 'true'
        self.grid_resolution = int(settings.value("display/grid_resolution", self.grid_resolution))
    def save(self):
        settings = QSettings("kfoltman", "DerpCAM")
        settings.setValue("geometry/resolution", self.resolution)
        settings.setValue("geometry/simplify_arcs", self.simplify_arcs)
        settings.setValue("geometry/simplify_lines", self.simplify_lines)
        settings.setValue("geometry/grid_resolution", self.grid_resolution)
        settings.sync()
    def update(self):
        GeometrySettings.RESOLUTION = self.resolution
        GeometrySettings.simplify_arcs = self.simplify_arcs
        GeometrySettings.simplify_lines = self.simplify_lines

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
        self.gridSpin = QSpinBox()
        self.gridSpin.setRange(0, 1000)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.form.addRow("&Resolution (pixels per mm):", self.resolutionSpin)
        self.form.addRow(self.simplifyArcsCheck)
        self.form.addRow(self.simplifyLinesCheck)
        self.form.addRow("&Display grid (mm):", self.gridSpin)
        self.form.addRow(self.buttonBox)
        self.resolutionSpin.setValue(self.config.resolution)
        self.simplifyArcsCheck.setChecked(self.config.simplify_arcs)
        self.simplifyLinesCheck.setChecked(self.config.simplify_lines)
        self.gridSpin.setValue(self.config.grid_resolution)
    def accept(self):
        self.config.resolution = self.resolutionSpin.value()
        self.config.simplify_arcs = self.simplifyArcsCheck.isChecked()
        self.config.simplify_lines = self.simplifyLinesCheck.isChecked()
        self.config.grid_resolution = self.gridSpin.value()
        QDialog.accept(self)

