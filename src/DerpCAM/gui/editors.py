import math
import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.common import geom, guiutils, view
from DerpCAM.gui import model

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
        if self.cancel_index is not None:
            while self.item.document.undoStack.index() > self.cancel_index:
                self.item.document.undoStack.undo()
        if self.canvas.editor:
            self.canvas.exitEditMode(False)
    def createControls(self):
        self.createLabel()
        self.createExtraControls()
        self.createButtons()
        self.updateLabel()
        self.parent.widget().setLayout(self.layout)
    def createExtraControls(self):
        pass
    def connectSignals(self):
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
        if isinstance(self.item, model.DrawingItemTreeItem):
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

class CanvasDrawingItemEditor(CanvasEditor):
    def __init__(self, item, cancel_index=None):
        CanvasEditor.__init__(self, item)
        self.last_pos = None
        self.visual_feedback = None
        self.can_cancel = True
        self.cancel_index = cancel_index
    def paintPoint(self, qp, loc, as_arc):
        coordsText = "(" + guiutils.Format.coord(loc.x, brief=True) + ", " + guiutils.Format.coord(loc.y, brief=True) + ")"
        hbox = QPointF(3, 3)
        metrics = QFontMetrics(qp.font())
        size = metrics.size(Qt.TextSingleLine, coordsText)
        width = size.width() + 10
        hbox2a = QPointF(width / 2, size.height() + 1)
        hbox2b = QPointF(width / 2, 5)
        displ = QPointF(0, 7.5)
        pt = self.canvas.project(QPointF(loc.x, loc.y))
        color = qp.pen().color()
        if as_arc:
            brush = qp.brush()
            qp.setBrush(color)
            qp.drawEllipse(QRectF(pt - hbox, pt + hbox))
            qp.setBrush(brush)
        else:
            qp.fillRect(QRectF(pt - hbox, pt + hbox), color)
        qp.drawText(QRectF(pt - hbox2a - displ, pt + hbox2b - displ), Qt.AlignBottom | Qt.AlignCenter, coordsText)
    def setTitle(self):
        self.parent.setWindowTitle("Create a text object")
    def updateLabel(self):
        modeText = f"""\
Click on a drawing to create a text object.
{self.snapInfo()}"""
        self.descriptionLabel.setText(modeText)
    def penForPath(self, item, path):
        if isinstance(self.item, model.DrawingItemTreeItem) and self.item.shape_id == item.shape_id:
            return None
        return item.defaultGrayPen
    def onShapesDeleted(self, shapes):
        if isinstance(self.item, model.DrawingItemTreeItem) and self.item in shapes:
            self.canvas.exitEditMode(False)
    def coordSnapValue(self):
        if self.canvas.scalingFactor() >= 330:
            return 2
        elif self.canvas.scalingFactor() >= 33:
            return 1
        else:
            return 0
    def snapCoords(self, pt):
        snap = self.coordSnapValue()
        def cround(val):
            val = round(val, snap)
            # Replace -0 by 0
            return val if val else 0
        return geom.PathPoint(cround(pt.x), cround(pt.y))
    def snapInfo(self):
        return f"snap={10 ** -self.coordSnapValue():0.2f} mm (zoom-dependent)"

class TempRenderer:
    def __init__(self):
        self.drawingOps = []
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

