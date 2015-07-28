# -*- coding: utf-8 -*-
""" TODO Docstring. """

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

import argparse
import datetime
import hashlib
import logging
import multiprocessing
import os

from scipy import ndimage
import h5py
import numpy as np

from openradar import osr
from openradar import ogr
from openradar import gdal


from openradar import calc
from openradar import config
from openradar import datasets
from openradar import periods
from openradar import scans
from openradar import utils

logger = logging.getLogger(__name__)

FIVE = datetime.timedelta(minutes=5)
SR = osr.SpatialReference(osr.GetUserInputAsWKT(b'epsg:28992'))
GEO_TRANSFORM = -110000, 500, 0, 700000, 0, -500
HEIGHT = 1024
WIDTH = 1024

# start of multiprocessing code
data_source = None
layer = None


def initializer(*initargs):
    """ Set the data source for the current operation. """
    global data_source
    global layer
    data_source = ogr.Open(initargs[0])
    layer = data_source[0]


def get_wedges(index):
    """ Return the wedges and proportionality factors for a grid cell. """
    polygon = get_polygon(get_points(index))
    polygon.AssignSpatialReference(SR)
    layer.SetSpatialFilter(polygon)
    areas = []
    wedges = []
    for feature in layer:
        geometry = feature.geometry()
        wedges.append(feature[b'index'])
        areas.append(geometry.Intersection(polygon).GetArea())
    if areas:
        area = sum(areas)
        factors = ([a / area for a in areas])
        return {'wedges': wedges,
                'factors': factors}
# end of multiprocessing code


def get_points(index):
    """ Return corners of a grid pixel at index. """
    p, a, b, q, c, d = GEO_TRANSFORM
    i, j = index
    x1, y1 = p + a * j + b * i, q + c * j + d * i
    x2, y2 = x1 + a + b, y1 + c + d
    return (x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)


def get_polygon(points):
    """ Return ogr Geometry instance. """
    ring = ogr.Geometry(ogr.wkbLinearRing)
    added = None
    for point in points:
        if point == added:
            continue  # prevent duplicate points
        ring.AddPoint_2D(*point)
        added = point
    polygon = ogr.Geometry(ogr.wkbPolygon)
    polygon.AddGeometry(ring)
    return polygon


