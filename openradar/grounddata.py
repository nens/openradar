# -*- coding: utf-8 -*-
"""
Created on Tue Feb 18 14:44:37 2014

Tom van Steijn, RHDHV
"""

import datetime as dt

import psycopg2

from openradar import config


def get_rainstations(datetime, timeframe):
    """ Connect and query database for datetime and timeframe. """

    # Define query template
    query = '''
        SELECT
          loc.x,
          loc.y,
          loc.id,
          tsv.scalarvalue
        FROM
          rgrddata00.timeseriesvaluesandflags tsv,
          rgrddata00.locations loc,
          rgrddata00.timeserieskeys tsk,
          rgrddata00.parameterstable prt
        WHERE
          prt.id = '{parameter}' AND
          tsv.serieskey = tsk.serieskey AND
          tsk.locationkey = loc.locationkey AND
          tsk.parameterkey = prt.parameterkey AND
          tsv.datetime = '%Y-%m-%d %H:%M:%S';
          '''
    # Fill query template with unit and datetime
    parameters = {'f': 'WNS1400.5m', 'h': 'WNS1400.1h', 'd': 'WNS1400.1d'}
    parameter = {'parameter': parameters[timeframe]}
    query = query.format(**parameter)
    query = dt.datetime.strftime(datetime, query)

    # Connect to database, query and retrieve rows
    kwargs = {'connect_timeout': '10',
              'options': '-c statement_timeout=10000'}
    kwargs.update(config.GROUND_DATABASE)
    conn = psycopg2.connect(**kwargs)
    cur = conn.cursor()
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()

    # Reshape to list of dicts
    rows = [{'coords': (x, y), 'id': q, 'value': v} for x, y, q, v in rows]
    return rows

if __name__ == '__main__':
    datetime = dt.datetime(2012, 1, 2, 12)
    timeframe = 'f'
    rows = get_rainstations(datetime, timeframe)
