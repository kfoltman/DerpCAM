from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

class GuiSettings(object):
    inch_mode = False

class UnitConverter(object):
    alt_units = {"in", "sfm", "ipm", "ipt"}
    @staticmethod
    def fromInch(value, multiplier=25.4):
        value = value.strip()
        if '/' in value:
            wholes = 0
            if ' ' in value:
                # Mixed numbers like 1 1/4"
                wholesStr, value = value.split(" ", 1)
                wholes = int(wholesStr)
            num, denom = value.split("/", 1)
            return str((float(num) + wholes * float(denom)) * multiplier / float(denom))
        return str(float(value) * multiplier)
    @staticmethod
    def fromMetric(value, multiplier):
        value = value.strip()
        if '/' in value:
            num, denom = value.split("/", 1)
            return str(float(num) * multiplier / float(denom))
        return str(float(value) * multiplier)
    @staticmethod
    def isAltUnit(unit):
        return unit in UnitConverter.alt_units
    @staticmethod
    def curUnit(unit):
        return UnitConverter.altUnit(unit) if GuiSettings.inch_mode else unit
    @staticmethod
    def formatCurrent(value, format, unit):
        return UnitConverter.format(value, format, UnitConverter.curUnit(unit))
    @staticmethod
    def altUnit(unit):
        if unit in UnitConverter.alt_units:
            return unit
        if unit == "mm" or unit == 'cm' or unit == 'dm' or unit == 'm':
            return "in"
        elif unit == 'm':
            return "ft"
        elif unit == "mm/min":
            return "ipm"
        elif unit == "mm/tooth":
            return "ipt"
        elif unit == "m/min":
            return "sfm"
        elif unit == "rpm" or unit == '%' or unit == '' or unit == '\u00b0':
            return unit
        else:
            assert False, f"Unhandled unit: {unit}"
    @staticmethod
    def fmt(value, dp, suffix, force_suffix, binary_fractions=False):
        suffix = force_suffix if force_suffix is not None else suffix
        if binary_fractions and value != round(value):
            max_denom = 64
            value = round(value, dp)
            num = round(value * max_denom * 1.0)
            value2 = num / (max_denom * 1.0)
            if num != 0 and abs(value - value2) < pow(0.1, dp):
                num = int(num)
                denom = max_denom
                while (num & 1) == 0 and denom > 1:
                    num = num >> 1
                    denom = denom >> 1
                if num >= denom:
                    whole = num // denom
                    num = num % denom
                    return f"{whole} {num}/{denom}" + suffix
                return f"{num}/{denom}" + suffix
        s = f"%0.{dp}f" % (value,)
        if '.' in s:
            s = s.rstrip("0").rstrip(".")
        s += suffix
        return s
    @staticmethod
    def format(value, unit, dp, force_suffix):
        fmt = UnitConverter.fmt
        if unit == 'mm':
            return fmt(value, dp, " mm", force_suffix)
        elif unit == 'cm':
            return fmt(value / 10.0, dp + 1, " cm", force_suffix)
        elif unit == 'dm':
            return fmt(value / 100.0, dp + 2, " dm", force_suffix)
        elif unit == 'm':
            return fmt(value / 1000.0, dp + 3, " m", force_suffix)
        elif unit == 'in':
            # XXXKF fractions
            return fmt(value / 25.4, dp + 1, '"', force_suffix, binary_fractions=True)
        elif unit == 'ft':
            return fmt(value / (12 * 25.4), dp + 2, "'", force_suffix)
        elif unit == 'mm/min' or unit == 'mm/tooth':
            return fmt(value, dp, " " + unit, force_suffix)
        elif unit == 'm/min':
            return fmt(value / 1000.0, dp + 3, " m/min", force_suffix)
        elif unit == 'sfm':
            return fmt(value / (12 * 25.4), dp + 2, " " + unit, force_suffix)
        elif unit == 'ipm' or unit == 'ipt':
            return fmt(value / 25.4, dp + 1, " " + unit, force_suffix)
        elif unit == 'rpm':
            return fmt(value, dp, " rpm", force_suffix)
        elif unit == '':
            return fmt(value, dp, "", force_suffix)
        elif unit == '%':
            return fmt(value * 100, dp, " %", force_suffix)
        elif unit == '\u00b0':
            return fmt(value, dp, " " + unit, force_suffix)
        else:
            raise ValueError(f"Unknown unit {unit}")
        # XXXKF percent, angle
    @staticmethod
    def parse(value, unit, as_float=False):
        value2 = value.strip()
        if unit == "m/min":
            if value2.endswith('sfm'):
                unit = "sfm"
                value = UnitConverter.fromInch(value2[:-3], 1000.0 / (12 * 25.4))
            elif value2.endswith('m/min'):
                unit = "m/min"
                value = UnitConverter.fromMetric(value2[:-5], 1)
            elif GuiSettings.inch_mode:
                unit = "sfm"
                value = UnitConverter.fromInch(value2, 1000.0 / (12 * 25.4))
        elif unit == "mm/min":
            if value2.endswith('ipm'):
                unit = "ipm"
                value = UnitConverter.fromInch(value2[:-3])
            elif value2.endswith('in/min'):
                unit = "ipm"
                value = UnitConverter.fromInch(value2[:-6])
            elif value2.endswith('mm/min'):
                unit = "mm/min"
                value = UnitConverter.fromMetric(value2[:-6], 1)
            elif GuiSettings.inch_mode:
                unit = "ipm"
                value = UnitConverter.fromInch(value2)
            else:
                value = value2
        elif unit == "mm":
            if value2.endswith('in'):
                unit = "in"
                value = UnitConverter.fromInch(value2[:-2])
            elif value2.endswith('"'):
                unit = "in"
                value = UnitConverter.fromInch(value2[:-1])
            elif value2.endswith('mm'):
                unit = "mm"
                value = UnitConverter.fromMetric(value2[:-2], 1)
            elif value2.endswith('cm'):
                unit = "cm"
                value = UnitConverter.fromMetric(value2[:-2], 10)
            elif value2.endswith('dm'):
                unit = "dm"
                value = UnitConverter.fromMetric(value2[:-2], 100)
            elif value2.endswith('m'):
                unit = "m"
                value = UnitConverter.fromMetric(value2[:-2], 1000)
            elif GuiSettings.inch_mode:
                value = UnitConverter.fromInch(value2)
            else:
                value = value2
        elif unit == "rpm":
            if value2.endswith("rpm"):
                value = value2[:-3].strip()
        elif unit == "":
            if value2.endswith("%"):
                value = str(float(value2) / 100.0)
        elif unit == "%":
            if value2.endswith("%"):
                # Dodgy special case, a bare value is the same as percent value
                value2 = value2[:-1].strip()
            value = str(float(value2))
        elif unit == "\u00b0": # degrees
            if value2.endswith("\u00b0"):
                value = value2[:-1].strip()
        else:
            raise ValueError(f"Unknown unit: {unit}")
        if as_float:
            value = float(value)
        return value, unit

