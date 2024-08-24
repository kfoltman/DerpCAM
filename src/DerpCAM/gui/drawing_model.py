from .common_model import *
import pyclipr

class DrawingItemTreeItem(CAMTreeItem):
    defaultGrayPen = QPen(QColor(0, 0, 0, 64), 0)
    defaultDrawingPen = QPen(QColor(0, 0, 0, 255), 0)
    selectedItemDrawingPen = QPen(QColor(0, 64, 128, 255), 2)
    selectedItemDrawingPen2 = QPen(QColor(0, 64, 128, 255), 2)
    next_drawing_item_id = 1
    def __init__(self, document):
        CAMTreeItem.__init__(self, document)
        self.shape_id = DrawingItemTreeItem.next_drawing_item_id
        DrawingItemTreeItem.next_drawing_item_id += 1
    def __hash__(self):
        return hash(self.shape_id)
    def selectedItemPenFunc(self, item, scale):
        # avoid draft behaviour of thick lines
        return QPen(self.selectedItemDrawingPen.color(), self.selectedItemDrawingPen.widthF() / scale), False
    def selectedItemPen2Func(self, item, scale):
        return QPen(self.selectedItemDrawingPen2.color(), self.selectedItemDrawingPen2.widthF() / scale), False
    def penForPath(self, path, editor):
        if editor is not None:
            pen = editor.penForPath(self, path)
            if pen is not None:
                return pen
        return lambda item, scale: self.selectedItemPenFunc(item, scale) if self.untransformed in path.selection else (self.defaultDrawingPen, False)
    def store(self):
        return { '_type' : type(self).__name__, 'shape_id' : self.shape_id }
    @classmethod
    def load(klass, document, dump):
        rtype = dump['_type']
        if rtype == 'DrawingPolyline' or rtype == 'DrawingPolylineTreeItem':
            points = [geom.PathNode.from_tuple(i) for i in dump['points']]
            item = DrawingPolylineTreeItem(document, points, dump.get('closed', True))
        elif rtype == 'DrawingCircle' or rtype == 'DrawingCircleTreeItem':
            item = DrawingCircleTreeItem(document, geom.PathPoint(dump['cx'], dump['cy']), dump['r'])
        elif rtype == 'DrawingTextTreeItem':
            item = DrawingTextTreeItem(document, geom.PathPoint(dump['x'], dump['y']), dump.get('target_width', None),
                DrawingTextStyle(dump['height'], dump['width'], dump['halign'], dump['valign'], dump['angle'], dump['font'], dump.get('spacing', 0)), dump['text'])
        else:
            raise ValueError("Unexpected type: %s" % rtype)
        item.shape_id = dump['shape_id']
        klass.next_drawing_item_id = max(item.shape_id + 1, klass.next_drawing_item_id)
        return item
    def onPropertyValueSet(self, name):
        self.emitPropertyChanged(name)
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(self.textDescription())
        return CAMTreeItem.data(self, role)
    def invalidatedObjects(self, aspect):
        if aspect == InvalidateAspect.CAM:
            return set([self] + self.document.allOperations(lambda item: item.usesShape(self.shape_id)))
        # Settings of operations are not affected and don't need to be refreshed
        return set([self])
    def reset_untransformed(self):
        self.untransformed = self
        return self
    def createPaths(self):
        pass

class DrawingCircleTreeItem(DrawingItemTreeItem):
    prop_x = FloatDistEditableProperty("Centre X", "x", Format.coord, unit="mm", allow_none=False)
    prop_y = FloatDistEditableProperty("Centre Y", "y", Format.coord, unit="mm", allow_none=False)
    prop_dia = FloatDistEditableProperty("Diameter", "diameter", Format.coord, unit="mm", min=0, allow_none=False)
    prop_radius = FloatDistEditableProperty("Radius", "radius", Format.coord, unit="mm", min=0, allow_none=False)
    def __init__(self, document, centre, r, untransformed = None):
        DrawingItemTreeItem.__init__(self, document)
        self.centre = centre
        self.r = r
        self.calcBounds()
        self.untransformed = untransformed if untransformed is not None else self
    @classmethod
    def properties(self):
        return [self.prop_x, self.prop_y, self.prop_dia, self.prop_radius]
    def getPropertyValue(self, name):
        if name == 'x':
            return self.centre.x
        elif name == 'y':
            return self.centre.y
        elif name == 'radius':
            return self.r
        elif name == 'diameter':
            return 2 * self.r
        else:
            assert False, "Unknown property: " + name
    def setPropertyValue(self, name, value):
        if name == 'x':
            self.centre = geom.PathPoint(value, self.centre.y)
        elif name == 'y':
            self.centre = geom.PathPoint(self.centre.x, value)
        elif name == 'radius':
            self.r = value
        elif name == 'diameter':
            self.r = value / 2.0
        else:
            assert False, "Unknown property: " + name
        self.emitPropertyChanged(name)
    def calcBounds(self):
        self.bounds = (self.centre.x - self.r, self.centre.y - self.r,
            self.centre.x + self.r, self.centre.y + self.r)
    def distanceTo(self, pt):
        return abs(geom.dist(self.centre, pt) - self.r)
    def renderTo(self, path, editor):
        path.addLines(self.penForPath(path, editor), geom.circle(self.centre.x, self.centre.y, self.r), True)
    def label(self):
        return "Circle%d" % self.shape_id
    def textDescription(self):
        return self.label() + (f" {Format.point(self.centre)} \u2300{Format.coord(2 * self.r)}")
    def toShape(self):
        return shapes.Shape.circle(self.centre.x, self.centre.y, self.r)
    def translated(self, dx, dy):
        cti = DrawingCircleTreeItem(self.document, self.centre.translated(dx, dy), self.r, self.untransformed)
        cti.shape_id = self.shape_id
        return cti
    def rotated(self, ox, oy, rotation):
        cti = DrawingCircleTreeItem(self.document, self.centre.rotated(ox, oy, rotation), self.r, self.untransformed)
        cti.shape_id = self.shape_id
        return cti
    def scaled(self, cx, cy, scale):
        return DrawingCircleTreeItem(self.document, self.centre.scaled(cx, cy, scale), self.r * scale, self.untransformed)
    def translate(self, dx, dy):
        old = self.centre
        self.centre = self.centre.translated(dx, dy)
        return old
    def restore_translate(self, old):
        self.centre = old
    def rotate(self, ox, oy, rotation):
        old = self.centre
        self.centre = self.centre.rotated(ox, oy, rotation)
        return old
    def restore_rotate(self, old):
        self.centre = old
    def store(self):
        res = DrawingItemTreeItem.store(self)
        res['cx'] = self.centre.x
        res['cy'] = self.centre.y
        res['r'] = self.r
        return res
    def startEndPos(self):
        p = geom.PathPoint(self.centre.x + self.r, self.centre.y)
        return (p, p)

