# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

from openradar import calc
from openradar import config
from openradar import io
from openradar import utils
from openradar import gridtools

from scipy import interpolate

from datetime import datetime as Datetime
from datetime import timedelta as Timedelta

import h5py
import json
import logging
import numpy as np
import os
import re
import shutil

BAND_RAIN = 1
BAND_RANG = 2
BAND_ELEV = 3

BAND_META = {
    BAND_RAIN: dict(name='rain'),
    BAND_RANG: dict(name='range'),
    BAND_ELEV: dict(name='elevation'),
}

# Regex patterns
PATTERNS = (
    # KNMI
    re.compile(
        'RAD_(?P<code>.*)_VOL_NA_(?P<timestamp>[0-9]{12})\.h5',
    ),
    # DWD archive
    re.compile(
        'raa00-dx_(?P<code>.*)-(?P<timestamp>[0-9]{10})-dwd---bin',
    ),
    # DWD operational
    re.compile(
        'raa00-dx_(?P<id>.*)-(?P<timestamp>[0-9]{10})-(?P<code>.*)---bin',
    ),
    # Jabbeke on FTP
    re.compile(
        'T_PAGW42_C_EBUM_(?P<timestamp>[0-9]{14})\.hdf',
    )
)


def create_basegrid(extent, cellsize):
    left, right, top, bottom = extent
    cellwidth, cellheight = cellsize
    width, height = right - left, top - bottom

    extent = [left, right, top, bottom]
    size = int(width / cellwidth), int(height / cellheight)
    projection = utils.projection(utils.RD)

    return gridtools.BaseGrid(
        extent=extent,
        size=size,
        projection=projection,
    )

BASEGRID = create_basegrid(config.COMPOSITE_EXTENT, config.COMPOSITE_CELLSIZE)
NOWCASTGRID = create_basegrid(config.NOWCAST_EXTENT, config.NOWCAST_CELLSIZE)


