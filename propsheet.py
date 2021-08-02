from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

class EditableProperty(object):
    def __init__(self, name, attribute, format = "%s"):
        self.name = name
        self.attribute = attribute
        self.format = format
    def getDefaultPropertyValue(self, item):
        if hasattr(item, "getDefaultPropertyValue"):
            return item.getDefaultPropertyValue(self.attribute)
        return None
    def getData(self, item):
        if hasattr(item, "getPropertyValue"):
            return item.getPropertyValue(self.attribute)
        return getattr(item, self.attribute)
    def setData(self, item, value):
        if hasattr(item, "setPropertyValue"):
            return item.setPropertyValue(self.attribute, value)
        setattr(item, self.attribute, value)
        if hasattr(item, "onPropertyValueSet"):
            item.onPropertyValueSet(self.attribute)
    def toTextColor(self, value):
        return None
    def toEditString(self, value):
        return self.format % (value,)
    def toDisplayString(self, value):
        return self.toEditString(value)
    def validate(self, value):
        return value
    def createEditor(self, parent):
        return None

class EnumEditableProperty(EditableProperty):
    def __init__(self, name, attribute, enum_class, allow_none = False, none_value = "none"):
        EditableProperty.__init__(self, name, attribute, "%s")
        self.enum_class = enum_class
        self.allow_none = allow_none
        self.none_value = none_value
    def toEditString(self, value):
        return self.enum_class.toString(value) or str(value)
    def validate(self, value):
        for data in self.enum_class.descriptions:
            id, description = data[0 : 2]
            if value == id or value == description:
                return id
        if self.allow_none and value == self.none_value:
            return None
        raise ValueError("Incorrect value: %s" % (value))
    def createEditor(self, parent):
        widget = QComboBox(parent)
        for data in self.enum_class.descriptions:
            id, description = data[0 : 2]
            widget.addItem(description, id)
        widget.showPopup()
        return widget

class FloatEditableProperty(EditableProperty):
    def __init__(self, name, attribute, format, min = None, max = None, allow_none = False, none_value = "none"):
        EditableProperty.__init__(self, name, attribute, format)
        self.min = min
        self.max = max
        self.allow_none = allow_none
        self.none_value = none_value
    def toEditString(self, value):
        if value is None:
            return ""
        return self.format % (value,)
    def toTextColor(self, value):
        return "gray" if value is None else None
    def toDisplayString(self, value):
        if value is None:
            return self.none_value
        return self.format % (value,)
    def validate(self, value):
        if value == "" and self.allow_none:
            return None
        value = float(value)
        if self.min is not None and value < self.min:
            value = self.min
        if self.max is not None and value > self.max:
            value = self.max
        return value

class IntEditableProperty(EditableProperty):
    def __init__(self, name, attribute, format = "%d", min = None, max = None, allow_none = False, none_value = "none"):
        EditableProperty.__init__(self, name, attribute, format)
        self.min = min
        self.max = max
        self.allow_none = allow_none
        self.none_value = none_value
    def toEditString(self, value):
        if value is None:
            return ""
        return self.format % (value,)
    def toDisplayString(self, value):
        if value is None:
            return self.none_value
        return self.format % (value,)
    def validate(self, value):
        if value == "" and self.allow_none:
            return None
        value = int(value)
        if self.min is not None and value < self.min:
            value = self.min
        if self.max is not None and value > self.max:
            value = self.max
        return value

class MultipleItem(object):
    @staticmethod
    def __str__(self):
        return "(multiple)"

