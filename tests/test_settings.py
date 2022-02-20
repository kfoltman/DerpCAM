import os.path
import sys
import unittest
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import geom
import gui.settings

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

class ConfigSettingsForTest(gui.settings.ConfigSettings):
    def createSettingsObj(self):
        settings = QSettings("kfoltman", "DerpCAM-test")
        return settings

class ConfigDialogTest(unittest.TestCase):
    def setUp(self):
        self.dlg = None
        self.settings = ConfigSettingsForTest()
    def tearDown(self):
        del self.dlg
    def testSpinboxes(self):
        self.checkSpinbox("resolution", "resolutionSpin", [(42, 33), (21, 55)], geometry_setting='RESOLUTION')
        self.checkSpinbox("grid_resolution", "gridSpin", [(42, 33), (21, 55)])
    def testCheckboxes(self):
        self.checkCheckbox('simplify_arcs', 'simplifyArcsCheck')
        self.checkCheckbox('simplify_lines', 'simplifyLinesCheck')
        self.checkCheckbox('draw_arrows', 'drawArrowsCheck')
    def createDialog(self):
        self.dlg = gui.settings.PreferencesDialog(None, self.settings)
        self.dlg.initUI()
    def verifyDialogContent(self):
        self.createDialog()
        self.assertEqual(self.dlg.resolutionSpin.text(), str(self.settings.resolution))
        self.assertEqual(self.dlg.gridSpin.text(), str(self.settings.grid_resolution))
    def checkSpinbox(self, config_attr, widget_attr, values, geometry_setting=None):
        for value, new_value in values:
            setattr(self.settings, config_attr, value)
            self.settings.save()
            self.settings.update()
            if geometry_setting:
                self.assertEqual(getattr(geom.GeometrySettings, geometry_setting), value, geometry_setting)
            # OK without changes
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
            self.dlg.accept()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            # OK with a change
            self.settings.load()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
            getattr(self.dlg, widget_attr).setValue(new_value)
            self.dlg.accept()
            self.assertEqual(getattr(self.settings, config_attr), new_value, config_attr)
            # Cancel with a change
            self.settings.load()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
            getattr(self.dlg, widget_attr).setValue(new_value)
            self.dlg.reject()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
    def checkCheckbox(self, config_attr, widget_attr):
        for value in (False, True):
            setattr(self.settings, config_attr, value)
            self.settings.save()
            # OK without changes
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).isChecked(), value, widget_attr)
            self.dlg.accept()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.settings.update()
            self.assertEqual(getattr(geom.GeometrySettings, config_attr), value, config_attr)
            # OK with a change
            self.settings.load()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).isChecked(), value, widget_attr)
            getattr(self.dlg, widget_attr).setChecked(not value)
            self.dlg.accept()
            self.assertEqual(getattr(self.settings, config_attr), not value, config_attr)
            # Cancel with a change
            self.settings.load()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).isChecked(), value, widget_attr)
            getattr(self.dlg, widget_attr).setChecked(not value)
            self.dlg.reject()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)

unittest.main()
