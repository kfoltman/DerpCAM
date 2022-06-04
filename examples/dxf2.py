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
from gui import model, cutter_mgr, main_win, settings
import json

settings = settings.ConfigSettings()
settings.update()
document = model.DocumentModel(settings)

parser = argparse.ArgumentParser(description="Generate G-Code from DXF data")
parser.add_argument('input', type=str, help="File to load on startup", nargs='?')
parser.add_argument('--export-gcode', nargs=1, metavar='OUTPUT_FILENAME', help="Convert a project file to G-Code and exit")
parser.add_argument('--close', action='store_true', help="Close the UI immediately after loading the project (for testing)")

args = parser.parse_args()
has_gui = not args.export_gcode

if has_gui:
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("My CAM experiment")
    app.processEvents()
else:
    app = QCoreApplication(sys.argv)
app.setOrganizationName("kfoltman")
app.setApplicationName("DerpCAM")

retcode = 0

def doLoad(args):
    if args.input:
        fn = args.input
        ext = os.path.splitext(fn)[1].lower()
        if ext == ".dxf":
            document.importDrawing(fn)
        elif ext == ".dcp":
            document.loadProject(fn)
        else:
            raise ValueError("Unrecognized file extension")

if args.export_gcode:
    if not args.input or not args.input.endswith(".dcp"):
        sys.stderr.write("Error: Input file not specified\n")
        retcode = 1
    elif args.export_gcode[0].endswith(".dcp") or args.export_gcode[0].endswith(".dxf"):
        sys.stderr.write("Error: Output filename has an extension that would suggest it is an input file\n")
        retcode = 1
    else:
        try:
            retcode = 0
            doLoad(args)
            document.validateForOutput()
            document.exportGcode(args.export_gcode[0])
        except ValueError as e:
            sys.stderr.write(f"Error: {e}\n")
            retcode = 2
else:
    cutter_mgr.loadInventory()
    w = main_win.CAMMainWindow(document, settings)
    w.initUI()
    w.showMaximized()
    try:
        doLoad(args)
    except Exception as e:
        QMessageBox.critical(w, "Error while loading a project/drawing", str(e))
    if args.close:
        if not document.waitForUpdateCAM():
            sys.stderr.write(f"Error: Operation cancelled\n")
            retcode = 1
        else:
            errors = document.checkCAMErrors()
            if any(errors):
                retcode = 1
                for i in errors:
                    if i:
                        sys.stderr.write(f"Error: {i}\n")
        QTimer.singleShot(0, app.quit)
    res = app.exec_()
    if not args.close or res:
        retcode = res
    del w
    del app
    cutter_mgr.saveInventory()

sys.exit(retcode)
