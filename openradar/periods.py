# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.
"""
Period looper for atomic scripts.
"""

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

import datetime
import math
import re

from openradar import utils

# period parsing
PERIOD = re.compile('([0-9]{1,2})([mhdw])')
UNITS = {'m': 'minutes', 'h': 'hours', 'd': 'days', 'w': 'weeks'}


def parse(text):
    """
    Return start, stop tuple.

    text can be:
        start/stop: 2003/2004
        start: 2003 - now
        period: 2d - now
    """
    if '/' in text:
        return map(utils.parse_datetime, text.split('/'))
    now = datetime.datetime.utcnow()
    match = PERIOD.match(text)
    if match:
        value, unit = match.groups()
        delta = datetime.timedelta(**{UNITS[unit]: int(value)})
        return now - delta, now
    return utils.parse_datetime(text), now


class Period(object):
    """ Period looper. """
    def __init__(self, text):
        period = parse(text)

        # init
        self.step = datetime.timedelta(minutes=5)

        # snap
        ref = datetime.datetime(2000, 1, 1)
        step = self.step.total_seconds()
        start = step * math.ceil((period[0] - ref).total_seconds() / step)
        stop = step * math.floor((period[1] - ref).total_seconds() / step)
        self.start = ref + datetime.timedelta(seconds=start)
        self.stop = ref + datetime.timedelta(seconds=stop)

    def __iter__(self):
        """ Return generator of datetimes. """
        now = self.start
        while now <= self.stop:
            yield now
            now += self.step

    def __repr__(self):
        return '{} - {}'.format(self.start, self.stop)