class PropertyTableWidgetItem(QTableWidgetItem):
    def __init__(self, prop, value, def_value=None):
        self.prop = prop
        self.value = value
        self.def_value = def_value
        if value is MultipleItem:
            QTableWidgetItem.__init__(self, "")
        else:
            QTableWidgetItem.__init__(self, prop.toEditString(value))
    def data(self, role):
        if self.value is MultipleItem:
            if role == Qt.DisplayRole:
                return "(multiple)"
            if role == Qt.ForegroundRole:
                return QBrush(QColor("gray"))
        elif self.value is None:
            if role == Qt.DisplayRole:
                if self.def_value is MultipleItem:
                    return "(multiple)"
                return self.prop.toDisplayString(self.def_value)
            if role == Qt.ForegroundRole:
                return QBrush(QColor("gray"))
        else:
            if role == Qt.DisplayRole:
                return self.prop.toDisplayString(self.value)
            if role == Qt.ForegroundRole:
                color = self.prop.toTextColor(self.value)
                if color is not None:
                    return QBrush(QColor(color))
        return QTableWidgetItem.data(self, role)

class PropertySheetItemDelegate(QStyledItemDelegate):
    def __init__(self, properties):
        QStyledItemDelegate.__init__(self)
        self.properties = properties
    def createEditor(self, parent, option, index):
        row = index.row()
        editor = self.properties[row].createEditor(parent)
        if editor is not None:
            return editor
        return QStyledItemDelegate.createEditor(self, parent, option, index)

class PropertySheetWidget(QTableWidget):
    propertyChanged = pyqtSignal([list])
    def __init__(self, properties):
        QTableWidget.__init__(self, 0, 1)
        self.updating = False
        self.objects = None
        self.setHorizontalHeaderLabels(['Value'])
        self.setProperties(properties)
        #self.verticalHeader().setResizeMode(QHeaderView.ResizeToContents)
        #self.verticalHeader().setClickable(False)
        self.horizontalHeader().setStretchLastSection(True)
        #self.horizontalHeader().setClickable(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setCurrentCell(0, 0)
        self.cellChanged.connect(self.onCellChanged)
    def setProperties(self, properties):
        self.properties = properties
        self.delegate = PropertySheetItemDelegate(properties)
        self.setRowCount(0)
        self.setItemDelegate(self.delegate)
        if self.properties:
            self.setRowCount(len(self.properties))
        if self.properties:
            self.setVerticalHeaderLabels([p.name for p in self.properties])
        else:
            self.setVerticalHeaderLabels([])
    def onCellChanged(self, row, column):
        if self.objects and not self.updating:
            item = self.item(row, column)
            newValueText = item.data(Qt.EditRole)
            prop = self.properties[row]
            changed = []
            try:
                value = prop.validate(newValueText)
                for o in self.objects:
                    if value != prop.getData(o):
                        prop.setData(o, value)
                        changed.append(o)
            except Exception as e:
                print (e)
            finally:
                self.refreshRow(row)
            self.propertyChanged.emit(changed)
    def refreshRow(self, row):
        if self.objects is None:
            self.setItem(row, 0, None)
            return
        prop = self.properties[row]
        values = [prop.getData(o) for o in self.objects]
        defValue = None
        if any([v2 is None for v2 in values]):
            defValues = [prop.getDefaultPropertyValue(o) for o in self.objects if prop.getData(o) is None]
            if any([v2 != defValues[0] for v2 in defValues[1:]]):
                defValue = MultipleItem
            else:
                defValue = defValues[0]
        i = self.item(row, 0)
        if len(values):
            if any([v2 != values[0] for v2 in values[1:]]):
                v = MultipleItem
            else:
                v = values[0]
            try:
                self.updating = True
                self.setItem(row, 0, PropertyTableWidgetItem(prop, v, defValue))
            finally:
                self.updating = False
        else:
            if i is not None:
                self.setItem(row, 0, None)
    def refreshAll(self):
        for i in range(len(self.properties)):
            self.refreshRow(i)
    def setObjects(self, objects, props=None):
        self.objects = objects
        self.setEnabled(len(self.objects) > 0)
        if props is not None:
            self.setProperties(props)
        if self.properties:
            for i in range(len(self.properties)):
                self.refreshRow(i)

