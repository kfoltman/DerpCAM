from .common_model import *
from .drawing_model import DrawingItemTreeItem, DrawingPolylineTreeItem, DrawingCircleTreeItem, \
    DrawingTextTreeItem, DrawingTreeItem, DrawingTextStyleHAlign, DrawingTextStyleVAlign, DrawingTextStyle, \
    JoinItemsUndoCommand, AddDrawingItemsUndoCommand, DeleteDrawingItemsUndoCommand, \
    ModifyPolylineUndoCommand, ModifyPolylinePointUndoCommand
from .tool_model import ToolListTreeItem, ToolTreeItem, ToolPresetTreeItem, PresetDerivedAttributes, \
    ModifyToolUndoCommand, RevertToolUndoCommand, \
    AddPresetUndoCommand, ModifyPresetUndoCommand, RevertPresetUndoCommand, DeletePresetUndoCommand
from .workpiece_model import MaterialType, WorkpieceTreeItem
from .worker import WorkerThread, WorkerThreadPack
from .wall_profile_mgr import WallProfileEditorDlg

debug_inventory_matching = False

class CutterAdapter(object):
    def getLookupData(self, items):
        assert items
        return items[0].document.getToolbitList(cutterTypesForOperationType(items[0].operation))
    def getDescription(self, item):
        return item.description()
    def lookupById(self, id):
        return inventory.IdSequence.lookup(id)    

class AltComboOption(object):
    pass

class SavePresetOption(AltComboOption):
    pass

class LoadPresetOption(AltComboOption):
    pass

class ToolPresetAdapter(object):
    def getLookupData(self, item):
        item = item[0]
        res = []
        if item.cutter:
            pda = PresetDerivedAttributes(item)
            if pda.dirty:
                res.append((SavePresetOption(), "<Convert to a preset>"))
            for preset in item.cutter.presets:
                res.append((preset.id, preset.description()))
            res.append((LoadPresetOption(), "<Load a preset>"))
        return res
    def getDescription(self, item):
        return item.description()
    def lookupById(self, id):
        if isinstance(id, AltComboOption):
            return id
        return inventory.IdSequence.lookup(id)    

class NewProfileOption(AltComboOption):
    pass

class WallProfileAdapter(object):
    def getLookupData(self, item):
        item = item[0]
        res = []
        for profile in inventory.inventory.wall_profiles:
            res.append((profile.id, profile.name))
        res.append((NewProfileOption(), "<New wall profile>"))
        return res
    def lookupById(self, id):
        if isinstance(id, AltComboOption):
            return id
        return inventory.IdSequence.lookup(id)
    def getDescription(self, item):
        return item.description

class CycleTreeItem(CAMTreeItem):
    def __init__(self, document, cutter):
        CAMTreeItem.__init__(self, document, "Tool cycle")
        self.setCheckable(True)
        self.setAutoTristate(True)
        self.cutter = cutter
        self.setCheckState(Qt.CheckState.Checked)
    def toString(self):
        return "Tool cycle"
    @staticmethod
    def listCheckState(items):
        allNo = allYes = True
        for i in items:
            if i.checkState() != Qt.CheckState.Unchecked:
                allNo = False
            if i.checkState() != Qt.CheckState.Checked:
                allYes = False
        if allNo:
            return Qt.CheckState.Unchecked
        if allYes:
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked
    def operCheckState(self):
        return CycleTreeItem.listCheckState(self.items())
    def updateCheckState(self):
        if self.items():
            self.setCheckState(self.operCheckState())
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(f"Use tool: {self.cutter.name}")
        if role == Qt.ToolTipRole:
            return QVariant(f"{self.cutter.description()}")
        if (self.document.current_cutter_cycle is not None) and (self is self.document.current_cutter_cycle):
            return self.format_item_as(role, CAMTreeItem.data(self, role), bold=True)
        return CAMTreeItem.data(self, role)
    def returnKeyPressed(self):
        self.document.selectCutterCycle(self)
    def reorderItem(self, direction: int):
        return self.reorderItemImpl(direction, self.model().invisibleRootItem())
    def canAccept(self, child: CAMTreeItem):
        if not isinstance(child, OperationTreeItem):
            return False
        if not self.cutter:
            return False
        if not (self.cutter.__class__ is child.cutter.__class__):
            return False
        if child.tool_preset is not None:
            for preset in self.cutter.presets:
                if preset.name == child.tool_preset.name:
                    break
            else:
                return False
        return True
    def updateItemAfterMove(self, child):
        if child.cutter != self.cutter:
            child.cutter = self.cutter
            if child.tool_preset:
                for preset in self.cutter.presets:
                    if preset.name == child.tool_preset.name:
                        child.tool_preset = preset
                        break
                else:
                    child.tool_preset = None
    def invalidatedObjects(self, aspect):
        return set([self] + self.document.allOperations(lambda item: item.parent() is self))

def not_none(*args):
    for i in args:
        if i is not None:
            return True
    return False

