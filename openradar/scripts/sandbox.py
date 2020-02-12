#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import products
from openradar import arguments
from openradar import utils


def sandbox(**kwargs):
    """ Print a value from various datafiles. """
    i, j = map(int, kwargs['indices'].split(','))
    datetimes = utils.MultiDateRange(kwargs['range']).iterdatetimes()
    combinations = utils.get_product_combinations(
        datetimes=datetimes,
        prodcodes=kwargs['prodcodes'],
        timeframes=kwargs['timeframes'],
    )
    for combination in combinations:
        # The calibrate
        calibrate = products.CalibratedProduct(**combination)
        with calibrate.get() as calibrate_h5:
            print('Calibrate: {}'.format(calibrate_h5['precipitation'][i, j]))
        # The rescaled
        if utils.consistent_product_expected(combination['prodcode'],
                                             combination['timeframe']):
            rescaled = products.ConsistentProduct(**combination)
            print(rescaled.path)
            with rescaled.get() as rescaled_h5:
                print('Rescaled: {}'.format(
                    rescaled_h5['precipitation'][i, j],
                ))
        # The thredds
        thredds = products.ThreddsFile.get_for_product(calibrate)
        t = thredds._index(calibrate)
        with thredds.get() as thredds_h5:
            print('Thredds: {}'.format(
                thredds_h5['precipitation'][i, j, t],
            ))
        # The merged threddsfile
        thredds_m = products.ThreddsFile.get_for_product(calibrate, merge=True)
        t = thredds_m._index(calibrate)
        with thredds_m.get() as thredds_m_h5:
            print('Thredds(m): {} ({})'.format(
                thredds_m_h5['precipitation'][i, j, t],
                thredds_m_h5['available'][t]
            ))
        # Opendap
        values = products.get_values_from_opendap(
            x=i,
            y=j,
            start_date=combination['datetime'],
            end_date=combination['datetime'],
        )
        print('Opendap: {}'.format(values))


def main():
    argument = arguments.Argument()
    parser = argument.parser([
        'range',
        'prodcodes',
        'timeframes',
        'indices',
    ])
    sandbox(**vars(parser.parse_args()))
