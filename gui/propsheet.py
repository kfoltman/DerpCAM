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
    def createEditor(self, parent, item, objects):
        return None
    def setEditorData(self, editor, value):
        pass
    def isEditable(self):
        return True

class SetEditableProperty(EditableProperty):
    def __init__(self, name, attribute, format_func=None):
        EditableProperty.__init__(self, name, attribute)
        self.format_func = format_func
    def toDisplayString(self, value):
        if self.format_func is None:
            return "%d items" % (len(value))
        else:
            return self.format_func(value)
    def validate(self, value):
        raise ValueError("Manual entry not supported")
    def isEditable(self):
        return False

class EnumClass(object):
    @classmethod
    def toString(classInst, value):
        for data in classInst.descriptions:
            if value == data[0]:
                return data[1]
        return None

class ComboEditableProperty(EditableProperty):
    def createEditor(self, parent, item, objects):
        widget = QListWidget(parent)
        widget.setMinimumSize(200, 100)
        widget.lookupData = self.getLookupData(objects)
        widget.rowToId = []
        for id, description in widget.lookupData:
            if item.valid_values is not None:
                if id not in item.valid_values:
                    continue
            widget.rowToId.append(id)
            widget.addItem(description)
        widget.itemPressed.connect(lambda: self.destroyEditor(widget))
        return widget
    def setEditorData(self, editor, value):
        item = None
        if type(value) is int:
            for row, item in enumerate(editor.lookupData):
                if item[0] == value:
                    editor.setCurrentRow(row)
                    return
        if type(value) is str:
            for row, item in enumerate(editor.lookupData):
                if item[1] == value:
                    editor.setCurrentRow(row)
                    return
            for row, item in enumerate(editor.lookupData):
                if str(item[0]) == value:
                    editor.setCurrentRow(row)
                    return
    
class RefEditableProperty(ComboEditableProperty):
    def __init__(self, name, attribute, items_adapter, allow_none = False, none_value = "none"):
        EditableProperty.__init__(self, name, attribute, "%s")
        self.items_adapter = items_adapter
        self.allow_none = allow_none
        self.none_value = none_value
    def getLookupData(self, item):
        return self.items_adapter.getLookupData(item)
    def toEditString(self, value):
        return value.description() if value is not None else self.none_value
    def getEditorData(self, editor):
        row = editor.currentRow()
        id = editor.rowToId[row] if row >= 0 else -1
        return self.items_adapter.lookupById(id)
    def destroyEditor(self, widget):
        widget.close()

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
    def createEditor(self, parent, item, objects):
        widget = QListWidget(parent)
        widget.setMinimumSize(200, 100)
        for data in self.enum_class.descriptions:
            id, description = data[0 : 2]
            if item.valid_values is not None:
                if id not in item.valid_values:
                    continue
            widget.addItem(description)
        widget.itemPressed.connect(lambda: self.destroyEditor(widget))
        return widget
    def getEditorData(self, editor):
        return editor.currentItem().data(Qt.DisplayRole)
    def setEditorData(self, editor, value):
        if type(value) is int:
            for row, item in enumerate(self.enum_class.descriptions):
                if item[0] == value:
                    editor.setCurrentRow(row)
                    return
        if type(value) is str:
            for row, item in enumerate(self.enum_class.descriptions):
                if str(item[0]) == value or item[1] == value:
                    editor.setCurrentRow(row)
                    return
    def destroyEditor(self, widget):
        widget.close()
    def getValidValues(self, objects):
        validValues = None
        for i in objects:
            if hasattr(i, 'getValidEnumValues'):
                values = i.getValidEnumValues(self.attribute)
                if values is not None:
                    if validValues is None:
                        validValues = set(values)
                    else:
                        validValues &= set(values)
        return validValues

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
    def __init__(self, table, prop, value, def_value = None, valid_values = None):
        if value is MultipleItem:
            QTableWidgetItem.__init__(self, "")
        else:
            QTableWidgetItem.__init__(self, prop.toEditString(value))
        self.table = table
        self.prop = prop
        self.value = value
        self.def_value = def_value
        self.valid_values = valid_values
    def data(self, role):
        if not (self.flags() & Qt.ItemIsEnabled):
            if role == Qt.DisplayRole:
                return "N/A"
        if not (self.flags() & Qt.ItemIsEditable):
            if role == Qt.ForegroundRole:
                return QBrush(QColor("black"))
            if role == Qt.BackgroundRole:
                return QBrush(QColor("lightgray"))
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
            if role == Qt.DisplayRole or role == Qt.ToolTipRole:
                return self.prop.toDisplayString(self.value)
            if role == Qt.ForegroundRole:
                color = self.prop.toTextColor(self.value)
                if color is not None:
                    return QBrush(QColor(color))
        return QTableWidgetItem.data(self, role)

