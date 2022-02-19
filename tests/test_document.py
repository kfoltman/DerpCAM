import os.path
import sys
import threading
import time
import unittest
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import geom
import gui.inventory
import gui.model

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtTest import *

testDocument1={
    "material": { "_type": "WorkpieceTreeItem", "material": 1, "thickness": 5, "clearance": 6, "safe_entry_z": 2 },
    "tools": [
        { "_type": "EndMillCutter", "id": 1036, "name": "test cutter", "material": "carbide", "diameter": 6, "length": 10.0, "flutes": 4 },
    ],
    "tool_presets": [
        { "_type": "EndMillPreset", "id": 1037, "name" : "test preset", "toolbit": 1036,
          "rpm": 16000, "hfeed": 500, "vfeed": 100, "maxdoc": 0.5, "stepover": 0.4, "direction": 1, "extra_width": 0.15, "trc_rate": 0.9,
          "pocket_strategy" : 2, "axis_angle" : 45},
    ],
    "default_presets": [ { "tool_id": 1036, "preset_id": 1037 } ],
    "drawing": {
        "header": { "_type": "DrawingTreeItem", "x_offset": 10, "y_offset": 20 },
        "items": [ 
            { "_type": "DrawingCircleTreeItem", "shape_id": 9, "cx": -40, "cy": -30, "r": 15 },
        ],
    },
    "operation_cycles": [ 
        {
            "tool_id": 1036, "is_current": True, 
            "operations": [
                {
                    "_type": "OperationTreeItem",
                    "operation": 4,
                    "cutter": 1036,
                    "tool_preset": 1037,
                    "shape_id": 9,
                },
            ],
        },
    ],
}

app = QApplication(sys.argv)

