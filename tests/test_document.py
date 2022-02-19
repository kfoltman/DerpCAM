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
        { "_type": "EndMillCutter", "id": 1036, "name": "test cutter", "material": "carbide", "diameter": 4, "length": 10.0, "flutes": 4 },
    ],
    "tool_presets": [
        { "_type": "EndMillPreset", "id": 1037, "name" : "test preset", "toolbit": 1036,
          "rpm": 16000, "hfeed": 500, "vfeed": 100, "maxdoc": 0.5, "stepover": 0.4, "direction": 1, "extra_width": 0.15, "trc_rate": 0.9, },
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
        
        self.assertIsInstance(doc.tool_list.child(0), gui.model.ToolTreeItem)
        self.assertEqual(doc.tool_list.child(0).rowCount(), 1)
        self.assertIsInstance(doc.tool_list.child(0).child(0), gui.model.ToolPresetTreeItem)
        
        self.assertEqual(doc.drawing.x_offset, 10)
        self.assertEqual(doc.drawing.y_offset, 20)
        self.assertEqual(doc.drawing.rowCount(), 1)
        self.assertIsInstance(doc.drawing.child(0), gui.model.DrawingCircleTreeItem)
        self.assertEqual(doc.drawing.child(0).centre.x, -40)
        self.assertEqual(doc.drawing.child(0).centre.y, -30)
        self.assertEqual(doc.drawing.child(0).r, 15)
        toolbit = doc.project_toolbits["test cutter"]
        self.assertEqual(toolbit.name, "test cutter")
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
        self.assertEqual(doc.default_preset_by_tool, {toolbit:preset})
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

unittest.main()