class PropertySheetItemDelegate(QStyledItemDelegate):
    def __init__(self, properties, props_widget):
        QStyledItemDelegate.__init__(self)
        self.properties = properties
        self.props_widget = props_widget
    def createEditor(self, parent, option, index):
        row = index.row()
        editor = self.properties[row].createEditor(parent, self.props_widget.itemFromIndex(index), self.props_widget.objects)
        if editor is not None:
            return editor
        return QStyledItemDelegate.createEditor(self, parent, option, index)
    def setEditorData(self, editor, index):
        row = index.row()
        value = index.data(Qt.EditRole)
        self.properties[row].setEditorData(editor, value)
    def setModelData(self, editor, model, index):
        row = index.row()
        if hasattr(self.properties[row], 'getEditorData'):
            value = self.properties[row].getEditorData(editor)
            model.setData(index, value)
        else:
            return QStyledItemDelegate.setModelData(self, editor, model, index)
        #self.props_widget.itemFromIndex(index).prop.setData(value)

class PropertySheetWidget(QTableWidget):
    def __init__(self, properties, document):
        QTableWidget.__init__(self, 0, 1)
        self.document = document
        self.updating = False
        self.objects = None
        self.setHorizontalHeaderLabels(['Value'])
        self.setProperties(properties)
        #self.verticalHeader().setResizeMode(QHeaderView.ResizeToContents)
        #self.verticalHeader().setClickable(False)
        self.horizontalHeader().setStretchLastSection(True)
        #self.horizontalHeader().setClickable(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)
        self.setCurrentCell(0, 0)
        self.cellChanged.connect(self.onCellChanged)
    def setProperties(self, properties):
        self.properties = properties
        self.delegate = PropertySheetItemDelegate(properties, self)
        self.setRowCount(0)
        self.setItemDelegate(self.delegate)
        if self.properties:
            self.setRowCount(len(self.properties))
        if self.properties:
            self.setVerticalHeaderLabels([p.name for p in self.properties])
        else:
            self.setVerticalHeaderLabels([])
    def setCellValue(self, row, newValueText):
        prop = self.properties[row]
        changes = []
        try:
            value = prop.validate(newValueText)
            for o in self.objects:
                if value != prop.getData(o):
                    changes.append((o, value))
            self.document.opChangeProperty(prop, changes)
        except Exception as e:
            box = QMessageBox(QMessageBox.Warning, "Warning", str(e), QMessageBox.Ok, self)
            box.exec_()
        finally:
            #self.refreshRow(row)
            self.refreshAll()
    def onCellChanged(self, row, column):
        if self.objects and not self.updating:
            item = self.item(row, column)
            newValueText = item.data(Qt.EditRole)
            self.setCellValue(row, newValueText)
    def refreshRow(self, row):
        if self.objects is None:
            self.setItem(row, 0, None)
            return
        prop = self.properties[row]
        values = [prop.getData(o) for o in self.objects]
        validValues = None
        if hasattr(prop, 'getValidValues'):
           validValues = prop.getValidValues(self.objects)
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
                isValid = True
                for obj in self.objects:
                    if hasattr(obj, 'isPropertyValid'):
                        if not obj.isPropertyValid(prop.attribute):
                            isValid = False
                            break
                item = PropertyTableWidgetItem(self, prop, v, defValue, validValues)
                if isValid:
                    if prop.isEditable():
                        item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                    else:
                        item.setFlags((item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled) &~ Qt.ItemIsEditable)
                else:
                    item.setFlags(item.flags() &~ (Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled ))
                self.setItem(row, 0, item)
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
