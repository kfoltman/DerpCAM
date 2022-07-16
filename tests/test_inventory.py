import os.path
import sys
import tempfile
import unittest
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from DerpCAM import gui
import DerpCAM.gui.inventory

MillDirection = gui.inventory.MillDirection
PocketStrategy = gui.inventory.PocketStrategy

std_cutters = gui.inventory.Inventory()

class InventoryTest(unittest.TestCase):
    def setUp(self):
        std_cutters.createStdCutters()
        self.test_dir = tempfile.TemporaryDirectory()
    def tearDown(self):
        self.test_dir.cleanup()
        gui.inventory.IdSequence.nukeAll()
    def testClasses(self):
        self.assertEqual(gui.inventory.EndMillCutter.preset_type, gui.inventory.EndMillPreset)
        self.assertEqual(gui.inventory.EndMillCutter.cutter_type_name, "End mill")
        self.assertEqual(gui.inventory.EndMillCutter.cutter_type_priority, 1)
        self.assertEqual(gui.inventory.DrillBitCutter.preset_type, gui.inventory.DrillBitPreset)
        self.assertEqual(gui.inventory.DrillBitCutter.cutter_type_name, "Drill bit")
        self.assertEqual(gui.inventory.DrillBitCutter.cutter_type_priority, 2)
    def testGetByName(self):
        self.assertIsNone(std_cutters.toolbitByName("cheapo 2F 2.5/12", gui.inventory.DrillBitCutter))
        self.assertIsNone(std_cutters.toolbitByName("2mm HSS", gui.inventory.EndMillCutter))
        self.assertIsInstance(std_cutters.toolbitByName("cheapo 2F 2.5/12", gui.inventory.EndMillCutter), gui.inventory.EndMillCutter)
        self.assertIsInstance(std_cutters.toolbitByName("2mm HSS", gui.inventory.DrillBitCutter), gui.inventory.DrillBitCutter)
    def testDelete(self):
        std_cutters.deleteCutter(std_cutters.toolbitByName("cheapo 2F 2.5/12", gui.inventory.EndMillCutter))
        std_cutters.deleteCutter(std_cutters.toolbitByName("2mm HSS", gui.inventory.DrillBitCutter))
        self.assertIsNone(std_cutters.toolbitByName("cheapo 2F 2.5/12", gui.inventory.EndMillCutter))
        self.assertIsNone(std_cutters.toolbitByName("2mm HSS", gui.inventory.DrillBitCutter))
    def testPropagation(self):
        self.checkPropagationForToolbit("2mm HSS", attr_values=[("diameter", 3), ("flutes", 3), ("length", 10)])
        self.checkPropagationForPreset("2mm HSS", "Wood-untested", attr_values=[("rpm", 3), ("vfeed", 30), ("maxdoc", 1)])
        self.checkPropagationForToolbit("cheapo 2F 3.2/15", attr_values=[("diameter", 3), ("flutes", 3), ("length", 10)])
        self.checkPropagationForPreset("cheapo 2F 3.2/15", "Wood-roughing",
            attr_values=[("rpm", 3), ("vfeed", 30), ("hfeed", 30), ("maxdoc", 1), ("offset", 0.1), ("stepover", 0.55), ("direction", MillDirection.CLIMB),
                ("extra_width", 0.1), ("trc_rate", 0.1), ("pocket_strategy", PocketStrategy.HSM_PEEL_ZIGZAG), ("axis_angle", 45), ('eh_diameter', 30)])
    def checkPropagationForToolbit(self, toolbit_name, attr_values):
        em = std_cutters.toolbitByName(toolbit_name)
        self.checkPropagation(em, attr_values)
    def checkPropagationForPreset(self, toolbit_name, preset_name, attr_values):
        em = std_cutters.toolbitByName(toolbit_name)
        preset = em.presetByName(preset_name)
        p1, p2 = self.checkPropagation(preset, attr_values)
        self.assertEqual(p1.toolbit, em)
        self.assertEqual(p2.toolbit, em)
        name = preset_name + "-test"
        self.assertIs(em.addPreset(None, name, **dict(attr_values)), em)
        preset2 = em.presetByName(name)
        self.assertEqual(preset2.toolbit, em)
        self.assertIsNotNone(preset2.id)
        self.assertNotEqual(preset2.id, 0)
        for key, value in attr_values:
            self.assertEqual(getattr(preset2, key), value)
        em.deletePreset(preset2)
        self.assertIsNone(em.presetByName(name))
    def checkPropagation(self, em, attr_values):
        em2 = em.newInstance()
        self.assertIsNot(em2, em)
        self.assertIs(em2.base_object, em)
        self.assertTrue(em2.equals(em))
        self.assertTrue(em.equals(em2))
        em3 = em.newInstance()
        self.assertIsNot(em3, em)
        self.assertIsNot(em3, em2)
        self.assertIs(em3.base_object, em)
        self.assertTrue(em2.equals(em3))
        self.assertTrue(em3.equals(em2))
        for attr, value in attr_values:
            setattr(em3, attr, value)
            self.assertFalse(em2.equals(em3), attr)
            self.assertFalse(em3.equals(em2), attr)
            em3.resetTo(em)
            self.assertTrue(em2.equals(em3), attr)
            self.assertTrue(em3.equals(em2), attr)
        return em2, em3
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
        self.checkCutterAttribs(inventory, 50, "2mm HSS", 2, 2, 25, "2 mm HSS drill bit, L=25 mm", gui.inventory.DrillBitCutter)
        self.checkCutterAttribs(inventory, 51, "3mm HSS", 3, 2, 41, "3 mm HSS drill bit, L=41 mm", gui.inventory.DrillBitCutter)
        self.checkPreset(inventory, "cheapo 2F 3.2/15", "Wood-roughing",
            ['\u21943200 ', '\u21931500 ', '\u21a72 ', '\u27f760%', '\u27f324000'],
            rpm=24000, hfeed=3200, vfeed=1500, maxdoc=2, offset=0, stepover=0.6,
            direction=MillDirection.CONVENTIONAL, pocket_strategy=PocketStrategy.CONTOUR_PARALLEL, extra_width=0, trc_rate=0, axis_angle=0, eh_diameter=0.5)
        self.checkPreset(inventory, "2mm HSS", "Wood-untested", ['\u27f310000', '\u2193100', '\u21a76'], rpm=10000, vfeed=100, maxdoc=6)
        self.checkPreset(inventory, "3mm HSS", "Wood-untested", ['\u27f37000', '\u2193100', '\u21a76'], rpm=7000, vfeed=100, maxdoc=6)
    def checkCutterAttribs(self, inventory, id, name, diameter, flutes, length, substr, data_type):
        toolbit = inventory.toolbitByName(name)
        self.assertIsNotNone(toolbit)
        self.assertIsInstance(toolbit, data_type)
        if inventory is std_cutters:
            self.assertEqual(toolbit.id, id)
        else:
            self.assertEqual(toolbit.orig_id, id)
        self.assertIs(toolbit, gui.inventory.IdSequence.lookup(toolbit.id))
        self.assertEqual(toolbit.name, name)
        self.assertEqual(toolbit.diameter, diameter)
        self.assertEqual(toolbit.flutes, flutes)
        self.assertEqual(toolbit.length, length)
        self.assertIn(name + ":", toolbit.description())
        self.assertNotIn(name + ":", toolbit.description_only())
        self.assertIn(substr, toolbit.description())
        self.assertIn(substr, toolbit.description_only())
        self.assertNotIn(substr, toolbit.name)
    def checkPreset(self, inventory, tool_name, preset_name, substrings, **attribs):
        toolbit = inventory.toolbitByName(tool_name)
        self.assertIsNotNone(toolbit)
        preset = toolbit.presetByName(preset_name)
        self.assertIsNotNone(preset)
        description = preset.description_only()
        for i in substrings:
            self.assertIn(i, description)
        for k, v in attribs.items():
            self.assertEqual(getattr(preset, k), v, f"{tool_name} -> {preset_name} -> {k}")

unittest.main()
