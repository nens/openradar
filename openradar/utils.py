# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from functools import reduce

import ciso8601
import codecs
import datetime
import h5py
import logging
import numpy as np
import os

from osgeo import osr
from matplotlib import colors
from matplotlib import cm
from PIL import Image

from openradar import config

# Some projections
UTM = 3405
DHDN = 4314
WGS84 = 4326
GOOGLE = 900913

AEQD_PROJ4 = ('+proj=aeqd +a=6378.137 +b=6356.752 +R_A'
              ' +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0')

# Copied from lizard_map/coordinates.py
RD = ("+proj=sterea +lat_0=52.15616055555555 +lon_0=5.38763888888889 "
      "+k=0.999908 +x_0=155000 +y_0=463000 +ellps=bessel "
      "+towgs84=565.237,50.0087,465.658,-0.406857,0.350733,-1.87035,4.0812 "
      "+units=m +no_defs")


# Projections and transformations
def projection_aeqd(lat=None, lon=None):
    sr = osr.SpatialReference()
    sr.ImportFromProj4(str(AEQD_PROJ4.format(lat=lat, lon=lon)))
    return sr.ExportToWkt()


def projection(desc, export='wkt'):
    sr = osr.SpatialReference()
    if isinstance(desc, int):
        sr.ImportFromEPSG(desc)
    elif isinstance(desc, (str)):
        if desc.startswith('+proj='):
            sr.ImportFromProj4(str(desc))
        else:
            sr.ImportFromWkt(str(desc))
    if export == 'wkt':
        return sr.ExportToWkt()
    if export == 'proj4':
        return sr.ExportToProj4()
    return sr


def transform(point, desc):
    srs = [projection(e, export=None) for e in desc]
    ct = osr.CoordinateTransformation(*srs)
    return ct.TransformPoint(*point)[0:2]


class CoordinateTransformer(object):
    """
    Transform coordinates or give cached coordinates back.

    TODO Make this a simple function, caching is not trivial here.
    """

    def __init__(self):
        self.cache = {}

    def transform(self, points, projections):
        """
        Transform arrays of points from one projection to another.
        """
        shape = np.array([p.shape for p in points]).max(0)

        points_in = np.array([
            points[0].flatten(),
            points[1].flatten(),
        ]).transpose()

        ct = osr.CoordinateTransformation(
            projection(projections[0], export=None),
            projection(projections[1], export=None),
        )

        points_out = np.array(ct.TransformPoints(points_in))[:, 0:2]

        result = points_out.reshape(shape[0], shape[1], 2).transpose(2, 0, 1)
        return result


# Singleton
coordinate_transformer = CoordinateTransformer()


# Dateranges and date helpers
def datetime_range(start, stop, step):
    """ Return generator of datetimes. """
    datetime = start
    while datetime <= stop:
        yield datetime
        datetime += step


def variabletimestamp2datetime(ts, fmt='%Y%m%d%H%M%S'):
    """ Trying to match and increasingly detailed timestamp. """
    return datetime.datetime.strptime(ts, fmt[:len(ts) - 2])


def timestamp2datetime(ts, fmt='%Y%m%d%H%M%S'):
    return datetime.datetime.strptime(ts, fmt)


def datetime2timestamp(dt, fmt='%Y%m%d%H%M%S'):
    return dt.strftime(fmt)


class DateRange(object):

    STEP = datetime.timedelta(minutes=5)

    def __init__(self, text, step=STEP):
        self.step = step
        self.start, self.stop = self._start_stop_from_text(text)

    def _start_stop_from_text(self, text):
        """
        Return start and end timestamps.
        """
        if '-' in text:
            text1, text2 = text.split('-')
            start = self._single_from_text(text=text1)
            stop = self._single_from_text(text=text2, last=True)
        else:
            start = self._single_from_text(text=text)
            stop = self._single_from_text(text=text)
        return start, stop

    def _single_from_text(self, text, last=False):
        """
        Return datetime that matches text.

        If last, return the last possible step for text.
        """
        first = variabletimestamp2datetime(text)
        if not last:
            return first

        td_kwargs = {
            8: {'days': 1},
            10: {'hours': 1},
            12: {'minutes': 5},  # Makes a range of minutes possible.
        }[len(text)]
        return first - self.step + datetime.timedelta(**td_kwargs)

    def iterdatetimes(self):
        dt = self.start
        while dt <= self.stop:
            yield dt
            dt += self.step


