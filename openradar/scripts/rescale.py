#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import arguments
from openradar import tasks
from openradar import utils


def rescale(**kwargs):
    """ Create aggregates given some commandline arguments. """
    # Determine action
    task = tasks.rescale
    if kwargs['direct']:
        action = task
    else:
        action = task.delay
    # Determine derived arguments
    datetimes = utils.MultiDateRange(kwargs['range']).iterdatetimes()
    combinations = utils.get_product_combinations(
        datetimes=datetimes,
        prodcodes=kwargs['prodcodes'],
        timeframes=kwargs['timeframes'])
    # Execute or delay task
    for combination in combinations:
        action_kwargs = dict(result=None,
                             direct=kwargs['direct'],
                             cascade=kwargs['cascade'])
        rescale_kwargs = {k: v
                          for k, v in combination.items()
                          if k in ['datetime', 'prodcode', 'timeframe']}
        action_kwargs.update(rescale_kwargs)
        action(**action_kwargs)


def main():
    argument = arguments.Argument()
    parser = argument.parser([
        'range',
        'prodcodes',
        'timeframes',
        'direct',
        'cascade',
    ])
    rescale(**vars(parser.parse_args()))
