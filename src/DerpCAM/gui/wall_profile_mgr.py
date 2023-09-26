import math

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from DerpCAM.cam.wall_profile import WallProfileItemType, WallProfileItem, UserDefinedWallProfile
from DerpCAM.common.guiutils import Format, UnitConverter
from . import inventory, model, propsheet

class SeparatorItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if index.row() != index.model().delim_pos():
            return QStyledItemDelegate.paint(self, painter, option, index)
        painter.save()
        painter.setFont(option.font)
        painter.setPen(QColor(0, 0, 0))
        painter.fillRect(option.rect, QBrush(Qt.lightGray))
        painter.drawLine(option.rect.left(), option.rect.top(), option.rect.right(), option.rect.top())
        painter.drawLine(option.rect.left(), option.rect.bottom(), option.rect.right(), option.rect.bottom())
        r = option.rect
        r.adjust(5, 0, -5, 0)
        painter.drawText(r, Qt.AlignTop | Qt.AlignLeft, "\u2ba4 From top")
        painter.drawText(r, Qt.AlignBottom | Qt.AlignRight, "From bottom \u2ba7")
        painter.restore()

class ProfileShapeItemDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        for value, text in WallProfileItemType.descriptions:
            combo.addItem(text, value)
        return combo
    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData(), Qt.DisplayRole)

