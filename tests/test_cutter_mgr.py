import os.path
import sys
import unittest

sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from DerpCAM import gui
import DerpCAM.gui.model
import DerpCAM.gui.inventory
import DerpCAM.gui.cutter_mgr
from DerpCAM.common.testutils import ExpectError, ExpectNoError, ExpectQuestion
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QMessageBox
from PyQt5.QtTest import QTest

app = QApplication(sys.argv)
config_settings = gui.settings.ConfigSettings()

saves = 0
def incSaveCount():
    global saves
    saves += 1
gui.cutter_mgr.saveInventory = incSaveCount

class CutterMgrTestBase(unittest.TestCase):
    def setUp(self):
        gui.inventory.IdSequence.nukeAll()
        gui.inventory.inventory = gui.inventory.Inventory()
        gui.inventory.inventory.createStdCutters()
        self.document = gui.model.DocumentModel(config_settings)
    def tearDown(self):
        del self.document
    def clickOk(self, dlg):
        self.assertTrue(dlg.buttonBox.button(QDialogButtonBox.Ok).isEnabled())
        QTest.keyClick(dlg.buttonBox.button(QDialogButtonBox.Ok), Qt.Key.Key_Space)
    def backspaces(self, widget, count):
        widget.setFocus()
        for i in range(count):
            QTest.keyClick(widget, Qt.Key.Key_Backspace)

class CutterListTest(CutterMgrTestBase):
    def testCutterListWidget(self):
        self.verifyInventoryCutterList(gui.inventory.EndMillCutter)
        self.verifyInventoryCutterList(gui.inventory.DrillBitCutter)
        self.verifyProjectCutter("cheapo 2F 3.2/15", gui.inventory.EndMillCutter)
        self.verifyProjectCutter("cheapo 2F 2.5/12", gui.inventory.EndMillCutter)
    def verifyProjectCutter(self, cutter_name, cutter_type):
        toolbits_func = gui.cutter_mgr.SelectCutterDialog.getCutters
        tool_data = gui.inventory.inventory.toolbitByName(cutter_name, cutter_type).newInstance()
        cycle = self.document.opAddCutter(tool_data)
        widget = gui.cutter_mgr.CutterListWidget(None, toolbits_func, self.document, cutter_type, inventory_only=False)
        self.assertEqual(widget.headerItem().text(0), "Type")
        self.assertEqual(widget.headerItem().text(1), "Name")
        self.assertEqual(widget.headerItem().text(2), "Description")
        cycles = self.document.allCycles()
        self.assertEqual(widget.project_toolbits.childCount(), len(cycles))
        sorted_presets = list(sorted(tool_data.presets, key=lambda preset: preset.name))
        for i in range(len(cycles)):
            tool_item = widget.project_toolbits.child(i)
            self.verifyTool(type(cycles[i].cutter), tool_item, cycles[i].cutter)
            for j in range(tool_item.childCount()):
                preset_item = tool_item.child(j)
                preset_data = sorted_presets[j]
                self.verifyPreset(preset_item, preset_data)
    def verifyTool(self, cutter_type, tool_item, tool_data):
        self.assertEqual(tool_item.data(0, Qt.DisplayRole), cutter_type.cutter_type_name)
        self.assertEqual(tool_item.data(1, Qt.DisplayRole), tool_data.name)
        self.assertEqual(tool_item.data(2, Qt.DisplayRole), tool_data.description_only())
    def verifyPreset(self, preset_item, preset_data):
        self.assertEqual(preset_item.data(0, Qt.DisplayRole), "Preset")
        self.assertEqual(preset_item.data(1, Qt.DisplayRole), preset_data.name)
        self.assertEqual(preset_item.data(2, Qt.DisplayRole), preset_data.description_only())
    def verifyInventoryCutterList(self, cutter_type):
        toolbits_func = gui.cutter_mgr.SelectCutterDialog.getCutters
        cutters = toolbits_func()
        self.assertGreater(len(cutters), 0)
        filtered = [i for i in cutters if isinstance(i, cutter_type)]
        widget = gui.cutter_mgr.CutterListWidget(None, toolbits_func, self.document, cutter_type, inventory_only=False)
        self.assertEqual(widget.inventory_toolbits.childCount(), len(filtered))
        self.assertEqual(widget.project_toolbits.childCount(), 0)
        for i in range(widget.inventory_toolbits.childCount()):
            tool_item = widget.inventory_toolbits.child(i)
            tool_data = filtered[i]
            self.verifyTool(cutter_type, tool_item, tool_data)
            sorted_presets = list(sorted(tool_data.presets, key=lambda preset: preset.name))
            for j in range(tool_item.childCount()):
                self.verifyPreset(tool_item.child(j), sorted_presets[j])
        del widget

