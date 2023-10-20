import os
import sys
import unittest

sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from DerpCAM.common.geom import *
from DerpCAM.cam.gcodegen import *
from DerpCAM.cam.milling_tool import *
from DerpCAM.cam.toolpath import *
from DerpCAM.cam.wall_profile import *

machine_params = MachineParams(5, 1)
tool = standard_tool(2, 2, 2, material_mildsteel, carbide_uncoated)
tool.maxdoc = 1

class LayerScheduleTest(unittest.TestCase):
    def assertNear(self, v1, v2, places=3, msg=None):
        self.assertAlmostEqual(v1, v2, places=places, msg=msg)

    def assertCloseEnoughTuple(self, a, b, places=3):
        self.assertEqual(len(a), len(b))
        for i in range(len(a)):
            self.assertNear(a[i], b[i], msg=f"{i}", places=places)

    def testBasic(self):
        # Without start depth
        props = OperationProps(depth=-12, start_depth=0)
        ls = LayerSchedule(machine_params, props, tool, False)
        mll = ls.major_layer_list()
        self.assertEqual(len(mll), 12)
        for i in range(12):
            self.assertEqual(mll[i].depth, -(i + 1))
            self.assertEqual(mll[i].prev_depth, -i)
            self.assertEqual(mll[i].offsets.start_offset, 0)
            self.assertEqual(mll[i].offsets.end_offset, 0)
            self.assertEqual(mll[i].tab_status, LayerInfo.TAB_ABOVE)
            self.assertFalse(mll[i].is_sublayer)
        # With start depth
        props = OperationProps(depth=-12, start_depth=-4)
        ls = LayerSchedule(machine_params, props, tool, False)
        mll = ls.major_layer_list()
        self.assertEqual(len(mll), 8)
        for i in range(8):
            self.assertEqual(mll[i].depth, -(i + 5))
            self.assertEqual(mll[i].prev_depth, -(i + 4))
            self.assertEqual(mll[i].offsets.start_offset, 0)
            self.assertEqual(mll[i].offsets.end_offset, 0)
            self.assertEqual(mll[i].tab_status, LayerInfo.TAB_ABOVE)
            self.assertFalse(mll[i].is_sublayer)

    def testFractional(self):
        # Test for floating point naughtiness
        tool2 = tool.clone_with_overrides(maxdoc=0.1)
        props = OperationProps(depth=-12, start_depth=0)
        ls = LayerSchedule(machine_params, props, tool2, False)
        mll = ls.major_layer_list()
        self.assertEqual(len(mll), 120)
        for i in range(120):
            self.assertEqual(mll[i].depth, round(-(i * 0.1 + 0.1), 3))
            self.assertEqual(mll[i].prev_depth, round(-i * 0.1, 3))
            self.assertEqual(mll[i].offsets.start_offset, 0)
            self.assertEqual(mll[i].offsets.end_offset, 0)
            self.assertEqual(mll[i].tab_status, LayerInfo.TAB_ABOVE)
            self.assertFalse(mll[i].is_sublayer)

    def testBasicTab(self):
        # Test tab_status
        for tab_depth in [-6, -6.5]:
            for use_tabs in [False, True]:
                props = OperationProps(depth=-12, start_depth=0, tab_depth=tab_depth)
                ls = LayerSchedule(machine_params, props, tool, use_tabs)
                mll = ls.major_layer_list()
                self.assertEqual(len(mll), 12)
                first = True
                for i in range(12):
                    self.assertEqual(mll[i].depth, -(i + 1))
                    self.assertEqual(mll[i].prev_depth, -i)
                    self.assertEqual(mll[i].offsets.start_offset, 0)
                    self.assertEqual(mll[i].offsets.end_offset, 0)
                    if mll[i].depth >= props.tab_depth or not use_tabs:
                        self.assertEqual(mll[i].tab_status, LayerInfo.TAB_ABOVE)
                    elif first:
                        self.assertEqual(mll[i].tab_status, LayerInfo.TAB_FIRST)
                        first = False
                    else:
                        self.assertEqual(mll[i].tab_status, LayerInfo.TAB_BELOW)
                    self.assertFalse(mll[i].is_sublayer)

    def testBasicSublayers(self):
        # Test for floating point naughtiness
        for offset_tolerance, num_sublayers in [(0, 9 * 12), (0.1, 4 * 12), (0.2, 2 * 12)]:
            props = OperationProps(depth=-12, start_depth=0, wall_profile=DraftWallProfile(30), offset_tolerance=offset_tolerance, tab_depth=-6)
            ls = LayerSchedule(machine_params, props, tool, True)
            mll = ls.major_layer_list()
            self.assertEqual(len(mll), 12 + num_sublayers)
            slope = -tan(30 * pi / 180)
            # Roughing passes
            first = True
            for i in range(12):
                depth = mll[i].depth
                self.assertEqual(mll[i].depth, -(i + 1))
                self.assertEqual(mll[i].prev_depth, -i)
                self.assertEqual(mll[i].offsets.start_offset, slope * depth)
                self.assertEqual(mll[i].offsets.end_offset, slope * props.depth)
                if depth >= -6:
                    self.assertEqual(mll[i].tab_status, LayerInfo.TAB_ABOVE)
                elif first:
                    self.assertEqual(mll[i].tab_status, LayerInfo.TAB_FIRST)
                    first = False
                else:
                    self.assertEqual(mll[i].tab_status, LayerInfo.TAB_BELOW)
                self.assertFalse(mll[i].is_sublayer)
            # Refining passes
            for i in range(12, len(mll)):
                j = i - 12
                if offset_tolerance == 0:
                    self.assertEqual(mll[i].depth, round(-(12 - (j // 9) - (j % 9) * 0.1 - 0.1), 3))
                if offset_tolerance == 0.1:
                    self.assertEqual(mll[i].depth, round(-(12 - (j // 4) - (j % 4) * 0.2 - 0.2), 3))
                if offset_tolerance == 0.2:
                    self.assertEqual(mll[i].depth, round(-(12 - (j // 2) - (j % 2) * 0.4 - 0.4), 3))
                self.assertEqual(round(mll[i].prev_depth - mll[i].depth, 3), props.sublayer_thickness)
                self.assertEqual(mll[i].offsets.start_offset, slope * mll[i].depth)
                self.assertEqual(mll[i].offsets.end_offset, slope * mll[i].depth)
                if mll[i].depth >= -6:
                    self.assertEqual(mll[i].tab_status, LayerInfo.TAB_ABOVE)
                else:
                    self.assertEqual(mll[i].tab_status, LayerInfo.TAB_BELOW)
                self.assertTrue(mll[i].is_sublayer)
            # Check if offset_tolerance is obeyed across sublayers
            sml = sorted(mll, key=lambda layer: layer.depth)
            last = None
            for i in sml:
                if last is not None and i.is_sublayer:
                    self.assertGreaterEqual(last - i.offsets.start_offset, offset_tolerance)
                last = i.offsets.start_offset

unittest.main()
