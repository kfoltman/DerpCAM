from DerpCAM.common.guiutils import EnumClass, Format, UnitConverter
from DerpCAM.cam.wall_profile import UserDefinedWallProfile, WallProfileItem, WallProfileItemType
import os
import json
import sys

class IdSequence(object):
    last_id = 999
    objects = {}
    @staticmethod
    def lookup(id):
        return IdSequence.objects.get(id, None)
    @staticmethod
    def next(who):
        IdSequence.last_id += 1
        IdSequence.objects[IdSequence.last_id] = who
        return IdSequence.last_id
    @staticmethod
    def register(id, who):
        if id is None:
            return IdSequence.next(who)
        if IdSequence.objects.get(id) is who:
            return id
        assert id not in IdSequence.objects
        if id > IdSequence.last_id:
            IdSequence.last_id = id + 1
        IdSequence.objects[id] = who
        return id
    @staticmethod
    def unregister(who):
        del IdSequence.objects[who.id]
    @staticmethod
    def nukeAll():
        IdSequence.last_id = 999
        IdSequence.objects = {}

class EncodedProperty(object):
    def __init__(self, name):
        self.name = name
    def encode(self, value):
        assert False
    def decode(self, value):
        assert False
    def copyValue(self, dst, src):
        setattr(dst, self.name, getattr(src, self.name))

# Material types are encoded as names
class MaterialProperty(EncodedProperty):
    def encode(self, value):
        return value.name
    def decode(self, name):
        return CutterMaterial.byName(name)
    def equals(self, v1, v2):
        return v1.name == v2.name

class IdRefProperty(EncodedProperty):
    def encode(self, value):
        return value.id
    def decode(self, value):
        # Requires a fixup step
        return value
    def equals(self, v1, v2):
        return getattr(v1, self.name).name == getattr(v2, self.name).name

class Serializable(object):
    def __init__(self, id, name):
        self.id = IdSequence.register(id, self)
        self.name = name
        self.orig_id = None
        self.base_object = None
        for i in self.properties:
            if isinstance(i, EncodedProperty):
                setattr(self, i.name, None)
            else:
                setattr(self, i, None)
    def equals(self, other):
        for i in self.properties:
            if isinstance(i, EncodedProperty):
                equals = i.equals(self, other)
            else:
                equals = getattr(self, i) == getattr(other, i)
            if not equals:
                return False
        return True
    @classmethod
    def load(klass, data, default_type=None):
        rtype = data.get('_type', default_type)
        if rtype is not None:
            klass2 = getattr(sys.modules[__name__], rtype, None)
            if klass2 is None:
                return None
            elif issubclass(klass2, klass):
                res = klass2(None, data['name'])
            else:
                raise ValueError(f"{rtype} is not a subclass of {klass.__name__}")
        else:
            res = klass(None, data['name'])
        res.orig_id = data['id']
        for i in res.properties:
            if isinstance(i, EncodedProperty):
                setattr(res, i.name, i.decode(data.get(i.name, None)))
            else:
                setattr(res, i, data.get(i, None))
        res.update_defaults()
        return res
    def store(self):
        data = {}
        data['_type'] = self.__class__.__name__
        data['id'] = self.id
        data['name'] = self.name
        for i in self.properties:
            if isinstance(i, EncodedProperty):
                data[i.name] = i.encode(getattr(self, i.name))
            else:
                data[i] = getattr(self, i)
        return data
    def update_defaults(self):
        pass
    def resetTo(self, src):
        for i in self.properties:
            if isinstance(i, EncodedProperty):
                i.copyValue(self, src)
            else:
                setattr(self, i, getattr(src, i))
    def newInstance(self):
        res = self.__class__(None, self.name)
        res.base_object = self
        for i in self.properties:
            if isinstance(i, EncodedProperty):
                i.copyValue(res, self)
            else:
                setattr(res, i, getattr(self, i))
        res.update_defaults()
        return res
    def forget(self):
        IdSequence.unregister(self)

class CutterMaterial(Serializable):
    properties = []
    values = {}
    @staticmethod
    def toString(value):
        return value.name
    @staticmethod
    def add(value):
        CutterMaterial.values[value.name] = value
    @staticmethod
    def byName(name):
        return CutterMaterial.values[name]
    def is_carbide(self):
        return 'carbide' in self.name