class DocumentTest(unittest.TestCase):
    def setUp(self):
        self.document = gui.model.DocumentModel()
    def tearDown(self):
        del self.document
    def testEmptyDoc(self):
        self.verifyEmptyDocument()
    def testLoadDocument(self):
        self.document.load(testDocument1)
        self.document.cancelAllWorkers()
        self.document.waitForUpdateCAM()
        self.verifyAnyDocument()
        doc = self.document
        self.assertEqual(doc.material.thickness, 5)
        self.assertEqual(doc.material.clearance, 6)
        self.assertEqual(doc.material.safe_entry_z, 2)
        self.assertEqual(doc.tool_list.rowCount(), 1)
        
        toolItem = doc.tool_list.child(0)
        self.assertIsInstance(toolItem, gui.model.ToolTreeItem)
        self.assertEqual(toolItem.rowCount(), 1)
        self.assertEqual(toolItem.getPropertyValue('name'), "test cutter")
        self.assertEqual(toolItem.getPropertyValue('flutes'), 4)
        self.assertEqual(toolItem.getPropertyValue('diameter'), 6)
        self.assertEqual(toolItem.getPropertyValue('length'), 10)
        presetItem = toolItem.child(0)
        self.assertIsInstance(presetItem, gui.model.ToolPresetTreeItem)
        self.assertEqual(presetItem.getPropertyValue('vfeed'), 100)
        self.assertEqual(presetItem.getPropertyValue('hfeed'), 500)
        self.assertEqual(presetItem.getPropertyValue('depth'), 0.5)
        self.assertEqual(presetItem.getPropertyValue('stepover'), 40)
        self.assertEqual(presetItem.getPropertyValue('extra_width'), 15)
        self.assertEqual(presetItem.getPropertyValue('trc_rate'), 90)
        self.assertEqual(presetItem.getPropertyValue('direction'), gui.inventory.MillDirection.CLIMB)
        self.assertEqual(presetItem.getPropertyValue('pocket_strategy'), gui.inventory.PocketStrategy.AXIS_PARALLEL)
        self.assertEqual(presetItem.getPropertyValue('axis_angle'), 45)
        
        self.assertEqual(doc.drawing.x_offset, 10)
        self.assertEqual(doc.drawing.y_offset, 20)
        self.assertEqual(doc.drawing.rowCount(), 1)
        circle = doc.drawing.child(0)
        self.assertIsInstance(circle, gui.model.DrawingCircleTreeItem)
        self.assertEqual(circle.centre.x, -40)
        self.assertEqual(circle.centre.y, -30)
        self.assertEqual(circle.r, 15)
        self.assertEqual(circle.getPropertyValue("x"), -40)
        self.assertEqual(circle.getPropertyValue("y"), -30)
        self.assertEqual(circle.getPropertyValue("radius"), 15)
        self.assertEqual(circle.getPropertyValue("diameter"), 30)
        toolbit = doc.project_toolbits["test cutter"]
        self.assertEqual(toolbit.name, "test cutter")
        self.assertEqual(toolbit.diameter, 6)
        self.assertEqual(toolbit.flutes, 4)
        self.assertEqual(toolbit.length, 10)
        self.assertEqual(len(doc.project_toolbits), 1)
        preset = toolbit.presets[0]
        self.assertEqual(preset.toolbit, toolbit)
        self.assertEqual(preset.name, "test preset")
        self.assertEqual(preset.vfeed, 100)
        self.assertEqual(preset.hfeed, 500)
        self.assertEqual(preset.maxdoc, 0.5)
        self.assertEqual(preset.stepover, 0.4)
        self.assertEqual(preset.extra_width, 0.15)
        self.assertEqual(preset.trc_rate, 0.9)
        self.assertEqual(preset.direction, gui.inventory.MillDirection.CLIMB)
        self.assertEqual(preset.pocket_strategy, gui.inventory.PocketStrategy.AXIS_PARALLEL)
        self.assertEqual(preset.axis_angle, 45)
        self.assertEqual(preset.axis_angle, 45)
        self.assertEqual(doc.default_preset_by_tool, {toolbit:preset})
    def testPropertyChangesCircle(self):
        self.document.load(testDocument1)
        self.document.cancelAllWorkers()
        self.document.waitForUpdateCAM()
        self.verifyAnyDocument()
        doc = self.document
        circle = doc.drawing.child(0)
        self.assertEqual(circle.label(), "Circle9")
        self.assertIsInstance(circle, gui.model.DrawingCircleTreeItem)
        doc.opChangeProperty(circle.prop_dia, [(circle, 40)])
        self.assertEqual(circle.getPropertyValue("radius"), 20)
        self.assertEqual(circle.getPropertyValue("diameter"), 40)
        doc.opChangeProperty(circle.prop_radius, [(circle, 10)])
        self.assertEqual(circle.getPropertyValue("radius"), 10)
        self.assertEqual(circle.getPropertyValue("diameter"), 20)
        doc.undo()
        self.assertEqual(circle.getPropertyValue("radius"), 20)
        self.assertEqual(circle.getPropertyValue("diameter"), 40)
        doc.undo()
        self.assertEqual(circle.getPropertyValue("radius"), 15)
        self.assertEqual(circle.getPropertyValue("diameter"), 30)
        doc.redo()
        self.assertEqual(circle.getPropertyValue("radius"), 20)
        self.assertEqual(circle.getPropertyValue("diameter"), 40)
        doc.redo()
        self.assertEqual(circle.getPropertyValue("radius"), 10)
        self.assertEqual(circle.getPropertyValue("diameter"), 20)
        doc.opChangeProperty(circle.prop_x, [(circle, 100)])
        doc.opChangeProperty(circle.prop_y, [(circle, 150)])
        self.assertEqual(circle.getPropertyValue("x"), 100)
        self.assertEqual(circle.getPropertyValue("y"), 150)
        doc.undo()
        self.assertEqual(circle.getPropertyValue("y"), -30)
        doc.undo()
        self.assertEqual(circle.getPropertyValue("x"), -40)
    def testPropertyChangesMaterial(self):
        self.document.load(testDocument1)
        self.document.cancelAllWorkers()
        self.document.waitForUpdateCAM()
        self.verifyAnyDocument()
        doc = self.document
        material = doc.material
        self.verifyPropertyOp(material, "thickness", 5, 8, "5.00 mm")
        self.verifyPropertyOp(material, "clearance", 6, 8, "6.00 mm")
        self.verifyPropertyOp(material, "safe_entry_z", 2, 3, "2.00 mm")
        doc.opChangeProperty(material.prop_clearance, [(material, 4)])
        doc.opChangeProperty(material.prop_safe_entry_z, [(material, 1.5)])
        self.verifyAnyDocument()
        doc.undo()
        doc.undo()
        self.verifyAnyDocument()
        doc.redo()
        doc.redo()
        self.verifyAnyDocument()
    def testPropertyChangesTool(self):
        self.document.load(testDocument1)
        self.document.cancelAllWorkers()
        self.document.waitForUpdateCAM()
        self.verifyAnyDocument()
        doc = self.document
        tool = doc.tool_list.child(0)
        self.verifyPropertyOp(tool, "diameter", 6, 8, "6.00 mm")
        self.verifyPropertyOp(tool, "flutes", 4, 2, "4")
        self.verifyPropertyOp(tool, "length", 10, 20, "10.0 mm")
        self.assertEqual(tool.childList(), [tool.child(0).inventory_preset])
    def testPropertyChangesPreset(self):
        self.document.load(testDocument1)
        self.document.cancelAllWorkers()
        self.document.waitForUpdateCAM()
        self.verifyAnyDocument()
        doc = self.document
        tool = doc.tool_list.child(0)
        preset = tool.child(0)
        self.assertEqual(doc.itemForCutter(tool.inventory_tool), tool)
        self.assertEqual(doc.itemForPreset(preset.inventory_preset), preset)
        self.verifyPropertyOp(preset, "depth", 0.5, 1, "0.50 mm")
        self.verifyPropertyOp(preset, "rpm", 16000, 12000, "16000 rev/min")
        self.verifyPropertyOp(preset, "hfeed", 500, 750, "500.0 mm/min")
        self.verifyPropertyOp(preset, "vfeed", 100, 150, "100.0 mm/min")
        self.verifyPropertyOp(preset, "stepover", 40, 60, "40.0 %")
        self.verifyPropertyOp(preset, "direction", 1, 0, "Climb")
        self.verifyPropertyOp(preset, "extra_width", 15, 50, "15.0 %")
        self.verifyPropertyOp(preset, "trc_rate", 90, 9, "90.0 %")
        self.verifyPropertyOp(preset, "pocket_strategy", 2, 1, "Axis-parallel (v. slow)")
        self.verifyPropertyOp(preset, "axis_angle", 45, 60, "45.0 \u00b0")
    def verifyPropertyOp(self, item, prop_name, orig_value, new_value, orig_display=None):
        doc = self.document
        prop = [p for p in item.properties() if p.attribute == prop_name][0]
        if orig_display is not None:
            self.assertEqual(prop.toDisplayString(prop.getData(item)), orig_display)
        self.assertEqual(prop.getData(item), orig_value)
        doc.opChangeProperty(prop, [(item, new_value)])
        self.assertEqual(prop.getData(item), new_value)
        if isinstance(item, gui.model.ToolPresetTreeItem):
            saved = item.inventory_preset.newInstance()
        doc.undo()
        self.assertEqual(prop.getData(item), orig_value)
        doc.redo()
        self.assertEqual(prop.getData(item), new_value)
        if isinstance(item, gui.model.ToolPresetTreeItem):
            doc.undo()
            doc.opModifyPreset(item.inventory_preset, saved)
            self.assertEqual(prop.getData(item), new_value)
            doc.undo()
            self.assertEqual(prop.getData(item), orig_value)
            doc.redo()
            self.assertEqual(prop.getData(item), new_value)
    def testReinitDocument(self):
        self.document.load(testDocument1)
        self.document.reinitDocument()
        self.verifyEmptyDocument()
    def verifyAnyDocument(self):
        doc = self.document
        self.assertIs(doc.material.model(), doc.shapeModel)
        self.assertEqual(doc.material.row(), 0)
        self.assertIs(doc.tool_list.model(), doc.shapeModel)
        self.assertEqual(doc.tool_list.row(), 1)
        self.assertIs(doc.drawing.model(), doc.shapeModel)
        self.assertEqual(doc.drawing.row(), 2)
        self.assertEqual(doc.shapeModel.rowCount(), 3)
        self.assertEqual(doc.gcode_machine_params.safe_z, doc.material.clearance)
        self.assertEqual(doc.gcode_machine_params.semi_safe_z, doc.material.safe_entry_z)
        self.assertEqual(doc.progress_dialog_displayed, False)
        self.assertIsNone(doc.update_suspended)
        self.assertFalse(doc.update_suspended_dirty)
    def verifyEmptyDocument(self):
        self.verifyAnyDocument()
        doc = self.document
        self.assertEqual(doc.operModel.rowCount(), 0)
        self.assertIsNone(doc.drawing_filename)
        self.assertIsNone(doc.current_cutter_cycle)
        self.assertEqual(doc.project_toolbits, {})
        self.assertEqual(doc.default_preset_by_tool, {})

