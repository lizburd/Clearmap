import os
import re

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import QRectF
from PyQt5.QtWidgets import QWidget, QDialogButtonBox

from ClearMap.IO.metadata import pattern_finders_from_base_dir
from ClearMap.Visualization import Plot3d as plot_3d
from ClearMap.config.config_loader import ConfigLoader
from ClearMap.gui.dialogs import make_splash
from ClearMap.gui.pyuic_utils import loadUiType


class RectItem(pg.GraphicsObject):  # Derived from https://stackoverflow.com/a/60012800
    def __init__(self, rect, parent=None):
        super().__init__(parent)
        self._rect = rect
        self.picture = QtGui.QPicture()
        self._generate_picture()
        self.name = 'rect'

    def __str__(self):
        return 'Rect {}, coordinates: {}'.format(self.name, self.rect.getCoords())

    @property
    def rect(self):
        return self._rect

    # TODO: setWidth, setLeft ... that call self.rect.setWidth + self._generate_picture

    def _generate_picture(self):
        painter = QtGui.QPainter(self.picture)
        painter.setPen(pg.mkPen("#FFFF007d"))
        painter.setBrush(pg.mkBrush("#2e34367d"))
        painter.drawRect(self.rect)
        painter.end()

    def paint(self, painter, option, widget=None):
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QRectF(self.picture.boundingRect())


class RedCross(pg.GraphicsObject):
    def __init__(self, coords=None, size=[10, 10], parent=None):
        super().__init__(parent)
        self.color = "#FF00007d"
        if coords is None:
            coords = [0, 0]
        self.size = size
        self._rect = QRectF(coords[0]-self.size[0]/2, coords[1]-self.size[1]/2, self.size[0], self.size[1])  # TODO@ set as fraction of image size
        self.coords = coords
        self.picture = QtGui.QPicture()

    def set_coords(self, coords):
        x, y = coords
        self.coords = coords
        self._rect.setCoords(x-self.size[0]/2, y-self.size[1]/2,
                             x+self.size[0]/2, y+self.size[1]/2)
        self._generate_picture()

    def _generate_picture(self):
        painter = QtGui.QPainter(self.picture)
        pen = pg.mkPen(self.color)
        pen.setWidth(4)
        painter.setPen(pen)
        painter.setBrush(pg.mkBrush(self.color))
        painter.drawLine(self._rect.topLeft(), self._rect.bottomRight())
        painter.drawLine(self._rect.bottomLeft(), self._rect.topRight())
        painter.drawPicture(0, 0, self.picture)
        painter.end()

    def paint(self, painter, option, widget=None):
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):  # TODO: check if we need this method
        return QRectF(self.picture.boundingRect())


