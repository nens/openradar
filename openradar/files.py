# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

from openradar import config
from openradar import periods
from openradar import scans
from openradar import utils

from datetime import datetime as Datetime
from datetime import timedelta as Timedelta
from os.path import abspath, dirname, exists, join

import collections
import ftplib
import logging
import os
import shutil
import time


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


class FtpImporter(object):
    """
    Connect to ftp for radars and fetch any files that are not fetched yet.
    """
    def __init__(self, datetime, max_age=86400):
        """
        Set datetime and empty connection dictionary. Max age is in
        seconds, measured from datetime.
        """
        utils.makedir(config.SOURCE_DIR)

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
    ftp_importer = FtpImporter(datetime=dt_calculation)
    while True:
        fetched = ftp_importer.fetch()
        if fetched:
            logging.info('Fetched {} files from FTP.'.format(len(fetched)))

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


RemoteFile = collections.namedtuple('RemoteFile', ['rpath', 'lname'])


class RemoteFileGenerator(object):
    def __init__(self, text):
        self.period = periods.Period(text)

    def __iter__(self):
        for datetime in self.period:
            for remote_file in config.REMOTE_RADARS:
                rpath = datetime.strftime(remote_file['remote'])
                lname = datetime.strftime(remote_file['local'])
                yield RemoteFile(rpath=rpath, lname=lname)


class RemoteFileRetriever(object):
    """ Contain a lot of protocol specific retriever methods. """
    def retrieve(self, remote_file):
        print(remote_file)


remote_file_generator = RemoteFileGenerator('15m')
remote_file_retriever = RemoteFileRetriever()
for remote_file in remote_file_generator:
    remote_file_retriever.retrieve(remote_file)
