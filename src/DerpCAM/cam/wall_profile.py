import math
from DerpCAM.common.guiutils import EnumClass

class BaseWallProfile(object):
    def offset_at_depth(self, z, total_depth):
        assert False

class PlainWallProfile(BaseWallProfile):
    def offset_at_depth(self, depth, total_depth):
        # Note: depth is in positive=deeper
        return 0

class DraftWallProfile(BaseWallProfile):
    def __init__(self, angle_deg):
        self.angle_deg = angle_deg
        self.draft = math.tan(angle_deg * math.pi / 180)
    def offset_at_depth(self, depth, total_depth):
        return self.draft * depth

class TopChamferWallProfile(BaseWallProfile):
    def __init__(self, angle_deg, length):
        self.angle_deg = angle_deg
        self.draft = math.tan(angle_deg * math.pi / 180)
        self.length = length
    def offset_at_depth(self, depth, total_depth):
        if depth <= length:
            return 0
        return self.draft * (depth - self.length)

class TopRoundoverWallProfile(BaseWallProfile):
    def __init__(self, r):
        self.r = r
    def offset_at_depth(self, depth, total_depth):
        if depth < self.r:
            return math.sqrt(self.r ** 2 - (self.r - depth) ** 2)
        return self.r

class BottomRoundoverWallProfile(BaseWallProfile):
    def __init__(self, r):
        self.r = r
    def offset_at_depth(self, depth, total_depth):
        depth = total_depth - depth
        if depth >= self.r:
            return 0
        return self.r - math.sqrt(self.r ** 2 - (self.r - depth) ** 2)

class CompositeWallProfile(BaseWallProfile):
    def __init__(self, *args):
        self.args = args
    def offset_at_depth(self, depth, total_depth):
        return sum([i.offset_at_depth(depth, total_depth) for i in self.args])

class WallProfileItemType(EnumClass):
    REBATE = 0
    TAPER = 1
    ROUND_H2V = 2
    ROUND_V2H = 3

    descriptions = [
        (REBATE, "Rebate/Rabbet"),
        (TAPER, "Taper/Draft \ /"),
        (ROUND_H2V, "Round H to V \u25DD \u25DC"),
        (ROUND_V2H, "Round V to H \u25DF \u25DE"),
    ]

class WallProfileItem:
    def __init__(self, offset=0, height=0, shape=WallProfileItemType.REBATE, arg=0):
        self.offset = offset
        self.height = height
        self.shape = shape
        self.rebate = arg if shape == WallProfileItemType.REBATE else 0
        self.taper = arg if shape == WallProfileItemType.TAPER else 0
    def offset_at_pos(self, pos, height_left):
        height = min(self.height, max(0, height_left))
        # pos = distance upwards from the bottom of this layer
        pos = min(self.height, pos)
        if self.shape == WallProfileItemType.REBATE:
            return self.rebate if pos < 0 else 0
        pos = max(0, pos)
        if self.shape == WallProfileItemType.TAPER:
            return math.tan(self.taper * math.pi / 180) * max(0, (height - min(height, pos)))
        elif self.shape == WallProfileItemType.ROUND_V2H:
            return math.sqrt(self.height ** 2 - pos ** 2)
        elif self.shape == WallProfileItemType.ROUND_H2V:
            return self.height - math.sqrt(self.height ** 2 - (self.height - pos) ** 2)
    def store(self):
        res = { 'offset' : self.offset, 'height' : self.height, 'shape' : WallProfileItemType.toString(self.shape) }
        if self.rebate != 0:
            res['rebate'] = self.rebate
        if self.taper != 0:
            res['taper'] = self.taper
        return res
    @staticmethod
    def load(data):
        return WallProfileItem(data.get('offset', 0), data.get('height', 0), WallProfileItemType.itemFromString(data.get('shape'), WallProfileItemType.REBATE), data.get('rebate', 0) or data.get('taper', 0))
    def __eq__(self, other):
        return self.offset == other.offset and self.height == other.height and self.shape == other.shape and (self.shape != WallProfileItemType.REBATE or self.rebate == other.rebate) and (self.shape != WallProfileItemType.TAPER or self.taper == other.taper)

class UserDefinedWallProfile(BaseWallProfile):
    def __init__(self, top=None, bottom=None, align=None):
        self.top = top or []
        self.bottom = bottom or []
        self.align = align if align is not None else 0
    def store(self):
        return { "top" : [ i.store() for i in self.top ], "bottom" : [ i.store() for i in self.bottom ], "align" : self.align }
    @classmethod
    def load(klass, data):
        res = klass()
        if "align" in data:
            res.align = data["align"]
        for i in data["top"]:
            res.top.append(WallProfileItem.load(i))
        for i in data["bottom"]:
            res.bottom.append(WallProfileItem.load(i))
        return res
    def clone(self):
        return self.load(self.store())
    def offset_at_depth(self, depth, total_depth):
        offset = 0
        pos = 0
        top_offset = 0
        for i in self.top:
            pos += i.offset
            offset += i.offset_at_pos(depth - pos, total_depth - pos)
            top_offset += i.offset_at_pos(0 - pos, total_depth - pos)
            pos += i.height
        pos = total_depth
        bottom_offset = 0
        for i in reversed(self.bottom):
            pos -= i.offset
            pos -= i.height
            offset += i.offset_at_pos(depth - pos, total_depth - pos)
            bottom_offset += i.offset_at_pos(0 - pos, total_depth - pos)
        if self.align == 0:
            return -offset
        if self.align == 1:
            return -offset + bottom_offset
        if self.align == 2:
            return -offset + top_offset + bottom_offset