class PDATest(unittest.TestCase):
    def setUp(self):
        self.document = gui.model.DocumentModel()
    def testToPresetEM(self):
        op = gui.model.OperationTreeItem(self.document)
        op.cutter = gui.inventory.EndMillCutter.new(None, "test cutter", gui.inventory.CutterMaterial.HSS, 4, 15, 3)
        op.rpm = 18000
        op.vfeed = 200
        op.hfeed = 700
        op.doc = 1.5
        op.stepover = 40
        op.extra_width = 90
        op.trc_rate = 50
        op.direction = gui.inventory.MillDirection.CLIMB
        op.pocket_strategy = gui.inventory.PocketStrategy.AXIS_PARALLEL
        op.axis_angle = 30
        pda = gui.model.PresetDerivedAttributes(op)
        errors = []
        pda.validate(errors)
        self.assertEqual(errors, [])
        preset = pda.toPreset("new preset")
        self.assertIsInstance(preset, gui.inventory.EndMillPreset)
        self.assertEqual(preset.name, "new preset")
        self.assertEqual(preset.rpm, 18000)
        self.assertEqual(preset.vfeed, 200)
        self.assertEqual(preset.hfeed, 700)
        self.assertEqual(preset.maxdoc, 1.5)
        self.assertEqual(preset.stepover, 0.4)
        self.assertEqual(preset.extra_width, 0.9)
        self.assertEqual(preset.trc_rate, 0.5)
        self.assertEqual(preset.direction, gui.inventory.MillDirection.CLIMB)
        self.assertEqual(preset.pocket_strategy, gui.inventory.PocketStrategy.AXIS_PARALLEL)
        self.assertEqual(preset.axis_angle, 30)
        pda.resetPresetDerivedValues(op)
        op.tool_preset = preset
        pda = gui.model.PresetDerivedAttributes(op)
        self.verifyAttribute(op, pda, 'rpm', 18000, 20000)
        self.verifyAttribute(op, pda, 'vfeed', 200, 300)
        self.verifyAttribute(op, pda, 'hfeed', 700, 800)
        self.verifyAttribute(op, pda, 'doc', 1.5, 2)
        self.verifyAttribute(op, pda, 'stepover', 40, 41)
        self.verifyAttribute(op, pda, 'extra_width', 90, 91)
        self.verifyAttribute(op, pda, 'trc_rate', 50, 51)
        self.verifyAttribute(op, pda, 'direction', gui.inventory.MillDirection.CLIMB, gui.inventory.MillDirection.CONVENTIONAL)
        self.verifyAttribute(op, pda, 'pocket_strategy', gui.inventory.PocketStrategy.AXIS_PARALLEL, gui.inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG)
        self.verifyAttribute(op, pda, 'axis_angle', 30, 35)
    def verifyAttribute(self, op, pda, name, value, alt_value):
        mapping = {}
        op_name = mapping.get(name, name)
        self.assertEqual(getattr(pda, name), value)
        self.assertEqual(getattr(op, op_name), None)
        pda2 = gui.model.PresetDerivedAttributes(op)
        self.assertFalse(pda2.dirty, name)
        try:
            setattr(op, op_name, alt_value)
            pda2 = gui.model.PresetDerivedAttributes(op)
            self.assertTrue(pda2.dirty, name)
        finally:
            setattr(op, op_name, None)

unittest.main()