class CanvasNewItemEditor(CanvasDrawingItemEditor):
    def __init__(self, document):
        item = self.createItem(document)
        CanvasDrawingItemEditor.__init__(self, item)
    def initUI(self, parent, canvas):
        CanvasDrawingItemEditor.initUI(self, parent, canvas)
        eLocalPos = self.canvas.mapFromGlobal(QCursor.pos())
        pos = self.canvas.unproject(eLocalPos)
        self.last_pos = self.snapCoords(geom.PathPoint(pos.x(), pos.y()))
        self.canvas.repaint()
    def drawCursorPoint(self, qp):
        if self.last_pos is not None:
            qp.setPen(QColor(0, 0, 0, 128))
            self.paintPoint(qp, self.last_pos, as_arc=False)
    def drawPreview(self, qp):
        self.item.origin = self.last_pos
        self.item.createPaths()
        oldTransform = qp.transform()
        transform = self.canvas.drawingTransform()
        qp.setTransform(transform)
        qp.setPen(QPen(QColor(0, 0, 0, 128), 1.0 / self.canvas.scalingFactor()))
        tempRenderer = TempRenderer()
        self.item.renderTo(tempRenderer, None)
        tempRenderer.paint(qp, self.canvas)
        qp.setTransform(oldTransform)
    def paint(self, e, qp):
        if self.last_pos is not None:
            self.drawCursorPoint(qp)
            self.drawPreview(qp)

class CanvasNewTextEditor(CanvasNewItemEditor):
    def createItem(self, document):
        style = model.DrawingTextStyle(height=10, width=1, halign=model.DrawingTextStyleHAlign.LEFT, valign=model.DrawingTextStyleVAlign.BASELINE, angle=0, font_name="Bitstream Vera", spacing=0)
        return model.DrawingTextTreeItem(document, geom.PathPoint(0, 0), 0, style, "Text")
    def mouseMoveEvent(self, e):
        pos = self.canvas.unproject(e.localPos())
        newPos = self.snapCoords(geom.PathPoint(pos.x(), pos.y()))
        if self.last_pos is None or self.last_pos != newPos:
            self.last_pos = newPos
            self.canvas.repaint()
        return False
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.canvas.unproject(e.localPos())
            newPos = self.snapCoords(geom.PathPoint(pos.x(), pos.y()))
            self.item.origin = newPos
            self.item.document.opAddDrawingItems([self.item])
            self.apply()
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
                    qp.drawLine(self.canvas.project(QPointF(other.x, other.y)), self.canvas.project(QPointF(self.last_pos.x, self.last_pos.y)))
            elif self.visual_feedback[0] == FEEDBACK_REMOVE:
                other1 = self.visual_feedback[1].seg_end()
                other2 = self.visual_feedback[2].seg_end()
                if other1.is_point() and other2.is_point():
                    qp.drawLine(self.canvas.project(QPointF(other1.x, other1.y)), self.canvas.project(QPointF(other2.x, other2.y)))
    def isArcEndpoint(self, index):
        if self.item.points[index].is_arc():
            return True, index, 1
        elif index + 1 < len(self.item.points) and self.item.points[index + 1].is_arc():
            return True, index + 1, 0
        return False, index, None
    def startDragArc(self, pos, index, where):
        self.drag_start_data = (pos, index, where, self.item.points[index].as_tuple())
    def clickOnPolyline(self, pos, e, is_double):
        self.visual_feedback = None
        npts = len(self.item.points)
        is_add = isinstance(self, CanvasNewPolylineEditor)
        polyline = self.item
        pt = geom.PathPoint(pos.x(), pos.y())
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
            pos = self.canvas.unproject(e.localPos())
            self.clickOnPolyline(pos, e, True)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.canvas.unproject(e.localPos())
            self.clickOnPolyline(pos, e, False)
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
        self.last_pos = self.snapCoords(geom.PathPoint(pos.x(), pos.y()))
        npts = len(self.item.points)
        if self.canvas.dragging:
            sp, dragged, start_pos = self.drag_start_data[:3]
            is_arc = len(self.drag_start_data) > 3
            pos = self.canvas.unproject(e.localPos())
            pt = geom.PathPoint(pos.x(), pos.y())
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
        pos = self.canvas.unproject(e.localPos())
        pt = geom.PathPoint(pos.x(), pos.y())
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
                pos = self.canvas.unproject(e.localPos())
                pt = geom.PathPoint(pos.x(), pos.y())
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

