import math
import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.common import geom, guiutils, view
from DerpCAM.gui import drawing_model, model

class CanvasEditor(object):
    def __init__(self, item):
        self.item = item
        self.can_cancel = False
    def initUI(self, parent, canvas):
        self.parent = parent
        self.canvas = canvas
        self.parent.setWidget(QWidget())
        self.layout = QFormLayout()
        self.setTitle()
        self.createControls()
        self.connectSignals()
    def cancel(self):
        if self.cancel_index is not None and self.item is not None:
            while self.item.document.undoStack.index() > self.cancel_index:
                self.item.document.undoStack.undo()
        if self.canvas.editor:
            self.canvas.exitEditMode(False)
    def createControls(self):
        self.createLabel()
        self.createSnapMode()
        self.createExtraControls()
        self.createButtons()
        self.updateLabel()
        self.updateControls()
        self.parent.widget().setLayout(self.layout)
    def createSnapMode(self):
        pass
    def createExtraControls(self):
        pass
    def connectSignals(self):
        pass
    def updateControls(self):
        pass
    def createLabel(self):
        self.descriptionLabel = QLabel()
        self.descriptionLabel.setFrameShape(QFrame.Panel)
        self.descriptionLabel.setMargin(5)
        self.descriptionLabel.setWordWrap(True)
        self.layout.addWidget(self.descriptionLabel)
    def createButtons(self):
        self.applyButton = QPushButton(self.parent.style().standardIcon(QStyle.SP_DialogApplyButton), "&Apply")
        self.applyButton.clicked.connect(lambda: self.apply())
        if self.can_cancel:
            self.cancelButton = QPushButton(self.parent.style().standardIcon(QStyle.SP_DialogCancelButton), "&Cancel")
            self.cancelButton.clicked.connect(lambda: self.cancel())
            self.btnLayout = QHBoxLayout()
            self.btnLayout.addWidget(self.applyButton)
            self.btnLayout.addWidget(self.cancelButton)
            self.layout.addRow(self.btnLayout)
        else:
            self.layout.addWidget(self.applyButton)
    def snapCoords(self, pt):
        return pt
    def apply(self):
        self.parent.applyClicked.emit()
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Return or e.key() == Qt.Key_Enter:
            self.apply()
        if e.key() == Qt.Key_Escape and self.can_cancel:
            self.cancel()
    def onExit(self):
        if self.item is not None and isinstance(self.item, model.DrawingItemTreeItem):
            self.item.emitPropertyChanged()
    def mousePressEvent(self, e):
        return False
    def mouseMoveEvent(self, e):
        return False
    def mouseReleaseEvent(self, e):
        return False
    def mouseDoubleClickEvent(self, e):
        pass
    def penForPath(self, item, path):
        return None
    def onShapesDeleted(self, shapes):
        pass
    def drawPreview(self, qp, item, ox, oy):
        item.createPaths()
        oldTransform = qp.transform()
        transform = self.canvas.drawingTransform()
        qp.setTransform(transform)
        qp.setPen(QPen(QColor(0, 0, 0, 128), 1.0 / self.canvas.scalingFactor()))
        tempRenderer = TempRenderer(self.canvas)
        item.translated(ox, oy).renderTo(tempRenderer, None)
        tempRenderer.paint(qp, self.canvas)
        qp.setTransform(oldTransform)

class TempRenderer:
    def __init__(self, canvas):
        self.drawingOps = []
        self.canvas = canvas
    def scalingFactor(self):
        return self.canvas.scalingFactor()
    def addLines(self, pen, points, closed):
        if closed:
            points = points + points[0:1]
        path = QPainterPath()
        view.addPolylineToPath(path, points)
        self.drawingOps.append((pen, path))
    def paint(self, qp, canvas):
        oldPen = qp.pen()
        for pen, path in self.drawingOps:
            qp.drawPath(path)
        qp.setPen(oldPen)

class CanvasEditorWithSnap(CanvasEditor):
    snapMode = 7
    def createSnapMode(self):
        self.snapGroup = QGroupBox("Snap mode")
        self.snapLayout = QHBoxLayout()
        self.snapButtons = []
        def mkButton(idx, mode):
            btn = QPushButton(mode)
            btn.setCheckable(True)
            btn.setChecked((self.snapMode & (1 << idx)) != 0)
            btn.clicked.connect(lambda: self.onSnapButtonClicked(idx))
            return btn
        for idx, mode in enumerate(["Grid", "Endpoints", "Centre"]):
            btn = mkButton(idx, mode)
            self.snapButtons.append(btn)
            self.snapLayout.addWidget(btn)
        self.snapGroup.setLayout(self.snapLayout)
        self.layout.addRow(self.snapGroup)
    def onSnapButtonClicked(self, which):
        if self.snapButtons[which].isChecked():
            self.snapMode |= 1 << which
        else:
            self.snapMode &= ~(1 << which)
    def coordSnapValue(self):
        if guiutils.GuiSettings.inch_mode:
            if self.canvas.scalingFactor() >= 16:
                return 128 / 25.4
            elif self.canvas.scalingFactor() >= 1:
                return 16 / 25.4
            else:
                return 2 / 25.4
        else:
            if self.canvas.scalingFactor() >= 330:
                return 100
            elif self.canvas.scalingFactor() >= 33:
                return 10
            else:
                return 1
    def excludeSnapPoints(self):
        return None
    def snapCoords(self, pt):
        threshold = 10 / self.canvas.scalingFactor()
        drawing = self.document.drawing
        pt2 = geom.PathPoint(pt.x + drawing.x_offset, pt.y + drawing.y_offset)
        if self.snapMode & 6:
            points = set()
            if self.snapMode & 2:
                points |= drawing.snapEndPoints()
            if self.snapMode & 4:
                points |= drawing.snapCentrePoints()
            excluded = self.excludeSnapPoints()
            if excluded:
                points -= excluded
            for i in points:
                if geom.dist_fast(i, pt2) < threshold:
                    return geom.PathPoint(i.x - drawing.x_offset, i.y - drawing.y_offset)
        if self.snapMode & 1:
            snap = self.coordSnapValue()
            def cround(val):
                val = round(val * snap) / snap
                # Replace -0 by 0
                return val if val else 0
            return geom.PathPoint(cround(pt.x), cround(pt.y))
        return pt
    def snapInfo(self):
        if guiutils.GuiSettings.inch_mode:
            return f"snap=1/{(25.4 * self.coordSnapValue()):0.0f} in (zoom-dependent)"
        else:
            return f"snap={1.0 / self.coordSnapValue():0.2f} mm (zoom-dependent)"
    def paintCoords(self, qp, loc, ox, oy):
        coordsText = "(" + guiutils.Format.coord(loc.x - ox, brief=True) + guiutils.UnitConverter.itemSeparator() + " " + guiutils.Format.coord(loc.y - oy, brief=True) + ")"
        metrics = QFontMetrics(qp.font())
        size = metrics.size(Qt.TextSingleLine, coordsText)
        width = size.width() + 10
        hbox2a = QPointF(width / 2, size.height() + 1)
        hbox2b = QPointF(width / 2, 5)
        displ = QPointF(0, 7.5)
        pt = self.canvas.project(QPointF(loc.x - ox, loc.y - oy))
        qp.drawText(QRectF(pt - hbox2a - displ, pt + hbox2b - displ), Qt.AlignBottom | Qt.AlignCenter, coordsText)

class CanvasEditorPickPoint(CanvasEditorWithSnap):
    def __init__(self, document):
        CanvasEditorWithSnap.__init__(self, None)
        self.document = document
        self.can_cancel = True
        self.cancel_index = None
        self.mouse_point = None
    def pointSelected(self):
        self.apply()
    def mousePointFromEvent(self, e):
        pos = self.canvas.unproject(e.localPos())
        pt = geom.PathPoint(pos.x(), pos.y())
        self.mouse_point = self.snapCoords(pt)
    def mouseMoveEvent(self, e):
        self.mousePointFromEvent(e)
        self.canvas.repaint()
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.mousePointFromEvent(e)
            self.pointSelected()
            return True
    def paint(self, e, qp):
        if self.mouse_point is not None:
            pen = qp.pen()
            qp.setPen(QPen(QColor(0, 0, 0), 0))
            pos = self.canvas.project(QPointF(self.mouse_point.x, self.mouse_point.y))
            qp.drawLine(pos - QPointF(5, 5), pos + QPointF(5, 5))
            qp.drawLine(pos - QPointF(-5, 5), pos + QPointF(-5, 5))
            qp.setPen(pen)
            self.paintCoords(qp, self.mouse_point, 0, 0)

