import geom, process, toolpath
import math
import pyclipper
from . import pocket

def outside_peel(shape, tool, displace=0):
    if not shape.closed:
        raise ValueError("Cannot side mill open polylines")
    tps = []
    tps_islands = []
    boundary = geom.IntPath(shape.boundary)
    boundary_transformed = [ geom.IntPath(i, True) for i in process.Shape._offset(boundary.int_points, True, tool.diameter * 0.5 * geom.GeometrySettings.RESOLUTION) ]
    islands_transformed = []
    islands_transformed_nonoverlap = []
    islands = shape.islands
    expected_size = min(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1]) / 2.0
    for island in islands:
        pc = pyclipper.PyclipperOffset()
        pts = geom.PtsToInts(island)
        if not pyclipper.Orientation(pts):
            pts = list(reversed(pts))
        pc.AddPath(pts, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        res = pc.Execute((tool.diameter * 0.5 + displace) * geom.GeometrySettings.RESOLUTION)
        if not res:
            return None
        if geom.is_calculation_cancelled():
            return None
        res = [geom.IntPath(it, True) for it in res]
        islands_transformed += res
        islands_transformed_nonoverlap += [it for it in res if not geom.run_clipper_simple(pyclipper.CT_DIFFERENCE, [it], boundary_transformed, bool_only=True)]
    if islands_transformed_nonoverlap:
        islands_transformed_nonoverlap = process.Shape._union(*[i for i in islands_transformed_nonoverlap], return_ints=True)
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
