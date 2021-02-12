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
      if ex > sx and ey > sy:
         self.zero = QPointF(0.5 * (sx + ex), 0.5 * (sy + ey))
         self.scale = min(self.size().width() / (ex - sx), self.size().height() / (ey - sy))
   def bounds(self):
      b = None
      for op in self.operations:
         opb = op.shape.bounds
         if op.paths:
            opb = max_bounds(opb, op.paths.bounds)
         if b is None:
            b = opb
         else:
            b = max_bounds(b, opb)
      return b
   def resizeEvent(self, e):
      sx, sy, ex, ey = self.bounds()
      self.cx = self.size().width() / 2
      self.cy = self.size().height() / 2
      self.scale = min(self.size().width() / (ex - sx), self.size().height() / (ey - sy))
      self.repaint()
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

   def drawToolpaths(self, qp, path, stage):
      if isinstance(path, Toolpaths):
         for tp in path.toolpaths:
            self.drawToolpaths(qp, tp, stage)
         return
      if stage == 1:
         pen = QPen(QColor(192, 192, 192, 100), path.tool.diameter * self.scalingFactor())
         pen.setCapStyle(Qt.RoundCap)
         pen.setJoinStyle(Qt.RoundJoin)
      else:
         pen = QPen(QColor(0, 0, 0), 0)
      qp.setPen(pen)
      self.drawLines(qp, path.points, path.closed)

   def drawRapids(self, qp, path, lastpt):
      if isinstance(path, Toolpaths):
         for tp in path.toolpaths:
            lastpt = self.drawRapids(qp, tp, lastpt)
         return lastpt
      self.drawLines(qp, [lastpt, path.points[0]], False)
      return path.points[0 if path.closed else -1]
      
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

      for op in self.operations:
         if op.paths:
            for toolpath in op.flattened:
               for stage in (1, 2):
                  #self.drawToolpaths(qp, self.paths, stage)
                  if stage == 1:
                     pen = QPen(QColor(192, 192, 192, 100), toolpath.tool.diameter * self.scalingFactor())
                     pen.setCapStyle(Qt.RoundCap)
                     pen.setJoinStyle(Qt.RoundJoin)
                  else:
                     pen = QPen(QColor(0, 0, 0), 0)
                  qp.setPen(pen)
                  self.drawToolpaths(qp, op.paths, stage)
      for op in self.operations:
         if op.paths and op.tabs and op.tabs.tabs:
            for toolpath in op.flattened:
               subpaths = toolpath.eliminate_tabs2(op.tabs)
               pen = QPen(QColor(128, 0, 128, 32), toolpath.tool.diameter * self.scalingFactor())
               pen.setCapStyle(Qt.RoundCap)
               pen.setJoinStyle(Qt.RoundJoin)
               qp.setPen(pen)
               for is_tab, subpath in subpaths:
                  if not is_tab:
                     self.drawLines(qp, subpath, False)
      lastpt = (0, 0)
      for op in self.operations:
         if op.paths:
            pen = QPen(QColor(255, 0, 0))
            qp.setPen(pen)
            lastpt = self.drawRapids(qp, op.paths, lastpt)
      for op in self.operations:
         pen = QPen(QColor(0, 0, 255))
         qp.setPen(pen)
         p = op.shape.boundary
         self.drawLines(qp, p, op.shape.closed)
         pen = QPen(QColor(0, 255, 0))
         qp.setPen(pen)
         for p in op.shape.islands:
            self.drawLines(qp, p, True)

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
   
   def drawLines(self, painter, points, closed):
      pts = [self.project(QPointF(p[0], p[1])) for p in points]

      #scale = self.scalingFactor()
      #zx, zy = self.zero.x(), self.zero.y()
      #pts = [QPointF((p[0] - zx) * scale + self.cx, (zy - p[1]) * scale + self.cy) for p in points]
      if closed:
         pts.append(pts[0])
      painter.drawPolyline(*pts)

   def mousePressEvent(self, e):
      b = e.button()
      if e.button() == Qt.RightButton:
         self.click_data = (self.zero, e.localPos())
      self.updateCursor()
         
   def mouseReleaseEvent(self, e):
      if self.click_data:
         self.processMove(e)
         self.click_data = None
      self.updateCursor()

   def mouseMoveEvent(self, e):
      if self.click_data:
         self.processMove(e)

   def wheelEvent(self, e):
      delta = e.angleDelta().y()
      if delta > 0:
         self.adjustScale(e.position(), 1)
      if delta < 0:
         self.adjustScale(e.position(), -1)
      if self.click_data:
         self.click_data = (self.zero, e.position())

   def processMove(self, e):
      orig_zero, orig_pos = self.click_data
      transpose = (e.localPos() - orig_pos) / self.scalingFactor()
      self.zero = orig_zero - QPointF(transpose.x(), -transpose.y())
      self.repaint()

   def updateCursor(self):
      if self.click_data:
         self.setCursor(Qt.OpenHandCursor)
      else:
         self.setCursor(Qt.CrossCursor)

def viewer_modal(operations):
   app = QApplication(sys.argv)
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
