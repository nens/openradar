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

EDGES = np.arange(0, 71)


class Histogram(object):
    """
    Updateable multidimensional histogram. Initialize with the edges of
    the bins and the shape of the individual datasets. Update with one
    dataset at a time.
    """
    def __init__(self, edges, shape):
        nbins = len(edges) - 1,
        self.count = 0
        self.array = np.zeros(nbins + shape, 'u8')
        self.edges = np.array(edges)
        self.total = np.zeros(shape)

    def add(self, array):
        """ Returns the updated histogram. """
        self.count += 1
        self.total += array
        before = array < self.edges[0]
        for i, l in enumerate(self.edges[1:]):
            current = np.logical_and(array < l, ~before)
            before[current] = True
            self.array[i] += current
        return self.array


def get_parser():
    parser = argparse.ArgumentParser(
        description='Create a multidimensional histogram',
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
        default=os.path.join(config.IMG_DIR, 'histogram.h5'),
        help='Ouput filename',
    )
    return parser


def command(target_path, range_text):
    """ Rain histogram gathering. """
    # collect
    daterange = utils.DateRange(range_text)
    pathhelper = utils.PathHelper(
        basedir=config.MULTISCAN_DIR,
        code=config.MULTISCAN_CODE,
        template='{code}_{timestamp}.h5'
    )
    result = dict()
    for dt in daterange.iterdatetimes():
        path = pathhelper.path(dt)
        logger.info('Processing {}'.format(path))
        with h5py.File(path, 'r') as h5:
            for k, v in h5.iteritems():
                logger.debug('Radar: {}'.format(k))
                r = v['rain'][:]
                r[r == -9999] = 0
                if k not in result:
                    result[k] = Histogram(edges=EDGES, shape=r.shape)
                result[k].add(r)

    # save
    logger.info('Saving: {}'.format(target_path))
    with h5py.File(target_path, 'w') as h5:
        for k, v in result.items():
            d = h5.create_dataset(
                k,
                data=v.array,
                dtype='f4',
                compression='lzf',
                shuffle=True,
            )
            d.attrs['count'] = v.count
            d.attrs['edges'] = v.edges
        h5.attrs['range'] = b'{} - {}'.format(
            daterange.start, daterange.stop
        )
    logging.info('Done creating histogram.')


def main():
    """ Call command with args from parser. """
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    return command(**vars(get_parser().parse_args()))
