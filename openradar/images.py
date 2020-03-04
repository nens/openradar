# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from matplotlib import patches

from osgeo import gdal
from osgeo import osr
from PIL import Image

import h5py
import json
import logging
import numpy as np
import os
import pytz
import shlex
import subprocess

from openradar import config
from openradar import utils
from openradar import gridtools
from openradar import scans

PROJECTION_RD_WKT = osr.GetUserInputAsWKT('epsg:28992')


def data_image(masked_array, max_rain=20, threshold=0.0):
    """ """
    basegrid = scans.BASEGRID
    rasterlayerkwargs = utils.rain_kwargs(
        name='jet', max_rain=max_rain, threshold=threshold,
    )
    return gridtools.RasterLayer(
        array=masked_array,
        extent=basegrid.extent,
        projection=basegrid.projection,
        **rasterlayerkwargs).image()


def shape_image():
    """ Return rgba image with shape of country. """
    basegrid = scans.BASEGRID
    shape_layer = basegrid.create_vectorlayer()
    shape_layer.add_line(
        os.path.join(config.MISC_DIR, 'west_europa_lijn.shp'),
        color='0.5',
        linewidth=0.5,
    )
    return shape_layer.image()


def shape_image_filled():
    """ Return rgba image with shape of country. """
    basegrid = scans.BASEGRID
    shape_layer = basegrid.create_vectorlayer()
    shape_layer.add_multipolygon(
        os.path.join(config.MISC_DIR, 'nederland_rd.shp'),
        color='g',
        linewidth=1,
    )
    return shape_layer.image()


def osm_image():
    """ Return rgba image with osm background. """
    ds_osm_rd = gdal.Open(os.path.join(config.MISC_DIR, 'osm-rd.tif'))
    osm_rgba = np.ones(
        (ds_osm_rd.RasterYSize, ds_osm_rd.RasterXSize, 4),
        dtype=np.uint8,
    ) * 255
    osm_rgba[:, :, 0:3] = ds_osm_rd.ReadAsArray().transpose(1, 2, 0)
    return Image.fromarray(osm_rgba)


def mapbox_image():
    """ Return rgba image with mapbox background. """
    ds_mapbox_rd = gdal.Open(os.path.join(config.MISC_DIR, 'mapbox-rd.tif'))
    mapbox_rgba = np.ones(
        (ds_mapbox_rd.RasterYSize, ds_mapbox_rd.RasterXSize, 4),
        dtype=np.uint8,
    ) * 255
    mapbox_rgba[:, :, 0:3] = ds_mapbox_rd.ReadAsArray().transpose(1, 2, 0)
    return Image.fromarray(mapbox_rgba)


def plain_image(color=(255, 255, 255)):
    """ Return opaque rgba image with color color. """
    basegrid = scans.BASEGRID
    rgba = np.ones(
        basegrid.get_shape() + (4,),
        dtype=np.uint8,
    ) * np.uint8(color + (255,))
    return Image.fromarray(rgba)


def radars_image(h5, label='', offset=(0, 0)):
    """
    Return radar image with optional label from open h5. Offset refers
    to the label position.
    """

    # Create vectorlayer get metadata
    label_layer = scans.BASEGRID.create_vectorlayer()
    metadata = h5.attrs
    locations = metadata['locations']
    stations = metadata['radars']
    ranges = metadata['ranges']

    for i in range(len(stations)):

        # Plot stations
        label_layer.axes.add_artist(patches.Circle(
            locations[i], 4000,
            facecolor='r', edgecolor='k', linewidth=2,
        ))

        # Plot range circles
        label_layer.axes.add_artist(patches.Circle(
            locations[i], ranges[i] * 1000,
            facecolor='none', edgecolor='0.5', linestyle='dotted',
        ))

    # Plot timestamp
    if label:
        label_layer.axes.annotate(
            label, offset, xycoords='axes fraction',
            ha='left', va='top', size='x-large', weight='bold',
            color='0.3',
        )

    return label_layer.image()


