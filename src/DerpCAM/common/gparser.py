import math
import re
import sys

class GcodeLine(object):
    def __init__(self, xs, ys, zs, xe, ye, ze, feed):
        self.xs = xs
        self.ys = ys
        self.zs = zs
        self.xe = xe
        self.ye = ye
        self.ze = ze
        self.feed = feed

class GcodeArc(GcodeLine):
    def __init__(self, xs, ys, zs, xe, ye, ze, xc, yc, clockwise, feed):
        GcodeLine.__init__(self, xs, ys, zs, xe, ye, ze, feed)
        self.xc = xc
        self.yc = yc
        self.clockwise = clockwise

class RewriteGcodeReceiver(object):
    def __init__(self):
        self.cmds = []
    def handleRest(self, cmd, data):
        self.cmds.append(cmd.as_gcode(data))
    def handleFeed(self, feed, data):
        self.cmds.append("F%s" % feed)
    def handleSpeed(self, speed, data):
        self.cmds.append("S%s" % speed)
    
class TestGcodeReceiver(object):
    def __init__(self):
        self.isRelative = False
        self.isMetric = True
        self.x = 0
        self.y = 0
        self.z = 0
        self.feed = None
        self.speed = None
        self.motions = []
        self.bbox_min = None
        self.bbox_max = None
    def addCoord(self, x, y, z):
        if self.bbox_min is None:
            self.bbox_min = (x, y, z)
            self.bbox_max = self.bbox_min
        else:
            self.bbox_min = (min(self.bbox_min[0], x), min(self.bbox_min[1], y), min(self.bbox_min[2], z))
            self.bbox_max = (max(self.bbox_max[0], x), max(self.bbox_max[1], y), max(self.bbox_max[2], z))
    def handleDistanceCommand(self, cmd, data):
        self.isRelative = cmd.name == "Relative"
    def handleUnitsCommand(self, cmd, data):
        self.isMetric = cmd.name == "Metric"
    def handlePlaneCommand(self, cmd, data):
        if cmd.name != "PlaneXY":
            raise Exception("Plane not XY")
    def handleDwellCommand(self, cmd, data):
        print("Dwell: %s seconds" % data.get('P', 0))
    def handleMotionCommand(self, cmd, data):
        x = data.get('X', 0 if self.isRelative else self.x)
        y = data.get('Y', 0 if self.isRelative else self.y)
        z = data.get('Z', 0 if self.isRelative else self.z)
        if self.isRelative:
            x += self.x
            y += self.y
            z += self.z
        self.addCoord(x, y, z)
        if cmd.name[0] == 'A': # Arc motion
            xc = self.x + data.get('I', 0) # won't support absolute arc mode (G90.1?), not handled by grbl
            yc = self.y + data.get('J', 0)
            self.handleArc(x, y, z, xc, yc, cmd.name == "ArcCW", self.feed)
        else:
            self.handleLine(x, y, z, None if cmd.name == "Rapid" else self.feed)
        self.x = x
        self.y = y
        self.z = z
    def handleArc(self, x, y, z, xc, yc, clockwise, feed):
        #print "%s Arc: (%f, %f, %f) -> (%f, %f, %f), (%f, %f) with feed=%s" % ("CW" if clockwise else "CCW", self.x, self.y, self.z, x, y, z, xc, yc, feed)
        r1 = ((self.x - xc) ** 2 + (self.y - yc) ** 2) ** 0.5
        r2 = ((x - xc) ** 2 + (y - yc) ** 2) ** 0.5
        r = max(r1, r2)
        # XXXKF This is a little bit heavy-handed, as it adds the whole circle instead
        # of just the part covered by the arc - however, this might be sufficient
        # for now
        self.addCoord(xc - r, yc - r, z)
        self.addCoord(xc + r, yc + r, z)
        #print "R1 = %s, R2 = %s" % (r1, r2)
        self.motions.append(GcodeArc(self.x, self.y, self.z, x, y, z, xc, yc, clockwise, feed))
    def handleLine(self, x, y, z, feed):
        #if feed is None:
        #    print "Rapid: (%f, %f, %f) -> (%f, %f, %f)" % (self.x, self.y, self.z, x, y, z)
        #else:
        #    print "Feed: (%f, %f, %f) -> (%f, %f, %f) with feed=%s" % (self.x, self.y, self.z, x, y, z, feed)
        self.motions.append(GcodeLine(self.x, self.y, self.z, x, y, z, feed))
    def handleFeed(self, feed, data):
        self.feed = feed
    def handleSpeed(self, speed, data):
        self.speed = speed

class GcodeCommand(object):
    modal = False
    def __init__(self, name, as_gcode = None):
        self.name = name
        self.gcode = as_gcode
    def __str__(self):
        return self.name
    def __repr__(self):
        return "%s('%s')" % (self.__class__.__name__, self.name)
    def as_gcode(self, data):
        if self.gcode is None:
            raise Exception("Unimplemented as_gcode for %s" % self.name)
        return self.gcode
    def get_family(self):
        return self.__class__.__name__
    def execute(self, receiver, data):
        f = "handle" + self.get_family()
        if hasattr(receiver, f):
            getattr(receiver, f)(self, data)
        else:
            if hasattr(receiver, "handleRest"):
                receiver.handleRest(self, data)
            else:
                print("Executing unimplemented %s" % self.get_family())
        
