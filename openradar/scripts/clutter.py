#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

import argparse
import h5py
import logging
import os
import sys

import numpy as np

from openradar import config
from openradar import utils

logger = logging.getLogger(__name__)

RAIN_THRESHOLD = dict(
    nhb=500,
    ess=500,
    ase=500,
    emd=500,
    NL60=1000,
    NL61=2000,
)


def get_parser():
    parser = argparse.ArgumentParser(
        description='Count clutter on rainless days',
    )
    parser.add_argument(
        'range_text',
        metavar='RANGE',
        type=str,
        help='Ranges to use, for example 20110101-20110103,20110105',
    )
    parser.add_argument(
        '-t', '--target-path',
        type=str,
        default=os.path.join(config.IMG_DIR, 'clutter.h5'),
        help='Ouput filename',
    )
    return parser


def get_threshold(code):
    return RAIN_THRESHOLD.get(code, 1000)


def command(target_path, range_text):
    """ Newstyle clutter gathering. """
    logfile = open(
        os.path.join(os.path.dirname(target_path), 'clutter.log'), 'w',
    )
    # collect
    daterange = utils.DateRange(range_text)
    pathhelper = utils.PathHelper(
        basedir=config.MULTISCAN_DIR,
        code=config.MULTISCAN_CODE,
        template='{code}_{timestamp}.h5'
    )
    result = dict()
    count = dict()
    for dt in daterange.iterdatetimes():
        path = pathhelper.path(dt)
        logger.info('Processing {}'.format(path))
        with h5py.File(path, 'r') as h5:
            for k, v in h5.iteritems():
                logger.debug('Radar: {}'.format(k))
                d = v['rain']
                a = d[:]
                r = np.where(a == -9999, 0, a)
                s = r.sum()
                logfile.write('{}, {}, {}\n'.format(dt, k, s))
                logger.debug('Sum: {}'.format(s))
                if s > get_threshold(k):
                    logger.debug('Skipping.')
                    continue
                if k in result:
                    result[k] += r
                    count[k] += 1
                    logger.debug('Adding.')
                    continue
                result[k] = r
                count[k] = 1
                logger.debug('Creating.')
        logger.info('Counts: {}'.format(count))
    logfile.close()

    # save
    logger.info('Saving {}'.format(target_path))
    with h5py.File(target_path, 'w') as h5:
        for k in result:
            # Write to result
            d = h5.create_dataset(
                k,
                data=result[k] / count[k],
                dtype='f4',
                compression='lzf',
                shuffle=True,
            )
            d.attrs['cluttercount'] = count[k]
            d.attrs['threshold'] = get_threshold(k)
        h5.attrs['cluttercount'] = int(sum(count.values()) / len(count))
        h5.attrs['range'] = b'{} - {}'.format(
            daterange.start, daterange.stop
        )
    logging.info('Done summing clutter.')


def main():
    """ Call command with args from parser. """
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    return command(**vars(get_parser().parse_args()))
