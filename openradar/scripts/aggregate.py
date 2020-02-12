#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import arguments
from openradar import tasks
from openradar import utils


def aggregate(**kwargs):
    """ Create aggregates given some commandline arguments. """
    # Determine action
    task = tasks.aggregate
    if kwargs['direct']:
        action = task
    else:
        action = task.delay
    # Determine derived arguments
    declutter = dict(
        size=kwargs['declutter_size'],
        history=kwargs['declutter_history'],
    )
    datetimes = utils.MultiDateRange(kwargs['range']).iterdatetimes()
    combinations = utils.get_aggregate_combinations(
        datetimes=datetimes, timeframes=kwargs['timeframes'],
    )
    # Execute or delay task
    for combination in combinations:
        if kwargs['nowcast'] != combination['nowcast']:
            continue
        action_kwargs = dict(result=None,
                             declutter=declutter,
                             radars=kwargs['radars'],
                             direct=kwargs['direct'],
                             cascade=kwargs['cascade'])
        action_kwargs.update(combination)
        action(**action_kwargs)


def main():
    argument = arguments.Argument()
    parser = argument.parser([
        'range',
        'radars',
        'timeframes',
        'declutter_size',
        'declutter_history',
        'direct',
        'cascade',
        'nowcast'
    ])
    aggregate(**vars(parser.parse_args()))
