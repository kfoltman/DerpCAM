import json
import math
import os.path
import sys
import threading
import time

import ezdxf
import pyclipper

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.common import geom
from DerpCAM.common.guiutils import Format, Spinner, is_gui_application
from DerpCAM import cam
from DerpCAM.cam import dogbone, gcodegen, gcodeops, shapes, milling_tool

from . import canvas, inventory
from .propsheet import EnumClass, IntEditableProperty, \
    FloatDistEditableProperty, EnumEditableProperty, SetEditableProperty, \
    RefEditableProperty, StringEditableProperty, FontEditableProperty

class InvalidateAspect:
    PROPERTIES = 1
    CAM = 2

class CAMTreeItem(QStandardItem):
    loaders = {
    }
    aliases = {
        'MaterialTreeItem' : 'WorkpieceTreeItem',
    }
    @classmethod
    def register_class(klass, klass2, name=None):
        klass2.loaders[name or klass2.__name__] = lambda document: klass2(document)
        return klass2
    def __init__(self, document, name=None):
        QStandardItem.__init__(self, name)
        self.document = document
        self.setEditable(False)
    def emitPropertyChanged(self, name=""):
        self.document.propertyChanged.emit(self, name)
    def format_item_as(self, role, def_value, bold=None, italic=None, color=None):
        if role == Qt.FontRole:
            font = QFont()
            if bold is not None:
                font.setBold(bold)
            if italic is not None:
                font.setItalic(italic)
            return QVariant(font)
        if color is not None and role == Qt.TextColorRole:
            return QVariant(color)
        return def_value

    def store(self):
        dump = {}
        dump['_type'] = type(self).__name__
        for prop in self.properties():
            dump[prop.attribute] = getattr(self, prop.attribute)
        return dump
    def class_specific_load(self, dump):
        pass
    def reload(self, dump):
        rtype = dump['_type']
        if rtype != type(self).__name__:
            if not (rtype == 'MaterialTreeItem' and isinstance(self, WorkpieceTreeItem)):
                raise ValueError("Unexpected type: %s" % rtype)
        for prop in self.properties():
            if prop.attribute in dump:
                setattr(self, prop.attribute, dump[prop.attribute])
        self.class_specific_load(dump)

    @staticmethod
    def load(document, dump):
        rtype = dump['_type']
        rtype = CAMTreeItem.aliases.get(rtype, rtype)
        loader = CAMTreeItem.loaders.get(rtype)
        if loader:
            res = loader(document)
        else:
            raise ValueError("Unexpected item type: %s" % rtype)
        res.reload(dump)
        return res
    def properties(self):
        return []
    def reorderItemImpl(self, direction, parent):
        row = self.row()
        if direction < 0 and row > 0:
            self.document.opMoveItem(parent, self, parent, row - 1)
            return self.index()
        elif direction > 0 and row < parent.rowCount() - 1:
            self.document.opMoveItem(parent, self, parent, row + 1)
            return self.index()
        return None
    def items(self):
        i = 0
        while i < self.rowCount():
            yield self.child(i)
            i += 1
    def __hash__(self):
        return id(self)
    def __eq__(self, other):
        return other is self
    def __ne__(self, other):
        return other is not self

class CAMListTreeItem(CAMTreeItem):
    def __init__(self, document, name):
        CAMTreeItem.__init__(self, document, name)
        self.reset()
    def reset(self):
        self.resetProperties()
    def resetProperties(self):
        pass
    
