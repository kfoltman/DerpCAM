from .common_model import *
from .workpiece_model import MaterialEnumEditableProperty, MaterialType

class PresetDerivedAttributeItem(object):
    def __init__(self, name, preset_name=None, preset_scale=None, def_value=None):
        self.name = name
        self.preset_name = preset_name or name
        self.preset_scale = preset_scale
        self.def_value = def_value
    def resolve(self, operation, preset):
        if operation is not None:
            op_value = getattr(operation, self.name)
            if op_value is not None:
                return (True, op_value)
        preset_value = getattr(preset, self.preset_name, None) if preset else None
        if preset_value is not None:
            if self.preset_scale is not None:
                preset_value *= self.preset_scale
            return (operation is None, preset_value)
        return (False, self.def_value)

class PresetDerivedAttributes(object):
    attrs_common = [
        PresetDerivedAttributeItem('rpm'),
        PresetDerivedAttributeItem('vfeed'),
        PresetDerivedAttributeItem('doc', preset_name='maxdoc'),
    ]
    attrs_endmill = [
        PresetDerivedAttributeItem('hfeed'),
        PresetDerivedAttributeItem('offset', def_value=0),
        PresetDerivedAttributeItem('roughing_offset', def_value=0),
        PresetDerivedAttributeItem('stepover', preset_scale=100),
        PresetDerivedAttributeItem('extra_width', preset_scale=100, def_value=0),
        PresetDerivedAttributeItem('trc_rate', preset_scale=100, def_value=0),
        PresetDerivedAttributeItem('direction', def_value=inventory.MillDirection.CONVENTIONAL),
        PresetDerivedAttributeItem('pocket_strategy', def_value=inventory.PocketStrategy.CONTOUR_PARALLEL),
        PresetDerivedAttributeItem('axis_angle', def_value=0),
        PresetDerivedAttributeItem('eh_diameter', preset_scale=100, def_value=50),
        PresetDerivedAttributeItem('entry_mode', def_value=inventory.EntryMode.PREFER_HELIX),
    ]
    # only endmill+drill bit
    attrs_all = attrs_common + attrs_endmill
    attrs_thread_only = [
        PresetDerivedAttributeItem('vfeed'),
    ]
    attrs_thread = attrs_thread_only + [
        PresetDerivedAttributeItem('rpm'),
        PresetDerivedAttributeItem('stepover', preset_scale=100),
    ]
    attrs = {
        inventory.EndMillCutter : {i.name : i for i in attrs_all},
        inventory.DrillBitCutter : {i.name : i for i in attrs_common},
        inventory.ThreadMillCutter : {i.name : i for i in attrs_thread},
    }
    def __init__(self, operation, preset=None, addError=None):
        if preset is None:
            preset = operation.tool_preset
        self.operation = operation
        attrs = self.attrs[operation.cutter.__class__]
        self.dirty = False
        for attr in attrs.values():
            dirty, value = attr.resolve(operation, preset)
            setattr(self, attr.name, value)
            self.dirty = self.dirty or dirty
        # Material defaults
        if operation.document.material.material is not None and operation.cutter is not None:
            m = MaterialType.toTuple(operation.document.material.material)[2]
            t = operation.cutter
            try:
                if isinstance(operation.cutter, inventory.EndMillCutter):
                    if not all([self.rpm, self.hfeed, self.vfeed, self.doc, self.stepover]):
                        # Slotting penalty
                        f = 1
                        if operation.operation in (OperationType.OUTSIDE_CONTOUR, OperationType.INSIDE_CONTOUR):
                            f = 0.6
                        st = milling_tool.standard_tool(t.diameter, t, t.flutes or 2, m, milling_tool.carbide_uncoated, not operation.cutter.material.is_carbide(), f, flute_length=t.length, machine_params=operation.document.gcode_machine_params)
                        if self.rpm is None:
                            self.rpm = st.rpm
                        if self.hfeed is None:
                            self.hfeed = st.hfeed * f
                        if self.vfeed is None:
                            self.vfeed = st.vfeed * f
                        if self.doc is None:
                            self.doc = st.maxdoc * f
                        if self.stepover is None:
                            self.stepover = st.stepover * 100
                elif isinstance(operation.cutter, inventory.DrillBitCutter):
                    if not all([self.rpm, self.vfeed, self.doc]):
                        st = milling_tool.standard_tool(t.diameter, t, t.flutes or 2, m, milling_tool.carbide_uncoated, not operation.cutter.material.is_carbide(), 1.0, flute_length=t.length, machine_params=operation.document.gcode_machine_params, is_drill=True)
                        if self.rpm is None:
                            self.rpm = st.rpm
                        if self.vfeed is None:
                            self.vfeed = st.vfeed
                        if self.doc is None:
                            self.doc = st.maxdoc
                elif isinstance(operation.cutter, inventory.ThreadMillCutter):
                    if not all([self.rpm, self.vfeed, self.stepover]):
                        st = milling_tool.standard_tool(t.diameter, t, t.flutes or 2, m, milling_tool.carbide_uncoated, not operation.cutter.material.is_carbide(), 1.0, flute_length=t.length, machine_params=operation.document.gcode_machine_params, is_drill=True)
                        if self.rpm is None:
                            self.rpm = st.rpm
                        if self.vfeed is None:
                            self.vfeed = st.vfeed
                        if self.stepover is None:
                            self.stepover = st.stepover * 100
            except ValueError as e:
                if addError:
                    addError(str(e))
    def validate(self, errors):
        if self.vfeed is None:
            errors.append("Vertical feed rate is not set")
        if not isinstance(self.operation.cutter, inventory.ThreadMillCutter) and self.doc is None:
            errors.append("Maximum depth of cut per pass is not set")
        if isinstance(self.operation.cutter, inventory.EndMillCutter):
            if self.hfeed is None:
                if self.operation.operation != OperationType.DRILLED_HOLE:
                    errors.append("Horizontal feed rate is not set")
            elif self.hfeed < 0.1 or self.hfeed > 10000:
                errors.append("Horizontal feed rate is out of range (0.1-10000)")
        if self.vfeed is not None and not (0.1 <= self.vfeed <= 10000):
            errors.append("Vertical feed rate is out of range (0.1-10000)")
        if isinstance(self.operation.cutter, inventory.ThreadMillCutter) and self.operation.threadPitch() is None:
            errors.append(f"Cannot guess the thread pitch for diameter {Format.coord(2 * self.operation.orig_shape.r)}")
        if isinstance(self.operation.cutter, (inventory.EndMillCutter, inventory.ThreadMillCutter)):
            if self.stepover is None or self.stepover < 0.1 or self.stepover > 100:
                if OperationType.has_stepover(self.operation.operation):
                    if self.stepover is None:
                        errors.append("Horizontal stepover is not set")
                    else:
                        errors.append("Horizontal stepover is out of range")
                else:
                    # Fake value that is never used
                    self.stepover = 0.5
    @staticmethod
    def valuesFromPreset(preset, cutter_type):
        values = {}
        if preset:
            values['name'] = preset.name
            for attr in PresetDerivedAttributes.attrs[cutter_type].values():
                present, value = attr.resolve(None, preset)
                values[attr.name] = value if present is not None else None
        else:
            for attr in PresetDerivedAttributes.attrs[cutter_type].values():
                if attr.def_value is not None:
                    values[attr.name] = attr.def_value
        return values
    def toPreset(self, name):
        return self.toPresetFromAny(name, self, self.operation.cutter, type(self.operation.cutter))
    @classmethod
    def toPresetFromAny(klass, name, src, cutter, cutter_type):
        kwargs = {}
        is_dict = isinstance(src, dict)
        for attr in klass.attrs[cutter_type].values():
            value = src[attr.name] if is_dict else getattr(src, attr.name)
            if value is not None and attr.preset_scale is not None:
                value /= attr.preset_scale
            kwargs[attr.preset_name] = value
        return cutter_type.preset_type.new(None, name, cutter, **kwargs)
    @classmethod
    def resetPresetDerivedValues(klass, target):
        for attr in klass.attrs_all:
            setattr(target, attr.name, None)
        target.emitPropertyChanged()

