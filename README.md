# DerpCAM

DerpCAM is a GUI application for creating 2.5D toolpaths for hobby 3-axis CNC
subtractive machines like routers and mills that are based on LinuxCNC or Grbl.
It is written in Python 3. The GUI is based on Qt5. It has been tested on Linux,
but may potentially run in other Unix based systems as well.

![screenshot](img/screenshot.png)

The overall goal was to create a simple but useful open-source (GPL), user-friendly,
well-performing application that could be used by private users and hackerspaces
without worrying about things like licensing, copy protection, Internet access
or capricious vendors removing features.

## Features

The following features are available in the current version:

* import of DXF files from LibreCAD (other DXF files may or may not work,
  some objects like points, dimensions and multiline text are ignored; ellipses
  and splines are converted to polylines during import)

* outside/inside slot milling with optional tabs, wide slots and trochoidal paths

* pocket milling with island support, multiple strategies available including a HSM strategy

* basic engraving and drilling

* helical milling of round holes of arbitrary diameter

* tabs placement either automatic or manual

* optional dogbones (corner overcut) for slot-and-tab designs, with 3 automatically-calculated variants to choose from

* ramped/helical entry support for milling hard materials

* project file support with per-project tools/presets

* global tool/preset library

* undo/redo

* G-Code output using Grbl or LinuxCNC dialects

### Incomplete/work-in-progress features

The following features may have unexpected limitations or bugs, but also might work
just fine in many cases.

* external (side) milling - producing a target shape by milling from the outside edges (HSM mode works best)

* rest machining - refining a coarsely-milled pocket or outline using a finer tool

* single-line text objects - no need to convert text to paths for most operations, it is based on system fonts like TrueType/OpenType etc.

* basic CAD-like functions (rectangles, circles, polylines) for quick tasks that don't require full CAD

* inch support - works for all CAM functionality, but not for the new CAD-like facilities

* Python API for generating G-Code from data instead of a CAD drawing

* wall profile support for efficient milling of draft angles or fillets with flat end endmills, Python API only

* automated testing facilities are limited and need a lot more work

## Requirements and installation

A Python 3 interpreter (minimum version 3.9) is necessary to run DerpCAM. The following third-party Python 3 packages are also required:

* PyQt5
* EZDXF
* PyClipper
* PyVoronoi
* Shapely
* HSM_nibble

The current method of installing DerpCAM is to download it from github:

        git clone https://github.com/kfoltman/DerpCAM/
        cd DerpCAM

Then, the required Python packages can be installed using the following command:

        pip3 install -r requirements.txt

To launch the application, use the following command from the DerpCAM directory:

        ./DerpCAM

No installation is needed, the application can run from the directory it has
been downloaded to.

## License

DerpCAM is licensed under a GNU General Public License version 3.

## Disclaimer

This project is not meant for use in a professional environment, as it lacks many
features or stability of its commercial and shareware counterparts. It does not
support G-Code dialects used by the common commercial machine vendors. It does
have bugs. Corners have been cut in many places. Use at your own risk. There
is no warranty of any kind.