class OrthoViewer(object):
    def __init__(self, img=None, parent=None):
        self.img = img
        self.parent = parent
        self.params = None
        if img is not None:
            self.shape = img.shape
        else:
            self.shape = None
        self.rectangles = []

    def setup(self, img, params, parent=None):
        self.img = img
        self.params = params
        self.parent = parent
        self.shape = img.shape
        self.rectangles = []

    @property
    def width(self):
        return self.shape[0]

    @property
    def height(self):
        return self.shape[1]

    @property
    def depth(self):
        return self.shape[2]

    def update_x_min(self, val):
        if self.params is not None:
            val = self.params.scale_x(val)
        self._update_rect('x', val, 'min')

    def update_x_max(self, val):
        if self.params is not None:
            val = self.params.scale_x(val)
        self._update_rect('x', val, 'max')

    def update_y_min(self, val):
        if self.params is not None:
            val = self.params.scale_y(val)
        self._update_rect('y', val, 'min')

    def update_y_max(self, val):
        if self.params is not None:
            val = self.params.scale_y(val)
        self._update_rect('y', val, 'max')

    def update_z_min(self, val):
        if self.params is not None:
            val = self.params.scale_z(val)
        self._update_rect('z', val, 'min')

    def update_z_max(self, val):
        if self.params is not None:
            val = self.params.scale_z(val)
        self._update_rect('z', val, 'max')

    def update_ranges(self):
        self.update_x_min(self.params.crop_x_min)
        self.update_x_max(self.params.crop_x_max)
        self.update_y_min(self.params.crop_y_min)
        self.update_y_max(self.params.crop_y_max)
        self.update_z_min(self.params.crop_z_min)
        self.update_z_max(self.params.crop_z_max)

    def get_rect(self, axis, min_or_max):
        axes = ('x', 'y', 'z')
        if axis in axes:
            axis = axes.index(axis)
        idx = axis * 2 + (min_or_max == 'max')
        return self.rectangles[idx]

    def _update_rect(self, axis, val, min_or_max='min'):
        if not self.rectangles:
            return
        rect_itm = self.get_rect(axis, min_or_max)
        if min_or_max == 'min':
            rect_itm.rect.setWidth(val)
        else:
            rect_itm.rect.setLeft(val)
        try:
            graph = getattr(self.parent, self.parent.graph_names[axis])  # REFACTOR: not the cleanest
        except KeyError:
            print('Wrong graphs displayed, skipping')
            return
        rect_itm._generate_picture()
        graph.view.update()

    def add_cropping_bars(self):
        self.rectangles = []
        matched_axes = (1, 0, 1)  # TODO: compute
        for i, dv in enumerate(self.dvs):
            min_rect = RectItem(QRectF(0, 0, 0, self.shape[matched_axes[i]]))
            self.rectangles.append(min_rect)
            dv.view.addItem(min_rect)
            max_rect = RectItem(QRectF(self.shape[i], 0, 0, self.shape[matched_axes[i]]))
            self.rectangles.append(max_rect)
            dv.view.addItem(max_rect)

    def plot_orthogonal_views(self, img=None, parent=None):
        if img is None:
            img = self.img.array
        if parent is None:
            parent = self.parent
            if parent is None:
                raise ValueError('Parent not set')
        x = np.copy(img)
        y = np.copy(img).swapaxes(0, 1)
        z = np.copy(img).swapaxes(0, 2)
        dvs = plot_3d.plot([x, y, z], arange=False, lut='white', parent=parent, sync=False)
        self.dvs = dvs
        return dvs


class PbarWatcher(QWidget):  # Inspired from https://stackoverflow.com/a/66266068
    progress_name_changed = QtCore.pyqtSignal(str)
    progress_changed = QtCore.pyqtSignal(int)
    max_changed = QtCore.pyqtSignal(int)

    main_max_changed = QtCore.pyqtSignal(int)
    main_progress_changed = QtCore.pyqtSignal(int)

    def __init__(self, max_progress=100, main_max_progress=1, parent=None):
        super().__init__(parent)
        self.__progress = 0
        self.__main_progress = 1
        self.__max_progress = max_progress
        self.__main_max_progress = main_max_progress
        self.range_fraction = 1

        self.log_path = None
        self.previous_log_length = 0  # The log length at the end of the previous operation
        self.n_dones = 0
        self.pattern = None

    def get_progress(self):
        return self.__progress

    def set_progress(self, value):
        if self.__progress == value:
            return
        self.__progress = round(value)
        self.progress_changed.emit(self.__progress)

    def set_main_progress(self, value):
        if self.__main_progress == value:
            return
        self.__main_progress = round(value)
        self.main_progress_changed.emit(self.__main_progress)

    def increment_main_progress(self, increment=1):
        self.set_main_progress(self.__main_progress + round(increment))

    def increment(self, increment):
        if isinstance(increment, float):
            self.set_progress(self.__progress + int(self.max_progress * increment))
        elif isinstance(increment, int):
            self.set_progress(self.__progress + increment)

    @property
    def max_progress(self):
        return self.__max_progress

    @max_progress.setter
    def max_progress(self, value):
        self.__max_progress = round(value)
        self.max_changed.emit(self.__max_progress)

    @property
    def main_max_progress(self):
        return self.__main_max_progress

    @main_max_progress.setter
    def main_max_progress(self, value):
        self.__main_max_progress = round(value)
        self.main_max_changed.emit(self.__main_max_progress)

    def __match(self, line):
        if isinstance(self.pattern, tuple):  # TODO: cache
            return self.pattern[0] in line and self.pattern[1].match(line)  # Most efficient
        elif isinstance(self.pattern, str):
            return self.pattern in line
        elif isinstance(self.pattern, re.Pattern):
            return self.pattern.match(line)

    def count_dones(self):
        with open(self.log_path, 'r') as log:
            log.seek(self.previous_log_length)
            new_lines = log.readlines()
        n_dones = len([ln for ln in new_lines if self.__match(ln)])
        self.n_dones += n_dones
        self.previous_log_length += self.__get_log_bytes(new_lines)
        return self.n_dones

    def reset_log_length(self):  # To bind
        with open(self.log_path, 'r') as log:
            self.previous_log_length = self.__get_log_bytes(log.readlines())
            self.n_dones = 0

    def __get_log_bytes(self, log):
        return sum([len(ln) for ln in log])

    def prepare_for_substep(self, step_length, pattern, step_name):
        """

        Parameters
        ----------
        step_name
            str
        step_length
            int The number of steps in the operation
        pattern
            str or re.Pattern or (str, re.Pattern) the text to look for in the logs to check for progress

        Returns
        -------

        """
        self.max_progress = step_length
        self.pattern = pattern
        self.reset_log_length()
        self.set_progress(0)
        self.progress_name_changed.emit(step_name)


