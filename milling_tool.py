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
   @staticmethod
   def calc_vfeed(hfeed, degrees):
      return hfeed * tan(degrees * pi / 180)
   # Path slope for ramp/helical entry
   def slope(self):
      return max(1, int(self.hfeed / self.vfeed))
      