class DrawingPolylineTreeItem(DrawingItemTreeItem):
    prop_points = SetEditableProperty("Points", "points", format_func=lambda value: f"{len(value)} points - double-click to edit", edit_func=lambda item: item.editPoints())

    def __init__(self, document, points, closed, untransformed=None, src_name=None):
        DrawingItemTreeItem.__init__(self, document)
        self.points = points
        self.closed = closed
        self.untransformed = untransformed if untransformed is not None else self
        self.src_name = src_name
        self.calcBounds()
    def store(self):
        res = DrawingItemTreeItem.store(self)
        res['points'] = [ i.as_tuple() for i in self.points ]
        res['closed'] = self.closed
        return res
    @classmethod
    def properties(self):
        return [self.prop_points]
    def editPoints(self):
        self.document.polylineEditRequested.emit(self)
    def distanceTo(self, pt):
        if not self.points:
            return None
        path = geom.Path(self.points, self.closed)
        closest, mindist = path.closest_point(pt)
        return mindist
    def translate(self, dx, dy):
        old = self.points
        self.points = [p.translated(dx, dy) for p in self.points]
        return old
    def restore_translate(self, points):
        self.points = points
    def rotate(self, ox, oy, rotation):
        old = self.points
        self.points = [p.rotated(ox, oy, rotation) for p in self.points]
        return old
    def restore_rotate(self, points):
        self.points = points
    def translated(self, dx, dy):
        pti = DrawingPolylineTreeItem(self.document, [p.translated(dx, dy) for p in self.points], self.closed, self.untransformed)
        pti.shape_id = self.shape_id
        return pti
    def rotated(self, ox, oy, rotation):
        pti = DrawingPolylineTreeItem(self.document, [p.rotated(ox, oy, rotation) for p in self.points], self.closed, self.untransformed)
        pti.shape_id = self.shape_id
        return pti
    def scaled(self, cx, cy, scale):
        return DrawingPolylineTreeItem(self.document, [p.scaled(cx, cy, scale) for p in self.points], self.closed, self.untransformed)
    def renderTo(self, path, editor):
        if not self.points:
            return
        path.addLines(self.penForPath(path, editor), geom.CircleFitter.interpolate_arcs(self.points, False, path.scalingFactor()), self.closed)
    def calcBounds(self):
        if self.points:
            self.bounds = geom.Path(self.points, self.closed).bounds()
        else:
            self.bounds = None
    def label(self):
        if geom.Path(self.points, self.closed).is_aligned_rectangle():
            return "Rectangle%d" % self.shape_id
        if len(self.points) == 2:
            if self.points[1].is_point():
                return "Line%d" % self.shape_id
            else:
                return "Arc%d" % self.shape_id
        if self.src_name is not None:
            return self.src_name + str(self.shape_id)
        return "Polyline%d" % self.shape_id
    def textDescription(self):
        if len(self.points) == 2:
            if self.points[1].is_point():
                return self.label() + (f"{Format.point(self.points[0], brief=True)}-{Format.point(self.points[1], brief=True)}")
            else:
                assert self.points[1].is_arc()
                arc = self.points[1]
                c = arc.c
                return self.label() + "(X=%s, Y=%s, R=%s, start=%0.2f\u00b0, span=%0.2f\u00b0" % (Format.coord(c.cx, brief=True), Format.coord(c.cy, brief=True), Format.coord(c.r, brief=True), arc.sstart * 180 / math.pi, arc.sspan * 180 / math.pi)
        if self.bounds is None:
            return self.label() + " (empty)"
        return self.label() + f"{Format.point_tuple(self.bounds[:2], brief=True)}-{Format.point_tuple(self.bounds[2:], brief=True)}"
    def toShape(self):
        return shapes.Shape(geom.CircleFitter.interpolate_arcs(self.points, False, 1.0), self.closed)
    @staticmethod
    def ellipse(document, centre, major, ratio, start_param, end_param):
        zero = geom.PathPoint(0, 0)
        if end_param < start_param:
            end_param += 2 * math.pi
        major_r = zero.dist(major)
        major_angle = major.angle_to(zero)
        n = int((end_param - start_param) * major_r * geom.GeometrySettings.RESOLUTION)
        points = []
        limit = n + 1
        closed = False
        if end_param - start_param >= 2 * math.pi - 0.001:
            limit = n
            closed = True
        for i in range(n + 1):
            angle = start_param + (end_param - start_param) * i / n
            x1 = major_r * math.cos(angle)
            y1 = major_r * ratio * math.sin(angle)
            x2 = centre.x + x1 * math.cos(major_angle) - y1 * math.sin(major_angle)
            y2 = centre.y + y1 * math.cos(major_angle) + x1 * math.sin(major_angle)
            points.append(geom.PathPoint(x2, y2))
        return DrawingPolylineTreeItem(document, points, closed, src_name="Ellipse")
    def startEndPos(self):
        if self.closed:
            return (self.points[0], self.points[0])
        else:
            return (self.points[0].seg_start(), self.points[-1].seg_end())
        