class ProfileShapeModel(QAbstractTableModel):
    pictureNeedsRefresh = pyqtSignal([])
    def __init__(self, profile):
        QAbstractTableModel.__init__(self)
        self.profile = profile
        self.top_empty_pos = len(self.profile.top)
        self.bottom_empty_pos = 0
        self.columnNames = ["Offset", "Height", "Shape", "Parameter"]
    def delim_pos(self):
        return len(self.profile.top) + 1
    def edit_data(self, index):
        delim = self.delim_pos()
        row = index.row()
        col = index.column()
        arr = None
        arr_idx = None
        bepos = delim + 1 + self.bottom_empty_pos
        if row < delim and row != self.top_empty_pos:
            arr = self.profile.top
            arr_idx = row if row < self.top_empty_pos else row - 1
        if row > delim and row != bepos:
            arr = self.profile.bottom
            arr_idx = (row if row < bepos else row - 1) - delim - 1
        return row, col, delim, bepos, arr, arr_idx
    def data(self, index, role):
        row, col, delim, bepos, arr, arr_idx = self.edit_data(index)
        if role == Qt.DisplayRole:
            if row == delim:
                return "\u2ba4 From top       |       From bottom \u2ba7"
            if arr is not None:
                if col == 0:
                    return Format.depth_of_cut(arr[arr_idx].offset)
                if col == 1:
                    return Format.depth_of_cut(arr[arr_idx].height)
                if col == 2:
                    return WallProfileItemType.toString(arr[arr_idx].shape)
                if col == 3:
                    if arr[arr_idx].shape == WallProfileItemType.REBATE:
                        return Format.width_of_cut(arr[arr_idx].rebate)
                    if arr[arr_idx].shape == WallProfileItemType.TAPER:
                        return Format.angle(arr[arr_idx].taper)
                    return ""
            if row == self.top_empty_pos or row == bepos:
                return ""
        if role == Qt.TextAlignmentRole:
            if row == delim:
                return Qt.AlignCenter
            if col == 2:
                return Qt.AlignHCenter | Qt.AlignVCenter
            return Qt.AlignRight | Qt.AlignVCenter
        if row == delim:
            if role == Qt.BackgroundRole:
                return QBrush(Qt.lightGray)
            if role == Qt.ForegroundRole:
                return QBrush(Qt.black)
        return None
    def setData(self, index, value, role):        
        if role == Qt.DisplayRole or role == Qt.EditRole:
            row, col, delim, bepos, arr, arr_idx = self.edit_data(index)
            if row == self.top_empty_pos or row == bepos:
                is_top = row == self.top_empty_pos
                empty = WallProfileItem()
                if self.trySetData(empty, col, value):
                    if is_top:
                        self.beginInsertRows(QModelIndex(), self.top_empty_pos, self.top_empty_pos)
                        self.profile.top.insert(self.top_empty_pos, empty)
                        self.top_empty_pos += 1
                    else:
                        self.beginInsertRows(QModelIndex(), bepos, bepos)
                        self.profile.bottom.insert(self.bottom_empty_pos, empty)
                    self.endInsertRows()
                    self.pictureNeedsRefresh.emit()
                    return True
                return False
            if self.trySetData(arr[arr_idx], col, value):
                self.pictureNeedsRefresh.emit()
                return True
            return False
        return QAbstractTableModel.setData(index, value, role)
    def trySetData(self, item, col, value):
        distUnit = "mm"
        try:
            if col == 0:
                item.offset, unit = UnitConverter.parse(value, distUnit, as_float=True)
            elif col == 1:
                item.height, unit = UnitConverter.parse(value, distUnit, as_float=True)
            elif col == 2:
                item.shape = value
            elif col == 3 and item.shape == WallProfileItemType.TAPER:
                item.taper, unit = UnitConverter.parse(value, "\u00b0", as_float=True)
            elif col == 3 and item.shape == WallProfileItemType.REBATE:
                item.rebate, unit = UnitConverter.parse(value, distUnit, as_float=True)
            else:
                return False
            return True
        except ValueError as e:
            return False
    def flags(self, index):
        row, col, delim, bepos, arr, arr_idx = self.edit_data(index)
        if row == delim:
            return Qt.NoItemFlags
        if arr:
            if col == 3 and arr[arr_idx].shape in [WallProfileItemType.REBATE, WallProfileItemType.TAPER]:
                return Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled
            if col in (0, 1, 2):
                return Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled
        if row == self.top_empty_pos or row == bepos:
            return Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled            
        return QAbstractTableModel.flags(self, index)
    def columnCount(self, parent):
        return 0 if parent.isValid() else 4
    def rowCount(self, parent):
        return 0 if parent.isValid() else (len(self.profile.top) + len(self.profile.bottom) + 3)
    def headerData(self, section, orientation, role):
        if orientation == Qt.Vertical and role == Qt.DisplayRole:
            if section < self.delim_pos():
                return f"T {1 + section}"
            if section == self.delim_pos():
                return ""
            if section > self.delim_pos():
                return f"B {len(self.profile.top) + len(self.profile.bottom ) + 3 - section}"
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.columnNames[section]
        return QAbstractTableModel.headerData(self, section, orientation, role)
    def deleteRange(self, range):
        lastRow = None
        rows = list(sorted(range, key=lambda item: -item.row()))
        for index in rows:
            row, col, delim, bepos, arr, arr_idx = self.edit_data(index)
            if row == lastRow:
                continue
            lastRow = row
            if arr:
                self.beginRemoveRows(QModelIndex(), row, row)
                del arr[arr_idx]
                self.endRemoveRows()
                if row < self.top_empty_pos:
                    self.top_empty_pos -= 1
                if row > delim and row < bepos:
                    self.bottom_empty_pos -= 1
        self.pictureNeedsRefresh.emit()
    def moveUp(self, range):
        lastRow = None
        rows = list(sorted(range, key=lambda item: -item.row()))
        for index in rows:
            row, col, delim, bepos, arr, arr_idx = self.edit_data(index)
            if row == lastRow:
                continue
            lastRow = row
            if not arr:
                if row == self.top_empty_pos and self.top_empty_pos > 0:
                    self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), row - 1)
                    self.top_empty_pos -= 1
                    self.endMoveRows()
                if row == bepos and self.bottom_empty_pos > 0:
                    self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), row - 1)
                    self.bottom_empty_pos -= 1
                    self.endMoveRows()
            else:
                if row == self.top_empty_pos + 1:
                    self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), row - 1)
                    self.top_empty_pos += 1
                    self.endMoveRows()
                elif row == bepos + 1:
                    self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), row - 1)
                    self.bottom_empty_pos += 1
                    self.endMoveRows()
                elif arr_idx > 0:
                    self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), row - 1)
                    arr[arr_idx - 1], arr[arr_idx] = arr[arr_idx], arr[arr_idx - 1]
                    self.endMoveRows()
                elif row == delim + 1:
                    self.tableWidget.setSpan(self.delim_pos(), 0, 1, 1)
                    self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), row - 1)
                    self.profile.top.append(arr[arr_idx])
                    del arr[arr_idx]
                    if bepos > row:
                        self.bottom_empty_pos -= 1
                    self.endMoveRows()
                    self.tableWidget.setSpan(self.delim_pos(), 0, 1, 4)
        self.pictureNeedsRefresh.emit()        
    def moveDown(self, range):
        lastRow = None
        rows = list(sorted(range, key=lambda item: item.row()))
        for index in rows:
            row, col, delim, bepos, arr, arr_idx = self.edit_data(index)
            if row == lastRow:
                continue
            lastRow = row
            if not arr:
                if row == self.top_empty_pos and self.top_empty_pos < len(self.profile.top):
                    self.beginMoveRows(QModelIndex(), row + 1, row + 1, QModelIndex(), row)
                    self.top_empty_pos += 1
                    self.endMoveRows()
                if row == bepos and self.bottom_empty_pos < len(self.profile.bottom):
                    self.beginMoveRows(QModelIndex(), row + 1, row + 1, QModelIndex(), row)
                    self.bottom_empty_pos += 1
                    self.endMoveRows()
            else:
                if row == self.top_empty_pos - 1:
                    self.beginMoveRows(QModelIndex(), row + 1, row + 1, QModelIndex(), row)
                    self.top_empty_pos -= 1
                    self.endMoveRows()
                elif row == bepos - 1:
                    self.beginMoveRows(QModelIndex(), row + 1, row + 1, QModelIndex(), row)
                    self.bottom_empty_pos -= 1
                    self.endMoveRows()
                elif arr_idx < len(arr) - 1:
                    self.beginMoveRows(QModelIndex(), row + 1, row + 1, QModelIndex(), row)
                    arr[arr_idx + 1], arr[arr_idx] = arr[arr_idx], arr[arr_idx + 1]
                    self.endMoveRows()
                elif row == delim - 1:
                    self.tableWidget.setSpan(self.delim_pos(), 0, 1, 1)
                    self.beginMoveRows(QModelIndex(), row + 1, row + 1, QModelIndex(), row)
                    self.profile.bottom.insert(0, arr[arr_idx])
                    del arr[arr_idx]
                    self.endMoveRows()
                    self.tableWidget.setSpan(self.delim_pos(), 0, 1, 4)
                    if bepos > row:
                        self.bottom_empty_pos += 1
                    
        self.pictureNeedsRefresh.emit()        