class CutterBase(Serializable):
    properties = [ MaterialProperty('material'), 'diameter', 'length', 'flutes' ]
    def __init__(self, id, name):
        Serializable.__init__(self, id, name)
        self.presets = []
    @classmethod
    def new_impl(klass, id, name, material, diameter, length, flutes):
        res = klass(id, name)
        res.material = material
        res.diameter = float(diameter)
        res.length = float(length) if length is not None else None
        res.flutes = int(flutes) if flutes is not None else 0
        res.presets = []
        return res
    def description(self):
        return (self.name + ": " if self.name is not None else "") + self.description_only()
    def description_only(self):
        assert False
    def presetByName(self, name):
        for i in self.presets:
            if i.name == name:
                return i
        return None
    def deletePreset(self, preset):
        del self.presets[self.presets.index(preset)]
        IdSequence.unregister(preset)
    def undeletePreset(self, preset):
        self.presets.append(preset)
        IdSequence.register(preset.id, preset)
        
class MillDirection(EnumClass):
    CONVENTIONAL = 0
    CLIMB = 1
    descriptions = [
        (CONVENTIONAL, "Conventional", False),
        (CLIMB, "Climb", True),
    ]

class PocketStrategy(EnumClass):
    CONTOUR_PARALLEL = 1
    AXIS_PARALLEL = 2
    AXIS_PARALLEL_ZIGZAG = 3
    HSM_PEEL = 4
    HSM_PEEL_ZIGZAG = 5
    descriptions = [
        (CONTOUR_PARALLEL, "Contour-parallel"),
        (AXIS_PARALLEL, "Axis-parallel (v. slow)"),
        (AXIS_PARALLEL_ZIGZAG, "Axis-parallel w/zig-zag"),
        (HSM_PEEL, "Arc peel (HSM)"),
        (HSM_PEEL_ZIGZAG, "Arc peel w/zig-zag (HSM)"),
    ]

class EntryMode(EnumClass):
    PREFER_RAMP = 1
    PREFER_HELIX = 2
    #REQUIRE_HELIX = 3
    #PLUNGE = 4
    descriptions = [
        (PREFER_RAMP, "Prefer ramp"),
        (PREFER_HELIX, "Prefer helix"),
        #(REQUIRE_HELIX, "Require helix"),
        #(PLUNGE, "Vertical plunge"),
    ]

class PresetBase(Serializable):
    def description(self):
        if self.name:
            return f"{self.name} ({self.description_only()})"
        else:
            return self.description_only()

class EndMillPreset(PresetBase):
    properties = [ 'rpm', 'hfeed', 'vfeed', 'maxdoc', 'offset', 'stepover', 'direction', 'extra_width', 'trc_rate', 'pocket_strategy', 'axis_angle', 'eh_diameter', 'entry_mode', 'roughing_offset', IdRefProperty('toolbit') ]
    @classmethod
    def new(klass, id, name, toolbit, rpm, hfeed, vfeed, maxdoc, offset, stepover, direction, extra_width, trc_rate, pocket_strategy, axis_angle, eh_diameter, entry_mode, roughing_offset):
        res = klass(id, name)
        res.toolbit = toolbit
        res.rpm = rpm
        res.hfeed = hfeed
        res.vfeed = vfeed
        res.maxdoc = maxdoc
        res.offset = offset
        res.stepover = stepover
        res.direction = direction
        res.extra_width = extra_width
        res.trc_rate = trc_rate
        res.pocket_strategy = pocket_strategy
        res.axis_angle = axis_angle
        res.eh_diameter = eh_diameter
        res.entry_mode = entry_mode
        res.roughing_offset = roughing_offset
        return res
    def description_only(self):
        res = []
        if self.trc_rate:
            res.append(f"\u21f4")
        if self.hfeed:
            res.append(f"f\u2194{Format.feed(self.hfeed, brief=True)}")
        if self.vfeed:
            res.append(f"f\u2193{Format.feed(self.vfeed, brief=True)}")
        if self.maxdoc:
            res.append(f"\u21a7{Format.depth_of_cut(self.maxdoc, brief=True)}")
        if self.stepover:
            res.append(f"\u27f7{Format.as_percent(self.stepover, brief=True)}%")
        if self.rpm:
            res.append(f"\u27f3{Format.rpm(self.rpm, brief=True)}")
        if self.direction is not None:
            res.append(MillDirection.toString(self.direction))
        return " ".join(res)

