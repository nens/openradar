#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import config
from openradar import loghelper
from openradar import publishing
from openradar import utils

import datetime
import os


def get_datetimes():
    """ Return generator of datetimes. """
    now = datetime.datetime.utcnow()
    five = datetime.timedelta(minutes=5)
    current = utils.closest_time() - datetime.timedelta(days=7)
    while current < now:
        yield current
        current += five


def sync_radar():
    """
    Synchronize publication FTP with calibrate or consistent dirs.

    Sometimes the publication FTP is not available and this causes
    missing publications although they are available on the server. This
    script fills in the holes.
    """
    loghelper.setup_logging(os.path.join(config.LOG_DIR, 'sync2ftp.log'))
    datetimes = tuple(get_datetimes())
    prodcodes = 'rnau'
    timeframes = 'fhd'

    publisher = publishing.Publisher(datetimes=datetimes,
                                     prodcodes=prodcodes,
                                     timeframes=timeframes,
                                     nowcast=False)
    publisher.publish_ftp(overwrite=False, cascade=True)


def main():
    return sync_radar()
