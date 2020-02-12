#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import arguments
from openradar import config
from openradar import images
from openradar import loghelper
from openradar import products
from openradar import scans
from openradar import utils


def get_image_args():
    argument = arguments.Argument()
    parser = argument.parser(
        ['image_dir', 'range'],
        description='Create images from radar data.',
    )
    parser.add_argument('--postfix',
                        type=str,
                        default='',
                        help='Postfix for filename.')
    parser.add_argument('--label',
                        type=str,
                        default='',
                        help='Label text in image.')
    parser.add_argument('-p', '--prodcode',
                        choices=['r', 'n', 'a', 'u'],
                        default='r',
                help='(r)ealtime, (n)ear-realtime, (a)fterwards or (u)ltimate')
    parser.add_argument('-c', '--product',
                        choices=['a', 'b', 'c'],
                        default='b',
                        help=('(a)ggregate, cali(b)rated, or (c)onsistent'))
    parser.add_argument('-t', '--timeframe',
                        choices=['f', 'h', 'd'],
                        default='f',
                        help='(f)ive minute, (h)our or (d)ay')
    parser.add_argument('-n', '--nowcast',
                        action='store_true',
                        default=False,
                        help='Use nowcast extent')
    parser.add_argument('-f', '--format',
                        type=str,
                        default='png',
                        choices=['png', 'tif'],
                        help='Save "tif" or "png"')
    return vars(parser.parse_args())


def product_generator(product, prodcode, timeframe, datetimes, nowcast):
    """ Return product generator. """
    if product == 'a':
        aggregate_kwargs = dict(declutter=None,
                                radars=config.ALL_RADARS)
        combinations = utils.get_aggregate_combinations(
            datetimes=datetimes,
            timeframes=timeframe,
        )
        for combination in combinations:
            if nowcast != combination['nowcast']:
                continue
            if nowcast:
                aggregate_kwargs.update(dict(
                    basedir=config.NOWCAST_AGGREGATE_DIR,
                    multiscandir=config.NOWCAST_MULTISCAN_DIR,
                    grid=scans.NOWCASTGRID,
                    datetime=combination['datetime'],
                    timeframe=combination['timeframe']))
            else:
                aggregate_kwargs.update(dict(
                    basedir=config.AGGREGATE_DIR,
                    multiscandir=config.MULTISCAN_DIR,
                    grid=scans.BASEGRID,
                    datetime=combination['datetime'],
                    timeframe=combination['timeframe']))

            yield scans.Aggregate(**aggregate_kwargs)
    else:
        combinations = utils.get_product_combinations(prodcodes=prodcode,
                                                      datetimes=datetimes,
                                                      timeframes=timeframe)
        for combination in combinations:
            if nowcast != combination.pop('nowcast'):
                continue
            if nowcast:
                yield products.CopiedProduct(datetime=combination['datetime'])
            else:
                if product == 'b':
                    yield products.CalibratedProduct(**combination)
                else:
                    yield products.ConsistentProduct(**combination)


def main():
    """ Create images for a range of products. """
    loghelper.setup_logging()

    # Get products according to args
    args = get_image_args()

    multidaterange = utils.MultiDateRange(args['range'])
    products = product_generator(product=args['product'],
                                 prodcode=args['prodcode'],
                                 timeframe=args['timeframe'],
                                 datetimes=multidaterange.iterdatetimes(),
                                 nowcast=args['nowcast'])

    create = dict(png=images.create_png,
                  tif=images.create_tif)[args['format']]

    # Create images with those products
    kwargs = args.copy()
    map(kwargs.pop, ['range', 'product', 'timeframe', 'prodcode'])
    create(products, **kwargs)
