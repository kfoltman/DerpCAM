from DerpCAM.common import geom
import math
import pyclipper
from . import pocket, shapes, toolpath

def outside_peel(shape, tool, displace=0):
    if not shape.closed:
        raise ValueError("Cannot side mill open polylines")
    tps = []
    boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap = pocket.calculate_tool_margin(shape, tool, displace)
    expected_size = min(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1]) / 2.0
    displace_now = displace - tool.diameter
    stepover = tool.stepover * tool.diameter
    while True:
        if geom.is_calculation_cancelled():
            return None
        geom.set_calculation_progress(abs(displace_now), expected_size)
        res = pocket.calc_contour(shape, tool, outside=False, displace=displace_now, subtract=islands_transformed)
        if not res:
            break
        displace_now += stepover
        tps += res.toolpaths
    if len(tps) == 0:
        raise ValueError("Empty contour")
    tps_islands = []
    for path in islands_transformed_nonoverlap:
        for ints in shapes.Shape._intersection(path, *boundary_transformed):
            # diff with other islands
            tps_islands += [toolpath.Toolpath(geom.Path(ints, True), tool)]
    # fixPathNesting normally expects the opposite order (inside to outside)
    tps = list(reversed(toolpath.fixPathNesting(list(reversed(tps)))))
    tps = toolpath.joinClosePathsWithCollisionCheck(tps, boundary_transformed, islands_transformed)
    tps_islands = toolpath.joinClosePathsWithCollisionCheck(tps_islands, boundary_transformed, islands_transformed)
    geom.set_calculation_progress(expected_size, expected_size)
    return toolpath.Toolpaths(tps + tps_islands)

def outside_peel_hsm(shape, tool, zigzag, displace=0):
    return pocket.hsm_peel(shape, tool, zigzag=zigzag, displace=displace, from_outside=True)
