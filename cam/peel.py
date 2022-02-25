import geom, process, toolpath
import math
import pyclipper
from . import pocket

def outside_peel(shape, tool, displace=0):
    if not shape.closed:
        raise ValueError("Cannot side mill open polylines")
    tps = []
    tps_islands = []
    boundary_transformed, islands_transformed, islands_transformed_nonoverlap, boundary_transformed_nonoverlap = pocket.calculate_tool_margin(shape, tool, displace)
    expected_size = min(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1]) / 2.0
    for path in islands_transformed_nonoverlap:
        for ints in process.Shape._intersection(path, *boundary_transformed):
            # diff with other islands
            tps_islands += [toolpath.Toolpath(geom.Path(ints, True), tool)]
    displace_now = displace
    stepover = tool.stepover * tool.diameter
    while True:
        if geom.is_calculation_cancelled():
            return None
        geom.set_calculation_progress(abs(displace_now), expected_size)
        res = pocket.calc_contour(shape, tool, outside=False, displace=displace_now, subtract=islands_transformed)
        if not res:
            break
        displace_now += stepover
        process.mergeToolpaths(tps, res, tool.diameter)
    if len(tps) == 0:
        raise ValueError("Empty contour")
    tps = process.joinClosePaths(tps + tps_islands)
    geom.set_calculation_progress(expected_size, expected_size)
    return toolpath.Toolpaths(tps)
