# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

from openradar import config
from openradar import periods
from openradar import scans

from datetime import datetime as Datetime
from datetime import timedelta as Timedelta
from os.path import abspath, dirname, exists, join

import ftplib
import json
import logging
import os
import shutil
import time

import requests


def organize_from_path(path):
    """ Walk basepath and move every scan in there to it's desired location """
    logging.info('Starting organize from {}'.format(path))

    for count, name in enumerate(os.listdir(path), 1):
        scan_path = abspath(join(path, name))

        try:
            scan_signature = scans.ScanSignature(scan_path=scan_path)
        except ValueError:
            msg = 'Error instantiating scan signature for %s'
            logging.exception(msg % scan_path)
            continue

        target_path = scan_signature.get_scanpath()

        if not exists(dirname(target_path)):
            os.makedirs(dirname(target_path))
        shutil.move(scan_path, target_path)

    try:
        logging.info('Processed %s files', count)
    except NameError:
        logging.info('Nothing found.')


def get_available_urls():
    """
    The KNMI open data service returns yesterdays volume file if todays
    file is not available yet. Luckily, a webservice exists that lists the
    available volume files. This function returns a set of urls that represent
    available products.
    """
    granule_id_head = 'urn:xkdc:dg:nl.knmi::'
    dataset_id_head = 'urn:xkdc:ds:nl.knmi::'
    dataset_id_tails = (
        'radar_volume_denhelder/2.0/',
        'radar_volume_full_herwijnen/1.0/',
    )

    template = (
        'https://data.knmi.nl/webservices/metadata/searchDataGranuleMetadata'
        '?from=1'
        '&to=24'
        '&sorting[sortField]=dateFrom'
        '&sorting[sortCaseSensitive]=false'
        '&sorting[sortOrder]=DESC'
        '&datasetId={dataset_id}'
        '&temporalExtent[dateFrom]='
        '&temporalExtent[timeFrom]='
        '&temporalExtent[timeTo]='
        '&temporalExtent[dateTo]='
        '&license[openData]=false'
        '&editMode=false'
        '&isThirdParty=true'
    )

    result = []
    for dataset_id_tail in dataset_id_tails:
        # fetch available so-called granule ids from the webservice
        url = template.format(dataset_id=dataset_id_head + dataset_id_tail)
        response = requests.get(url, auth=('guest', 'guest'))
        data = response.json()['data']

        # turn them into download urls
        for item in data:
            data_granule_id = json.loads(item)['dataGranuleId']
            result.append(join(
                'https://data.knmi.nl/download',
                data_granule_id[len(granule_id_head):],
            ))

    # return as a set for quick lookups
    return set(result)


class FtpImporter(object):
    """
    Connect to ftp for radars and fetch any files that are not fetched yet.
    """
    def __init__(self, datetime, max_age=3600):
        """
        Set datetime and empty connection dictionary. Max age is in
        seconds, measured from datetime.
        """
        self.datetime = datetime
        self.max_age = max_age
        self.connections = {}
        # Check what is already there.
        self.arrived = []

    def _connect(self, group):
        """ Create and store connection for group on self. """
        ftp = ftplib.FTP(
            config.FTP_RADARS[group]['host'],
            config.FTP_RADARS[group]['user'],
            config.FTP_RADARS[group]['password'],
        )
        ftp.cwd(config.FTP_RADARS[group]['path'])
        self.connections[group] = ftp
        logging.debug('FTP connection to {} established.'.format(group))

    def _sync(self, group):
        """
        Fetch files that are not older than max_age, and that are not
        yet in config.SOURCE_DIR or in config.RADAR_DIR, and store them
        in SOURCE_DIR.
        """
        ftp = self.connections[group]
        remote = ftp.nlst()
        synced = []
        for name in remote:
            try:
                scan_signature = scans.ScanSignature(scan_name=name)
            except ValueError:
                continue  # It is not a radar file as we know it.

            scandatetime = scan_signature.get_datetime()
            path = scan_signature.get_scanpath()
            age = (self.datetime - scandatetime).total_seconds()
            if name in self.arrived or age > self.max_age or exists(path):
                continue

            # Try to retrieve the file, but remove it when errors occur.
            target_path = join(config.SOURCE_DIR, name)
            try:
                with open(target_path, 'wb') as scanfile:
                    ftp.retrbinary('RETR ' + name, scanfile.write)
                synced.append(name)
                logging.debug('Fetched: {}'.format(name))
            except ftplib.all_errors:
                logging.warn('Fetch of {} failed.'.format(name))
                if exists(target_path):
                    os.remove(target_path)
        return synced

    def fetch(self):
        """ Create connection if necessary and sync any files. """
        # Update what we already have.
        for path, dirs, names in os.walk(config.SOURCE_DIR):
            self.arrived.extend(names)

        # Walk ftp filelists and sync where necessary
        synced = []
        for group in config.FTP_RADARS:
            try:
                if group not in self.connections:
                    self._connect(group)
                synced.extend(self._sync(group))
            except ftplib.all_errors:
                logging.warn('FTP connection problem for {}'.format(group))
                if group in self.connections:
                    del self.connections[group]
        return synced

    def close(self):
        """ Close open connections. """
        for group in self.connections:
            self.connections[group].quit()
            logging.debug('Quit FTP connection to {}'.format(group))