class Interpolator(object):
    """
    Convert scan into grids.
    """
    @classmethod
    def create(cls, scancode, datetime):
        """ Return an interpolator object if the scan exists. """
        scan = scans.ScanSignature(scancode=scancode,
                                   scandatetime=datetime).get_scan()
        if scan is not None:
            return cls(scan)

    def __init__(self, scan):
        self.scan = scan

    def get_data(self):
        for data in self.scan.get_data():
            if isinstance(self.scan, scans.ScanDWD):
                rang, azim, elev = data['polar']
                data['polar'] = rang, azim, np.array(1.0)  # fixing DWD elev
            data['ant_alt'] = data['ant_alt'] / 1000
            yield data

    def get_md5(self, data):
        md5 = hashlib.md5()
        for array in data['polar']:
            md5.update(array.tostring())
        md5.update(str(data['latlon']))
        md5.update(str(data['ant_alt']))
        return md5.hexdigest()

    def get_vertices(self, data):
        """ Convert to cartesian polygons. """
        rang, azim, elev = data['polar']
        latlon = data['latlon']
        anth = data['ant_alt']

        rangstep = (rang.max() - rang.min()) / (2 * rang.shape[1] - 2)
        azimstep = (azim.max() - azim.min()) / (2 * azim.shape[0] - 2)

        points = np.empty((azim.shape[0], rang.shape[1], 5, 2))
        directions = (-1, -1), (-1, 1), (1, 1), (1, -1), (-1, -1)
        for i, (r, a) in enumerate(directions):

            theta = calc.calculate_theta(
                rang=rang + r * rangstep,
                elev=np.radians(elev),
                anth=anth,
            )

            points_aeqd = calc.calculate_cartesian(
                theta=theta,
                azim=np.radians(azim + a * azimstep),
            )

            projections = utils.projection_aeqd(*latlon), SR.ExportToWkt()

            points[:, :, i] = utils.coordinate_transformer.transform(
                points=points_aeqd,
                projections=projections,
            ).transpose(1, 2, 0)

        return points.reshape(-1, 5, 2)

    def get_factors(self, data):
        """ Create interpolation factors for data. """
        # cache path
        md5 = self.get_md5(data)
        logger.debug(md5)
        h5_path = os.path.join(config.FACTOR_DIR, '{}.h5'.format(md5))
        shp_path = os.path.join(config.FACTOR_DIR, b'{}.shp'.format(md5))

        # try to return from cache
        if os.path.exists(h5_path):
            with h5py.File(h5_path, 'r') as h5:
                return {'cells': h5['cells'][:],
                        'wedges': h5['wedges'][:],
                        'factors': h5['factors'][:],
                        'distinct': h5['distinct'][:]}

        # create the vector datasource
        name = md5
        driver = ogr.GetDriverByName(b'esri shapefile')
        if os.path.exists(shp_path):
            driver.DeleteDataSource(shp_path)
        data_source = driver.CreateDataSource(shp_path)
        layer = data_source.CreateLayer(name, SR)
        field_defn = ogr.FieldDefn(b'index', ogr.OFTInteger)
        layer.CreateField(field_defn)
        layer_defn = layer.GetLayerDefn()

        # add wedges
        vertices = self.get_vertices(data)
        total = len(vertices)
        logger.debug('Generating wedges:')
        for wedge in xrange(total):
            polygon = get_polygon(vertices[wedge].tolist())
            feature = ogr.Feature(layer_defn)
            feature.SetGeometry(polygon)
            feature[b'index'] = wedge
            layer.CreateFeature(feature)
            gdal.TermProgress_nocb((wedge + 1) / total)

        # create index
        sql = b'CREATE SPATIAL INDEX ON {}'
        data_source.ExecuteSQL(sql.format(name))

        # prepare for the factor calculation
        cells = []
        wedges = []
        factors = []
        distinct = []
        total = WIDTH * HEIGHT
        indices = ((i, j) for i in xrange(HEIGHT) for j in xrange(WIDTH))

        # calculate factors
        logger.debug('Calculating factors:')
        initargs = shp_path,
        pool = multiprocessing.Pool(initargs=initargs,
                                    initializer=initializer)
        for count, result in enumerate(pool.imap(get_wedges, indices)):
            if result:
                cells.extend([count] * len(result['factors']))
                wedges.extend(result['wedges'])
                factors.extend(result['factors'])
                distinct.append(count)
            gdal.TermProgress_nocb((count + 1) / total)
        pool.close()

        # save cache
        kwargs = {'compression': 'lzf'}
        with h5py.File(h5_path) as h5:
            h5.create_dataset(name='cells', data=cells, **kwargs)
            h5.create_dataset(name='wedges', data=wedges, **kwargs)
            h5.create_dataset(name='factors', data=factors, **kwargs)
            h5.create_dataset(name='distinct', data=distinct, **kwargs)

        return {'cells': cells,
                'wedges': wedges,
                'factors': factors,
                'distinct': distinct}

    def get_grid(self, data):
        """ Get interpolated grids. """
        rain = data.pop('rain')
        factor_dict = self.get_factors(data)

        cells = factor_dict['cells']
        wedges = factor_dict['wedges']
        factors = factor_dict['factors']
        distinct = factor_dict['distinct']

        rang, azim, elev = data['polar']
        rang = rang * np.ones(rain.shape)
        elev = elev * np.ones(rain.shape)

        rain_grid = -9999 * np.ones((HEIGHT, WIDTH))
        rang_grid = rain_grid.copy()
        elev_grid = rain_grid.copy()

        rain_grid.ravel()[distinct] = ndimage.sum(
            rain.ravel()[wedges] * factors, cells, distinct,
        )
        rang_grid.ravel()[distinct] = ndimage.sum(
            rang.ravel()[wedges] * factors, cells, distinct,
        )
        elev_grid.ravel()[distinct] = ndimage.sum(
            elev.ravel()[wedges] * factors, cells, distinct,
        )

        return {'rain': rain_grid,
                'elev': elev_grid,
                'rang': rang_grid,
                'scan': data['scan_id'],
                'anth': data['ant_alt']}

    def get_grids(self):
        for data in self.get_data():
            grid = self.get_grid(data)
            yield grid

    @property
    def name(self):
        return self.scan.signature.get_scanname()


