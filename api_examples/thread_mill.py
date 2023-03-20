from example_common import *
from DerpCAM.cam.milling_tool import *
import math

# Safe Z for rapid moves above the workpiece (clear of clamping, screws etc.)
safe_z = 5
# Use slower downward moves/ramping/helical entry below this height
# (ideally, that should be zero, but this makes up for any material unevenness
# or slightly tilted workpieces)
semi_safe_z = 1
machine_params = MachineParams(safe_z = safe_z, semi_safe_z = semi_safe_z)

flutes = 3
diameter = 3.9
sfm = 200 # midrange for alu
rpm = sfm * 1000 / (math.pi * diameter)
Fz = 0.03 # lowish for alu for small cutters
feed = Fz * flutes * rpm
print (f"RPM: {rpm}, feed: {feed}")
tool = ThreadCutter(diameter=diameter, min_pitch=0.5, max_pitch=0.8, flutes=flutes, flute_length=15, rpm=rpm, feed=feed, stepover=0.2)

props_fulldepth = OperationProps(depth=-5)

operations = Operations(machine_params=machine_params, tool=tool, props=props_fulldepth)
operations.thread_mill(x=0, y=0, d=5, pitch=0.5)
operations.to_gcode_file("thread.ngc")

viewer_modal(operations)
