from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from geom import *
import view
import toolpath
from gui import settings

class DrawingUIMode(object):
    MODE_NORMAL = 0
    MODE_ISLANDS = 1
    MODE_TABS = 2

class DocumentRenderer(object):
    def __init__(self, document):
        self.document = document
    def bounds(self):
        return max_bounds((0, 0, 1, 1), self.document.drawing.bounds())
    def renderDrawing(self, owner):
        #PathViewer.renderDrawing(self)
        with view.Spinner():
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
    def renderRapids(self, renderer, owner):
        self.lastpt = renderer.renderRapids(owner, self.lastpt)

class OperationsRendererWithSelection(view.OperationsRenderer):
    def __init__(self, owner):
        view.OperationsRenderer.__init__(self, owner.cam)
        self.owner = owner
        self.isFlashHighlighted = False
    def isHighlighted(self, operation):
        if self.isFlashHighlighted:
            return (64, 160, 128) if not self.owner.isSelected else (0, 192, 255)
        return self.owner.isSelected
    def renderToolpaths(self, owner, alpha_scale=1.0):
        self.isFlashHighlighted = owner.flash_highlight is self.owner
        view.OperationsRenderer.renderToolpaths(self, owner, alpha_scale)
        if owner.mode == DrawingUIMode.MODE_NORMAL and GeometrySettings.draw_arrows:
            self.renderArrows(owner)
    def renderArrows(self, owner):
        pen = QPen(QColor(0, 0, 0), 0)
        self.owner.document.forEachOperation(lambda item: [self.renderArrowsForPath(owner, pen, path) for operation in item.renderer.operations.operations if item.renderer.operations for path in operation.flattened ] if item.renderer else None)
    def renderArrowhead(self, owner, p1, p2, pos):
        if p2.is_arc():
            angle = p2.angle_at_fraction(pos) + pi / 2
            midpoint = p2.at_fraction(pos)
        else:
            angle = atan2(p2.y - p1.y, p2.x - p1.x)
            midpoint = weighted(p1, p2, pos)
        d = 0.3
        d2 = 1
        da = pi / 2
        da2 = 0
        arrow = [
            PathPoint(midpoint.x + d2 * cos(angle + da2), midpoint.y + d2 * sin(angle + da2)),
            PathPoint(midpoint.x + d * cos(angle + da), midpoint.y + d * sin(angle + da)),
            PathPoint(midpoint.x + d * cos(angle - da), midpoint.y + d * sin(angle - da)),
            PathPoint(midpoint.x + d2 * cos(angle + da2), midpoint.y + d2 * sin(angle + da2)),
        ]
        owner.addPolygons(QBrush(QColor(0, 0, 0)), [arrow], False, darken=False)
    def renderArrowsForPath(self, owner, pen, path):
        if isinstance(path, toolpath.Toolpaths):
            for tp in path.toolpaths:
                self.paintArrowsForPath(e, qp, tp)
            return
        tlength = path.tlength
        i = 0
        pos = 0
        spacing = 10
        max_arrows = 1000
        if tlength / spacing > max_arrows:
            spacing = tlength / max_arrows
        lastpt = None
        nodes = path.path.nodes
        #nodes = CircleFitter.simplify(nodes)
        lastpt2 = nodes[0]
        cnt = 0
        while i < len(nodes):
            p1 = lastpt
            p2 = nodes[i]
            if p1 is not None and (dist(p1, p2) > 2 or p2.is_arc() or cnt > 5):
                if p2.is_arc():
                    if p2.length() > 5:
                        self.renderArrowhead(owner, p1, p2, 0.15)
                        self.renderArrowhead(owner, p1, p2, 0.85)
                    self.renderArrowhead(owner, p1, p2, 0.5)
                elif dist(p1, p2) > 5:
                    self.renderArrowhead(owner, p1, p2, 0.15)
                    self.renderArrowhead(owner, p1, p2, 0.85)
                else:
                    self.renderArrowhead(owner, p1, p2, 0.5)
                cnt = 0
                lastpt2 = p2
            elif lastpt is not None:
                if p2.is_arc():
                    cnt += p2.length()
                else:
                    cnt += dist(p1, p2)
            lastpt = p2.seg_end()
            i += 1

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
        self.renderDrawing()
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
    def paintGrid(self, e, qp):
        size = self.size()

        gridPen = QPen(QColor(224, 224, 224))
        qp.setPen(gridPen)
        grid = self.configSettings.grid_resolution
        if grid > 0 and grid < 1000:
            gridm = grid * self.scalingFactor()
            gridres = 2 + int(size.height() / gridm)
            gridfirst = int(self.unproject(QPointF(0, size.height())).y() / grid)
            for i in range(gridres):
                pt = self.project(QPointF(0, (i + gridfirst) * grid))
                qp.drawLine(QLineF(0.0, pt.y(), size.width(), pt.y()))
            gridfirst = int(self.unproject(QPointF(0, 0)).x() / grid)
            gridres = 2 + int(size.width() / gridm)
            for i in range(gridres):
                pt = self.project(QPointF((i + gridfirst) * grid, 0))
                qp.drawLine(QLineF(pt.x(), 0, pt.x(), size.height()))

        zeropt = self.project(QPointF())
        qp.setPen(QPen(QColor(144, 144, 144), 0))
        qp.drawLine(QLineF(0.0, zeropt.y(), size.width(), zeropt.y()))
        qp.drawLine(QLineF(zeropt.x(), 0.0, zeropt.x(), size.height()))
    def paintIslandsEditor(self, e, qp):
        op = self.mode_item
        p = op.shape.boundary + op.shape.boundary[0:1]
        path = QPainterPath()
        view.addPolylineToPath(path, p)
        for p in op.shape.islands:
            path2 = QPainterPath()
            view.addPolylineToPath(path2, p + p[0:1])
            path = path.subtracted(path2)
        transform = self.drawingTransform()
        brush = QBrush(QColor(0, 128, 192), Qt.DiagCrossPattern)
        brush.setTransform(transform.inverted()[0])
        qp.setTransform(transform)
        qp.fillPath(path, brush)
        qp.setTransform(QTransform())
    def paintOverlays(self, e, qp):
        if self.mode == DrawingUIMode.MODE_ISLANDS and self.mode_item:
            self.paintIslandsEditor(e, qp)
        if self.mode != DrawingUIMode.MODE_NORMAL:
            if self.mode == DrawingUIMode.MODE_TABS:
                modeText = "Click on outlines to add/remove preferred locations for holding tabs"
            if self.mode == DrawingUIMode.MODE_ISLANDS:
                modeText = "Click on outlines to toggle exclusion of areas from the pocket"
            pen = qp.pen()
            qp.setPen(QPen(QColor(128, 0, 0), 0))
            qp.drawText(QRect(40, 5, self.width() - 40, 35), Qt.AlignVCenter | Qt.TextWordWrap, modeText)
            if self.mode == DrawingUIMode.MODE_TABS:
                qp.setPen(QPen(QColor(255, 0, 0), 0))
                for tab in self.mode_item.user_tabs:
                    pos = self.project(QPointF(tab.x, tab.y))
                    qp.drawEllipse(pos, 10, 10)
            qp.setPen(pen)
        if self.rubberband_rect:
            qp.setOpacity(0.33)
            qp.drawRect(self.rubberband_rect)
            qp.setOpacity(1.0)
        if not self.document.progress_dialog_displayed:
            progress = self.document.pollForUpdateCAM()
            if progress is not None:
                qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
                qp.setPen(QPen(QColor(128, 0, 0), 0))
                qp.fillRect(QRect(38, 35, 242, 55), QBrush(QColor(255, 255, 255)))
                qp.fillRect(QRect(39, 35, 240 * max(0, min(1, progress)), 55), QBrush(QColor(128, 0, 0, 64)))
                qp.drawRect(QRect(38, 35, 242, 55))
                qp.drawText(QRect(40, 35, 240, 55), Qt.AlignCenter | Qt.AlignVCenter, f"Update in progress ({100 * progress:0.0f}%)")
    def keyPressEvent(self, e):
        if self.mode != DrawingUIMode.MODE_NORMAL and (e.key() == Qt.Key_Escape or e.key() == Qt.Key_Return or e.key() == Qt.Key_Enter):
            self.exitEditMode()
        return view.PathViewer.keyPressEvent(self, e)
    def exitEditMode(self):
        item = self.mode_item
        item.startUpdateCAM()
        self.changeMode(DrawingUIMode.MODE_NORMAL, None)
        self.modeChanged.emit(DrawingUIMode.MODE_NORMAL)
        self.renderDrawing()
        self.majorUpdate()
    def applyClicked(self):
        self.exitEditMode()
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
    def mouseMoveEvent(self, e):
        if not self.dragging and self.mode == DrawingUIMode.MODE_ISLANDS:
            pos = self.unproject(e.localPos())
            objs = self.document.drawing.objectsNear(pos, 24 / self.scalingFactor())
            objs = [o for o in objs if o.shape_id != self.mode_item.shape_id]
            if objs:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.updateCursor()
        if not self.dragging and self.start_point:
            dist = e.localPos() - self.start_point
            if dist.manhattanLength() > QApplication.startDragDistance():
                self.dragging = True
        if self.dragging:
            self.rubberband_rect = QRectF(self.start_point, e.localPos())
            self.startDeferredRepaint()
            self.repaint()
        view.PathViewer.mouseMoveEvent(self, e)
    def mouseReleaseEvent(self, e):
        if self.dragging:
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