class ToolListTreeItem(CAMListTreeItemWithChildren):
    def __init__(self, document):
        CAMListTreeItemWithChildren.__init__(self, document, "Tool list")
        self.reset()
    def childList(self):
        return sorted(self.document.project_toolbits.values(), key = lambda item: item.name)
    def createChildItem(self, data):
        return ToolTreeItem(self.document, data, True)

@CAMTreeItem.register_class
class ToolTreeItem(CAMListTreeItemWithChildren):
    prop_name = StringEditableProperty("Name", "name", False)
    prop_flutes = IntEditableProperty("# flutes", "flutes", "%d", min=1, max=100, allow_none=False)
    prop_diameter = FloatDistEditableProperty("Diameter", "diameter", Format.cutter_dia, unit="mm", min=0, max=100, allow_none=False)
    prop_length = FloatDistEditableProperty("Flute length", "length", Format.cutter_length, unit="mm", min=0.1, max=100, allow_none=True)
    prop_material = MaterialEnumEditableProperty("Material", "material", inventory.CutterMaterial, allow_none=False)
    prop_shape = EnumEditableProperty("Shape", "shape", inventory.EndMillShape, allow_none=False)
    prop_angle = FloatDistEditableProperty("Tip angle", "angle", format=Format.angle, unit='\u00b0', min=1, max=179, allow_none=False)
    prop_tip_diameter = FloatDistEditableProperty("Tip diameter", "tip_diameter", Format.cutter_dia, unit="mm", min=0, max=100, allow_none=False)
    prop_min_pitch = FloatDistEditableProperty("Min. pitch", "min_pitch", Format.thread_pitch, unit="mm", min=0.1, max=10, allow_none=False)
    prop_max_pitch = FloatDistEditableProperty("Max. pitch", "max_pitch", Format.thread_pitch, unit="mm", min=0.1, max=10, allow_none=True)
    prop_thread_angle = FloatDistEditableProperty("Thread angle", "thread_angle", format=Format.angle, unit='\u00b0', min=1, max=179, allow_none=False)
    def __init__(self, document, inventory_tool, is_local):
        self.inventory_tool = inventory_tool
        CAMListTreeItemWithChildren.__init__(self, document, "Tool")
        self.setEditable(False)
        self.reset()
    def label(self):
        return f"Tool '{self.inventory_tool.name}'"
    def isLocal(self):
        return not self.inventory_tool.base_object or not (self.inventory_tool.equals(self.inventory_tool.base_object))
    def isNewObject(self):
        return self.inventory_tool.base_object is None
    def isModifiedStock(self):
        return self.inventory_tool.base_object is not None and not (self.inventory_tool.equals(self.inventory_tool.base_object))
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant(self.inventory_tool.description())
        is_local = self.isLocal()
        return self.format_item_as(role, CAMTreeItem.data(self, role), italic=not is_local)
    def childList(self):
        return sorted(self.inventory_tool.presets, key = lambda item: item.name)
    def createChildItem(self, data):
        return ToolPresetTreeItem(self.document, data)
    def properties(self):
        if isinstance(self.inventory_tool, inventory.EndMillCutter):
            return [self.prop_name, self.prop_diameter, self.prop_flutes, self.prop_length, self.prop_material, self.prop_shape, self.prop_angle, self.prop_tip_diameter]
        elif isinstance(self.inventory_tool, inventory.DrillBitCutter):
            return [self.prop_name, self.prop_diameter, self.prop_length, self.prop_material]
        elif isinstance(self.inventory_tool, inventory.ThreadMillCutter):
            return [self.prop_name, self.prop_diameter, self.prop_length, self.prop_material, self.prop_min_pitch, self.prop_max_pitch, self.prop_thread_angle]
        return []
    def isPropertyValid(self, name):
        if (not isinstance(self.inventory_tool, inventory.EndMillCutter) or self.inventory_tool.shape != inventory.EndMillShape.TAPERED) and name in ['angle', 'tip_diameter']:
            return False
        if not isinstance(self.inventory_tool, inventory.ThreadMillCutter) and name in ['min_pitch', 'max_pitch', 'thread_angle']:
            return False
        return True
    def resetProperties(self):
        self.emitPropertyChanged()
    def getPropertyValue(self, name):
        return getattr(self.inventory_tool, name)
    def setPropertyValue(self, name, value):
        if name == 'name':
            self.inventory_tool.name = value
            self.inventory_tool.base_object = inventory.inventory.toolbitByName(value, type(self.inventory_tool))
        elif hasattr(self.inventory_tool, name):
            setattr(self.inventory_tool, name, value)
        else:
            assert False, "Unknown attribute: " + repr(name)
        self.emitPropertyChanged(name)
    def invalidatedObjects(self, aspect):
        # Need to refresh properties for any default or calculated values updated, tool name etc.
        # Affects both properties and CAM
        return set([self] + self.document.allOperationsPlusRefinements(lambda item: item.cutter is self.inventory_tool))

