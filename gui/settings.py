from PyQt5.QtCore import *
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
    def save(self):
        settings = self.settings
        settings.setValue("geometry/resolution", self.resolution)
        settings.setValue("geometry/simplify_arcs", "true" if self.simplify_arcs else "false")
        settings.setValue("geometry/simplify_lines", "true" if self.simplify_lines else "false")
        settings.setValue("display/draw_arrows", "true" if self.draw_arrows else "false")
        settings.setValue("display/grid_resolution", self.grid_resolution)
        settings.sync()
    def update(self):
        GeometrySettings.RESOLUTION = self.resolution
        GeometrySettings.simplify_arcs = self.simplify_arcs
        GeometrySettings.simplify_lines = self.simplify_lines
        GeometrySettings.draw_arrows = self.draw_arrows

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
        self.form.addRow("&Resolution (pixels per mm):", self.resolutionSpin)
        self.form.addRow(self.simplifyArcsCheck)
        self.form.addRow(self.simplifyLinesCheck)
        self.form.addRow(self.drawArrowsCheck)
        self.form.addRow("&Display grid (mm):", self.gridSpin)
        self.form.addRow(self.buttonBox)
        self.resolutionSpin.setValue(self.config.resolution)
        self.simplifyArcsCheck.setChecked(self.config.simplify_arcs)
        self.simplifyLinesCheck.setChecked(self.config.simplify_lines)
        self.drawArrowsCheck.setChecked(self.config.draw_arrows)
        self.gridSpin.setValue(self.config.grid_resolution)
    def accept(self):
        self.config.resolution = self.resolutionSpin.value()
        self.config.simplify_arcs = self.simplifyArcsCheck.isChecked()
        self.config.simplify_lines = self.simplifyLinesCheck.isChecked()
        self.config.draw_arrows = self.drawArrowsCheck.isChecked()
        self.config.grid_resolution = self.gridSpin.value()
        QDialog.accept(self)

