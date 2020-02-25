# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

import logging
import os
import sys
from datetime import timedelta

import celery
import ciso8601

from openradar import config
from openradar import loghelper
from openradar import images
from openradar import scans
from openradar import products
from openradar import publishing
from openradar import utils

# Configure celery
app = celery.Celery()
app.conf.broker_url = config.CELERY_BROKER_URL
app.conf.task_time_limit = 600
# app.conf.task_always_eager = True


def on_failure(self, exc, task_id, args, kwargs, einfo):
    logging.warn(einfo)


@app.task
def do_nothing():
    """ Empty task that can be used as the start of a chain. """


@app.task(on_failure=on_failure)
def aggregate(result, datetime, timeframe, nowcast,
              radars, declutter, direct=False, cascade=False):
    """ Create aggregates and optionally cascade to depending products. """
    loghelper.setup_logging(logfile_name='radar_aggregate.log')
    logging.info(20 * '-' + ' aggregate ' + 20 * '-')

    # parse datetime if necessary
    try:
        datetime = ciso8601.parse_datetime(datetime)
    except TypeError:
        pass
    
    # Create aggregates
    aggregate_kwargs = dict(
        radars=radars,
        declutter=declutter,
        datetime=datetime,
        timeframe=timeframe
        )
    if nowcast:
        aggregate_kwargs.update(dict(
            basedir=config.NOWCAST_AGGREGATE_DIR,
            multiscandir=config.NOWCAST_MULTISCAN_DIR,
            grid=scans.NOWCASTGRID))
    else:
        aggregate_kwargs.update(dict(
            basedir=config.AGGREGATE_DIR,
            multiscandir=config.MULTISCAN_DIR,
            grid=scans.BASEGRID))

    aggregate = scans.Aggregate(**aggregate_kwargs)

    aggregate.make()
    # Cascade when requested
    if cascade:
        combinations = utils.get_product_combinations(
            datetimes=[datetime], timeframes=[timeframe],
        )
        for combination in combinations:
            calibrate_kwargs = dict(result=None,
                                    radars=radars,
                                    declutter=declutter,
                                    direct=direct,
                                    cascade=cascade)
            calibrate_kwargs.update(combination)
            if direct:
                calibrate(**calibrate_kwargs)
            else:
                calibrate.delay(**calibrate_kwargs)
    
    logging.info(20 * '-' + ' aggregate complete ' + 20 * '-')


@app.task(on_failure=on_failure)
def calibrate(result, datetime, prodcode, timeframe, nowcast,
              radars, declutter, direct=False, cascade=False):
    """ Created calibrated aggregated composites. """
    loghelper.setup_logging(logfile_name='radar_calibrate.log')
    logging.info(20 * '-' + ' calibrate ' + 20 * '-')

    # parse datetime if necessary
    try:
        datetime = ciso8601.parse_datetime(datetime)
    except TypeError:
        pass

    # Create products
    if nowcast:
        product = products.CopiedProduct(datetime)
    else:
        product = products.CalibratedProduct(
            radars=radars,
            prodcode=prodcode,
            datetime=datetime,
            timeframe=timeframe,
            declutter=declutter,
        )
    product.make()
    # Cascade when requested
    if cascade:
        combinations = utils.get_product_combinations(
            datetimes=[datetime],
            prodcodes=[prodcode],
            timeframes=[timeframe],
        )
        for combination in combinations:
            rescale_kwargs = dict(result=None,
                                  direct=direct,
                                  cascade=cascade)
            extra_kwargs = {k: v
                            for k, v in combination.items()
                            if k in ['datetime', 'prodcode', 'timeframe']}
            rescale_kwargs.update(extra_kwargs)
            if direct:
                rescale(**rescale_kwargs)
            else:
                rescale.delay(**rescale_kwargs)

    logging.info(20 * '-' + ' calibrate complete ' + 20 * '-')


@app.task(on_failure=on_failure)
def rescale(result, datetime, prodcode,
            timeframe, direct=False, cascade=False):
    """ Create rescaled products wherever possible. """
    loghelper.setup_logging(logfile_name='radar_rescale.log')
    logging.info(20 * '-' + ' rescale ' + 20 * '-')

    # parse datetime if necessary
    try:
        datetime = ciso8601.parse_datetime(datetime)
    except TypeError:
        pass

    product = products.CalibratedProduct(prodcode=prodcode,
                                         datetime=datetime,
                                         timeframe=timeframe)
    rescaleds = products.Consistifier.create_consistent_products(product)
    if not rescaleds:
        logging.info('Nothing to rescale.')

    logging.info(20 * '-' + ' rescale complete ' + 20 * '-')


@app.task(on_failure=on_failure)
def publish(result, datetimes, prodcodes, timeframes, endpoints, cascade,
            nowcast):
    """
    Publish products.

    Cascade means rescaled (derived) products are published as well.
    If the calibrate task is also run with 'cascade=True', this should
    be no problem.
    """
    loghelper.setup_logging(logfile_name='radar_publish.log')
    logging.info(20 * '-' + ' publish ' + 20 * '-')

    # parse datetimes if necessary
    try:
        datetimes = [ciso8601.parse_datetime(d) for d in datetimes]
    except TypeError:
        pass

    publisher = publishing.Publisher(datetimes=datetimes,
                                     prodcodes=prodcodes,
                                     timeframes=timeframes,
                                     nowcast=nowcast)
    for endpoint in endpoints:
        getattr(publisher, 'publish_' + endpoint)(cascade=cascade)
    logging.info(20 * '-' + ' publish complete ' + 20 * '-')


@app.task(on_failure=on_failure)
def nowcast(result, datetime, timeframe, minutes):
    """
    Create nowcast product.
    """
    loghelper.setup_logging(logfile_name='radar_nowcast.log')
    logging.info(20 * '-' + ' nowcast ' + 20 * '-')

    # parse datetime if necessary
    try:
        datetime = ciso8601.parse_datetime(datetime)
    except TypeError:
        pass

    # the result product is called the nowcast product
    nowcast_product = products.NowcastProduct(
        datetime=datetime,
        timeframe=timeframe,
    )
    # the vector products (realtime, five minutes)
    # are used to determine the translation vector.
    vector_products = []
    for vector_delay in minutes + 15, minutes:
        vector_products.append(products.CalibratedProduct(
            prodcode='r',
            timeframe='f',
            datetime=datetime - timedelta(minutes=vector_delay),
        ))
    # the base product is the product for which the data
    # is shifted to arrive at a nowcasted product.
    base_product = products.CalibratedProduct(
        prodcode='r',
        timeframe='f',
        datetime=datetime - timedelta(minutes=minutes)
    )

    nowcast_product.make(
        base_product=base_product,
        vector_products=vector_products,
    )
    logging.info(20 * '-' + ' nowcast complete ' + 20 * '-')


@app.task(on_failure=on_failure)
def animate(result, datetime):
    """
    Create animation
    Publish products.

    Cascade means rescaled (derived) products are published as well.
    """
    loghelper.setup_logging(logfile_name='radar_animate.log')
    logging.info(20 * '-' + ' animate ' + 20 * '-')

    # parse datetime if necessary
    try:
        datetime = ciso8601.parse_datetime(datetime)
    except TypeError:
        pass

    images.create_animated_gif(datetime=datetime)
    logging.info(20 * '-' + ' animate complete ' + 20 * '-')
