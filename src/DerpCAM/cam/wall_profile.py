import math

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

