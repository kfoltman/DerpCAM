from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from process import *
from geom import *
from gcodegen import *
import sys
import time

class PathViewer(QWidget):
   def __init__(self, operations):
      QWidget.__init__(self)
      self.operations = operations
      sx, sy, ex, ey = self.bounds()
      self.zero = QPointF(0, 0)
      self.zoom_level = 0
      self.click_data = None
      self.draft_time = None
      if ex > sx and ey > sy:
         self.zero = QPointF(0.5 * (sx + ex), 0.5 * (sy + ey))
         self.scale = min(self.size().width() / (ex - sx), self.size().height() / (ey - sy))
      self.renderDrawing()
      self.startTimer(50)
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

   def toolPen(self, path, alpha=100):
      pen = QPen(QColor(192, 192, 192, alpha), path.tool.diameter)
      pen.setCapStyle(Qt.RoundCap)
      pen.setJoinStyle(Qt.RoundJoin)
      return pen

   def addToolpaths(self, pen, path, stage):
      if isinstance(path, Toolpaths):
         for tp in path.toolpaths:
            self.addToolpaths(pen, tp, stage)
         return
      path = path.transformed()
      if simplify_arcs:
         path = path.lines_to_arcs()
         if stage == 1:
            pen = self.toolPen(path)
         else:
            pen = QPen(QColor(160, 160, 160) if path.is_tab else QColor(0, 128, 128), 0)
         self.addLines(pen, path.points, path.closed, True)
      else:
         self.addLines(pen, path.points, path.closed)

   def addRapids(self, pen, path, lastpt):
      if isinstance(path, Toolpaths):
         for tp in path.toolpaths:
            lastpt = self.addRapids(pen, tp, lastpt)
         return lastpt
      if path.helical_entry:
         self.addLines(pen, circle(*path.helical_entry) + path.points[0:1], False)
      self.addLines(pen, [lastpt, path.points[0]], False)
      return path.points[0 if path.closed else -1]
      
   def renderDrawing(self):
      self.drawingOps = []
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
               if op.props.tab_depth is not None and op.props.tab_depth < op.props.start_depth:
                  for toolpath in op.flattened:
                     if stage == 1:
                        # Use the alpha for the tab depth
                        pen = self.toolPen(toolpath, alpha=tab_alpha)
                     if stage == 2:
                        pen = QPen(QColor(0, 0, 0, tab_alpha), 0)
                     self.addToolpaths(pen, toolpath, stage)
               for toolpath in op.tabbed:
                  if stage == 1:
                     # Draw a cut line of the diameter of the cut
                     alpha = tab_alpha if toolpath.is_tab else 100
                     pen = self.toolPen(toolpath, alpha=tab_alpha)
                  else:
                     if toolpath.is_tab:
                        pen = QPen(QColor(0, 0, 0, tab_alpha), 0)
                     else:
                        pen = QPen(QColor(0, 0, 0, 100), 0)
                  #self.drawToolpaths(qp, self.paths, stage)
                  self.addToolpaths(pen, toolpath, stage)
      # Pink tint for cuts that are not tabs
      for op in self.operations.operations:
         pen = QPen(QColor(128, 0, 128, 32), op.tool.diameter)
         pen.setCapStyle(Qt.RoundCap)
         pen.setJoinStyle(Qt.RoundJoin)
         if op.paths and op.tabs and op.tabs.tabs:
            for subpath in op.tabbed:
               if not subpath.is_tab:
                  self.addLines(pen, subpath.transformed().points, False)
      # Red rapid moves
      pen = QPen(QColor(255, 0, 0), 0)
      lastpt = (0, 0)
      for op in self.operations.operations:
         if op.paths:
            lastpt = self.addRapids(pen, op.paths, lastpt)
      # Original shapes (before all the offsetting)
      penOutside = QPen(QColor(0, 0, 255), 0)
      penIslands = QPen(QColor(0, 255, 0), 0)
      for op in self.operations.operations:
         p = op.shape.boundary
         self.addLines(penOutside, p, op.shape.closed)
         for p in op.shape.islands:
            self.addLines(penIslands, p, True)

   def isDraft(self):
      return self.click_data or self.draft_time

   def paintEvent(self, e):
      qp = QPainter()
      qp.begin(self)
      qp.setRenderHint(1, True)
      qp.setRenderHint(8, True)

      size = self.size()
      zeropt = self.project(QPointF())
      qp.setPen(QPen(QColor(128, 128, 128)))
      qp.drawLine(QLineF(0.0, zeropt.y(), size.width(), zeropt.y()))
      qp.drawLine(QLineF(zeropt.x(), 0.0, zeropt.x(), size.height()))
      scale = self.scalingFactor()
      transform = QTransform().translate(zeropt.x(), zeropt.y()).scale(scale, -scale)
      qp.setTransform(transform)
      drawingArea = QRectF(self.rect())
      for pen, path, bbox in self.drawingOps:
         bounds = transform.mapRect(bbox)
         if bounds.intersects(drawingArea):
            # Skip all the thick lines when drawing during an interactive
            # operation like panning and zooming
            if self.isDraft() and pen.widthF():
               continue
            qp.setPen(pen)
            # Do not anti-alias very long segments
            is_slow = pen.widthF() and path.elementCount() > 1000
            if is_slow:
               qp.setRenderHint(1, False)
               qp.setRenderHint(8, False)
            qp.drawPath(path)
            if is_slow:
               qp.setRenderHint(1, True)
               qp.setRenderHint(8, True)
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
         points = CircleFitter.interpolate_arcs(points, debug_simplify_arcs, self.scalingFactor())
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

   def wheelEvent(self, e):
      delta = e.angleDelta().y()
      if delta != 0:
         self.draft_time = time.time() + 0.5
      if delta > 0:
         self.adjustScale(e.position(), 1)
      if delta < 0:
         self.adjustScale(e.position(), -1)
      if delta != 0:
         # do it again to account for repainting time
         self.draft_time = time.time() + 0.5
      if self.click_data:
         self.click_data = (self.zero, e.position())

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
   w.viewer = PathViewer(operations)
   w.viewer.initUI()
   w.setCentralWidget(w.viewer)
   w.show()
   retcode = app.exec_()
   w = None
   app = None
   return retcode

