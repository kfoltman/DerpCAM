from .propsheet import EnumClass
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
        return getattr(v1, self.name).id == getattr(v2, self.name).id

class Serializable(object):
    def __init__(self, id, name):
        self.id = IdSequence.register(id, self)
        self.name = name
        self.orig_id = None
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

class CutterMaterial(Serializable):
    properties = []

class CutterBase(Serializable):
    properties = [ MaterialProperty('material'), 'diameter', 'length', 'flutes' ]
    def __init__(self, id, name):
        Serializable.__init__(self, id, name)
        self.presets = []
    @classmethod
    def new_impl(klass, id, name, material, diameter, length):
        res = klass(id, name)
        res.material = material
        res.diameter = float(diameter)
        res.length = float(length) if length is not None else None
        res.presets = []
        return res
    def description(self):
        return (self.name + ": " if self.name is not None else "") + self.description_only()
    def description_only(self):
        assert False
        
class MillDirection(EnumClass):
    CONVENTIONAL = 0
    CLIMB = 1
    descriptions = [
        (CONVENTIONAL, "Conventional", False),
        (CLIMB, "Climb", True),
    ]

class PresetBase(Serializable):
    def description(self):
        return (self.name + ": " if self.name is not None else "") + self.description_only()

class EndMillPreset(PresetBase):
    properties = [ 'rpm', 'hfeed', 'vfeed', 'maxdoc', 'stepover', 'direction', IdRefProperty('toolbit') ]
    @classmethod
    def new(klass, id, name, toolbit, rpm, hfeed, vfeed, maxdoc, stepover, direction):
        res = klass(id, name)
        res.toolbit = toolbit
        res.rpm = rpm
        res.hfeed = hfeed
        res.vfeed = vfeed
        res.maxdoc = maxdoc
        res.stepover = stepover
        res.direction = direction
        return res
    def description(self):
        if self.name:
            return f"{self.name}: {self.description_only()}"
        else:
            return self.description_only()
    def description_only(self):
        res = []
        if self.hfeed:
            res.append(f"Fxy{self.hfeed:0.0f}")
        if self.vfeed:
            res.append(f"Fz{self.vfeed:0.0f}")
        if self.maxdoc:
            res.append(f"DOC{self.maxdoc:0.2f}")
        if self.stepover:
            res.append(f"SO{self.stepover:0.0f}%")
        if self.direction is not None:
            res.append(MillDirection.toString(self.direction))
        return " ".join(res)

class EndMillCutter(CutterBase):
    cutter_type_name = "End mill"
    properties = CutterBase.properties + [ 'flutes' ]
    @classmethod
    def new(klass, id, name, material, diameter, length, flutes):
        res = klass.new_impl(id, name, material, diameter, length)
        res.flutes = flutes
        return res
    def addPreset(self, id, name, rpm, hfeed, vfeed, maxdoc, stepover, direction):
        self.presets.append(EndMillPreset.new(id, name, self, rpm, hfeed, vfeed, maxdoc, stepover, direction))
        return self
    def description_only(self):
        if self.length is not None:
            return f"{self.flutes}F D{self.diameter:0.1f} L{self.length:0.1f} {self.material.name} end mill"
        else:
            return f"{self.flutes}F D{self.diameter:0.1f} {self.material.name} end mill"
        
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
            res.append(f"Fz{self.vfeed:0.0f}")
        if self.maxdoc:
            res.append(f"DOC{self.maxdoc:0.2f}")
        return " ".join(res)

class DrillBitCutter(CutterBase):
    cutter_type_name = "Drill bit"
    @classmethod
    def new(klass, id, name, material, diameter, length):
        return klass.new_impl(id, name, material, diameter, length)
    def addPreset(self, id, name, rpm, vfeed, maxdoc):
        self.presets.append(DrillBitPreset.new(id, name, self, rpm, vfeed, maxdoc))
        return self
    def description_only(self):
        return f"{self.diameter:0.1f}mm {self.material.name} drill bit" + (f", L={self.length:0.0f}mm" if self.length is not None else "")
    
class Inventory(object):
    def __init__(self):
        self.cutter_materials = []
        for name in ("HSS", "HSSCo", "carbide", "TiN", "AlTiN"):
            material = CutterMaterial(None, name)
            setattr(CutterMaterial, name, material)
            self.cutter_materials.append(name)
        self.toolbits = [
            EndMillCutter.new(1, "cheapo 2F 3.2/15", CutterMaterial.carbide, 3.2, 15, 2)
                .addPreset(100, "Wood-roughing", 24000, 3200, 1500, 2, 0.6, MillDirection.CONVENTIONAL)
                .addPreset(101, "Wood-finishing", 24000, 1600, 1500, 1, 0.6, MillDirection.CLIMB),
            EndMillCutter.new(2, "cheapo 2F 2.5/12", CutterMaterial.carbide, 2.5, 12, 2)
                .addPreset(102, "Wood-roughing", 24000, 3200, 1500, 2, 0.6, MillDirection.CONVENTIONAL)
                .addPreset(103, "Wood-finishing", 24000, 1600, 1500, 1, 0.6, MillDirection.CLIMB),
            EndMillCutter.new(3, "cheapo 1F 3.2/15", CutterMaterial.carbide, 3.2, 15, 1)
                .addPreset(104, "Alu-risky", 16000, 500, 100, 0.5, 0.4, MillDirection.CONVENTIONAL),
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

inventory = Inventory()