class DrawingTextStyleHAlign(EnumClass):
    LEFT = 0
    CENTRE = 1
    RIGHT = 2
    ALIGNED = 3
    MIDDLE = 4
    FIT = 5
    descriptions = [
        (LEFT, "Left"),
        (CENTRE, "Centre"),
        (RIGHT, "Right"),
        (ALIGNED, "Aligned"),
        (MIDDLE, "Middle"),
        (FIT, "Fit"),
    ]

class DrawingTextStyleVAlign(EnumClass):
    BASELINE = 0
    BOTTOM = 1
    MIDDLE = 2
    TOP = 3
    descriptions = [
        (BASELINE, "Baseline"),
        (BOTTOM, "Bottom"),
        (MIDDLE, "Middle"),
        (TOP, "Top"),
    ]

class DrawingTextStyle(object):
    def __init__(self, height, width, halign, valign, angle, font_name, spacing):
        self.height = height
        self.width = width
        self.halign = halign
        self.valign = valign
        self.angle = angle
        self.font_name = font_name
        self.spacing = spacing
    def clone(self):
        return DrawingTextStyle(self.height, self.width, self.halign, self.valign, self.angle, self.font_name, self.spacing)

class DrawingTextTreeItem(DrawingItemTreeItem):
    prop_x = FloatDistEditableProperty("Insert X", "x", Format.coord, unit="mm", allow_none=False)
    prop_y = FloatDistEditableProperty("Insert Y", "y", Format.coord, unit="mm", allow_none=False)
    prop_text = StringEditableProperty("Text", "text", False)
    prop_font = FontEditableProperty("Font face", "font")
    prop_height = FloatDistEditableProperty("Font size", "height", Format.coord, min=1, unit="mm", allow_none=False)
    prop_width = FloatDistEditableProperty("Stretch", "width", Format.percent, min=10, unit="%", allow_none=False)
    prop_spacing = FloatDistEditableProperty("Letter spacing", "spacing", Format.coord, min=0, max=100, allow_none=False)
    prop_angle = FloatDistEditableProperty("Angle", "angle", Format.angle, min=-360, max=360, unit='\u00b0', allow_none=False)
    prop_halign = EnumEditableProperty("Horizontal align", "halign", DrawingTextStyleHAlign, allow_none=False)
    prop_valign = EnumEditableProperty("Vertical align", "valign", DrawingTextStyleVAlign, allow_none=False)
    prop_target_width = FloatDistEditableProperty("Target width", "target_width", Format.coord, unit="mm", allow_none=True, min=0)
    def __init__(self, document, origin, target_width, style, text, untransformed = None):
        DrawingItemTreeItem.__init__(self, document)
        self.untransformed = untransformed if untransformed is not None else self
        self.origin = origin
        self.target_width = target_width
        self.style = style
        self.text = text
        self.closed = True
        self.createPaths()
    def properties(self):
        return [ self.prop_x, self.prop_y, self.prop_text, self.prop_font, self.prop_height, self.prop_width, self.prop_angle, self.prop_spacing, self.prop_halign, self.prop_target_width, self.prop_valign ]
    def isPropertyValid(self, name):
        ha = DrawingTextStyleHAlign
        if name == 'valign':
            return self.style.halign in (ha.LEFT, ha.CENTRE, ha.RIGHT)
        if name == 'target_width':
            return self.style.halign in (ha.ALIGNED, ha.FIT)
        return True
    def store(self):
        return { '_type' : type(self).__name__, 'shape_id' : self.shape_id,
            'text' : self.text, 'x' : self.origin.x, 'y' : self.origin.y,
            'target_width' : self.target_width,
            'height' : self.style.height, 'width' : self.style.width,
            'halign' : self.style.halign, 'valign' : self.style.valign,
            'angle' : self.style.angle,
            'font' : self.style.font_name, 'spacing' : self.style.spacing}
    def getPropertyValue(self, name):
        if name == 'x':
            return self.origin.x
        elif name == 'y':
            return self.origin.y
        elif name == 'target_width':
            return self.target_width
        elif name == 'text':
            return self.text
        elif name == 'font':
            return self.style.font_name
        elif name == 'height':
            return self.style.height
        elif name == 'width':
            return self.style.width * 100
        elif name == 'angle':
            return self.style.angle
        elif name == 'spacing':
            return self.style.spacing
        elif name == 'halign':
            return self.style.halign
        elif name == 'valign':
            return self.style.valign
        else:
            assert False, "Unknown property: " + name
    def setPropertyValue(self, name, value):
        if name == 'x':
            self.origin = geom.PathPoint(value, self.origin.y)
        elif name == 'y':
            self.origin = geom.PathPoint(self.origin.x, value)
        elif name == 'target_width':
            self.target_width = value
        elif name == 'text':
            self.text = value
        elif name == 'font':
            self.style.font_name = value
        elif name == 'height':
            self.style.height = value
        elif name == 'width':
            self.style.width = value / 100
        elif name == 'angle':
            self.style.angle = value
        elif name == 'spacing':
            self.style.spacing = value
        elif name == 'halign':
            self.style.halign = value
        elif name == 'valign':
            self.style.valign = value
        else:
            assert False, "Unknown property: " + name
        self.createPaths()
        self.emitPropertyChanged(name)
    def translated(self, dx, dy):
        tti = DrawingTextTreeItem(self.document, self.origin.translated(dx, dy), self.target_width, self.style, self.text, self.untransformed)
        tti.shape_id = self.shape_id
        return tti
    def rotated(self, ox, oy, rotation):
        style = self.style.clone()
        style.angle += round(rotation * 180 / math.pi, 3)
        style.angle = style.angle % 360
        if style.angle > 180:
            style.angle -= 360
        tti = DrawingTextTreeItem(self.document, self.origin.rotated(ox, oy, rotation), self.target_width, style, self.text, self.untransformed)
        tti.shape_id = self.shape_id
        return tti
    def translate(self, dx, dy):
        old = self.origin
        self.origin = self.origin.translated(dx, dy)
        return old
    def restore_translate(self, old):
        self.origin = old
    def rotate(self, ox, oy, rotation):
        old = (self.origin, self.style)
        self.origin = self.origin.rotated(ox, oy, rotation)
        style = self.style.clone()
        style.angle += round(rotation * 180 / math.pi, 3)
        style.angle = style.angle % 360
        self.style = style
        return old
    def restore_rotate(self, old):
        self.origin = old[0]
        self.style = old[1]
    def toShape(self):
        res = []
        last_bounds = None
        if self.paths:
            for i, path in enumerate(sorted(self.paths, key=lambda path: path.bounds()[0])):
                path_bounds = path.bounds()
                if len(res) and geom.inside_bounds(path_bounds, last_bounds):
                    res[-1].add_island(path.nodes)
                else:
                    shape = shapes.Shape(path.nodes, path.closed)
                    last_bounds = path_bounds
                    res.append(shape)
        res = list(sorted(res, key=lambda item: item.bounds[0]))
        return res
    def renderTo(self, path, editor):
        for i in self.paths:
            path.addLines(self.penForPath(path, editor), i.nodes, i.closed)
    def distanceTo(self, pt):
        mindist = None
        for path in self.paths:
            closest, dist = path.closest_point(pt)
            if mindist is None or dist < mindist:
                mindist = dist
        return mindist
    def calcBounds(self):
        bounds = []
        for i in self.paths:
            xcoords = [p.x for p in i.nodes if p.is_point()]
            ycoords = [p.y for p in i.nodes if p.is_point()]
            bounds.append((min(xcoords), min(ycoords), max(xcoords), max(ycoords)))
        self.bounds = geom.max_bounds(*bounds)
    def label(self):
        return "Text%d" % self.shape_id
    def textDescription(self):
        return f"{self.label()}: {self.text}"
    def createPaths(self):
        scale = geom.GeometrySettings.RESOLUTION
        if self.style.height * scale > 100:
            scale = 100 / self.style.height
        if not isinstance(QCoreApplication.instance(), QGuiApplication):
            raise Exception("Use --allow-text for converting files using text objects")
        font = QFont(self.style.font_name, 1, 400, False)
        font.setPointSizeF(self.style.height * scale)
        font.setLetterSpacing(QFont.AbsoluteSpacing, self.style.spacing * scale)
        metrics = QFontMetrics(font)
        width = self.style.width
        angle = -self.style.angle
        twidth = metrics.horizontalAdvance(self.text) / scale * self.style.width
        x, y = self.origin.x, self.origin.y
        if self.style.halign == DrawingTextStyleHAlign.RIGHT:
            x -= twidth
        elif self.style.halign == DrawingTextStyleHAlign.CENTRE:
            x -= twidth / 2
        elif self.style.halign == DrawingTextStyleHAlign.ALIGNED:
            if twidth and self.target_width:
                font.setPointSizeF(self.style.height * (self.target_width / (width * twidth) * scale))
                metrics = QFontMetrics(font)
        elif self.style.halign == DrawingTextStyleHAlign.FIT:
            if twidth and self.target_width:
                width *= self.target_width / twidth
        elif self.style.halign == DrawingTextStyleHAlign.MIDDLE:
            x -= twidth / 2
            # This is likely wrong, but I don't have a better idea
            y -= metrics.capHeight() / 2 / scale
        # For non-special H alignment values, use V alignment
        if self.style.halign < DrawingTextStyleHAlign.ALIGNED:
            if self.style.valign == DrawingTextStyleVAlign.BOTTOM:
                y += metrics.descent() / scale
            elif self.style.valign == DrawingTextStyleVAlign.MIDDLE:
                y -= metrics.capHeight() / 2 / scale
            elif self.style.valign == DrawingTextStyleVAlign.TOP:
                y -= metrics.capHeight() / scale
        ppath = QPainterPath()
        ppath.addText(0, 0, font, self.text)
        transform = QTransform().scale(width, 1)
        angle_rad = math.pi * angle / 180
        self.paths = []
        for polygon in ppath.toSubpathPolygons(transform):
            self.paths.append(geom.Path([geom.PathPoint(p.x() / scale + x, -p.y() / scale + y).rotated(self.origin.x, self.origin.y, -angle_rad) for p in polygon], True))
        self.calcBounds()
    def startEndPos(self):
        if self.paths:
            return (self.paths[0].seg_start(), self.paths[-1].seg_end())