class CanvasSetOriginEditor(CanvasEditorPickPoint):
    def __init__(self, document):
        CanvasEditorPickPoint.__init__(self, document)
        self.origin = QPointF(self.document.drawing.x_offset, self.document.drawing.y_offset)
    def setTitle(self):
        self.parent.setWindowTitle("Set origin point of the drawing")
    def updateLabel(self):
        self.descriptionLabel.setText("Click the new origin point.")
    def apply(self):
        DrawingTreeItem = drawing_model.DrawingTreeItem
        self.document.opChangeProperty(DrawingTreeItem.prop_x_offset, [(self.document.drawing, self.origin.x() + self.mouse_point.x)])
        self.document.opChangeProperty(DrawingTreeItem.prop_y_offset, [(self.document.drawing, self.origin.y() + self.mouse_point.y)])
        self.parent.applyClicked.emit()

class CanvasCopyEditor(CanvasEditorPickPoint):
    def setTitle(self):
        self.parent.setWindowTitle("Copy objects - select reference point")
    def updateLabel(self):
        self.descriptionLabel.setText("Click the reference point for the objects.")

class CanvasCutEditor(CanvasCopyEditor):
    def setTitle(self):
        self.parent.setWindowTitle("Cut objects - select reference point")

class CanvasPasteEditor(CanvasEditorPickPoint):
    def __init__(self, document, clipboard):
        CanvasEditorPickPoint.__init__(self, document)
        self.origin = clipboard[0]
        self.objects = [model.DrawingItemTreeItem.load(self.document, item_json) for item_json in clipboard[1]]
    def setTitle(self):
        self.parent.setWindowTitle("Paste objects - select insertion point")
    def updateLabel(self):
        self.descriptionLabel.setText("Click the insertion point for the objects.")
    def paint(self, e, qp):
        CanvasEditorPickPoint.paint(self, e, qp)
        if self.mouse_point is not None:
            dx = self.mouse_point.x - self.origin.x - self.document.drawing.x_offset
            dy = self.mouse_point.y - self.origin.y - self.document.drawing.y_offset
            for item in self.objects:
                self.drawPreview(qp, item, dx, dy)

class CanvasMoveEditor(CanvasEditorPickPoint):
    mode = 0
    rows = 2
    cols = 2
    def __init__(self, document, objects):
        CanvasEditorPickPoint.__init__(self, document)
        self.objects = objects
        self.stage = 0
        self.origin_point = None
    def setTitle(self):
        if self.stage == 0:
            self.parent.setWindowTitle("Move/clone objects - select origin reference point")
        else:
            self.parent.setWindowTitle("Move/clone objects - select target reference point")
    def updateLabel(self):
        if self.stage == 0:
            self.descriptionLabel.setText("Click the origin reference point for moving/cloning the objects.")
        else:
            self.descriptionLabel.setText("Click the target reference point for moving/cloning the objects.")
    def updateControls(self):
        self.updateButtons()
    def updateButtons(self):
        self.applyButton.setText(["Move", "Clone", "Create array"][self.mode])
        self.applyButton.setEnabled(self.stage == 1)
        self.modeRadioMove.setChecked(self.mode == 0)
        self.modeRadioClone.setChecked(self.mode == 1)
        self.modeRadioArray.setChecked(self.mode == 2)
    def createExtraControls(self):
        self.modeGroupBox = QGroupBox()
        self.modeRadioMove = QRadioButton("&Move the item(s)")
        self.modeRadioClone = QRadioButton("&Clone the item(s)")
        self.modeRadioArray = QRadioButton("Create an &array")
        self.modeGroupBoxLayout = QVBoxLayout()
        self.modeGroupBoxLayout.addWidget(self.modeRadioMove)
        self.modeGroupBoxLayout.addWidget(self.modeRadioClone)
        self.arrayLayout = QHBoxLayout()
        self.arrayLayout.addWidget(self.modeRadioArray)
        self.arrayRows = guiutils.intSpin(1, 100, self.rows, "Rows in the array")
        self.arrayLayout.addWidget(self.arrayRows)
        self.arrayLayout.addWidget(QLabel("rows x"))
        self.arrayCols = guiutils.intSpin(1, 100, self.cols, "Columns in the array")
        self.arrayLayout.addWidget(self.arrayCols)
        self.arrayLayout.addWidget(QLabel("columns"))
        self.arrayLayout.addStretch()
        self.modeGroupBoxLayout.addLayout(self.arrayLayout)
        self.modeGroupBox.setLayout(self.modeGroupBoxLayout)
        self.layout.addRow(self.modeGroupBox)
        self.modeRadioMove.clicked.connect(lambda: self.setMode(0))
        self.modeRadioClone.clicked.connect(lambda: self.setMode(1))
        self.modeRadioArray.clicked.connect(lambda: self.setMode(2))
    def setMode(self, mode):
        CanvasMoveEditor.mode = mode
        self.updateButtons()
    def pointSelected(self):
        if self.stage == 0:
            self.origin_point = self.mouse_point
            self.stage = 1
            self.setTitle()
            self.updateLabel()
            self.updateControls()
        else:
            self.apply()
    def paint(self, e, qp):
        CanvasEditorPickPoint.paint(self, e, qp)
        if self.origin_point is not None:
            dx = self.mouse_point.x - self.origin_point.x
            dy = self.mouse_point.y - self.origin_point.y
            ox = self.document.drawing.x_offset
            oy = self.document.drawing.y_offset
            if self.mode != 2:
                for item in self.objects:
                    self.drawPreview(qp, item, dx - ox, dy - oy)
            else:
                for i in range(self.arrayCols.value()):
                    dx2 = dx * i
                    for j in range(self.arrayRows.value()):
                        dy2 = dy * j
                        for item in self.objects:
                            self.drawPreview(qp, item, dx2 - ox, dy2 - oy)
    def apply(self):
        if self.stage == 1:
            paste_point = self.mouse_point
            dx = paste_point.x - self.origin_point.x
            dy = paste_point.y - self.origin_point.y
            if self.mode == 1:
                items = [model.DrawingItemTreeItem.load(self.document, item.store()).translated(dx, dy).reset_untransformed().reset_id() for item in self.objects]
                self.document.opAddDrawingItems(items)
            elif self.mode == 2:
                if dx == 0 and self.arrayCols.value() > 1:
                    QMessageBox.critical(self.parent, None, "Multiple columns but horizontal spacing is zero")
                    return
                if dy == 0 and self.arrayRows.value() > 1:
                    QMessageBox.critical(self.parent, None, "Multiple rows but vertical spacing is zero")
                    return
                CanvasMoveEditor.rows = self.arrayRows.value()
                CanvasMoveEditor.cols = self.arrayCols.value()
                items = []
                for i in range(self.cols):
                    dx2 = dx * i
                    for j in range(self.rows):
                        dy2 = dy * j
                        if i or j:
                            items += [model.DrawingItemTreeItem.load(self.document, item.store()).translated(dx2, dy2).reset_untransformed().reset_id() for item in self.objects]
                self.document.opAddDrawingItems(items)
                CanvasEditorPickPoint.apply(self)
            else:
                self.document.opMoveDrawingItems(self.objects, dx, dy)
                CanvasEditorPickPoint.apply(self)

