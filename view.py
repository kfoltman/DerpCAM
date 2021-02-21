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
         self.drawingOps.append((pen, path, path.boundingRect()))

   def addToolpaths(self, pen, path, stage):
      if isinstance(path, Toolpaths):
         for tp in path.toolpaths:
            self.addToolpaths(pen, tp, stage)
         return
      if simplify_arcs:
         if stage == 1:
            pen = QPen(QColor(192, 192, 192, 100), path.tool.diameter)
         else:
            pen = QPen(QColor(0, 128, 128), 0)
         self.addLines(pen, CircleFitter.simplify(path.points), path.closed, True)
      else:
         self.addLines(pen, path.points, path.closed)

   def addRapids(self, pen, path, lastpt):
      if isinstance(path, Toolpaths):
         for tp in path.toolpaths:
            lastpt = self.addRapids(pen, tp, lastpt)
         return lastpt
      self.addLines(pen, [lastpt, path.points[0]], False)
      return path.points[0 if path.closed else -1]
      
   def renderDrawing(self):
      self.drawingOps = []
      for op in self.operations.operations:
         if op.paths:
            for stage in (1, 2):
               for toolpath in op.flattened:
                  if stage == 1:
                     pen = QPen(QColor(192, 192, 192, 100), toolpath.tool.diameter)
                     pen.setCapStyle(Qt.RoundCap)
                     pen.setJoinStyle(Qt.RoundJoin)
                  else:
                     pen = QPen(QColor(0, 0, 0), 0)
                  #self.drawToolpaths(qp, self.paths, stage)
                  self.addToolpaths(pen, op.paths, stage)
      pen = QPen(QColor(128, 0, 128, 32), toolpath.tool.diameter)
      pen.setCapStyle(Qt.RoundCap)
      pen.setJoinStyle(Qt.RoundJoin)
      for op in self.operations.operations:
         if op.paths and op.tabs and op.tabs.tabs:
            for toolpath in op.flattened:
               subpaths = toolpath.eliminate_tabs2(op.tabs)
               for is_tab, subpath in subpaths:
                  if not is_tab:
                     self.addLines(pen, subpath, False)
      pen = QPen(QColor(255, 0, 0), 0)
      lastpt = (0, 0)
      for op in self.operations.operations:
         if op.paths:
            lastpt = self.addRapids(pen, op.paths, lastpt)
      penOutside = QPen(QColor(0, 0, 255), 0)
      penIslands = QPen(QColor(0, 255, 0), 0)
      for op in self.operations.operations:
         p = op.shape.boundary
         self.addLines(penOutside, p, op.shape.closed)
         for p in op.shape.islands:
            self.addLines(penIslands, p, True)

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
            if self.click_data or self.draft_time:
               qp.setPen(QPen(pen.color(), 0))
            else:
               qp.setPen(pen)
            qp.drawPath(path)
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

#shape1 = Shape.circle(-20, -20, d = 50)
#shape2 = Shape.circle(20, -20, d = 50)
#shape1 = Shape.rectangle((80, 20), (120, 180))
#shape3 = Shape.rectangle((-20, -20), (20, 20))
#shape = Shape.union(Shape.union(shape1, shape3), shape2)
#shape = Shape.union(shape1, shape2)
#shape = Shape.rectangle((0, 0), (20, 20))
#shape = Shape.circle(0, 0, d = 16)
#shape = Shape.rectangle(0, 0, 160, 40)

#tool = Tool(diameter = 3, hfeed = 500, vfeed = 100, maxdoc = 0.2)
#tool = Tool(diameter = 3, hfeed = 1500, vfeed = 1000, maxdoc = 1)
#contour = shape.contour(tool, outside=True)
#contour = shape.pocket_contour(tool)

# tabs = Tabs([]) #contour.autotabs(4)
# gcode = Gcode()
# gcode.reset()
# pathToGcode(gcode, path=contour, safe_z=5, start_depth=0, end_depth=-15, doc=1, tabs=tabs, tab_depth=-6)
# gcode.rapid(z=5)
# gcode.rapid(x=0, y=0)
# gcode.finish()
# for line in gcode.gcode:
#    print (line)

#def main():
#   viewer_modal(shape, contour, tabs)
    
#sys.exit(main())
