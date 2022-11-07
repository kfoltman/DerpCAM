import os.path
import sys
import math
import unittest
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from DerpCAM.common import geom
from DerpCAM import gui
import DerpCAM.gui.inventory
import DerpCAM.gui.model
import DerpCAM.gui.settings

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QSignalSpy

testDocument1 = {
    "material": { "_type": "WorkpieceTreeItem", "material": 1, "thickness": 5, "clearance": 6, "safe_entry_z": 2 },
    "tools": [
        { "_type": "EndMillCutter", "id": 1036, "name": "test cutter", "material": "carbide", "diameter": 6, "length": 10.0, "flutes": 4 },
    ],
    "tool_presets": [
        { "_type": "EndMillPreset", "id": 1037, "name" : "test preset", "toolbit": 1036,
          "rpm": 16000, "hfeed": 500, "vfeed": 100, "maxdoc": 0.5, "stepover": 0.4, "offset" : 0, "direction": 1, "extra_width": 0.15, "trc_rate": 0.9,
          "pocket_strategy" : 2, "axis_angle" : 45},
    ],
    "default_presets": [ { "tool_id": 1036, "preset_id": 1037 } ],
    "drawing": {
        "header": { "_type": "DrawingTreeItem", "x_offset": 10, "y_offset": 20 },
        "items": [ 
            { "_type": "DrawingCircleTreeItem", "shape_id": 9, "cx": -40, "cy": -30, "r": 15 },
            { "_type": "DrawingPolylineTreeItem", "shape_id": 15, "points": [[200, 0], [250, 0], [250, 50], [200, 50]], "closed": True},
            { "_type": "DrawingPolylineTreeItem", "shape_id": 23, "points": [[100, 0], [150, 50]], "closed": False},
            { "_type": "DrawingPolylineTreeItem", "shape_id": 24, "points": [[100, 0], ["ARC_CCW", [100, 0], [0, 100], [0, 0, 100], 50, 0, math.pi / 2]], "closed": False},
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

testDocument2 = {
    "material": { "_type": "WorkpieceTreeItem", "material": 1, "thickness": 5, "clearance": 6, "safe_entry_z": 2 },
    "tools": [],
    "tool_presets": [],
    "default_presets": [],
    "drawing": {
        "header": { "_type": "DrawingTreeItem", "x_offset": 10, "y_offset": 20 },
        "items": [
            { "_type": "DrawingCircleTreeItem", "shape_id": 1, "cx": 0, "cy": 0, "r": 15 },
            { "_type": "DrawingCircleTreeItem", "shape_id": 2, "cx": 0, "cy": 0, "r": 30 },
            { "_type": "DrawingCircleTreeItem", "shape_id": 3, "cx": 0, "cy": 0, "r": 8 },
            { "_type": "DrawingPolylineTreeItem", "shape_id": 4, "points": [[-50, 0], [50, 0]], "closed": False},
            { "_type": "DrawingPolylineTreeItem", "shape_id": 5, "points": [[200, 0], [250, 0], [250, 50], [200, 50]], "closed": True},
            { "_type": "DrawingPolylineTreeItem", "shape_id": 6, "points": [[220, 10], [240, 10], [240, 40], [210, 40]], "closed": True},
        ],
    },
    "operation_cycles": [],
}

app = QApplication(sys.argv)
config_settings = gui.settings.ConfigSettings()

class DocumentTest(unittest.TestCase):
    def setUp(self):
        self.document = gui.model.DocumentModel(config_settings)
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
        self.assertEqual(presetItem.getPropertyValue('doc'), 0.5)
        self.assertEqual(presetItem.getPropertyValue('offset'), 0)
        self.assertEqual(presetItem.getPropertyValue('stepover'), 40)
        self.assertEqual(presetItem.getPropertyValue('extra_width'), 15)
        self.assertEqual(presetItem.getPropertyValue('trc_rate'), 90)
        self.assertEqual(presetItem.getPropertyValue('direction'), gui.inventory.MillDirection.CLIMB)
        self.assertEqual(presetItem.getPropertyValue('pocket_strategy'), gui.inventory.PocketStrategy.AXIS_PARALLEL)
        self.assertEqual(presetItem.getPropertyValue('axis_angle'), 45)
        
        self.assertEqual(doc.drawing.x_offset, 10)
        self.assertEqual(doc.drawing.y_offset, 20)
        self.assertEqual(doc.drawing.rowCount(), 4)
        circle = doc.drawing.child(0)
        self.assertIsInstance(circle, gui.model.DrawingCircleTreeItem)
        self.assertEqual(circle.centre.x, -40)
        self.assertEqual(circle.centre.y, -30)
        self.assertEqual(circle.r, 15)
        self.assertEqual(circle.getPropertyValue("x"), -40)
        self.assertEqual(circle.getPropertyValue("y"), -30)
        self.assertEqual(circle.getPropertyValue("radius"), 15)
        self.assertEqual(circle.getPropertyValue("diameter"), 30)
        self.assertEqual(circle.translated(15, 25).getPropertyValue("x"), -25)
        self.assertEqual(circle.translated(15, 25).getPropertyValue("y"), -5)
        self.assertEqual(circle.translated(15, 25).getPropertyValue("diameter"), 30)
        self.assertEqual(circle.scaled(0, 0, 2).getPropertyValue("x"), -80)
        self.assertEqual(circle.scaled(0, 0, 2).getPropertyValue("y"), -60)
        self.assertEqual(circle.scaled(0, 0, 2).getPropertyValue("diameter"), 60)
        poly = doc.drawing.child(1)
        self.assertEqual(poly.closed, True)
        self.assertEqual(len(poly.points), 4)
        self.assertEqual(poly.points, [geom.PathPoint(200, 0), geom.PathPoint(250, 0), geom.PathPoint(250, 50), geom.PathPoint(200, 50)])
        self.assertEqual(poly.translated(20, 10).points, [geom.PathPoint(220, 10), geom.PathPoint(270, 10), geom.PathPoint(270, 60), geom.PathPoint(220, 60)])
        self.assertEqual(poly.scaled(200, 0, 2).points, [geom.PathPoint(200, 0), geom.PathPoint(300, 0), geom.PathPoint(300, 100), geom.PathPoint(200, 100)])
        self.assertEqual(poly.label(), "Polyline15")
        self.assertIn("Polyline15(200, 0)-(250, 50)", poly.textDescription())
        shape = poly.toShape()
        self.assertEqual(shape.boundary, [geom.PathPoint(200, 0), geom.PathPoint(250, 0), geom.PathPoint(250, 50), geom.PathPoint(200, 50)])
        self.assertEqual(shape.closed, True)
        poly = doc.drawing.child(2)
        self.assertEqual(poly.closed, False)
        self.assertEqual(len(poly.points), 2)
        self.assertEqual(poly.points, [geom.PathPoint(100, 0), geom.PathPoint(150, 50)])
        self.assertEqual(poly.translated(20, 10).points, [geom.PathPoint(120, 10), geom.PathPoint(170, 60)])
        self.assertEqual(poly.scaled(50, 10, 2).points, [geom.PathPoint(150, -10), geom.PathPoint(250, 90)])
        self.assertEqual(poly.label(), "Line23")
        self.assertIn("Line23(100, 0)-(150, 50)", poly.textDescription())
        shape = poly.toShape()
        self.assertEqual(shape.boundary, [geom.PathPoint(100, 0), geom.PathPoint(150, 50)])
        self.assertEqual(shape.closed, False)
        poly = doc.drawing.child(3)
        self.assertEqual(poly.closed, False)
        self.assertEqual(len(poly.points), 2)
        self.assertEqual(poly.points, [geom.PathPoint(100, 0), geom.PathArc(geom.PathPoint(100, 0), geom.PathPoint(0, 100), geom.CandidateCircle(0, 0, 100), 50, 0, math.pi / 2)])
        self.assertEqual(poly.translated(50, 25).points, [geom.PathPoint(150, 25), geom.PathArc(geom.PathPoint(150, 25), geom.PathPoint(50, 125), geom.CandidateCircle(50, 25, 100), 50, 0, math.pi / 2)])
        self.assertEqual(poly.scaled(0, 0, 2).points, [geom.PathPoint(200, 0), geom.PathArc(geom.PathPoint(200, 0), geom.PathPoint(0, 200), geom.CandidateCircle(0, 0, 200), 50, 0, math.pi / 2)])
        self.assertEqual(poly.label(), "Arc24")
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
        self.assertEqual(preset.offset, 0)
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
        self.verifyPropertyOp(material, "thickness", 5, 8, "5 mm")
        self.verifyPropertyOp(material, "clearance", 6, 8, "6 mm")
        self.verifyPropertyOp(material, "safe_entry_z", 2, 3, "2 mm")
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
        self.verifyPropertyOp(tool, "diameter", 6, 8, "6 mm")
        self.verifyPropertyOp(tool, "flutes", 4, 2, "4")
        self.verifyPropertyOp(tool, "length", 10, 20, "10 mm")
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
        self.verifyPropertyOp(preset, "doc", 0.5, 1, "0.5 mm")
        self.verifyPropertyOp(preset, "rpm", 16000, 12000, "16000 rpm")
        self.verifyPropertyOp(preset, "hfeed", 500, 750, "500 mm/min")
        self.verifyPropertyOp(preset, "vfeed", 100, 150, "100 mm/min")
        self.verifyPropertyOp(preset, "offset", 0, 0.2, "0 mm")
        self.verifyPropertyOp(preset, "stepover", 40, 60, "40 %")
        self.verifyPropertyOp(preset, "direction", 1, 0, "Climb")
        self.verifyPropertyOp(preset, "extra_width", 15, 50, "15 %")
        self.verifyPropertyOp(preset, "trc_rate", 90, 9, "90 %")
        self.verifyPropertyOp(preset, "pocket_strategy", 2, 1, "Axis-parallel (v. slow)")
        self.verifyPropertyOp(preset, "axis_angle", 45, 60, "45 \u00b0")
    def verifyPropertyOp(self, item, prop_name, orig_value, new_value, orig_display=None):
        doc = self.document
        prop = [p for p in item.properties() if p.attribute == prop_name][0]
        if orig_display is not None:
            self.assertEqual(prop.toDisplayString(prop.getData(item)), orig_display)
        self.assertEqual(prop.getData(item), orig_value)
        doc.opChangeProperty(prop, [(item, new_value)])
        self.assertEqual(prop.getData(item), new_value)
        if isinstance(item, gui.model.ToolTreeItem):
            saved = item.inventory_tool.newInstance()
        elif isinstance(item, gui.model.ToolPresetTreeItem):
            saved = item.inventory_preset.newInstance()
        doc.undo()
        self.assertEqual(prop.getData(item), orig_value)
        doc.redo()
        self.assertEqual(prop.getData(item), new_value)
        if isinstance(item, gui.model.ToolTreeItem):
            doc.undo()
            doc.opModifyCutter(item.inventory_tool, saved)
            self.assertEqual(prop.getData(item), new_value)
            doc.undo()
            self.assertEqual(prop.getData(item), orig_value)
            doc.redo()
            self.assertEqual(prop.getData(item), new_value)
        elif isinstance(item, gui.model.ToolPresetTreeItem):
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
    def testAddCutter(self):
        doc = self.document
        self.verifyAnyDocument()
        cutter = gui.inventory.EndMillCutter.new(None, "added cutter", gui.inventory.CutterMaterial.HSS, 4, 15, 3, gui.inventory.EndMillShape.FLAT, None, None)
        self.verifyCutter(cutter, "added cutter: 3F \u23004 L15 HSS flat end mill")
        cutter = gui.inventory.DrillBitCutter.new(None, "added drill bit", gui.inventory.CutterMaterial.HSS, 3.175, 33)
        self.verifyCutter(cutter, "added drill bit: 3.175 mm HSS drill bit, L=33 mm")
        doc.load(testDocument1)
        doc.cancelAllWorkers()
        doc.waitForUpdateCAM()
        self.verifyAnyDocument()
        cutter = gui.inventory.EndMillCutter.new(None, "added cutter", gui.inventory.CutterMaterial.HSS, 4, 15, 3, gui.inventory.EndMillShape.FLAT, None, None)
        self.verifyCutter(cutter, "added cutter: 3F \u23004 L15 HSS flat end mill")
        cutter = gui.inventory.DrillBitCutter.new(None, "added drill bit", gui.inventory.CutterMaterial.HSS, 3.3, 33)
        self.verifyCutter(cutter, "added drill bit: 3.3 mm HSS drill bit, L=33 mm")
    def testChangeActive(self):
        doc = self.document
        doc.load(testDocument1)
        doc.cancelAllWorkers()
        doc.waitForUpdateCAM()
        cycle = doc.allCycles()[0]
        self.assertEqual(cycle.checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        doc.opChangeActive([(cycle.child(0), False)])
        self.assertEqual(cycle.checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Unchecked)
        doc.undo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        doc.redo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Unchecked)
        cycle.setCheckState(Qt.CheckState.Checked)
        self.assertEqual(cycle.checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        doc.undo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Unchecked)
        doc.redo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        doc.opCreateOperation({9: []}, gui.model.OperationType.POCKET, cycle)
        doc.cancelAllWorkers()
        doc.waitForUpdateCAM()
        self.assertEqual(cycle.checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Checked)
        doc.opChangeActive([(cycle.child(1), False)])
        self.assertEqual(cycle.checkState(), Qt.CheckState.PartiallyChecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Unchecked)
        doc.undo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Checked)
        doc.redo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.PartiallyChecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Unchecked)
        cycle.setCheckState(Qt.CheckState.Checked)
        self.assertEqual(cycle.checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Checked)
        doc.undo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.PartiallyChecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Unchecked)
        doc.redo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Checked)
        cycle.setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(cycle.checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Unchecked)
        doc.opChangeActive([(cycle.child(1), True)])
        self.assertEqual(cycle.checkState(), Qt.CheckState.PartiallyChecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Checked)
        doc.undo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Unchecked)
        doc.redo()
        self.assertEqual(cycle.checkState(), Qt.CheckState.PartiallyChecked)
        self.assertEqual(cycle.child(0).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(cycle.child(1).checkState(), Qt.CheckState.Checked)
    def verifyCutter(self, cutter, description):
        doc = self.document
        doc.opAddCutter(cutter)
        self.verifyAnyDocument()
        cycle = doc.cycleForCutter(cutter)
        self.assertIn(cycle, doc.allCycles())
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle.data(Qt.DisplayRole).value(), f"Use tool: {cutter.name}")
        item = doc.itemForCutter(cutter)
        self.assertIsNotNone(item)
        self.assertEqual(item.data(Qt.DisplayRole).value(), description)
        spy = QSignalSpy(doc.cutterSelected)
        doc.selectCutterCycle(cycle)
        self.assertEqual(len(spy), 1)
        self.assertEqual(doc.current_cutter_cycle, cycle)
        toolbit = [tb for tb in doc.getToolbitList(type(cutter)) if tb[0] == cutter.id][0]
        self.assertEqual(toolbit, (cutter.id, cutter.description()))
        doc.undo()
        self.assertIsNone(doc.cycleForCutter(cutter))
        self.assertIsNone(doc.itemForCutter(cutter))
        doc.redo()
        self.assertIs(doc.cycleForCutter(cutter), cycle)
        self.assertIs(doc.itemForCutter(cutter), item)
        self.assertIs(doc.itemForCutter(cutter).parent(), doc.tool_list)
        doc.opDeleteCycle(cycle)
        self.verifyAnyDocument()
        self.assertIsNone(doc.cycleForCutter(cutter))
        self.assertIsNone(doc.itemForCutter(cutter))
        doc.undo()
        self.assertIs(doc.cycleForCutter(cutter), cycle)
        self.assertIs(doc.itemForCutter(cutter), item)
        self.assertIs(doc.itemForCutter(cutter).parent(), doc.tool_list)
        doc.redo()
        self.assertIsNone(doc.cycleForCutter(cutter))
        self.assertIsNone(doc.itemForCutter(cutter))
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