class TableViewWithDelete(QTableView):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            event.accept()
            self.model().deleteRange(self.selectionModel().selectedIndexes())
            return
        if event.key() == Qt.Key_Up and event.modifiers() & Qt.ControlModifier:
            event.accept()
            self.model().moveUp(self.selectionModel().selectedIndexes())
            return
        if event.key() == Qt.Key_Down and event.modifiers() & Qt.ControlModifier:
            event.accept()
            self.model().moveDown(self.selectionModel().selectedIndexes())
            return
        return QTableView.keyPressEvent(self, event)

def renderWallProfile(drawSurface, src, height, edge, size):
    qp = QPainter()
    qp.begin(drawSurface)
    qp.setRenderHint(QPainter.Antialiasing, True)
    qp.setRenderHint(QPainter.HighQualityAntialiasing, True)
    qp.setPen(QColor(160, 160, 160))
    qp.drawRect(-3, -3, size + 5, size + 5)
    qp.setPen(QColor(160, 160, 160))
    qp.drawLine(0, 0, edge, 0)
    qp.drawLine(edge, 0, edge, size)
    qp.setPen(QColor(0, 0, 0))
    path = QPainterPath()
    path.moveTo(0, 0)
    for i in range(size):
        depth = height * i / (size - 1)
        if src:
            pos = -src.offset_at_depth(depth, height) * size / height
        else:
            pos = 0
        nextpt = QPointF(edge - pos, i)
        path.lineTo(nextpt)
        lastpt = nextpt
    path.lineTo(0, size)
    path.lineTo(0, 0)
    qp.fillPath(path, QBrush(Qt.black, Qt.BDiagPattern))
    qp.drawPath(path)
    qp.end()

class WallProfileEditorDlg(QDialog):
    def __init__(self, parent, title, profile):
        QDialog.__init__(self, parent)
        self.title = title
        self.profile = profile
        self.edit_shape = self.profile.shape.clone()
        self.initUI()
    def drawProfile(self):
        renderWallProfile(self.shapePicture, self.edit_shape, 24, 90, 120)
        self.shapeWidget.repaint()
    def initUI(self):
        self.setWindowTitle(self.title)
        self.layout = QVBoxLayout(self)
        self.layout3 = QFormLayout()
        self.nameEdit = QLineEdit(self.profile.name)
        self.layout3.addRow("Name", self.nameEdit)
        self.descEdit = QLineEdit(self.profile.description)
        self.layout3.addRow("Description", self.descEdit)
        self.alignEdit = QComboBox()
        self.alignEdit.addItems(["Target shape only", "Bottom=Target shape, Top=Margin", "Margin only"])
        self.alignEdit.setCurrentIndex(self.profile.shape.align)
        self.alignEdit.currentIndexChanged.connect(self.alignmentChanged)
        self.layout3.addRow("Profile alignment", self.alignEdit)
        self.layout2 = QHBoxLayout()
        self.shapePicture = QPicture()
        self.shapeWidget = QLabel()
        self.shapeWidget.setPicture(self.shapePicture)
        self.shapeWidget.setMargin(2)
        self.layout2.addWidget(self.shapeWidget)
        self.layout2.addSpacing(10)
        self.tableWidget = TableViewWithDelete()
        self.model = ProfileShapeModel(self.edit_shape)
        self.model.tableWidget = self.tableWidget
        self.tableWidget.setModel(self.model)
        self.tableWidget.setMinimumSize(600, 200)
        self.tableWidget.setColumnWidth(2, 150)
        hdr = self.tableWidget.horizontalHeader()
        self.profileDelegate = ProfileShapeItemDelegate()
        self.tableWidget.setItemDelegateForColumn(2, self.profileDelegate)
        self.separatorDelegate = SeparatorItemDelegate()
        self.tableWidget.setItemDelegate(self.separatorDelegate)
        self.tableWidget.setSpan(self.model.delim_pos(), 0, 1, 4)
        self.layout2.addWidget(self.tableWidget)
        self.layout.addLayout(self.layout3)
        self.layout.addLayout(self.layout2)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.layout.addWidget(self.buttonBox)
        self.drawProfile()
        self.model.pictureNeedsRefresh.connect(self.drawProfile)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
    def alignmentChanged(self, index):
        self.edit_shape.align = index
        self.drawProfile()
    def accept(self):
        name = self.nameEdit.text()
        if name == '':
            QMessageBox.critical(self, None, "Name is required")
            self.nameEdit.setFocus()
            return
        self.profile.name = name
        self.profile.description = self.descEdit.text()
        self.profile.shape = self.edit_shape
        QDialog.accept(self)

