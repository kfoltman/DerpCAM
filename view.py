from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from geom import *
import gcodegen
import toolpath
import sys
import time

class OperationsRenderer(object):
    def __init__(self, operations):
        self.operations = operations
    def bounds(self):
        b = None
        for op in self.operations.operations:
            opb = op.shape.bounds
            if op.paths:
                opb = max_bounds(opb, op.paths.bounds)
            if b is None:
                b = opb
            else:
                b = max_bounds(b, opb)
        return b
    def highlightPen(self, path):
        return QPen(QColor(0, 128, 192, 255), path.tool.diameter)
    def toolPen(self, path, alpha=100, isHighlighted=False):
        if isHighlighted:
            pen = self.highlightPen(path)
        else:
            pen = QPen(QColor(192, 192, 192, alpha), path.tool.diameter)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen
    def renderToolpaths(self, owner):
        # Toolpaths
        for op in self.operations.operations:
            if op.paths:
                for stage in (1, 2):
                    # Null passes (we should probably warn about these)
                    if op.props.start_depth <= op.props.depth:
                        continue
                    # Draw tab-less version unless tabs are full height
                    if op.props.tab_depth is None:
                        tab_alpha = 100
                    else:
                        tab_alpha = 100 * (op.props.start_depth - op.props.tab_depth) / (op.props.start_depth - op.props.depth)
                    if not isinstance(op, gcodegen.TabbedOperation):
                        for toolpath in op.flattened:
                            if stage == 1:
                                pen = self.toolPen(toolpath, alpha=100, isHighlighted = self.isHighlighted(op))
                            if stage == 2:
                                pen = QPen(QColor(0, 0, 0, 100), 0)
                            self.addToolpaths(owner, pen, toolpath, stage, op)
                    elif (op.props.tab_depth is not None and op.props.tab_depth < op.props.start_depth):
                        for toolpath in op.flattened:
                            if stage == 1:
                                # Use the alpha for the tab depth
                                pen = self.toolPen(toolpath, alpha=tab_alpha, isHighlighted = self.isHighlighted(op))
                            if stage == 2:
                                pen = QPen(QColor(0, 0, 0, tab_alpha), 0)
                            self.addToolpaths(owner, pen, toolpath, stage, op)
                        for toolpath in op.tabbed:
                            if stage == 1:
                                # Draw a cut line of the diameter of the cut
                                alpha = tab_alpha if toolpath.is_tab else 100
                                pen = self.toolPen(toolpath, alpha=tab_alpha, isHighlighted = self.isHighlighted(op))
                            else:
                                if toolpath.is_tab:
                                    pen = QPen(QColor(0, 0, 0, tab_alpha), 0)
                                else:
                                    pen = QPen(QColor(0, 0, 0, 100), 0)
                            self.addToolpaths(owner, pen, toolpath, stage, op)
    def isHighlighted(self, operation):
        return False
    def renderNotTabs(self, owner):
        # Pink tint for cuts that are not tabs
        for op in self.operations.operations:
            if self.isHighlighted(op):
                pen = self.highlightPen(op)
            else:
                pen = QPen(QColor(128, 0, 128, 32), op.tool.diameter)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            if op.paths and isinstance(op, gcodegen.TabbedOperation) and op.tabs and op.tabs.tabs:
                for subpath in op.tabbed:
                    if not subpath.is_tab:
                        owner.addLines(pen, subpath.transformed().points, False)
    def renderRapids(self, owner, lastpt = (0, 0)):
        # Red rapid moves
        pen = QPen(QColor(255, 0, 0), 0)
        for op in self.operations.operations:
            if op.paths:
                lastpt = self.addRapids(owner, pen, op.paths, lastpt)
        return lastpt
    def renderShapes(self, owner):
        penOutside = QPen(QColor(0, 0, 255), 0)
        penIslands = QPen(QColor(0, 255, 0), 0)
        for op in self.operations.operations:
            p = op.shape.boundary
            owner.addLines(penOutside, p, op.shape.closed)
            for p in op.shape.islands:
                owner.addLines(penIslands, p, True)
    def renderDrawing(self, owner):
        self.renderToolpaths(owner)
        self.renderNotTabs(owner)
        self.renderRapids(owner)
        self.renderShapes(owner)
    def addRapids(self, owner, pen, path, lastpt):
        if isinstance(path, toolpath.Toolpaths):
            for tp in path.toolpaths:
                lastpt = self.addRapids(owner, pen, tp, lastpt)
            return lastpt
        if path.helical_entry:
            owner.addLines(pen, circle(*path.helical_entry) + path.points[0:1], False)
        owner.addLines(pen, [lastpt, path.points[0]], False)
        return path.points[0 if path.closed else -1]
    def addToolpaths(self, owner, pen, path, stage, operation):
        if isinstance(path, toolpath.Toolpaths):
            for tp in path.toolpaths:
                self.addToolpaths(owner, pen, tp, stage)
            return
        path = path.transformed()
        if GeometrySettings.simplify_arcs:
            path = path.lines_to_arcs()
            if stage == 1:
                pen = self.toolPen(path, isHighlighted = self.isHighlighted(operation))
            else:
                pen = QPen(QColor(160, 160, 160) if path.is_tab else QColor(0, 128, 128), 0)
            owner.addLines(pen, path.points, path.closed, True)
        else:
            owner.addLines(pen, path.points, path.closed)