@CAMTreeItem.register_class
class DrawingTreeItem(CAMListTreeItem):
    prop_x_offset = FloatDistEditableProperty("X origin", "x_offset", Format.coord, unit="mm")
    prop_y_offset = FloatDistEditableProperty("Y origin", "y_offset", Format.coord, unit="mm")
    def __init__(self, document):
        CAMListTreeItem.__init__(self, document, "Drawing")
    def resetProperties(self):
        self.x_offset = 0
        self.y_offset = 0
        self.emitPropertyChanged("x_offset")
        self.emitPropertyChanged("y_offset")
    def bounds(self):
        b = None
        for item in self.items():
            if b is None:
                b = item.bounds
            else:
                b = geom.max_bounds(b, item.bounds)
        if b is None:
            return (-1, -1, 1, 1)
        margin = 5
        return (b[0] - self.x_offset - margin, b[1] - self.y_offset - margin, b[2] - self.x_offset + margin, b[3] - self.y_offset + margin)
    def importDrawing(self, name):
        doc = ezdxf.readfile(name)
        msp = doc.modelspace()
        existing = {}
        for item in self.items():
            itemRepr = item.store()
            del itemRepr['shape_id']
            itemStr = json.dumps(itemRepr)
            existing[itemStr] = item
        itemsToAdd = []
        for entity in msp:
            item = self.importDrawingEntity(entity)
            if item is not None:
                itemRepr = item.store()
                del itemRepr['shape_id']
                itemStr = json.dumps(itemRepr)
                if itemStr not in existing:
                    itemsToAdd.append(item)
        self.document.opAddDrawingItems(itemsToAdd)
        self.document.drawingImported.emit()
    def importDrawingEntity(self, entity):
        dxftype = entity.dxftype()
        inch_mode = geom.GeometrySettings.dxf_inches
        scaling = 25.4 if inch_mode else 1
        def pt(x, y):
            return geom.PathPoint(x * scaling, y * scaling)
        if dxftype == 'LWPOLYLINE':
            points, closed = geom.dxf_polyline_to_points(entity, scaling)
            return DrawingPolylineTreeItem(self.document, points, closed)
        elif dxftype == 'LINE':
            start = tuple(entity.dxf.start)[0:2]
            end = tuple(entity.dxf.end)[0:2]
            return DrawingPolylineTreeItem(self.document, [pt(start[0], start[1]), pt(end[0], end[1])], False)
        elif dxftype == 'ELLIPSE':
            centre = pt(entity.dxf.center[0], entity.dxf.center[1])
            return DrawingPolylineTreeItem.ellipse(self.document, centre, pt(entity.dxf.major_axis[0], entity.dxf.major_axis[1]), entity.dxf.ratio, entity.dxf.start_param, entity.dxf.end_param)
        elif dxftype == 'SPLINE':
            iter = entity.flattening(1.0 / geom.GeometrySettings.RESOLUTION)
            points = [geom.PathPoint(i[0], i[1]) for i in iter]
            return DrawingPolylineTreeItem(self.document, points, entity.closed, src_name="Spline")
        elif dxftype == 'LINE':
            start = tuple(entity.dxf.start)[0:2]
            end = tuple(entity.dxf.end)[0:2]
            return DrawingPolylineTreeItem(self.document, [pt(start[0], start[1]), pt(end[0], end[1])], False)
        elif dxftype == 'CIRCLE':
            centre = pt(entity.dxf.center[0], entity.dxf.center[1])
            return DrawingCircleTreeItem(self.document, centre, entity.dxf.radius * scaling)
        elif dxftype == 'ARC':
            start = pt(entity.start_point[0], entity.start_point[1])
            end = pt(entity.end_point[0], entity.end_point[1])
            centre = (entity.dxf.center[0] * scaling, entity.dxf.center[1] * scaling)
            c = geom.CandidateCircle(*centre, entity.dxf.radius * scaling)
            sangle = entity.dxf.start_angle * math.pi / 180
            eangle = entity.dxf.end_angle * math.pi / 180
            if eangle < sangle:
                sspan = eangle - sangle + 2 * math.pi
            else:
                sspan = eangle - sangle
            points = [start, geom.PathArc(start, end, c, 50, sangle, sspan)]
            return DrawingPolylineTreeItem(self.document, points, False)
        elif dxftype == 'TEXT':
            font = "OpenSans"
            style = DrawingTextStyle(entity.dxf.height * scaling, entity.dxf.width, entity.dxf.halign, entity.dxf.valign, entity.dxf.rotation, font, 0)
            target_width = None
            ap = entity.dxf.align_point
            ip = pt(entity.dxf.insert[0], entity.dxf.insert[1])
            if entity.dxf.align_point is None:
                ap = ip
            else:
                ap = pt(entity.dxf.align_point[0], entity.dxf.align_point[1])
                target_width = ap.dist(ip)
            rp = ip if entity.dxf.halign in (0, 3, 5) else ap
            return DrawingTextTreeItem(self.document, rp, target_width, style, entity.dxf.text)
        else:
            print ("Ignoring DXF entity: %s" % dxftype)
        return None
    def renderTo(self, path, modeData):
        # XXXKF convert
        for i in self.items():
            i.translated(-self.x_offset, -self.y_offset).renderTo(path, modeData)
    def addItem(self, item):
        self.appendRow(item)
    def itemById(self, shape_id):
        # XXXKF slower than before
        for i in self.items():
            if i.shape_id == shape_id:
                return i
            for j in i.items():
                if j.shape_id == shape_id:
                    return j
    def objectsNear(self, pos, margin):
        xy = geom.PathPoint(pos.x() + self.x_offset, pos.y() + self.y_offset)
        found = []
        mindist = margin
        for item in self.items():
            if item.bounds is not None and geom.point_inside_bounds(geom.expand_bounds(item.bounds, margin), xy):
                distance = item.distanceTo(xy)
                if distance is not None and distance < margin:
                    mindist = min(mindist, distance)
                    found.append((item, distance))
        found = sorted(found, key=lambda item: item[1])
        found = [item[0] for item in found if item[1] < mindist * 1.5]
        return found
    def objectsWithin(self, xs, ys, xe, ye):
        xs += self.x_offset
        ys += self.y_offset
        xe += self.x_offset
        ye += self.y_offset
        bounds = (xs, ys, xe, ye)
        found = []
        for item in self.items():
            if geom.inside_bounds(item.bounds, bounds):
                found.append(item)
        return found
    def parseSelection(self, selection, operType):
        translation = self.translation()
        warnings = []
        def pickObjects(selector):
            matched = []
            warnings = []
            for i in selection:
                verdict = selector(i)
                if verdict is True:
                    matched.append(i)
                else:
                    warnings.append(verdict % (i.label(),))
            return matched, warnings
        if operType in [OperationType.INTERPOLATED_HOLE, OperationType.DRILLED_HOLE, OperationType.INSIDE_THREAD]:
            selection, warnings = pickObjects(lambda i: isinstance(i, DrawingCircleTreeItem) or "%s is not a circle")
        elif operType != OperationType.ENGRAVE:
            selection, warnings = pickObjects(lambda i: isinstance(i, DrawingTextTreeItem) or i.toShape().closed or "%s is not a closed shape")
        if not OperationType.has_islands(operType):
            return {i.shape_id: set() for i in selection}, selection, warnings
        nonzeros = set()
        zeros = set()
        texts = [ i for i in selection if isinstance(i, DrawingTextTreeItem) ]
        selectionId = [ i.shape_id for i in selection if not isinstance(i, DrawingTextTreeItem) ]
        selectionTrans = [ geom.IntPath(i.translated(*translation).toShape().boundary) for i in selection if not isinstance(i, DrawingTextTreeItem) ]
        for i in range(len(selectionTrans)):
            isi = selectionId[i]
            for j in range(len(selectionTrans)):
                if i == j:
                    continue
                jsi = selectionId[j]
                if not geom.run_clipper_simple(pyclipr.Difference, subject_polys=[selectionTrans[i]], clipper_polys=[selectionTrans[j]], bool_only=True, fillMode=pyclipr.FillRule.NonZero):
                    zeros.add((isi, jsi))
        outsides = { i.shape_id: set() for i in selection }
        for isi, jsi in zeros:
            # i minus j = empty set, i.e. i wholly contained in j
            if isi in outsides:
                del outsides[isi]
        for isi, jsi in zeros:
            # i minus j = empty set, i.e. i wholly contained in j
            if jsi in outsides:
                outsides[jsi].add(isi)
        allObjects = set(outsides.keys())
        for outside in outsides:
            islands = outsides[outside]
            redundant = set()
            for i1 in islands:
                for i2 in islands:
                    if i1 != i2 and (i1, i2) in zeros:
                        redundant.add(i1)
            for i in redundant:
                islands.remove(i)
            allObjects |= islands
        for i in texts:
            #glyphs = i.translated(*translation).toShape()
            outsides[i.shape_id] = set()
            allObjects.add(i.shape_id)
        selection = [i for i in selection if i.shape_id in allObjects]
        return outsides, selection, warnings
    def properties(self):
        return [self.prop_x_offset, self.prop_y_offset]
    def translation(self):
        return (-self.x_offset, -self.y_offset)
    def onPropertyValueSet(self, name):
        self.emitPropertyChanged(name)
    def invalidatedObjects(self, aspect):
        if aspect == InvalidateAspect.CAM:
            return set([self] + self.document.allOperations())
        # Properties of operations are not affected
        return set([self])
    def snapCentrePoints(self):
        points = set()
        for item in self.items():
            if isinstance(item, DrawingCircleTreeItem):
                points.add(item.centre)
        return points
    def snapEndPoints(self):
        points = set()
        for item in self.items():
            if isinstance(item, DrawingPolylineTreeItem):
                for p in item.points:
                    points.add(p.seg_end())
        return points
        