class EndMillShape(EnumClass):
    FLAT = 0
    TAPERED = 1
    BALL = 2
    descriptions = [
        (FLAT, "Flat"),
        (TAPERED, "Tapered/Vee"),
        (BALL, "Ball nose"),
    ]

class EndMillCutter(CutterBase):
    cutter_type_name = "End mill"
    cutter_type_priority = 1
    preset_type = EndMillPreset
    properties = CutterBase.properties + ['shape', 'angle', 'tip_diameter']
    @classmethod
    def new(klass, id, name, material, diameter, length, flutes, shape, angle, tip_diameter):
        res = klass.new_impl(id, name, material, diameter, length, int(flutes))
        res.shape = shape
        res.angle = angle
        res.tip_diameter = tip_diameter
        res.update_defaults()
        return res
    def update_defaults(self):
        if self.shape is None:
            self.shape = EndMillShape.FLAT
        if self.angle is None:
            self.angle = 180
        if self.tip_diameter is None:
            self.tip_diameter = 0
    def addPreset(self, id, name, rpm, hfeed, vfeed, maxdoc, offset, stepover, direction, extra_width, trc_rate, pocket_strategy, axis_angle, eh_diameter, entry_mode, roughing_offset):
        self.presets.append(EndMillPreset.new(id, name, self, rpm, hfeed, vfeed, maxdoc, offset, stepover, direction, extra_width, trc_rate, pocket_strategy, axis_angle, eh_diameter, entry_mode, roughing_offset))
        return self
    def description_only(self):
        form = EndMillShape.toString(self.shape).lower() + " end mill"
        if self.shape == EndMillShape.TAPERED:
            form = f"{Format.angle(self.angle, brief=True)}\u00b0 {form}"
        if self.length is not None:
            return f"{self.flutes}F \u2300{Format.cutter_dia(self.diameter, brief=True)} L{Format.cutter_length(self.length, brief=True)} {self.material.name} {form}"
        else:
            return f"{self.flutes}F \u2300{Format.cutter_length(self.diameter, brief=True)} {self.material.name} {form}"
        
class DrillBitPreset(PresetBase):
    properties = [ 'rpm', 'vfeed', 'maxdoc', IdRefProperty('toolbit') ]
    @classmethod
    def new(klass, id, name, toolbit, rpm, vfeed, maxdoc):
        res = klass(id, name)
        res.toolbit = toolbit
        res.rpm = rpm
        res.vfeed = vfeed
        res.maxdoc = maxdoc
        return res
    def description_only(self):
        res = []
        if self.vfeed:
            res.append(f"f\u2193{Format.feed(self.vfeed, brief=True)}")
        if self.maxdoc:
            res.append(f"\u21a7{Format.depth_of_cut(self.maxdoc, brief=True)}")
        if self.rpm:
            res.append(f"\u27f3{Format.rpm(self.rpm, brief=True)}")
        return " ".join(res)

class DrillBitCutter(CutterBase):
    cutter_type_name = "Drill bit"
    cutter_type_priority = 2
    preset_type = DrillBitPreset
    @classmethod
    def new(klass, id, name, material, diameter, length, flutes=2):
        return klass.new_impl(id, name, material, diameter, length, flutes)
    def addPreset(self, id, name, rpm, vfeed, maxdoc):
        self.presets.append(DrillBitPreset.new(id, name, self, rpm, vfeed, maxdoc))
        return self
    def description_only(self):
        return f"{Format.cutter_dia(self.diameter)} {self.material.name} drill bit" + (f", L={Format.cutter_length(self.length)}" if self.length is not None else "")
    
class ThreadMillPreset(PresetBase):
    properties = [ 'rpm', 'vfeed', 'stepover', IdRefProperty('toolbit') ]
    @classmethod
    def new(klass, id, name, toolbit, rpm, vfeed, stepover):
        res = klass(id, name)
        res.toolbit = toolbit
        res.rpm = rpm
        res.vfeed = vfeed
        res.stepover = stepover
        return res
    def description_only(self):
        res = []
        if self.vfeed:
            res.append(f"f\u2193{Format.feed(self.vfeed, brief=True)}")
        if self.stepover:
            res.append(f"\u27f7{Format.as_percent(self.stepover, brief=True)}%")
        if self.rpm:
            res.append(f"\u27f3{Format.rpm(self.rpm, brief=True)}")
        return " ".join(res)