class WallProfileManagerDlg(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.initUI()
    def initUI(self):
        self.setWindowTitle("Wall profiles")
        self.layout = QVBoxLayout(self)
        self.hlayout = QHBoxLayout()
        self.profileList = QTableWidget(0, 2)
        self.profileList.setVerticalHeader(None)
        self.profileList.setMinimumSize(450, 200)
        self.profileList.setColumnWidth(0, 150)
        self.profileList.setColumnWidth(1, 250)
        self.profileList.setSelectionBehavior(QTableView.SelectRows)
        self.profileList.setHorizontalHeaderLabels(["Name", "Description"])
        self.hlayout.addWidget(self.profileList)
        self.shapeLabel = QLabel()
        self.shapePicture = QPicture()
        self.shapeLabel.setPicture(self.shapePicture)
        self.shapeLabel.setMargin(2)
        renderWallProfile(self.shapePicture, None, 24, 90, 120)
        self.hlayout.addWidget(self.shapeLabel)
        self.layout.addLayout(self.hlayout)
        self.editButtons = QHBoxLayout()
        self.addButton = QPushButton("&Add")
        self.addButton.clicked.connect(self.addWallProfile)
        self.editButtons.addWidget(self.addButton)
        self.editButton = QPushButton("&Edit")
        self.editButton.clicked.connect(self.editWallProfile)
        self.editButtons.addWidget(self.editButton)
        self.deleteButton = QPushButton("&Delete")
        self.deleteButton.clicked.connect(self.deleteWallProfile)
        self.editButtons.addWidget(self.deleteButton)
        self.layout.addLayout(self.editButtons)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttonBox.rejected.connect(self.reject)
        self.layout.addWidget(self.buttonBox)
        self.profileList.selectionModel().selectionChanged.connect(self.onItemActivated)
        self.populateList()
    def currentProfile(self):
        itemIdx = self.profileList.currentRow()
        if itemIdx >= 0 and itemIdx < len(inventory.inventory.wall_profiles):
            return inventory.inventory.wall_profiles[itemIdx]
        else:
            return None
    def onItemActivated(self):
        profile = self.currentProfile()
        item = profile.shape if profile else None
        renderWallProfile(self.shapePicture, item, 24, 90, 120)
        self.shapeLabel.repaint()
        self.editButton.setEnabled(item is not None)
        self.deleteButton.setEnabled(item is not None)
    def populateList(self, profile=None):
        self.profileList.setRowCount(len(inventory.inventory.wall_profiles))
        current = 0
        for i, wp in enumerate(inventory.inventory.wall_profiles):
            if wp is profile:
                current = i
            self.profileList.setItem(i, 0, QTableWidgetItem(wp.name))
            self.profileList.setItem(i, 1, QTableWidgetItem(wp.description))
        self.profileList.setCurrentCell(current, 0)
        self.onItemActivated()
    def addWallProfile(self):
        profile = inventory.InvWallProfile.new(None, "", "")
        dlg = WallProfileEditorDlg(parent=None, title="Create a new wall profile", profile=profile)
        if dlg.exec_():
            inventory.inventory.wall_profiles.append(profile)
            self.populateList(profile)
        else:
            profile.forget()
            return
    def editWallProfile(self):
        profile = self.currentProfile()
        if not profile:
            return
        workcopy = inventory.InvWallProfile.new(None, profile.name, "")
        workcopy.resetTo(profile)
        dlg = WallProfileEditorDlg(self, "Edit a wall profile", workcopy)
        if dlg.exec_():
            profile.name = workcopy.name
            profile.resetTo(workcopy)
            self.populateList(profile)
    def deleteWallProfile(self):
        profile = self.currentProfile()
        if not profile:
            return
        if QMessageBox.question(self, None, "Delete the profile: " + profile.name) != QMessageBox.Yes:
            return
        inventory.inventory.deleteWallProfile(profile)
        self.populateList()
