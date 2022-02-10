from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from geom import *
import view
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
    def isHighlighted(self, operation):
        return self.owner.isSelected

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
        view.PathViewer.__init__(self, DocumentRenderer(document))
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Base)
    def changeMode(self, mode, item):
        self.mode = mode
        self.mode_item = item
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
    def paintOverlays(self, e, qp):
        if self.mode != DrawingUIMode.MODE_NORMAL:
            if self.mode == DrawingUIMode.MODE_TABS:
                modeText = "Holding tabs"
            if self.mode == DrawingUIMode.MODE_ISLANDS:
                modeText = "Islands"
            icon = self.style().standardIcon(QStyle.SP_DialogApplyButton)
            pen = qp.pen()
            qp.setPen(QPen(QColor(0, 0, 0), 0))
            qp.drawRect(3, 3, 34, 34)
            icon.paint(qp, 5, 5, 30, 30, Qt.AlignCenter)
            qp.setPen(QPen(QColor(128, 0, 0), 0))
            qp.drawText(QRect(40, 5, 200, 35), Qt.AlignVCenter, "Mode: " + modeText)
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
        progress = self.document.pollForUpdateCAM()
        if progress is not None:
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
    def mousePressEvent(self, e):
        b = e.button()
        if e.button() == Qt.LeftButton:
            self.rubberband_rect = None
            self.dragging = False
            pos = self.unproject(e.localPos())
            objs = self.document.drawing.objectsNear(pos, 8 / self.scalingFactor())
            if self.mode != DrawingUIMode.MODE_NORMAL:
                lpos = e.localPos()
                if lpos.x() >= 5 and lpos.x() < 35 and lpos.y() >= 5 and lpos.y() < 35:
                    self.exitEditMode()
                    return
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
            if e.modifiers() & Qt.ControlModifier:
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