class Scatter3D:
    def __init__(self, coordinates, smarties=False):
        self.coordinates = coordinates
        if smarties:
            self.colours = np.random.randint(255, size=self.coordinates.shape)
        else:
            self.colours = None

    def get_all_data(self, main_z, half_z_size=3):
        pos = np.empty((0, 2))
        colours = np.empty((0, 3))
        sizes = np.empty(0)
        for i in range(main_z - half_z_size, main_z + half_z_size):
            if i < 0:
                continue
            else:
                z = i
            pos = np.vstack((pos, self.get_pos(z)))
            if self.colours is not None:
                colours = np.vstack((colours, self.get_colours(z)))
            sizes = np.hstack((sizes, self.get_symbol_sizes(main_z, z)))
        data = {'pos': pos,
                'size': sizes}
        if self.colours is not None:
            data['pen'] = [pg.mkPen(c) for c in colours]
        return data

    def get_symbol_sizes(self, main_z, z, half_size=3):
        marker_size = round(10 * ((half_size - abs(main_z - z)) / half_size))
        n_markers = len(self.get_pos(z))
        return np.full(n_markers, marker_size)

    def get_colours(self, z):
        return self.colours[self.coordinates[:, 2] == z]

    def get_pos(self, z):
        return self.coordinates[self.coordinates[:, 2] == z][:, :2]


