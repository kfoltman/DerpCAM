from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from DerpCAM.common.geom import *
from DerpCAM.common import view, guiutils
from DerpCAM.cam import toolpath
from DerpCAM.gui import settings

class DrawingUIMode(object):
    MODE_NORMAL = 0
    MODE_ISLANDS = 1
    MODE_TABS = 2
    MODE_ENTRY = 3
    MODE_EXIT = 4
    MODE_POLYLINE = 5

class DocumentRenderer(object):
    def __init__(self, document):
        self.document = document
    def bounds(self):
        return max_bounds((0, 0, 1, 1), self.document.drawing.bounds())
    def renderDrawing(self, owner):
        #PathViewer.renderDrawing(self)
        with guiutils.Spinner():
            if False and owner.mode == DrawingUIMode.MODE_ISLANDS:
                # This works, but doesn't look particularly good
                if owner.mode_item.renderer:
                    owner.mode_item.renderer.renderToolpaths(owner, alpha_scale = 0.25)
            modeData = (owner.mode, owner.mode_item)
            self.document.drawing.renderTo(owner, modeData)
            if owner.mode == DrawingUIMode.MODE_NORMAL:
                self.document.forEachOperation(lambda item: item.renderer.renderToolpaths(owner) if item.renderer else None)
                self.lastpt = PathPoint(0, 0)
                self.document.forEachOperation(lambda item: self.renderRapids(item.renderer, owner) if item.renderer else None)
                if dist(self.lastpt, PathPoint(0, 0)) > 0:
                    pen = QPen(QColor(255, 0, 0), 0)
                    owner.addRapidLine(pen, self.lastpt, PathPoint(0, 0))
    def renderRapids(self, renderer, owner):
        self.lastpt = renderer.renderRapids(owner, self.lastpt)

class OperationsRendererWithSelection(view.OperationsRenderer):
    def __init__(self, owner):
        view.OperationsRenderer.__init__(self, owner.cam)
        self.owner = owner
        self.isFlashHighlighted = lambda: False
    def isHighlighted(self, operation):
        if self.isFlashHighlighted():
            return (64, 160, 128) if not self.owner.isSelected else (0, 192, 255)
        return self.owner.isSelected
    def renderToolpaths(self, owner, alpha_scale=1.0):
        self.isFlashHighlighted = lambda: owner.flash_highlight is self.owner
        view.OperationsRenderer.renderToolpaths(self, owner, alpha_scale)
        if owner.mode == DrawingUIMode.MODE_NORMAL and GeometrySettings.draw_arrows:
            self.renderArrows(owner)
    def renderArrows(self, owner):
        pen = QPen(QColor(0, 0, 0), 0)
        arrows = []
        if self.owner.renderer.operations:
            for operation in self.owner.renderer.operations.operations:
                for path in operation.flattened:
                    self.renderArrowsForPath(arrows, pen, path)
        owner.addPolygons(QBrush(QColor(0, 0, 0)), arrows, False, darken=False)
    def renderArrowhead(self, p1, p2, pos, output):
        if p2.is_arc():
            angle = p2.angle_at_fraction(pos) + pi / 2
            midpoint = p2.at_fraction(pos)
        else:
            angle = p1.angle_to(p2)
            midpoint = weighted(p1, p2, pos)
        d = 0.3
        d2 = 1
        da = pi / 2
        da2 = 0
        output.append([
            PathPoint(midpoint.x + d2 * cos(angle + da2), midpoint.y + d2 * sin(angle + da2)),
            PathPoint(midpoint.x + d * cos(angle + da), midpoint.y + d * sin(angle + da)),
            PathPoint(midpoint.x + d * cos(angle - da), midpoint.y + d * sin(angle - da)),
            PathPoint(midpoint.x + d2 * cos(angle + da2), midpoint.y + d2 * sin(angle + da2)),
        ])
    def renderArrowsForPath(self, arrows, pen, path):
        if isinstance(path, toolpath.Toolpaths):
            for tp in path.toolpaths:
                self.paintArrowsForPath(e, qp, tp)
            return
        tlength = path.tlength
        i = 0
        pos = 0
        spacing = 10
        if tlength < spacing / 2:
            return
        if spacing > tlength:
            spacing = tlength
        max_arrows = 1000
        if tlength / spacing > max_arrows:
            spacing = tlength / max_arrows
        pos += spacing / 2
        eps = 0.1
        hint = path.path.start_hint()
        while pos < tlength:
            p1, hint = path.path.point_at_hint(pos - eps, hint)
            p2, hint = path.path.point_at_hint(pos + eps, hint)
            self.renderArrowhead(p1, p2, 0.5, arrows)
            pos += spacing

