from math import *
from geom import *

class Tool(object):
    def __init__(self, diameter, hfeed, vfeed, maxdoc, stepover=0.5, stepover_fulldepth=0.1, climb=False, min_helix_ratio=None):
        self.diameter = diameter
        self.flutes = None
        self.hfeed = hfeed
        self.vfeed = vfeed
        self.maxdoc = maxdoc
        self.climb = climb
        self.stepover = stepover
        self.stepover_fulldepth = stepover_fulldepth
        # Reduction of feed rate for full engagement plunges
        self.full_plunge_feed_ratio = 0.5
        # Minimum diameter of the helix during helical ramps. If 0, this will
        # essentially permit plunge cuts, and if it's too small, then chip
        # evacuation may be a problem.
        if min_helix_ratio is None:
            min_helix_ratio = 0.5
        self.min_helix_diameter = min_helix_ratio * diameter
        self.helix_entry_diameter = self.min_helix_diameter
        self.material = None
        self.coating = None
        self.rpm = None
        self.info = None
        self.short_info = None
    def adjusted_hfeed(self, radial_engagement):
        if radial_engagement < 0.5:
            return self.hfeed / (2 * sqrt(radial_engagement * (1 - radial_engagement)))
        else:
            return self.hfeed / (2 * radial_engagement)
    @staticmethod
    def calc_vfeed(hfeed, degrees):
        return hfeed * tan(min(45, degrees) * pi / 180)
    # Path slope for ramp/helical entry
    def slope(self):
        return max(1, int(self.hfeed / self.vfeed))
    def clone_with_overrides(self, hfeed=None, vfeed=None, maxdoc=None, rpm=None, stepover=None, climb=None):
        tool = Tool(self.diameter, hfeed or self.hfeed, vfeed or self.vfeed, maxdoc or self.maxdoc, stepover or self.stepover, self.stepover_fulldepth, climb if climb is not None else self.climb)
        if rpm is None:
            tool.rpm = self.rpm
        else:
            tool.rpm = rpm
            tool.hfeed = tool.hfeed * rpm / self.rpm
            tool.vfeed = tool.vfeed * rpm / self.rpm
        tool.flutes = self.flutes
        tool.material = self.material
        tool.coating = self.coating
        tool.set_info()
        return tool
    def mrr(self):
        return self.maxdoc * self.diameter * self.vfeed
    def hp(self):
        return self.material.cut_power * self.mrr() / (25.4 ** 3)
    def set_info(self):
        self.info = "%d-flute %0.2fmm %s cutter cutting %s at %0.0f RPM and %0.0f mm/min" % (self.flutes, self.diameter, self.coating.name, self.material.name, self.rpm, self.hfeed)
        if int(self.diameter * 100) % 100 == 0:
            self.short_info = "%dF %0.0fmm %s/%s @S=%0.0f, F=%0.0f, D=%0.2f" % (self.flutes, self.diameter, self.coating.short_name, self.material.short_name, self.rpm, self.hfeed, self.maxdoc)
        elif int(self.diameter * 100) % 10 == 0:
            self.short_info = "%dF %0.1fmm %s/%s @S=%0.0f, F=%0.0f, D=%0.2f" % (self.flutes, self.diameter, self.coating.short_name, self.material.short_name, self.rpm, self.hfeed, self.maxdoc)
        else:
            self.short_info = "%dF %0.2fmm %s/%s @S=%0.0f, F=%0.0f, D=%0.2f" % (self.flutes, self.diameter, self.coating.short_name, self.material.short_name, self.rpm, self.hfeed, self.maxdoc)

class CutterMaterial:
    def __init__(self, name, short_name, sfm_multiplier):
        self.name = name
        self.short_name = short_name
        self.sfm_multiplier = sfm_multiplier

class Material:
    def __init__(self, name, short_name, sfm, chipload_10mm, ramp_angle, depth_factor, cut_power):
        self.name = name
        self.short_name = short_name
        self.sfm = sfm
        self.chipload_10mm = chipload_10mm # mm chipload at 10mm diameter
        self.ramp_angle = ramp_angle # degrees
        self.depth_factor = depth_factor # multiplier of tool diameter
        self.cut_power = cut_power # HP / (in^3/min)

# 1018, S235, EN3 etc. mild steels
material_mildsteel = Material("mild steel", "stl", 350, 0.06, 1, 0.25, 1.0)
# 4140, EN19 etc. low alloy steels
material_alloysteel = Material("low alloy steel", "lastl", 250, 0.06, 1, 0.25, 1.6)
# Tool steels
material_toolsteel = Material("tool steel", "tstl", 200, 0.05, 1, 0.2, 2)
# Steel forgings
material_forgedsteel = Material("forged steel", "fstl", 125, 0.05, 1, 0.2, 2)
# Aluminium alloys
material_aluminium = Material("aluminium alloy", "alu", 500, 0.08, 3, 0.5, 0.3)
# Brasses
material_brass = Material("brass", "brs", 400, 0.08, 3, 0.5, 0.8)
# Plastics
material_plastics = Material("plastics", "pls", 800, 0.08, 5, 0.6, 0.4)
# Wood and engineered wood
material_wood = Material("woods", "wd", 1600, 0.08, 25, 0.8, 0.2)

carbide_uncoated = CutterMaterial("uncoated carbide", "C-U", 1.0)
carbide_TiN = CutterMaterial("TiN coated carbide", "C-TiN", 1.2)
carbide_AlTiN = CutterMaterial("AlTiN coated carbide", "C-AlTiN", 1.3)

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
    tool.flutes = flutes
    tool.material = material
    tool.coating = coating
    tool.rpm = rpm
    tool.set_info()
    return tool