class CutterEditDlgTest(CutterMgrTestBase):
    def testCreateCutterNoName(self):
        passed = []
        dlg = gui.cutter_mgr.CreateEditCutterDialog(None, None)
        with ExpectError(self, 'Name is required'):
            self.clickOk(dlg)
    def testCreateCutterEM(self):
        for lengthStr in ["", "12"]:
            dlg = gui.cutter_mgr.CreateEditCutterDialog(None, None)
            QTest.keyClicks(dlg.nameEdit, "New endmill")
            QTest.keyClicks(dlg.diameterEdit, "3.175")
            QTest.keyClicks(dlg.lengthEdit, lengthStr)
            self.backspaces(dlg.flutesEdit, 1)
            QTest.keyClicks(dlg.flutesEdit, "4")
            QTest.keyClick(dlg.emRadio, " ")
            with ExpectNoError(self):
                self.clickOk(dlg)
            self.assertTrue(dlg.cutter)
            self.assertIsInstance(dlg.cutter, gui.inventory.EndMillCutter)
            self.assertEqual(dlg.cutter.name, "New endmill")
            self.assertEqual(dlg.cutter.diameter, 3.175)
            self.assertEqual(dlg.cutter.length, float(lengthStr) if lengthStr != "" else None)
            self.assertEqual(dlg.cutter.flutes, 4)
    def testCreateCutterDB(self):
        for lengthStr in ["", "20"]:
            dlg = gui.cutter_mgr.CreateEditCutterDialog(None, None)
            QTest.keyClicks(dlg.nameEdit, "New drill bit")
            QTest.keyClicks(dlg.diameterEdit, "5.5")
            self.backspaces(dlg.flutesEdit, 1)
            QTest.keyClicks(dlg.flutesEdit, "6")
            QTest.keyClick(dlg.drillRadio, " ")
            QTest.keyClicks(dlg.lengthEdit, lengthStr)
            with ExpectNoError(self):
                self.clickOk(dlg)
            self.assertTrue(dlg.cutter)
            self.assertIsInstance(dlg.cutter, gui.inventory.DrillBitCutter)
            self.assertEqual(dlg.cutter.name, "New drill bit")
            self.assertEqual(dlg.cutter.diameter, 5.5)
            self.assertEqual(dlg.cutter.length, float(lengthStr) if lengthStr != "" else None)
            self.assertEqual(dlg.cutter.flutes, 6)
    def testCreateCutterErrors(self):
        for variant in ['emRadio', 'drillRadio']:
            dlg = gui.cutter_mgr.CreateEditCutterDialog(None, None)
            QTest.keyClicks(dlg.nameEdit, variant)
            QTest.keyClicks(dlg.diameterEdit, "bad")
            QTest.keyClicks(dlg.lengthEdit, "bad")
            QTest.keyClicks(dlg.flutesEdit, "bad")
            QTest.keyClick(getattr(dlg, variant), " ")
            with ExpectError(self, 'Invalid number of flutes'):
                self.clickOk(dlg)
            self.backspaces(dlg.flutesEdit, 4)
            QTest.keyClicks(dlg.flutesEdit, "4")

            with ExpectError(self, 'Cutter diameter is not valid'):
                self.clickOk(dlg)
            self.backspaces(dlg.diameterEdit, 3)
            QTest.keyClicks(dlg.diameterEdit, "3.175")

            with ExpectError(self, 'Cutter length is specified but not a valid number'):
                self.clickOk(dlg)
            self.backspaces(dlg.lengthEdit, 3)
            QTest.keyClicks(dlg.lengthEdit, "15")

            self.clickOk(dlg)
            self.assertTrue(dlg.cutter)
            if variant == 'emRadio':
                self.assertIsInstance(dlg.cutter, gui.inventory.EndMillCutter)
            else:
                self.assertIsInstance(dlg.cutter, gui.inventory.DrillBitCutter)
            self.assertEqual(dlg.cutter.name, variant)
            self.assertEqual(dlg.cutter.diameter, 3.175)
            self.assertEqual(dlg.cutter.length, 15)
            self.assertEqual(dlg.cutter.flutes, 4)
    def testEditCutterEM(self):
        orig_tool = gui.inventory.inventory.toolbitByName("cheapo 2F 2.5/12")
        dlg = gui.cutter_mgr.CreateEditCutterDialog(None, orig_tool)
        self.assertEqual(dlg.flutesEdit.text(), "2")
        self.assertEqual(dlg.diameterEdit.text(), "2.5 mm")
        self.assertEqual(dlg.lengthEdit.text(), "12 mm")
        self.clickOk(dlg)
        self.assertIsNot(dlg.cutter, orig_tool)
        self.assertEqual(dlg.cutter.diameter, orig_tool.diameter)
        self.assertEqual(dlg.cutter.length, orig_tool.length)
        self.assertEqual(dlg.cutter.flutes, orig_tool.flutes)
        dlg = gui.cutter_mgr.CreateEditCutterDialog(None, orig_tool)
        dlg.flutesEdit.setText("4")
        dlg.diameterEdit.setText("3.175")
        dlg.lengthEdit.setText("8")
        self.clickOk(dlg)
        self.assertIsNot(dlg.cutter, orig_tool)
        self.assertEqual(dlg.cutter.flutes, 4)
        self.assertEqual(dlg.cutter.diameter, 3.175)
        self.assertEqual(dlg.cutter.length, 8)
    def testEditCutterDB(self):
        orig_tool = gui.inventory.inventory.toolbitByName("3mm HSS")
        dlg = gui.cutter_mgr.CreateEditCutterDialog(None, orig_tool)
        self.assertEqual(dlg.flutesEdit.text(), "2")
        self.assertEqual(dlg.diameterEdit.text(), "3 mm")
        self.assertEqual(dlg.lengthEdit.text(), "41 mm")
        self.clickOk(dlg)
        self.assertIsNot(dlg.cutter, orig_tool)
        self.assertEqual(dlg.cutter.diameter, orig_tool.diameter)
        self.assertEqual(dlg.cutter.length, orig_tool.length)
        self.assertEqual(dlg.cutter.flutes, orig_tool.flutes)
        dlg = gui.cutter_mgr.CreateEditCutterDialog(None, orig_tool)
        dlg.flutesEdit.setText("4")
        dlg.diameterEdit.setText("3.175")
        dlg.lengthEdit.setText("8")
        self.clickOk(dlg)
        self.assertIsNot(dlg.cutter, orig_tool)
        self.assertEqual(dlg.cutter.flutes, 4)
        self.assertEqual(dlg.cutter.diameter, 3.175)
        self.assertEqual(dlg.cutter.length, 8)

