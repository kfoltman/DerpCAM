import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from DerpCAM.common.geom import *
from DerpCAM.common.view import *
from DerpCAM.cam.shapes import *
from DerpCAM.cam.gcodegen import *
from DerpCAM.cam.gcodeops import *
from DerpCAM.cam.ptext import *
from DerpCAM.cam.wall_profile import *
from DerpCAM.cam.toolpath import Tool

# Aluminium (feed at the limit for 17k RPM, 2x more and it breaks instantly)
tool_alu_2_5_pocket = Tool(diameter = 2.5, hfeed = 500, vfeed = 100, maxdoc = 0.75)
# Slotting
tool_alu_2_5_slot = Tool(diameter = 2.5, hfeed = 200, vfeed = 20, maxdoc = 0.5)

tool_alu_3_2_slot = Tool(diameter = 3.2, hfeed = 500, vfeed = 100, maxdoc = 0.3)
