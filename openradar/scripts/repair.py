# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.
"""
Report on the missing realtime products as indication of missed masters.
"""

from datetime import datetime as Datetime
from datetime import timedelta as Timedelta
import argparse
import logging
import os
import sys

from openradar import config
from openradar import periods
from openradar import utils

logger = logging.getLogger(__name__)

TOLERANCE = Timedelta(minutes=15)


def command(text):
    """ Check existence of realtime files. """
    # prepare
    period = periods.Period(text)
    recently = Datetime.utcnow() - TOLERANCE
    helper = utils.PathHelper(basedir=config.CALIBRATE_DIR,
                              code='TF0005_R',
                              template=config.PRODUCT_TEMPLATE)

    # the check
    for datetime in period:
        if datetime > recently:
            continue
        path = helper.path(datetime)
        if not os.path.exists(path):
            timestamp = utils.datetime2timestamp(datetime)
            logger.debug(f'/srv/openradar/.venv/bin/master -r {timestamp}')


def get_parser():
    """ Return argument parser. """
    parser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument(
        'text',
        metavar='PERIOD',
    )
    return parser


def main():
    """ Call command with args from parser. """
    kwargs = vars(get_parser().parse_args())

    logging.basicConfig(stream=sys.stderr,
                        level=logging.DEBUG,
                        format='%(message)s')

    try:
        return command(**kwargs)
    except Exception:
        logger.exception('An exception has occurred.')
