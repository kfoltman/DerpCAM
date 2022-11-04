from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from .geom import *
from .guiutils import Spinner
from DerpCAM.cam import gcodegen
from DerpCAM.cam import toolpath
import sys
import time

interpolate_all_arcs = False
draw_arrows_for_rapids = True

def addPolylineToPath(path, polyline):
    path.moveTo(polyline[0].x, polyline[0].y)
    for point in polyline[1:]:
        if point.is_point():
            path.lineTo(point.x, point.y)
        else:
            arc = point
            # Qt doesn't seem to handle large-radius arcs correctly, so we
            # turn these into lines instead
            if arc.c.r > 5 * arc.length():
                npts = arc.steps or 20
                for f in range(npts + 1):
                    pt = arc.at_fraction(f / npts)
                    path.lineTo(pt.x, pt.y)
            else:
                path.arcTo(QRectF(arc.c.cx - arc.c.r, arc.c.cy - arc.c.r, 2 * arc.c.r, 2 * arc.c.r), -arc.sstart * 180 / pi, -arc.sspan * 180 / pi)

class OperationsRenderer(object):
    def __init__(self, operations):
        self.operations = operations
    def bounds(self):
        b = None
        for op in self.operations.operations:
            opb = op.shape.bounds
            for depth, paths in op.to_preview():
                opb = max_bounds(opb, paths.bounds)
            if b is None:
                b = opb
            else:
                b = max_bounds(b, opb)
        return b
    def penColInt(self, r, g, b, a, diameter):
        def c2w(v):
            return int(255 + (v - 255) * a / 255)
        return QPen(QColor(c2w(r), c2w(g), c2w(b)), diameter)
    def toolPen(self, path, alpha=255, isHighlighted=False):
        if isinstance(isHighlighted, tuple):
            pen = self.penColInt(*isHighlighted, alpha, path.tool.diameter)
        elif isHighlighted:
            pen = self.penColInt(0, 128, 192, alpha, path.tool.diameter)
        else:
            pen = self.penColInt(192, 192, 192, alpha, path.tool.diameter)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen
    def toolPenFunc(self, toolpath, alpha, op):
        return lambda path, scale: (self.toolPen(toolpath, alpha=alpha, isHighlighted = self.isHighlighted(op)), False)
    def depth2intensity(self, z, thickness):
        if z >= -0.001:
            return 0.1
        return 0.25 + 0.75 * -z / thickness
    def renderToolpaths(self, owner, alpha_scale=1.0):
        # Toolpaths
        for op in self.operations.operations:
            preview = op.to_preview()
            if preview:
                for stage in (1, 2):
                    # Null passes (we should probably warn about these)
                    if op.props.start_depth <= op.props.depth:
                        continue
                    for depth, toolpath in preview:
                        if self.operations.thickness:
                            alpha = int(255 * alpha_scale * self.depth2intensity(depth, self.operations.thickness))
                        else:
                            alpha = int(255 * alpha_scale * (op.props.start_depth - depth) / (op.props.start_depth - op.props.depth))
                        if stage == 1:
                            pen = self.toolPenFunc(toolpath, alpha, op)
                        if stage == 2:
                            pen = self.penColInt(0, 0, 0, alpha, 0)
                        self.addToolpaths(owner, pen, toolpath, stage, op)
    def isHighlighted(self, operation):
        return False
    def renderRapids(self, owner, lastpt = PathPoint(0, 0)):
        # Red rapid moves
        pen = QPen(QColor(192, 0, 0), 0)
        for op in self.operations.operations:
            for i in op.cutpaths:
                last_depth = self.operations.machine_params.safe_z
                for depth, subpath in i.to_preview():
                    lastpt = self.addRapids(owner, pen, subpath, lastpt, op, depth < last_depth)
                    last_depth = depth
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
        self.renderRapids(owner)
        self.renderShapes(owner)
    def addRapids(self, owner, pen, path, lastpt, op, is_descend):
        assert not isinstance(path, toolpath.Toolpaths)
        if is_descend:
            if path.helical_entry:
                he = path.helical_entry
                if isinstance(he, toolpath.HelicalEntry):
                    pen2 = lambda path, owner: (self.toolPen(path, alpha=255, isHighlighted=self.isHighlighted(op)), False)
                    owner.addPolygons(lambda: self.pen2brush(owner, path, pen2), [circle2(he.point.x, he.point.y, he.r + path.tool.diameter / 2, None, 0, 0 + 2 * pi)], False, darken=True)
                    owner.addLines(pen, circle2(he.point.x, he.point.y, he.r, None, he.angle, he.angle + 2 * pi) + path.path.nodes[0:1], False, darken=False)
                elif isinstance(he, toolpath.PlungeEntry):
                    sp = he.start
                    d = path.tool.diameter / (2 * sqrt(2))
                    owner.addLines(pen, circle(sp.x, sp.y, path.tool.diameter / 2, None, 5 * pi / 4, 13 * pi / 4) + [PathPoint(sp.x - d, sp.y - d), PathPoint(sp.x + d, sp.y + d), sp, PathPoint(sp.x - d, sp.y + d), PathPoint(sp.x + d, sp.y - d)], False, darken=False)
            else:
                pt = path.path.seg_start()
                brush = QBrush(pen.color())
                if pt.dist(lastpt) < 1.0 / GeometrySettings.RESOLUTION:
                    # Highlight the puzzling reentry moves in pink
                    brush = QBrush(QColor(255, 0, 255))
                r = 8
                owner.addScaledPolygon(brush, [pt, pt.translated(r, r), pt.translated(-r, r), pt], QPointF(pt.x, pt.y), r)
        if lastpt != path.path.seg_start():
            owner.addRapidLine(pen, lastpt, path.path.seg_start())
        return path.path.seg_end()
    def pen2brush(self, owner, path, pen):
        if not isinstance(pen, QPen):
            pen2, slow = pen(path, owner.scalingFactor())
        else:
            pen2 = pen
        return QBrush(pen2.color())
    def addToolpaths(self, owner, pen, path, stage, operation):
        if isinstance(path, toolpath.Toolpaths):
            for tp in path.toolpaths:
                self.addToolpaths(owner, pen, tp, stage, operation)
            return
        path = path.transformed()
        self.addToolpathsTransformed(owner, pen, path, stage, operation)
    def addToolpathsTransformed(self, owner, pen, path, stage, operation):
        if isinstance(path, toolpath.Toolpaths):
            for tp in path.toolpaths:
                self.addToolpathsTransformed(owner, pen, tp, stage, operation)
            return
        if stage == 1:
            t = time.time()
            # print ("Before buffer")
            #print ("->", len(outlines))
            outlines = getattr(path, 'rendered_outlines', None)
            if outlines is None:
                path.rendered_outlines = outlines = path.render_as_outlines()
            for o in outlines:
                owner.addPolygons(lambda: self.pen2brush(owner, path, pen), outlines, GeometrySettings.simplify_arcs)
            # print ("After buffer", time.time() - t)
            return
        if GeometrySettings.simplify_arcs:
            path = path.lines_to_arcs()
        if GeometrySettings.simplify_lines:
            path = path.optimize_lines()
        owner.addLines(pen, path.path.nodes, path.path.closed, GeometrySettings.simplify_arcs)

