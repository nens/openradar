# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

import datetime
import os
import re

# Directories
BUILDOUT_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    '..',
)

# Likely to be overwritten
AGGREGATE_DIR = os.path.join(BUILDOUT_DIR, 'var', 'aggregate')
CALIBRATE_DIR = os.path.join(BUILDOUT_DIR, 'var', 'calibrate')
CONSISTENT_DIR = os.path.join(BUILDOUT_DIR, 'var', 'consistent')
IMG_DIR = os.path.join(BUILDOUT_DIR, 'var', 'img')
MISC_DIR = os.path.join(BUILDOUT_DIR, 'var', 'misc')
MULTISCAN_DIR = os.path.join(BUILDOUT_DIR, 'var', 'multiscan')
NOWCAST_AGGREGATE_DIR = os.path.join(BUILDOUT_DIR, 'var', 'nowcast_aggregate')
NOWCAST_CALIBRATE_DIR = os.path.join(BUILDOUT_DIR, 'var', 'nowcast_calibrate')
NOWCAST_MULTISCAN_DIR = os.path.join(BUILDOUT_DIR, 'var', 'nowcast_multiscan')
RADAR_DIR = os.path.join(BUILDOUT_DIR, 'var', 'radar')
REPORT_DIR = os.path.join(BUILDOUT_DIR, 'var', 'report')
SOURCE_DIR = os.path.join(BUILDOUT_DIR, 'var', 'source')

# Unlikely to be overwritten
LOG_DIR = os.path.join(BUILDOUT_DIR, 'var', 'log')

# Default nodatavalue
NODATAVALUE = -9999

# Declutter defaults
DECLUTTER_FILEPATH = 'clutter-20180601-20190531.h5'
DECLUTTER_HISTORY = 0.1
DECLUTTER_SIZE = 4

# Radar codes
DWD_RADARS = (
    'ess',
    'nhb',
    'emd',
    'ase',  # ess seems to be called ase in archived files
    'asb',  # recommended replacement for retired emd since jan 2018
)
KNMI_RADARS = ('NL61', 'NL62')
JABBEKE_RADARS = ('JAB',)
ALL_RADARS = DWD_RADARS + KNMI_RADARS

# New DWD files have an id that corresponds to the radar code
RADAR_ID = {
    'asb': '10103',
    'emd': '10204',
    'ess': '10410',
    'nhb': '10605',
}

CALIBRATION_PATTERN = re.compile(
    'GEO *= *(?P<a>[-.0-9]+) *\* *PV *\+ *(?P<b>[-.0-9]+)',
)

# Timestamp Templates
TEMPLATE_TIME_KNMI = '%Y%m%d%H%M'
TEMPLATE_TIME_DWD = '%y%m%d%H%M'
TEMPLATE_TIME_JABBEKE = '%Y%m%d%H%M'

# Templates that reveal datetime format when code and id are substituted
TEMPLATE_KNMI = 'RAD_{code}_VOL_NA_%Y%m%d%H%M.h5'
TEMPLATE_DWD_ARCHIVE = 'raa00-dx_{code}-%y%m%d%H%M-dwd---bin'
TEMPLATE_DWD = 'raa00-dx_{id}-%y%m%d%H%M-{code}---bin'
TEMPLATE_JABBEKE = '{code}-%Y%m%d%H%M.dBZ.vol.h5'

# Format for all-digit timestamp
TIMESTAMP_FORMAT = '%Y%m%d%H%M%S'

# Gridproperties for resulting composite (left, right, top, bottom)
COMPOSITE_EXTENT = (-110000, 390000, 700000, 210000)
COMPOSITE_CELLSIZE = (1000, 1000)

# Gridproperties for Infoplaza (left, right, top, bottom)
NOWCAST_EXTENT = (-310000, 400000, 800000, 50000)
NOWCAST_CELLSIZE = (1000, 1000)

# DWD coordinates using standard transformation from EPSG:4314 to EPSG:4326
DWD_COORDINATES = dict(
    ase=(51.405659776445475, 6.967144448033989),
    emd=(53.33871596412482, 7.023769628293414),
    ess=(51.405659776445475, 6.967144448033989),
    nhb=(50.1097523464156, 6.548542364687092),
    asb=(53.564011, 6.748292),
)

# Radar altitudes in meters above MSL
ANTENNA_HEIGHT = dict(
    asb=50.00,  # estimate
    ase=185.10,
    emd=58.00,
    ess=185.10,
    nhb=585.15,
    NL61=51.0,
    NL62=50.0,  # estimate
)

# KNMI scan selection
KNMI_SCAN_NUMBER = {'NL61': 7, 'NL62': 7}
KNMI_SCAN_TYPE = 'Z'

# Naming of products and files
MULTISCAN_CODE = 'multiscan'
TIMEFRAME_DELTA = {
    'f': datetime.timedelta(minutes=5),
    'h': datetime.timedelta(hours=1),
    'd': datetime.timedelta(days=1),
}
FRAMESTAMP = dict(f='0005', h='0100', d='2400')
PRODUCT_CODE = {t: {p: 'TF{}_{}'.format(FRAMESTAMP[t], p.upper())
                    for p in 'rnau'}
                for t in 'fhd'}
PRODUCT_TEMPLATE = 'RAD_{code}_{timestamp}.h5'
NOWCAST_PRODUCT_CODE = 'TF0005_X'

# Delivery times for various products (not a dict, because order matters)
DELIVERY_TIMES = (
    ('x', datetime.timedelta()),
    ('r', datetime.timedelta()),
    ('n', datetime.timedelta(hours=1)),
    ('a', datetime.timedelta(hours=12)),
    ('u', datetime.timedelta(days=30)),
)

# Delays for waiting-for-files
WAIT_SLEEP_TIME = 10  # Seconds
WAIT_EXPIRE_DELTA = datetime.timedelta(minutes=3)

# Productcopy settings, for fews import, for example.
COPY_TARGET_DIRS = []

# Root path to opendap data, for retrieval only.
OPENDAP_ROOT = 'http://opendap.nationaleregenradar.nl/thredds/dodsC/radar'

# FTP settings
# Publishing
FTP_AGE = 7   # max age in days for files on ftp
FTP_HOST = ''  # Empty to skip ftp publishing
FTP_USER = 'MyUser'
FTP_PASSWORD = 'MyPassword'
# Old style FTP imports
FTP_RADARS = {}
# New style mixed source imports
REMOTE_RADARS = []
# Throughputs of radar related data to client ftp.
FTP_THROUGH = {}

# redis host for mtime cache and turn locking system
REDIS_HOST = 'localhost'
REDIS_DB = 0

CELERY_BROKER_URL = 'redis://localhost'  # until rmq better understood

# Import local settings
try:
    from openradar.localconfig import *  # NOQA
except ImportError:
    pass
