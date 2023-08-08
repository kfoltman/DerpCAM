from .common_model import *

class MaterialEnumEditableProperty(EnumEditableProperty):
    def descriptions(self):
        res = []
        mat = inventory.inventory.cutter_materials
        for k, v in mat.items():
            res.append((v, v.name))
        return res

class MaterialType(EnumClass):
    WOOD = 0
    PLASTICS = 1
    ALU = 2
    MILD_STEEL = 3
    ALLOY_STEEL = 4
    TOOL_STEEL = 5
    STAINLESS_STEEL = 6
    CAST_IRON = 7
    MALLEABLE_IRON = 8
    BRASS = 9
    FOAM = 10
    descriptions = [
        (FOAM, "Foam", milling_tool.material_foam),
        (WOOD, "Wood/MDF", milling_tool.material_wood),
        (PLASTICS, "Plastics", milling_tool.material_plastics),
        (ALU, "Aluminium", milling_tool.material_aluminium),
        (BRASS, "Brass", milling_tool.material_brass),
        (MILD_STEEL, "Mild steel", milling_tool.material_mildsteel),
        (ALLOY_STEEL, "Alloy or MC steel", milling_tool.material_alloysteel),
        (TOOL_STEEL, "Tool steel", milling_tool.material_toolsteel),
        (STAINLESS_STEEL, "Stainless steel", milling_tool.material_stainlesssteel),
        (CAST_IRON, "Cast iron - gray", milling_tool.material_castiron),
        (MALLEABLE_IRON, "Cast iron - malleable", milling_tool.material_malleableiron),
    ]

@CAMTreeItem.register_class
class WorkpieceTreeItem(CAMTreeItem):
    prop_material = EnumEditableProperty("Material", "material", MaterialType, allow_none=True, none_value="Unknown")
    prop_thickness = FloatDistEditableProperty("Thickness", "thickness", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True)
    prop_clearance = FloatDistEditableProperty("Clearance", "clearance", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True)
    prop_safe_entry_z = FloatDistEditableProperty("Safe entry Z", "safe_entry_z", Format.depth_of_cut, unit="mm", min=0, max=100, allow_none=True)
    def __init__(self, document):
        CAMTreeItem.__init__(self, document, "Workpiece")
        self.resetProperties()
    def resetProperties(self):
        self.material = None
        self.thickness = None
        self.clearance = self.document.config_settings.clearance_z
        self.safe_entry_z = self.document.config_settings.safe_entry_z
        self.emitPropertyChanged()
    def properties(self):
        return [self.prop_material, self.prop_thickness, self.prop_clearance, self.prop_safe_entry_z]
    def data(self, role):
        if role == Qt.DisplayRole:
            mname = MaterialType.toString(self.material) if self.material is not None else "unknown material"
            if self.thickness is not None:
                return QVariant(f"Workpiece: {Format.depth_of_cut(self.thickness)} {mname}")
            elif self.material is not None:
                return QVariant(f"Workpiece: {mname}, unknown thickness")
            else:
                return QVariant(f"Workpiece: unknown material or thickness")
        return CAMTreeItem.data(self, role)
    def onPropertyValueSet(self, name):
        #if name == 'material':
        #    self.document.make_tool()
        if name in ('clearance', 'safe_entry_z'):
            self.document.makeMachineParams()
        self.emitPropertyChanged(name)
    def invalidatedObjects(self, aspect):
        # Depth of cut, mostly XXXKF might check for default value
        return set([self] + self.document.allOperations())