class LineDrawingOp(object):
    def __init__(self, pen, path, bounds, darken):
        self.pen = pen
        self.path = path
        self.bounds = bounds
        self.darken = darken
    def paint(self, qp, transform, drawingArea, is_draft, scale):
        bounds = transform.mapRect(self.bounds)
        if bounds.intersects(drawingArea):
            # Skip all the thick lines when drawing during an interactive
            # operation like panning and zooming
            pen = self.pen
            if not isinstance(pen, QPen):
                pen, is_slow = pen(self.path, scale)
            else:
                is_slow = pen.widthF() and not isinstance(self.path, QPointF) and self.path.elementCount() > 1000
            if is_draft and is_slow:
                return
            qp.setPen(pen)
            if self.darken:
                qp.setCompositionMode(QPainter.CompositionMode_Darken)
            else:
                qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
            # Do not anti-alias very long segments
            if is_slow:
                qp.setRenderHint(QPainter.Antialiasing, False)
            if isinstance(self.path, QPointF):
                qp.drawPoint(self.path)
            else:
                qp.drawPath(self.path)
            if is_slow:
                qp.setRenderHint(QPainter.Antialiasing, True)
            qp.setCompositionMode(QPainter.CompositionMode_SourceOver)

class FillDrawingOp(object):
    def __init__(self, brush, path, bounds, darken):
        self.brush = brush
        self.path = path
        self.bounds = bounds
        self.darken = darken
    def paint(self, qp, transform, drawingArea, is_draft, scale):
        if self.darken:
            qp.setCompositionMode(QPainter.CompositionMode_Darken)
        else:
            qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
        bounds = transform.mapRect(self.bounds)
        if bounds.intersects(drawingArea):
            if isinstance(self.brush, QBrush):
                qp.fillPath(self.path, self.brush)
            else:
                qp.fillPath(self.path, self.brush())

class ScaledFillDrawingOp(object):
    def __init__(self, brush, path, bounds, origin, limit):
        self.brush = brush
        self.path = path
        self.bounds = bounds
        self.origin = origin
        self.limit = limit
    def paint(self, qp, transform, drawingArea, is_draft, scale):
        if scale < self.limit:
            return
        qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
        transform2 = QTransform(transform).translate(self.origin.x(), self.origin.y()).scale(1.0 / scale, 1.0 / scale).translate(-self.origin.x(), -self.origin.y())
        qp.setTransform(transform2)
        bounds = transform2.mapRect(self.bounds)
        if bounds.intersects(drawingArea):
            if isinstance(self.brush, QBrush):
                qp.fillPath(self.path, self.brush)
            else:
                qp.fillPath(self.path, self.brush())
        qp.setTransform(transform)