class MultiDateRange(object):
    """ Hold a series of datetime ranges and generate it. """

    def __init__(self, text, step=5):
        step = datetime.timedelta(minutes=step)
        self._dateranges = [DateRange(subtext, step)
                            for subtext in text.strip(',').split(',')]

    def iterdatetimes(self):
        for dr in self._dateranges:
            for dt in dr.iterdatetimes():
                yield dt


# Path helpers and organizers
class PathHelper(object):
    """
        >>> import datetime
        >>> dt = datetime.datetime(2011, 03, 05, 14, 15, 00)
        >>> ph = PathHelper('a', 'c', '{code}:{timestamp}')
        >>> ph. path(dt)
        u'a/c/2011/03/05/c:20110305141500'
    """

    TIMESTAMP_FORMAT = config.TIMESTAMP_FORMAT

    def __init__(self, basedir, code, template):
        """
        Filetemplate must be something like '{code}_{timestamp}.'
        """
        self._basedir = os.path.join(basedir, code)
        self._code = code
        self._template = template

    def path(self, dt):
        return os.path.join(
            self._basedir,
            dt.strftime('%Y'),
            dt.strftime('%m'),
            dt.strftime('%d'),
            self._template.format(
                code=self._code,
                timestamp=dt.strftime(self.TIMESTAMP_FORMAT)
            )
        )

    def path_with_hour(self, dt):
        return os.path.join(
            self._basedir,
            dt.strftime('%Y'),
            dt.strftime('%m'),
            dt.strftime('%d'),
            dt.strftime('%H'),
            self._template.format(
                code=self._code,
                timestamp=dt.strftime(self.TIMESTAMP_FORMAT)
            )
        )


# Timing
def closest_time(timeframe='f', dt_close=None):
    '''
    Get corresponding datetime based on the timeframe.
    e.g. with    dt_close = 2012-04-13 12:27
    timeframe = 'f' returns 2012-04-13 12:25
    timeframe = 'h' returns 2012-04-13 12:00
    timeframe = 'd' returns 2012-04-12 08:00
    '''
    if dt_close is not None:
        now = dt_close
    else:
        now = datetime.datetime.utcnow()
    if timeframe == 'h':
        closesttime = now.replace(minute=0, second=0, microsecond=0)
    elif timeframe == 'd':
        closesttime = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if closesttime > now:
            closesttime = closesttime - datetime.timedelta(days=1)
    else:
        closesttime = now.replace(
            minute=now.minute - (now.minute % 5), second=0, microsecond=0,
        )
    return closesttime


