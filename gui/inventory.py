from .propsheet import EnumClass
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
    def decode(self, value):
        return getattr(CutterMaterial, value)
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
            klass2 = getattr(sys.modules[__name__], rtype)
            if issubclass(klass2, klass):
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
        return res

class CutterMaterial(Serializable):
    properties = []

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

class PresetBase(Serializable):
    def description(self):
        if self.name:
            return f"{self.name} ({self.description_only()})"
        else:
            return self.description_only()

class EndMillPreset(PresetBase):
    properties = [ 'rpm', 'hfeed', 'vfeed', 'maxdoc', 'stepover', 'direction', 'extra_width', 'trc_rate', 'pocket_strategy', 'axis_angle', 'eh_diameter', IdRefProperty('toolbit') ]
    @classmethod
    def new(klass, id, name, toolbit, rpm, hfeed, vfeed, maxdoc, stepover, direction, extra_width, trc_rate, pocket_strategy, axis_angle, eh_diameter):
        res = klass(id, name)
        res.toolbit = toolbit
        res.rpm = rpm
        res.hfeed = hfeed
        res.vfeed = vfeed
        res.maxdoc = maxdoc
        res.stepover = stepover
        res.direction = direction
        res.extra_width = extra_width
        res.trc_rate = trc_rate
        res.pocket_strategy = pocket_strategy
        res.axis_angle = axis_angle
        res.eh_diameter = eh_diameter
        return res
    def description_only(self):
        res = []
        if self.trc_rate:
            res.append(f"\u21f4")
        if self.hfeed:
            res.append(f"f\u2194{self.hfeed:0.0f}")
        if self.vfeed:
            res.append(f"f\u2193{self.vfeed:0.0f}")
        if self.maxdoc:
            res.append(f"\u21a7{self.maxdoc:0.2f}")
        if self.stepover:
            res.append(f"\u27f7{100 * self.stepover:0.0f}%")
        if self.rpm:
            res.append(f"\u27f3{self.rpm:0.0f}")
        if self.direction is not None:
            res.append(MillDirection.toString(self.direction))
        return " ".join(res)

class EndMillCutter(CutterBase):
    cutter_type_name = "End mill"
    cutter_type_priority = 1
    properties = CutterBase.properties
    @classmethod
    def new(klass, id, name, material, diameter, length, flutes):
        res = klass.new_impl(id, name, material, diameter, length, int(flutes))
        return res
    def addPreset(self, id, name, rpm, hfeed, vfeed, maxdoc, stepover, direction, extra_width, trc_rate, pocket_strategy, axis_angle, eh_diameter):
        self.presets.append(EndMillPreset.new(id, name, self, rpm, hfeed, vfeed, maxdoc, stepover, direction, extra_width, trc_rate, pocket_strategy, axis_angle, eh_diameter))
        return self
    def description_only(self):
        if self.length is not None:
            if (int(self.length * 10) % 10) != 0:
                return f"{self.flutes}F \u2300{self.diameter:0.1f} L{self.length:0.1f} {self.material.name} end mill"
            else:
                return f"{self.flutes}F \u2300{self.diameter:0.1f} L{self.length:0.0f} {self.material.name} end mill"
        else:
            return f"{self.flutes}F \u2300{self.diameter:0.1f} {self.material.name} end mill"
        
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
            res.append(f"f\u2193{self.vfeed:0.0f}")
        if self.maxdoc:
            res.append(f"\u21a7{self.maxdoc:0.2f}")
        if self.rpm:
            res.append(f"\u27f3{self.rpm:0.0f}")
        return " ".join(res)

class DrillBitCutter(CutterBase):
    cutter_type_name = "Drill bit"
    cutter_type_priority = 2
    @classmethod
    def new(klass, id, name, material, diameter, length, flutes=2):
        return klass.new_impl(id, name, material, diameter, length, flutes)
    def addPreset(self, id, name, rpm, vfeed, maxdoc):
        self.presets.append(DrillBitPreset.new(id, name, self, rpm, vfeed, maxdoc))
        return self
    def description_only(self):
        if (int(self.diameter * 10) % 10) != 0:
            return f"{self.diameter:0.1f}mm {self.material.name} drill bit" + (f", L={self.length:0.0f}mm" if self.length is not None else "")
        else:
            return f"{self.diameter:0.0f}mm {self.material.name} drill bit" + (f", L={self.length:0.0f}mm" if self.length is not None else "")
    
class Inventory(object):
    def __init__(self):
        self.cutter_materials = []
        for name in ("HSS", "HSSCo", "carbide", "TiN", "AlTiN"):
            material = CutterMaterial(None, name)
            setattr(CutterMaterial, name, material)
            self.cutter_materials.append(name)
        self.toolbits = []
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
        for i in data['tools']:
            tool = CutterBase.load(i)
            cutter_map[tool.orig_id] = tool
            self.toolbits.append(tool)
        for i in data['presets']:
            preset = PresetBase.load(i)
            preset.toolbit = cutter_map[preset.toolbit]
            preset.toolbit.presets.append(preset)
        return True
    def createStdCutters(self):
        self.toolbits = [
            EndMillCutter.new(1, "cheapo 2F 3.2/15", CutterMaterial.carbide, 3.2, 15, 2)
                .addPreset(100, "Wood-roughing", 24000, 3200, 1500, 2, 0.6, MillDirection.CONVENTIONAL, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5)
                .addPreset(101, "Wood-finishing", 24000, 1600, 1500, 1, 0.6, MillDirection.CLIMB, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5),
            EndMillCutter.new(2, "cheapo 2F 2.5/12", CutterMaterial.carbide, 2.5, 12, 2)
                .addPreset(102, "Wood-roughing", 24000, 3200, 1500, 2, 0.6, MillDirection.CONVENTIONAL, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5)
                .addPreset(103, "Wood-finishing", 24000, 1600, 1500, 1, 0.6, MillDirection.CLIMB, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5),
            EndMillCutter.new(3, "cheapo 1F 3.2/15", CutterMaterial.carbide, 3.2, 15, 1)
                .addPreset(104, "Alu-risky", 16000, 500, 100, 0.5, 0.4, MillDirection.CONVENTIONAL, 0, 0, PocketStrategy.CONTOUR_PARALLEL, 0, 0.5),
            EndMillCutter.new(4, "cheapo 1F 2/8", CutterMaterial.carbide, 2, 8, 1),
            DrillBitCutter.new(50, "2mm HSS", CutterMaterial.HSS, 2, 25)
                .addPreset(200, "Wood-untested", 10000, 100, 6),
            DrillBitCutter.new(51, "3mm HSS", CutterMaterial.HSS, 3, 41)
                .addPreset(201, "Wood-untested", 7000, 100, 6),
            DrillBitCutter.new(52, "4mm HSS", CutterMaterial.HSS, 4, 54)
                .addPreset(202, "Wood-untested", 5000, 100, 6),
            DrillBitCutter.new(53, "5mm HSS", CutterMaterial.HSS, 5, 62)
                .addPreset(203, "Wood-untested", 4000, 100, 6),
            DrillBitCutter.new(54, "6mm HSS", CutterMaterial.HSS, 6, 70)
                .addPreset(204, "Wood-untested", 3000, 100, 6),
        ]
    def writeTo(self, dirname, filename):
        res = { 'tools' : [ i.store() for i in self.toolbits ], 'presets' : [ j.store() for i in self.toolbits for j in i.presets ] }
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        f = open(os.path.join(dirname, filename), "w")
        json.dump(res, f, indent=2)
        f.close()

inventory = Inventory()
