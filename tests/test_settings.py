import os.path
import sys
import unittest
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import geom
import gui.settings

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QApplication, QFileDialog
from PyQt5.QtTest import QTest

app = QApplication(sys.argv)

class ConfigSettingsForTest(gui.settings.ConfigSettings):
    def createSettingsObj(self):
        settings = QSettings("kfoltman", "DerpCAM-test")
        settings.clear()
        return settings

class ConfigDialogTest(unittest.TestCase):
    def setUp(self):
        self.dlg = None
        self.settings = ConfigSettingsForTest()
    def tearDown(self):
        del self.dlg
    def testSpinboxes(self):
        self.checkSpinbox("resolution", "resolutionSpin", [(42, 33), (21, 55)], geometry_setting='RESOLUTION')
        self.checkSpinbox("grid_resolution", "gridSpin", [(42, 33.25), (21, 55)])
    def testCheckboxes(self):
        self.checkCheckbox('simplify_arcs', 'simplifyArcsCheck')
        self.checkCheckbox('simplify_lines', 'simplifyLinesCheck')
        self.checkCheckbox('draw_arrows', 'drawArrowsCheck')
    def testEditBoxes(self):
        self.checkDirEditbox('input_directory', 'inputDirEdit')
        self.checkDirEditbox('gcode_directory', 'gcodeDirEdit')
    def createDialog(self):
        self.dlg = gui.settings.PreferencesDialog(None, self.settings)
        self.dlg.initUI()
    def verifyDialogContent(self):
        self.createDialog()
        self.assertEqual(self.dlg.resolutionSpin.text(), str(self.settings.resolution))
        self.assertEqual(self.dlg.gridSpin.text(), str(self.settings.grid_resolution))
    def checkDirEditbox(self, config_attr, widget_attr):
        self.checkEditbox(config_attr, widget_attr, check_last=True)
        value = '/tmp'

        def verifyDlg(dlg):
            self.assertEqual(dlg.fileMode(), QFileDialog.FileMode.Directory)
            self.assertEqual(dlg.directory().absolutePath(), value)
            passed.append(True)
            return True # accept the dialog
        QFileDialog.exec_ = verifyDlg
        # Set directly
        passed = []
        setattr(self.settings, config_attr, value)
        self.createDialog()
        QTest.keyClick(getattr(self.dlg, widget_attr).selectButton, Qt.Key.Key_Space)
        self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
        self.assertEqual(getattr(self.dlg, widget_attr).edit.text(), value, widget_attr)
        self.assertTrue(passed)
        # Set via last value
        passed = []
        setattr(self.settings, config_attr, '')
        setattr(self.settings, f'last_{config_attr}', value)
        self.createDialog()
        QTest.keyClick(getattr(self.dlg, widget_attr).selectButton, Qt.Key.Key_Space)
        self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
        self.assertEqual(getattr(self.dlg, widget_attr).edit.text(), value, widget_attr)
        self.assertTrue(passed)
        # Set via last value while main value is not empty
        passed = []
        setattr(self.settings, config_attr, value)
        setattr(self.settings, f'last_{config_attr}', 'distraction')
        self.createDialog()
        QTest.keyClick(getattr(self.dlg, widget_attr).selectButton, Qt.Key.Key_Space)
        self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
        self.assertEqual(getattr(self.dlg, widget_attr).edit.text(), value, widget_attr)
        self.assertTrue(passed)
    def checkEditbox(self, config_attr, widget_attr, check_last=False):
        new_value = 'testing'
        for value in ('first', 'second'):
            setattr(self.settings, config_attr, value)
            if check_last:
                def_value = f'default value/{value}'
                setattr(self.settings, f'last_{config_attr}', def_value)
            self.settings.save()
            self.createDialog()
            if check_last:
                self.assertEqual(getattr(self.dlg, widget_attr).default_value, def_value, widget_attr)
            self.assertEqual(getattr(self.dlg, widget_attr).edit.text(), value, widget_attr)
            self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
            self.dlg.accept()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            # OK with a change
            self.settings.load()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
            self.assertEqual(getattr(self.dlg, widget_attr).edit.text(), value, widget_attr)
            getattr(self.dlg, widget_attr).edit.setText(new_value)
            self.dlg.accept()
            self.assertEqual(getattr(self.settings, config_attr), new_value, config_attr)
            # OK with a change - using setValue
            self.settings.load()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
            self.assertEqual(getattr(self.dlg, widget_attr).edit.text(), value, widget_attr)
            getattr(self.dlg, widget_attr).setValue(new_value, '123')
            self.assertEqual(getattr(self.dlg, widget_attr).default_value, '123')
            self.dlg.accept()
            self.assertEqual(getattr(self.settings, config_attr), new_value, config_attr)
            # OK with a change - using keyClicks
            self.settings.load()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
            self.assertEqual(getattr(self.dlg, widget_attr).edit.text(), value, widget_attr)
            # Shift-Home to erase the old value
            QTest.keyClick(getattr(self.dlg, widget_attr).edit, Qt.Key.Key_Home, Qt.ShiftModifier)
            QTest.keyClicks(getattr(self.dlg, widget_attr).edit, new_value)
            self.dlg.accept()
            self.assertEqual(getattr(self.settings, config_attr), new_value, config_attr)
            # Cancel with a change
            self.settings.load()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
            self.createDialog()
            self.assertEqual(getattr(self.dlg, widget_attr).value(), value, widget_attr)
            self.assertEqual(getattr(self.dlg, widget_attr).edit.text(), value, widget_attr)
            getattr(self.dlg, widget_attr).edit.setText(new_value)
            self.dlg.reject()
            self.assertEqual(getattr(self.settings, config_attr), value, config_attr)
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