class BlockmapEntry(object):
    def __init__(self):
        self.starts = set()
        self.ends = set()

class Blockmap:
    def __init__(self):
        self.bmap = dict()
        self.edges = set()
        self.duplicates = set()
        self.coord_values = set()
        self.coord_map = dict()
    def add_edge_coords(self, points):
        self.add_point_coords(points[0].seg_start())
        self.add_point_coords(points[-1].seg_end())
    def add_point_coords(self, point):
        self.coord_values.add(point.x)
        self.coord_values.add(point.y)
    def create_approx_map(self):
        values = sorted(list(self.coord_values))
        if not values:
            return
        deltas = [ values[i + 1] - values[i] for i in range(len(values) - 1) ]
        self.coord_map[values[0]] = 0
        start = values[0]
        step = 1.0 / geom.GeometrySettings.RESOLUTION
        counter = 0
        for i, delta in enumerate(deltas):
            if delta >= step / 2 or values[i + 1] - start >= step:
                start = values[i + 1]
                counter += 1
            self.coord_map[values[i + 1]] = counter
            #print (values[i + 1], counter)
    def pt_to_index(self, pt):
        return (self.coord_map[pt.x], self.coord_map[pt.y])
    def point(self, pt):
        i = self.pt_to_index(pt)
        res = self.bmap.get(i, None)
        if res is None:
            res = self.bmap[i] = BlockmapEntry()
        return res
    def start_point(self, points):
        return self.point(points[0].seg_start())
    def end_point(self, points):
        return self.point(points[-1].seg_end())
    def add_edge(self, edge, points):
        # Only apply duplicate elimination logic to single lines, otherwise it's too expensive
        if len(points) == 2:
            start = self.pt_to_index(points[0].seg_start())
            end = self.pt_to_index(points[-1].seg_end())
            if not points[0].is_arc() and not points[1].is_arc():
                if (end, start) in self.edges or (start, end) in self.edges:
                    self.duplicates.add(edge)
                    return
                self.edges.add((start, end))
            else:
                assert not points[0].is_arc()
                if (end, points[1].c.r, start) in self.edges or (start, points[1].c.r, end) in self.edges:
                    self.duplicates.add(edge)
                    return
                self.edges.add((start, points[1].c.r, end))
        self.start_point(points).starts.add(edge)
        self.end_point(points).ends.add(edge)
    def all_points(self):
        return self.bmap.values()

