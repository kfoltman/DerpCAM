from math import *
from ..common.geom import *

class FakeTool(object):
    def __init__(self, diameter):
        self.diameter = diameter

class Tool(object):
    def __init__(self, diameter, hfeed, vfeed, maxdoc, stepover=0.5, stepover_fulldepth=0.1, climb=False, min_helix_ratio=None, tip_angle=0, tip_diameter=0):
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
        self.min_helix_ratio = min_helix_ratio
        self.min_helix_diameter = min_helix_ratio * diameter
        self.helix_entry_diameter = self.min_helix_diameter
        self.material = None
        self.coating = None
        self.rpm = None
        self.info = None
        self.short_info = None
        self.tip_angle = tip_angle
        self.tip_diameter = tip_diameter
    def max_ramp_length(self, z_diff):
        return 2 * self.diameter + 2 * z_diff
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
    # Diameter to depth conversion for v-carving
    def dia2depth(self, dia):
        slope = -0.5 / tan((self.tip_angle * pi / 180) / 2)
        eff_dia = max(0, min(dia, self.diameter) - self.tip_diameter)
        return slope * eff_dia
    def depth2dia(self, depth):
        # depth is negative here
        if not self.tip_angle:
            return self.diameter
        slope = -0.5 / tan((self.tip_angle * pi / 180) / 2)
        return min(self.diameter, self.tip_diameter + depth / slope)
    def clone_with_overrides(self, hfeed=None, vfeed=None, maxdoc=None, rpm=None, stepover=None, climb=None, min_helix_ratio=None, tip_angle=None, tip_diameter=None):
        def ovr(v1, v2):
            return v1 if v1 is not None else v2
        tool = Tool(self.diameter, hfeed or self.hfeed, vfeed or self.vfeed, maxdoc or self.maxdoc, stepover or self.stepover, self.stepover_fulldepth, 
            ovr(climb, self.climb), ovr(min_helix_ratio, self.min_helix_ratio), ovr(tip_angle, self.tip_angle), ovr(tip_diameter, self.tip_diameter))
        if rpm is None:
            tool.rpm = self.rpm
        else:
            tool.rpm = rpm
            tool.hfeed = tool.hfeed * rpm / self.rpm
            tool.vfeed = tool.vfeed * rpm / self.rpm
        tool.flutes = self.flutes
        tool.material = self.material
        tool.coating = self.coating
        if self.coating is not None and self.material is not None:
            tool.set_info()
        return tool
    def mrr(self):
        return self.maxdoc * self.diameter * self.vfeed
    def hp(self):
        return self.material.cut_power * self.mrr() / (25.4 ** 3)
    def diagonal_factor(self):
        slope = self.slope()
        return sqrt(slope ** 2 + 1) / slope
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
    def __init__(self, name, short_name, sfm_carbide, sfm_hss, drill_sfm_carbide, drill_sfm_hss, chipload_3mm, chipload_10mm, ramp_angle, depth_factor, cut_power, stepover):
        self.name = name
        self.short_name = short_name
        self.sfm_carbide = sfm_carbide
        self.sfm_hss = sfm_hss
        self.drill_sfm_carbide = drill_sfm_carbide
        self.drill_sfm_hss = drill_sfm_hss
        self.chipload_3mm = chipload_3mm # mm chipload at 10mm diameter
        self.chipload_10mm = chipload_10mm # mm chipload at 10mm diameter
        self.ramp_angle = ramp_angle # degrees
        self.depth_factor = depth_factor # multiplier of tool diameter
        self.cut_power = cut_power # HP / (in^3/min)
        self.stepover = stepover

