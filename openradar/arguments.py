#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

import argparse

from openradar import config


class Argument(object):
    """ Argument container. """
    def parser(self, arguments, description=None):
        """ Return argument parser. """
        # Create a parser
        parser = argparse.ArgumentParser(
            description=description,
            #formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        # Add requested arguments to the parser
        for argument in arguments:
            getattr(self, argument)(parser)
        return parser

    def range(self, parser):
        parser.add_argument(
            'range',
            metavar='RANGE',
            type=str,
            help='Ranges to use, for example 20110101-20110103,20110105',
        )

    def opt_range(self, parser):
        parser.add_argument(
            '-r', '--range',
            type=str,
            help='Ranges to use, for example 20110101-20110103,20110105',
        )

    def prodcodes(self, parser):
        parser.add_argument(
            '-p', '--prodcodes',
            metavar='PRODCODE',
            nargs='*',
            choices=['r', 'n', 'a', 'u'],
            default=['r', 'n', 'a', 'u'],
            help=('Choose product: (n)ear-realtime'
                  ' (r)ealtime, (a)fterwards or (u)ltimate'),
        )

    def timeframes(self, parser):
        parser.add_argument(
            '-t', '--timeframes',
            metavar='TIMEFRAME',
            nargs='*',
            choices=['f', 'h', 'd'],
            default=['f', 'h', 'd'],
            help=('Choose timeframe: (f)ive minute (e.g. at 15.55), '
                  '(h)ourly aggregates (on whole hours e.g. 09.00) or '
                  '(d)aily aggregates (24 hours from 08.00 AM to 07.55 AM'),
        )

    def radars(self, parser):
        parser.add_argument(
            '-r', '--radars',
            metavar='RADAR',
            nargs='*',
            default=config.ALL_RADARS,
            help='Radars to use. Default: {}'.format(
                ' '.join(config.ALL_RADARS),
            )
        )

    def declutter_size(self, parser):
        parser.add_argument(
            '-ds', '--declutter-size',
            type=int,
            default=config.DECLUTTER_SIZE,
            help='Groups of pixels less than this will be removed',
        )

    def declutter_history(self, parser):
        parser.add_argument(
            '-dh', '--declutter-history',
            type=float,
            default=config.DECLUTTER_HISTORY,
            help='Discard pixels with average historical clutter above this'
        )

    def source_dir(self, parser):
        parser.add_argument(
            '-s', '--source-dir',
            type=str,
            default=config.SOURCE_DIR,
            help=('Path from where all the files'
                  ' are stored that need to be organized'),
        )

    def image_dir(self, parser):
        parser.add_argument(
            '-i', '--image-dir',
            type=str,
            default=config.IMG_DIR,
            help=('Path to store images.'),
        )

    def direct(self, parser):
        parser.add_argument(
            '-d', '--direct',
            action='store_true',
            help='Run directly instead of submitting task.',
        )

    def cascade(self, parser):
        parser.add_argument(
            '-c', '--cascade',
            action='store_true',
            help='Automatically create depending tasks',
        )
    def nowcast(self, parser):
        parser.add_argument(
            '-n', '--nowcast',
            action='store_true',
            help='Use nowcast extent')

    def endpoints(self, parser):
        parser.add_argument(
            '-e', '--endpoints',
            metavar='ENDPOINT',
            nargs='*',
            choices=['h5', 'h5m', 'image', 'local', 'ftp'],
            default=['image', 'local', 'ftp'],
            help='Endpoint for publication.'
        )

    def timestamp(self, parser):
        parser.add_argument(
            '-t', '--timestamp',
            metavar='TIMESTAMP',
            help='A timestamp of the form 201302030405.',
        )

    def indices(self, parser):
        parser.add_argument(
            '-i', '--indices',
            help='Indices into the product, for example 5,7',
        )

    def minutes(self, parser):
        parser.add_argument(
            '-m', '--minutes',
            type=int,
            default=5,
            help='Integer amount of minutes.',
        )
