from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

class Format(object):
    @staticmethod
    def dp(value, dp):
        s = f"%0.{dp}f" % (value,)
        if '.' in s:
            s = s.rstrip("0").rstrip(".")
        return s
    @staticmethod
    def cutter_dia(value):
        return Format.dp(value, 3)
    @staticmethod
    def cutter_length(value):
        return Format.dp(value, 2)
    @staticmethod
    def depth_of_cut(value):
        return Format.dp(value, 3)
    @staticmethod
    def feed(value):
        return Format.dp(value, 1)
    @staticmethod
    def rpm(value):
        return Format.dp(value, 1)
    @staticmethod
    def surf_speed(value):
        return Format.dp(value, 2)
    @staticmethod
    def chipload(value):
        return Format.dp(value, 4)
    @staticmethod
    def coord(value):
        return Format.dp(value, 3)
    @staticmethod
    def coord_unit():
        return "mm"
    @staticmethod
    def point(value):
        return f"({Format.coord(value.x)}, {Format.coord(value.y)})"
    @staticmethod
    def point_tuple(value):
        return f"({Format.coord(value[0])}, {Format.coord(value[1])})"
    @staticmethod
    def angle(value):
        return Format.dp(value, 2)
    @staticmethod
    def percent(value):
        return Format.dp(value, 2)
    @staticmethod
    def as_percent(value):
        return Format.dp(value * 100, 2) + "%"

def is_gui_application():
    return isinstance(QCoreApplication.instance(), QGuiApplication)

class Spinner(object):
    def __enter__(self):
        if is_gui_application():
            QGuiApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if is_gui_application():
            QGuiApplication.restoreOverrideCursor()