class ThreadMillCutter(CutterBase):
    cutter_type_name = "Thread mill"
    cutter_type_priority = 3
    preset_type = ThreadMillPreset
    properties = CutterBase.properties + ['min_pitch', 'max_pitch', 'thread_angle']
    @classmethod
    def new(klass, id, name, material, diameter, length, flutes, min_pitch, max_pitch, thread_angle=60):
        res = klass.new_impl(id, name, material, diameter, length, flutes)
        res.min_pitch = min_pitch
        res.max_pitch = max_pitch
        res.thread_angle = thread_angle or 60
        return res
    def description_only(self):
        if self.min_pitch == self.max_pitch:
            return f"{Format.cutter_dia(self.diameter)} {self.material.name} thread mill, P={Format.thread_pitch(self.min_pitch)}" + (f", L={Format.cutter_length(self.length)}" if self.length is not None else "")
        else:
            return f"{Format.cutter_dia(self.diameter)} {self.material.name} thread mill, P={Format.thread_pitch(self.min_pitch)}-{Format.thread_pitch(self.max_pitch)}" + (f", L={Format.cutter_length(self.length)}" if self.length is not None else "")

class WallProfileShapeProperty(EncodedProperty):
    def encode(self, value):
        return value.store()
    def decode(self, value):
        return UserDefinedWallProfile.load(value)
    def equals(self, v1, v2):
        return v1.top == v2.top and v1.bottom == v2.bottom

class InvWallProfile(Serializable):
    properties = [ WallProfileShapeProperty('shape'), "description" ]
    @classmethod
    def new(klass, id, name, description, top=None, bottom=None):
        res = InvWallProfile(id, name)
        res.description = description
        res.shape = UserDefinedWallProfile(top, bottom)
        return res