class CAMListTreeItemWithChildren(CAMListTreeItem):
    def __init__(self, document, title):
        # Child items already in a tree
        self.child_items = {}
        # Deleted child items
        self.recycled_items = {}
        CAMListTreeItem.__init__(self, document, title)
    def childList(self):
        # Returns list of data items that map to child nodes in the tree
        assert False
    def createChildItem(self, data):
        # Returns a CAMListTreeItem for a data item
        assert False
    def syncChildren(self):
        expectedChildren = self.childList()
        # Recycle (without deleting) child items deleted from the list
        # (they may still be referenced in undo)
        excess = set(self.child_items.keys()) - set(expectedChildren)
        for child in excess:
            self.recycled_items[child] = self.takeRow(self.child_items.pop(child).row())[0]
        for child in expectedChildren:
            item = self.child_items.get(child, None)
            if item is None:
                item = self.recycled_items.pop(child, None)
                if item is None:
                    item = self.createChildItem(child)
                self.child_items[child] = item
                self.appendRow(item)
            if hasattr(item, 'syncChildren'):
                item.syncChildren()
        self.sortChildren(0)
    def reset(self):
        CAMListTreeItem.reset(self)
        self.syncChildren()

class OperationType(EnumClass):
    OUTSIDE_CONTOUR = 1
    INSIDE_CONTOUR = 2
    POCKET = 3
    ENGRAVE = 4
    INTERPOLATED_HOLE = 5
    DRILLED_HOLE = 6
    SIDE_MILL = 7
    REFINE = 8
    FACE = 9
    V_CARVE = 10
    PATTERN_FILL = 11
    INSIDE_THREAD = 12
    descriptions = [
        (OUTSIDE_CONTOUR, "Outside contour"),
        (INSIDE_CONTOUR, "Inside contour"),
        (POCKET, "Pocket"),
        (ENGRAVE, "Engrave"),
        (INTERPOLATED_HOLE, "H-Hole"),
        (DRILLED_HOLE, "Drill"),
        (SIDE_MILL, "Side mill"),
        (REFINE, "Refine"),
        (FACE, "Face mill"),
        (V_CARVE, "V-Carve"),
        (PATTERN_FILL, "Pattern fill"),
        (INSIDE_THREAD, "Internal thread"),
    ]
    @staticmethod
    def has_islands(value):
        return value in (OperationType.POCKET, OperationType.SIDE_MILL, OperationType.FACE, OperationType.V_CARVE, OperationType.PATTERN_FILL)
    @staticmethod
    def has_stepover(value):
        return value in (OperationType.POCKET, OperationType.SIDE_MILL, OperationType.REFINE, OperationType.FACE, OperationType.INTERPOLATED_HOLE, OperationType.INSIDE_THREAD)
    @staticmethod
    def has_entry_helix(value):
        return value in (OperationType.POCKET, OperationType.REFINE, OperationType.FACE, OperationType.INTERPOLATED_HOLE)

class FillType(EnumClass):
    LINES = 1
    CROSS = 2
    DIAMOND = 3
    HEX = 4
    TEETH = 5
    BRICK = 6
    descriptions = [
        (LINES, "Parallel lines", "lines"),
        (CROSS, "Cross hatch", "cross"),
        (DIAMOND, "Diamond hatch", "diamond"),
        (HEX, "Hex/honeycomb", "hex"),
        (TEETH, "Teeth/steps", "teeth"),
        (BRICK, "Bricks", "brick"),
    ]

def cutterTypesForOperationType(operationType):
    if operationType == OperationType.INSIDE_THREAD:
        return inventory.ThreadMillCutter
    elif operationType == OperationType.DRILLED_HOLE:
        return (inventory.DrillBitCutter, inventory.EndMillCutter)
    else:
        return inventory.EndMillCutter


class PropertySetUndoCommand(QUndoCommand):
    def __init__(self, property, subject, old_value, new_value):
        QUndoCommand.__init__(self, "Set " + property.name)
        self.property = property
        self.subject = subject
        self.old_value = old_value
        self.new_value = new_value
    def undo(self):
        self.property.setData(self.subject, self.old_value)
    def redo(self):
        self.property.setData(self.subject, self.new_value)

class MultipleItemUndoContext(object):
    def __init__(self, document, items, title_func):
        self.document = document
        self.items = items
        self.title_func = title_func
    def __enter__(self):
        if self.items and len(self.items) > 1:
            self.document.undoStack.beginMacro(self.title_func(len(self.items)))
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.items and len(self.items) > 1:
            self.document.undoStack.endMacro()