class JoinItemsUndoCommand(QUndoCommand):
    def __init__(self, document, items):
        QUndoCommand.__init__(self, "Join items")
        self.document = document
        self.items = items
        self.original_items = {}
        self.removed_items = []
    def undo(self):
        root = self.document.shapeModel.invisibleRootItem()
        pos = self.document.drawing.row()
        root.takeRow(pos)
        for item, points in self.original_items.items():
            item.untransformed.points = points
            item.closed = False
        for row, item in self.removed_items:
            self.document.drawing.insertRow(row, item)
        root.insertRow(pos, self.document.drawing)
        self.document.shapesUpdated.emit()
    def redo(self):
        def rev(pts):
            return geom.Path(pts, False).reverse().nodes
        def join(p1, p2):
            if not p1[-1].is_arc():
                assert not p2[0].is_arc()
                return p1[:-1] + p2
            else:
                assert not p2[0].is_arc()
                return p1 + p2
        blockmap = Blockmap()
        joined = set()
        edges = set()
        toRemove = set()
        toRecalc = set()
        originals = {}
        for edge in self.items:
            blockmap.add_edge_coords(edge.untransformed.points)
        blockmap.create_approx_map()
        for edge in self.items:
            points = edge.untransformed.points
            originals[edge] = points
            blockmap.add_edge(edge, points)
        result = set()
        for bme in blockmap.all_points():
            while len(bme.starts) >= 1 and len(bme.ends) >= 1:
                i = bme.ends.pop()
                j = bme.starts.pop()
                if i is j:
                    i.untransformed.closed = True
                    if not i.untransformed.points[-1].is_arc():
                        del i.untransformed.points[-1:]
                    result.add(i)
                    continue
                i.untransformed.points = join(i.untransformed.points, j.untransformed.points)
                p = blockmap.end_point(j.untransformed.points)
                p.ends.remove(j)
                p.ends.add(i)
                toRecalc.add(i)
                toRemove.add(j)
            while len(bme.starts) >= 2:
                i = bme.starts.pop()
                j = bme.starts.pop()
                if i is j:
                    assert False
                i.untransformed.points = join(rev(j.untransformed.points), i.untransformed.points)
                p = blockmap.end_point(j.untransformed.points)
                p.ends.remove(j)
                p.starts.add(i)
                toRecalc.add(i)
                toRemove.add(j)
            while len(bme.ends) >= 2:
                i = bme.ends.pop()
                j = bme.ends.pop()
                i.untransformed.points = join(i.untransformed.points, rev(j.untransformed.points))
                p = blockmap.start_point(j.untransformed.points)
                p.starts.remove(j)
                p.ends.add(i)
                toRecalc.add(i)
                toRemove.add(j)
        for i in toRecalc:
            i.untransformed.calcBounds()
        root = self.document.shapeModel.invisibleRootItem()
        pos = self.document.drawing.row()
        root.takeRow(pos)
        self.original_items = {k : v for k, v in originals.items() if k in toRecalc}
        self.removed_items = []
        for i in blockmap.duplicates | toRemove:
            row = i.row()
            self.removed_items.append((row, self.document.drawing.takeRow(row)))
        self.removed_items = self.removed_items[::-1]
        root.insertRow(pos, self.document.drawing)
        self.document.shapesUpdated.emit()
        self.document.shapesCreated.emit(list(result))

