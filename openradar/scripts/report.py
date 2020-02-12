#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.
"""
Created on Wed Feb 12 16:10:32 2014

Tom van Steijn, RHDHV
"""

import datetime as dt
import glob
import logging
import os
import sys

import psycopg2
import pandas as pd

from openradar import arguments
from openradar import config
from openradar import scans
from openradar import utils


def expected_files_volumetric(radarcode, datetimes):
    """ Generate list of expected files based on radar code and datetimes. """
    # generate expected path from scan signature
    files = []
    for scandatetime in datetimes:
        scan = scans.ScanSignature(
            scancode=radarcode,
            scandatetime=scandatetime,
        )
        files.append(scan.get_scanpath())
    return files


def available_files_volumetric(radar_dir, start):
    """ Generate list of available files for given date. """
    # Get radar_dir names from start datetime
    year = str(start.year)
    month = str(start.month).zfill(2)
    day = str(start.day).zfill(2)

    # List all content in specified radar_dir
    files = glob.glob(os.path.join(radar_dir, '*', year, month, day, '*'))
    return files


def check_availability_volumetric(radar_dir, radars, (start, end)):
    """ Check data availability for given timestep. """
    # Generate expected date range
    end = end - pd.DateOffset(minutes=5)
    datetimes = pd.date_range(start=start, end=end, freq='5Min')

    # Generate expected files
    expected = expected_files_volumetric(radars, datetimes)

    # Locate available files
    found = available_files_volumetric(radar_dir, start)

    # Set difference and fraction
    missing = set(expected) - set(found)
    frac = 1 - len(missing) / len(expected)
    return frac, missing


def period_availability_volumetric(radar_dir, radars,
                                   (start, end), identities):
    """ Calculate data availability per radar for defined period. """
    # Generate date range within period in daily timestep
    period = pd.date_range(start=start, end=end, freq='D')

    # Get availability of files per day, for all radars
    availability = {}
    offset = pd.DateOffset(days=1)
    for radar in radars:
        radar_availability = {}
        for start, end in zip(period, period + offset):
            frac, missing = check_availability_volumetric(
                radar_dir, radar, (start, end),
            )
            radar_availability[start] = frac
        availability[radar] = radar_availability

    # To pandas timeseries
    availability = pd.DataFrame(availability)

    # Maximum for identities in radar codes (e.g. 'ase' and 'ess' )
    for primary, secondary in identities:
        availability[primary] = availability[[primary, secondary]].sum(axis=1)
        availability = availability.drop(secondary, axis=1)

    return availability, missing


def availability_volumetric(start, end):
    """ Availability report for volumetric data. """

    # Get data dir
    radar_dir = config.RADAR_DIR

    # Get radar codes (e.g. NL60)
    radars = config.ALL_RADARS

    # Get report dir
    report_dir = config.REPORT_DIR

    # Set identities in radar codes
    identities = [('ess', 'ase')]

    # Availability as timeseries in daily timestep
    availability, missing = period_availability_volumetric(
        radar_dir, radars, (start, end), identities
    )
    export_csv(availability, report_dir, 'volumetric')


def available_grounddata(start, end, timeframe):
    """ Connect and query database for location, datetime and timeframe. """

    # Define connection string and query template
    connstr_template = ('host={host} dbname={dbname} '
                        'user={user} password={password}')
    connstr = connstr_template.format(**config.GROUND_DATABASE)

    query = '''
        SELECT
           loc.name,
           tsv.datetime,
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
          tsv.datetime BETWEEN '{start}' AND '{end}';
          '''

    # Fill query template with unit and datetime
    parameters = {'f': 'WNS1400.5m', 'h': 'WNS1400.1h', 'd': 'WNS1400.1d'}

    start = dt.datetime.strftime(start, '%Y-%m-%d %H:%M:%S')
    end = dt.datetime.strftime(end, '%Y-%m-%d %H:%M:%S')

    query_dict = {
        'parameter': parameters[timeframe],
        'start': start,
        'end': end,
    }
    query = query.format(**query_dict)

    # Connect to database, query and retrieve rows
    conn = psycopg2.connect(connstr)
    cur = conn.cursor()
    cur.execute(query)
    rows = cur.fetchall()
    return rows


def check_availability_grounddata(rows, full_index):
    """ Check availability (not null) for rows from grounddata database. """

    try:
        # Rows to timeseries with multiindex (location, datetime)
        locations, datetimes, values = zip(*rows)
        index = pd.MultiIndex.from_tuples(zip(locations, datetimes))
        timeseries = pd.Series(values, index=index)

        # Reindex with full index (to cover for timesteps missing in
        # all series)
        timeseries = timeseries.reindex(full_index, level=1)

        return timeseries.notnull()
    except:
        print('No grounddata data in defined period')


def availability_timeframe(start, end, timeframe):
    """ Availability of groundstation data for given timeframe. """

    # Define full index for period between (start, end)
    freqs = {'f': '5Min', 'h': 'h', 'd': 'd'}
    full_index = pd.date_range(start=start, end=end, freq=freqs[timeframe])

    # Account for readout at UTC+8 if timeframe is day
    if timeframe == 'd':
        full_index = full_index + pd.DateOffset(hours=8)

    # Retrieve series as rows from database for period and timeframe
    rows = available_grounddata(start, end, timeframe)

    # Check availability per station for full index
    availability = check_availability_grounddata(rows, full_index)
    return availability


def availability_grounddata(start, end):
    """ Check availability for all ground data within start, end inclusive. """

    # Get report dir
    report_dir = config.REPORT_DIR

    # Check availability for all timeframes (5 minutes, hourly, daily)
    timeframes = ['f', 'h', 'd']
    for timeframe in timeframes:
        availability = availability_timeframe(start, end, timeframe)

        # Map boolean values to 1, 0
        availability = availability.map({True: 1, False: 0})

        # Locations to column names, missing values to 0
        availability = availability.unstack(0)
        availability = availability.fillna(0)

        # Resample to daily series
        availability = availability.resample('d', how='mean')

        # Export using generic csv export for reports
        export_csv(availability, report_dir, 'grounddata_' + timeframe)


def export_csv(report, report_dir, report_type, export_sum=True):
    """ Export report as comma separated values. """
    # Get start and end datetime as string
    start = report.index[0].strftime('%Y%m%d')
    end = report.index[-1].strftime('%Y%m%d')

    # Build filepath
    csvpath = '_'.join([report_type, start, end]) + '.csv'
    csvpath = os.path.join(report_dir, csvpath)

    # Export to csv
    report.to_csv(csvpath, na_rep=-999, float_format='%.3f')

    if export_sum:
        csvpath = '_'.join([report_type, 'sum', start, end]) + '.csv'
        csvpath = os.path.join(report_dir, csvpath)
        report.sum(axis=1).to_csv(csvpath, na_rep=-999, float_format='%.3f')


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    argument = arguments.Argument()
    parser = argument.parser(['range'])
    args = vars(parser.parse_args())
    dates = utils.DateRange(args['range'])

    availability_volumetric(dates.start, dates.stop)
    availability_grounddata(dates.start, dates.stop)
