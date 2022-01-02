from .propsheet import EnumClass

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

class CutterMaterial(object):
    def __init__(self, id, name):
        self.id = IdSequence.register(id, self)        
        self.name = name

class CutterBase(object):
    def __init__(self, id, name, material, diameter, length):
        self.id = IdSequence.register(id, self)
        self.name = name
        self.material = material
        self.diameter = float(diameter)
        self.length = float(length)
        self.presets = []
    def description(self):
        assert False
        
class MillDirection(EnumClass):
    CONVENTIONAL = 0
    CLIMB = 1
    descriptions = [
        (CONVENTIONAL, "Conventional", False),
        (CLIMB, "Climb", True),
    ]

class EndMillPreset(object):
    def __init__(self, id, name, toolbit, rpm, hfeed, vfeed, maxdoc, stepover, direction):
        self.id = IdSequence.register(id, self)
        self.name = name
        self.toolbit = toolbit
        self.rpm = rpm
        self.hfeed = hfeed
        self.vfeed = vfeed
        self.maxdoc = maxdoc
        self.stepover = stepover
        self.direction = direction
    def description(self):
        return f"{self.name}: Fxy{self.hfeed:0.0f} Fz{self.vfeed:0.0f} DOC{self.maxdoc:0.2f} SO{100*self.stepover:0.0f}% {MillDirection.toString(self.direction)}"

class EndMillCutter(CutterBase):
    def __init__(self, id, name, material, diameter, length, flutes):
        CutterBase.__init__(self, id, name, material, diameter, length)
        self.flutes = flutes
    def addPreset(self, id, name, rpm, hfeed, vfeed, maxdoc, stepover, direction):
        self.presets.append(EndMillPreset(id, name, self, rpm, hfeed, vfeed, maxdoc, stepover, direction))
        return self
    def description(self):
        optname = self.name + ": " if self.name is not None else ""
        return optname + f"{self.flutes}F D{self.diameter:0.1f} L{self.length:0.1f} {self.material.name} end mill"
        
class DrillBitCutter(CutterBase):
    def description(self):
        return f"D{self.diameter:0.1f} L{self.length:0.1f} {self.material.name} drill bit"
    
class Inventory(object):
    def __init__(self):
        self.cutter_materials = []
        for name in ("HSS", "HSSCo", "carbide", "TiN", "AlTiN"):
            material = CutterMaterial(None, name)
            setattr(CutterMaterial, name, material)
            self.cutter_materials.append(name)
        self.toolbits = [
            EndMillCutter(1, "cheapo 2F 3.2/15", CutterMaterial.carbide, 3.2, 15, 2)
                .addPreset(100, "Wood-roughing", 24000, 3200, 1500, 2, 0.6, MillDirection.CONVENTIONAL)
                .addPreset(101, "Wood-finishing", 24000, 1600, 1500, 1, 0.6, MillDirection.CLIMB),
            EndMillCutter(2, "cheapo 2F 2.5/12", CutterMaterial.carbide, 2.5, 12, 2)
                .addPreset(102, "Wood-roughing", 24000, 3200, 1500, 2, 0.6, MillDirection.CONVENTIONAL)
                .addPreset(103, "Wood-finishing", 24000, 1600, 1500, 1, 0.6, MillDirection.CLIMB),
            EndMillCutter(3, "cheapo 1F 3.2/15", CutterMaterial.carbide, 3.2, 15, 1)
                .addPreset(104, "Alu-risky", 16000, 500, 100, 0.5, 0.4, MillDirection.CONVENTIONAL),
            EndMillCutter(4, "cheapo 1F 2/8", CutterMaterial.carbide, 2, 8, 1),
            DrillBitCutter(50, "2mm HSS", CutterMaterial.HSS, 2, 25),
            DrillBitCutter(51, "3mm HSS", CutterMaterial.HSS, 3, 41),
            DrillBitCutter(52, "4mm HSS", CutterMaterial.HSS, 4, 54),
            DrillBitCutter(53, "5mm HSS", CutterMaterial.HSS, 5, 62),
            DrillBitCutter(54, "6mm HSS", CutterMaterial.HSS, 6, 70),
        ]
    def getToolbitList(self, data_type):
        return [(tb.id, tb.description()) for tb in self.toolbits if isinstance(tb, data_type) and tb.presets]

inventory = Inventory()