class AddDrawingItemsUndoCommand(QUndoCommand):
    def __init__(self, document, items):
        QUndoCommand.__init__(self, "Add drawing items")
        self.document = document
        self.items = items
        self.pos = self.document.drawing.rowCount()
    def undo(self):
        deletedItems = []
        for i in range(len(self.items)):
            deletedItems.append(self.document.drawing.takeRow(self.pos)[0])
        self.document.shapesDeleted.emit(deletedItems)
        self.document.shapesUpdated.emit()
    def redo(self):
        self.document.drawing.insertRows(self.pos, self.items)
        self.document.shapesUpdated.emit()

class DeleteDrawingItemsUndoCommand(QUndoCommand):
    def __init__(self, document, items):
        QUndoCommand.__init__(self, "Delete drawing items")
        self.document = document
        self.items = [(self.document.drawing, item.row(), item) for item in items]
        self.items = sorted(self.items, key=lambda item: item[1])
    def undo(self):
        for parent, pos, item in self.items:
            parent.insertRow(pos, item)
        self.document.shapesUpdated.emit()
    def redo(self):
        deletedItems = []
        for parent, pos, item in self.items[::-1]:
            deletedItems.append(parent.takeRow(pos)[0])
        self.document.shapesDeleted.emit(deletedItems)
        self.document.shapesUpdated.emit()