def get_valid_timeframes(datetime):
    """ Return a list of timeframe codes corresponding to a datetime."""
    result = []
    if datetime.second == 0 and datetime.microsecond == 0:
        if datetime.minute == (datetime.minute // 5) * 5:
            result.append('f')
        # if datetime.minute == 0:
            # result.append('h')
            # if datetime.hour == 8:
                # result.append('d')
    return result


def get_aggregate_combinations(datetimes,
                               timeframes=['f', 'h', 'd']):
    """ Return generator of dictionaries. """
    for _datetime in datetimes:
        valid_timeframes = get_valid_timeframes(datetime=_datetime)
        for timeframe in timeframes:
            if timeframe in valid_timeframes:
                # yield dict(nowcast=False,
                           # datetime=_datetime,
                           # timeframe=timeframe)
                if timeframe == 'f':
                    yield dict(nowcast=True,
                               datetime=_datetime,
                               timeframe=timeframe)


def get_product_combinations(datetimes,
                             prodcodes=['r', 'n', 'a', 'u'],
                             timeframes=['f', 'h', 'd']):
    """ Return generator of dictionaries. """
    for _datetime in datetimes:
        valid_timeframes = get_valid_timeframes(datetime=_datetime)
        for prodcode in prodcodes:
            for timeframe in timeframes:
                if timeframe in valid_timeframes:
                    yield dict(nowcast=False,
                               datetime=_datetime,
                               prodcode=prodcode,
                               timeframe=timeframe)
                    if timeframe == 'f' and prodcode == 'r':
                        yield dict(nowcast=True,
                                   datetime=_datetime,
                                   prodcode=prodcode,
                                   timeframe=timeframe)


def consistent_product_expected(prodcode, timeframe):
    """
    Return if a consistent product is expected, for a product. It
    can be used to determine if a product needs to be published, or
    not. If not, the rescaled equivalent should be published.
    """
    if prodcode in 'au' and timeframe in 'fh':
        return True
    if prodcode == 'n' and timeframe == 'f':
        return True
    return False


def get_groundfile_datetimes(prodcode, timeframe, date):
    '''
    Return datetime for groundfile for a given product code and datetime

    For ground data to be more complete, the datetime of the grounddata
    must a certain amount later than the radar datetime.  So for a
    product at 2012-12-18 09:05 the groundfile datetimes must be:
        real-time           => 2012-12-18-09:05
        near-real-time      => 2012-12-18-10:05
        afterwards          => 2012-12-20-09:05

    Unfortunately, for technical reasons, the groundfile dating is
    not consistent over history. Therefore, this function now takes a
    timeframe argument and returns a generator of datetimes to try. The
    first datetime for which a ground file exists, must be used.
    '''
    delta = dict(
        r=datetime.timedelta(minutes=0),
        n=datetime.timedelta(hours=1),
        a=datetime.timedelta(days=2)
    )
    base_datetime = date + delta[prodcode]
    if timeframe == 'f':
        # It used to be on exact 5 minutes, but now it is 1 minute late.
        for minutes in [1, 0]:
            yield base_datetime + datetime.timedelta(minutes=minutes)
    elif timeframe == 'd' and prodcode == 'n':
        # It used to be on 8 o'clock utc, but now it is (correctly) at 9.
        for hours in [0, -1]:
            yield base_datetime + datetime.timedelta(hours=hours)
    else:
        yield base_datetime


# Visualization
def rain_kwargs(max_rain=120, name='buienradar', threshold=0.1):
    """ Return colormap and normalizer suitable for rain. """
    if name == 'buienradar':
        rain_colors = {
            'red': (
                (0, 240, 240),
                (2, 158, 110),
                (5, 88, 0),
                (10, 0, 255),
                (100, 131, 192),
                (max_rain, 192, 192),
            ),
            'green': (
                (0, 240, 240),
                (2, 158, 110),
                (5, 88, 0),
                (10, 0, 0),
                (100, 0, 0),
                (max_rain, 0, 0),
            ),
            'blue': (
                (0, 255, 255),
                (2, 255, 255),
                (5, 255, 200),
                (10, 110, 0),
                (100, 0, 192),
                (max_rain, 192, 192),
            ),
        }

        cdict = {}
        for key, value in rain_colors.items():
            cdict[key] = []
            for element in value:
                cdict[key].append((
                    element[0] / max_rain,
                    element[1] / 255,
                    element[2] / 255,
                ))

        colormap = colors.LinearSegmentedColormap('rain', cdict)
        normalize = colors.Normalize(vmin=0, vmax=max_rain)

        return dict(colormap=colormap, normalize=normalize)

    if name == 'jet':
        colormap = cm.jet

        def normalize(data):
            ma = np.ma.array(data)
            ma[np.less(ma, threshold)] = np.ma.masked
            return colors.LogNorm(vmin=threshold, vmax=max_rain)(ma)

        return dict(colormap=colormap, normalize=normalize)


def merge(images):
    """
    Return a pil image.

    Merge a list of pil images with equal sizes top down based on
    the alpha channel.
    """

    def paste(image1, image2):
        image = image2.copy()
        mask = Image.fromarray(np.array(image1)[:, :, 3])
        rgb = Image.fromarray(np.array(image1)[:, :, 0:3])
        image.paste(rgb, None, mask)
        return image

    return reduce(paste, images)


def makedir(dirname):
    """ Return True if directory was created, else False. """
    try:
        os.makedirs(dirname)
        return True
    except OSError:
        return False


class UTF8Recoder:
    """
    Iterator that reads an encoded stream and reencodes the input to UTF-8
    """
    def __init__(self, f, encoding):
        self.reader = codecs.getreader(encoding)(f)

    def __iter__(self):
        return self

    def next(self):
        return self.reader.next().encode("utf-8")


def save_attrs(h5, attrs):
    for key, value in attrs.items():
        if isinstance(value, dict):
            group = h5.create_group(key)
            save_attrs(h5=group, attrs=value)
            continue
        if hasattr(value, 'encode'):
            value = value.encode('ascii')
        h5.attrs[key] = np.array([value])


def save_dataset(data, meta, path):
    '''
    Accepts an array jampacked with data, a metadata file and a path
    to produce a fresh h5 file.
    '''
    logging.debug('Saving hdf5 dataset: {}'.format(os.path.basename(path)))
    logging.debug(path)
    tmp_path = path + '.in'

    makedir(os.path.dirname(path))
    h5 = h5py.File(tmp_path, 'w')

    # Geographic group
    left, right, top, bottom = meta['grid_extent']
    width, height = meta['grid_size']

    geographic = dict(
        geo_par_pixel=b'X,Y',
        geo_dim_pixel=b'KM,KM',
        geo_pixel_def=b'CENTRE',
        geo_number_columns=width,
        geo_number_rows=height,
        geo_pixel_size_x=1.000,
        geo_pixel_size_y=-1.000,
        geo_product_corners=[left, bottom, left, top,
                             right, top, right, bottom],
        map_projection=dict(
            projection_indication=b'Y',
            projection_name=b'STEREOGRAPHIC',
            projection_proj4_params=projection(RD, export='proj4'),
        ),
    )

    # Overview group
    availables = meta['available']
    try:
        availables_any = [any(r) for r in zip(*availables)]
    except TypeError:
        availables_any = availables
    products_missing = str(', '.join(
        [radar
         for radar, available in zip(meta['radars'], availables_any)
         if not available],
    ))
    timestamp_last_composite = meta['timestamp_last_composite']
    if hasattr(timestamp_last_composite, "decode"):
        timestamp_last_composite = timestamp_last_composite.decode("ascii")
    product_datetime_start = (timestamp2datetime(
        timestamp_last_composite,
    ) + config.TIMEFRAME_DELTA['f']).strftime('%d-%b-%Y;%H:%M:%S.%f').upper()
    product_datetime_end = product_datetime_start

    overview = dict(
        hdftag_version_number=b'3.5',
        number_image_groups=1,
        number_radar_groups=0,
        number_satellite_groups=0,
        number_station_groups=0,
        product_datetime_end=product_datetime_end,
        product_datetime_start=product_datetime_start,
        product_group_name=str(os.path.splitext(os.path.basename(path))[0]),
        products_missing=products_missing,
    )

    # Image group
    calibration = dict(
        calibration_flag=b'Y',
        calibration_formulas=b'GEO = 0.010000 * PV + 0.000000',
        calibration_missing_data=0,
        calibration_out_of_image=65535,
    )

    image1 = dict(
        calibration=calibration,
        image_bytes_per_pixel=2,
        image_geo_parameter=b'PRECIP_[MM]',
        image_product_name=overview['product_group_name'],
        image_size=data['precipitation'].size,
    )

    groups = dict(
        overview=overview,
        geographic=geographic,
        image1=image1,
    )

    save_attrs(h5, groups)
    dataset = h5.create_dataset('image1/image_data',
                                data['precipitation'].shape,
                                dtype='u2', compression='gzip', shuffle=True)

    image_data = dict(
        CLASS=b'IMAGE',
        VERSION=b'1.2',
    )

    save_attrs(dataset, image_data)

    # Creating the pixel values
    dataset[...] = np.uint16(np.round(data['precipitation'] * 100)).filled(
        calibration['calibration_out_of_image'],
    )

    # Keep the old way for compatibility with various products
    for name, value in data.items():
        dataset = h5.create_dataset(name, value.shape, dtype='f4',
                                    compression='gzip', shuffle=True)
        dataset[...] = value.filled(config.NODATAVALUE)

    for name, value in meta.items():
        if hasattr(value, 'encode'):
            value = value.encode('ascii')
        elif isinstance(value, list):
            value = [
                e.encode('ascii')
                if hasattr(e, 'encode')
                else e
                for e in value
            ]
        h5.attrs[name] = value

    h5.close()
    os.rename(tmp_path, path)

    return path


def get_countrymask():
    """
    Get a prefabricated country mask, 1 everywhere in the country and 0
    50 km outside the country. If extent and cellsize are not as in
    config.py, this breaks.
    """
    countrymask_path = os.path.join(config.MISC_DIR, 'countrymask.h5')
    h5 = h5py.File(countrymask_path, 'r')
    mask = h5['mask'][...]
    h5.close()
    return mask


def get_geo_transform():
    left, right, top, bottom = config.COMPOSITE_EXTENT
    width, height = config.COMPOSITE_CELLSIZE
    return left, width, 0, top, 0, -height


def parse_datetime(text):
    """ Return a datetime instance. """
    if len(text) == 4:
        # ciso8601 requires at least months to be specified
        return ciso8601.parse_datetime_unaware(text + '01')
    return ciso8601.parse_datetime_unaware(text)


def convert_to_lists_and_unicode(meta):
    """ Updates dict. Return None. """
    for k, v in meta.items():
        # numpy array
        if hasattr(v, 'size'):
            if v.size == 0:
                meta[k] = []
            elif v.size == 1:
                meta[k] = v.item()
            else:
                meta[k] = [
                    e.decode('ascii')
                    if hasattr(e, 'decode') else e
                    for e in v.tolist()
                ]
        # bytes
        elif hasattr(v, 'decode'):
            meta[k] = v.decode('ascii')
