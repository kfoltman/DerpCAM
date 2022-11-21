import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.common import geom, guiutils, view

class CanvasEditor(object):
    def __init__(self, item):
        self.item = item
    def initUI(self, parent, canvas):
        self.parent = parent
        self.canvas = canvas
        self.parent.setWidget(QWidget())
        self.layout = QFormLayout()
        self.setTitle()
        self.createControls()
        self.connectSignals()
    def createControls(self):
        self.createLabel()
        self.createButtons()
        self.updateLabel()
        self.parent.widget().setLayout(self.layout)
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
        self.applyButton.clicked.connect(lambda: self.parent.applyClicked.emit())
        self.layout.addWidget(self.applyButton)
    def snapCoords(self, pt):
        return pt
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape or e.key() == Qt.Key_Return or e.key() == Qt.Key_Enter:
            self.canvas.exitEditMode(False)
    def onExit(self):
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

class CanvasPolylineEditor(CanvasEditor):
    def __init__(self, item):
        CanvasEditor.__init__(self, item)
        self.last_pos = None
        self.visual_feedback = None
    def connectSignals(self):
        self.canvas.zoomChanged.connect(self.updateLabel)
        self.item.document.shapesUpdated.connect(self.resetVisualFeedback)
    def resetVisualFeedback(self):
        if self.visual_feedback:
            self.visual_feedback = None
            self.canvas.repaint()
    def setTitle(self):
        self.parent.setWindowTitle("Modify a polyline")
    def updateLabel(self):
        modeText = f"""\
Drag nodes to move them.
Moving a node into a neighbour deletes it.
Moving a node into a non-neighbour node breaks up a closed polyline.
Moving the first node into the last one closes an open polyline.
Dragging a line inserts a node at that point.
Clicking near the start/end of an open polyline adds a node there.
Double-clicking a node removes it.
snap={10 ** -self.polylineSnapValue():0.2f} mm (zoom-dependent)"""
        self.descriptionLabel.setText(modeText)
    def paintPoint(self, qp, loc):
        coordsText = "(" + guiutils.Format.coord(loc.x, brief=True) + ", " + guiutils.Format.coord(loc.y, brief=True) + ")"
        hbox = QPointF(3, 3)
        metrics = QFontMetrics(qp.font())
        size = metrics.size(Qt.TextSingleLine, coordsText)
        width = size.width() + 10
        hbox2a = QPointF(width / 2, size.height())
        hbox2b = QPointF(width / 2, -5)
        pt = self.canvas.project(QPointF(loc.x, loc.y))
        color = qp.pen().color()
        qp.fillRect(QRectF(pt - hbox, pt + hbox), color)
        qp.drawText(QRectF(pt - hbox2a, pt + hbox2b), Qt.AlignBottom | Qt.AlignCenter, coordsText)
    def paint(self, e, qp):
        is_add = isinstance(self, CanvasNewPolylineEditor)
        polyline = self.item
        normPen = QColor(0, 0, 0)
        qp.setPen(normPen)
        for i in polyline.points:
            if i.is_point():
                self.paintPoint(qp, i)
        if is_add and self.last_pos is not None:
            qp.setPen(QColor(0, 0, 0, 128))
            self.paintPoint(qp, self.last_pos)
        if self.visual_feedback:
            qp.setPen(QColor(0, 0, 0, 128))
            if self.visual_feedback[0] == FEEDBACK_ADD:
                other = self.visual_feedback[1]
                qp.drawLine(self.canvas.project(QPointF(other.x, other.y)), self.canvas.project(QPointF(self.last_pos.x, self.last_pos.y)))
            elif self.visual_feedback[0] == FEEDBACK_REMOVE:
                other1 = self.visual_feedback[1]
                other2 = self.visual_feedback[2]
                qp.drawLine(self.canvas.project(QPointF(other1.x, other1.y)), self.canvas.project(QPointF(other2.x, other2.y)))
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
                if nearest == 0 or not polyline.points[nearest - 1].is_arc():
                    self.canvas.start_point = e.localPos()
                    self.drag_start_data = (e.localPos(), nearest, polyline.points[nearest])
                    return
        if not is_double:
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
            pdist = pt.dist(pp)
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
    def polylineSnapValue(self):
        if self.canvas.scalingFactor() >= 330:
            return 2
        elif self.canvas.scalingFactor() >= 33:
            return 1
        else:
            return 0
    def snapCoords(self, pt):
        snap = self.polylineSnapValue()
        def cround(val):
            val = round(val, snap)
            # Replace -0 by 0
            return val if val else 0
        return geom.PathPoint(cround(pt.x), cround(pt.y))
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
    def mouseMoveEvent(self, e):
        repaint = False
        if self.visual_feedback:
            self.visual_feedback = None
            repaint = True
        pos = self.canvas.unproject(e.localPos())
        self.last_pos = self.snapCoords(geom.PathPoint(pos.x(), pos.y()))
        npts = len(self.item.points)
        if self.canvas.dragging:
            sp, dragged, start_pos = self.drag_start_data
            pos = self.canvas.unproject(e.localPos())
            pt = geom.PathPoint(pos.x(), pos.y())
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
            is_add = isinstance(self, CanvasNewPolylineEditor)
            if is_add and (nearest == 0 or nearest == npts - 1):
                self.canvas.setCursor(guiutils.customCursor('polyline_join'))
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
                sp, dragged, start_pos = self.drag_start_data
                pos = self.canvas.unproject(e.localPos())
                pt = geom.PathPoint(pos.x(), pos.y())
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
    def penForPath(self, item, path):
        if self.item.shape_id == item.shape_id:
            return None
        return item.defaultGrayPen
    def onShapesDeleted(self, shapes):
        if self.item in shapes:
            self.canvas.exitEditMode(False)

class CanvasNewPolylineEditor(CanvasPolylineEditor):
    def __init__(self, item):
        CanvasPolylineEditor.__init__(self, item)
    def setTitle(self):
        self.parent.setWindowTitle("Create a polyline")
    def updateLabel(self):
        modeText = """\
Click to add a node. Clicking the first point closes the polyline.
Drag a line or click near the start or end node to add a node.
Drag a node to move it.
Double-click a middle point to remove it.
Double-click the last point to complete a polyline."""
        modeText += f"\nsnap={10 ** -self.polylineSnapValue():0.2f} mm (zoom-dependent)"
        self.descriptionLabel.setText(modeText)
    def paint(self, e, qp):
        CanvasPolylineEditor.paint(self, e, qp)
    def mouseMoveEvent(self, e):
        res = CanvasPolylineEditor.mouseMoveEvent(self, e)
        if not self.canvas.dragging:
            if self.item.points:
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