class PathViewer(QWidget):
    coordsUpdated = pyqtSignal([float, float])

    def __init__(self, renderer):
        QWidget.__init__(self)
        self.renderer = renderer
        self.click_data = None
        self.draft_time = None
        self.majorUpdate()
        self.startTimer(50)
    def majorUpdate(self):
        self.resetZoom()
        self.renderDrawing()
        self.repaint()
    def resetZoom(self):
        sx, sy, ex, ey = self.bounds()
        self.zero = QPointF(0, 0)
        self.zoom_level = 0
        if ex > sx and ey > sy:
            self.zero = QPointF(0.5 * (sx + ex), 0.5 * (sy + ey))
            self.scale = min(self.size().width() / (ex - sx), self.size().height() / (ey - sy))
    def bounds(self):
        b = self.renderer.bounds()
        if b is None:
            return (0, 0, 1, 1)
        return b
    def initUI(self):
        self.setMinimumSize(500, 500)
        self.setMouseTracking(True)
        self.updateCursor()
    def adjustScale(self, pt, delta):
        vpt = self.unproject(pt)
        self.zoom_level += delta
        scale = self.scalingFactor()
        vpt2 = self.unproject(pt)
        self.zero += vpt - vpt2
        self.repaint()
    def addPath(self, pen, *polylines):
        paths = []
        for polyline in polylines:
            path = QPainterPath()
            path.moveTo(*polyline[0])
            for point in polyline[1:]:
                path.lineTo(*point)
            if polyline[0] == polyline[-1]:
                self.drawingOps.append((pen, path, path.boundingRect()))
            else:
                self.drawingOps.append((pen, path, path.boundingRect().marginsAdded(QMarginsF(1, 1, 1, 1))))

    def renderDrawing(self):
        self.drawingOps = []
        self.renderer.renderDrawing(self)

    def isDraft(self):
        return self.click_data or self.draft_time

    def paintGrid(self, e, qp):
        size = self.size()
        zeropt = self.project(QPointF())
        qp.setPen(QPen(QColor(128, 128, 128)))
        qp.drawLine(QLineF(0.0, zeropt.y(), size.width(), zeropt.y()))
        qp.drawLine(QLineF(zeropt.x(), 0.0, zeropt.x(), size.height()))

    def paintDrawingOps(self, e, qp):
        scale = self.scalingFactor()
        zeropt = self.project(QPointF())
        transform = QTransform().translate(zeropt.x(), zeropt.y()).scale(scale, -scale)
        qp.setTransform(transform)
        drawingArea = QRectF(self.rect())
        for pen, path, bbox in self.drawingOps:
            bounds = transform.mapRect(bbox)
            if bounds.intersects(drawingArea):
                # Skip all the thick lines when drawing during an interactive
                # operation like panning and zooming
                if not isinstance(pen, QPen):
                    pen, is_slow = pen(path, scale)
                else:
                    is_slow = pen.widthF() and path.elementCount() > 1000
                if self.isDraft() and is_slow:
                    continue
                qp.setPen(pen)
                # Do not anti-alias very long segments
                if is_slow:
                    qp.setRenderHint(1, False)
                    qp.setRenderHint(8, False)
                qp.drawPath(path)
                if is_slow:
                    qp.setRenderHint(1, True)
                    qp.setRenderHint(8, True)
        qp.setTransform(QTransform())

    def paintOverlays(self, e, qp):
        pass

    def paintEvent(self, e):
        qp = QPainter()
        qp.begin(self)
        qp.setRenderHint(1, True)
        qp.setRenderHint(8, True)

        self.paintGrid(e, qp)
        self.paintDrawingOps(e, qp)
        self.paintOverlays(e, qp)
        qp.end()

    def scalingFactor(self):
        return self.scale * (2 ** (self.zoom_level / 4))

    def project_tuple(self, t):
        return self.project(QPointF(t[0], t[1]))

    def project(self, qpf):
        scale = self.scalingFactor()
        qpf -= self.zero
        return QPointF(qpf.x() * scale + self.cx, -qpf.y() * scale + self.cy)

    def unproject(self, qpf):
        scale = self.scalingFactor()
        mx, my = (self.size().width() * 0.5, self.size().height() * 0.5)
        return QPointF((qpf.x() - mx) / scale + self.zero.x(), -(qpf.y() - my) / scale + self.zero.y())

    def addLines(self, pen, points, closed, has_arcs=False):
        if has_arcs:
            points = CircleFitter.interpolate_arcs(points, gcodegen.debug_simplify_arcs, self.scalingFactor())
        if closed:
            self.addPath(pen, points + points[0:1])
        else:
            self.addPath(pen, points)

    def processMove(self, e):
        orig_zero, orig_pos = self.click_data
        transpose = (e.localPos() - orig_pos) / self.scalingFactor()
        self.zero = orig_zero - QPointF(transpose.x(), -transpose.y())
        self.repaint()

    def mousePressEvent(self, e):
        b = e.button()
        if e.button() == Qt.RightButton:
            self.click_data = (self.zero, e.localPos())
        self.updateCursor()

    def mouseReleaseEvent(self, e):
        if self.click_data:
            self.processMove(e)
            self.click_data = None
            self.repaint()
        self.updateCursor()

    def mouseMoveEvent(self, e):
        if self.click_data:
            self.processMove(e)
        p = self.unproject(e.localPos())
        self.coordsUpdated.emit(p.x(), p.y())

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        if hasattr(e, 'position'):
            pos = e.position()
        else:
            pos = e.posF()
        if delta != 0:
            self.startDeferredRepaint()
        if delta > 0:
            self.adjustScale(pos, 1)
        if delta < 0:
            self.adjustScale(pos, -1)
        if delta != 0:
            # do it again to account for repainting time
            self.startDeferredRepaint()
        if self.click_data:
            self.click_data = (self.zero, pos)

    def startDeferredRepaint(self):
        self.draft_time = time.time() + 0.5

    def resizeEvent(self, e):
        sx, sy, ex, ey = self.bounds()
        self.cx = self.size().width() / 2
        self.cy = self.size().height() / 2
        self.scale = min(self.size().width() / (ex - sx), self.size().height() / (ey - sy))
        self.repaint()

    def timerEvent(self, e):
        if self.draft_time is not None and time.time() > self.draft_time:
            self.draft_time = None
            self.setCursor(Qt.WaitCursor)
            self.repaint()
            self.updateCursor()

    def updateCursor(self):
        if self.click_data:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.CrossCursor)

app = None

def init_app():
    global app
    if app is None:
        app = QApplication(sys.argv)

def viewer_modal(operations):
    global app
    init_app()
    w = QMainWindow()
    w.viewer = PathViewer(OperationsRenderer(operations))
    w.viewer.initUI()
    w.setCentralWidget(w.viewer)
    w.show()
    retcode = app.exec_()
    w = None
    app = None
    return retcode