# 1018, S235, EN3 etc. mild steels
material_mildsteel = Material("mild steel", "stl", 350, 80, 230, 100, 0.016, 0.06, 3, 0.25, 1.0, 22)
# 4140, EN19 etc. low alloy steels
material_alloysteel = Material("low alloy steel", "lastl", 250, 70, 130, 70, 0.016, 0.06, 1, 0.25, 1.6, 22)
# Tool steels
material_toolsteel = Material("tool steel", "tstl", 200, 50, 100, 50, 0.01, 0.05, 1, 0.2, 2, 22)
# Stainless steels
material_stainlesssteel = Material("stainless steel", "sstl", 200, 50, 100, 30, 0.01, 0.05, 1, 0.2, 2, 22)
# Steel forgings
material_forgedsteel = Material("forged steel", "fstl", 125, 30, 60, 40, 0.01, 0.05, 1, 0.2, 2, 22)
# Cast iron - gray
material_castiron = Material("gray iron", "giron", 400, 100, 250, 90, 0.015, 0.06, 1, 0.25, 1.2, 22)
# Cast iron - malleable
material_malleableiron = Material("malleable iron", "miron", 200, 50, 160, 70, 0.015, 0.06, 1, 0.25, 1.2, 22)
# Aluminium alloys
#material_aluminium = Material("aluminium alloy", "alu", 500, 150, 500, 200, 0.025, 0.08, 3, 0.5, 0.3, 22)
material_aluminium = Material("aluminium alloy", "alu", 500, 150, 500, 200, 0.016, 0.06, 5, 0.25, 0.3, 22)
# Brasses
#material_brass = Material("brass", "brs", 400, 120, 330, 150, 0.025, 0.08, 3, 0.5, 0.8, 22)
material_brass = Material("brass", "brs", 400, 120, 330, 150, 0.016, 0.06, 4, 0.25, 0.8, 22)
# Plastics
material_plastics = Material("plastics", "pls", 800, 800, 800, 200, 0.025, 0.08, 5, 0.6, 0.4, 30)
# Wood and engineered wood
material_wood = Material("woods", "wd", 1600, 1600, 800, 200, 0.025, 0.08, 10, 0.8, 0.2, 40)
# Plastic foam
material_foam = Material("foams", "fm", 1600, 1600, 800, 200, 0.025, 0.08, 20, 1.6, 0.2, 40)

carbide_uncoated = CutterMaterial("uncoated carbide", "C-U", 1.0)
carbide_TiN = CutterMaterial("TiN coated carbide", "C-TiN", 1.2)
carbide_AlTiN = CutterMaterial("AlTiN coated carbide", "C-AlTiN", 1.3)

min_rpm = 2800
max_rpm = 24000

def standard_tool(diameter, flutes, material, coating, is_hss=False, sfm_factor=1, flute_length=None, machine_params=None, is_drill=False):
    if is_drill:
        msfm = material.drill_sfm_hss if is_hss else material.drill_sfm_carbide
    else:
        msfm = material.sfm_hss if is_hss else material.sfm_carbide
    sfm = msfm * coating.sfm_multiplier * sfm_factor
    rpm = 12 * sfm / (pi * diameter / 25.4)
    if machine_params:
        if machine_params.min_rpm is not None and rpm < machine_params.min_rpm:
            raise ValueError(f"Calculated spindle speed of {rpm:0.1f} is below the spindle minimum of {machine_params.min_rpm:0.1f}")
        if machine_params.max_rpm is not None and rpm > machine_params.max_rpm:
            rpm = machine_params.max_rpm
    dia_factor = log(diameter / 3) / log (10 / 3)
    chipload = material.chipload_3mm * pow(material.chipload_10mm / material.chipload_3mm, dia_factor)
    if is_drill:
        plunge = feed = chipload * rpm
    else:
        feed = flutes * chipload * rpm
        angle = material.ramp_angle
        plunge = Tool.calc_vfeed(feed, angle)
    if is_drill:
        if is_hss:
            doc = 3 * diameter
        else:
            # Peck drilling is discouraged for carbide?
            doc = 5 * diameter
    else:
        doc = material.depth_factor * diameter
    if flute_length is not None:
        doc = min(doc, flute_length)
    if is_drill:
        tool = Tool(diameter, 0, plunge, doc)
    else:
        tool = Tool(diameter, feed, plunge, doc)
    tool.flutes = flutes
    tool.material = material
    tool.coating = coating
    tool.rpm = rpm
    tool.stepover = material.stepover / 100
    tool.set_info()
    return tool