class ScanSignature(object):
    """
    Hold datetime and code for a scan.

    Import from scanname or from code and datetime.
    Export to scanname or to code and datetime.
    Get timestamp or scanpath.
    """

    def __init__(self, scan_name=None, scan_path=None, scan_tuple=None):
        """
        Init with scan_path, scan_name, or (code, datetime) scan_tuple.
        """
        if scan_tuple:
            radar_code, scan_datetime = scan_tuple
            radar_id = config.RADAR_ID.get(radar_code, '')
            radar_id = radar_id if scan_datetime.year >= 2013 else ''

            self._datetime = scan_datetime
            self._code = radar_code
            self._id = radar_id

            return

        if scan_name:
            radar_dict = self._radar_dict_from_scan_name(scan_name)
        else:
            radar_dict = self._radar_dict_from_scan_path(scan_path)
        fmt = self._get_datetime_format(radar_dict)

        self._datetime = Datetime.strptime(radar_dict['timestamp'], fmt)
        self._code = radar_dict['code']
        self._id = radar_dict['id']

    def _radar_dict_from_scan_name(self, scan_name):
        """
        Return dict with radar parameters from ftp scansource.

        Use this when judging files in ftp listing.
        """
        for pattern in PATTERNS:
            match = pattern.match(scan_name)
            if match:
                # handle id
                if 'id' in pattern.groupindex:
                    radar_id = match.group('id')  # dwd from 2013
                else:
                    radar_id = ''

                # handle code and timestamp
                if 'code' in pattern.groupindex:
                    radar_code = match.group('code')
                    radar_timestamp = match.group('timestamp')
                else:
                    radar_code = 'JAB'
                    name_timestamp = match.group('timestamp')
                    d1 = utils.timestamp2datetime(name_timestamp)
                    m = 5 * (d1.minute // 5)
                    d2 = d1.replace(minute=m, second=0, microsecond=0)
                    t = Timedelta(minutes=5)
                    d3 = d1 + min((d2 - d1), abs(d2 - d1 + t), key=abs) - t
                    radar_timestamp = utils.datetime2timestamp(d3)[:-2]

                return {'id': radar_id,
                        'code': radar_code,
                        'timestamp': radar_timestamp}

        message = 'No pattern matches {}'
        raise ValueError(message.format(scan_name))

    def _radar_dict_from_scan_path(self, scan_path):
        """ Use this when judging files on disk, such as when organizing. """
        scan_name = os.path.basename(scan_path)
        radar_dict = self._radar_dict_from_scan_name(scan_name)

        # get exact product time from h5
        if radar_dict['code'] == 'JAB':
            try:
                with h5py.File(scan_path, 'r') as h5:
                    attrs = h5['what'].attrs
                    date = attrs['date']
                    time = attrs['time'][:-2]  # truncate seconds
            except IOError:
                msg = 'Error reading %s'
                raise ValueError(msg % scan_path)
            radar_dict['radar_timestamp'] = date + time

        return radar_dict

    def _get_datetime_format(self, radar_dict):
        """
        Return the filename format with the datetime format string
        that corresponds to current scan.
        """
        radar_code = radar_dict['code']

        if radar_code in config.KNMI_RADARS:
            return config.TEMPLATE_TIME_KNMI
        if radar_code in config.DWD_RADARS:
            return config.TEMPLATE_TIME_DWD
        if radar_code in config.JABBEKE_RADARS:
            return config.TEMPLATE_TIME_JABBEKE
        raise ValueError("There is no format for {}".format(radar_dict))

    def _get_datetime_name(self, radar_dict):
        radar_code = radar_dict['code']
        radar_id = radar_dict['id']

        if radar_code in config.KNMI_RADARS:
            return config.TEMPLATE_KNMI.format(**radar_dict)
        if radar_code in config.DWD_RADARS:
            if radar_id:
                return config.TEMPLATE_DWD.format(**radar_dict)
            return config.TEMPLATE_DWD_ARCHIVE.format(**radar_dict)
        if radar_code in config.JABBEKE_RADARS:
            return config.TEMPLATE_JABBEKE.format(**radar_dict)
        raise ValueError("There is no format for {}".format(radar_dict))

    def get_scanname(self):
        radar_dict = {'code': self._code, 'id': self._id}
        fmt = self._get_datetime_name(radar_dict)
        return self._datetime.strftime(fmt)

    def get_scanpath(self):
        return os.path.join(
            config.RADAR_DIR,
            self._code,
            self._datetime.strftime('%Y'),
            self._datetime.strftime('%m'),
            self._datetime.strftime('%d'),
            self.get_scanname(),
        )

    def get_datetime(self):
        return self._datetime

    def get_timestamp(self):
        return self._datetime.strftime(config.TIMESTAMP_FORMAT)

    def get_code(self):
        if self._code == 'ase':
            return 'ess'
        return self._code

    def get_scan(self, grid):
        if not os.path.exists(self.get_scanpath()):
            logging.warn(
                '{} not found.'.format(os.path.basename(self.get_scanpath())),
            )
            return None
        elif self._code in config.DWD_RADARS:
            return ScanDWD(self, grid)
        elif self._code in config.KNMI_RADARS:
            return ScanKNMI(self, grid)
        elif self._code in config.JABBEKE_RADARS:
            return ScanJabbeke(self, grid)
        logging.error(
            "Currently no scan class matching '{}'".format(self._code),
        )
        return None

    def __repr__(self):
        return '<ScanSignature: {} [{}]>'.format(self._code, self._datetime)

    def __hash__(self):
        """ Bitwise or is a good method for combining hashes. """
        return hash(self._datetime) ^ hash(self._code)


class GenericScan(object):
    """
    Procedures for manipulating scan data.
    """
    def __init__(self, scansignature, grid):
        self.signature = scansignature
        self.grid = grid

    def data(self):
        """
        Dummy placeholder, needs to be implemented in a specific scan object.
        """

        raise NotImplementedError

    def _interpolate(self, points, values, grid):
        """
        Return numpy masked array.
        """
        # Interpolate
        data_out = interpolate.griddata(
            np.array([point.flatten() for point in points]).transpose(),
            np.array([value.flatten() for value in values]).transpose(),
            grid,
            method='linear',
            fill_value=config.NODATAVALUE,
        ).transpose(2, 0, 1)

        # Create masked array
        ma_out = np.ma.array(
            data_out,
            mask=np.equal(data_out, config.NODATAVALUE),
            fill_value=config.NODATAVALUE,
        )

        return ma_out

    def is_readable(self):
        """ Return True if readable, else return False. """
        try:
            self.data()
            logging.debug('Read test for {}.'.format(
                self.signature.get_scanname(),
            ))
            return True
        except Exception:
            logging.exception('{} read failure:'.format(
                self.signature.get_scanname(),
            ))
            return False

    def get(self):
        """ Return gdal dataset in rd projection. """
        data = self.data()
        rang, azim, elev = data['polar']
        rain = data['rain']
        latlon = data['latlon']
        anth = data['ant_alt']

        theta = calc.calculate_theta(
            rang=rang,
            elev=np.radians(elev),
            anth=anth / 1000,
        )

        points_aeqd = calc.calculate_cartesian(
            theta=theta,
            azim=np.radians(azim),
        )

        projections = (
            utils.projection_aeqd(*latlon),
            utils.projection(utils.RD),
        )

        points_rd = utils.coordinate_transformer.transform(
            points=points_aeqd,
            projections=projections,
        )

        # Interpolate
        grid_rain, grid_rang, grid_elev = self._interpolate(
            points=points_rd,
            values=(
                rain,
                rang * np.ones(rain.shape),
                elev * np.ones(rain.shape),
            ),
            grid=self.grid.get_grid(),
        )

        location = utils.transform((0, 0), projections)

        ds_rd = self.grid.create_dataset(bands=3)
        ds_rd.SetMetadata(dict(
            source=self.signature.get_scanname(),
            timestamp=self.signature.get_timestamp(),
            station=self.signature.get_code(),
            location=json.dumps(location),
            antenna_height=json.dumps(anth),
            max_elevation=json.dumps(elev.max()),
            min_elevation=json.dumps(elev.min()),
            max_range=json.dumps(rang.max()),
        ))

        banddata = {
            BAND_RAIN: grid_rain,
            BAND_RANG: grid_rang,
            BAND_ELEV: grid_elev,
        }

        for i in range(1, ds_rd.RasterCount + 1):
            band = ds_rd.GetRasterBand(i)
            band.SetNoDataValue(banddata[i].fill_value)
            band.WriteArray(banddata[i].filled())
            band.SetMetadata(BAND_META[i])

        return ds_rd


class ScanKNMI(GenericScan):

    def data(self):
        """ Return data dict for further processing. """
        scanpath = self.signature.get_scanpath()
        code = self.signature.get_code()
        with h5py.File(scanpath, 'r') as dataset:
            scan_key = 'scan{}'.format(config.KNMI_SCAN_NUMBER[code])

            latlon = self._latlon(dataset)
            rain = self._rain(dataset[scan_key])
            polar = self._polar(dataset[scan_key])
            ant_alt = config.ANTENNA_HEIGHT[code]

        return dict(
            latlon=latlon,
            rain=rain,
            polar=polar,
            ant_alt=ant_alt,
        )

    def _latlon(self, dataset):
        """ Return (lat, lon) in WGS84. """
        lon, lat = dataset['radar1'].attrs['radar_location']
        return float(lat), float(lon)

    def _rain(self, dataset):
        """ Convert and return rain values. """
        type_key = 'scan_{}_data'.format(config.KNMI_SCAN_TYPE)
        PV = np.float64(dataset[type_key])

        # Get calibration from attribute
        calibration_formula = (
            dataset['calibration'].attrs['calibration_Z_formulas']
        )

        # new format since 2016-09-19 does not have the array
        if isinstance(calibration_formula, np.ndarray):
            calibration_formula = calibration_formula.item()

        calibration_formula_match = re.match(
            config.CALIBRATION_PATTERN, calibration_formula
        )
        a = float(calibration_formula_match.group('a'))
        b = float(calibration_formula_match.group('b'))
        logging.debug('From "{}": a={}, b={} in dBZ = a * PV + b'.format(
            calibration_formula, a, b,
        ))

        dBZ = a * PV + b
        return calc.Rain(dBZ).get()

    def _polar(self, dataset):
        """ Return (rang, azim, elev). """

        range_size = dataset.attrs['scan_number_range']
        range_bin = dataset.attrs['scan_range_bin']
        rang = np.arange(
            0.5 * range_bin,
            (range_size + 0.5) * range_bin,
            range_bin,
        ).reshape(1, -1)

        azim_step = dataset.attrs['scan_azim_bin']
        azim = np.arange(
            azim_step / 2,
            360 + azim_step / 2,
            azim_step,
        ).reshape(-1, 1)

        elev = dataset.attrs['scan_elevation'] * np.ones(azim.shape)
        return rang, azim, elev


class ScanDWD(GenericScan):

    def data(self, path=None):
        """ Return data dict for further processing. """
        scanpath = self.signature.get_scanpath()
        dBZ, meta = io.readDX(scanpath)

        return dict(
            latlon=self._latlon(),
            rain=self._rain(dBZ),
            polar=self._polar(meta),
            ant_alt=config.ANTENNA_HEIGHT[self.signature.get_code()]
        )

    def _polar(self, meta):
        rang = np.arange(meta['clutter'].shape[1]).reshape(1, -1) + 0.5
        azim = meta['azim'].reshape(-1, 1) + 180 / meta['azim'].size
        elev = meta['elev'].reshape(-1, 1)
        return rang, azim, elev

    def _rain(self, dBZ):
        """ wradlib did conversion to dBZ. """
        return calc.Rain(dBZ).get()

    def _latlon(self):
        latlon = config.DWD_COORDINATES[self.signature.get_code()]
        return latlon


class ScanJabbeke(GenericScan):

    def data(self, path=None):
        scanpath = self.signature.get_scanpath()
        with h5py.File(scanpath, 'r') as h5file:
            dataset = self._get_dataset_with_minimal_elevation(h5file)
            d = dict(
                latlon=self._latlon(h5file),
                rain=self._rain(dataset),
                polar=self._polar(dataset),
                ant_alt=self._ant_alt(h5file)
            )

        return d

    def _get_dataset_with_minimal_elevation(self, h5file):
        # a generator with (angle, dataset_name) per dataset
        datasets = ((h5file[dataset_name]['where'].attrs['elangle'],
                     dataset_name) for dataset_name in h5file
                    if 'dataset' in dataset_name)
        # Get the dataset that corresponds with the minimal elevation angle.
        dataset_name = min(datasets)[1]
        return h5file[dataset_name]

    def _rain(self, dataset):
        """Calculate rain in mm/hour from the dBZ."""
        data1 = dataset['data1']
        PV = data1['data'].value  # Pixel value
        # Set nodata pixels to a low value
        PV[PV == dataset['data1/what'].attrs['nodata']] = 0
        gain = data1['what'].attrs['gain']
        offset = data1['what'].attrs['offset']
        return calc.Rain(PV * gain + offset).get()

    def _polar(self, dataset):
        where = dataset['where'].attrs

        bins = where['nbins']
        if bins == 598:
            rang = np.arange(0.25, 299, 0.5)
        elif bins == 300:
            rang = np.arange(0.5, 300, 1)
        rang = rang.reshape(1, -1)

        # get the middle of each measured angle.
        try:
            # older files
            how = dataset['how'].attrs
            arr = map(lambda x: x.split(':'), how['azangles'].split(','))
        except KeyError:
            # recent files
            arr = None
        if arr is not None:
            startazA, stopazA = np.array(arr, dtype=float).transpose()
            azim = (startazA + stopazA) / 2
            azim = azim.reshape(-1, 1)
        else:
            azim = np.arange(0.5, 360.5)[:, np.newaxis]

        elev = where['elangle']

        return rang, azim, elev

    def _latlon(self, dataset):
        """Return the latlon coordinates of the radar station."""
        where = dataset['where']
        return where.attrs['lat'], where.attrs['lon']

    def _ant_alt(self, dataset):
        """Return the antenea altitude of the radar station."""
        return dataset['where'].attrs['height']


class MultiScan(object):
    """ Container for aligned rectangular precipitation data. """

    def __init__(self, multiscandatetime, scancodes, grid, basedir):
        self.multiscandatetime = multiscandatetime
        self.scancodes = scancodes
        self.grid = grid

        self.path = self.pathhelper = utils.PathHelper(
            basedir=basedir,
            code=config.MULTISCAN_CODE,
            template='{code}_{timestamp}.h5'
        ).path(multiscandatetime)

    def _add(self, dataset, scan):
        """
        Add scan to dataset, if it is available
        """
        source = scan.get()
        radar = source.GetMetadata()['station']
        target = dataset.create_group(radar)

        # Add general metadata
        target.attrs['projection'] = source.GetProjection()
        target.attrs['geotransform'] = source.GetGeoTransform()
        for k, v in source.GetMetadata().items():
            target.attrs[k] = v

        # Add bands with their metadata
        for source_band in [source.GetRasterBand(i + 1)
                            for i in range(source.RasterCount)]:
            # Data
            data = source_band.ReadAsArray()
            target_band = target.create_dataset(
                source_band.GetMetadataItem(b'name'),
                data.shape,
                dtype='f4',
                compression='gzip',
                shuffle=True,
            )
            target_band[:] = data

            # Metadata
            target_band.attrs['fill_value'] = source_band.GetNoDataValue()
            for k, v in source_band.GetMetadata().items():
                if k == 'name':
                    continue  # This will be used as the name of the dataset.
                target_band.attrs[k] = v

        logging.debug('{} added to multiscan.'.format(radar))

    def get(self):
        """
        Return a readonly hdf5 dataset for requested scans.

        If the dataset is not available, it is created.
        If it is available, but lacks some scan requested, it is appended.
        """
        utils.makedir(os.path.dirname(self.path))

        try:
            # Improperly closed h5 files cannot be opened.
            dataset = h5py.File(self.path, 'a')
        except IOError:
            dataset = h5py.File(self.path, 'w')

        if len(dataset):
            logging.debug(
                'Multiscan file already has {}.'.format(', '.join(dataset))
            )
        else:
            logging.debug('Starting with empty multiscan file.')

        for scancode in self.scancodes:
            scan_tuple = scancode, self.multiscandatetime
            scan = ScanSignature(scan_tuple=scan_tuple).get_scan(self.grid)
            if scan is None or scancode in dataset:
                continue
            if scan.is_readable():
                self._add(dataset=dataset, scan=scan)
            else:
                # Remove it.
                scanpath = scan.signature.get_scanpath()
                try:
                    shutil.move(scanpath, config.RADAR_DIR)
                    logging.warn('Removed corrupt scanfile {}'.format(
                        os.path.basename(scanpath),
                    ))
                except (OSError, IOError):
                    pass  # No permission.

        dataset.close()
        return h5py.File(self.path, 'r')


class Composite(object):

    def __init__(self, compositedatetime, scancodes, declutter, grid, basedir):

        self.scancodes = scancodes
        self.declutter = declutter
        self.grid = grid

        if None in declutter.values():
            raise ValueError('Declutter may not contain None values.')

        self.multiscan = MultiScan(grid=self.grid,
                                   basedir=basedir,
                                   scancodes=scancodes,
                                   multiscandatetime=compositedatetime)

    def _get_window(self, rain):
        """
        Get 2-dimensional slice of rain grid for declutter extent
        assuming equal cell size
        """
        # rainfall grid transform
        x, a, b, y, c, d = rain.get_geotransform()

        # declutter grid extent and shape
        left, right, upper, lower = BASEGRID.extent
        height, width = BASEGRID.get_shape()

        # get window indices
        window_left = int((left - x) / a)
        window_upper = int((upper - y) / d)
        window_right = window_left + width
        window_lower = window_upper + height
        return window_left, window_right, window_upper, window_lower

    def _calculate(self, datasets):
        """
        Return a composite dataset based on the
        weighted lowest altitudes method.
        """
        if not datasets:
            return np.ma.array(
                np.zeros(self.grid.get_shape()),
                mask=True,
                fill_value=config.NODATAVALUE,
            )

        # Read datasets
        metadata = [dict(ds.attrs) for ds in datasets]

        stations = [m['station'] for m in metadata]

        anth = np.array(
            [json.loads(m['antenna_height']) for m in metadata],
        ).reshape((-1, 1, 1)) / 1000

        rain = np.ma.array(
            [gridtools.h5ds2ma(ds['rain']) for ds in datasets],
            fill_value=config.NODATAVALUE,
        )

        rang = np.ma.array(
            [gridtools.h5ds2ma(ds['range']) for ds in datasets],
            fill_value=config.NODATAVALUE,
        )

        elev = np.ma.array(
            [gridtools.h5ds2ma(ds['elevation']) for ds in datasets],
            fill_value=config.NODATAVALUE,
        )

        # Extend mask around NL stations
        if 'NL61' in stations and 'NL62' in stations:
            for i in map(stations.index, ['NL61', 'NL62']):
                rain.mask[i][np.less(rang[i], 15)] = True

        # Extend mask around JAB
        if 'JAB' in stations and 'NL62' in stations:
            i = stations.index('JAB')
            rain.mask[i][np.less(rang[i], 15)] = True

        # Do history declutter
        if self.declutter['history']:  # None or 0 disables history declutter
            logging.debug('Starting history declutter, threshold {}'.format(
                self.declutter['history']
            ))

            # Initialize clutter array of same dimensions as rain array
            clutter = np.zeros(rain.shape, rain.dtype)
            declutter_mask = h5py.File(
                os.path.join(config.MISC_DIR, config.DECLUTTER_FILEPATH), 'r',
            )
            left, right, upper, lower = self._get_window(self.grid)
            for i, radar in enumerate(stations):
                if radar in declutter_mask:
                    clutter[i, upper:lower, left:right] = declutter_mask[radar]
            declutter_mask.close()

            while True:
                clutter[rain.mask] = 0
                extra = reduce(np.logical_and, [
                    # clutter above threshold for that pixel
                    np.greater(clutter, self.declutter['history']),
                    # at least two unmasked pixels left
                    np.greater((~rain.mask).sum(0), 1),
                    # the maximum clutter must be masked
                    np.equal(clutter, clutter.max(0)),
                ])
                # Extend rain mask with cluttermask.
                count = extra.sum()
                if not count:
                    break
                logging.debug(
                    'Masking {} historically suspicious pixels'.format(count),
                )
                rain.mask[extra] = True

        rang.mask = rain.mask
        elev.mask = rain.mask

        # Calculate heights
        theta = calc.calculate_theta(
            rang=rang, elev=np.radians(elev), anth=anth,
        )

        alt_min = calc.calculate_height(
            theta=theta, elev=np.radians(elev - 0.5), anth=anth,
        )
        alt_max = calc.calculate_height(
            theta=theta, elev=np.radians(elev + 0.5), anth=anth,
        )

        lowest_alt_max = np.ma.where(
            np.equal(alt_min, alt_min.min(0)),
            alt_max,
            np.ma.masked,
        ).min(0)

        bandwidth = alt_max - alt_min

        vertdist1 = (lowest_alt_max - alt_min)
        vertdist1[np.ma.less(vertdist1, 0)] = 0

        vertdist2 = (lowest_alt_max - alt_max)
        vertdist2[np.ma.less(vertdist2, 0)] = 0

        overlap = vertdist1 - vertdist2

        weight = overlap / bandwidth

        composite = (rain * weight).sum(0) / weight.sum(0)
        composite.fill_value = config.NODATAVALUE

        return composite

    def _metadata(self, radars, datasets):
        """ Return metadata dict. """
        requested_stations = json.dumps(self.scancodes)
        timestamp = self.multiscan.multiscandatetime.strftime(
            config.TIMESTAMP_FORMAT,
        )
        metadatas = [dict(ds.attrs) for ds in datasets]
        stations = json.dumps(radars)
        locations = json.dumps([json.loads(metadata['location'])
                                for metadata in metadatas])
        ranges = json.dumps([json.loads(metadata['max_range'])
                             for metadata in metadatas])
        method = 'weighted lowest altitudes'
        declutter_size = str(self.declutter['size'])
        declutter_history = str(self.declutter['history'])

        return dict(
            requested_stations=requested_stations,
            stations=stations,
            locations=locations,
            ranges=ranges,
            method=method,
            timestamp=timestamp,
            declutter_size=declutter_size,
            declutter_history=declutter_history,
        )

    def _dataset(self, ma, md):
        """ Return dataset with composite. """
        dataset = self.grid.create_dataset()
        dataset.SetMetadata(md)
        band = dataset.GetRasterBand(1)
        band.WriteArray(ma.filled())
        band.SetNoDataValue(ma.fill_value)
        return dataset

    def get(self):
        """
        Return a composite dataset based on the
        weighted lowest altitudes method.
        """
        multiscan_dataset = self.multiscan.get()
        if len(multiscan_dataset):
            (
                radars,
                datasets,
            ) = zip(*[(code, dataset)
                    for code, dataset in multiscan_dataset.items()
                    if code in self.scancodes])
        else:
            radars, datasets = [], []

        logging.debug('Calculating composite.')

        if len(datasets) == 0:
            logging.warn(
                'no composite created for {}: None of {} found.'.format(
                    self.multiscan.multiscandatetime,
                    ', '.join(self.multiscan.scancodes),
                ),
            )
            pass
            # return None

        ma = self._calculate(datasets)
        md = self._metadata(radars=radars, datasets=datasets)

        multiscan_dataset.close()

        if self.declutter['size']:  # None or 0 disables size declutter
            calc.declutter_by_area(array=ma, area=self.declutter['size'])

        dataset = self._dataset(ma=ma, md=md)

        logging.info('Created composite {}: {}'.format(
            self.multiscan.multiscandatetime.strftime('%Y-%m-%d %H:%M:%S'),
            ', '.join(json.loads(dataset.GetMetadataItem(b'stations'))),
        ))

        return dataset


def make_aggregate(aggregate):
    aggregate.make()
    return aggregate


class Aggregate(object):
    """
    The Aggregate contains the sum of a number of radar composites,
    depending on the timeframe.

    It is the aggregate that is calibrated using ground gauges. The
    aggregate uses the composites of 5 minutes earlier, because the
    composite datetime is when the radar starts to scan, and the detected
    rain still has to fall down.
    """
    CODE = {
        Timedelta(minutes=5): '5min',
        Timedelta(hours=1): 'uur',
        Timedelta(days=1): '24uur',
        Timedelta(days=2): '48uur',
    }

    TD = {v: k for k, v in CODE.items()}

    SUB_CODE = {
        '48uur': '24uur',
        '24uur': 'uur',
        'uur': '5min',
    }

    SUB_TIMEFRAME = {'d': 'h',
                     'h': 'f'}

    def __init__(self, datetime, timeframe, radars,
                 declutter, basedir, multiscandir, grid):
        """ Do some argument checking. """
        # Attributes
        self.datetime = datetime
        self.timeframe = timeframe
        self.radars = radars
        self.declutter = declutter
        self.basedir = basedir
        self.multiscandir = multiscandir
        self.grid = grid

        # Derived attributes
        self.timedelta = config.TIMEFRAME_DELTA[timeframe]
        self.code = self.CODE[self.timedelta]
        # Prevent illegal combinations of dt and dd, can be nicer...
        if self.code == '48uur':
            if datetime != datetime.replace(hour=8, minute=0,
                                            second=0, microsecond=0):
                raise ValueError
        if self.code == '24uur':
            if datetime != datetime.replace(hour=8, minute=0,
                                            second=0, microsecond=0):
                raise ValueError
        if self.code == 'uur':
            if datetime != datetime.replace(minute=0,
                                            second=0, microsecond=0):
                raise ValueError
        if self.code == '5min':
            if datetime != datetime.replace(second=0,
                                            microsecond=0,
                                            minute=(datetime.minute // 5) * 5):
                raise ValueError
        self.path = self.get_path()

    def _sub_datetimes(self):
        """
        Return datetime generator of datetimes of the next aggregate
        resulution.

        Note that it ends at this aggregate's datetime.
        """
        step = self.TD[self.SUB_CODE[self.code]]
        end = self.datetime
        start = self.datetime - self.timedelta + step

        current = start
        while current <= end:
            yield current
            current += step

    def get_path(self):
        """ Return the file path where this aggregate should be stored. """
        path_helper = utils.PathHelper(basedir=self.basedir,
                                       code=self.code,
                                       template='{code}_{timestamp}.h5')
        return path_helper.path(self.datetime)

    def _check(self, h5):
        """ Return if h5 is consistent with requested parameters. """
        if set(h5.attrs['radars']) != set(self.radars):
            # Aggregate was made for a different set of radars
            raise ValueError('Unmatched radarset in existing aggregate')
        if h5.attrs['declutter_history'] != self.declutter['history']:
            raise ValueError('Other history declutter setting in aggregate')
        if h5.attrs['declutter_size'] != self.declutter['size']:
            raise ValueError('Other size declutter setting in aggregate')
        is_recent = (Datetime.utcnow() - self.datetime).days < 7
        if not is_recent:
            logging.info('Skipping completeness check for old aggregate')
        if is_recent and not h5.attrs['available'].all():
            if self.code != '5min':
                raise ValueError('Missing radars in existing aggregate')
            # Check if it is useful to create a new composite
            dt_composite = self.datetime - self.TD[self.code]
            files_available = []
            for radar in sorted(self.radars):
                scan_tuple = radar, dt_composite
                scan_path = ScanSignature(scan_tuple=scan_tuple).get_scanpath()
                files_available.append(os.path.exists(scan_path))
            if not (h5.attrs['available'] == files_available).all():
                raise ValueError('Missing radars, but scanfiles exist.')
            else:
                logging.debug('Missing radars caused by missing scanfiles.')
        return

    def _create(self):
        """
        Create a new dataset from the composite.
        """
        # Create the composite
        dt_composite = self.datetime - self.TD[self.code]

        composite = Composite(compositedatetime=dt_composite,
                              scancodes=self.radars,
                              declutter=self.declutter,
                              grid=self.grid,
                              basedir=self.multiscandir).get()

        # Composite unit is mm/hr and covers 5 minutes. It must be in mm.
        fill_value = config.NODATAVALUE
        array = composite.GetRasterBand(1).ReadAsArray()
        mask = np.equal(array, fill_value)
        masked_array = np.ma.array(
            array, mask=mask, fill_value=fill_value,
        ) / 12

        composite_meta = composite.GetMetadata()

        # Create the data for the h5
        radars = sorted(
            [str(radar)
             for radar in json.loads(composite_meta['requested_stations'])],
        )
        radar_list = zip(json.loads(composite_meta['stations']),
                         json.loads(composite_meta['ranges']),
                         json.loads(composite_meta['locations']))
        locations_dict = {rad: loc for rad, rng, loc in radar_list}
        ranges_dict = {rad: rng for rad, rng, loc in radar_list}

        available = np.array([radar in ranges_dict for radar in radars])
        ranges = [ranges_dict.get(radar, fill_value) for radar in radars]
        locations = np.array([locations_dict.get(radar, 2 * [fill_value])
                              for radar in radars])

        h5_meta = dict(
            grid_projection=self.grid.projection,
            grid_extent=self.grid.extent,
            grid_size=self.grid.size,
            radars=radars,
            ranges=ranges,
            locations=locations,
            available=available,
            method=composite_meta['method'],
            declutter_history=float(composite_meta['declutter_history']),
            declutter_size=float(composite_meta['declutter_size']),
            timestamp_first_composite=composite_meta['timestamp'],
            timestamp_last_composite=composite_meta['timestamp'],
            composite_count=1,
            fill_value=fill_value,
        )

        h5_data = dict(
            precipitation=masked_array,
        )

        path = self.get_path()
        utils.save_dataset(h5_data, h5_meta, path)
        logging.info('Created aggregate {} ({})'.format(
            self.datetime, self.code
        ))

    def _merge(self, aggregates):
        """
        Return h5_dataset by merging iterable of aggregate objects.
        """
        iterable = iter(map(make_aggregate, aggregates))

        aggregate = iterable.next()
        h5 = aggregate.get()

        meta = dict(h5.attrs)
        available = [meta['available']]

        array = h5['precipitation']
        fill_value = config.NODATAVALUE
        mask = np.equal(array, fill_value)
        masked_array = np.ma.array(array, mask=mask, fill_value=fill_value)

        h5.close()

        for aggregate in iterable:

            h5 = aggregate.get()

            array = h5['precipitation']
            fill_value = config.NODATAVALUE
            mask = np.equal(array, fill_value)
            masked_array = np.ma.array([
                masked_array,
                np.ma.array(array, mask=mask)
            ]).sum(0)

            for i in range(len(meta['radars'])):
                if meta['ranges'][i] == config.NODATAVALUE:
                    meta['ranges'][i] = h5.attrs['ranges'][i]
                if (meta['locations'][i] == 2 * [config.NODATAVALUE]).all():
                    meta['locations'][i] = h5.attrs['locations'][i]

            available.append(meta['available'])

            meta['composite_count'] += h5.attrs.get(
                'composite_count',
            )
            meta['timestamp_last_composite'] = h5.attrs.get(
                'timestamp_last_composite',
            )

            h5.close()

        meta['available'] = np.vstack(available)
        data = dict(precipitation=masked_array)
        path = self.get_path()

        utils.save_dataset(data, meta, path)
        logging.info('Created aggregate {} ({})'.format(
            self.datetime, self.code
        ))

    def make(self):
        """ Creates the hdf5 file corresponding to this objects. """
        logging.debug('Creating aggregate {} ({})'.format(
            self.datetime, self.code,
        ))
        path = self.get_path()

        # If there is already a good one, return it
        if os.path.exists(path):
            logging.debug('Checking if existing aggregate can be reused.')
            try:
                with h5py.File(path, 'r') as h5:
                    self._check(h5)
                logging.debug('Check ok.')
                logging.info('Reuse aggregate {} ({})'.format(
                    self.datetime, self.code
                ))
                return
            except KeyError as error:
                logging.debug('Check failed: {}.'.format(error))
            except ValueError as error:
                logging.debug('Check failed: {}.'.format(error))

        # So, now we really need to create an aggregate.
        sub_code = self.SUB_CODE.get(self.code)

        if sub_code is None:
            return self._create()

        # If there is a sub_code, return corresponding aggregates merged.
        sub_aggrs = (Aggregate(datetime=datetime,
                               radars=self.radars,
                               declutter=self.declutter,
                               timeframe=self.SUB_TIMEFRAME[self.timeframe],
                               basedir=self.basedir,
                               multiscandir=self.multiscandir,
                               grid=self.grid)
                     for datetime in self._sub_datetimes())

        return self._merge(aggregates=sub_aggrs)

    def get(self):
        """ Return opened h5 dataset in read mode. """
        path = self.get_path()
        try:
            return h5py.File(path, 'r')
        except IOError:
            logging.warn(
                'Creating aggregate {} ({}) because it did not exist'.format(
                    self.datetime, self.code,
                ),
            )
            self.make()
        return h5py.File(path, 'r')