def create_geotiff(dt_aggregate, code='5min'):

    pathhelper = utils.PathHelper(
        basedir=config.AGGREGATE_DIR,
        code=code,
        template='{code}_{timestamp}.h5'
    )

    rasterlayerkwargs = utils.rain_kwargs(
        name='jet', max_rain=2, threshold=0.008,
    )

    aggregatepath = pathhelper.path(dt_aggregate)

    tifpath_rd = os.path.join(
        config.IMG_DIR, 'geotiff', 'rd',
        dt_aggregate.strftime('%Y-%m-%d-%H-%M.tiff')
    )

    with h5py.File(aggregatepath, 'r') as h5:
        array = h5['precipitation']
        mask = np.equal(array, h5.attrs['fill_value'])
        masked_array = np.ma.array(array, mask=mask)

        # Create the rd tiff.
        utils.makedir(os.path.dirname(tifpath_rd))
        gridtools.RasterLayer(array=masked_array,
                              extent=h5.attrs['grid_extent'],
                              projection=h5.attrs['grid_projection'],
                              **rasterlayerkwargs).save(tifpath_rd, rgba=True)

    logging.info('saved {}.'.format(os.path.basename(tifpath_rd)))
    logging.debug('saved {}.'.format(tifpath_rd))


def create_tif(products, image_dir=None, **kwargs):
    """ Save a tif with metadata """
    if image_dir:
        target_dir = image_dir
    else:
        target_dir = config.IMG_DIR
    utils.makedir(target_dir)

    # Loop products
    for product in products:

        # Get data
        try:
            with h5py.File(product.path, 'r') as h5:
                data = np.ma.masked_equal(h5['precipitation'],
                                          h5.attrs['fill_value'])
                attrs = dict(h5.attrs)
        except IOError:
            logging.info('Not found: {}, skipping.'.format(product))
            continue

        # make a dataset
        raster_layer = gridtools.RasterLayer(
            array=data,
            extent=attrs['grid_extent'],
            projection=attrs['grid_projection'],
        )
        mem = raster_layer.create_dataset(datatype=6)

        mem.SetProjection(PROJECTION_RD_WKT)
        band = mem.GetRasterBand(1)
        band.WriteArray(data.filled(band.GetNoDataValue()))
        for k, v in attrs.items():
            if hasattr(v, 'tolist'):
                v = json.dumps(v.tolist())
            band.SetMetadataItem(str(k), str(v))

        timestamp = utils.datetime2timestamp(product.datetime)
        filename = '{}{}.{}'.format(
            timestamp, kwargs.get('postfix', ''), kwargs.get('format', 'png'),
        )
        path = os.path.join(target_dir, filename)

        driver = gdal.GetDriverByName('gtiff')
        driver.CreateCopy(path, mem)

        logging.info('saved {}.'.format(os.path.basename(path)))
        logging.debug('saved {}.'.format(path))