def get_interpolators(datetime):
    """ Return all available interpolators. """
    scandatetime = datetime - FIVE
    interpolators = []
    for scancode in config.ALL_RADARS:
        interpolator = Interpolator.create(scancode=scancode,
                                           datetime=scandatetime)
        if interpolator is not None:
            interpolators.append(interpolator)
    return interpolators


def create_composite(datetime):
    """ Create the composite array. """
    interpolators = get_interpolators(datetime)
    grids = [grid
             for interpolator in interpolators
             for grid in interpolator.get_grids()]

    scan = [d['scan'] for d in grids]
    # make numpy arrays
    anth = np.ma.array([d['anth'] for d in grids]).reshape(-1, 1, 1)
    rain = np.ma.masked_values([d['rain'] for d in grids], -9999)
    rang = np.ma.masked_values([d['rang'] for d in grids], -9999)
    elev = np.ma.masked_values([d['elev'] for d in grids], -9999)

    # Calculate heights
    theta = calc.calculate_theta(
        rang=rang, elev=np.radians(elev), anth=anth,
    )

    logger.debug('calculate altitudes')

    alt_min = calc.calculate_height(
        theta=theta, elev=np.radians(elev - 0.5), anth=anth,
    )
    alt_max = calc.calculate_height(
        theta=theta, elev=np.radians(elev + 0.5), anth=anth,
    )

    alt_min, alt_max

    logger.debug('done')

    from matplotlib import colors
    from matplotlib import cm
    from PIL import Image

    for ma, sc in zip(rain, scan):
        image = Image.fromarray(
            cm.jet(colors.LogNorm(0.01, 5)(ma), bytes=True),
        )
        path = os.path.join(config.IMG_DIR, '{}_{}.png'.format(datetime, sc))
        image.save(path)

    # save a png
    composite = None
    ma = np.ma.masked_values(composite[0], -9999)
    image = Image.fromarray(
        cm.jet(colors.LogNorm(0.01, 5)(ma), bytes=True),
    )
    path = os.path.join(config.IMG_DIR, '{}.png'.format(datetime))
    image.save(path)

    # save a geotiff
    driver = gdal.GetDriverByName(b'gtiff')
    kwargs = {'no_data_value': -9999,
              'geo_transform': GEO_TRANSFORM,
              'projection': SR.ExportToWkt()}
    path = os.path.join(config.IMG_DIR, '{}.tif'.format(datetime))
    with datasets.Dataset(composite.filled(-9999), **kwargs) as dataset:
        driver.CreateCopy(path, dataset)

    return composite


def command(text):
    """
    bin/atomic-aggregate 2014-07-28T12:35/2014-07-28T12:35 -v

    need to store:
    - array with indices into source
    - factors with weights into source
    - labels with index to array with indices into target
    - indices into target

    test for readable scans in organize!
    Find sources
    Find target
    Determine if aggregate is meaningful  - depending on existing target
    Create temporary h5 files for each scan of each radar (rain, elev, rang):
        - fast factor lookup for JAB and 2 KNMNI radars * ~ 12 scans
        - conventional interpolation for DWD ~ 3 scans
    Chunkwise determine clutter and create composite according to old method
    Resample to conventional aggregate grid
    """

    period = periods.Period(text)
    for d in period:
        create_composite(d)


def get_parser():
    """ Return argument parser. """
    parser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument(
        'text',
        metavar='PERIOD',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
    )
    return parser


def main():
    """ Call command with args from parser. """
    kwargs = vars(get_parser().parse_args())
    utils.setup_logging(
        verbose=kwargs.pop('verbose'), name=__name__.split('.')[-1],
    )
    try:
        return command(**kwargs)
    except:
        logger.exception('An exception has occurred.')
