# DerpCAM

DerpCAM is a GUI application for creating 2.5D toolpaths for hobby 3-axis CNC
subtractive machines like routers and mills that are based on LinuxCNC or Grbl.
It is written in Python. The GUI is based on Qt5. It has been tested on Linux,
but may potentially run in other Unix based systems as well.

The overall goal was to create a simple but useful open-source, user-friendly,
well-performing application that could be used by private users and hackerspaces
without worrying about things like licensing, copy protection, Internet access
or capricious vendors removing features.

It is not meant for use in a professional environment, as it lacks many
features or stability of its commercial and shareware counterparts. It does not
support G-Code dialects used by the common commercial machine vendors. It does
have bugs. Corners have been cut in many places. Use at your own risk. There
is no warranty of any kind.

The following features are available in the current version:

* import of DXF files from LibreCAD (other DXF files may or may not work,
  some objects like points, splines, ellipses, dimensions and multiline text
  are not supported)

* outside/inside slot milling with optional tabs, wide slots and trochoidal paths

* pocket milling with island support, multiple strategies available (including a HSM strategy via an external library by Duncan Law)

* basic engraving and drilling

* helical milling of round holes of arbitrary diameter

* tabs placement either automatic or manual

* optional dogbones for slot-and-tab designs (2 automatically-calculated variants to choose from)

* project file support with per-project tools/presets

* global tool/preset library

* G-Code output using Grbl or LinuxCNC dialects

Some more features are only partially implemented:

* external milling - producing a target shape by milling from the outside

* rest machining - refining a coarsely-milled pocket using a finer tool

* single-line text objects - no need to convert to paths for most operations, uses system fonts like TrueType/OpenType etc.

* inch support - the application works in metric, but can import inch-based drawings, output inch-based G-Code and accept values in inches in some places

* ramped entry support - picks helical, linear or plunge based on what is possible

* automated testing facilities are limited and need a lot more work