class FeedCommand(GcodeCommand):
    def __init__(self, feed):
        GcodeCommand.__init__(self, "Feed")
        self.feed = feed
    def as_gcode(self, data):
        return "F%s" % data.get('F', self.feed)
    def execute(self, receiver, data):
        receiver.handleFeed(self.feed, data)

class SpeedCommand(GcodeCommand):
    def __init__(self, speed):
        GcodeCommand.__init__(self, "Speed")
        self.speed = speed
    def as_gcode(self, data):
        return "S%s" % data.get('S', self.speed)
    def execute(self, receiver, data):
        receiver.handleSpeed(self.speed, data)

class MotionCommand(GcodeCommand):
    modal = True
    def as_gcode(self, data):
        cmd = "%s" % self.gcode
        for v in "XYZIJK":
            if v in data:
                cmd += " %s%s" % (v, ("%0.6f" % data[v]).rstrip('0').rstrip('.'))
        return cmd

class PlaneCommand(GcodeCommand):
    pass

class DistanceCommand(GcodeCommand):
    pass

class CoordCommand(GcodeCommand):
    pass

class UnitsCommand(GcodeCommand):
    pass

class SpindleCommand(GcodeCommand):
    pass

class StopCommand(GcodeCommand):
    pass

class DwellCommand(GcodeCommand):
    pass

cmdTypeList = [
    # Feed rate mode (G93/G94),
    FeedCommand,
    SpeedCommand,
    # Tool,
    # Tool changes,
    SpindleCommand,
    # Save state etc.,
    # Coolant,
    # Overrides,
    # User defined commands,
    DwellCommand,
    PlaneCommand,
    UnitsCommand,
    #TRC,
    #TLC,
    CoordCommand,
    #Path control,
    DistanceCommand,
    #Retract mode,
    #Go to reference location,
    MotionCommand,
    StopCommand
]

class GcodeCommands(object):
    G0  = MotionCommand("Rapid", "G0")
    G1  = MotionCommand("Feed", "G1")
    G2  = MotionCommand("ArcCW", "G2")
    G3  = MotionCommand("ArcCCW", "G3")
    G4  = DwellCommand("Dwell", "G4")
    G17 = PlaneCommand("PlaneXY", "G17")
    G20 = UnitsCommand("Inches", "G20")
    G21 = UnitsCommand("Metric", "G21")
    G54 = CoordCommand("Coord1", "G54")
    G55 = CoordCommand("Coord2", "G55")
    G56 = CoordCommand("Coord3", "G56")
    G57 = CoordCommand("Coord4", "G57")
    G58 = CoordCommand("Coord5", "G58")
    G59 = CoordCommand("Coord6", "G59")
    G90 = DistanceCommand("Absolute", "G90")
    G91 = DistanceCommand("Relative", "G91")
    M0  = GcodeCommand("Pause", "M0")
    M1  = GcodeCommand("PauseIf", "M1")
    M2  = StopCommand("End2", "M2")
    M3  = SpindleCommand("SpindleCW", "M3")
    M4  = SpindleCommand("SpindleCCW", "M4")
    M5  = SpindleCommand("SpindleOff", "M5")
    M30 = StopCommand("End30", "M30")

class GcodeState(object):
    def __init__(self, receiver):
        self.receiver = receiver
        self.word_extractor = re.compile("([A-Za-z])([-+0-9.]*)")
        self.sticky_state = {}
    @staticmethod
    def prepare(line):
        line = line.strip()
        comment = None
        if '(' in line or ';' in line:
            is_comment = False
            is_siemens_comment = False
            line2 = ''
            for item in re.split('\((.*?)\)', line):
                if is_siemens_comment:
                    if is_comment:
                        comment += "(%s)" % item
                    else:
                        comment += item
                else:
                    if not is_comment:
                        sc = item.find(';')
                        if sc > 0:
                            comment = item[sc + 1:]
                            is_siemens_comment = True
                            line2 += item[0:sc]
                        else:
                            line2 += item
                    else:
                        comment = item
                is_comment = not is_comment
            line = line2
        return line, comment
    def handle_line(self, line):
        words = {}
        words.update(self.sticky_state)
        line, comment = self.prepare(line)
        for word, value in self.word_extractor.findall(line):
            if value != "":
                valueFloat = float(value)
            else:
                valueFloat = None
            word = word.upper()
            #print word, value
            if word in ['F']:
                words['FeedCommand'] = FeedCommand(valueFloat)
            elif word in ['S']:
                words['SpeedCommand'] = SpeedCommand(valueFloat)
            elif word in ['G', 'M']:
                cmd, subcmd = int(valueFloat), int(valueFloat * 10) % 10
                if subcmd > 0:
                    cmd = "%s%s_%s" % (word, cmd, subcmd)
                else:
                    cmd = "%s%s" % (word, cmd)
                if hasattr(GcodeCommands, cmd):
                    cmdo = getattr(GcodeCommands, cmd)
                    words[cmdo.get_family()] = cmdo
                else:
                    words[word] = valueFloat
            else:
                words[word] = valueFloat
        for ctype in cmdTypeList:
            cname = ctype.__name__
            if cname in words:
                words[cname].execute(self.receiver, words)
                if ctype.modal:
                    self.sticky_state[cname] = words[cname]

if __name__ == "__main__":
    lines = list(map(str.strip, open(sys.argv[1], "r").readlines()))

    rec = RewriteGcodeReceiver()
    gs = GcodeState(rec)
    for l in lines:
        rec.cmds = []
        gs.handle_line(l)
        print(" ".join(rec.cmds))