class WallProfileTreeItem(CAMTreeItem):
    prop_name = StringEditableProperty("Name", "name", False)
    prop_description = StringEditableProperty("Description", "description", True)
    def __init__(self, document, wall_profile, is_local):
        self.wall_profile = wall_profile
        CAMTreeItem.__init__(self, document)
        self.setEditable(False)
    def data(self, role):
        if role == Qt.DisplayRole:
            #return QVariant("Wall profile: " + (self.wall_profile.description or self.wall_profile.name))
            if self.wall_profile.description:
                return QVariant(self.wall_profile.name + ": " + self.wall_profile.description)
            else:
                return QVariant(self.wall_profile.name)
        is_default = False
        is_local = True
        return self.format_item_as(role, CAMTreeItem.data(self, role), bold=is_default, italic=not is_local)
    def resetProperties(self):
        self.emitPropertyChanged()
    @classmethod
    def properties(klass):
        return [klass.prop_name, klass.prop_description]
    def getPropertyValue(self, name):
        return getattr(self.wall_profile, name)
    def setPropertyValue(self, name, value):
        if name == 'name':
            if value != self.wall_profile.name and value in self.document.project_wall_profiles:
                # Cannot raise exceptions here, because it's used inside undo commands
                #raise ValueError(f"Wall profile named '{name}' already exists")
                return
            self.wall_profile.name = value
            self.wall_profile.base_object = inventory.inventory.wallProfileByName(value)
        elif hasattr(self.wall_profile, name):
            setattr(self.wall_profile, name, value)
        else:
            assert False, "Unknown attribute: " + repr(name)
        self.emitPropertyChanged(name)
    def invalidatedObjects(self, aspect):
        # Need to refresh properties for any default or calculated values updated
        return set([self] + self.document.allOperationsPlusRefinements(lambda item: item.wall_profile is self.wall_profile))