class PatternDialog:
    def __init__(self, src_folder, app=None):
        self.src_folder = src_folder
        self.app = app

        cls, _ = loadUiType('ClearMap/gui/pattern_prompt.ui', patch_parent_class='QDialog')
        dlg = cls()
        dlg.setWindowTitle('File paths wizzard')
        dlg.setupUi()
        self.dlg = dlg
        self.fix_btn_boxes_text()
        self.connect_buttons()

        self.pattern_strings = {}
        self.patterns_finders = self.get_patterns()

        for pattern_idx, p_finder in enumerate(self.patterns_finders):
            for subpattern_idx, digit_cluster in enumerate(p_finder.pattern.digit_clusters):
                label_widget, pattern_widget, combo_widget = self.get_widgets(pattern_idx, subpattern_idx)
                pattern_widget.setText(p_finder.pattern.highlight_digits(subpattern_idx))
                self.enable_widgets((label_widget, pattern_widget, combo_widget))
            for subpattern_idx in range(subpattern_idx + 1, 4):
                self.hide_widgets(self.get_widgets(pattern_idx, subpattern_idx))

    def connect_buttons(self):
        self.dlg.pattern0ButtonBox.button(QDialogButtonBox.Apply).clicked.connect(self.validate_pattern0)
        self.dlg.pattern1ButtonBox.button(QDialogButtonBox.Apply).clicked.connect(self.validate_pattern1)
        self.dlg.pattern2ButtonBox.button(QDialogButtonBox.Apply).clicked.connect(self.validate_pattern2)

        self.dlg.mainButtonBox.button(QDialogButtonBox.Apply).clicked.connect(self.save_results)

    def save_results(self):
        config_loader = ConfigLoader(self.src_folder)
        sample_cfg = config_loader.get_cfg('sample')
        for channel_name, pattern_string in self.pattern_strings.items():
            sample_cfg['src_paths'][channel_name] = pattern_string
        sample_cfg.write()

    def __validate_pattern(self, pattern_idx):
        pattern = self.patterns_finders[pattern_idx].pattern
        for subpattern_idx, digit_cluster in enumerate(pattern.digit_clusters):
            _, _, combo_widget = self.get_widgets(pattern_idx, subpattern_idx)
            axis_name = combo_widget.currentText()
            n_axis_chars = len(pattern.digit_clusters[subpattern_idx])

            if axis_name == 'C':
                raise NotImplementedError('Channel splitting is not implemented yet')
            else:
                pattern_element = '<{axis},{length}>'.format(axis=axis_name, length=n_axis_chars)
                pattern.pattern_elements[subpattern_idx] = pattern_element

        result_widget = getattr(self.dlg, 'result_{}'.format(pattern_idx))
        pattern_string = pattern.get_formatted_pattern()
        pattern_string = os.path.join(self.patterns_finders[pattern_idx].folder, pattern_string)

        result_widget.setText(pattern_string)

        channel_name = getattr(self.dlg, 'channelComboBox{}'.format(pattern_idx)).currentText()
        self.pattern_strings[channel_name] = pattern_string

    def validate_pattern0(self):
        self.__validate_pattern(0)

    def validate_pattern1(self):
        self.__validate_pattern(1)

    def validate_pattern2(self):
        self.__validate_pattern(2)

    def fix_btn_boxes_text(self):
        for btn_box in self.dlg.findChildren(QDialogButtonBox):
            if btn_box.property('applyText'):
                btn_box.button(QDialogButtonBox.Apply).setText(btn_box.property('applyText'))

    def get_patterns(self):
        splash, progress_bar = make_splash(bar_max=0)
        splash.show()  # TODO: other thread to show at the same time
        # update_pbar(self.app, progress_bar, 10)
        # self.app.processEvents()
        pattern_finders = pattern_finders_from_base_dir(self.src_folder)
        splash.finish(self.dlg)
        return pattern_finders

    def get_widgets(self, pattern_idx, subpattern_idx):
        label_widget = getattr(self.dlg, 'label{}_{}'.format(pattern_idx, subpattern_idx))
        pattern_widget = getattr(self.dlg, 'pattern{}_{}'.format(pattern_idx, subpattern_idx))
        combo_widget = getattr(self.dlg, 'pattern{}_{}ComboBox'.format(pattern_idx, subpattern_idx))
        return label_widget, pattern_widget, combo_widget

    def enable_widgets(self, widget_list):  # REFACTOR: parent dialog class
        for w in widget_list:
            w.setEnabled(True)

    def disable_widgets(self, widget_list):  # REFACTOR: parent dialog class
        for w in widget_list:
            w.setEnabled(False)

    def hide_widgets(self, widget_list):  # REFACTOR: parent dialog class
        for w in widget_list:
            w.setHidden(True)

    def unhide_widgets(self, widget_list):  # REFACTOR: parent dialog class
        for w in widget_list:
            w.setHidden(False)

    def exec(self):
        self.dlg.exec()
