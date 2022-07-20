from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

class AboutDlg(QDialog):
    def initUI(self):
        self.setWindowTitle("About DerpCAM")
        self.layout = QVBoxLayout(self)
        title = QLabel('''\
<h1>DerpCAM</h1>
<p><i>CAM/toolpath generator for hobby CNC routers and mills</i></p>
<p>Version: development</p>
<p>Authors: Krzysztof Foltman, Duncan Law</p>
<p> This program is free software: you can redistribute it and/or modify<br>
    it under the terms of the GNU General Public License as published by<br>
    the Free Software Foundation, either version 3 of the License, or<br>
    (at your option) any later version.<br>
<br>
    This program is distributed in the hope that it will be useful,<br>
    but WITHOUT ANY WARRANTY; without even the implied warranty of<br>
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the<br>
    GNU General Public License for more details.</p>
<p><a href="http://github.com/kfoltman/DerpCAM/">Project GitHub page</a></p>
<p> </p>
''')
        title.setTextFormat(Qt.RichText)
        self.layout.addWidget(title)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok)
        self.buttonBox.accepted.connect(self.accept)
        self.layout.addWidget(self.buttonBox)
        