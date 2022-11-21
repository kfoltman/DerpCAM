from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from DerpCAM.common.geom import *
from DerpCAM.common import view, guiutils
from DerpCAM.cam import toolpath
from DerpCAM.gui import settings

class DocumentRenderer(object):
    def __init__(self, document):
        self.document = document
    def bounds(self):
        return max_bounds((0, 0, 100, 100), self.document.drawing.bounds())
    def renderDrawing(self, owner):
        #PathViewer.renderDrawing(self)
        with guiutils.Spinner():
            if False and owner.mode == DrawingUIMode.MODE_ISLANDS:
                # This works, but doesn't look particularly good
                if owner.mode_item.renderer:
                    owner.mode_item.renderer.renderToolpaths(owner, alpha_scale = 0.25)
            self.document.drawing.renderTo(owner, owner.editor)
            if owner.editor is None:
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
        if owner.editor is None and GeometrySettings.draw_arrows:
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
    editorChangeRequest = pyqtSignal(object)
    def __init__(self, document, configSettings):
        self.document = document
        self.configSettings = configSettings
        self.selection = set([])
        self.dragging = False
        self.rubberband_rect = None
        self.start_point = None
        self.editor = None
        self.flash_highlight = None
        view.PathViewer.__init__(self, DocumentRenderer(document))
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Base)
    def flashHighlight(self, item):
        if self.flash_highlight is item:
            return
        self.flash_highlight = item
        self.repaint()
    def setEditor(self, editor):
        self.editor = editor
        if self.editor is not None:
            self.document.setUpdateSuspended(self.editor.item)
        else:
            self.document.setUpdateSuspended(None)
        self.renderDrawing()
        self.repaint()
        self.updateCursor()
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
    def paintOverlays(self, e, qp):
        if self.editor:
            self.editor.paint(e, qp)
        if self.rubberband_rect:
            qp.setPen(QPen(QColor(0, 0, 0), 0))
            qp.setOpacity(0.33)
            qp.drawRect(self.rubberband_rect)
            qp.setOpacity(1.0)
        if not self.document.progress_dialog_displayed:
            progress = self.document.pollForUpdateCAM()
            if progress is not None:
                s = f"Update in progress (888%)"
                metrics = QFontMetrics(qp.font())
                size = metrics.size(Qt.TextSingleLine, s)
                w, h = size.width() + 10, size.height() + 10
                s = s.replace("888", str(int(100 * progress)))
                qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
                qp.setPen(QPen(QColor(128, 0, 0), 0))
                qp.fillRect(QRectF(38, 35, w + 2, h), QBrush(QColor(255, 255, 255)))
                qp.fillRect(QRectF(39, 35, w * max(0, min(1, progress)), h), QBrush(QColor(128, 0, 0, 64)))
                qp.drawRect(QRectF(38, 35, w + 2, h))
                qp.drawText(QRectF(40, 35, w, h), Qt.AlignCenter | Qt.AlignVCenter, f"Update in progress ({100 * progress:0.0f}%)")
    def keyPressEvent(self, e):
        if self.editor:
            res = self.editor.keyPressEvent(e)
            if res is not None:
                return res
        return view.PathViewer.keyPressEvent(self, e)
    def abortEditMode(self, reset_zoom=True):
        if self.editor:
            self.exitEditMode(reset_zoom)
    def exitEditMode(self, reset_zoom=True):
        self.editor.onExit()
        self.editor = None
        self.editorChangeRequest.emit(self.editor)
        self.renderDrawing()
        self.majorUpdate(reset_zoom=reset_zoom)
    def applyClicked(self):
        self.exitEditMode(False)
    def mouseDoubleClickEvent(self, e):
        if self.editor:
            return self.editor.mouseDoubleClickEvent(e)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.rubberband_rect = None
            self.dragging = False
        if self.editor and self.editor.mousePressEvent(e):
            return
        b = e.button()
        if e.button() == Qt.LeftButton:
            pos = self.unproject(e.localPos())
            if self.editor and self.editor.mousePressEvent(e):
                return
            objs = self.document.drawing.objectsNear(pos, 24 / self.scalingFactor())
            self.start_point = e.localPos()
            if objs:
                if e.modifiers() & Qt.ControlModifier:
                    self.selection ^= set(objs)
                else:
                    self.selection = set(objs)
                self.selectionChanged.emit()
                self.repaint()
            else:
                if self.selection and not (e.modifiers() & Qt.ControlModifier):
                    self.selection = set()
                    self.selectionChanged.emit()
                    self.repaint()
        else:
            view.PathViewer.mousePressEvent(self, e)
    def emitCoordsUpdated(self, pos):
        pt = PathPoint(pos.x(), pos.y())
        if self.editor:
            pt = self.editor.snapCoords(pt)
        self.coordsUpdated.emit(pt.x, pt.y)
    def mouseMoveEvent(self, e):
        if self.editor and self.editor.mouseMoveEvent(e):
            view.PathViewer.mouseMoveEvent(self, e)
            return
        if self.dragging:
            sp = self.start_point
            ep = e.localPos()
            self.rubberband_rect = QRectF(QPointF(min(sp.x(), ep.x()), min(sp.y(), ep.y())), QPointF(max(sp.x(), ep.x()), max(sp.y(), ep.y())))
            self.startDeferredRepaint()
            self.repaint()
        else:
            if self.start_point:
                dist = e.localPos() - self.start_point
                if dist.manhattanLength() > QApplication.startDragDistance():
                    self.dragging = True
        view.PathViewer.mouseMoveEvent(self, e)
    def rubberbandDrawingObjects(self):
        pt1 = self.unproject(self.rubberband_rect.bottomLeft())
        pt2 = self.unproject(self.rubberband_rect.topRight())
        return self.document.drawing.objectsWithin(pt1.x(), pt1.y(), pt2.x(), pt2.y())
    def mouseReleaseEvent(self, e):
        if self.editor and self.editor.mouseReleaseEvent(e):
            view.PathViewer.mouseReleaseEvent(self, e)
            return
        if self.dragging:
            objs = self.rubberbandDrawingObjects()
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