class PathViewer(QWidget):
    coordsUpdated = pyqtSignal([float, float])
    coordsInvalid = pyqtSignal([])

    def __init__(self, renderer):
        QWidget.__init__(self)
        self.renderer = renderer
        self.click_data = None
        self.draft_time = None
        self.majorUpdate()
        self.startTimer(50)
    def majorUpdate(self, reset_zoom=True):
        with Spinner():
            if reset_zoom:
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
    def addFilledPath(self, brush, polylines, darken=True):
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        for polyline in polylines:
            path.moveTo(polyline[0].x, polyline[0].y)
            for point in polyline[1:]:
                if point.is_point():
                    path.lineTo(point.x, point.y)
                else:
                    arc = point
                    path.arcTo(QRectF(arc.c.cx - arc.c.r, arc.c.cy - arc.c.r, 2 * arc.c.r, 2 * arc.c.r), -arc.sstart * 180 / pi, -arc.sspan * 180 / pi)
            path.closeSubpath()
        self.drawingOps.append(FillDrawingOp(brush, path, path.boundingRect(), darken))
    def addScaledPolygon(self, brush, polyline, origin, limit):
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        path.moveTo(polyline[0].x, polyline[0].y)
        for point in polyline[1:]:
            if point.is_point():
                path.lineTo(point.x, point.y)
            else:
                arc = point
                path.arcTo(QRectF(arc.c.cx - arc.c.r, arc.c.cy - arc.c.r, 2 * arc.c.r, 2 * arc.c.r), -arc.sstart * 180 / pi, -arc.sspan * 180 / pi)
        path.closeSubpath()
        self.drawingOps.append(ScaledFillDrawingOp(brush, path, path.boundingRect(), origin, limit))
    def addPath(self, pen, *polylines, darken=True):
        for polyline in polylines:
            path = QPainterPath()
            if len(polyline) == 1:
                x, y = polyline[0].x, polyline[0].y
                self.drawingOps.append(LineDrawingOp(pen, QPointF(x, y), QRectF(x, y, 1, 1), darken))
            else:
                addPolylineToPath(path, polyline)
                if polyline[0] == polyline[-1].seg_end():
                    self.drawingOps.append(LineDrawingOp(pen, path, path.boundingRect(), darken))
                else:
                    self.drawingOps.append(LineDrawingOp(pen, path, path.boundingRect().marginsAdded(QMarginsF(1, 1, 1, 1)), darken))

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

    def drawingTransform(self):
        scale = self.scalingFactor()
        zeropt = self.project(QPointF())
        return QTransform().translate(zeropt.x(), zeropt.y()).scale(scale, -scale)

    def paintDrawingOps(self, e, qp):
        scale = self.scalingFactor()
        transform = self.drawingTransform()
        qp.setTransform(transform)
        drawingArea = QRectF(self.rect())
        for op in self.drawingOps:
            op.paint(qp, transform, drawingArea, self.isDraft(), scale)
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

    def addLines(self, pen, points, closed, has_arcs=False, darken=True):
        if has_arcs and interpolate_all_arcs:
            points = CircleFitter.interpolate_arcs(points, gcodegen.debug_simplify_arcs, self.scalingFactor())
        if closed and points[0] != points[-1].seg_end():
            self.addPath(pen, points + points[0:1], darken=darken)
        else:
            self.addPath(pen, points, darken=darken)

    def addRapidLine(self, pen, sp, ep):
        if draw_arrows_for_rapids:
            dlen = sp.dist(ep)
            if not dlen:
                return
            r = 10
            midp = weighted(sp, ep, 0.48)
            angle = atan2(ep.y - sp.y, ep.x - sp.x)
            dangle = 28 * pi / 32
            tip = PathPoint(midp.x + r * cos(angle), midp.y + r * sin(angle))
            m1 = PathPoint(midp.x + r * cos(angle - dangle), midp.y + r * sin(angle - dangle))
            m2 = PathPoint(midp.x + r * cos(angle + dangle), midp.y + r * sin(angle + dangle))
            self.addScaledPolygon(QBrush(pen.color()), [tip, m1, m2, tip], QPointF(midp.x, midp.y), 4 * r / dlen)
        self.addLines(pen, [sp, ep], False, darken=False)

    def addPolygons(self, brush, polygons, has_arcs=False, darken=True):
        if has_arcs:
            polygons = [CircleFitter.interpolate_arcs(points, gcodegen.debug_simplify_arcs, self.scalingFactor()) for points in polygons]
        self.addFilledPath(brush, polygons, darken=darken)

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
            with Spinner():
                self.repaint()
        self.updateCursor()

    def mouseMoveEvent(self, e):
        if self.click_data:
            self.processMove(e)
        p = self.unproject(e.localPos())
        self.emitCoordsUpdated(p)
    def emitCoordsUpdated(self, p):
        self.coordsUpdated.emit(p.x(), p.y())

    def enterEvent(self, e):
        p = self.unproject(e.localPos())
        self.coordsUpdated.emit(p.x(), p.y())
    def leaveEvent(self, e):
        self.coordsInvalid.emit()

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
        with Spinner():
            self.repaint()

    def timerEvent(self, e):
        if self.draft_time is not None and time.time() > self.draft_time:
            self.draft_time = None
            with Spinner():
                self.repaint()

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
        app.processEvents()

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

