#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import config
from openradar import loghelper

from datetime import datetime as Datetime
import logging
import ftplib
import os
import re

DIR_PATTERN = re.compile('TF[0-9]{4}_[XRNAU]')
FILE_PATTERN = re.compile(
    'RAD_TF[0-9]{4}_(?P<prodcode>[XRNAU])_(?P<timestamp>[0-9]{14}).h5'
)

delivery_times = dict(config.DELIVERY_TIMES)


def has_expired(filename):
    """
    Return boolean.

    True if file can be removed.
    """
    match = FILE_PATTERN.match(filename)
    if match is None:
        return False
    timestamp = match.group('timestamp')
    prodcode = match.group('prodcode').lower()
    timedelta_delivery = delivery_times[prodcode]
    datetime_product = Datetime.strptime(timestamp, '%Y%m%d%H%M%S')
    age = Datetime.utcnow() - datetime_product - timedelta_delivery
    return age.days > config.FTP_AGE


def cleanup_ftp_dir(ftp, dirname):
    """ Remove old files in dir. """
    count = 0
    ftp.cwd(dirname)
    try:
        names = ftp.nlst()
    except ftplib.error_perm as ftp_error:
        logging.debug(ftp_error)
        ftp.cwd('..')
        return 0
    for filename in names:
        if has_expired(filename):
            ftp.delete(filename)
            count += 1
    logging.debug('Removed {} files from {}.'.format(count, dirname))
    ftp.cwd('..')
    return count


def cleanup_ftp():
    """ Remove old files from ftp. """
    # Connect
    ftp = ftplib.FTP(config.FTP_HOST,
                     config.FTP_USER,
                     config.FTP_PASSWORD)

    # Call dir cleanup for every dir
    count = 0
    for dirname in ftp.nlst():
        if DIR_PATTERN.match(dirname):
            count += cleanup_ftp_dir(ftp=ftp, dirname=dirname)
    logging.info('Removed {} files from FTP.'.format(count))
    ftp.quit()


def cleanup():
    """ Synchronize specific remote ftp folders with our ftp. """
    loghelper.setup_logging(os.path.join(config.LOG_DIR, 'cleanup.log'))
    logging.info('Starting cleanup...')

    # Check sync possible
    if not hasattr(config, 'FTP_HOST') or config.FTP_HOST == '':
        logging.warning('FTP not configured, FTP cleanup not possible.')
        return

    try:
        cleanup_ftp()
    except:
        logging.exception('Error:')
    logging.info('Cleanup done.')


def main():
    return cleanup()