class DrawingTest(unittest.TestCase):
    def setUp(self):
        self.document = gui.model.DocumentModel(config_settings)
        self.document.load(testDocument2)
        self.drawing = self.document.drawing
        self.selection = list(self.drawing.items())
    def testEngraveParser(self):
        outsides, actualSelection, warnings = self.drawing.parseSelection(self.selection, gui.model.OperationType.ENGRAVE)
        self.assertEqual(outsides, {i.shape_id: set() for i in self.selection})
        self.assertEqual(warnings, [])
    def testHoleParser(self):
        outsides, actualSelection, warnings = self.drawing.parseSelection(self.selection, gui.model.OperationType.DRILLED_HOLE)
        self.assertEqual(outsides, {i.shape_id: set() for i in self.selection if i.shape_id in [1, 2, 3]})
        self.assertEqual(warnings, ["Line4 is not a circle", "Polyline5 is not a circle", "Polyline6 is not a circle"])
        outsides, actualSelection, warnings = self.drawing.parseSelection(self.selection, gui.model.OperationType.INTERPOLATED_HOLE)
        self.assertEqual(outsides, {i.shape_id: set() for i in self.selection if i.shape_id in [1, 2, 3]})
        self.assertEqual(warnings, ["Line4 is not a circle", "Polyline5 is not a circle", "Polyline6 is not a circle"])
    def testContourParser(self):
        contourIds = {i.shape_id: set() for i in self.selection if i.shape_id in [1, 2, 3, 5, 6]}
        outsides, actualSelection, warnings = self.drawing.parseSelection(self.selection, gui.model.OperationType.OUTSIDE_CONTOUR)
        self.assertEqual(warnings, ["Line4 is not a closed shape"])
        self.assertEqual(outsides, contourIds)
        outsides, actualSelection, warnings = self.drawing.parseSelection(self.selection, gui.model.OperationType.INSIDE_CONTOUR)
        self.assertEqual(outsides, contourIds)
        self.assertEqual(warnings, ["Line4 is not a closed shape"])
    def testPocketParser(self):
        outsides, actualSelection, warnings = self.drawing.parseSelection(self.selection, gui.model.OperationType.POCKET)
        self.assertEqual(outsides, {2: set([1]), 5: set([6])})
        self.assertEqual(set([i.shape_id for i in actualSelection]), set([1, 2, 5, 6]))
        self.assertEqual(warnings, ["Line4 is not a closed shape"])
        outsides, actualSelection, warnings = self.drawing.parseSelection(self.selection, gui.model.OperationType.OUTSIDE_PEEL)
        self.assertEqual(outsides, {2: set([1]), 5: set([6])})
        self.assertEqual(set([i.shape_id for i in actualSelection]), set([1, 2, 5, 6]))
        self.assertEqual(warnings, ["Line4 is not a closed shape"])

