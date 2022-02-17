import os.path
import sys
import threading
import time
import tempfile
import unittest
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import gui.inventory

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
        std_cutters.writeTo(self.test_dir.name, "std-cutters.json")
        self.assertTrue(os.path.exists(self.test_dir.name))
        alt_inventory = gui.inventory.Inventory()
        alt_inventory.readFrom(os.path.join(self.test_dir.name, "std-cutters.json"))
        self.checkStdCutters(alt_inventory)
        for i in std_cutters.toolbits:
            orig = std_cutters.toolbitByName(i.name)
            self.assertIsNotNone(orig)
            saved = alt_inventory.toolbitByName(i.name)
            self.assertIsNotNone(saved)
            self.assertFalse(orig is saved)
            self.assertTrue(orig.equals(saved))
    def checkStdCutters(self, inventory):
        self.checkCutterAttribs(inventory, 1, "cheapo 2F 3.2/15", 3.2, 2, 15, "2F \u23003.2 L15 carbide end mill")
        self.checkCutterAttribs(inventory, 2, "cheapo 2F 2.5/12", 2.5, 2, 12, "2F \u23002.5 L12 carbide end mill")
        self.checkCutterAttribs(inventory, 50, "2mm HSS", 2, 2, 25, "2mm HSS drill bit, L=25mm")
        self.checkCutterAttribs(inventory, 51, "3mm HSS", 3, 2, 41, "3mm HSS drill bit, L=41mm")
    def checkCutterAttribs(self, inventory, id, name, diameter, flutes, length, substr):
        toolbit = inventory.toolbitByName(name)
        self.assertIsNotNone(toolbit)
        if inventory is std_cutters:
            self.assertEqual(toolbit.id, id)
        else:
            self.assertEqual(toolbit.orig_id, id)
        self.assertEqual(toolbit.name, name)
        self.assertEqual(toolbit.diameter, diameter)
        self.assertEqual(toolbit.flutes, flutes)
        self.assertEqual(toolbit.length, length)
        self.assertIn(substr, toolbit.description_only())

unittest.main()