class CanvasRotateEditor(CanvasEditorPickPoint):
    deleteOrig = True
    count = 1
    def __init__(self, document, objects):
        CanvasEditorPickPoint.__init__(self, document)
        self.objects = objects
        self.stage = 0
        self.centre_point = None
        self.first_arm = None
    def setTitle(self):
        if self.stage == 0:
            self.parent.setWindowTitle("Rotate objects - select centre of rotation")
        elif self.stage == 1:
            self.parent.setWindowTitle("Rotate objects - set the first arm of the angle")
        else:
            self.parent.setWindowTitle("Rotate objects - set the second arm of the angle")
    def updateLabel(self):
        if self.stage == 0:
            self.descriptionLabel.setText("Click the centre of rotation.")
        elif self.stage == 1:
            self.descriptionLabel.setText("Click to determine the first (origin) arm of rotation angle.")
        else:
            self.descriptionLabel.setText("Click to determine the second (target) arm of rotation angle.")
    def updateControls(self):
        self.updateButtons()
    def updateButtons(self):
        self.applyButton.setText("Rotate")
        self.applyButton.setEnabled(self.stage == 2)
        self.deleteOriginalButton.setChecked(self.deleteOrig)
    def createExtraControls(self):
        self.deleteOriginalButton = QCheckBox("&Delete original")
        self.optionsLayout = QVBoxLayout()
        self.optionsLayout.addWidget(self.deleteOriginalButton)
        self.arrayLayout = QHBoxLayout()
        self.arrayCount = guiutils.intSpin(1, 100, self.count, "Number of copies added")
        self.arrayLayout.addWidget(QLabel("Copies:"))
        self.arrayLayout.addWidget(self.arrayCount)
        self.arrayLayout.addStretch()
        self.optionsLayout.addLayout(self.arrayLayout)
        self.layout.addRow(self.optionsLayout)
        self.deleteOriginalButton.clicked.connect(lambda: self.setDeleteOriginal(self.deleteOriginalButton.isChecked()))
    def setDeleteOriginal(self, value):
        CanvasRotateEditor.deleteOrig = value
        self.updateButtons()
    def pointSelected(self):
        if self.stage == 0:
            self.centre_point = self.mouse_point
            self.stage = 1
            self.setTitle()
            self.updateLabel()
            self.updateControls()
        elif self.stage == 1:
            self.first_arm = self.mouse_point
            self.stage = 2
            self.setTitle()
            self.updateLabel()
            self.updateControls()
        else:
            self.apply()
    def getTransform(self, second_arm):
        ox = self.centre_point.x
        oy = self.centre_point.y
        angle1 = math.atan2(self.first_arm.y - oy, self.first_arm.x - ox)
        angle2 = math.atan2(second_arm.y - oy, second_arm.x - ox)
        rotation = angle2 - angle1
        return ox, oy, rotation
    def drawPreview(self, qp, item, ox, oy, rotation):
        item.createPaths()
        oldTransform = qp.transform()
        transform = self.canvas.drawingTransform()
        qp.setTransform(transform)
        qp.setPen(QPen(QColor(0, 0, 0, 128), 1.0 / self.canvas.scalingFactor()))
        tempRenderer = TempRenderer(self.canvas)
        item.rotated(ox, oy, rotation).renderTo(tempRenderer, None)
        tempRenderer.paint(qp, self.canvas)
        qp.setTransform(oldTransform)
    def paint(self, e, qp):
        CanvasEditorPickPoint.paint(self, e, qp)
        if self.centre_point is not None:
            first_arm = self.first_arm if self.first_arm is not None else self.mouse_point
            pen = qp.pen()
            qp.setPen(QPen(QColor(255, 0, 0), 0))
            qp.drawLine(self.canvas.project(QPointF(self.centre_point.x, self.centre_point.y)), self.canvas.project(QPointF(first_arm.x, first_arm.y)))
            if self.first_arm is not None:
                second_arm = self.mouse_point
                qp.drawLine(self.canvas.project(QPointF(self.centre_point.x, self.centre_point.y)), self.canvas.project(QPointF(second_arm.x, second_arm.y)))
            qp.setPen(pen)
            if self.first_arm is not None:
                ox, oy, rotation = self.getTransform(self.mouse_point)
                for i in range(self.arrayCount.value()):
                    for item in self.objects:
                        self.drawPreview(qp, item, ox, oy, rotation * (i + 1))
    def apply(self):
        if self.stage == 2:
            second_arm = self.mouse_point
            ox, oy, rotation = self.getTransform(second_arm)
            CanvasRotateEditor.count = self.arrayCount.value()
            items = []
            count = self.count
            start = 0
            if self.deleteOrig:
                # Rotate existing
                self.document.opRotateDrawingItems(self.objects, ox, oy, rotation)
                if count <= 1:
                    CanvasEditorPickPoint.apply(self)
                    return
                start += 1
            for i in range(start, self.count):
                items += [model.DrawingItemTreeItem.load(self.document, item.store()).rotated(ox, oy, rotation * (i + 1)).reset_untransformed().reset_id() for item in self.objects]
            self.document.opAddDrawingItems(items)
            CanvasEditorPickPoint.apply(self)

class CanvasTabsEditor(CanvasEditor):
    def __init__(self, item):
        CanvasEditor.__init__(self, item)
    def setTitle(self):
        self.parent.setWindowTitle("Place holding tabs")
    def updateLabel(self):
        self.descriptionLabel.setText("Click on outlines to add/remove preferred locations for holding tabs.")
    def paint(self, e, qp):
        pen = qp.pen()
        qp.setPen(QPen(QColor(255, 0, 0), 0))
        for tab in self.item.user_tabs:
            pos = self.canvas.project(QPointF(tab.x, tab.y))
            qp.drawEllipse(pos, 10, 10)
        qp.setPen(pen)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.canvas.unproject(e.localPos())
            pt = geom.PathPoint(pos.x(), pos.y())
            ptToDelete = None
            for pp in self.item.user_tabs:
                if geom.dist(pt, pp) < 5:
                    ptToDelete = pp
            if ptToDelete is not None:
                self.item.document.opChangeProperty(self.item.prop_user_tabs, [(self.item, self.item.user_tabs - set([ptToDelete]))])
            else:
                self.item.document.opChangeProperty(self.item.prop_user_tabs, [(self.item, self.item.user_tabs | set([pt]))])
            self.canvas.renderDrawing()
            self.canvas.repaint()
            return True
    def penForPath(self, item, path):
        if self.item.shape_id == item.shape_id:
            return item.defaultDrawingPen
        return item.defaultGrayPen

class CanvasIslandsEditor(CanvasEditor):
    def __init__(self, item):
        CanvasEditor.__init__(self, item)
        self.can_cancel = True
        self.cancel_index = self.item.document.undoStack.index()
    def setTitle(self):
        self.parent.setWindowTitle("Select areas to exclude")
    def updateLabel(self):
        self.descriptionLabel.setText("Click on outlines to toggle exclusion of areas from the pocket.")
    def paint(self, e, qp):
        op = self.item
        translation = op.document.drawing.translation()
        shape = op.orig_shape.translated(*translation).toShape()
        p = shape.boundary + shape.boundary[0:1]
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        view.addPolylineToPath(path, p)
        for p in shape.islands:
            path2 = QPainterPath()
            view.addPolylineToPath(path2, p + p[0:1])
            path = path.subtracted(path2)
        for island in op.islands:
            shape = op.document.drawing.itemById(island).translated(*translation).toShape()
            items = []
            if isinstance(shape, list):
                items = shape
            elif shape.closed:
                items = [shape]
            for shape in items:
                path2 = QPainterPath()
                view.addPolylineToPath(path2, shape.boundary + shape.boundary[0:1])
                path = path.subtracted(path2)
                path2 = QPainterPath()
                for i in shape.islands:
                    view.addPolylineToPath(path2, i + i[0:1])
                path = path.united(path2)
        transform = self.canvas.drawingTransform()
        brush = QBrush(QColor(0, 128, 192), Qt.DiagCrossPattern)
        brush.setTransform(transform.inverted()[0])
        qp.setTransform(transform)
        qp.fillPath(path, brush)
        qp.setTransform(QTransform())
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.canvas.unproject(e.localPos())
            objs = self.item.document.drawing.objectsNear(pos, 24 / self.canvas.scalingFactor())
            objs = [o for o in objs if o.shape_id != self.item.shape_id]
            if not objs:
                self.canvas.start_point = e.localPos()
                return False
            self.item.document.opChangeProperty(self.item.prop_islands, [(self.item, self.item.islands ^ set([o.shape_id for o in objs]))])
            self.canvas.renderDrawing()
            self.canvas.repaint()
            return True
    def mouseMoveEvent(self, e):
        if self.canvas.dragging:
            self.canvas.updateCursor()
        else:
            pos = self.canvas.unproject(e.localPos())
            objs = self.item.document.drawing.objectsNear(pos, 24 / self.canvas.scalingFactor())
            objs = [o for o in objs if o.shape_id != self.item.shape_id]
            if objs:
                self.canvas.setCursor(Qt.PointingHandCursor)
            else:
                self.canvas.updateCursor()
            # Let normal rubberband logic work
    def mouseReleaseEvent(self, e):
        if self.canvas.dragging:
            objs = self.canvas.rubberbandDrawingObjects()
            self.item.document.opChangeProperty(self.item.prop_islands, [(self.item, self.item.islands ^ set([o.shape_id for o in objs if o.shape_id != self.item.shape_id]))])
    def penForPath(self, item, path):
        if self.item.shape_id == item.shape_id:
            return item.defaultDrawingPen
        if item.shape_id in self.item.islands:
            return item.selectedItemPen2Func
        if geom.bounds_overlap(item.bounds, self.item.orig_shape.bounds):
            return item.defaultDrawingPen
        return item.defaultGrayPen