class DrawingViewer(view.PathViewer):
    selectionChanged = pyqtSignal()
    modeChanged = pyqtSignal(int)
    def __init__(self, document, configSettings):
        self.document = document
        self.configSettings = configSettings
        self.selection = set([])
        self.dragging = False
        self.rubberband_rect = None
        self.start_point = None
        self.mouse_point = None
        self.mode = DrawingUIMode.MODE_NORMAL
        self.mode_item = None
        self.flash_highlight = None
        view.PathViewer.__init__(self, DocumentRenderer(document))
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Base)
        self.applyIcon = self.style().standardIcon(QStyle.SP_DialogApplyButton)
        self.applyButton = QPushButton(self.applyIcon, "", self)
        self.applyButton.setVisible(False)
        self.applyButton.setFixedSize(30, 30)
        self.applyButton.setCursor(QCursor(Qt.ArrowCursor))
        self.applyButton.move(5, 5)
        self.applyButton.clicked.connect(self.applyClicked)
    def flashHighlight(self, item):
        if self.flash_highlight is item:
            return
        self.flash_highlight = item
        self.repaint()
    def changeMode(self, mode, item):
        self.mode = mode
        self.mode_item = item
        if self.mode != DrawingUIMode.MODE_NORMAL:
            self.document.setUpdateSuspended(item)
        else:
            self.document.setUpdateSuspended(None)
        self.applyButton.setVisible(self.mode != DrawingUIMode.MODE_NORMAL)
        self.renderDrawing()
        self.repaint()
    def paintGridPart(self, e, qp, grid):
        size = self.size()
        gridm = grid * self.scalingFactor()
        gridres = 2 + int(size.height() / gridm)
        if gridres > max(size.width(), size.height()) / 4:
            return
        gridfirst = int(self.unproject(QPointF(0, size.height())).y() / grid)
        for i in range(gridres):
            pt = self.project(QPointF(0, (i + gridfirst) * grid))
            qp.drawLine(QLineF(0.0, pt.y(), size.width(), pt.y()))
        gridfirst = int(self.unproject(QPointF(0, 0)).x() / grid)
        gridres = 2 + int(size.width() / gridm)
        for i in range(gridres):
            pt = self.project(QPointF((i + gridfirst) * grid, 0))
            qp.drawLine(QLineF(pt.x(), 0, pt.x(), size.height()))
    def paintGrid(self, e, qp):
        size = self.size()
        grid = self.configSettings.grid_resolution
        if grid > 0 and grid < 1000:
            qp.setPen(QPen(QColor(208, 208, 208), 0))
            self.paintGridPart(e, qp, grid)
        grid = self.configSettings.grid_resolution_minor
        if grid > 0 and grid < 1000:
            qp.setPen(QPen(QColor(244, 244, 244), 0))
            self.paintGridPart(e, qp, grid)
        zeropt = self.project(QPointF())
        qp.setPen(QPen(QColor(144, 144, 144), 0))
        qp.drawLine(QLineF(0.0, zeropt.y(), size.width(), zeropt.y()))
        qp.drawLine(QLineF(zeropt.x(), 0.0, zeropt.x(), size.height()))
    def paintEntryExitEditor(self, e, qp):
        op = self.mode_item
        ee = op.entry_exit
        translation = op.document.drawing.translation()
        #shape = op.orig_shape.translated(*translation).toShape()
        qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for i in ee:
            qp.setPen(QPen(QColor(0, 255, 0, 128), 0))
            qp.setBrush(QBrush(QColor(0, 255, 0, 128)))
            pos = self.project(QPointF(i[0].x, i[0].y))
            if op.cutter:
                r = op.cutter.diameter * self.scalingFactor() / 2
                qp.drawEllipse(pos, r, r)
                qp.setPen(QPen(QColor(255, 0, 0, 128), 0))
                qp.setBrush(QBrush())
                pos = self.project(QPointF(i[1].x, i[1].y))
                qp.drawEllipse(pos, r, r)
        if self.mouse_point is not None:
            erase = None
            mp = PathPoint(self.mouse_point.x(), self.mouse_point.y())
            for pp in self.mode_item.entry_exit:
                if dist(mp, pp[0]) < 5:
                    erase = pp[0]
            if erase:
                qp.setPen(QPen(QColor(255, 128, 128, 192), 0))
            else:
                qp.setPen(QPen(QColor(128, 128, 128, 128), 0))
                if self.mode == DrawingUIMode.MODE_ENTRY:
                    qp.setBrush(QBrush(QColor(128, 128, 128, 128)))
            pos = self.project(self.mouse_point if erase is None else QPointF(erase.x, erase.y))
            if op.cutter:
                r = op.cutter.diameter * self.scalingFactor() / 2
                r2 = r * (2 ** 0.5)
                qp.drawEllipse(pos, r, r)
                if erase:
                    qp.drawLine(pos + QPointF(-r2, -r2), pos + QPointF(r2, r2))
                    qp.drawLine(pos + QPointF(r2, -r2), pos + QPointF(-r2, r2))
            qp.setBrush(QBrush())
    def paintIslandsEditor(self, e, qp):
        op = self.mode_item
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
        transform = self.drawingTransform()
        brush = QBrush(QColor(0, 128, 192), Qt.DiagCrossPattern)
        brush.setTransform(transform.inverted()[0])
        qp.setTransform(transform)
        qp.fillPath(path, brush)
        qp.setTransform(QTransform())
    def paintPolylineEditor(self, e, qp):
        polyline = self.mode_item
        gpath = Path(polyline.points, polyline.closed)
        transform = self.drawingTransform()
        Format = guiutils.Format
        hbox = QPointF(3, 3)
        hbox2a = QPointF(50, 20)
        hbox2b = QPointF(50, 0)
        normPen = QColor(0, 0, 0)
        qp.setPen(normPen)
        for i, j in PathSegmentIterator(gpath):
            if isinstance(i, PathPoint):
                pt = self.project(QPointF(i.x, i.y))
                qp.fillRect(QRectF(pt - hbox, pt + hbox), QColor(0, 0, 0))
                qp.drawText(QRectF(pt - hbox2a, pt + hbox2b), Qt.AlignBottom | Qt.AlignCenter, Format.coord(i.x, brief=True) + ", " + Format.coord(i.y, brief=True))
    def paintOverlays(self, e, qp):
        if self.mode == DrawingUIMode.MODE_ISLANDS and self.mode_item:
            self.paintIslandsEditor(e, qp)
        if self.mode in (DrawingUIMode.MODE_ENTRY, DrawingUIMode.MODE_EXIT) and self.mode_item:
            self.paintEntryExitEditor(e, qp)
        if self.mode == DrawingUIMode.MODE_POLYLINE and self.mode_item:
            self.paintPolylineEditor(e, qp)
        if self.mode != DrawingUIMode.MODE_NORMAL:
            if self.mode == DrawingUIMode.MODE_TABS:
                modeText = "Click on outlines to add/remove preferred locations for holding tabs"
            if self.mode == DrawingUIMode.MODE_ISLANDS:
                modeText = "Click on outlines to toggle exclusion of areas from the pocket"
            if self.mode == DrawingUIMode.MODE_ENTRY:
                orientation = self.mode_item.contourOrientation()
                if orientation:
                    modeText = "Click on desired entry point for the contour running in counter-clockwise direction"
                else:
                    modeText = "Click on desired entry point for the contour running in clockwise direction"
            if self.mode == DrawingUIMode.MODE_EXIT:
                orientation = self.mode_item.contourOrientation()
                if orientation:
                    modeText = "Click on desired end of the cut, counter-clockwise from starting point"
                else:
                    modeText = "Click on desired end of the cut, clockwise from starting point"
            if self.mode == DrawingUIMode.MODE_POLYLINE:
                modeText = f"Drag to add or move a node, double-click to remove, snap={10 ** -self.polylineSnapValue():0.2f} mm"
            pen = qp.pen()
            qp.setPen(QPen(QColor(128, 0, 0), 0))
            qp.drawText(QRectF(40, 5, self.width() - 40, 35), Qt.AlignVCenter | Qt.TextWordWrap, modeText)
            if self.mode == DrawingUIMode.MODE_TABS:
                qp.setPen(QPen(QColor(255, 0, 0), 0))
                for tab in self.mode_item.user_tabs:
                    pos = self.project(QPointF(tab.x, tab.y))
                    qp.drawEllipse(pos, 10, 10)
            qp.setPen(pen)
        if self.rubberband_rect:
            qp.setPen(QPen(QColor(0, 0, 0), 0))
            qp.setOpacity(0.33)
            qp.drawRect(self.rubberband_rect)
            qp.setOpacity(1.0)
        if not self.document.progress_dialog_displayed:
            progress = self.document.pollForUpdateCAM()
            if progress is not None:
                qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
                qp.setPen(QPen(QColor(128, 0, 0), 0))
                qp.fillRect(QRectF(38, 35, 242, 55), QBrush(QColor(255, 255, 255)))
                qp.fillRect(QRectF(39, 35, 240 * max(0, min(1, progress)), 55), QBrush(QColor(128, 0, 0, 64)))
                qp.drawRect(QRectF(38, 35, 242, 55))
                qp.drawText(QRectF(40, 35, 240, 55), Qt.AlignCenter | Qt.AlignVCenter, f"Update in progress ({100 * progress:0.0f}%)")
    def keyPressEvent(self, e):
        if self.mode != DrawingUIMode.MODE_NORMAL and (e.key() == Qt.Key_Escape or e.key() == Qt.Key_Return or e.key() == Qt.Key_Enter):
            self.exitEditMode()
        return view.PathViewer.keyPressEvent(self, e)
    def exitEditMode(self):
        item = self.mode_item
        item.emitPropertyChanged()
        self.changeMode(DrawingUIMode.MODE_NORMAL, None)
        self.modeChanged.emit(DrawingUIMode.MODE_NORMAL)
        self.renderDrawing()
        self.majorUpdate()
    def applyClicked(self):
        self.exitEditMode()
    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.unproject(e.localPos())
            objs = self.document.drawing.objectsNear(pos, 24 / self.scalingFactor())
            if self.mode == DrawingUIMode.MODE_POLYLINE:
                self.clickOnPolyline(self.mode_item, pos, e, True)
    def mousePressEvent(self, e):
        b = e.button()
        if e.button() == Qt.LeftButton:
            self.rubberband_rect = None
            self.dragging = False
            pos = self.unproject(e.localPos())
            objs = self.document.drawing.objectsNear(pos, 24 / self.scalingFactor())
            if self.mode != DrawingUIMode.MODE_NORMAL:
                if self.mode == DrawingUIMode.MODE_ISLANDS:
                    objs = [o for o in objs if o.shape_id != self.mode_item.shape_id]
                if self.mode == DrawingUIMode.MODE_ISLANDS and not objs:
                    self.start_point = e.localPos()
                    return
                lpos = e.localPos()
                if self.mode == DrawingUIMode.MODE_ISLANDS:
                    self.document.opChangeProperty(self.mode_item.prop_islands, [(self.mode_item, self.mode_item.islands ^ set([o.shape_id for o in objs]))])
                    self.renderDrawing()
                    self.repaint()
                elif self.mode == DrawingUIMode.MODE_TABS:
                    pt = PathPoint(pos.x(), pos.y())
                    ptToDelete = None
                    for pp in self.mode_item.user_tabs:
                        if dist(pt, pp) < 5:
                            ptToDelete = pp
                    if ptToDelete is not None:
                        self.document.opChangeProperty(self.mode_item.prop_user_tabs, [(self.mode_item, self.mode_item.user_tabs - set([ptToDelete]))])
                    else:
                        self.document.opChangeProperty(self.mode_item.prop_user_tabs, [(self.mode_item, self.mode_item.user_tabs | set([pt]))])
                    self.renderDrawing()
                    self.repaint()
                elif self.mode == DrawingUIMode.MODE_ENTRY:
                    pt = PathPoint(pos.x(), pos.y())
                    erase = None
                    for pp in self.mode_item.entry_exit:
                        if dist(pt, pp[0]) < 5:
                            erase = True
                    if erase:
                        self.document.opChangeProperty(self.mode_item.prop_entry_exit, [(self.mode_item, [])])
                    else:
                        self.document.opChangeProperty(self.mode_item.prop_entry_exit, [(self.mode_item, [(pt, pt)])])
                        self.mode = DrawingUIMode.MODE_EXIT
                    self.renderDrawing()
                    self.repaint()
                elif self.mode == DrawingUIMode.MODE_EXIT:
                    sp = self.mode_item.entry_exit[0][0]
                    pt = PathPoint(pos.x(), pos.y())
                    self.document.opChangeProperty(self.mode_item.prop_entry_exit, [(self.mode_item, [(sp, pt)])])
                    self.exitEditMode()
                elif self.mode == DrawingUIMode.MODE_POLYLINE:
                    self.clickOnPolyline(self.mode_item, pos, e, False)
                return
            if objs:
                if e.modifiers() & Qt.ControlModifier:
                    self.selection ^= set(objs)
                else:
                    self.selection = set(objs)
                self.selectionChanged.emit()
                self.repaint()
                self.start_point = e.localPos()
            else:
                self.start_point = e.localPos()
                if self.selection and not (e.modifiers() & Qt.ControlModifier):
                    self.selection = set()
                    self.selectionChanged.emit()
                    self.repaint()
        else:
            view.PathViewer.mousePressEvent(self, e)
    def clickOnPolyline(self, polyline, pos, e, is_double):
        pt = PathPoint(pos.x(), pos.y())
        nearest = self.nearestPolylineItem(polyline, pt)
        if nearest is not None:
            if is_double:
                if len(polyline.points) > 2:
                    del polyline.points[nearest]
                    self.renderDrawing()
                    self.repaint()
                return
            else:
                if nearest == 0 or not polyline.points[nearest - 1].is_arc():
                    self.dragging = True
                    self.drag_start_data = (e.localPos(), nearest, polyline.points[nearest])
                    return
        if not is_double:
            item = self.nearestPolylineLine(polyline, pt)
            if item is not None:
                pt = self.polylineSnap(pt)
                self.document.opModifyPolyline(polyline, polyline.points[:item] + [pt] + polyline.points[item:], polyline.closed)
                self.dragging = True
                self.drag_start_data = (e.localPos(), item, pt)
                self.renderDrawing()
                self.repaint()
    def nearestPolylineItem(self, polyline, pt, exclude=None):
        nearest = None
        nearest_dist = None
        for i, pp in enumerate(polyline.points):
            if exclude is not None and i == exclude:
                continue
            pdist = pt.dist(pp)
            if nearest is None or pdist < nearest_dist:
                nearest = i
                nearest_dist = pdist
        if nearest_dist is not None and nearest_dist < 5 / self.scalingFactor():
            return nearest
        return None
    def nearestPolylineLine(self, polyline, pt):
        if not polyline.points:
            return None
        nearest = 0
        nearest_dist = None
        for i, line in enumerate(PathSegmentIterator(Path(polyline.points, polyline.closed))):
            if line[1].is_point():
                pdist = dist_line_to_point(line[0], line[1], pt)
                if nearest_dist is None or pdist < nearest_dist:
                    nearest = 1 + i
                    nearest_dist = pdist
        if nearest_dist is not None and nearest_dist < 5 / self.scalingFactor():
            return nearest
        return None
    def polylineSnapValue(self):
        if self.scalingFactor() >= 330:
            return 2
        elif self.scalingFactor() >= 33:
            return 1
        else:
            return 0
    def polylineSnap(self, pt):
        snap = self.polylineSnapValue()
        return PathPoint(round(pt.x, snap), round(pt.y, snap))
    def emitCoordsUpdated(self, p):
        if self.mode == DrawingUIMode.MODE_POLYLINE:
            pt = self.polylineSnap(PathPoint(p.x(), p.y()))
            self.coordsUpdated.emit(pt.x, pt.y)
        else:
            self.coordsUpdated.emit(p.x(), p.y())
    def mouseMoveEvent(self, e):
        if self.dragging:
            if self.mode == DrawingUIMode.MODE_POLYLINE:
                sp, dragging, start_pos = self.drag_start_data
                pos = self.unproject(e.localPos())
                pt = PathPoint(pos.x(), pos.y())
                nearest = self.nearestPolylineItem(self.mode_item, pt, dragging)
                if nearest is not None:
                    self.setCursor(Qt.ForbiddenCursor)
                else:
                    self.document.opModifyPolylinePoint(self.mode_item, dragging, self.polylineSnap(pt), True)
                    self.setCursor(Qt.SizeAllCursor)
                self.renderDrawing()
                self.repaint()
            else:
                sp = self.start_point
                ep = e.localPos()
                self.rubberband_rect = QRectF(QPointF(min(sp.x(), ep.x()), min(sp.y(), ep.y())), QPointF(max(sp.x(), ep.x()), max(sp.y(), ep.y())))
                self.startDeferredRepaint()
                self.repaint()
        else:
            if self.mode in (DrawingUIMode.MODE_ENTRY, DrawingUIMode.MODE_EXIT):
                self.mouse_point = self.unproject(e.localPos())
                self.repaint()            
            elif self.mode == DrawingUIMode.MODE_ISLANDS:
                pos = self.unproject(e.localPos())
                objs = self.document.drawing.objectsNear(pos, 24 / self.scalingFactor())
                objs = [o for o in objs if o.shape_id != self.mode_item.shape_id]
                if objs:
                    self.setCursor(Qt.PointingHandCursor)
                else:
                    self.updateCursor()
            elif self.mode == DrawingUIMode.MODE_POLYLINE:
                pos = self.unproject(e.localPos())
                pt = PathPoint(pos.x(), pos.y())
                nearest = self.nearestPolylineItem(self.mode_item, pt)
                if nearest is not None:
                    self.setCursor(Qt.PointingHandCursor)
                else:
                    nearest = self.nearestPolylineLine(self.mode_item, pt)
                    if nearest is not None:
                        self.setCursor(Qt.CrossCursor)
                    else:
                        self.setCursor(Qt.ArrowCursor)
            elif self.start_point:
                dist = e.localPos() - self.start_point
                if dist.manhattanLength() > QApplication.startDragDistance():
                    self.dragging = True
        view.PathViewer.mouseMoveEvent(self, e)
    def mouseReleaseEvent(self, e):
        if self.dragging:
            if self.mode == DrawingUIMode.MODE_POLYLINE:
                sp, dragged, start_pos = self.drag_start_data
                pos = self.unproject(e.localPos())
                pt = PathPoint(pos.x(), pos.y())
                nearest = self.nearestPolylineItem(self.mode_item, pt, dragged)
                if nearest is not None:
                    self.document.opModifyPolyline(self.mode_item, self.mode_item.points[:dragged] + self.mode_item.points[dragged + 1:], self.mode_item.closed)
                else:
                    self.document.opModifyPolylinePoint(self.mode_item, dragged, self.polylineSnap(pt), False)
                self.mode_item.calcBounds()
                self.renderDrawing()
                self.repaint()
                self.dragging = False
                return
            pt1 = self.unproject(self.rubberband_rect.bottomLeft())
            pt2 = self.unproject(self.rubberband_rect.topRight())
            objs = self.document.drawing.objectsWithin(pt1.x(), pt1.y(), pt2.x(), pt2.y())
            if self.mode == DrawingUIMode.MODE_ISLANDS:
                self.document.opChangeProperty(self.mode_item.prop_islands, [(self.mode_item, self.mode_item.islands ^ set([o.shape_id for o in objs if o.shape_id != self.mode_item.shape_id]))])
            elif e.modifiers() & Qt.ControlModifier:
                self.selection ^= set(objs)
            else:
                self.selection = set(objs)
            self.dragging = False
            self.start_point = None
            self.rubberband_rect = None
            self.selectionChanged.emit()
            self.renderDrawing()
            self.repaint()
        else:
            self.dragging = False
            self.start_point = None
            self.rubberband_rect = None
        view.PathViewer.mouseReleaseEvent(self, e)
    def setSelection(self, selection):
        self.selection = set(selection)
        self.repaint()

