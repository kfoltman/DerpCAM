import os.path
import sys
import threading
import time
import unittest
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import gui.settings

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtTest import *

app = QApplication(sys.argv)

class ConfigSettingsForTest(gui.settings.ConfigSettings):
    def createSettingsObj(self):
        settings = QSettings("kfoltman", "DerpCAM-test")
        settings.setAtomicSyncRequired(True)
        return settings

class ConfigDialogTest(unittest.TestCase):
    def setUp(self):
        self.dlg = None
        self.settings = ConfigSettingsForTest()
    def tearDown(self):
        del self.dlg
    def testSpinboxes(self):
        self.checkSpinbox("resolution", "resolutionSpin", [(42, 33), (21, 55)])
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
    def checkSpinbox(self, config_attr, widget_attr, values):
        for value, new_value in values:
            setattr(self.settings, config_attr, value)
            self.settings.save()
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