class CutterListDialogTest(CutterMgrTestBase):
    def testBrowseInventory(self):
        dlg = gui.cutter_mgr.SelectCutterDialog(None, self.document)
        self.verifyButtonUpdates(dlg, "inventory")
    def testButtonUpdates(self):
        cutter_name = "cheapo 2F 3.2/15"
        cutter_type = gui.inventory.EndMillCutter
        tool_data = gui.inventory.inventory.toolbitByName(cutter_name, cutter_type).newInstance()
        cycle = self.document.opAddCutter(tool_data)

        dlg = gui.cutter_mgr.SelectCutterDialog(None, self.document)
        self.verifyButtonUpdates(dlg, "inventory")
        self.verifyButtonUpdates(dlg, "project")
    def testEditCutterEM(self):
        self.verifyEditCutter("cheapo 2F 3.2/15", "pricey 4F 2/8", "carbide+TiN", gui.inventory.EndMillCutter, "\u23002 L8 carbide+TiN end mill")
    def testEditCutterDB(self):
        self.verifyEditCutter("3mm HSS", "2mm 4F HSS stubby", "HSSCo5", gui.inventory.DrillBitCutter, "2 mm HSSCo5 drill bit, L=8 mm")
    def verifyEditCutter(self, cutter_name, new_cutter_name, new_material, cutter_type, expected_str):
        tool_data = gui.inventory.inventory.toolbitByName(cutter_name, cutter_type).newInstance()
        self.assertIsNotNone(tool_data)
        cycle = self.document.opAddCutter(tool_data)
        def fakeExec(editDlg):
            editDlg.nameEdit.setText(new_cutter_name)
            editDlg.diameterEdit.setText("2")
            editDlg.materialCombo.setCurrentText(new_material)
            editDlg.flutesEdit.setText("4")
            editDlg.lengthEdit.setText("8")
            self.clickOk(editDlg)
            return True
        for variant in ['project', 'inventory']:
            dlg = gui.cutter_mgr.SelectCutterDialog(None, self.document)
            parent = getattr(dlg.tools, f"{variant}_toolbits")
            tool_item = self.findCutterItem(parent, cutter_name)
            self.assertIsNotNone(tool_item)
            dlg.tools.setCurrentItem(tool_item)
            gui.cutter_mgr.CreateEditCutterDialog.exec_ = fakeExec
            self.assertTrue(dlg.editButton.isEnabled())
            old_saves = saves
            QTest.keyClick(dlg.editButton, Qt.Key.Key_Space)
            self.assertEqual(saves, old_saves + 1 if variant == 'inventory' else old_saves)
            del gui.cutter_mgr.CreateEditCutterDialog.exec_
            tool_item = self.findCutterItem(parent, cutter_name)
            self.assertIsNone(tool_item)
            tool_item = self.findCutterItem(parent, new_cutter_name)
            self.assertIsNotNone(tool_item)
            content = tool_item.content if variant == 'inventory' else tool_item.content.cutter
            self.assertEqual(content.diameter, 2)
            self.assertEqual(content.flutes, 4)
            self.assertEqual(content.length, 8)
            self.assertIn(expected_str, content.description())
    def testDeleteCutterEM(self):
        self.verifyDeleteCutter("cheapo 2F 3.2/15", "Wood-finishing", gui.inventory.EndMillCutter)
    def testDeleteCutterDB(self):
        self.verifyDeleteCutter("3mm HSS", "Wood-untested", gui.inventory.DrillBitCutter)
    def verifyDeleteCutter(self, cutter_name, preset_name, cutter_type):
        orig_tool = gui.inventory.inventory.toolbitByName(cutter_name, cutter_type)
        self.assertIsNotNone(orig_tool)
        tool_copy = orig_tool.newInstance()
        self.assertIsNotNone(tool_copy)
        cycle = self.document.opAddCutter(tool_copy)
        self.document.opAddLibraryPreset(orig_tool.presetByName(preset_name))
        for variant in ['project', 'inventory']:
            dlg = gui.cutter_mgr.SelectCutterDialog(None, self.document)
            parent = getattr(dlg.tools, f"{variant}_toolbits")
            tool_item = self.findCutterItem(parent, cutter_name)
            self.assertIsNotNone(tool_item)
            preset_item = self.findPresetItem(tool_item, preset_name)
            self.assertIsNotNone(preset_item)
            dlg.tools.setCurrentItem(preset_item)
            self.assertTrue(dlg.deleteButton.isEnabled())
            for answer in [QMessageBox.No, QMessageBox.Yes]:
                msg = "This will delete the preset from the "
                msg += "project" if variant == 'project' else "global inventory"
                old_saves = saves
                with ExpectQuestion(self, msg, answer):
                    QTest.keyClick(dlg.deleteButton, Qt.Key.Key_Space)
                self.assertEqual(saves, old_saves + 1 if variant == 'inventory' and answer == QMessageBox.Yes else old_saves)
                # this invalidates the tool_item/preset_item due to refresh
                tool_item = self.findCutterItem(parent, cutter_name)
                preset_item = self.findPresetItem(tool_item, preset_name)
                self.assertEqual(preset_item is not None, answer == QMessageBox.No)
                if variant == 'inventory':
                    self.assertEqual(gui.inventory.inventory.toolbitByName(cutter_name).presetByName(preset_name) is not None, answer == QMessageBox.No)
                else:
                    self.assertEqual(self.document.project_toolbits[cutter_name].presetByName(preset_name) is not None, answer == QMessageBox.No)
            tool_item = self.findCutterItem(parent, cutter_name)
            self.assertIsNotNone(tool_item)
            dlg.tools.setCurrentItem(tool_item)
            self.assertTrue(dlg.deleteButton.isEnabled())
            for answer in [QMessageBox.No, QMessageBox.Yes]:
                msg = "This will delete the cutter"
                old_saves = saves
                with ExpectQuestion(self, msg, answer):
                    QTest.keyClick(dlg.deleteButton, Qt.Key.Key_Space)
                self.assertEqual(saves, old_saves + 1 if variant == 'inventory' and answer == QMessageBox.Yes else old_saves)
                tool_item = self.findCutterItem(parent, cutter_name)
                self.assertEqual(tool_item is not None, answer == QMessageBox.No)
                if variant == 'inventory':
                    self.assertEqual(gui.inventory.inventory.toolbitByName(cutter_name) is not None, answer == QMessageBox.No)
                else:
                    self.assertEqual(self.document.allCycles() != [], answer == QMessageBox.No)
                    self.assertEqual(cutter_name in self.document.project_toolbits, answer == QMessageBox.No)
    def testAddCutterEM(self):
        self.verifyAddCutter("New endmill", gui.inventory.EndMillCutter)
    def testAddCutterDB(self):
        self.verifyAddCutter("New drill bit", gui.inventory.DrillBitCutter)
    def verifyAddCutter(self, cutter_name, cutter_type):
        preset_name = "Test preset"
        def fakeExecCutter(addDlg):
            addDlg.nameEdit.setText(cutter_name)
            addDlg.diameterEdit.setText("2")
            addDlg.flutesEdit.setText("3")
            addDlg.lengthEdit.setText("12")
            self.clickOk(addDlg)
            return True
        def fakeExecPreset(addDlg):
            addDlg.prop_controls[gui.model.ToolPresetTreeItem.prop_name].setText(preset_name)
            self.clickOk(addDlg)
            self.assertIsNotNone(addDlg.result)
            return True
        for variant in ['project', 'inventory']:
            dlg = gui.cutter_mgr.SelectCutterDialog(None, self.document)
            parent = getattr(dlg.tools, f"{variant}_toolbits")
            dlg.tools.setCurrentItem(parent)
            self.assertTrue(dlg.newButton.isEnabled())
            gui.cutter_mgr.CreateEditCutterDialog.exec_ = fakeExecCutter
            QTest.keyClick(dlg.newButton, Qt.Key.Key_Space)
            del gui.cutter_mgr.CreateEditCutterDialog.exec_
            tool_item = self.findCutterItem(parent, cutter_name)
            self.assertIsNotNone(tool_item)
            self.assertIs(dlg.tools.selectedItem(), tool_item.content)
            cutter = tool_item.content.cutter if variant == 'project' else tool_item.content
            self.assertEqual(cutter.diameter, 2)
            self.assertEqual(cutter.flutes, 3)
            self.assertEqual(cutter.length, 12)
            if variant == 'inventory':
                self.assertIsNotNone(gui.inventory.inventory.toolbitByName(cutter_name))
            else:
                self.assertIsNotNone(self.document.project_toolbits[cutter_name])
            self.assertTrue(dlg.newButton.isEnabled())
            gui.cutter_mgr.CreateEditPresetDialog.exec_ = fakeExecPreset
            QTest.keyClick(dlg.newButton, Qt.Key.Key_Space)
            del gui.cutter_mgr.CreateEditPresetDialog.exec_
            
    def findCutterItem(self, parent, cutter_name):
        for i in range(parent.childCount()):
            tool_item = parent.child(i)
            if tool_item.data(1, Qt.DisplayRole) == cutter_name:
                return tool_item
    def findPresetItem(self, tool_item, preset_name):
        # Same as for tools, but might change in future
        for i in range(tool_item.childCount()):
            preset_item = tool_item.child(i)
            if preset_item.data(1, Qt.DisplayRole) == preset_name:
                return preset_item
    def verifyButtonUpdates(self, dlg, where):
        tools = dlg.tools
        parent = getattr(tools, f"{where}_toolbits")
        tools.setCurrentItem(parent)
        self.verifyButtonState(dlg, True, False, False)
        self.verifyButtonTexts(dlg, f"&Add cutter ({where})...", "Modify...", "Delete")
        for i in range(parent.childCount()):
            tool_item = parent.child(i)
            tools.setCurrentItem(tool_item)
            self.assertEqual(tool_item.is_global, where == 'inventory')
            self.verifyButtonState(dlg, True, True, True)
            if where == 'inventory':
                self.verifyButtonTexts(dlg, f"&Add preset...", "&Modify cutter...", "&Delete cutter")
            else:
                self.verifyButtonTexts(dlg, f"&Add preset...", "&Modify cutter...", "&Delete cycle/cutter")
            for j in range(tool_item.childCount()):
                preset_item = tool_item.child(j)
                tools.setCurrentItem(preset_item)
                self.assertEqual(preset_item.is_global, where == 'inventory')
                self.verifyButtonState(dlg, True, True, True)
                self.verifyButtonTexts(dlg, f"&Duplicate preset...", "&Modify preset...", "&Delete preset")
    def verifyButtonState(self, dlg, newEnabled, editEnabled, deleteEnabled):
        self.assertEqual(dlg.newButton.isEnabled(), newEnabled)
        self.assertEqual(dlg.editButton.isEnabled(), editEnabled)
        self.assertEqual(dlg.deleteButton.isEnabled(), deleteEnabled)
    def verifyButtonTexts(self, dlg, newText, editText, deleteText):
        self.assertEqual(dlg.newButton.text(), newText)
        self.assertEqual(dlg.editButton.text(), editText)
        self.assertEqual(dlg.deleteButton.text(), deleteText)

unittest.main()

del app