class Inventory(object):
    def __init__(self):
        self.cutter_materials = {}
        for name in ("HSS", "HSS+TiN", "HSSCo5", "HSSCo8", "carbide", "carbide+TiN", "carbide+TiCN", "carbide+TiSiN", "carbide+AlTiN", "carbide+TiAlN", "carbide+DLC"):
            self.addMaterial(CutterMaterial(None, name))
        for name in ("HSS", "carbide"):
            setattr(CutterMaterial, name, CutterMaterial.byName(name))
        self.toolbits = []
        self.wall_profiles = []
    def addMaterial(self, material):
        name = material.name
        CutterMaterial.add(material)
        self.cutter_materials[material.name] = material
    def addWallProfile(self, wall_profile):
        self.wall_profiles.append(wall_profile)
    def materialByName(self, name):
        return self.cutter_materials[name]
    def wallProfileByName(self, name):
        for i in self.wall_profiles:
            if i.name == name:
                return i
        return None
    def toolbitByName(self, name, klass=CutterBase):
        for i in self.toolbits:
            if i.name == name and isinstance(i, klass):
                return i
        return None
    def readFrom(self, filename):
        f = open(filename, "r")
        data = json.load(f)
        f.close()
        cutter_map = {}
        cm = data.get('cutter_materials', None)
        if cm:
            self.cutter_materials.clear()
            for i in data['cutter_materials']:
                self.addMaterial(CutterMaterial.load(i))
        self.toolbits.clear()
        for i in data['tools']:
            tool = CutterBase.load(i)
            if tool:
                cutter_map[tool.orig_id] = tool
                self.toolbits.append(tool)
        for i in data['presets']:
            preset = PresetBase.load(i)
            if preset:
                preset.toolbit = cutter_map[preset.toolbit]
                preset.toolbit.presets.append(preset)
        if 'wall_profiles' not in data:
            self.createStdWallProfiles()
        else:
            self.wall_profiles = []
            for i in data['wall_profiles']:
                profile = InvWallProfile.load(i)
                self.addWallProfile(profile)
        return True
    def createStdCutters(self):
        HSS = self.materialByName('HSS')
        carbide = self.materialByName('carbide')
        self.toolbits = [
            EndMillCutter.new(1, "cheapo 2F 3.2/15", carbide, 3.2, 15, 2, EndMillShape.FLAT, 0, 0)
                .addPreset(100, "Wood-roughing", 24000, 3200, 1500, 2, 0, 0.6, MillDirection.CONVENTIONAL, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5, EntryMode.PREFER_RAMP, 0.1)
                .addPreset(101, "Wood-finishing", 24000, 1600, 1500, 1, 0, 0.6, MillDirection.CLIMB, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5, EntryMode.PREFER_RAMP, 0.1),
            EndMillCutter.new(2, "cheapo 2F 2.5/12", carbide, 2.5, 12, 2, EndMillShape.FLAT, 0, 0)
                .addPreset(102, "Wood-roughing", 24000, 3200, 1500, 2, 0, 0.6, MillDirection.CONVENTIONAL, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5, EntryMode.PREFER_RAMP, 0.1)
                .addPreset(103, "Wood-finishing", 24000, 1600, 1500, 1, 0, 0.6, MillDirection.CLIMB, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5, EntryMode.PREFER_RAMP, 0.1),
            EndMillCutter.new(3, "cheapo 1F 3.2/15", carbide, 3.2, 15, 1, EndMillShape.FLAT, 0, 0)
                .addPreset(104, "Alu-risky", 16000, 500, 100, 0.5, 0, 0.4, MillDirection.CONVENTIONAL, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5, EntryMode.PREFER_HELIX, 0.15),
            EndMillCutter.new(4, "cheapo 1F 2/8", carbide, 2, 8, 1, EndMillShape.FLAT, 0, 0),
            EndMillCutter.new(5, "30\u00b0 0.3mm V-bit, 3.2mm shank", carbide, 3.2, None, 1, EndMillShape.TAPERED, 30, 0.3),
            DrillBitCutter.new(50, "2mm HSS", HSS, 2, 25)
                .addPreset(200, "Wood-untested", 10000, 100, 6),
            DrillBitCutter.new(51, "3mm HSS", HSS, 3, 41)
                .addPreset(201, "Wood-untested", 7000, 100, 6),
            DrillBitCutter.new(52, "4mm HSS", HSS, 4, 54)
                .addPreset(202, "Wood-untested", 5000, 100, 6),
            DrillBitCutter.new(53, "5mm HSS", HSS, 5, 62)
                .addPreset(203, "Wood-untested", 4000, 100, 6),
            DrillBitCutter.new(54, "6mm HSS", HSS, 6, 70)
                .addPreset(204, "Wood-untested", 3000, 100, 6),
        ]
    def createStdWallProfiles(self):
        self.wall_profiles = [
            InvWallProfile.new(81, '3° draft', "3 degree draft angle - for casting etc.", [WallProfileItem(0, 30, WallProfileItemType.TAPER, 3)]),
            InvWallProfile.new(82, '3° draft+r/o', "3 degree draft angle + roundover", [WallProfileItem(0, 2, WallProfileItemType.ROUND_H2V), WallProfileItem(-2, 30, WallProfileItemType.TAPER, 3)], [WallProfileItem(0, 2, WallProfileItemType.ROUND_V2H)]),
            InvWallProfile.new(83, '1mm chamfer', "45° chamfer of 1mm depth", [WallProfileItem(0, 1, WallProfileItemType.TAPER, 45)]),
            InvWallProfile.new(84, '2mm roundover', "2mm roundover top and bottom", [WallProfileItem(0, 2, WallProfileItemType.ROUND_H2V)], [WallProfileItem(0, 2, WallProfileItemType.ROUND_V2H)]),
        ]
    def deleteWallProfile(self, profile):
        self.wall_profiles = [p for p in self.wall_profiles if p is not profile]
        IdSequence.unregister(profile)
    def writeTo(self, dirname, filename):
        res = {
            'cutter_materials' : [ i.store() for i in self.cutter_materials.values() ],
            'tools' : [ i.store() for i in self.toolbits ],
            'presets' : [ j.store() for i in self.toolbits for j in i.presets ],
            'wall_profiles' : [ i.store() for i in self.wall_profiles ],
        }
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        f = open(os.path.join(dirname, filename), "w")
        json.dump(res, f, indent=2)
        f.close()
    def deleteCutter(self, cutter):
        del self.toolbits[self.toolbits.index(cutter)]
        IdSequence.unregister(cutter)

inventory = Inventory()
