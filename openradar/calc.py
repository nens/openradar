# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.
"""
The Z and R functions should be each others inverse:

    >>> round(Z(R(10.123456)), 3)
    10.123

Rain values must be correct:

    >>> Rain(np.array([56,55,54,7,6]).reshape(-1,1)).get()
    array([[ 99.85188151],
           [ 99.85188151],
           [ 86.46816701],
           [  0.09985188],
           [  0.        ]])

"""

from scipy.ndimage import measurements
from scipy import ndimage

import logging
import math
import numpy as np

RADIUS43 = 8495.  # Effective earth radius in km.

def R(Z):
    return np.power(Z / 200., 0.625)


def Z(R):
    return 200. * np.power(R, 1.6)


def weight(r, rtop, rmax):
    """ Must this be radar range, rather than surface dist? """
    w = np.where(
        r > rtop,
        1 - np.square((r - rtop) / (rmax - rtop)),
        np.square(r / rtop),
    )
    return w


def calculate_theta(rang, elev, anth):
    """
    Return angle <radar, center-of-earth, datapoint> in radians.

    rang: distance from radar to datapoint in km
    elev: angle between beam and horizontal plane in radians
    anth: the antenna height above the earth surface in km

    horizon_height: height relative to horizon plane
    horizon_dist: distance along horizon plane
    """
    horizon_dist = rang * np.cos(elev)
    horizon_alt = anth + rang * np.sin(elev)

    return np.arctan(horizon_dist / (horizon_alt + RADIUS43))


def calculate_cartesian(theta, azim):
    """
    Return (x,y) in km along earth surface.

    All angles must be in radians.
    azim: clockwise from north
    theta: angle <radar, center-of-earth, datapoint>
    """
    dist = theta * RADIUS43
    return dist * np.sin(azim), dist * np.cos(azim)


def calculate_height(theta, elev, anth):
    """
    Return height of datapoint above earth surface.

    All angles must be in radians.
    anth: the antenna height above the earth surface in km
    elev: angle between beam and horizontal plane
    theta: angle <radar, center-of-earth, datapoint>
    alpha: angle <datapoint, radar, center-of-earth>
    beta: angle <center-of-earth, datapoint, radar>

    a and b are the lengths of the triangle sides opposite to angles
    alpha and beta respectively.
    """
    alpha = elev + np.pi / 2
    beta = np.pi - theta - alpha
    b = RADIUS43 + anth
    a = b * np.sin(alpha) / np.sin(beta)  # Law of sines used here.

    return a - RADIUS43


class Rain(object):
    """ Do calculations from dBZ to rain """
    def __init__(self, dBZ):
        self._dBZ = dBZ.copy()

    def _clip_hail(self):
        self._dBZ[np.greater(self._dBZ, 55)] = 55

    def _make_Z(self):
        self._Z = np.power(10, self._dBZ / 10)

    def _remove_noise(self):
        self._Z[np.less(self._dBZ, 7)] = 0

    def get(self):
        self._clip_hail()
        self._make_Z()
        self._remove_noise()
        return R(self._Z)


def declutter_by_area(array, area):
    """
    Remove clusters with area less or equal to area.
    """

    # Create array
    if isinstance(array, np.ma.MaskedArray):
        nonzero = np.greater(array.filled(fill_value=0), 0.1)
    else:
        nonzero = np.greater(array, 0.1)

    logging.debug('Starting size declutter.')
    labels, count1 = measurements.label(nonzero)
    logging.debug('Found {} clusters.'.format(count1))
    areas = measurements.sum(nonzero, labels, labels)
    index = np.less_equal(areas, area)
    nonzero[index] = False
    labels, count2 = measurements.label(nonzero)
    logging.debug(
        'Removed {} clusters with area <= {}.'.format(
            count1 - count2, area,
        ),
    )

    if isinstance(array, np.ma.MaskedArray):
        array.data[index] = 0
    else:
        array[index] = 0


def calculate_vector(data1, data2):
    """
    Return translation vector based on correlation.
    """
    if data1.shape != data2.shape:
        raise ValueError('arrays must have equal shape.')
    data3 = ndimage.correlate(data1, data2, mode='constant')
    return [i - int(s / 2)
            for s, i in zip(data3.shape,
                            np.unravel_index(data3.argmax(), data3.shape))]


def calculate_slices(size, full_extent, partial_extent):
    """
    Return the slices into an array of size size to access a partial
    extent where the array covers the full extent.
    """
    w, h = size
    p1, q1, p2, q2 = partial_extent
    f1, g1, f2, g2 = full_extent

    # slice stops for the first array (y) dimension
    s01 = int(math.floor(h * (q1 - g1) / (g2 - g1)))
    s02 = int(math.ceil(h * (q2 - g1) / (g2 - g1)))

    # slice stops for the second array (x) dimension
    s11 = int(math.floor(w * (p1 - f1) / (f2 - f1)))
    s12 = int(math.ceil(w * (p2 - f1) / (f2 - f1)))

    return slice(s01, s02), slice(s11, s12)


def calculate_shifted(data, shift):
    """ Shift data. """
    return ndimage.shift(data, shift, order=1, cval=0)


def declutter_experimental(data, ratio):
    """
    For regions with size less or equal than size, set to zero if ratio
    of of egde sum to region sum exceeds ratio.
    """
    # label
    data_nonzero = data > 0
    lbl, nlbl = ndimage.label(data_nonzero)

    # data
    data_size = ndimage.measurements.sum(data_nonzero, lbl, lbl)
    data_sum = ndimage.measurements.sum(data, lbl, lbl)

    # edge
    edge = np.where(
        np.logical_and(ndimage.binary_erosion(data_nonzero), data_nonzero),
        0,
        data,
    )
    edge_nonzero = edge > 0
    edge_size = ndimage.measurements.sum(edge_nonzero, lbl, lbl)
    edge_sum = ndimage.measurements.sum(edge, lbl, lbl)

    # ratio
    data_mean = data_sum[data_nonzero] / data_size[data_nonzero]
    edge_mean = edge_sum[data_nonzero] / edge_size[data_nonzero]
    data_ratio = np.zeros(data.shape, data.dtype)
    data_ratio[data_nonzero] = edge_mean / data_mean

    return np.where(data_ratio > ratio, 0, data)