class WallProfileListTreeItem(CAMListTreeItemWithChildren):
    def __init__(self, document):
        CAMListTreeItemWithChildren.__init__(self, document, "Wall profiles")
        self.reset()
    def childList(self):
        return sorted(self.document.project_wall_profiles.values(), key=lambda item: item.name)
    def createChildItem(self, data):
        return WallProfileTreeItem(self.document, data, True)

class ToolPresetTreeItem(CAMTreeItem):
    prop_name = StringEditableProperty("Name", "name", False)
    prop_doc = FloatDistEditableProperty("Cut depth/pass", "doc", Format.depth_of_cut, unit="mm", min=0.01, max=100, allow_none=True)
    prop_rpm = FloatDistEditableProperty("RPM", "rpm", Format.rpm, unit="rpm", min=0.1, max=60000, allow_none=True)
    prop_surf_speed = FloatDistEditableProperty("Surface speed", "surf_speed", Format.surf_speed, unit="m/min", allow_none=True, computed=True)
    prop_chipload = FloatDistEditableProperty("Chipload", "chipload", Format.chipload, unit="mm/tooth", allow_none=True, computed=True)
    prop_hfeed = FloatDistEditableProperty("Horizontal feed rate", "hfeed", Format.feed, unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_vfeed = FloatDistEditableProperty("Vertical feed rate", "vfeed", Format.feed, unit="mm/min", min=0.1, max=10000, allow_none=True)
    prop_offset = FloatDistEditableProperty("Offset", "offset", Format.coord, unit="mm", min=-20, max=20, default_value=0)
    prop_roughing_offset = FloatDistEditableProperty("Roughing Offset", "roughing_offset", Format.coord, unit="mm", min=0, max=20, default_value=0)
    prop_stepover = FloatDistEditableProperty("Stepover", "stepover", Format.percent, unit="%", min=1, max=100, allow_none=True)
    prop_direction = EnumEditableProperty("Direction", "direction", inventory.MillDirection, allow_none=False)
    prop_extra_width = FloatDistEditableProperty("Extra width", "extra_width", Format.percent, unit="%", min=0, max=100, allow_none=True)
    prop_trc_rate = FloatDistEditableProperty("Trochoid: step", "trc_rate", Format.percent, unit="%", min=0, max=100, allow_none=True)
    prop_pocket_strategy = EnumEditableProperty("Strategy", "pocket_strategy", inventory.PocketStrategy, allow_none=True)
    prop_axis_angle = FloatDistEditableProperty("Axis angle", "axis_angle", format=Format.angle, unit='\u00b0', min=0, max=90, allow_none=True)
    prop_eh_diameter = FloatDistEditableProperty("Entry helix %dia", "eh_diameter", format=Format.percent, unit='%', min=0, max=100, allow_none=True)
    prop_entry_mode = EnumEditableProperty("Entry mode", "entry_mode", inventory.EntryMode, allow_none=True)
    
    props_percent = set(['stepover', 'extra_width', 'trc_rate', 'eh_diameter'])

    def __init__(self, document, preset):
        self.inventory_preset = preset
        CAMTreeItem.__init__(self, document, "Tool preset")
        self.setEditable(False)
        self.resetProperties()
    def label(self):
        return f"Preset '{self.inventory_preset.name}'"
    def resetProperties(self):
        self.emitPropertyChanged()
    def data(self, role):
        if role == Qt.DisplayRole:
            return QVariant("Preset: " + self.inventory_preset.description())
        is_default = self.isDefault()
        is_local = self.isLocal()
        return self.format_item_as(role, CAMTreeItem.data(self, role), bold=is_default, italic=not is_local)
    def isDefault(self):
        return self.parent() and self.document.default_preset_by_tool.get(self.parent().inventory_tool, None) is self.inventory_preset
    def isLocal(self):
        return not self.inventory_preset.base_object or not (self.inventory_preset.equals(self.inventory_preset.base_object))
    def isModifiedStock(self):
        return self.parent().inventory_tool.base_object is not None and self.inventory_preset.base_object is not None and not (self.inventory_preset.equals(self.inventory_preset.base_object))
    def isNewObject(self):
        return self.inventory_preset.base_object is None
    def properties(self):
        return self.properties_for_cutter_type(type(self.inventory_preset.toolbit))
    @classmethod
    def properties_for_cutter_type(klass, cutter_type):
        if cutter_type == inventory.EndMillCutter:
            return klass.properties_endmill()
        elif cutter_type == inventory.DrillBitCutter:
            return klass.properties_drillbit()
        elif cutter_type == inventory.ThreadMillCutter:
            return klass.properties_threadmill()
        return []
    @classmethod
    def properties_endmill(klass):
        return [klass.prop_name, klass.prop_doc, klass.prop_hfeed, klass.prop_vfeed, klass.prop_offset, klass.prop_roughing_offset, klass.prop_stepover, klass.prop_direction, klass.prop_rpm, klass.prop_surf_speed, klass.prop_chipload, klass.prop_extra_width, klass.prop_trc_rate, klass.prop_pocket_strategy, klass.prop_axis_angle, klass.prop_eh_diameter, klass.prop_entry_mode]
    @classmethod
    def properties_drillbit(klass):
        return [klass.prop_name, klass.prop_doc, klass.prop_vfeed, klass.prop_rpm, klass.prop_surf_speed, klass.prop_chipload]
    @classmethod
    def properties_threadmill(klass):
        return [klass.prop_name, klass.prop_vfeed, klass.prop_stepover, klass.prop_rpm, klass.prop_surf_speed, klass.prop_chipload]
    def getDefaultPropertyValue(self, name):
        if name != 'surf_speed' and name != 'chipload':
            attr = PresetDerivedAttributes.attrs[self.inventory_preset.toolbit.__class__][name]
            if attr.def_value is not None:
                return attr.def_value
        return None
    def getPropertyValue(self, name):
        def toPercent(v):
            return v * 100.0 if v is not None else v
        attrs = PresetDerivedAttributes.attrs[type(self.inventory_preset.toolbit)]
        attr = attrs.get(name)
        if attr is not None:
            present, value = attr.resolve(None, self.inventory_preset)
            if present:
                return value
        elif name == 'surf_speed':
            return self.inventory_preset.toolbit.diameter * math.pi * self.inventory_preset.rpm if self.inventory_preset.rpm else None
        elif name == 'chipload':
            if isinstance(self.inventory_preset.toolbit, inventory.EndMillCutter):
                return self.inventory_preset.hfeed / (self.inventory_preset.rpm * (self.inventory_preset.toolbit.flutes or 2)) if self.inventory_preset.hfeed and self.inventory_preset.rpm else None
            elif isinstance(self.inventory_preset.toolbit, (inventory.DrillBitCutter, inventory.ThreadMillCutter)):
                return self.inventory_preset.vfeed / self.inventory_preset.rpm if self.inventory_preset.vfeed and self.inventory_preset.rpm else None
        else:
            return getattr(self.inventory_preset, name)
    def setPropertyValue(self, name, value):
        def fromPercent(v):
            return v / 100.0 if v is not None else v
        if name == 'doc':
            self.inventory_preset.maxdoc = value
        elif name in self.props_percent:
            setattr(self.inventory_preset, name, fromPercent(value))
        elif name == 'name':
            self.inventory_preset.name = value
            # Update link to inventory object
            base_tool = self.inventory_preset.toolbit.base_object
            if base_tool:
                self.inventory_preset.base_object = base_tool.presetByName(value)
            else:
                assert self.inventory_preset.base_object is None
        elif hasattr(self.inventory_preset, name):
            setattr(self.inventory_preset, name, value)
        elif name == 'surf_speed':
            if value:
                rpm = value / (self.inventory_preset.toolbit.diameter * math.pi)
                if rpm >= self.prop_rpm.min and rpm <= self.prop_rpm.max:
                    self.inventory_preset.rpm = rpm
            else:
                self.inventory_preset.rpm = None
        elif name == 'chipload':
            if isinstance(self.inventory_preset.toolbit, inventory.EndMillCutter):
                if value and self.inventory_preset.rpm:
                    hfeed = self.inventory_preset.rpm * value * (self.inventory_preset.toolbit.flutes or 2)
                    if hfeed >= self.prop_hfeed.min and hfeed <= self.prop_hfeed.max:
                        self.inventory_preset.hfeed = hfeed
                else:
                    self.inventory_preset.hfeed = None
            elif isinstance(self.inventory_preset.toolbit, (inventory.DrillBitCutter, inventory.ThreadMillCutter)):
                if value and self.inventory_preset.rpm:
                    vfeed = self.inventory_preset.rpm * value
                    if vfeed >= self.prop_vfeed.min and vfeed <= self.prop_vfeed.max:
                        self.inventory_preset.vfeed = vfeed
                else:
                    self.inventory_preset.vfeed = None
        else:
            assert False, "Unknown attribute: " + repr(name)
        if name in ['roughing_offset', 'offset', 'stepover', 'direction', 'extra_width', 'trc_rate', 'pocket_strategy', 'axis_angle', 'eh_diameter', 'entry_mode']:
            # There are other things that might require a recalculation, but do not result in visible changes
            self.document.startUpdateCAM(subset=self.document.allOperations(lambda item: item.tool_preset is self.inventory_preset))
        self.emitPropertyChanged(name)
    def returnKeyPressed(self):
        self.document.selectPresetAsDefault(self.inventory_preset.toolbit, self.inventory_preset)
    def invalidatedObjects(self, aspect):
        # Need to refresh properties for any default or calculated values updated
        return set([self] + self.document.allOperationsPlusRefinements(lambda item: item.tool_preset is self.inventory_preset))

class BaseRevertUndoCommand(QUndoCommand):
    def __init__(self, item):
        QUndoCommand.__init__(self, self.NAME)
        self.item = item
        self.old = None
    def undo(self):
        self.updateTo(self.old)

class ModifyToolUndoCommand(QUndoCommand):
    def __init__(self, item, new_data):
        QUndoCommand.__init__(self, "Modify tool")
        self.item = item
        self.new_data = new_data
        self.old_data = None
    def updateTo(self, data):
        cutter = self.item.inventory_tool
        cutter.resetTo(data)
        cutter.name = data.name
        self.item.emitDataChanged()
        self.item.document.refreshToolList()
    def undo(self):
        self.updateTo(self.old_data)
    def redo(self):
        cutter = self.item.inventory_tool
        self.old_data = cutter.newInstance()
        self.updateTo(self.new_data)

class RevertToolUndoCommand(BaseRevertUndoCommand):
    NAME = "Revert tool"
    def updateTo(self, data):
        tool = self.item.inventory_tool
        tool.resetTo(data)
        self.item.emitDataChanged()
        self.item.document.refreshToolList()
    def redo(self):
        tool = self.item.inventory_tool
        self.old = tool.newInstance()
        self.updateTo(tool.base_object)

class AddPresetUndoCommand(QUndoCommand):
    def __init__(self, item, preset):
        QUndoCommand.__init__(self, "Create preset")
        self.item = item
        self.preset = preset
    def undo(self):
        self.item.inventory_tool.deletePreset(self.preset)
        self.item.document.refreshToolList()
    def redo(self):
        self.item.inventory_tool.presets.append(self.preset)
        self.item.document.refreshToolList()

class ModifyPresetUndoCommand(QUndoCommand):
    def __init__(self, item, new_data):
        QUndoCommand.__init__(self, "Modify preset")
        self.item = item
        self.new_data = new_data
        self.old_data = None
    def updateTo(self, data):
        preset = self.item.inventory_preset
        preset.resetTo(data)
        preset.name = data.name
        preset.toolbit = self.item.parent().inventory_tool
        self.item.emitDataChanged()
        self.item.document.refreshToolList()
    def undo(self):
        self.updateTo(self.old_data)
    def redo(self):
        preset = self.item.inventory_preset
        self.old_data = preset.newInstance()
        self.updateTo(self.new_data)

class RevertPresetUndoCommand(BaseRevertUndoCommand):
    NAME = "Revert preset"
    def updateTo(self, data):
        preset = self.item.inventory_preset
        preset.resetTo(data)
        preset.toolbit = self.item.parent().inventory_tool
        self.item.emitDataChanged()
        self.item.document.refreshToolList()
    def redo(self):
        preset = self.item.inventory_preset
        self.old = preset.newInstance()
        self.updateTo(preset.base_object)

class DeletePresetUndoCommand(QUndoCommand):
    def __init__(self, document, preset):
        QUndoCommand.__init__(self, "Delete preset: " + preset.name)
        self.document = document
        self.preset = preset
        self.was_default = False
    def undo(self):
        self.preset.toolbit.undeletePreset(self.preset)
        if self.was_default:
            self.document.default_preset_by_tool[self.preset.toolbit] = self.preset
        self.document.refreshToolList()
    def redo(self):
        self.preset.toolbit.deletePreset(self.preset)
        if self.document.default_preset_by_tool.get(self.preset.toolbit, None) is self.preset:
            del self.document.default_preset_by_tool[self.preset.toolbit]
            self.was_default = True
        self.document.refreshToolList()