@CAMTreeItem.register_class
class OperationTreeItem(CAMTreeItem):
    prop_operation = EnumEditableProperty("Operation", "operation", OperationType)
    prop_cutter = RefEditableProperty("Cutter", "cutter", CutterAdapter())
    prop_preset = RefEditableProperty("Tool preset", "tool_preset", ToolPresetAdapter(), allow_none=True, none_value="<none>")
    prop_depth = FloatDistEditableProperty("Depth", "depth", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True, none_value="full depth")
    prop_start_depth = FloatDistEditableProperty("Start Depth", "start_depth", Format.depth_of_cut, unit="mm", min=0, max=100, default_value=0)
    prop_tab_height = FloatDistEditableProperty("Tab Height", "tab_height", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True, none_value="full height")
    prop_tab_count = IntEditableProperty("# Auto Tabs", "tab_count", "%d", min=0, max=100, allow_none=True, none_value="default")
    prop_user_tabs = SetEditableProperty("Tab Locations", "user_tabs", format_func=lambda value: ", ".join([f"({Format.coord(i.x)}, {Format.coord(i.y)})" for i in value]), edit_func=lambda item: item.editTabLocations())
    prop_entry_exit = SetEditableProperty("Entry/Exit points", "entry_exit", format_func=lambda value: ("Applied" if value else "Not applied") + " - double-click to edit", edit_func=lambda item: item.editEntryExit())
    prop_islands = SetEditableProperty("Islands", "islands", edit_func=lambda item: item.editIslands(), format_func=lambda value: f"{len(value)} items - double-click to edit")
    prop_wall_profile = RefEditableProperty("Wall profile", "wall_profile", WallProfileAdapter(), allow_none=True, none_value="<none>")
    prop_dogbones = EnumEditableProperty("Dogbones", "dogbones", cam.dogbone.DogboneMode, allow_none=False)
    prop_pocket_strategy = EnumEditableProperty("Strategy", "pocket_strategy", inventory.PocketStrategy, allow_none=True, none_value="(use preset value)")
    prop_axis_angle = FloatDistEditableProperty("Axis angle", "axis_angle", format=Format.angle, unit='\u00b0', min=0, max=90, allow_none=True)
    prop_eh_diameter = FloatDistEditableProperty("Entry helix %dia", "eh_diameter", format=Format.percent, unit='%', min=0, max=100, allow_none=True)
    prop_entry_mode = EnumEditableProperty("Entry mode", "entry_mode", inventory.EntryMode, allow_none=True, none_value="(use preset value)")

    prop_hfeed = FloatDistEditableProperty("Horizontal feed rate", "hfeed", Format.feed, unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_vfeed = FloatDistEditableProperty("Vertical feed rate", "vfeed", Format.feed, unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_doc = FloatDistEditableProperty("Cut depth/pass", "doc", Format.depth_of_cut, unit="mm", min=0.01, max=100, allow_none=True)
    prop_offset = FloatDistEditableProperty("Offset", "offset", Format.coord, unit="mm", min=-20, max=20, allow_none=True)
    prop_roughing_offset = FloatDistEditableProperty("Roughing offset", "roughing_offset", Format.coord, unit="mm", min=0, max=20, allow_none=True)
    prop_stepover = FloatDistEditableProperty("Stepover", "stepover", Format.percent, unit="%", min=1, max=100, allow_none=True)
    prop_thread_pitch = FloatDistEditableProperty("Thread pitch", "thread_pitch", Format.thread_pitch, unit="mm", min=0.01, max=10, allow_none=True)
    prop_extra_width = FloatDistEditableProperty("Extra width", "extra_width", Format.percent, unit="%", min=0, max=100, allow_none=True)
    prop_trc_rate = FloatDistEditableProperty("Trochoid: step", "trc_rate", Format.percent, unit="%", min=0, max=200, allow_none=True)
    prop_direction = EnumEditableProperty("Direction", "direction", inventory.MillDirection, allow_none=True, none_value="(use preset value)")
    prop_pattern_type = EnumEditableProperty("Pattern type", "pattern_type", FillType, allow_none=False)
    prop_pattern_angle = FloatDistEditableProperty("Pattern angle", "pattern_angle", Format.angle, unit='\u00b0', min=0, max=360, allow_none=False)
    prop_pattern_scale = FloatDistEditableProperty("Pattern scale", "pattern_scale", Format.percent, unit='%', min=10, max=10000, allow_none=False)
    prop_rpm = FloatDistEditableProperty("RPM", "rpm", Format.rpm, unit="rpm", min=0.1, max=100000, allow_none=True)

    def __init__(self, document):
        CAMTreeItem.__init__(self, document)
        self.setCheckable(True)
        self.shape_id = None
        self.orig_shape = None
        self.shape = None
        self.shape_to_refine = None
        self.resetProperties()
        self.isSelected = False
        self.error = None
        self.warning = None
        self.worker = None
        self.prev_diameter = None
        self.cam = None
        self.renderer = None
        self.error = None
        self.warning = None
    def resetProperties(self):
        self.active = True
        self.updateCheckState()
        self.cutter = None
        self.tool_preset = None
        self.operation = OperationType.OUTSIDE_CONTOUR
        self.depth = None
        self.start_depth = 0
        self.tab_height = None
        self.tab_count = None
        self.offset = 0
        self.roughing_offset = 0
        self.pattern_type = FillType.CROSS
        self.pattern_angle = 45
        self.pattern_scale = 100
        self.thread_pitch = None
        self.islands = set()
        self.wall_profile = None
        self.dogbones = cam.dogbone.DogboneMode.DISABLED
        self.user_tabs = set()
        self.entry_exit = []
        PresetDerivedAttributes.resetPresetDerivedValues(self)
    def updateCheckState(self):
        if not self.active and self.cam is not None:
            self.cam = None
            self.document.operationsUpdated.emit()
        self.setCheckState(Qt.CheckState.Checked if self.active else Qt.CheckState.Unchecked)
    def editTabLocations(self):
        self.document.tabEditRequested.emit(self)
    def editIslands(self):
        self.document.islandsEditRequested.emit(self)
    def editEntryExit(self):
        self.document.entryExitEditRequested.emit(self)
    def editEdgeProfile(self):
        print ("edge profile")
    def areIslandsEditable(self):
        if self.operation not in (OperationType.POCKET, OperationType.SIDE_MILL, OperationType.FACE, OperationType.V_CARVE, OperationType.PATTERN_FILL):
            return False
        return not isinstance(self.orig_shape, DrawingTextTreeItem)
    def usesShape(self, shape_id):
        if self.shape_id == shape_id:
            return True
        for i in self.islands:
            if i == shape_id:
                return True
        return False
    def toString(self):
        return OperationType.toString(self.operation)
    def isPropertyValid(self, name):
        is_contour = self.operation in (OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR)
        has_islands = OperationType.has_islands(self.operation)
        if not is_contour and name in ['tab_height', 'tab_count', 'extra_width', 'trc_rate', 'user_tabs', 'entry_exit']:
            return False
        if not has_islands and name == 'pocket_strategy':
            return False
        if not self.areIslandsEditable() and name == 'islands':
            return False
        if not OperationType.has_stepover(self.operation) and name == 'stepover':
            return False
        if not OperationType.has_entry_helix(self.operation) and name == 'eh_diameter':
            return False
        if (not has_islands or self.pocket_strategy not in [inventory.PocketStrategy.AXIS_PARALLEL, inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG]) and name == 'axis_angle':
            return False
        if self.operation in (OperationType.ENGRAVE, OperationType.DRILLED_HOLE, OperationType.INTERPOLATED_HOLE) and name == 'dogbones':
            return False
        if self.operation == OperationType.ENGRAVE and name in ['direction']:
            return False
        if self.operation == OperationType.DRILLED_HOLE and name in ['hfeed', 'trc_rate', 'direction']:
            return False
        if self.operation != OperationType.PATTERN_FILL and name in ['pattern_angle', 'pattern_scale', 'pattern_type', 'pattern_x_ofs', 'pattern_y_ofs']:
            return False
        if self.operation == OperationType.INSIDE_THREAD and name in ['hfeed', 'trc_rate', 'direction', 'dogbones', 'offset', 'roughing_offset', 'entry_mode', 'doc']:
            return False
        if self.operation != OperationType.INSIDE_THREAD and name in ['thread_pitch']:
            return False
        return True
    def getValidEnumValues(self, name):
        if name == 'pocket_strategy' and self.operation == OperationType.SIDE_MILL:
            return [inventory.PocketStrategy.HSM_PEEL, inventory.PocketStrategy.HSM_PEEL_ZIGZAG]
        if name == 'operation':
            if self.cutter is not None and isinstance(self.cutter, inventory.DrillBitCutter):
                return [OperationType.DRILLED_HOLE]
            if self.cutter is not None and isinstance(self.cutter, inventory.ThreadMillCutter):
                return [OperationType.INSIDE_THREAD] if isinstance(self.orig_shape, DrawingCircleTreeItem) else []
            if isinstance(self.orig_shape, DrawingCircleTreeItem):
                return [OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR, OperationType.POCKET, OperationType.SIDE_MILL, OperationType.ENGRAVE, OperationType.INTERPOLATED_HOLE, OperationType.DRILLED_HOLE, OperationType.FACE, OperationType.PATTERN_FILL]
            if isinstance(self.orig_shape, DrawingPolylineTreeItem) or isinstance(self.orig_shape, DrawingTextTreeItem):
                if self.orig_shape.closed:
                    return [OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR, OperationType.POCKET, OperationType.SIDE_MILL, OperationType.ENGRAVE, OperationType.REFINE, OperationType.FACE, OperationType.V_CARVE, OperationType.PATTERN_FILL]
                else:
                    return [OperationType.ENGRAVE]
    def getDefaultPropertyValue(self, name):
        if isinstance(self.cutter, inventory.DrillBitCutter):
            if name == 'hfeed' or name == 'stepover' or name == 'direction':
                return None
        pda = PresetDerivedAttributes(self)
        return getattr(pda, name, None)
    def store(self):
        dump = CAMTreeItem.store(self)
        dump['active'] = self.active
        dump['shape_id'] = self.shape_id
        dump['islands'] = list(sorted(self.islands))
        dump['user_tabs'] = list(sorted([(pt.x, pt.y) for pt in self.user_tabs]))
        dump['entry_exit'] = [[(pts[0].x, pts[0].y), (pts[1].x, pts[1].y)] for pts in self.entry_exit]
        dump['cutter'] = self.cutter.id
        dump['tool_preset'] = self.tool_preset.id if self.tool_preset else None
        dump['wall_profile'] = self.wall_profile.id if self.wall_profile is not None else None
        return dump
    def class_specific_load(self, dump):
        self.shape_id = dump.get('shape_id', None)
        self.islands = set(dump.get('islands', []))
        self.user_tabs = set(geom.PathPoint(i[0], i[1]) for i in dump.get('user_tabs', []))
        self.entry_exit = [(geom.PathPoint(i[0][0], i[0][1]), geom.PathPoint(i[1][0], i[1][1])) for i in dump.get('entry_exit', [])]
        self.active = dump.get('active', True)
        self.wall_profile = dump.get('wall_profile', None)
        if self.wall_profile is not None:
            self.wall_profile = inventory.IdSequence.lookup(self.wall_profile)
        self.updateCheckState()
    def properties(self):
        return [self.prop_operation, self.prop_cutter, self.prop_preset, 
            self.prop_depth, self.prop_start_depth, 
            self.prop_tab_height, self.prop_tab_count, self.prop_user_tabs,
            self.prop_entry_exit, self.prop_wall_profile,
            self.prop_dogbones,
            self.prop_extra_width,
            self.prop_islands,
            self.prop_pocket_strategy, self.prop_axis_angle,
            self.prop_direction,
            self.prop_doc, self.prop_hfeed, self.prop_vfeed,
            self.prop_offset, self.prop_roughing_offset,
            self.prop_stepover, self.prop_thread_pitch, self.prop_eh_diameter, self.prop_entry_mode,
            self.prop_trc_rate, self.prop_pattern_type, self.prop_pattern_angle, self.prop_pattern_scale, self.prop_rpm]
    def setPropertyValue(self, name, value):
        if name == 'tool_preset':
            if isinstance(value, SavePresetOption):
                from . import cutter_mgr
                pda = PresetDerivedAttributes(self)
                preset = pda.toPreset("")
                dlg = cutter_mgr.CreateEditPresetDialog(parent=None, title="Create a preset from operation attributes", preset=preset, cutter_type=type(self.cutter), cutter_for_add=self.cutter)
                if dlg.exec_():
                    self.tool_preset = dlg.result
                    self.tool_preset.toolbit = self.cutter
                    self.cutter.presets.append(self.tool_preset)
                    pda.resetPresetDerivedValues(self)
                    self.document.refreshToolList()
                    self.document.selectPresetAsDefault(self.tool_preset.toolbit, self.tool_preset)
                return
            if isinstance(value, LoadPresetOption):
                from . import cutter_mgr
                cutter_type = cutterTypesForOperationType(self.operation)
                if cutter_mgr.selectCutter(None, cutter_mgr.SelectCutterDialog, self.document, cutter_type):
                    if self.cutter is not self.document.current_cutter_cycle.cutter:
                        self.document.opMoveItem(self.parent(), self, self.document.current_cutter_cycle, 0)
                        self.cutter = self.document.current_cutter_cycle.cutter
                    self.tool_preset = self.document.default_preset_by_tool.get(self.cutter, None)
                    self.startUpdateCAM()
                    self.document.refreshToolList()
                return
        if name == 'wall_profile':
            if isinstance(value, NewProfileOption):
                profile = inventory.InvWallProfile.new(None, "", "")
                dlg = WallProfileEditorDlg(parent=None, title="Create a new wall profile", profile=profile)
                if dlg.exec_():
                    inventory.inventory.wall_profiles.append(profile)
                    value = profile
                else:
                    profile.forget()
                    return
        if name == 'direction' and self.entry_exit:
            pda = PresetDerivedAttributes(self)
            old_orientation = pda.direction
        setattr(self, name, value)
        if name == 'direction' and self.entry_exit:
            pda = PresetDerivedAttributes(self)
            if pda.direction != old_orientation:
                self.entry_exit = [(e, s) for s, e in self.entry_exit]
        self.onPropertyValueSet(name)
    def onPropertyValueSet(self, name):
        if name == 'cutter' and self.parent().cutter != self.cutter:
            self.parent().takeRow(self.row())
            cycle = self.document.cycleForCutter(self.cutter)
            if cycle:
                if self.operation == OperationType.OUTSIDE_CONTOUR:
                    cycle.appendRow(self)
                else:
                    cycle.insertRow(0, self)
        if name == 'cutter' and self.tool_preset and self.tool_preset.toolbit != self.cutter:
            # Find a matching preset
            for i in self.cutter.presets:
                if i.name == self.tool_preset.name:
                    self.tool_preset = i
                    break
            else:
                self.tool_preset = None
        self.startUpdateCAM()
        self.emitDataChanged()
    def operationTypeLabel(self):
        if self.operation == OperationType.DRILLED_HOLE:
            if self.cutter:
                if self.orig_shape and self.cutter.diameter < 2 * self.orig_shape.r - 0.2:
                    return f"Pilot Drill {self.cutter.diameter:0.1f}mm" if self.cutter else ""
                if self.orig_shape and self.cutter.diameter > 2 * self.orig_shape.r + 0.2:
                    return f"Oversize Drill {self.cutter.diameter:0.1f}mm" if self.cutter else ""
            return OperationType.toString(self.operation) + (f" {self.cutter.diameter:0.1f}mm" if self.cutter else "")
        if self.operation == OperationType.INSIDE_THREAD:
            pitch = self.thread_pitch or self.threadPitch()
            opStr = OperationType.toString(self.operation)
            if pitch is not None and pitch > self.cutter.max_pitch:
                opStr = "Internal pre-thread"
            pitch = "?" if pitch is None else Format.thread_pitch(pitch, brief=True)
            return opStr + (f" {Format.coord(2 * self.orig_shape.r, brief=True)} x {pitch}" if self.cutter else "")
        return OperationType.toString(self.operation)
    def data(self, role):
        if role == Qt.DisplayRole:
            preset_if = ", " + self.tool_preset.name if self.tool_preset else ", no preset"
            return QVariant(self.operationTypeLabel() + ": " + self.orig_shape.label() + ", " + ((f"{self.depth:0.2f} mm") if self.depth is not None else "full") + f" depth{preset_if}")
        if role == Qt.DecorationRole and self.error is not None:
            return QVariant(QApplication.instance().style().standardIcon(QStyle.SP_MessageBoxCritical))
        if role == Qt.DecorationRole and self.warning is not None:
            return QVariant(QApplication.instance().style().standardIcon(QStyle.SP_MessageBoxWarning))
        if role == Qt.ToolTipRole:
            if self.error is not None:
                return QVariant(self.error)
            elif self.warning is not None:
                return QVariant(self.warning)
            else:
                return QVariant(self.operationTypeLabel() + ": " + self.orig_shape.label() + ", " + ((Format.depth_of_cut(self.depth) + " mm") if self.depth is not None else "full") + f" depth, preset: {self.tool_preset.name if self.tool_preset else 'none'}")
        return CAMTreeItem.data(self, role)
    def addWarning(self, warning):
        if self.warning is None:
            self.warning = ""
        else:
            self.warning += "\n"
        self.warning += warning
        self.emitDataChanged()
    def updateOrigShape(self):
        self.orig_shape = self.document.drawing.itemById(self.shape_id) if self.shape_id is not None else None
    def resetRenderedState(self):
        self.renderer = None
        self.document.operationsUpdated.emit()
    def startUpdateCAM(self):
        with Spinner():
            self.last_progress = (1, 100000)
            self.error = None
            self.warning = None
            self.cam = None
            self.renderer = None
            self.updateOrigShape()
            self.cancelWorker()
            if not self.cutter:
                self.error = "Cutter not set"
                self.last_progress = (1, 1)
                return
            if not self.active:
                self.last_progress = (1, 1)
                # Operation not enabled
                return
            self.updateCAMWork()
    def pollForUpdateCAM(self):
        if not self.worker:
            return self.last_progress
        self.last_progress = self.worker.getProgress()
        if self.worker and not self.worker.is_alive():
            self.worker.join()
            if self.error is None and self.worker.exception is not None:
                self.error = self.worker.exception_text
            self.worker = None
            self.document.operationsUpdated.emit()
            self.emitDataChanged()
        return self.last_progress
    def cancelWorker(self):
        if self.worker:
            self.worker.cancel()
            self.worker.join()
            self.worker = None
            self.last_progress = None
    def operationFunc(self, shape, pda, parent_cam):
        translation = self.document.drawing.translation()
        if len(self.user_tabs):
            tabs = self.user_tabs
        else:
            cs = self.document.config_settings
            tabs = self.tab_count if self.tab_count is not None else shape.default_tab_count(cs.min_tabs, cs.max_tabs, cs.tab_dist, cs.tab_min_length)
        if self.document.checkUpdateSuspended(self):
            return
        if self.operation == OperationType.OUTSIDE_CONTOUR:
            if pda.trc_rate:
                return lambda: parent_cam.outside_contour_trochoidal(shape, pda.extra_width / 100.0, pda.trc_rate / 100.0, tabs=tabs, entry_exit=self.entry_exit)
            else:
                return lambda: parent_cam.outside_contour(shape, tabs=tabs, widen=pda.extra_width / 50.0, entry_exit=self.entry_exit)
        elif self.operation == OperationType.INSIDE_CONTOUR:
            if pda.trc_rate:
                return lambda: parent_cam.inside_contour_trochoidal(shape, pda.extra_width / 100.0, pda.trc_rate / 100.0, tabs=tabs, entry_exit=self.entry_exit)
            else:
                return lambda: parent_cam.inside_contour(shape, tabs=tabs, widen=pda.extra_width / 50.0, entry_exit=self.entry_exit)
        elif self.operation == self.operation == OperationType.REFINE and self.shape_to_refine is not None:
            assert pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL or pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL_ZIGZAG
            if self.is_external:
                if isinstance(self.shape_to_refine, dict):
                    return lambda: parent_cam.outside_peel_hsm(shape, shape_to_refine=self.shape_to_refine.get(shape, None))
                else:
                    return lambda: parent_cam.outside_peel_hsm(shape, shape_to_refine=self.shape_to_refine)
            else:
                if isinstance(self.shape_to_refine, dict):
                    return lambda: parent_cam.pocket_hsm(shape, shape_to_refine=self.shape_to_refine.get(shape, None))
                else:
                    return lambda: parent_cam.pocket_hsm(shape, shape_to_refine=self.shape_to_refine)
        elif self.operation == OperationType.POCKET or self.operation == OperationType.REFINE:
            if pda.pocket_strategy == inventory.PocketStrategy.CONTOUR_PARALLEL:
                return lambda: parent_cam.pocket(shape)
            elif pda.pocket_strategy == inventory.PocketStrategy.AXIS_PARALLEL or pda.pocket_strategy == inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG:
                return lambda: parent_cam.pocket_axis_parallel(shape)
            elif pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL or pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL_ZIGZAG:
                return lambda: parent_cam.pocket_hsm(shape)
        elif self.operation == OperationType.FACE:
            if pda.pocket_strategy == inventory.PocketStrategy.CONTOUR_PARALLEL:
                return lambda: parent_cam.face_mill(shape)
            elif pda.pocket_strategy == inventory.PocketStrategy.AXIS_PARALLEL or pda.pocket_strategy == inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG:
                return lambda: parent_cam.face_mill_axis_parallel(shape)
            elif pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL or pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL_ZIGZAG:
                return lambda: parent_cam.outside_peel_hsm(shape)
        elif self.operation == OperationType.SIDE_MILL:
            if pda.pocket_strategy == inventory.PocketStrategy.CONTOUR_PARALLEL:
                return lambda: parent_cam.outside_peel(shape)
            elif pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL or pda.pocket_strategy == inventory.PocketStrategy.HSM_PEEL_ZIGZAG:
                return lambda: parent_cam.outside_peel_hsm(shape)
            else:
                raise ValueError("Strategy not supported for outside cuts")
        elif self.operation == OperationType.ENGRAVE:
            return lambda: parent_cam.engrave(shape)
        elif self.operation == OperationType.INTERPOLATED_HOLE:
            return lambda: parent_cam.helical_drill(self.orig_shape.centre.x + translation[0], self.orig_shape.centre.y + translation[1], 2 * self.orig_shape.r)
        elif self.operation == OperationType.DRILLED_HOLE:
            return lambda: parent_cam.peck_drill(self.orig_shape.centre.x + translation[0], self.orig_shape.centre.y + translation[1])
        elif self.operation == OperationType.V_CARVE:
            return lambda: parent_cam.vcarve(shape)
        elif self.operation == OperationType.PATTERN_FILL:
            return lambda: parent_cam.pattern_fill(shape, FillType.toItem(self.pattern_type, 2), self.pattern_angle, self.pattern_scale / 100.0, 0, 0)
        elif self.operation == OperationType.INSIDE_THREAD:
            return lambda: parent_cam.thread_mill(self.orig_shape.centre.x + translation[0], self.orig_shape.centre.y + translation[1], 2 * self.orig_shape.r, self.threadPitch())
        raise ValueError("Unsupported operation")
    DEFAULT_METRIC_PITCHES = {
        1.6 : 0.35,
        2   : 0.4,
        2.5 : 0.45,
        3   : 0.5,
        3.5 : 0.6,
        4   : 0.7,
        5   : 0.8,
        6   : 1,
        8   : 1.25,
        10  : 1.5,
        12  : 1.75,
        14  : 2,
        16  : 2,
        18  : 2.5,
        20  : 2.5
    }
    def threadPitch(self):
        if self.thread_pitch:
            return self.thread_pitch
        d = self.orig_shape.r * 2
        for diameter, pitch in self.DEFAULT_METRIC_PITCHES.items():
            if abs(diameter - d) < 0.1:
                return pitch
        return None
    def shapeToRefine(self, shape, previous, is_external):
        if is_external:
            return cam.pocket.shape_to_refine_external(shape, previous)
        else:
            return cam.pocket.shape_to_refine_internal(shape, previous)
    def refineShape(self, shape, previous, current, min_entry_dia, is_external):
        if is_external:
            return cam.pocket.refine_shape_external(shape, previous, current, min_entry_dia)
        else:
            return cam.pocket.refine_shape_internal(shape, previous, current, min_entry_dia)
    def createShapeObject(self):
        translation = self.document.drawing.translation()
        self.shape = self.orig_shape.translated(*translation).toShape()
        if not isinstance(self.shape, list) and OperationType.has_islands(self.operation):
            extra_shapes = []
            for island in self.islands:
                item = self.document.drawing.itemById(island).translated(*translation).toShape()
                if isinstance(item, list):
                    for i in item:
                        self.shape.add_island(i.boundary)
                        if i.islands:
                            extra_shapes += [shapes.Shape(j, True) for j in i.islands]
                elif item.closed:
                    self.shape.add_island(item.boundary)
                    if item.islands:
                        extra_shapes += [shapes.Shape(j, True) for j in item.islands]
            if extra_shapes:
                self.shape = [self.shape] + extra_shapes
    def addDogbonesToIslands(self, shape, tool):
        new_islands = []
        for i in shape.islands:
            new_shapes = cam.dogbone.add_dogbones(shapes.Shape(i, True), tool, True, self.dogbones, False)
            if isinstance(new_shapes, list):
                new_islands += [j.boundary for j in new_shapes]
            else:
                new_islands.append(new_shapes.boundary)
        shape.islands = new_islands
    def updateCAMWork(self):
        try:
            translation = self.document.drawing.translation()
            errors = []
            if self.orig_shape:
                self.createShapeObject()
            else:
                self.shape = None
            thickness = self.document.material.thickness
            depth = self.depth if self.depth is not None else thickness
            if depth is None or depth == 0:
                raise ValueError("Neither material thickness nor cut depth is set")
            start_depth = self.start_depth if self.start_depth is not None else 0
            if self.cutter.length and depth > self.cutter.length:
                self.addWarning(f"Cut depth ({depth:0.1f} mm) greater than usable flute length ({self.cutter.length:0.1f} mm)")
            # Only checking for end mills because most drill bits have a V tip and may require going slightly past
            if thickness and isinstance(self.cutter, inventory.EndMillCutter) and depth > thickness:
                self.addWarning(f"Cut depth ({depth:0.1f} mm) greater than material thickness ({thickness:0.1f} mm)")
            if self.operation == OperationType.DRILLED_HOLE and self.cutter.diameter > 2 * self.orig_shape.r + 0.01:
                self.addWarning(f"Cutter diameter ({self.cutter.diameter:0.1f} mm) greater than hole diameter ({2 * self.orig_shape.r:0.1f} mm)")
            tab_depth = max(start_depth, depth - self.tab_height) if self.tab_height is not None else start_depth

            pda = PresetDerivedAttributes(self, addError=lambda error: errors.append(error))
            pda.validate(errors)
            if errors:
                raise ValueError("\n".join(errors))
            if pda.rpm is not None:
                mp = self.document.gcode_machine_params
                if mp.min_rpm is not None and pda.rpm < mp.min_rpm:
                    self.addWarning(f"Spindle speed {pda.rpm:1f} lower than the minimum of {mp.min_rpm:1f}")
                if mp.max_rpm is not None and pda.rpm > mp.max_rpm:
                    self.addWarning(f"Spindle speed {pda.rpm:1f} higher than the maximum of {mp.max_rpm:1f}")

            if isinstance(self.cutter, inventory.ThreadMillCutter):
                tool = milling_tool.ThreadCutter(self.cutter.diameter, self.cutter.min_pitch, self.cutter.max_pitch, self.cutter.flutes, self.cutter.length, pda.rpm, pda.vfeed, pda.stepover / 100.0, self.cutter.thread_angle)
                self.gcode_props = gcodeops.OperationProps(-depth, -start_depth, -tab_depth, 0)
            elif isinstance(self.cutter, inventory.EndMillCutter):
                wall_profile = self.wall_profile.shape if self.wall_profile else None
                is_tapered = self.cutter.shape == inventory.EndMillShape.TAPERED
                tool = milling_tool.Tool(self.cutter.diameter, pda.hfeed, pda.vfeed, pda.doc, stepover=pda.stepover / 100.0,
                    climb=(pda.direction == inventory.MillDirection.CLIMB), min_helix_ratio=pda.eh_diameter / 100.0, tip_angle=self.cutter.angle if is_tapered else 0, tip_diameter=self.cutter.tip_diameter if is_tapered else 0)
                zigzag = pda.pocket_strategy in (inventory.PocketStrategy.HSM_PEEL_ZIGZAG, inventory.PocketStrategy.AXIS_PARALLEL_ZIGZAG, wall_profile)
                self.gcode_props = gcodeops.OperationProps(-depth, -start_depth, -tab_depth, pda.offset, zigzag, pda.axis_angle * math.pi / 180, pda.roughing_offset, 
                    pda.entry_mode != inventory.EntryMode.PREFER_RAMP, wall_profile)
            elif isinstance(self.cutter, inventory.DrillBitCutter):
                tool = milling_tool.Tool(self.cutter.diameter, 0, pda.vfeed, pda.doc)
                self.gcode_props = gcodeops.OperationProps(-depth, -start_depth, -tab_depth, 0)
            else:
                assert False, f"Unknown cutter type: {type(self.cutter)}"
            self.gcode_props.rpm = pda.rpm
            if self.dogbones and self.operation == OperationType.SIDE_MILL and not isinstance(self.shape, list):
                self.addDogbonesToIslands(self.shape, tool)
            if self.dogbones and self.operation not in (OperationType.ENGRAVE, OperationType.DRILLED_HOLE, OperationType.INTERPOLATED_HOLE, OperationType.SIDE_MILL):
                is_outside = self.operation == OperationType.OUTSIDE_CONTOUR
                is_refine = self.operation == OperationType.REFINE
                is_pocket = self.operation == OperationType.POCKET or self.operation == OperationType.PATTERN_FILL or self.operation == OperationType.V_CARVE
                if isinstance(self.shape, list):
                    res = []
                    for i in self.shape:
                        res.append(cam.dogbone.add_dogbones(i, tool, is_outside, self.dogbones, is_refine))
                    if is_pocket:
                        for i in res:
                            self.addDogbonesToIslands(self.shape, tool)
                    self.shape = res
                else:
                    self.shape = cam.dogbone.add_dogbones(self.shape, tool, is_outside, self.dogbones, is_refine)
                    if is_pocket:
                        self.addDogbonesToIslands(self.shape, tool)
            if self.operation == OperationType.REFINE:
                diameter_plus = self.cutter.diameter + 2 * pda.offset
                prev_diameter, prev_operation, islands = self.document.largerDiameterForShape(self.orig_shape, diameter_plus)
                self.prev_diameter = prev_diameter
                if prev_diameter is None:
                    if pda.offset:
                        raise ValueError(f"No matching milling operation to refine with cutter diameter {Format.cutter_dia(self.cutter.diameter)} and offset {Format.coord(pda.offset)}")
                    else:
                        raise ValueError(f"No matching milling operation to refine with cutter diameter {Format.cutter_dia(self.cutter.diameter)}")
                is_hsm = pda.pocket_strategy in (inventory.PocketStrategy.HSM_PEEL, inventory.PocketStrategy.HSM_PEEL_ZIGZAG)
                if prev_operation.operation == OperationType.SIDE_MILL:
                    # Make up a list of shapes from shape's islands?
                    raise ValueError("Refining side milling operations is not supported yet")
                self.is_external = (prev_operation.operation == OperationType.OUTSIDE_CONTOUR)
                self.shape_to_refine = None
                if islands and not isinstance(self.shape, list):
                    for island in islands:
                        item = self.document.drawing.itemById(island).translated(*translation).toShape()
                        if item.closed:
                            self.shape.add_island(item.boundary)
                if is_hsm:
                    if isinstance(self.shape, list):
                        self.shape_to_refine = { i : self.shapeToRefine(i, prev_diameter, self.is_external) for i in self.shape }
                    else:
                        self.shape_to_refine = self.shapeToRefine(self.shape, prev_diameter, self.is_external)
                elif isinstance(self.shape, list):
                    res = []
                    for i in self.shape:
                        res += self.refineShape(i, prev_diameter, diameter_plus, tool.min_helix_diameter, self.is_external)
                    self.shape = res
                else:
                    self.shape = self.refineShape(self.shape, prev_diameter, diameter_plus, tool.min_helix_diameter, self.is_external)
            else:
                self.prev_diameter = None
            if isinstance(self.shape, list) and len(self.shape) == 1:
                self.shape = self.shape[0]
            self.cam = self.createOpsObject(tool)
            self.renderer = canvas.OperationsRendererWithSelection(self)
            if self.shape:
                if isinstance(self.shape, list):
                    threadDataList = []
                    for shape in self.shape:
                        subcam = self.createOpsObject(tool)
                        func = self.operationFunc(shape, pda, subcam)
                        if func is not None:
                            threadDataList.append((subcam, func))
                    if threadDataList:
                        self.worker = WorkerThreadPack(self, threadDataList, self.cam)
                        self.worker.start()
                else:
                    threadFunc = self.operationFunc(self.shape, pda, self.cam)
                    if threadFunc:
                        self.worker = WorkerThread(self, threadFunc, self.cam)
                        self.worker.start()
            self.error = None
        except Exception as e:
            self.cam = None
            self.renderer = None
            self.error = str(e)
            self.document.operationsUpdated.emit()
            if not isinstance(e, ValueError):
                raise
    def createOpsObject(self, tool):
        return gcodeops.Operations(self.document.gcode_machine_params, tool, self.gcode_props, self.document.material.thickness)
    def reorderItem(self, direction):
        index = self.reorderItemImpl(direction, self.parent())
        if index is not None:
            return index
        if direction < 0:
            parentRow = self.parent().row() - 1
            while parentRow >= 0:
                otherParent = self.model().invisibleRootItem().child(parentRow)
                if otherParent.canAccept(self):
                    self.document.opMoveItem(self.parent(), self, otherParent, otherParent.rowCount())
                    return self.index()
                parentRow -= 1
            return None
        elif direction > 0:
            parentRow = self.parent().row() + 1
            while parentRow < self.model().invisibleRootItem().rowCount():
                otherParent = self.model().invisibleRootItem().child(parentRow)
                if otherParent.canAccept(self):
                    self.document.opMoveItem(self.parent(), self, otherParent, 0)
                    return self.index()
                parentRow += 1
            return None
    def invalidatedObjects(self, aspect):
        if aspect == InvalidateAspect.CAM:
            return set([self] + self.document.refineOpsForShapes(set([self.shape_id])))
        return set([self])
    def contourOrientation(self):
        pda = PresetDerivedAttributes(self)
        if self.operation == OperationType.OUTSIDE_CONTOUR:
            return pda.direction == inventory.MillDirection.CONVENTIONAL
        else:
            return pda.direction == inventory.MillDirection.CLIMB

class OperationsModel(QStandardItemModel):
    def __init__(self, document):
        QStandardItemModel.__init__(self)
        self.document = document
    def findItem(self, item):
        index = self.indexFromItem(item)
        return item.parent() or self.invisibleRootItem(), index.row()
    def removeItemAt(self, row):
        self.takeRow(row)
        return row

class AddOperationUndoCommand(QUndoCommand):
    def __init__(self, document, item, parent, row):
        if isinstance(item, OperationTreeItem):
            QUndoCommand.__init__(self, "Create " + item.toString())
        else:
            QUndoCommand.__init__(self, "Add tool cycle")
        self.document = document
        self.item = item
        self.parent = parent
        self.row = row
    def undo(self):
        self.parent.takeRow(self.row)
        self.document.refreshRefineForOpOrCycle(self.item)
        if isinstance(self.item, CycleTreeItem):
            del self.document.project_toolbits[self.item.cutter.name]
            self.item.document.refreshToolList()
    def redo(self):
        self.parent.insertRow(self.row, self.item)
        self.document.refreshRefineForOpOrCycle(self.item)
        if isinstance(self.item, CycleTreeItem):
            self.document.project_toolbits[self.item.cutter.name] = self.item.cutter
            self.item.document.refreshToolList()

class DeleteCycleUndoCommand(QUndoCommand):
    def __init__(self, document, cycle):
        QUndoCommand.__init__(self, "Delete cycle: " + cycle.cutter.name)
        self.document = document
        self.cycle = cycle
        self.row = None
        self.def_preset = None
        self.was_default = False
    def undo(self):
        self.document.operModel.invisibleRootItem().insertRow(self.row, self.cycle)
        self.document.project_toolbits[self.cycle.cutter.name] = self.cycle.cutter
        if self.was_default:
            self.document.selectCutterCycle(self.cycle)
        if self.def_preset is not None:
            self.document.default_preset_by_tool[self.cycle.cutter] = self.def_preset
        self.document.refreshRefineForOpOrCycle(self.cycle)
        self.document.refreshToolList()
    def redo(self):
        self.row = self.cycle.row()
        self.was_default = self.cycle is self.document.current_cutter_cycle
        self.def_preset = self.document.default_preset_by_tool.get(self.cycle.cutter, None)
        self.document.operModel.invisibleRootItem().takeRow(self.row)
        self.document.refreshRefineForOpOrCycle(self.cycle)
        del self.document.project_toolbits[self.cycle.cutter.name]
        if self.cycle.cutter in self.document.default_preset_by_tool:
            del self.document.default_preset_by_tool[self.cycle.cutter]
        self.document.refreshToolList()

class DeleteOperationUndoCommand(QUndoCommand):
    def __init__(self, document, item, parent, row):
        QUndoCommand.__init__(self, "Delete " + item.toString())
        self.document = document
        self.item = item
        self.deleted_cutter = None
        self.parent = parent
        self.row = row
    def undo(self):
        self.parent.insertRow(self.row, self.item)
        self.document.refreshRefineForOpOrCycle(self.item)
        if isinstance(self.item, CycleTreeItem) and self.deleted_cutter:
            self.document.project_toolbits[self.item.cutter.name] = self.deleted_cutter
            self.document.refreshToolList()
        elif isinstance(self.item, OperationTreeItem):
            self.item.startUpdateCAM()
    def redo(self):
        self.parent.takeRow(self.row)
        self.document.refreshRefineForOpOrCycle(self.item)
        if isinstance(self.item, CycleTreeItem):
            # Check if there are other users of the same tool
            if self.document.cycleForCutter(self.item.cutter) is None:
                self.deleted_cutter = self.document.project_toolbits[self.item.cutter.name]
                del self.document.project_toolbits[self.item.cutter.name]
                self.document.refreshToolList()
        else:
            self.item.cancelWorker()

class ActiveSetUndoCommand(QUndoCommand):
    def __init__(self, changes):
        QUndoCommand.__init__(self, "Toggle active status")
        self.changes = changes
    def undo(self):
        self.applyChanges(True)
    def redo(self):
        self.applyChanges(False)
    def applyChanges(self, reverse):
        changedOpers = {}
        for item, state in self.changes:
            changedOpers[item.parent().row()] = item.parent()
            item.active = state ^ reverse
            item.updateCheckState()
        for item, state in self.changes:
            item.startUpdateCAM()
        for parent in changedOpers.values():
            parent.updateCheckState()

class MoveItemUndoCommand(QUndoCommand):
    def __init__(self, oldParent, child, newParent, pos):
        QUndoCommand.__init__(self, "Move item")
        self.oldParent = oldParent
        self.oldPos = child.row()
        self.child = child
        self.newParent = newParent
        self.newPos = pos
    def undo(self):
        self.newParent.takeRow(self.newPos)
        self.oldParent.insertRow(self.oldPos, self.child)
        if hasattr(self.newParent, 'updateItemAfterMove'):
            self.oldParent.updateItemAfterMove(self.child)
    def redo(self):
        self.oldParent.takeRow(self.oldPos)
        self.newParent.insertRow(self.newPos, self.child)
        if hasattr(self.newParent, 'updateItemAfterMove'):
            self.newParent.updateItemAfterMove(self.child)

class DocumentModel(QObject):
    propertyChanged = pyqtSignal([CAMTreeItem, str])
    cutterSelected = pyqtSignal([CycleTreeItem])
    tabEditRequested = pyqtSignal([OperationTreeItem])
    islandsEditRequested = pyqtSignal([OperationTreeItem])
    entryExitEditRequested = pyqtSignal([OperationTreeItem])
    polylineEditRequested = pyqtSignal([DrawingPolylineTreeItem])
    toolListRefreshed = pyqtSignal([])
    operationsUpdated = pyqtSignal([])
    shapesCreated = pyqtSignal([list])
    shapesDeleted = pyqtSignal([list])
    shapesUpdated = pyqtSignal([])
    projectCleared = pyqtSignal([])
    projectLoaded = pyqtSignal([])
    drawingImported = pyqtSignal([])
    def __init__(self, config_settings):
        QObject.__init__(self)
        self.config_settings = config_settings
        self.undoStack = QUndoStack(self)
        self.material = WorkpieceTreeItem(self)
        self.makeMachineParams()
        self.drawing = DrawingTreeItem(self)
        self.filename = None
        self.drawing_filename = None
        self.current_cutter_cycle = None
        self.project_toolbits = {}
        self.default_preset_by_tool = {}
        self.shapes_to_revisit = set()
        self.progress_dialog_displayed = False
        self.update_suspended = None
        self.update_suspended_dirty = False
        self.tool_list = ToolListTreeItem(self)
        self.shapeModel = QStandardItemModel()
        self.shapeModel.setHorizontalHeaderLabels(["Input object"])
        self.shapeModel.appendRow(self.material)
        self.shapeModel.appendRow(self.tool_list)
        self.shapeModel.appendRow(self.drawing)

        self.operModel = OperationsModel(self)
        self.operModel.setHorizontalHeaderLabels(["Operation"])
        self.operModel.dataChanged.connect(self.operDataChanged)
        self.operModel.rowsInserted.connect(self.operRowsInserted)
        self.operModel.rowsRemoved.connect(self.operRowsRemoved)
        self.operModel.rowsAboutToBeRemoved.connect(self.operRowsAboutToBeRemoved)

    def reinitDocument(self):
        self.undoStack.clear()
        self.undoStack.setClean()
        self.material.resetProperties()
        self.makeMachineParams()
        self.current_cutter_cycle = None
        self.project_toolbits = {}
        self.default_preset_by_tool = {}
        self.update_suspended = None
        self.update_suspended_dirty = False
        self.refreshToolList()
        self.drawing.reset()
        self.drawing.removeRows(0, self.drawing.rowCount())
        self.operModel.removeRows(0, self.operModel.rowCount())
    def refreshToolList(self):
        self.tool_list.reset()
        self.toolListRefreshed.emit()
    def allCycles(self):
        return [self.operModel.item(i) for i in range(self.operModel.rowCount())]
    def store(self):
        #cutters = set(self.forEachOperation(lambda op: op.cutter))
        #presets = set(self.forEachOperation(lambda op: op.tool_preset))
        data = {}
        data['material'] = self.material.store()
        data['tools'] = [i.store() for i in self.project_toolbits.values()]
        data['tool_presets'] = [j.store() for i in self.project_toolbits.values() for j in i.presets]
        data['default_presets'] = [{'tool_id' : k.id, 'preset_id' : v.id} for k, v in self.default_preset_by_tool.items() if v is not None]
        data['drawing'] = { 'header' : self.drawing.store(), 'items' : [item.store() for item in self.drawing.items()] }
        data['operation_cycles'] = [ { 'tool_id' : cycle.cutter.id, 'is_current' : (self.current_cutter_cycle is cycle), 'operations' : [op.store() for op in cycle.items()] } for cycle in self.allCycles() ]
        wall_profiles_used = set([op.wall_profile.id for op in self.allOperations()])
        data['wall_profiles'] = [profile.store() for profile in inventory.inventory.wall_profiles if profile.id in wall_profiles_used]
        #data['current_cutter_id'] = self.current_cutter_cycle.cutter.id if self.current_cutter_cycle is not None else None
        return data
    def load(self, data):
        self.reinitDocument()
        self.default_preset_by_tool = {}
        self.material.reload(data['material'])
        currentCutterCycle = None
        cycleForCutter = {}
        if 'tool' in data:
            # Old style singleton tool
            material = MaterialType.toTuple(self.material.material)[2] if self.material.material is not None else material_plastics
            tool = data['tool']
            prj_cutter = inventory.EndMillCutter.new(None, "Project tool", inventory.CutterMaterial.carbide, tool['diameter'], tool['cel'], tool['flutes'], inventory.EndMillShape.FLAT, 0, 0)
            std_tool = milling_tool.standard_tool(prj_cutter.diameter, prj_cutter.flutes, material, milling_tool.carbide_uncoated).clone_with_overrides(
                hfeed=tool['hfeed'], vfeed=tool['vfeed'], maxdoc=tool['depth'], rpm=tool['rpm'], stepover=tool.get('stepover', None))
            prj_preset = inventory.EndMillPreset.new(None, "Project preset", prj_cutter,
                std_tool.rpm, std_tool.hfeed, std_tool.vfeed, std_tool.maxdoc, 0, std_tool.stepover,
                tool.get('direction', 0), 0, 0, None, 0, 0.5, inventory.EntryMode.PREFER_RAMP, 0)
            prj_cutter.presets.append(prj_preset)
            self.opAddCutter(prj_cutter)
            self.default_preset_by_tool[prj_cutter] = prj_preset
            self.refreshToolList()
        add_cycles = 'operation_cycles' not in data
        cycle = None
        if 'tools' in data:
            std_cutters = { i.name : i for i in inventory.inventory.toolbits }
            cutters = [inventory.CutterBase.load(i, default_type='EndMillCutter') for i in data['tools']]
            presets = [inventory.PresetBase.load(i, default_type='EndMillPreset') for i in data['tool_presets']]
            cutter_map = { i.orig_id : i for i in cutters }
            preset_map = { i.orig_id : i for i in presets }
            # Try to map to standard cutters
            for cutter in cutters:
                orig_id = cutter.orig_id
                if cutter.name in std_cutters:
                    std = std_cutters[cutter.name]
                    cutter.base_object = std
                    if debug_inventory_matching:
                        if std.equals(cutter):
                            print ("Matched library tool", cutter.name)
                        else:
                            print ("Found different library tool with same name", cutter.name)
                    cutter_map[cutter.orig_id] = cutter
                    self.project_toolbits[cutter.name] = cutter
                else:
                    if debug_inventory_matching:
                        print ("New tool without library prototype", cutter.name)
                    # New tool not present in the inventory
                    self.project_toolbits[cutter.name] = cutter
                if add_cycles:
                    cycle = CycleTreeItem(self, cutter)
                    cycleForCutter[orig_id] = cycle
                    self.operModel.appendRow(cycle)
                    if cutter.orig_id == data.get('current_cutter_id', None):
                        currentCutterCycle = cycle
                    else:
                        currentCutterCycle = currentCutterCycle or cycle
            # Fixup cutter references (they're initially loaded as ints instead)
            for i in presets:
                i.toolbit = cutter_map[i.toolbit]
                if i.toolbit.base_object is not None:
                    i.base_object = i.toolbit.base_object.presetByName(i.name)
                i.toolbit.presets.append(i)
            self.refreshToolList()
        if 'default_presets' in data:
            for i in data['default_presets']:
                def_tool_id = i['tool_id']
                def_preset_id = i['preset_id']
                if def_tool_id in cutter_map and def_preset_id in preset_map:
                    self.default_preset_by_tool[cutter_map[def_tool_id]] = preset_map[def_preset_id]
                else:
                    print (f"Warning: bogus default preset entry, tool {def_tool_id}, preset {def_preset_id}")
        #self.tool.reload(data['tool'])
        self.drawing.reset()
        self.drawing.reload(data['drawing']['header'])
        for i in data['drawing']['items']:
            self.drawing.appendRow(DrawingItemTreeItem.load(self, i))
        if 'operations' in data:
            for i in data['operations']:
                operation = CAMTreeItem.load(self, i)
                if ('cutter' not in i) and ('tool' in data):
                    cycle = self.operModel.item(0)
                    operation.cutter = prj_cutter
                    operation.tool_preset = prj_preset
                else:
                    cycle = cycleForCutter[operation.cutter]
                    operation.cutter = cutter_map[operation.cutter]
                    operation.tool_preset = preset_map[operation.tool_preset] if operation.tool_preset else None
                operation.updateOrigShape()
                if operation.orig_shape is None:
                    print ("Warning: dangling reference to shape %d, ignoring the referencing operation" % (operation.shape_id, ))
                else:
                    cycle.appendRow(operation)
        elif 'operation_cycles' in data:
            for i in data['operation_cycles']:
                cycle = CycleTreeItem(self, cutter_map[i['tool_id']])
                cycleForCutter[orig_id] = cycle
                self.operModel.appendRow(cycle)
                if i['is_current']:
                    currentCutterCycle = cycle
                for j in i['operations']:
                    operation = CAMTreeItem.load(self, j)
                    operation.cutter = cutter_map[operation.cutter]
                    operation.tool_preset = preset_map[operation.tool_preset] if operation.tool_preset else None
                    cycle.appendRow(operation)
        self.startUpdateCAM()
        if currentCutterCycle:
            self.selectCutterCycle(currentCutterCycle)
        self.undoStack.clear()
        self.undoStack.setClean()
    def loadProject(self, fn):
        f = open(fn, "r")
        data = json.load(f)
        f.close()
        self.filename = fn
        self.drawing_filename = None
        self.load(data)
        self.projectLoaded.emit()
    def makeMachineParams(self):
        self.gcode_machine_params = gcodeops.MachineParams(safe_z=self.material.clearance, semi_safe_z=self.material.safe_entry_z,
            min_rpm=geom.GeometrySettings.spindle_min_rpm, max_rpm=geom.GeometrySettings.spindle_max_rpm)
    def newDocument(self):
        self.reinitDocument()
        self.filename = None
        self.drawing_filename = None
        self.projectCleared.emit()
    def importDrawing(self, fn):
        if self.drawing_filename is None:
            self.drawing_filename = fn
        self.drawing.importDrawing(fn)
    def allOperationsPlusRefinements(self, func=None):
        ops = set(self.allOperations(func))
        shape_ids = set([op.shape_id for op in ops])
        for op in self.refineOpsForShapes(shape_ids):
            ops.add(op)
        return list(ops)
    def allOperations(self, func=None):
        res = []
        for i in range(self.operModel.rowCount()):
            cycle : CycleTreeItem = self.operModel.item(i)
            for j in range(cycle.rowCount()):
                operation : OperationTreeItem = cycle.child(j)
                if func is None or func(operation):
                    res.append(operation)
        return res
    def forEachOperation(self, func):
        res = []
        for i in range(self.operModel.rowCount()):
            cycle : CycleTreeItem = self.operModel.item(i)
            for j in range(cycle.rowCount()):
                operation : OperationTreeItem = cycle.child(j)
                res.append(func(operation))
        return res
    def largerDiameterForShape(self, shape, min_size):
        candidates = []
        for operation in self.forEachOperation(lambda operation: operation):
            pda = PresetDerivedAttributes(operation)
            diameter_plus = operation.cutter.diameter + 2 * pda.offset
            if (operation.shape_id is shape.shape_id) and (diameter_plus > min_size):
                candidates.append((diameter_plus, operation))
        if not candidates:
            return None, None, None
        islands = None
        candidates = list(sorted(candidates, key = lambda item: item[0]))
        for diameter_plus, operation in candidates:
            if operation.areIslandsEditable() and operation.islands:
                islands = operation.islands
                break
        return candidates[0][0], candidates[0][1], islands
    def operDataChanged(self, topLeft, bottomRight, roles):
        if not roles or (Qt.CheckStateRole in roles):
            changes = []
            for row in range(topLeft.row(), bottomRight.row() + 1):
                item = topLeft.model().itemFromIndex(topLeft.siblingAtRow(row))
                if isinstance(item, OperationTreeItem):
                    active = item.checkState() != Qt.CheckState.Unchecked
                    if active != item.active:
                        changes.append((item, active))
                if isinstance(item, CycleTreeItem):
                    reqState = item.checkState()
                    itemState = item.operCheckState()
                    if reqState != itemState:
                        reqActive = reqState != Qt.CheckState.Unchecked
                        for i in item.items():
                            if i.active != reqActive:
                                changes.append((i, reqActive))
            if changes:
                self.opChangeActive(changes)
        if not roles or (Qt.DisplayRole in roles):
            shape_ids = set()
            for row in range(topLeft.row(), bottomRight.row() + 1):
                item = topLeft.model().itemFromIndex(topLeft.siblingAtRow(row))
                if isinstance(item, OperationTreeItem):
                    shape_ids.add(item.shape_id)
            self.updateRefineOps(shape_ids)
    def operRowsInserted(self, parent, first, last):
        item = self.operModel.itemFromIndex(parent)
        if isinstance(item, CycleTreeItem):
            item.updateCheckState()
            self.updateRefineOps(self.shapesForOperationRange(item, first, last))
    def operRowsAboutToBeRemoved(self, parent, first, last):
        item = self.operModel.itemFromIndex(parent)
        if isinstance(item, CycleTreeItem):
            self.shapes_to_revisit |= self.shapesForOperationRange(item, first, last)
    def operRowsRemoved(self, parent, first, last):
        item = self.operModel.itemFromIndex(parent)
        if isinstance(item, CycleTreeItem):
            item.updateCheckState()
        if self.shapes_to_revisit:
            self.updateRefineOps(self.shapes_to_revisit)
            self.shapes_to_revisit = set()
    def shapesForOperationRange(self, parent, first, last):
        shape_ids = set()
        for row in range(first, last + 1):
            item = parent.child(row)
            shape_ids.add(item.shape_id)
        return shape_ids
    def updateRefineOps(self, shape_ids):
        self.forEachOperation(lambda item: self.updateRefineOp(item, shape_ids))
    def updateRefineOp(self, operation, shape_ids):
        if operation.operation == OperationType.REFINE and operation.shape_id in shape_ids and operation.orig_shape:
            pda = PresetDerivedAttributes(operation)
            diameter_plus = operation.cutter.diameter + 2 * pda.offset
            prev_diameter, prev_operation, islands = self.largerDiameterForShape(operation.orig_shape, diameter_plus)
            if prev_diameter != operation.prev_diameter:
                operation.startUpdateCAM()
    def startUpdateCAM(self, subset=None):
        self.makeMachineParams()
        if subset is None:
            self.forEachOperation(lambda item: item.startUpdateCAM())
        else:
            self.forEachOperation(lambda item: item.startUpdateCAM() if item in subset else None)
    def cancelAllWorkers(self):
        self.forEachOperation(lambda item: item.cancelWorker())
    def pollForUpdateCAM(self):
        has_workers = any(self.forEachOperation(lambda item: item.worker))
        if not has_workers:
            return
        results = self.forEachOperation(lambda item: item.pollForUpdateCAM())
        totaldone = 0
        totaloverall = 0
        for i in results:
            if i is not None:
                totaldone += i[0]
                totaloverall += i[1]
        if totaloverall > 0:
            return totaldone / totaloverall
    def waitForUpdateCAM(self):
        if self.pollForUpdateCAM() is None:
            return True
        if is_gui_application():
            try:
                self.progress_dialog_displayed = True
                progress = QProgressDialog()
                progress.show()
                progress.setWindowModality(Qt.WindowModal)
                progress.setLabelText("Calculating toolpaths")
                cancelled = False
                while True:
                    if progress.wasCanceled():
                        self.cancelAllWorkers()
                        cancelled = True
                        break
                    pollValue = self.pollForUpdateCAM()
                    if pollValue is None:
                        break
                    progress.setValue(int(pollValue * 100))
                    QGuiApplication.sync()
                    time.sleep(0.25)
            finally:
                self.progress_dialog_displayed = False
        else:
            cancelled = False
            while self.pollForUpdateCAM() is not None:
                time.sleep(0.25)
        return not cancelled
    def checkCAMErrors(self):
        return self.forEachOperation(lambda item: item.error)
    def checkCAMWarnings(self):
        return self.forEachOperation(lambda item: item.warning)
    def getToolbitList(self, data_type: type):
        res = [(tb.id, tb.description()) for tb in self.project_toolbits.values() if isinstance(tb, data_type)]
        #res += [(tb.id, tb.description()) for tb in inventory.inventory.toolbits if isinstance(tb, data_type) and tb.presets]
        return res
    def validateForOutput(self):
        def validateOperation(item):
            if item.depth is None:
                if self.material.thickness is None or self.material.thickness == 0:
                    raise ValueError("Default material thickness not set")
            if item.error is not None:
                raise ValueError(item.error)
        self.forEachOperation(validateOperation)
    def setOperSelection(self, selection):
        changes = []
        def setSelected(operation):
            isIn = (operation in selection)
            if operation.isSelected != isIn:
                operation.isSelected = isIn
                return True
        return any(self.forEachOperation(setSelected))
    def cycleForCutter(self, cutter: inventory.CutterBase):
        for i in range(self.operModel.rowCount()):
            cycle: CycleTreeItem = self.operModel.item(i)
            if cycle.cutter == cutter:
                return cycle
        return None
    def selectCutterCycle(self, cycle):
        old = self.current_cutter_cycle
        self.current_cutter_cycle = cycle
        self.current_cutter_cycle.emitDataChanged()
        if old:
            old.emitDataChanged()
        self.cutterSelected.emit(cycle)
    def selectPresetAsDefault(self, toolbit, preset):
        old = self.default_preset_by_tool.get(toolbit, None)
        self.default_preset_by_tool[toolbit] = preset
        if old:
            self.itemForPreset(old).emitDataChanged()
        if preset:
            self.itemForPreset(preset).emitDataChanged()
    def itemForCutter(self, cutter):
        for i in range(self.tool_list.rowCount()):
            tool = self.tool_list.child(i)
            if tool.inventory_tool is cutter:
                return tool
    def itemForPreset(self, preset):
        tool = self.itemForCutter(preset.toolbit)
        for i in range(tool.rowCount()):
            p = tool.child(i)
            if p.inventory_preset is preset:
                return p
    def refineOpsForShapes(self, shape_ids):
        return self.allOperations(lambda item: item.operation == OperationType.REFINE and item.shape_id in shape_ids)
    def refreshRefineForOpOrCycle(self, item):
        shape_ids = set()
        if isinstance(item, CycleTreeItem):
            for i in item.items():
                self.refreshRefineForOpOrCycle(i)
        elif isinstance(item, OperationTreeItem):
            shape_ids.add(item.shape_id)
        refineOps = self.refineOpsForShapes(shape_ids)
        for i in refineOps:
            i.startUpdateCAM()
    def checkUpdateSuspended(self, item):
        if self.update_suspended is item:
            self.update_suspended_dirty = True
            return True
        return False
    def setUpdateSuspended(self, item):
        if self.update_suspended is item:
            return
        was_suspended = self.update_suspended if self.update_suspended_dirty else None
        self.update_suspended = item
        self.update_suspended_dirty = False
        if was_suspended is not None:
            was_suspended.startUpdateCAM()
    def exportGcode(self, fn):
        with Spinner():
            OpExporter(self).write(fn)
    def addShapesFromEditor(self, items):
        self.opAddDrawingItems(items)
        self.shapesCreated.emit(items)
    def opAddCutter(self, cutter: inventory.CutterBase):
        cycle = CycleTreeItem(self, cutter)
        self.undoStack.push(AddOperationUndoCommand(self, cycle, self.operModel.invisibleRootItem(), self.operModel.rowCount()))
        #self.operModel.appendRow(self.current_cutter_cycle)
        self.refreshToolList()
        self.selectCutterCycle(cycle)
        return cycle
    def opAddProjectPreset(self, cutter: inventory.CutterBase, preset: inventory.PresetBase):
        item = self.itemForCutter(cutter)
        self.undoStack.push(AddPresetUndoCommand(item, preset))
    def opAddLibraryPreset(self, library_preset: inventory.PresetBase):
        # XXXKF undo
        for cutter in self.project_toolbits.values():
            if cutter.base_object is library_preset.toolbit:
                preset = library_preset.newInstance()
                preset.toolbit = cutter
                cutter.presets.append(preset)
                self.refreshToolList()
                return cutter, preset, False
        else:
            preset = library_preset.newInstance()
            cutter = library_preset.toolbit.newInstance()
            preset.toolbit = cutter
            cutter.presets.append(preset)
            return cutter, preset, True
    def opCreateOperation(self, shapeIds, operationType, cycle=None):
        if cycle is None:
            cycle = self.current_cutter_cycle
            if cycle is None:
                raise ValueError("Cutter not selected")
        with MultipleItemUndoContext(self, shapeIds, lambda count: f"Create {count} of {OperationType.toString(operationType)}"):
            indexes = []
            rowCount = cycle.rowCount()
            for i in shapeIds:
                item = CAMTreeItem.load(self, { '_type' : 'OperationTreeItem', 'shape_id' : i, 'operation' : operationType })
                item.cutter = cycle.cutter
                item.tool_preset = self.default_preset_by_tool.get(item.cutter, None)
                item.islands = shapeIds[i]
                item.startUpdateCAM()
                self.undoStack.push(AddOperationUndoCommand(self, item, cycle, rowCount))
                indexes.append(item.index())
                rowCount += 1
        return rowCount, cycle, indexes
    def opChangeProperty(self, property, changes):
        with MultipleItemUndoContext(self, changes, lambda count: f"Set {property.name} on {count} items"):
            for subject, value in changes:
                self.undoStack.push(PropertySetUndoCommand(property, subject, property.getData(subject), value))
    def opChangeActive(self, changes):
        self.undoStack.push(ActiveSetUndoCommand(changes))
    def opDeleteOperations(self, items):
        with MultipleItemUndoContext(self, items, lambda count: f"Delete {count} cycles/operations"):
            for item in items:
                parent, row = self.operModel.findItem(item)
                if isinstance(item, OperationTreeItem):
                    self.undoStack.push(DeleteOperationUndoCommand(self, item, parent, row))
                elif isinstance(item, CycleTreeItem):
                    self.undoStack.push(DeleteCycleUndoCommand(self, item))
    def opMoveItem(self, oldParent, child, newParent, pos):
        self.undoStack.push(MoveItemUndoCommand(oldParent, child, newParent, pos))
    def opMoveItems(self, items, direction):
        itemsToMove = []
        for item in items:
            if hasattr(item, 'reorderItem'):
                itemsToMove.append(item)
        if not itemsToMove:
            return
        indexes = []
        itemsToMove = list(sorted(itemsToMove, key=lambda item: -item.row() * direction))
        dir_text = "down" if direction > 0 else "up"
        with MultipleItemUndoContext(self, itemsToMove, lambda count: f"Move {count} operations {dir_text}"):
            for item in itemsToMove:
                index = item.reorderItem(direction)
                if index is not None:
                    indexes.append(index)
        return indexes
    def opDeletePreset(self, preset):
        self.undoStack.beginMacro(f"Delete preset: {preset.name}")
        try:
            changes = []
            self.forEachOperation(lambda operation: changes.append((operation, None)) if operation.tool_preset is preset else None)
            self.opChangeProperty(OperationTreeItem.prop_preset, changes)
            self.undoStack.push(DeletePresetUndoCommand(self, preset))
        finally:
            self.undoStack.endMacro()
    def opDeleteCycle(self, cycle):
        self.undoStack.beginMacro(f"Delete cycle: {cycle.cutter.name}")
        try:
            self.undoStack.push(DeleteCycleUndoCommand(self, cycle))
        finally:
            self.undoStack.endMacro()
    def opUnlinkInventoryCutter(self, cutter):
        for tb in self.project_toolbits:
            if tb.base_object is preset:
                tb.base_object = None
    def opUnlinkInventoryPreset(self, preset):
        for tb in self.project_toolbits.values():
            for p in tb.presets:
                if p.base_object is preset:
                    p.base_object = None
    def opRevertPreset(self, item):
        self.undoStack.push(RevertPresetUndoCommand(item))
    def opRevertTool(self, item):
        self.undoStack.push(RevertToolUndoCommand(item))
    def opModifyPreset(self, preset, new_data):
        item = self.itemForPreset(preset)
        self.undoStack.push(ModifyPresetUndoCommand(item, new_data))
    def opModifyCutter(self, cutter, new_data):
        item = self.itemForCutter(cutter)
        self.undoStack.push(ModifyToolUndoCommand(item, new_data))
    def opJoin(self, items):
        self.undoStack.push(JoinItemsUndoCommand(self, items))
    def opModifyPolyline(self, polyline, new_points, new_closed):
        self.undoStack.push(ModifyPolylineUndoCommand(self, polyline, new_points, new_closed))
    def opModifyPolylinePoint(self, polyline, position, location, mergeable):
        self.undoStack.push(ModifyPolylinePointUndoCommand(self, polyline, position, location, mergeable))
    def opAddDrawingItems(self, items):
        self.undoStack.push(AddDrawingItemsUndoCommand(self, items))
    def opDeleteDrawingItems(self, items):
        shapes = []
        tools = []
        presets = []
        for i in items:
            if isinstance(i, DrawingItemTreeItem):
                shapes.append(i)
            elif isinstance(i, ToolTreeItem):
                tools.append(i)
            elif isinstance(i, ToolPresetTreeItem):
                presets.append(i)
            else:
                raise ValueError("Cannot delete an item of type: " + str(i.__class__.__name__))
        if shapes:
            self.undoStack.push(DeleteDrawingItemsUndoCommand(self, shapes))
        for i in presets:
            self.opDeletePreset(i.inventory_preset)
        for i in tools:
            self.opDeleteCycle(self.cycleForCutter(i.inventory_tool))
    def undo(self):
        self.undoStack.undo()
    def redo(self):
        self.undoStack.redo()

class OpExporter(object):
    def __init__(self, document):
        document.waitForUpdateCAM()
        self.machine_params = document.gcode_machine_params
        self.operations = gcodeops.Operations(document.gcode_machine_params)
        self.all_cutters = set([])
        self.cutter = None
        document.forEachOperation(self.add_cutter)
        document.forEachOperation(self.process_operation)
    def add_cutter(self, item):
        if item.cam:
            self.all_cutters.add(item.cutter)
    def process_operation(self, item):
        if item.cam:
            if item.cutter != self.cutter and len(self.all_cutters) > 1:
                self.operations.add(gcodeops.ToolChangeOperation(item.cutter, self.machine_params))
                self.cutter = item.cutter
            self.operations.add_all(item.cam.operations)
    def write(self, fn):
        self.operations.to_gcode_file(fn)
