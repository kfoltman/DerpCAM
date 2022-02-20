import argparse
import os.path
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

import process
import gcodegen
import view
from gui import propsheet, settings, canvas, model, inventory, dock, cutter_mgr, main_win
import json

document = model.DocumentModel()

parser = argparse.ArgumentParser(description="Generate G-Code from DXF data")
parser.add_argument('input', type=str, help="File to load on startup", nargs='?')
parser.add_argument('--export-gcode', nargs=1, metavar='OUTPUT_FILENAME', help="Convert a project file to G-Code and exit")

QCoreApplication.setOrganizationName("kfoltman")
QCoreApplication.setApplicationName("DerpCAM")

app = QApplication(sys.argv)
app.setApplicationDisplayName("My CAM experiment")
app.processEvents()

args = parser.parse_args()

cutter_mgr.loadInventory()

w = main_win.CAMMainWindow(document)
w.initUI()
if args.input:
    if not args.export_gcode:
        w.showMaximized()
    fn = args.input
    fnl = fn.lower()
    if fnl.endswith(".dxf"):
        w.importDrawing(fn)
    elif fnl.endswith(".dcp"):
        w.loadProject(fn)
if args.export_gcode:
    if not args.input or not args.input.endswith(".dcp"):
        sys.stderr.write("Error: Input file not specified\n")
        retcode = 1
    elif args.export_gcode[0].endswith(".dcp") or args.export_gcode[0].endswith(".dxf"):
        sys.stderr.write("Error: Output filename has an extension that would suggest it is an input file\n")
        retcode = 1
    else:
        try:
            w.document.validateForOutput()
            w.exportGcode(args.export_gcode[0])
            retcode = 0
        except ValueError as e:
            sys.stderr.write(str(e) + "\n")
            retcode = 2
else:
    w.showMaximized()
    retcode = app.exec_()
    del w
    del app

    cutter_mgr.saveInventory()

sys.exit(retcode)
