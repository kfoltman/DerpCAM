import os.path
import sys
import threading
import time
import tempfile
import unittest
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import gui.inventory

MillDirection = gui.inventory.MillDirection
PocketStrategy = gui.inventory.PocketStrategy

std_cutters = gui.inventory.Inventory()
std_cutters.createStdCutters()

class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
    def tearDown(self):
        self.test_dir.cleanup()
    def testStdCutters(self):
        self.checkStdCutters(std_cutters)
    def testStdCuttersSaveLoad(self):
        tdir = self.test_dir.name
        fname = "std-cutters.json"
        fullname = os.path.join(tdir, fname)
        std_cutters.writeTo(tdir, fname)
        self.assertTrue(os.path.isdir(tdir))
        self.assertTrue(os.path.isfile(fullname))
        alt_inventory = gui.inventory.Inventory()
        alt_inventory.readFrom(fullname)
        self.checkStdCutters(alt_inventory)
        for i in std_cutters.toolbits:
            orig = std_cutters.toolbitByName(i.name)
            self.assertIsNotNone(orig)
            saved = alt_inventory.toolbitByName(i.name)
            self.assertIsNotNone(saved)
            self.assertFalse(orig is saved)
            self.assertTrue(orig.equals(saved))
    def checkStdCutters(self, inventory):
        self.checkCutterAttribs(inventory, 1, "cheapo 2F 3.2/15", 3.2, 2, 15, "2F \u23003.2 L15 carbide end mill", gui.inventory.EndMillCutter)
        self.checkCutterAttribs(inventory, 2, "cheapo 2F 2.5/12", 2.5, 2, 12, "2F \u23002.5 L12 carbide end mill", gui.inventory.EndMillCutter)
        self.checkCutterAttribs(inventory, 50, "2mm HSS", 2, 2, 25, "2mm HSS drill bit, L=25mm", gui.inventory.DrillBitCutter)
        self.checkCutterAttribs(inventory, 51, "3mm HSS", 3, 2, 41, "3mm HSS drill bit, L=41mm", gui.inventory.DrillBitCutter)
        self.checkPreset(inventory, "cheapo 2F 3.2/15", "Wood-roughing", rpm=24000, hfeed=3200, vfeed=1500, maxdoc=2, stepover=0.6, direction=MillDirection.CONVENTIONAL, pocket_strategy=PocketStrategy.CONTOUR_PARALLEL, extra_width=0, trc_rate=0, axis_angle=0)
        self.checkPreset(inventory, "2mm HSS", "Wood-untested", rpm=10000, vfeed=100, maxdoc=6)
        self.checkPreset(inventory, "3mm HSS", "Wood-untested", rpm=7000, vfeed=100, maxdoc=6)
    def checkCutterAttribs(self, inventory, id, name, diameter, flutes, length, substr, data_type):
        toolbit = inventory.toolbitByName(name)
        self.assertIsNotNone(toolbit)
        self.assertIsInstance(toolbit, data_type)
        if inventory is std_cutters:
            self.assertEqual(toolbit.id, id)
        else:
            self.assertEqual(toolbit.orig_id, id)
        self.assertEqual(toolbit.name, name)
        self.assertEqual(toolbit.diameter, diameter)
        self.assertEqual(toolbit.flutes, flutes)
        self.assertEqual(toolbit.length, length)
        self.assertIn(name + ":", toolbit.description())
        self.assertIn(substr, toolbit.description())
        self.assertIn(substr, toolbit.description_only())
    def checkPreset(self, inventory, tool_name, preset_name, **attribs):
        toolbit = inventory.toolbitByName(tool_name)
        self.assertIsNotNone(toolbit)
        preset = toolbit.presetByName(preset_name)
        self.assertIsNotNone(preset)
        for k, v in attribs.items():
            self.assertEqual(getattr(preset, k), v, f"{tool_name} -> {preset_name} -> {k}")

unittest.main()