class ModifyPolylineUndoCommand(QUndoCommand):
    def __init__(self, document, polyline, new_points, new_closed):
        QUndoCommand.__init__(self, "Modify polyline")
        self.document = document
        self.polyline = polyline
        self.new_points = new_points
        self.new_closed = new_closed
        self.orig_points = polyline.points
        self.orig_closed = polyline.closed
    def undo(self):
        self.polyline.points = self.orig_points
        self.polyline.closed = self.orig_closed
        self.polyline.calcBounds()
        self.document.shapesUpdated.emit()
    def redo(self):
        self.polyline.points = self.new_points
        self.polyline.closed = self.new_closed
        self.polyline.calcBounds()
        self.document.shapesUpdated.emit()

class ModifyPolylinePointUndoCommand(QUndoCommand):
    def __init__(self, document, polyline, position, location, mergeable):
        QUndoCommand.__init__(self, "Move polyline point")
        self.document = document
        self.polyline = polyline
        self.position = position
        self.new_location = location
        self.orig_location = self.polyline.points[self.position]
        self.mergeable = mergeable
    def undo(self):
        self.polyline.points[self.position] = self.orig_location
        if self.orig_location.is_arc():
            assert self.position > 0
            self.polyline.points[self.position - 1] = self.orig_location.p1
        self.polyline.calcBounds()
        self.document.shapesUpdated.emit()
    def redo(self):
        self.polyline.points[self.position] = self.new_location
        if self.new_location.is_arc():
            assert self.position > 0
            self.polyline.points[self.position - 1] = self.new_location.p1
        self.polyline.calcBounds()
        self.document.shapesUpdated.emit()
    def id(self):
        return 1000
    def mergeWith(self, other):
        if not isinstance(other, ModifyPolylinePointUndoCommand):
            return False
        if not self.mergeable:
            return False
        self.new_location = other.new_location
        return True

