import os.path
import sys

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.common import geom, guiutils
from DerpCAM.gui.propsheet import BaseCreateEditDialog, FloatDistEditableProperty
from DerpCAM.gui.model import DrawingCircleTreeItem, DrawingPolylineTreeItem

class DrawCircleDialog(BaseCreateEditDialog):
    def __init__(self, parent, document):
        BaseCreateEditDialog.__init__(self, parent, "Add a circle")
        self.document = document
    def properties(self):
        return [i for i in DrawingCircleTreeItem.properties() if i.attribute != 'radius']
    def processResult(self, result):
        return DrawingCircleTreeItem(self.document, geom.PathPoint(result['x'], result['y']), result['diameter'] / 2.0)


class DrawRectangleDialog(BaseCreateEditDialog):
    prop_left = FloatDistEditableProperty("Left", "x1", guiutils.Format.coord, unit="mm", allow_none=False)
    prop_top = FloatDistEditableProperty("Top", "y1", guiutils.Format.coord, unit="mm", allow_none=False)
    prop_right = FloatDistEditableProperty("Right", "x2", guiutils.Format.coord, unit="mm", allow_none=False)
    prop_bottom = FloatDistEditableProperty("Bottom", "y2", guiutils.Format.coord, unit="mm", allow_none=False)

    def __init__(self, parent, document):
        BaseCreateEditDialog.__init__(self, parent, "Add an axis-aligned rectangle")
        self.document = document
    def properties(self):
        return [self.prop_left, self.prop_top, self.prop_right, self.prop_bottom]
    def processResult(self, result):
        x1 = result['x1']
        x2 = result['x2']
        y1 = result['y1']
        y2 = result['y2']
        points = [geom.PathPoint(x1, y1), geom.PathPoint(x2, y1), geom.PathPoint(x2, y2), geom.PathPoint(x1, y2)]
        return DrawingPolylineTreeItem(self.document, points, True)



