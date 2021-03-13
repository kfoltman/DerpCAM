from math import *
from geom import *

class Tool(object):
   def __init__(self, diameter, hfeed, vfeed, maxdoc, stepover=0.5, stepover_fulldepth=0.1):
      self.diameter = diameter
      self.hfeed = hfeed
      self.vfeed = vfeed
      self.maxdoc = maxdoc
      self.stepover = stepover
      self.stepover_fulldepth = stepover_fulldepth
      # Minimum diameter of the helix during helical ramps. If 0, this will
      # essentially permit plunge cuts, and if it's too small, then chip
      # evacuation may be a problem. Picking half the diameter just because.
      self.min_helix_diameter = 0.5 * diameter
   def adjusted_hfeed(self, radial_engagement):
      if radial_engagement < 0.5:
         return self.hfeed / (2 * sqrt(radial_engagement * (1 - radial_engagement)))
      else:
         return self.hfeed / (2 * radial_engagement)
   @staticmethod
   def calc_vfeed(hfeed, degrees):
      return hfeed * tan(degrees * pi / 180)
   # Path slope for ramp/helical entry
   def slope(self):
      return max(1, int(self.hfeed / self.vfeed))
      
class CutterMaterial:
   def __init__(self, name, sfm_multiplier):
      self.name = name
      self.sfm_multiplier = sfm_multiplier

class Material:
   def __init__(self, name, sfm, chipload_10mm, ramp_angle, depth_factor):
      self.name = name
      self.sfm = sfm
      self.chipload_10mm = chipload_10mm # mm chipload at 10mm diameter
      self.ramp_angle = ramp_angle # degrees
      self.depth_factor = depth_factor # multiplier of tool diameter

# 1018, S235, EN3 etc. mild steels
material_mildsteel = Material("mild steel", 350, 0.06, 1, 0.25)
# 4140, EN19 etc. low alloy steels
material_alloysteel = Material("low alloy steel", 250, 0.06, 1, 0.25)
# Tool steels
material_toolsteel = Material("tool steel", 200, 0.05, 1, 0.2)
# Steel forgings
material_toolsteel = Material("forged steel", 125, 0.05, 1, 0.2)
# Aluminium alloys
material_aluminium = Material("aluminium alloy", 500, 0.08, 3, 0.5)
# Brasses
material_brass = Material("brass", 400, 0.08, 3, 0.5)
# Plastics
material_plastics = Material("plastics", 800, 0.08, 5, 0.6)

carbide_uncoated = CutterMaterial("uncoated carbide", 1.0)
carbide_TiN = CutterMaterial("TiN coated carbide", 1.2)
carbide_AlTiN = CutterMaterial("AlTiN coated carbide", 1.3)

min_rpm = 2800
max_rpm = 24000

def standard_tool(diameter, flutes, material, coating):
   sfm = material.sfm * coating.sfm_multiplier
   rpm = 4 * sfm / (diameter / 25.4)
   if rpm < min_rpm:
      raise ValueError("RPM %f below the spindle minimum" % rpm)
   if rpm > max_rpm:
      rpm = max_rpm
   feed = flutes * material.chipload_10mm * diameter / 10 * rpm
   angle = material.ramp_angle
   plunge = Tool.calc_vfeed(feed, angle)
   doc = material.depth_factor * diameter
   tool = Tool(diameter, feed, plunge, doc)
   tool.info = "%d-flute %0.2fmm %s cutter cutting %s at %0.0f RPM and %0.0f mm/min" % (flutes, diameter, coating.name, material.name, rpm, feed)
   return tool
