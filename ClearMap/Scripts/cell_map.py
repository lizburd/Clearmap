#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CellMap
=======

This script is the main pipeline to analyze immediate early gene expression 
data from iDISCO+ cleared tissue [Renier2016]_.

See the :ref:`CellMap tutorial </CellMap.ipynb>` for a tutorial and usage.


.. image:: ../Static/cell_abstract_2016.jpg
   :target: https://doi.org/10.1016/j.cell.2020.01.028
   :width: 300

.. figure:: ../Static/CellMap_pipeline.png

  iDISCO+ and ClearMap: A Pipeline for Cell Detection, Registration, and 
  Mapping in Intact Samples Using Light Sheet Microscopy.


References
----------
.. [Renier2016] `Mapping of brain activity by automated volume analysis of immediate early genes. Renier* N, Adams* EL, Kirst* C, Wu* Z, et al. Cell. 2016 165(7):1789-802 <https://doi.org/10.1016/j.cell.2016.05.007>`_
"""
__author__ = 'Christoph Kirst <christoph.kirst.ck@gmail.com>'
__license__ = 'GPLv3 - GNU General Public License v3 (see LICENSE)'
__copyright__ = 'Copyright © 2020 by Christoph Kirst'
__webpage__ = 'https://idisco.info'
__download__ = 'https://www.github.com/ChristophKirst/ClearMap2'

import copy
import importlib
import os
import re
from concurrent.futures.process import BrokenProcessPool

import numpy as np
import pandas as pd
from ClearMap.IO.MHD import mhd_read
from PyQt5.QtGui import QColor
from numpy.lib import recfunctions
from matplotlib import pyplot as plt
import pyqtgraph as pg

# noinspection PyPep8Naming
import ClearMap.Alignment.Elastix as elastix
# noinspection PyPep8Naming
import ClearMap.IO.IO as clearmap_io
# noinspection PyPep8Naming
import ClearMap.Visualization.Plot3d as plot_3d
import ClearMap.Visualization.Qt.Plot3d as qplot_3d
# noinspection PyPep8Naming
import ClearMap.Alignment.Resampling as resampling
# noinspection PyPep8Naming
import ClearMap.ImageProcessing.Experts.Cells as cell_detection
# noinspection PyPep8Naming
import ClearMap.Analysis.Measurements.Voxelization as voxelization
# noinspection PyPep8Naming
import ClearMap.Alignment.Annotation as annotation
from ClearMap.Scripts.sample_preparation import PreProcessor, TabProcessor
from ClearMap.Utils.utilities import runs_on_ui
from ClearMap.gui.widgets import Scatter3D


class CellDetector(TabProcessor):
    def __init__(self, preprocessor=None):
        super().__init__()
        self.sample_config = None
        self.processing_config = None
        self.machine_config = None
        self.preprocessor = None
        self.workspace = None
        self.cell_detection_re = ('Processing block',
                                  re.compile(r'.*?Processing block \d+/\d+.*?\selapsed time:\s\d+:\d+:\d+\.\d+'))
        self.setup(preprocessor)

    def setup(self, preprocessor):
        self.preprocessor = preprocessor
        if preprocessor is not None:
            self.workspace = preprocessor.workspace
            configs = preprocessor.get_configs()
            self.sample_config = configs['sample']
            self.machine_config = configs['machine']
            self.processing_config = self.preprocessor.config_loader.get_cfg('cell_map')

            self.set_progress_watcher(self.preprocessor.progress_watcher)

    def run(self):
        # select sub-slice for testing the pipeline
        slicing = (
            slice(*self.processing_config['test_set_slicing']['dim_0']),
            slice(*self.processing_config['test_set_slicing']['dim_1']),
            slice(*self.processing_config['test_set_slicing']['dim_2'])
        )
        self.create_test_dataset(slicing)
        self.run_cell_detection(tuning=True)
        if self.processing_config['detection']['preview']:
            self.preview_cell_detection()

        self.run_cell_detection()
        # print("Number of cells detected: {}".format(self.get_n_detected_cells()))

        self.post_process_cells()

    def post_process_cells(self):
        self.processing_config.reload()
        if self.processing_config['detection']['plot_cells'] and not runs_on_ui():
            self.plot_cells()
        self.filter_cells()
        if self.processing_config['cell_filtration']['preview'] and not runs_on_ui():
            self.plot_filtered_cells()
        self.atlas_align()
        self.export_as_csv()
        self.export_to_clearmap1_fmt()
        self.voxelize()

    def voxelize(self, postfix=''):
        self.processing_config.reload()
        coordinates, cells, voxelization_parameter = self.get_voxelization_params(postfix=postfix)
        # %% Unweighted
        coordinates, counts_file_path = self.voxelize_unweighted(coordinates, voxelization_parameter)
        if self.processing_config['voxelization']['preview']['counts'] and not runs_on_ui():
            self.plot_voxelized_counts()
        # %% Weighted
        # intensities_file_path = self.voxelize_weighted(coordinates, cells, voxelization_parameter)  # WARNING: Currently causing issues
        # if self.processing_config['voxelization']['preview']['densities']:
        #     self.plot_voxelized_intensities()

    def plot_voxelized_counts(self, arange=True, parent=None):
        return plot_3d.plot(self.workspace.filename('density', postfix='counts'), arange=arange, parent=parent)

    def create_test_dataset(self, slicing):
        self.workspace.create_debug('stitched', slicing=slicing)

    def get_voxelization_params(self, postfix=''):
        voxelization_parameter = {
            'radius': self.processing_config['voxelization']['radii'],
            'verbose': True
        }
        if self.preprocessor.was_registered:
            voxelization_parameter['shape'] = clearmap_io.shape(self.preprocessor.annotation_file_path),
        else:
            voxelization_parameter['shape'] = self.preprocessor.resampled_shape
        if postfix:
            cells = self.workspace.source('cells', postfix=postfix)  # Hack to compensate for the fact that the realigned makes no sense in
            coordinates = np.array([cells[axis] for axis in 'xyz']).T
        else:
            cells = self.workspace.source('cells')
            coordinates = np.array([cells[n] for n in ['xt', 'yt', 'zt']]).T
        return coordinates, cells, voxelization_parameter

    # def voxelize_chunk(self):
    #     self.workspace.debug = True
    #     coordinates = self.get_coords()
    #
    #     shape = clearmap_io.shape(self.preprocessor.annotation_file_path),
    #     # %% Unweighted
    #     counts_file_path = self.workspace.filename('density', postfix='counts_upperlayers')
    #     clearmap_io.delete_file(self.workspace.filename('density', postfix='counts'))  # WARNING: deletes different file
    #     voxelization.voxelize(coordinates, sink=counts_file_path, radius=(2, 2, 2), shape=shape)
    #     self.workspace.debug = False

    def get_coords(self, coord_type='filtered'):
        if coord_type not in ('filtered', 'raw'):
            raise ValueError(f'Coordinate type "{coord_type}" not recognised')
        table = np.load(self.workspace.filename('cells', postfix=coord_type))
        coordinates = np.array([table[axis] for axis in ['x', 'y', 'z']]).T
        return coordinates

    def voxelize_unweighted(self, coordinates, voxelization_parameter):
        """
        Voxelize un weighted i.e. for cell counts

        Parameters
        ----------
        coordinates
            str, array or Source
            Source of point of nxd coordinates.

        voxelization_parameter
            dict

        Returns
        -------

        """
        counts_file_path = self.workspace.filename('density', postfix='counts')  # TODO: improve var name
        clearmap_io.delete_file(counts_file_path)
        voxelization.voxelize(coordinates, sink=counts_file_path, **voxelization_parameter)
        # self.remove_crust(coordinates, voxelization_parameter)  # WARNING: currently causing issues
        return coordinates, counts_file_path

    def voxelize_weighted(self, coordinates, source, voxelization_parameter):
        """
        Voxelize weighted i.e. for cell intensities

        Parameters
        ----------
        coordinates
            np.array
        source
            Source.Source
        voxelization_parameter
            dict

        Returns
        -------

        """
        intensities_file_path = self.workspace.filename('density', postfix='intensities')
        intensities = source['source']
        voxelization.voxelize(coordinates, sink=intensities_file_path, weights=intensities, **voxelization_parameter)
        return intensities_file_path

    def atlas_align(self):
        """Atlas alignment and annotation """
        # Cell alignment
        source = self.workspace.source('cells', postfix='filtered')
        coordinates = np.array([source[c] for c in 'xyz']).T
        coordinates_transformed = self.transform_coordinates(coordinates)

        if self.preprocessor.was_registered:
            # Cell annotation
            annotation.set_annotation_file(self.preprocessor.annotation_file_path)
            label = annotation.label_points(coordinates_transformed,
                                            annotation_file=self.preprocessor.annotation_file_path, key='order')
            names = annotation.convert_label(label, key='order', value='name')

        # Save results
        coordinates_transformed.dtype = [(t, float) for t in ('xt', 'yt', 'zt')]
        arrays = [source[:], coordinates_transformed]
        if self.preprocessor.was_registered:
            label = np.array(label, dtype=[('order', int)])
            names = np.array(names, dtype=[('name', 'U256')])
            arrays.extend([label, names])
        cells_data = recfunctions.merge_arrays(arrays, flatten=True, usemask=False)

        df = pd.DataFrame(cells_data)
        if self.preprocessor.was_registered:
            unique_labels = np.sort(df['order'].unique())
            color_map = {lbl: annotation.find(lbl, key='order')['rgb'] for lbl in unique_labels}

            def lookup_color(lbl):
                return color_map[lbl]

            df['color'] = df['order'].apply(lookup_color)

        clearmap_io.write(self.workspace.filename('cells'), cells_data)  # TEST: buggy ?
        if importlib.util.find_spec('pyarrow'):
            df.to_feather(os.path.splitext(self.workspace.filename('cells'))[0] + '.feather')  # TODO: add to workspace

    def transform_coordinates(self, coords):
        coords = resampling.resample_points(
            coords, sink=None,
            source_shape=self.preprocessor.raw_stitched_shape,
            sink_shape=self.preprocessor.resampled_shape)

        if self.preprocessor.was_registered:
            coords = elastix.transform_points(
                coords, sink=None,
                transform_directory=self.workspace.filename('resampled_to_auto'),
                binary=True, indices=False)

            coords = elastix.transform_points(
                coords, sink=None,
                transform_directory=self.workspace.filename('auto_to_reference'),
                binary=True, indices=False)

        return coords

    def filter_cells(self):
        self.processing_config.reload()
        cell_detection.filter_cells(source=self.workspace.filename('cells', postfix='raw'),
                                    sink=self.workspace.filename('cells', postfix='filtered'),
                                    thresholds={
                                        'source': None,
                                        'size': self.processing_config['cell_filtration']['thresholds']['size']
                                    })

    def run_cell_detection(self, tuning=False):
        self.processing_config.reload()
        self.workspace.debug = tuning  # TODO: use context manager
        cell_detection_param = copy.deepcopy(cell_detection.default_cell_detection_parameter)  # FIXME: check this is always done
        cell_detection_param['illumination'] = None  # WARNING: illumination or illumination_correction
        cell_detection_param['background_correction']['shape'] = self.processing_config['detection']['background_correction']['diameter']
        cell_detection_param['intensity_detection']['measure'] = ['source']
        cell_detection_param['shape_detection']['threshold'] = self.processing_config['detection']['shape_detection']['threshold']
        if tuning:
            clearmap_io.delete_file(self.workspace.filename('cells', postfix='bkg'))
            cell_detection_param['background_correction']['save'] = self.workspace.filename('cells', postfix='bkg')
            clearmap_io.delete_file(self.workspace.filename('cells', postfix='shape'))
            cell_detection_param['shape_detection']['save'] = self.workspace.filename('cells', postfix='shape')

            # clearmap_io.delete_file(workspace.filename('cells', postfix='maxima'))
            # cell_detection_param['maxima_detection']['save'] = workspace.filename('cells', postfix='maxima')

        processing_parameter = cell_detection.default_cell_detection_processing_parameter.copy()
        processing_parameter.update(  # TODO: store as other dict and run .update(**self.extra_detection_params)
            processes=self.machine_config['n_processes_cell_detection'],
            size_min=self.machine_config['detection_chunk_size_min'],
            size_max=self.machine_config['detection_chunk_size_max'],
            overlap=self.machine_config['detection_chunk_overlap'],
            verbose=True
        )

        n_steps = self.get_n_blocks(self.workspace.source('stitched').shape[2])  # OPTIMISE: read metadata w/out load  # TODO: round to processors
        self.prepare_watcher_for_substep(n_steps, self.cell_detection_re, 'Detecting cells')
        try:
            cell_detection.detect_cells(self.workspace.filename('stitched'),
                                        self.workspace.filename('cells', postfix='raw'),
                                        cell_detection_parameter=cell_detection_param,
                                        processing_parameter=processing_parameter,
                                        workspace=self.workspace)
        except BrokenProcessPool as err:
            print('Cell detection canceled')
            return
        finally:
            self.workspace.debug = False

    @property
    def detected(self):
        return os.path.exists(self.workspace.filename('cells', postfix='raw'))

    def export_as_csv(self):
        csv_file_path = self.workspace.filename('cells', extension='csv')
        self.get_cells_df().to_csv(csv_file_path)

    def export_to_clearmap1_fmt(self):
        """ClearMap 1.0 export (will generate the files cells_ClearMap1_intensities, cells_ClearMap1_points_transformed,
        cells_ClearMap1_points necessaries to use the analysis script of ClearMap1.
        In ClearMap2 the 'cells' file contains already all this information)
        In order to align the coordinates when we have right and left hemispheres, if the orientation of the brain is left,
         will calculate the new coordinates for the Y axes (resta a lonxitude do eixo Y),
         this change will not affect the orientation of the heatmaps,
        since these are generated from the ClearMap2 file 'cells'
        """

        source = self.workspace.source('cells')
        clearmap1_format = {'points': ['x', 'y', 'z'],
                            'points_transformed': ['xt', 'yt', 'zt'],
                            'intensities': ['source', 'dog', 'background', 'size']}
        for filename, names in clearmap1_format.items():
            sink = self.workspace.filename('cells', postfix=['ClearMap1', filename])
            print(filename, sink)
            data = np.array(
                [source[name] if name in source.dtype.names else np.full(source.shape[0], np.nan) for name in names]
            )
            data = data.T   # FIXME: seems hacky
            # if self.sample_config['orientation'] == (1, -2, 3):  # WARNING: seems hacky, why that particular orientation
            #     if filename == 'points_transformed':
            #         data[:, 1] = 528 - data[:, 1]  # WARNING: why 528
            clearmap_io.write(sink, data)

    def plot_cells(self):
        source = self.workspace.source('cells', postfix='raw')
        plt.figure(1)
        plt.clf()
        names = source.dtype.names
        nx, ny = plot_3d.subplot_tiling(len(names))
        for i, name in enumerate(names):
            plt.subplot(nx, ny, i + 1)
            plt.hist(source[name])
            plt.title(name)
        plt.tight_layout()

    def plot_cells_3d_scatter_w_atlas_colors(self, parent=None):
        if self.preprocessor.was_registered:
            dv = qplot_3d.plot(clearmap_io.source(annotation.default_reference_file),  # FIXME: check that default is updated
                               arange=False, lut='white', parent=parent)[0]
        else:
            dv = qplot_3d.plot(self.workspace.filename('resampled'),
                               arange=False, lut='white', parent=parent)[0]

        scatter = pg.ScatterPlotItem()

        dv.view.addItem(scatter)
        dv.scatter = scatter

        df = self.get_cells_df()

        coordinates = df[['xt', 'yt', 'zt']].values.astype(np.int)  # required to match integer z
        colors = df['color'].values * 255
        colors = np.array([QColor(*cols.astype(np.int)) for cols in colors])
        dv.scatter_coords = Scatter3D(coordinates, colors=colors, half_z_size=0)
        dv.updateSlice()  # WARNING: does not work

        return [dv]

    def get_cells_df(self):
        feather_path = self.workspace.filename('cells').replace('.npy', '.feather')  # TODO: add to workspace
        if os.path.exists(feather_path):
            df = pd.read_feather(feather_path)
        else:
            df = pd.DataFrame(np.load(self.workspace.filename('cells')))
        return df

    def plot_filtered_cells(self, parent=None, smarties=False):
        coordinates = self.get_coords('filtered')
        stitched_path = self.workspace.filename('stitched')
        dvs = qplot_3d.plot(stitched_path, arange=False, lut='white', parent=parent)
        self.filtered_cells = Scatter3D(coordinates, smarties=smarties)
        scatter = pg.ScatterPlotItem()
        dvs[0].view.addItem(scatter)
        dvs[0].scatter_coords = self.filtered_cells
        dvs[0].scatter = scatter
        dvs[0].updateSlice()
        return dvs

    def plot_background_substracted_img(self):
        coordinates = np.hstack([self.workspace.source('cells', postfix='raw')[c][:, None] for c in 'xyz'])
        p = plot_3d.list_plot_3d(coordinates)
        return plot_3d.plot_3d(self.workspace.filename('stitched'), view=p, cmap=plot_3d.grays_alpha(alpha=1))

    def remove_crust(self, coordinates,voxelization_parameter):
        dist2surf = clearmap_io.read(self.preprocessor.distance_file_path)
        threshold = 3
        shape = dist2surf.shape

        good_coordinates = np.logical_and(np.logical_and(coordinates[:, 0] < shape[0],
                                                         coordinates[:, 1] < shape[1]),
                                          coordinates[:, 2] < shape[2]).nonzero()[0]
        coordinates = coordinates[good_coordinates]
        coordinates_wcrust = coordinates[np.asarray(
            [dist2surf[tuple(np.floor(coordinates[i]).astype(int))] > threshold for i in
             range(coordinates.shape[0])]).nonzero()[0]]

        voxelization.voxelize(coordinates_wcrust, sink=self.workspace.filename('density', postfix='counts_wcrust'),
                              **voxelization_parameter)

    def preview_cell_detection(self, parent=None, arange=True, sync=True):
        sources = [self.workspace.filename('stitched'),
                   self.workspace.filename('cells', postfix='bkg'),
                   self.workspace.filename('cells', postfix='shape')
                   ]
        sources = [s for s in sources if os.path.exists(s)]  # Remove missing files (if not tuning)
        return plot_3d.plot(sources, arange=arange, sync=sync, lut='white', parent=parent)

    def get_n_detected_cells(self):
        if os.path.exists(self.workspace.filename('cells', postfix='raw')):
            coords = self.get_coords(coord_type='raw')
            return np.max(coords.shape)  # TODO: check dimension instead
        else:
            return 0

    def get_n_fitlered_cells(self):
        if os.path.exists(self.workspace.filename('cells', postfix='filtered')):
            coords = self.get_coords(coord_type='filtered')
            return np.max(coords.shape)  # TODO: check dimension instead
        else:
            return 0

    def plot_voxelized_intensities(self, arange=True):
        return plot_3d.plot(self.workspace.filename('density', postfix='intensities'), arange=arange)

    def get_n_blocks(self, dim_size):
        blk_size = self.machine_config['detection_chunk_size_max']
        overlap = self.machine_config['detection_chunk_overlap']
        n_blocks = int(np.ceil((dim_size - blk_size) / (blk_size - overlap) + 1))
        return n_blocks


if __name__ == "__main__":
    import sys
    preprocessor = PreProcessor()
    preprocessor.setup(sys.argv[1:3])
    preprocessor.setup_atlases()
    # preprocessor.run()

    detector = CellDetector(preprocessor)
