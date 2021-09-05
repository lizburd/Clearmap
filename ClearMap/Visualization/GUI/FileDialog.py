# -*- coding: utf-8 -*-
"""
FileDialog widget

Provides a FileDialog that opens both folders or directories
"""
__author__    = 'Christoph Kirst <ckirst@rockefeller.edu>'
__license__   = 'MIT License <http://www.opensource.org/licenses/mit-license.php>'
__copyright__ = 'Copyright 2017 by Christoph Kirst, The Rockefeller University, New York City'

from pyqtgraph import QtGui, QtCore

class FileDialog(QtGui.QFileDialog):
    def __init__(self, parent=None):
        super (FileDialog, self).__init__()
        self.init_ui()

    def init_ui(self):
        self.select_dir_cb = QtGui.QCheckBox('Select directory')
        self.select_dir_cb.stateChanged.connect(self.toggle_files_folders)
        self.layout().addWidget(self.select_dir_cb)

    def toggle_files_folders(self, state):
        if state == QtCore.Qt.Checked:
            self.setFileMode(self.Directory)
            self.setOption(self.ShowDirsOnly, True)
        else:
            self.setFileMode(self.AnyFile)
            self.setOption(self.ShowDirsOnly, False)
            self.setNameFilter('All files (*)')

def test():
    from pyqtgraph import mkQApp
    import ClearMap.Visualization.GUI.FileDialog as fd
    
    mkQApp()
    dialog = fd.FileDialog()

    ret = dialog.exec_();
    print('return: ', ret);
    print(dialog.selectedFiles());


if __name__ == '__main__':
    test()

  