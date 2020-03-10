# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import config
from openradar import periods
from openradar import scans

from datetime import datetime as Datetime
from datetime import timedelta as Timedelta
from os.path import abspath, dirname, exists, join

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


class RemoteFileRetriever(object):
    """ Currently retrieves from HTTPS. """
    def __init__(self, remote_radars, source_dir):
        self.remote_radars = remote_radars
        self.source_dir = source_dir

    def retrieve(self, text):
        """ Retrieve files for some period. """
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

                # determine url
                url = datetime.strftime(remote_radar['url'])

                # check head for modification time
                response = requests.head(url)
                if response.status_code != 200:
                    logging.debug('%s not available yet.', scan_name)
                    continue

                # compare modification time to expected datetime
                last_modified = Datetime.strptime(
                    response.headers["last-modified"],
                    "%a, %d %b %Y %H:%M:%S GMT",
                )
                if abs((datetime - last_modified).total_seconds()) > 3600:
                    logging.debug('%s not available yet.', scan_name)
                    continue

                # log head request content length
                content_length = response.headers["content-length"]
                logging.info('%s HEAD size %s', scan_name, content_length)

                # download
                logging.debug('Downloading %s', url)
                response = requests.get(url, auth=remote_radar.get('auth'))
                if response.status_code != 200:
                    logging.info('Retrieve of %s failed.', scan_name)
                    continue

                # double check header size and content size
                content_length_get = response.headers["content-length"]
                logging.info('%s GET size %s', scan_name, content_length_get)
                size = len(response.content)
                logging.info('%s acutal size %s', scan_name, size)
                if content_length_get != size:
                    logging.info('Size mismatch, not saving.', scan_name)
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

    # new style http and maybe other imports
    remote_file_retriever = RemoteFileRetriever(
        remote_radars=config.REMOTE_RADARS,
        source_dir=config.SOURCE_DIR,
    )

    while True:
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
    return False