class RemoteFileRetriever(object):
    """ Currently retrieves from HTTPS. """
    def __init__(self, remote_radars, source_dir):
        self.remote_radars = remote_radars
        self.source_dir = source_dir

    def retrieve(self, text):
        """ Retrieve files for some period. """
        available = get_available_urls()

        count = 0
        for datetime in periods.Period(text):
            for remote_radar in self.remote_radars:
                # determine local paths
                scan_name = datetime.strftime(remote_radar['scan'])
                temp_path = join(self.source_dir, scan_name)
                scan_signature = scans.ScanSignature(scan_name=scan_name)
                scan_path = scan_signature.get_scanpath()

                # check if already retrieved
                if exists(scan_path):
                    logging.debug('%s already in radar dir.', scan_name)
                    continue
                if exists(temp_path):
                    logging.debug(temp_path)
                    logging.debug('%s already in source dir.', scan_name)
                    continue

                # attempt to retrieve
                url = datetime.strftime(remote_radar['url'])
                if url not in available:
                    logging.debug('%s not available yet.', scan_name)
                    continue

                logging.debug('Trying to retrieve %s', url)
                response = requests.get(url)
                if response.status_code != 200:
                    logging.debug('Retrieve of %s failed.', scan_name)
                    continue

                # save content to temporary directory
                with open(temp_path, 'wb') as temp_file:
                    temp_file.write(response.content)
                    logging.debug('Retrieve of %s succeeded.', scan_name)

                # count succesful retrievings
                count += 1
        return count


def sync_and_wait_for_files(dt_calculation, td_wait=None, sleep=10):
    """
    Return if files are present or utcnow > dt_files + td_wait

    Waiting for config.ALL_RADARS.
    """
    if td_wait is None:
        td_wait = config.WAIT_EXPIRE_DELTA

    logging.info('Waiting for files until {}.'.format(
        dt_calculation + td_wait,
    ))

    dt_radar = dt_calculation - Timedelta(minutes=5)

    set_expected = set()

    # Add radars to expected files.
    for radar in config.ALL_RADARS:
        scan_tuple = radar, dt_radar
        scan_signature = scans.ScanSignature(scan_tuple=scan_tuple)
        if not exists(scan_signature.get_scanpath()):
            set_expected.add(scan_signature.get_scanname())

    logging.debug('looking for {}'.format(', '.join(set_expected)))

    # keep walking the source dir until all
    # files are found or the timeout expires.

    # old style ftp imports
    ftp_importer = FtpImporter(datetime=dt_calculation)

    # new style http and maybe other imports
    remote_file_retriever = RemoteFileRetriever(
        remote_radars=config.REMOTE_RADARS,
        source_dir=config.SOURCE_DIR,
    )

    while True:
        # retrieve from ftp sources
        fetched = ftp_importer.fetch()
        if fetched:
            logging.info('Fetched %s files from FTP.', len(fetched))
        # retrieve from http sources
        retrieved = remote_file_retriever.retrieve('1h')
        if retrieved:
            logging.info('Retrieved %s remote files.', retrieved)

        set_names = set()
        for name in os.listdir(config.SOURCE_DIR):
            scan_signature = scans.ScanSignature(scan_name=name)
            set_names.add(scan_signature.get_scanname())

        # Add the intersection of names and expected to arrived.
        set_arrived = set_names & set_expected
        if set_arrived:
            set_expected -= set_arrived
            logging.debug('Found: {}'.format(', '.join(set_arrived)))
            if not set_expected:
                logging.info('All required files have arrived.')
                ftp_importer.close()
                return True
            logging.debug('Awaiting: {}'.format(
                ', '.join(set_expected),
            ))

        if Datetime.utcnow() > dt_calculation + td_wait:
            break

        try:
            logging.debug('Sleeping...')
            time.sleep(config.WAIT_SLEEP_TIME)
        except KeyboardInterrupt:
            break

    logging.info('Timeout expired, but {} not found.'.format(
        ', '.join(set_expected),
    ))

    ftp_importer.close()
    return False