def sortPoints(pos):
    n = len(pos)
    first = 0
    startPos = PathPoint(0.0, 0.0)
    firstDist = pos[0][0].dist(startPos)
    for i in range(1, n):
        tryDist = pos[i][0].dist(startPos)
        if tryDist < firstDist:
            first = i
            firstDist = tryDist
    deck = list(range(n))
    seq = [first]
    lastPoint = pos[first][1]
    del deck[first]
    while deck:
        shortest = 0
        shortestLen = lastPoint.dist(pos[deck[0]][0])
        for i in range(1, len(deck)):
            thisLen = lastPoint.dist(pos[deck[i]][0])
            if thisLen < shortestLen:
                shortest = i
                shortestLen = thisLen
        nearestIdx = deck[shortest]
        seq.append(nearestIdx)
        lastPoint = pos[nearestIdx][1]
        del deck[shortest]
    return seq

def sortSelections(selections, shape_ids):
    if len(selections) < 2:
        return shape_ids
    selections = list(selections)
    pos = [i.startEndPos() for i in selections]
    seq = sortPoints(pos)
    # Map shape_id to order
    spos = {}
    for i, v in enumerate(seq):
        spos[selections[v].shape_id] = i
    res = {}
    for i in list(sorted(shape_ids.keys(), key=lambda shape_id: spos[shape_id])):
        res[i] = list(sorted(shape_ids[i], key=lambda shape_id: spos[shape_id]))
    return res
