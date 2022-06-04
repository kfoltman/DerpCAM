from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from geom import GeometrySettings

class ConfigSetting(object):
    def __init__(self, attr_name, setting_pathname, def_value):
        self.attr_name = attr_name
        self.setting_pathname = setting_pathname
        self.def_value = def_value
    def init(self, target):
        setattr(target, self.attr_name, self.def_value)
    def load(self, settings, target):
        if settings.contains(self.setting_pathname):
            setattr(target, self.attr_name, self.from_setting(settings.value(self.setting_pathname)))
    def save(self, settings, source):
        settings.setValue(self.setting_pathname, self.to_setting(getattr(source, self.attr_name)))
    def from_setting(self, cfgvalue):
        return str(cfgvalue)
    def to_setting(self, value):
        return str(value)

class IntConfigSetting(ConfigSetting):
    def from_setting(self, cfgvalue):
        return int(cfgvalue)
    def to_setting(self, value):
        return str(value)

class FloatConfigSetting(ConfigSetting):
    def __init__(self, attr_name, setting_pathname, def_value, digits):
        ConfigSetting.__init__(self, attr_name, setting_pathname, def_value)
        self.digits = digits
    def from_setting(self, cfgvalue):
        return float(cfgvalue)
    def to_setting(self, value):
        return f"{value:0.{self.digits}f}"

class BoolConfigSetting(ConfigSetting):
    def from_setting(self, cfgvalue):
        return cfgvalue == 'true'
    def to_setting(self, value):
        return 'true' if value else 'false'

class ConfigSettings(object):
    setting_list = [
        FloatConfigSetting('resolution', 'geometry/resolution', GeometrySettings.RESOLUTION, 1),
        BoolConfigSetting('simplify_arcs', 'geometry/simplify_arcs', GeometrySettings.simplify_arcs),
        BoolConfigSetting('simplify_lines', 'geometry/simplify_lines', GeometrySettings.simplify_lines),
        BoolConfigSetting('draw_arrows', 'display/draw_arrows', GeometrySettings.draw_arrows),
        FloatConfigSetting('grid_resolution', 'display/grid_resolution', 50, 2),
        ConfigSetting('input_directory', 'paths/input', ''),
        ConfigSetting('last_input_directory', 'paths/last_input', ''),
        ConfigSetting('gcode_directory', 'paths/gcode', ''),
        ConfigSetting('last_gcode_directory', 'paths/last_gcode', ''),
        FloatConfigSetting('clearance_z', 'defaults/clearance_z', 5, 2),
        FloatConfigSetting('safe_entry_z', 'defaults/safe_entry_z', 1, 2),
    ]
    def __init__(self):
        self.settings = self.createSettingsObj()
        for i in self.setting_list:
            i.init(self)
        self.load()
    def createSettingsObj(self):
        return QSettings("kfoltman", "DerpCAM")
    def load(self):
        settings = self.settings
        settings.sync()
        for i in self.setting_list:
            i.load(settings, self)
    def save(self):
        settings = self.settings
        for i in self.setting_list:
            i.save(settings, self)
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
            self.setValue(dlg.directory().absolutePath(), self.default_value)
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
        self.outerForm = QFormLayout(self)
        self.tabs = QTabWidget()

        def floatSpin(vmin, vmax, decs, value, tooltip):
            res = QDoubleSpinBox()
            res.setRange(vmin, vmax)
            res.setDecimals(decs)
            res.setValue(value)
            res.setToolTip(tooltip)
            vlongest = max(len(str(vmin)), len(str(vmax)))
            digits = vlongest + decs + (1 if decs else 0)
            spinWidth = QFontMetrics(res.font()).size(Qt.TextSingleLine, "9999" + ("9" * digits)).width()
            res.setMaximumWidth(spinWidth)
            return res

        self.widgetCAM = QWidget()
        self.formCAM = QFormLayout(self.widgetCAM)
        self.resolutionSpin = floatSpin(10, 200, 1, self.config.resolution, "Resolution of the internal raster for path computation. More = slower but more accurate.")
        self.formCAM.addRow("&Resolution (pixels per mm):", self.resolutionSpin)
        self.simplifyArcsCheck = QCheckBox("&Convert lines to arcs")
        self.formCAM.addRow(self.simplifyArcsCheck)
        self.simplifyLinesCheck = QCheckBox("&Merge short segments (experimental)")
        self.formCAM.addRow(self.simplifyLinesCheck)

        self.widgetDisplay = QWidget()
        self.formDisplay = QFormLayout(self.widgetDisplay)
        self.gridSpin = floatSpin(0, 1000, 2, self.config.grid_resolution, "Spacing between display grid lines in mm")
        self.formDisplay.addRow("&Display grid (mm):", self.gridSpin)
        self.drawArrowsCheck = QCheckBox("Draw &arrows on toolpaths (experimental)")
        self.formDisplay.addRow(self.drawArrowsCheck)

        self.widgetPaths = QWidget()
        self.formPaths = QFormLayout(self.widgetPaths)
        self.inputDirEdit = DirectorySelector()
        self.formPaths.addRow("&Input directory:", self.inputDirEdit)
        self.gcodeDirEdit = DirectorySelector()
        self.formPaths.addRow("&Gcode directory:", self.gcodeDirEdit)

        self.widgetDefaults = QWidget()
        self.formDefaults = QFormLayout(self.widgetDefaults)
        self.clearanceZSpin = floatSpin(-100, 100, 2, self.config.clearance_z, "Z coordinate at which horizontal rapid moves are performed, assumed safe from collision with workholding")
        self.formDefaults.addRow("&Clearance Z:", self.clearanceZSpin)
        self.safeEntryZSpin = floatSpin(-100, 100, 2, self.config.safe_entry_z, "Z coordinate above which vertical rapid moves are safe, slightly above the top of the material")
        self.formDefaults.addRow("&Safe entry Z:", self.safeEntryZSpin)

        self.tabs.addTab(self.widgetCAM, "&CAM")
        self.tabs.addTab(self.widgetDisplay, "&Display")
        self.tabs.addTab(self.widgetPaths, "&Paths")
        self.tabs.addTab(self.widgetDefaults, "D&efaults")

        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.outerForm.addRow(self.tabs)
        self.outerForm.addRow(self.buttonBox)

        self.simplifyArcsCheck.setChecked(self.config.simplify_arcs)
        self.simplifyLinesCheck.setChecked(self.config.simplify_lines)
        self.drawArrowsCheck.setChecked(self.config.draw_arrows)
        self.inputDirEdit.setValue(self.config.input_directory, self.config.last_input_directory)
        self.gcodeDirEdit.setValue(self.config.gcode_directory, self.config.last_gcode_directory)
        self.resolutionSpin.setFocus()
    def accept(self):
        self.config.resolution = self.resolutionSpin.value()
        self.config.simplify_arcs = self.simplifyArcsCheck.isChecked()
        self.config.simplify_lines = self.simplifyLinesCheck.isChecked()
        self.config.draw_arrows = self.drawArrowsCheck.isChecked()
        self.config.grid_resolution = self.gridSpin.value()
        self.config.input_directory = self.inputDirEdit.value()
        self.config.gcode_directory = self.gcodeDirEdit.value()
        self.config.clearance_z = self.clearanceZSpin.value()
        self.config.safe_entry_z = self.safeEntryZSpin.value()
        QDialog.accept(self)