class CanvasEntryPointEditor(CanvasEditor):
    def __init__(self, item):
        CanvasEditor.__init__(self, item)
        self.mouse_point = None
    def setTitle(self):
        self.parent.setWindowTitle("Select entry point")
    def updateLabel(self):
        orientation = self.item.contourOrientation()
        if orientation:
            modeText = "Click on desired entry point for the contour running in counter-clockwise direction."
        else:
            modeText = "Click on desired entry point for the contour running in clockwise direction."
        self.descriptionLabel.setText(modeText)
    def paint(self, e, qp):
        op = self.item
        ee = op.entry_exit
        translation = op.document.drawing.translation()
        #shape = op.orig_shape.translated(*translation).toShape()
        qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for i in ee:
            qp.setPen(QPen(QColor(0, 255, 0, 128), 0))
            qp.setBrush(QBrush(QColor(0, 255, 0, 128)))
            pos = self.canvas.project(QPointF(i[0].x, i[0].y))
            if op.cutter:
                r = op.cutter.diameter * self.canvas.scalingFactor() / 2
                qp.drawEllipse(pos, r, r)
                qp.setPen(QPen(QColor(255, 0, 0, 128), 0))
                qp.setBrush(QBrush())
                pos = self.canvas.project(QPointF(i[1].x, i[1].y))
                qp.drawEllipse(pos, r, r)
        mouse_point = self.mouse_point
        if mouse_point is not None:
            erase = None
            mp = geom.PathPoint(mouse_point.x(), mouse_point.y())
            for pp in self.item.entry_exit:
                if geom.dist(mp, pp[0]) < 5:
                    erase = pp[0]
            if erase:
                qp.setPen(QPen(QColor(255, 128, 128, 192), 0))
            else:
                qp.setPen(QPen(QColor(128, 128, 128, 128), 0))
                self.setBrushForAdd(qp)
            pos = self.canvas.project(mouse_point if erase is None else QPointF(erase.x, erase.y))
            if op.cutter:
                r = op.cutter.diameter * self.canvas.scalingFactor() / 2
                r2 = r * (2 ** 0.5)
                qp.drawEllipse(pos, r, r)
                if erase:
                    qp.drawLine(pos + QPointF(-r2, -r2), pos + QPointF(r2, r2))
                    qp.drawLine(pos + QPointF(r2, -r2), pos + QPointF(-r2, r2))
            qp.setBrush(QBrush())
    def setBrushForAdd(self, qp):
        qp.setBrush(QBrush(QColor(128, 128, 128, 128)))
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.canvas.unproject(e.localPos())
            pt = geom.PathPoint(pos.x(), pos.y())
            erase = None
            for pp in self.item.entry_exit:
                if geom.dist(pt, pp[0]) < 5:
                    erase = True
            if erase:
                self.item.document.opChangeProperty(self.item.prop_entry_exit, [(self.item, [])])
            else:
                self.item.document.opChangeProperty(self.item.prop_entry_exit, [(self.item, [(pt, pt)])])
                self.canvas.editorChangeRequest.emit(CanvasExitPointEditor(self.item))
            self.canvas.renderDrawing()
            self.canvas.repaint()
            return True
    def mouseMoveEvent(self, e):
        self.mouse_point = self.canvas.unproject(e.localPos())
        self.canvas.repaint()

class CanvasExitPointEditor(CanvasEntryPointEditor):
    def setTitle(self):
        self.parent.setWindowTitle("Select exit point")
    def updateLabel(self):
        orientation = self.item.contourOrientation()
        if orientation:
            modeText = "Click on desired end of the cut, counter-clockwise from starting point."
        else:
            modeText = "Click on desired end of the cut, clockwise from starting point."
        self.descriptionLabel.setText(modeText)
    def setBrushForAdd(self, qp):
        qp.setBrush(QBrush())
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.canvas.unproject(e.localPos())
            sp = self.item.entry_exit[0][0]
            pt = geom.PathPoint(pos.x(), pos.y())
            self.item.document.opChangeProperty(self.item.prop_entry_exit, [(self.item, [(sp, pt)])])
            self.canvas.exitEditMode(False)
            return True

FEEDBACK_ADD = 1
FEEDBACK_REMOVE = 2

class CanvasDrawingItemEditor(CanvasEditorWithSnap):
    def __init__(self, item, cancel_index=None):
        CanvasEditorWithSnap.__init__(self, item)
        self.document = item.document if item else None
        self.last_pos = None
        self.visual_feedback = None
        self.can_cancel = True
        self.cancel_index = cancel_index
    def drawingOffset(self):
        return self.document.drawing.x_offset, self.document.drawing.y_offset
    def ptFromPos(self, eLocalPos, snap=True, inverse=False):
        pos = self.canvas.unproject(eLocalPos)
        ox, oy = self.drawingOffset()
        if inverse:
            ox, oy = -ox, -oy
        if snap:
            return self.snapCoords(geom.PathPoint(pos.x() + ox, pos.y() + oy))
        else:
            return geom.PathPoint(pos.x() + ox, pos.y() + oy)
    def paintPoint(self, qp, loc, as_arc):
        ox, oy = self.drawingOffset()
        self.paintCoords(qp, loc, ox, oy)
        pt = self.canvas.project(QPointF(loc.x - ox, loc.y - oy))
        hbox = QPointF(3, 3)
        color = qp.pen().color()
        if as_arc:
            brush = qp.brush()
            qp.setBrush(color)
            qp.drawEllipse(QRectF(pt - hbox, pt + hbox))
            qp.setBrush(brush)
        else:
            qp.fillRect(QRectF(pt - hbox, pt + hbox), color)
    def setTitle(self):
        self.parent.setWindowTitle("Create a text object")
    def updateLabel(self):
        modeText = f"""\
Click on a drawing to create a text object.
{self.snapInfo()}"""
        self.descriptionLabel.setText(modeText)
    def penForPath(self, item, path):
        if self.item is not None and isinstance(self.item, model.DrawingItemTreeItem) and self.item.shape_id == item.shape_id:
            return None
        return item.defaultGrayPen
    def onShapesDeleted(self, shapes):
        if isinstance(self.item, model.DrawingItemTreeItem) and self.item in shapes:
            self.canvas.exitEditMode(False)

class CanvasNewItemEditor(CanvasDrawingItemEditor):
    def __init__(self, document):
        CanvasDrawingItemEditor.__init__(self, self.createItem(document))
        self.document = document
    def initUI(self, parent, canvas):
        CanvasDrawingItemEditor.initUI(self, parent, canvas)
        eLocalPos = self.canvas.mapFromGlobal(QCursor.pos())
        self.initState(self.ptFromPos(eLocalPos))
        self.canvas.repaint()
    def mousePressEvent(self, e):
        return self.mousePressEventPos(e, self.ptFromPos(e.localPos()))
    def mouseMoveEvent(self, e):
        return self.mouseMoveEventPos(e, self.ptFromPos(e.localPos()))
    def paint(self, e, qp):
        self.drawCursorPoint(qp)
        ox, oy = self.drawingOffset()
        self.drawPreview(qp, self.item, -ox, -oy)