class PDATest(unittest.TestCase):
    def setUp(self):
        self.document = gui.model.DocumentModel(config_settings)
    def testToPresetEM(self):
        op = gui.model.OperationTreeItem(self.document)
        op.cutter = gui.inventory.EndMillCutter.new(None, "test cutter", gui.inventory.CutterMaterial.HSS, 4, 15, 3, gui.inventory.EndMillShape.FLAT, None, None)
        self.verifyOpBlank(op)
        op.rpm = 18000
        op.vfeed = 200
        op.hfeed = 700
        op.doc = 1.5
        op.offset = 0.1
        op.stepover = 40
        op.extra_width = 90
        op.trc_rate = 50
        op.direction = gui.inventory.MillDirection.CLIMB
        op.pocket_strategy = gui.inventory.PocketStrategy.AXIS_PARALLEL
        op.axis_angle = 30
        op.eh_diameter = 80
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
        self.assertEqual(preset.offset, 0.1)
        self.assertEqual(preset.stepover, 0.4)
        self.assertEqual(preset.extra_width, 0.9)
        self.assertEqual(preset.trc_rate, 0.5)
        self.assertEqual(preset.direction, gui.inventory.MillDirection.CLIMB)
        self.assertEqual(preset.pocket_strategy, gui.inventory.PocketStrategy.AXIS_PARALLEL)
        self.assertEqual(preset.axis_angle, 30)
        self.assertEqual(preset.eh_diameter, 0.8)
        # Reset the operation's settings, verify that they are reset
        pda.resetPresetDerivedValues(op)
        self.verifyOpBlank(op)
        # Verify that applying a newly created preset on an empty operation
        # is equivalent to setting the values at the operation level.
        op.tool_preset = preset
        self.verifyOpValuesEM(op)
        self.verifyOpBlank(op)
        # Convert preset values to a dictionary (used by the preset editor dialog)
        # and create another preset from those values, verify that they are identical
        values = gui.model.PresetDerivedAttributes.valuesFromPreset(preset, type(preset.toolbit))
        preset2 = gui.model.PresetDerivedAttributes.toPresetFromAny("from dlg values", values, preset.toolbit, type(preset.toolbit))
        op.tool_preset = preset2
        self.verifyOpValuesEM(op)
        self.verifyOpBlank(op)
        # Modify one value and retest, just to be slightly on the paranoid side
        values['rpm'] = 22000
        preset2 = pda.toPresetFromAny("from dlg values", values, preset.toolbit, type(preset.toolbit))
        op.tool_preset = preset2
        pda = gui.model.PresetDerivedAttributes(op)
        self.verifyAttribute(op, pda, 'rpm', 22000, 20000)
    def testToPresetDB(self):
        op = gui.model.OperationTreeItem(self.document)
        op.cutter = gui.inventory.DrillBitCutter.new(None, "test cutter", gui.inventory.CutterMaterial.HSS, 4, 15, 3)
        self.verifyOpBlank(op)
        op.rpm = 18000
        op.vfeed = 200
        op.doc = 1.5
        pda = gui.model.PresetDerivedAttributes(op)
        errors = []
        pda.validate(errors)
        self.assertEqual(errors, [])
        preset = pda.toPreset("new preset")
        self.assertIsInstance(preset, gui.inventory.DrillBitPreset)
        self.assertEqual(preset.name, "new preset")
        self.assertEqual(preset.rpm, 18000)
        self.assertEqual(preset.vfeed, 200)
        self.assertEqual(preset.maxdoc, 1.5)
        # Reset the operation's settings, verify that they are reset
        pda.resetPresetDerivedValues(op)
        self.verifyOpBlank(op)
        # Verify that applying a newly created preset on an empty operation
        # is equivalent to setting the values at the operation level.
        op.tool_preset = preset
        self.verifyOpValuesDB(op)
        self.verifyOpBlank(op)
        # Convert preset values to a dictionary (used by the preset editor dialog)
        # and create another preset from those values, verify that they are identical
        values = gui.model.PresetDerivedAttributes.valuesFromPreset(preset, type(preset.toolbit))
        preset2 = gui.model.PresetDerivedAttributes.toPresetFromAny("from dlg values", values, preset.toolbit, type(preset.toolbit))
        op.tool_preset = preset2
        self.verifyOpValuesDB(op)
        self.verifyOpBlank(op)
        # Modify one value and retest, just to be slightly on the paranoid side
        values['rpm'] = 22000
        preset2 = pda.toPresetFromAny("from dlg values", values, preset.toolbit, type(preset.toolbit))
        op.tool_preset = preset2
        pda = gui.model.PresetDerivedAttributes(op)
        self.verifyAttribute(op, pda, 'rpm', 22000, 20000)
    def verifyOpBlank(self, op):
        for i in gui.model.PresetDerivedAttributes.attrs[type(op.cutter)].values():
            self.assertIsNone(getattr(op, i.name), i.name)
    def verifyOpValuesEM(self, op):
        pda = gui.model.PresetDerivedAttributes(op)
        self.verifyAttribute(op, pda, 'rpm', 18000, 20000)
        self.verifyAttribute(op, pda, 'vfeed', 200, 300)
        self.verifyAttribute(op, pda, 'hfeed', 700, 800)
        self.verifyAttribute(op, pda, 'doc', 1.5, 2)
        self.verifyAttribute(op, pda, 'stepover', 40, 41)
        self.verifyAttribute(op, pda, 'offset', 0.1, 0.11)
        self.verifyAttribute(op, pda, 'extra_width', 90, 91)
        self.verifyAttribute(op, pda, 'trc_rate', 50, 51)
        self.verifyAttribute(op, pda, 'direction', gui.inventory.MillDirection.CLIMB, gui.inventory.MillDirection.CONVENTIONAL)
        self.verifyAttribute(op, pda, 'pocket_strategy', gui.inventory.PocketStrategy.AXIS_PARALLEL, gui.inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG)
        self.verifyAttribute(op, pda, 'axis_angle', 30, 35)
        self.verifyAttribute(op, pda, 'eh_diameter', 80, 20)
    def verifyOpValuesDB(self, op):
        pda = gui.model.PresetDerivedAttributes(op)
        self.verifyAttribute(op, pda, 'rpm', 18000, 20000)
        self.verifyAttribute(op, pda, 'vfeed', 200, 300)
        self.verifyAttribute(op, pda, 'doc', 1.5, 2)
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

class OpTypeTest(unittest.TestCase):
    def testCutterSelection(self):
        for id, name in gui.model.OperationType.descriptions:
            cutter_types = gui.model.cutterTypesForOperationType(id)
            if name == 'Drill':
                assert cutter_types == (gui.inventory.DrillBitCutter, gui.inventory.EndMillCutter)
            else:
                assert cutter_types == gui.inventory.EndMillCutter

unittest.main()

del app