class Format(object):
    @staticmethod
    def fmt(dp, unit="mm", suffix=None):
        return lambda value, alt_suffix=None, brief=False: UnitConverter.format(value, UnitConverter.curUnit(unit), dp, "" if brief else (alt_suffix or suffix))
    cutter_dia = fmt(3)
    cutter_length = fmt(2)
    depth_of_cut = fmt(3)
    feed = fmt(1, unit="mm/min")
    rpm = fmt(1, unit="rpm")
    surf_speed = fmt(2, unit="m/min")
    chipload = fmt(4, unit="mm/tooth")
    coord = fmt(2)
    angle = fmt(2, unit='\u00b0')
    percent = fmt(2, unit='', suffix=" %")
    as_percent = fmt(2, unit='%')
    @staticmethod
    def coord_unit():
        return UnitConverter.curUnit("mm")
    @staticmethod
    def point_tuple(value, brief=False):
        return f"({Format.coord(value[0], brief=brief)}, {Format.coord(value[1], brief=brief)})"
    @staticmethod
    def point(value, brief=False):
        return Format.point_tuple((value.x, value.y), brief=brief)

def is_gui_application():
    return isinstance(QCoreApplication.instance(), QGuiApplication)

class Spinner(object):
    def __enter__(self):
        if is_gui_application():
            QGuiApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if is_gui_application():
            QGuiApplication.restoreOverrideCursor()