class CanvasNewTextEditor(CanvasNewItemEditor):
    last_style = model.DrawingTextStyle(height=10, width=1, halign=model.DrawingTextStyleHAlign.LEFT, valign=model.DrawingTextStyleVAlign.BASELINE, angle=0, font_name="Bitstream Vera", spacing=0)
    def createItem(self, document):
        return model.DrawingTextTreeItem(document, geom.PathPoint(0, 0), 0, self.last_style.clone(), "Text")
    def createExtraControls(self):
        self.controlsLayout = QFormLayout()
        self.valueEdit = QLineEdit()
        self.valueEdit.setText(self.item.text)
        self.valueEdit.textChanged.connect(self.onTextChanged)
        self.controlsLayout.addRow("&Text", self.valueEdit)
        self.fontCombo = QFontComboBox()
        self.fontCombo.currentFontChanged.connect(lambda value: self.item.setPropertyValue('font', value.family()))
        self.controlsLayout.addRow("&Font", self.fontCombo)
        self.sizeSpin = guiutils.floatSpin(1, 100, 1, self.item.getPropertyValue('height'), "Size of the text object - affects height directly and width indirectly")
        self.sizeSpin.valueChanged.connect(lambda value: self.item.setPropertyValue('height', value))
        self.controlsLayout.addRow("&Size", self.sizeSpin)
        self.widthSpin = guiutils.floatSpin(10, 1000, 1, self.item.getPropertyValue('width'), "Width of the text object - relative to size")
        self.widthSpin.valueChanged.connect(lambda value: self.item.setPropertyValue('width', value))
        self.controlsLayout.addRow("&Width %", self.widthSpin)
        self.angleSpin = guiutils.floatSpin(0, 360, 1, self.item.getPropertyValue('angle'), "Text angle in degrees")
        self.angleSpin.valueChanged.connect(lambda value: self.item.setPropertyValue('angle', value))
        self.controlsLayout.addRow("&Angle", self.angleSpin)
        self.spacingSpin = guiutils.floatSpin(0, 1000, 1, self.item.getPropertyValue('spacing'), "Letter spacing in degrees")
        self.spacingSpin.valueChanged.connect(lambda value: self.item.setPropertyValue('spacing', value))
        self.controlsLayout.addRow("&Letter spacing", self.spacingSpin)
        self.alignLayout = QGridLayout()
        HAlign = model.DrawingTextStyleHAlign
        VAlign = model.DrawingTextStyleVAlign
        alignments = [
            (HAlign.LEFT,   VAlign.TOP, "Top Left"),
            (HAlign.CENTRE, VAlign.TOP, "Top Centre"),
            (HAlign.RIGHT,  VAlign.TOP, "Top Right"),
            (HAlign.LEFT,   VAlign.MIDDLE, "Mid Left"),
            (HAlign.CENTRE, VAlign.MIDDLE, "Centre"),
            (HAlign.RIGHT,  VAlign.MIDDLE, "Mid Right"),
            (HAlign.LEFT,   VAlign.BASELINE, "Base Left"),
            (HAlign.CENTRE, VAlign.BASELINE, "Base Centre"),
            (HAlign.RIGHT,  VAlign.BASELINE, "Base Right"),
            (HAlign.LEFT,   VAlign.BOTTOM, "Btm Left"),
            (HAlign.CENTRE, VAlign.BOTTOM, "Btm Centre"),
            (HAlign.RIGHT,  VAlign.BOTTOM, "Btm Right"),
            (HAlign.ALIGNED,   VAlign.TOP, "Aligned"),
            (HAlign.MIDDLE, VAlign.TOP, "Middle"),
            (HAlign.FIT,  VAlign.TOP, "Fit"),
        ]
        def alignHandler(halign, valign):
            return lambda: self.onAlignChanged(halign, valign)
        for i, value in enumerate(alignments):
            halign, valign, name = value
            button = QPushButton(name)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setChecked(self.item.style.halign == halign and self.item.style.valign == valign)
            button.clicked.connect(alignHandler(halign, valign))
            self.alignLayout.addWidget(button, int(i // 3), int(i % 3))
        self.alignGroup = QGroupBox("Al&ignment")
        self.alignGroup.setLayout(self.alignLayout)
        self.overallLayout = QHBoxLayout()
        self.overallLayout.addLayout(self.controlsLayout)
        self.overallLayout.addWidget(self.alignGroup)
        self.layout.addRow(self.overallLayout)
    def onTextChanged(self, newText):
        self.item.setPropertyValue('text', newText)
    def onSizeChanged(self, newValue):
        self.item.setPropertyValue('height', newValue)
    def onAlignChanged(self, halign, valign):
        self.item.setPropertyValue('halign', halign)
        self.item.setPropertyValue('valign', valign)
    def drawCursorPoint(self, qp):
        qp.setPen(QColor(0, 0, 0, 128))
        self.paintPoint(qp, self.item.origin, as_arc=False)
    def initState(self, pos):
        self.item.origin = pos
    def mouseMoveEventPos(self, e, newPos):
        if self.item.origin != newPos:
            self.item.origin = newPos
            self.canvas.repaint()
        return False
    def mousePressEventPos(self, e, newPos):
        if e.button() == Qt.LeftButton:
            self.last_style = self.item.style.clone()
            self.item.origin = newPos
            self.document.addShapesFromEditor([self.item])
            self.apply()
            return True
        return True

class CanvasNewRectangleEditor(CanvasNewItemEditor):
    RADIUS = 0
    def createItem(self, document):
        return None
    def initState(self, pos):
        self.first_point = pos
        self.second_point = None
    def createExtraControls(self):
        self.controlsLayout = QHBoxLayout()
        self.radiusEditor = QLineEdit()
        self.radiusEditor.setValidator(QDoubleValidator(0, 1000, 20))
        self.radiusEditor.setText(self.radiusEditor.validator().locale().toString(self.RADIUS))
        self.controlsLayout.addWidget(QLabel("Radius"))
        self.controlsLayout.addWidget(self.radiusEditor)
        self.layout.addRow(self.controlsLayout)
    def setTitle(self):
        self.parent.setWindowTitle("Create a rectangle polyline object")
    def drawCursorPoint(self, qp):
        qp.setPen(QColor(0, 0, 0, 128))
        self.paintPoint(qp, self.first_point if self.second_point is None else self.second_point, as_arc=False)
    def polylinePath(self):
        x1, y1 = self.first_point.x, self.first_point.y
        x2, y2 = self.second_point.x, self.second_point.y
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        radius, ok = self.radiusEditor.validator().locale().toDouble(self.radiusEditor.text())
        if radius == 0 or not ok or abs(x2 - x1) <= 2 * radius or abs(y2 - y1) <= 2 * radius:
            return [geom.PathPoint(x1, y1), geom.PathPoint(x2, y1), geom.PathPoint(x2, y2), geom.PathPoint(x1, y2)]
        else:
            def fillet(x, y, no):
                x += -radius if no < 2 else +radius
                y += -radius if no >= 1 and no < 3 else +radius
                return geom.PathArc.xyra(x, y, radius, (no + 3) * math.pi / 2, math.pi / 2)
            return [geom.PathPoint(x1 + radius, y1), geom.PathPoint(x2 - radius, y1), fillet(x2, y1, 0), geom.PathPoint(x2, y1 + radius), geom.PathPoint(x2, y2 - radius), fillet(x2, y2, 1), geom.PathPoint(x2 - radius, y2), geom.PathPoint(x1 + radius, y2), fillet(x1, y2, 2), geom.PathPoint(x1, y2 - radius), geom.PathPoint(x1, y1 + radius), fillet(x1, y1, 3)]
    def drawPreview(self, qp, item, ox, oy):
        if self.second_point is None:
            return
        path = geom.Path(self.polylinePath(), True).interpolated()
        for start, end in geom.PathSegmentIterator(path):
            qs = self.canvas.project(QPointF(start.x + ox, start.y + oy))
            qe = self.canvas.project(QPointF(end.x + ox, end.y + oy))
            qp.drawLine(qs, qe)
    def apply(self):
        radius, ok = self.radiusEditor.validator().locale().toDouble(self.radiusEditor.text())
        if ok:
            CanvasNewRectangleEditor.RADIUS = radius
        CanvasNewItemEditor.apply(self)
    def mouseMoveEventPos(self, e, newPos):
        if self.second_point is None:
            changed = self.first_point != newPos
            self.first_point = newPos
        else:
            changed = self.second_point != newPos
            self.second_point = newPos
        if changed:
            self.canvas.repaint()
        return False
    def mousePressEventPos(self, e, newPos):
        if e.button() == Qt.LeftButton:
            if self.second_point is None:
                # First click
                self.first_point = newPos
                self.second_point = newPos
            else:
                # Second click
                self.item = model.DrawingPolylineTreeItem(self.document, self.polylinePath(), True)
                self.document.addShapesFromEditor([self.item])
                self.apply()
            return True
        return True

class CanvasNewCircleEditor(CanvasNewItemEditor):
    drawMode = 0
    lastRadius = ""
    def createItem(self, document):
        return None
    def initState(self, pos):
        self.first_point = pos
        self.second_point = None
    def setTitle(self):
        self.parent.setWindowTitle("Create a circle object")
    def createExtraControls(self):
        self.pointsButton = QPushButton("2 Points")
        self.radiusButton = QPushButton("Radius")
        self.diameterButton = QPushButton("Diameter")
        self.modeButtons = [ self.pointsButton, self.radiusButton, self.diameterButton ]
        self.modeLayout = QHBoxLayout()
        self.modeLayout.addWidget(QLabel("Mode:"))
        def buttonHandler(index):
            return lambda: self.onModeButtonClicked(index)
        for i, button in enumerate(self.modeButtons):
            self.modeLayout.addWidget(button)
            button.clicked.connect(buttonHandler(i))
        self.valueEdit = QLineEdit()
        self.valueEdit.setText(CanvasNewCircleEditor.lastRadius)
        self.valueEdit.setValidator(QDoubleValidator(0, 1000, 3))
        self.valueEdit.textChanged.connect(self.updateModeButtons)
        self.modeLayout.addWidget(self.valueEdit)
        self.modeLayout.addStretch(1)
        self.layout.addRow(self.modeLayout)
        self.updateModeButtons()
    def updateModeButtons(self):
        mode = CanvasNewCircleEditor.drawMode
        for i, button in enumerate(self.modeButtons):
            button.setDown(i == mode)
        self.valueEdit.setEnabled(mode != 0)
        if mode == 0:
            self.radius = None
        else:
            self.radius = None
            try:
                self.radius = float(self.valueEdit.text())
                if mode == 2:
                    self.radius /= 2
                CanvasNewCircleEditor.lastRadius = self.valueEdit.text()
            except ValueError as e:
                pass
    def onModeButtonClicked(self, mode):
        CanvasNewCircleEditor.drawMode = mode
        self.updateModeButtons()
    def drawCursorPoint(self, qp):
        qp.setPen(QColor(0, 0, 0, 128))
        self.paintPoint(qp, self.first_point if self.second_point is None else self.second_point, as_arc=False)
    def polylinePath(self):
        endp = geom.PathPoint(xc + r, yc)
        return [endp, geom.PathArc.xyra(xc, yc, r, 0, 2 * math.pi, steps = int(max(20, 10 * r)))]
    def drawPreview(self, qp, item, ox, oy):
        if self.second_point is None and self.radius is None:
            return
        xc, yc = self.first_point.x + ox, self.first_point.y + oy
        if self.radius is None:
            r = self.first_point.dist(self.second_point)
        else:
            r = self.radius
        r *= self.canvas.scalingFactor()
        qp.drawEllipse(self.canvas.project(QPointF(xc, yc)), r, r)
    def mouseMoveEventPos(self, e, newPos):
        if self.second_point is None:
            changed = self.first_point != newPos
            self.first_point = newPos
        else:
            changed = self.second_point != newPos
            self.second_point = newPos
        if changed:
            self.canvas.repaint()
        return False
    def mousePressEventPos(self, e, newPos):
        if e.button() == Qt.LeftButton:
            if self.second_point is None and self.radius is None:
                # First click
                self.first_point = newPos
                self.second_point = newPos
            else:
                # Second click (or first for polyline)
                xc, yc = self.first_point.x, self.first_point.y
                if self.radius is not None:
                    r = self.radius
                else:
                    r = self.first_point.dist(self.second_point)
                self.item = model.DrawingCircleTreeItem(self.document, self.first_point, r)
                self.document.addShapesFromEditor([self.item])
                self.apply()
            return True
        return True

class CanvasPolylineEditor(CanvasDrawingItemEditor):
    def apply(self):
        if not self.item.closed and len(self.item.points) < 2:
            QMessageBox.critical(self.parent, None, "An open polyline must have at least 2 points")
            return
        if self.item.closed and len(self.item.points) < 3:
            QMessageBox.critical(self.parent, None, "A closed polyline must have at least 3 points")
            return
        CanvasEditor.apply(self)
    def cancel(self):
        CanvasEditor.cancel(self)
    def connectSignals(self):
        self.canvas.zoomChanged.connect(self.updateLabel)
        self.item.document.shapesUpdated.connect(self.resetVisualFeedback)
    def resetVisualFeedback(self):
        if self.visual_feedback:
            self.visual_feedback = None
            self.canvas.repaint()
    def setTitle(self):
        self.parent.setWindowTitle("Modify a polyline")
    def createExtraControls(self):
        self.arcMode = 2
        self.arcMoveButton = QPushButton("Move")
        self.arcSpanButton = QPushButton("Span")
        self.arcAnchorButton = QPushButton("Anchor")
        self.arcModeButtons = [ self.arcMoveButton, self.arcSpanButton, self.arcAnchorButton ]
        self.arcModeLayout = QHBoxLayout()
        self.arcModeLayout.addWidget(QLabel("Arc edit mode:"))
        self.updateArcButtons()
        def buttonHandler(index):
            return lambda: self.onArcButtonClicked(index)
        for i, button in enumerate(self.arcModeButtons):
            self.arcModeLayout.addWidget(button)
            button.clicked.connect(buttonHandler(i))
        self.arcModeLayout.addWidget(self.arcAnchorButton)
        self.arcModeLayout.addStretch(1)
        self.layout.addRow(self.arcModeLayout)
    def updateArcButtons(self):
        for i, button in enumerate(self.arcModeButtons):
            button.setDown(i == self.arcMode)
    def onArcButtonClicked(self, which):
        self.arcMode = which
        self.updateArcButtons()
    def updateLabel(self):
        modeText = f"""\
Drag nodes to move them.
Moving a node into a neighbour deletes it.
Moving a node into a non-neighbour node breaks up a closed polyline.
Moving the first node into the last one closes an open polyline.
Dragging a line inserts a node at that point.
Clicking near the start/end of an open polyline adds a node there.
Double-clicking a node removes it.
{self.snapInfo()}"""
        #for i in self.item.points:
        #    modeText += str(i) + "\n"
        self.descriptionLabel.setText(modeText)
    def paint(self, e, qp):
        ox, oy = self.drawingOffset()
        is_add = isinstance(self, CanvasNewPolylineEditor)
        polyline = self.item
        normPen = QColor(0, 0, 0)
        qp.setPen(normPen)
        for i, p in enumerate(polyline.points):
            if p.is_point() and (i + 1 == len(polyline.points) or polyline.points[i + 1].is_point()):
                self.paintPoint(qp, p, as_arc=False)
            elif p.is_arc():
                self.paintPoint(qp, p.p2, as_arc=True)
            else:
                self.paintPoint(qp, p, as_arc=True)
        qp.setPen(QColor(0, 0, 0, 64))
        for p in polyline.points:
            if p.is_arc():
                self.paintPoint(qp, p.c.centre(), as_arc=True)
        if is_add and self.last_pos is not None:
            qp.setPen(QColor(0, 0, 0, 128))
            self.paintPoint(qp, self.last_pos, as_arc=False)
        if self.visual_feedback:
            qp.setPen(QColor(0, 0, 0, 128))
            if self.visual_feedback[0] == FEEDBACK_ADD:
                other = self.visual_feedback[1]
                if other.is_point():
                    qp.drawLine(self.canvas.project(QPointF(other.x - ox, other.y - oy)), self.canvas.project(QPointF(self.last_pos.x - ox, self.last_pos.y - oy)))
            elif self.visual_feedback[0] == FEEDBACK_REMOVE:
                other1 = self.visual_feedback[1].seg_end()
                other2 = self.visual_feedback[2].seg_end()
                if other1.is_point() and other2.is_point():
                    qp.drawLine(self.canvas.project(QPointF(other1.x - ox, other1.y - oy)), self.canvas.project(QPointF(other2.x - ox, other2.y - oy)))
    def isArcEndpoint(self, index):
        if self.item.points[index].is_arc():
            return True, index, 1
        elif index + 1 < len(self.item.points) and self.item.points[index + 1].is_arc():
            return True, index + 1, 0
        return False, index, None
    def excludeSnapPoints(self):
        if self.canvas.dragging and len(self.drag_start_data) == 3:
            index = self.drag_start_data[1]
            return set([ self.item.points[index] ])
    def startDragArc(self, pos, index, where):
        self.drag_start_data = (pos, index, where, self.item.points[index].as_tuple())
    def clickOnPolyline(self, e, is_double):
        self.visual_feedback = None
        npts = len(self.item.points)
        is_add = isinstance(self, CanvasNewPolylineEditor)
        polyline = self.item
        pt = self.ptFromPos(e.localPos(), snap=False)
        nearest = self.nearestPolylineItem(pt)
        if nearest is None and is_double:
            nearest = self.nearestPolylineItem(self.snapCoords(pt))
        if nearest is not None:
            if is_double:
                if npts > 2:
                    if is_add:
                        if nearest == npts - 1:
                            self.canvas.exitEditMode(False)
                            return
                        #if nearest == 0:
                        #    polyline.closed = True
                        #    self.canvas.renderDrawing()
                        #    self.canvas.exitEditMode()
                        #    return
                    if not polyline.closed or len(polyline.points) > 3:
                        polyline.document.opModifyPolyline(polyline, polyline.points[:nearest] + polyline.points[nearest + 1:], polyline.closed)
                    self.canvas.renderDrawing()
                    self.canvas.repaint()
                return
            else:
                is_arc_ep, index, t = self.isArcEndpoint(nearest)
                if is_arc_ep:
                    self.canvas.start_point = e.localPos()
                    self.startDragArc(e.localPos(), index, t)
                    return
                else:
                    self.canvas.start_point = e.localPos()
                    self.drag_start_data = (e.localPos(), nearest, polyline.points[nearest])
                    return
        if not is_double:
            nearest = self.nearestPolylineCentre(pt)
            if nearest is not None:
                self.canvas.start_point = e.localPos()
                self.startDragArc(e.localPos(), nearest, 'centre')
                return
            if not polyline.closed:
                nearest = self.nearestPolylineItem(pt, margin=15)
                if nearest == 0 or nearest == npts - 1:
                    pt = self.snapCoords(pt)
                    if nearest == 0:
                        polyline.document.opModifyPolyline(polyline, [pt] + polyline.points, False)
                        self.drag_start_data = (e.localPos(), 0, pt)
                    else:
                        polyline.document.opModifyPolyline(polyline, polyline.points + [pt], False)
                        self.drag_start_data = (e.localPos(), npts, pt)
                    self.canvas.start_point = e.localPos()
                    self.canvas.renderDrawing()
                    self.canvas.repaint()
                    return
            item = self.nearestPolylineLine(pt)
            if item is not None:
                pt = self.snapCoords(pt)
                polyline.document.opModifyPolyline(polyline, polyline.points[:item] + [pt] + polyline.points[item:], polyline.closed)
                self.canvas.start_point = e.localPos()
                self.drag_start_data = (e.localPos(), item, pt)
                self.canvas.renderDrawing()
                self.canvas.repaint()
            elif is_add:
                pt = self.snapCoords(pt)
                polyline.document.opModifyPolyline(polyline, polyline.points + [pt], False)
                self.canvas.start_point = e.localPos()
                self.drag_start_data = (e.localPos(), len(polyline.points) - 1, pt)
    def nearestPolylineItem(self, pt, exclude=None, margin=5):
        polyline = self.item
        nearest = None
        nearest_dist = None
        for i, pp in enumerate(polyline.points):
            if exclude is not None and i == exclude:
                continue
            pdist = pt.dist(pp.seg_end())
            if nearest is None or pdist < nearest_dist:
                nearest = i
                nearest_dist = pdist
        if nearest_dist is not None and nearest_dist < margin / self.canvas.scalingFactor():
            return nearest
        return None
    def nearestPolylineCentre(self, pt, margin=5):
        polyline = self.item
        nearest = None
        nearest_dist = None
        for i, pp in enumerate(polyline.points):
            if pp.is_arc():
                pdist = pt.dist(pp.c.centre())
                if nearest is None or pdist < nearest_dist:
                    nearest = i
                    nearest_dist = pdist
        if nearest_dist is not None and nearest_dist < margin / self.canvas.scalingFactor():
            return nearest
        return None
    def nearestPolylineLine(self, pt):
        polyline = self.item
        if not polyline.points:
            return None
        nearest = 0
        nearest_dist = None
        for i, line in enumerate(geom.PathSegmentIterator(geom.Path(polyline.points, polyline.closed))):
            if line[1].is_point():
                pdist = geom.dist_line_to_point(line[0], line[1], pt)
                if nearest_dist is None or pdist < nearest_dist:
                    nearest = 1 + i
                    nearest_dist = pdist
        if nearest_dist is not None and nearest_dist < 5 / self.canvas.scalingFactor():
            return nearest
        return None
    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clickOnPolyline(e, True)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clickOnPolyline(e, False)
            return True
    def adjacent(self, i1, i2):
        if abs(i1 - i2) == 1:
            return True
        if min(i1, i2) == 0 and max(i1, i2) == len(self.item.points) - 1:
            return True
        return False
    def editArcEndpoint(self, pt):
        sp, dragged, start_pos, arc_as_tuple = self.drag_start_data
        pt = self.snapCoords(pt)
        mode = self.arcMode
        old = geom.PathArc.from_tuple(arc_as_tuple)
        c = old.c
        cx, cy, r = c.cx, c.cy, c.r
        sstart = old.sstart
        sspan = old.sspan
        if start_pos == 'centre':
            #old = geom.PathArc.from_tuple(arc_as_tuple)
            #cur = self.item.points[dragged]
            #oldr = r
            #r = min(old.p1.dist(pt), old.p2.dist(pt))
            #if r < 0.001:
            #    return
            #angle = sstart + sspan / 2
            #cx -= math.sqrt(2) * (r - oldr) * math.cos(angle)
            #cy -= math.sqrt(2) * (r - oldr) * math.sin(angle)
            r = min(old.p1.dist(pt), old.p2.dist(pt))
            cx = old.p1.x - r * math.cos(sstart)
            cy = old.p1.y - r * math.sin(sstart)
        elif mode == 1:
            old_angle = old.angle_at_fraction(start_pos)
            new_angle = c.angle(pt)
            adiff = (new_angle - old_angle) % (2 * math.pi)
            if adiff >= math.pi:
                adiff -= 2 * math.pi
            if start_pos == 0:
                sstart += adiff
                sspan -= adiff
            else:
                sspan += adiff
            if abs(sspan) >= 2 * math.pi:
                return
            if abs(sspan) * c.r < 0.001:
                return
        elif mode == 2:
            if start_pos == 1:
                p1 = old.p1
                p2 = pt
                angle = sstart
            elif start_pos == 0:
                p1 = old.p2
                p2 = pt
                angle = sstart + sspan
            else:
                return
            p1ext = geom.PathPoint(p1.x - 10000 * math.cos(angle), p1.y - 10000 * math.sin(angle))
            extension = QLineF(p1.x, p1.y, p1ext.x, p1ext.y)
            conn = QLineF(p1.x, p1.y, p2.x, p2.y)
            bisector = conn.normalVector().translated(conn.dx() / 2, conn.dy() / 2)            
            mode, point = extension.intersects(bisector)
            if mode == QLineF.NoIntersection:
                return
            cx = point.x()
            cy = point.y()
            r = QLineF(conn.p1(), point).length()
            if r > 100 * conn.length():
                return
            cur = self.item.points[dragged]
            old_dir = cur.sspan > 0
            old_mag = abs(cur.sspan) > math.pi
            if start_pos == 1:
                sstart = math.atan2(p1.y - cy, p1.x - cx)
                sspan = math.atan2(p2.y - cy, p2.x - cx) - sstart
            else:
                sstart = math.atan2(p2.y - cy, p2.x - cx)
                sspan = math.atan2(p1.y - cy, p1.x - cx) - sstart
            new_dir = sspan > 0
            new_mag = abs(sspan) > math.pi
            
            if sspan > 0:
                sspan2 = sspan - 2 * math.pi
            else:
                sspan2 = sspan + 2 * math.pi

            flip = False
            if abs(sspan2 - cur.sspan) < abs(sspan - cur.sspan):
                flip = True
            if flip:
                sspan = sspan2
        elif mode == 3:
            bulge = 0.5
            if start_pos == 0:
                new_arc = geom.arc_from_cad(pt, old.p2, bulge)[1]
            else:
                new_arc = geom.arc_from_cad(old.p1, pt, bulge)[1]
            self.item.document.opModifyPolylinePoint(self.item, dragged, new_arc, True)
            return
        elif mode == 0:
            if start_pos == 0:
                cx = pt.x - r * math.cos(sstart)
                cy = pt.y - r * math.sin(sstart)
            if start_pos == 1:
                cx = pt.x - r * math.cos(sstart + sspan)
                cy = pt.y - r * math.sin(sstart + sspan)
        new_arc = geom.PathArc.xyra(cx, cy, r, sstart, sspan)
        self.item.document.opModifyPolylinePoint(self.item, dragged, new_arc, True)
        
    def mouseMoveEvent(self, e):
        repaint = False
        if self.visual_feedback:
            self.visual_feedback = None
            repaint = True
        pos = self.canvas.unproject(e.localPos())
        prev_last_pos = self.last_pos
        self.last_pos = self.ptFromPos(e.localPos(), inverse=True)
        if prev_last_pos != self.last_pos:
            repaint = True
        npts = len(self.item.points)
        if self.canvas.dragging:
            sp, dragged, start_pos = self.drag_start_data[:3]
            is_arc = len(self.drag_start_data) > 3
            pt = self.ptFromPos(e.localPos(), snap=False)
            if is_arc:
                self.editArcEndpoint(pt)
                return True
            nearest = self.nearestPolylineItem(self.snapCoords(pt), dragged)
            if nearest is not None:
                if not self.item.closed and npts > 3 and ((nearest == 0 and dragged == npts - 1) or (nearest == npts - 1 and dragged == 0)):
                    if nearest == 0:
                        self.visual_feedback = (FEEDBACK_ADD, self.item.points[dragged - 1])
                    else:
                        self.visual_feedback = (FEEDBACK_ADD, self.item.points[1])
                    self.canvas.setCursor(guiutils.customCursor('polyline_join'))
                elif self.item.closed and not self.adjacent(nearest, dragged):
                    self.canvas.setCursor(guiutils.customCursor('scissors'))
                elif (not self.item.closed or npts > 3) and self.adjacent(nearest, dragged):
                    if dragged == (nearest + 1) % npts:
                        other = (nearest + 2) % npts
                    else:
                        other = (nearest - 2) % npts
                    self.visual_feedback = (FEEDBACK_REMOVE, self.item.points[nearest], self.item.points[other])
                    self.canvas.setCursor(guiutils.customCursor('arrow_minus'))
                else:
                    self.canvas.setCursor(Qt.ForbiddenCursor)
            else:
                self.item.document.opModifyPolylinePoint(self.item, dragged, self.snapCoords(pt), True)
                self.canvas.setCursor(Qt.SizeAllCursor)
            self.canvas.renderDrawing()
            self.canvas.repaint()
            return True
        pt = self.ptFromPos(e.localPos(), snap=False)
        nearest = self.nearestPolylineItem(pt)
        if nearest is not None:
            is_arc_ep, index, t = self.isArcEndpoint(nearest)
            is_add = isinstance(self, CanvasNewPolylineEditor)
            if is_add and (nearest == 0 or nearest == npts - 1) and npts >= 3:
                self.canvas.setCursor(guiutils.customCursor('polyline_join'))
            elif is_arc_ep:
                self.canvas.setCursor(guiutils.customCursor('polyline_arcep'))
            else:
                self.canvas.setCursor(Qt.PointingHandCursor)
        else:
            nearest = self.nearestPolylineItem(pt, margin=15) if not self.item.closed else None
            if nearest == 0 or nearest == npts - 1:
                # Extend the start or the end
                self.visual_feedback = (FEEDBACK_ADD, self.item.points[nearest])
                repaint = True
                self.canvas.setCursor(guiutils.customCursor('arrow_plus'))
            else:
                nearest = self.nearestPolylineLine(pt)
                if nearest is not None or isinstance(self, CanvasNewPolylineEditor):
                    self.canvas.setCursor(guiutils.customCursor('arrow_plus'))
                else:
                    self.canvas.setCursor(Qt.ArrowCursor)
        if repaint:
            self.canvas.repaint()
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            is_add = isinstance(self, CanvasNewPolylineEditor)
            self.canvas.start_point = None
            if self.canvas.dragging:
                is_arc = len(self.drag_start_data) > 3
                sp, dragged, start_pos = self.drag_start_data[:3]
                pt = self.ptFromPos(e.localPos())
                if is_arc:
                    self.editArcEndpoint(pt)
                else:
                    nearest = self.nearestPolylineItem(self.snapCoords(pt), dragged)
                    npts = len(self.item.points)
                    if nearest is not None:
                        if not self.item.closed and npts > 3 and ((nearest == 0 and dragged == npts - 1) or (nearest == npts - 1 and dragged == 0)):
                            # Join ends together - make an open polyline closed and (if new polyline) finish
                            if dragged == npts - 1:
                                self.item.document.opModifyPolyline(self.item, self.item.points[:npts - 1], True)
                            else:
                                self.item.document.opModifyPolyline(self.item, self.item.points[1:], True)
                            if is_add:
                                self.canvas.exitEditMode(False)
                        elif self.item.closed and not self.adjacent(dragged, nearest):
                            # Break a closed polyline line
                            self.item.document.opModifyPolyline(self.item, self.item.points[dragged + 1:] + self.item.points[:dragged], False)
                        elif (not self.item.closed or npts > 3) and self.adjacent(dragged, nearest):
                            # Just remove the point
                            self.item.document.opModifyPolyline(self.item, self.item.points[:dragged] + self.item.points[dragged + 1:], self.item.closed)
                    else:
                        self.item.document.opModifyPolylinePoint(self.item, dragged, self.snapCoords(pt), False)
                self.item.calcBounds()
                self.canvas.renderDrawing()
                self.canvas.repaint()
                self.canvas.dragging = False
                return True

class CanvasNewPolylineEditor(CanvasPolylineEditor):
    def setTitle(self):
        self.parent.setWindowTitle("Create a polyline")
    def updateLabel(self):
        modeText = f"""\
Click to add a node. Clicking the first point closes the polyline.
Drag a line or click near the start or end node to add a node.
Drag a node to move it.
Double-click a middle point to remove it.
Double-click the last point to complete a polyline.
{self.snapInfo()}"""
        self.descriptionLabel.setText(modeText)
    def mouseMoveEvent(self, e):
        res = CanvasPolylineEditor.mouseMoveEvent(self, e)
        if not self.canvas.dragging:
            if self.item.points and self.visual_feedback is None:
                self.visual_feedback = (FEEDBACK_ADD, self.item.points[-1])
            self.canvas.repaint()
        return res
    def mouseReleaseEvent(self, e):
        if CanvasPolylineEditor.mouseReleaseEvent(self, e):
            return True
        if e.button() == Qt.LeftButton and not self.canvas.dragging:
            # Click on first point to close the polyline
            pos = self.canvas.unproject(e.localPos())
            pt = geom.PathPoint(pos.x(), pos.y())
            nearest = self.nearestPolylineItem(pt)
            if nearest == 0 and len(self.item.points) > 2:
                self.canvas.dragging = False
                self.item.closed = True
                self.canvas.renderDrawing()
                self.canvas.exitEditMode(False)
                return True