def create_png(products, **kwargs):
    """
    Create image for products.

    This is a kind of sandbox version.
    """
    utils.makedir(config.IMG_DIR)

    # Load some images
    img_shape = shape_image()
    img_blue = plain_image(color=(0, 0, 127))
    img_shape_filled = shape_image_filled()

    # Get dutch time label
    tz_amsterdam = pytz.timezone('Europe/Amsterdam')
    tz_utc = pytz.timezone('UTC')

    # Loop products
    for product in products:
        utc = tz_utc.localize(product.datetime)
        amsterdam = utc.astimezone(tz_amsterdam)
        label = amsterdam.strftime('%Y-%m-%d %H:%M')
        label_from_kwargs = kwargs.get('label', '')
        if label_from_kwargs:
            label += ' ' + label_from_kwargs
        offset = 0.1, 0.9

        # Get data image
        try:
            with product.get() as h5:
                array = h5['precipitation'][...] / h5.attrs['composite_count']
                mask = np.equal(array, h5.attrs['fill_value'])
                img_radars = radars_image(h5=h5, label=label, offset=offset)
        except IOError:
            logging.debug('Does not exist: {}'.format(product.path))
            continue
        masked_array = np.ma.array(array, mask=mask)
        img_rain = data_image(masked_array, max_rain=2, threshold=0.008)

        timestamp = utils.datetime2timestamp(product.datetime)

        filename = '{}{}.{}'.format(
            timestamp, kwargs.get('postfix', ''), kwargs.get('format', 'png'),
        )
        # Merge and save
        path = os.path.join(config.IMG_DIR, filename)
        utils.merge([
            img_radars,
            img_rain,
            img_shape,
            img_shape_filled,
            img_blue,
        ]).save(path)

        logging.info('saved {}.'.format(os.path.basename(path)))
        logging.debug('saved {}.'.format(path))


def create_png_for_animated_gif(products, **kwargs):
    """
    Create image for products.

    This is the tweaked version that creates the pngs for use in the
    animated gif.
    """
    utils.makedir(config.IMG_DIR)

    # Load some images
    img_mapbox = mapbox_image()
    img_osm = osm_image()
    img_shape = shape_image()
    img_blue = plain_image(color=(0, 0, 127))
    img_shape_filled = shape_image_filled()

    # Get dutch time label
    tz_amsterdam = pytz.timezone('Europe/Amsterdam')
    tz_utc = pytz.timezone('UTC')

    # Loop products
    for product in products:
        utc = tz_utc.localize(product.datetime)
        amsterdam = utc.astimezone(tz_amsterdam)
        #label = amsterdam.strftime('%Y-%m-%d %H:%M')
        label = amsterdam.strftime('%H:%M')
        offset = 0.25, 0.82

        # Get data image
        with product.get() as h5:
            array = h5['precipitation'][...] / h5.attrs['composite_count']
            mask = np.equal(array, h5.attrs['fill_value'])
            img_radars = radars_image(h5=h5, label=label, offset=offset)
        masked_array = np.ma.array(array, mask=mask)
        img_rain = data_image(masked_array, max_rain=2, threshold=0.008)

        timestamp = utils.datetime2timestamp(product.datetime)

        filename = '{}{}.{}'.format(
            timestamp, kwargs.get('postfix', ''), kwargs.get('format', 'png'),
        )
        # Merge and save
        path = os.path.join(config.IMG_DIR, filename)
        utils.merge([
            img_radars,
            img_rain,
            img_mapbox,
            img_shape,
            img_shape_filled,
            img_blue,
        ]).save(path)

        logging.info('saved {}.'.format(os.path.basename(path)))
        logging.debug('saved {}.'.format(path))


def create_animated_gif(datetime):
    """ Produces animated gif file from images in IMG_DIR. """
    template = ('convert -set delay 20 -loop 0 -crop 340x370+80+40 '
                '+repage {} {}')
    step = config.TIMEFRAME_DELTA['f']
    pngpaths = []

    # Add files if they exist
    for i in range(36):
        timestamp = utils.datetime2timestamp(datetime - i * step)
        pngpath = os.path.join(config.IMG_DIR, timestamp + '.png')
        if os.path.exists(pngpath):
            pngpaths = [pngpath] + pngpaths
    logging.debug('Found {} suitable png files.'.format(len(pngpaths)))

    # Create the gif
    gifpath = os.path.join(config.IMG_DIR, 'radar.gif')
    tempgifpath = gifpath.replace('radar.gif', 'radar_temp.gif')
    command = template.format(' '.join(pngpaths), tempgifpath)
    subprocess.call(shlex.split(command))
    os.rename(tempgifpath, gifpath)
    logging.debug(gifpath)
    logging.info('Animation created at {}.'.format(gifpath))
