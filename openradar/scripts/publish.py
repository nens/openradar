#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import arguments
from openradar import tasks
from openradar import utils


def publish(**kwargs):
    """ Create aggregates given some commandline arguments. """
    # Determine action
    task = tasks.publish
    if kwargs['direct']:
        action = task
    else:
        action = task.delay
    # Execute or delay task
    action_kwargs = dict(result=None,
                         datetimes=kwargs['range'],
                         prodcodes=kwargs['prodcodes'],
                         timeframes=kwargs['timeframes'],
                         endpoints=kwargs['endpoints'],
                         cascade=kwargs['cascade'],
                         nowcast=kwargs['nowcast'])
    action(**action_kwargs)

def main():
    argument = arguments.Argument()
    parser = argument.parser([
        'range',
        'prodcodes',
        'timeframes',
        'endpoints',
        'direct',
        'cascade',
        'nowcast'
    ])
    publish(**vars(parser.parse_args()))
