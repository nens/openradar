#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

import logging

from celery import chain

from openradar import arguments
from openradar import config
from openradar import files
from openradar import loghelper
from openradar import tasks
from openradar import utils


def master(**kwargs):
    """ Run the radar production chain for a single datetime. """
    loghelper.setup_logging(logfile_name='radar_master.log')
    logging.info(20 * '-' + ' master ' + 20 * '-')

    # Determine the delivery datetime and if necessary wait for files.
    if kwargs['range'] is not None:
        datetimes = utils.DateRange(kwargs['range']).iterdatetimes()
        for i, datetime_delivery in enumerate(datetimes):
            if i > 0:
                logging.warning('Range of datetimes given. Using the first.')
                break
    else:
        datetime_delivery = utils.closest_time()
        try:
            files.sync_and_wait_for_files(dt_calculation=datetime_delivery)
        except Exception as exception:
            logging.exception(exception)

    # Organize
    files.organize_from_path(path=config.SOURCE_DIR)

    # Product datetime depends on delevery times
    declutter = dict(
        size=config.DECLUTTER_SIZE,
        history=config.DECLUTTER_HISTORY,
    )
    radars = config.ALL_RADARS

    # nowcast extent is from utils.get_combinations
    delivery_times = [(p, t) for p, t in config.DELIVERY_TIMES if p in 'rnau']

    # Submit tasks in a chain.
    subtasks = [tasks.do_nothing.s()]
    for prodcode, timedelta_delivery in delivery_times:
        datetime_product = datetime_delivery - timedelta_delivery
        combinations = utils.get_aggregate_combinations(
            datetimes=[datetime_product],
        )
        for combination in combinations:
            # Add a separator between groups of tasks
            logging.info(40 * '-')

            # Nowcast combinations only proceed for prodcode r
            if combination['nowcast'] and not prodcode == 'r':
                continue

            # Append aggregate subtask
            aggregate_kwargs = dict(declutter=declutter, radars=radars)
            aggregate_kwargs.update(combination)
            subtasks.append(tasks.aggregate.s(**aggregate_kwargs))
            tpl = 'Agg. task: {datetime} {timeframe}   {nowcast}'
            logging.info(tpl.format(**aggregate_kwargs))

            # Append calibrate subtask
            calibrate_kwargs = dict(prodcode=prodcode)
            calibrate_kwargs.update(aggregate_kwargs)
            subtasks.append(tasks.calibrate.s(**calibrate_kwargs))
            tpl = 'Cal. task: {datetime} {timeframe} {prodcode} {nowcast}'
            logging.info(tpl.format(**calibrate_kwargs))

            # Append rescale subtask
            rescale_kwargs = {k: v
                              for k, v in calibrate_kwargs.items()
                              if k in ['datetime', 'prodcode', 'timeframe']}
            subtasks.append(tasks.rescale.s(**rescale_kwargs))
            tpl = 'Res. task: {datetime} {timeframe} {prodcode}'
            logging.info(tpl.format(**rescale_kwargs))

            # Append publication subtask
            subtasks.append(tasks.publish.s(
                datetimes=[calibrate_kwargs['datetime']],
                prodcodes=[calibrate_kwargs['prodcode']],
                timeframes=[calibrate_kwargs['timeframe']],
                nowcast=calibrate_kwargs['nowcast'],
                endpoints=['ftp', 'local', 'image'],
                cascade=True,
            ))
            tpl = 'Pub. task: {datetime} {timeframe} {prodcode} {nowcast}'
            logging.info(tpl.format(**calibrate_kwargs))

    # Append subtask to create animated gif
    subtasks.append(tasks.animate.s(datetime=datetime_delivery))

    # Submit all subtask as a single chain
    chain(*subtasks).apply_async()

    logging.info(20 * '-' + ' master complete ' + 20 * '-')


def main():
    argument = arguments.Argument()
    parser = argument.parser(
        ['opt_range'],
        description=('Run the radar production chain for '
                     'now, or for a single moment in time.'),
    )
    master(**vars(parser.parse_args()))
