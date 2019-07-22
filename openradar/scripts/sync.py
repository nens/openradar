#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

from openradar import config
from openradar import loghelper

import logging
import ftplib
import os
import io


def ftp_transfer(source, target, name):
    """ Transfer ftp file from source ftp to target ftp. """
    data = io.BytesIO()
    source.retrbinary('RETR ' + name, data.write)
    data.seek(0)
    target.storbinary('STOR ' + name, data)


def ftp_sync(source, target):
    """ Synchronize working directory of target ftp to that of source ftp. """
    removed = 0
    copied = 0

    # Get the lists
    source_names = [n for n in source.nlst() if not n.startswith('.')]
    target_names = target.nlst()

    # Delete files in target that are not in source
    for name in target_names:
        if name not in source_names:
            target.delete(name)
            logging.debug('Removed {}.'.format(name))
            removed += 1

    # Add files that are in source but not in target
    for name in source_names:
        if name not in target_names:
            try:
                ftp_transfer(source=source, target=target, name=name)
                logging.debug('Copied {}.'.format(name))
                copied += 1
            except IOError:
                logging.warning('Could not transfer {}.'.format(name))
    logging.info('Files removed: {}, copied: {}.'.format(removed, copied))


def sync():
    """ Synchronize specific remote ftp folders with our ftp. """
    loghelper.setup_logging(os.path.join(config.LOG_DIR, 'sync.log'))

    # Check sync possible
    if not hasattr(config, 'FTP_HOST') or config.FTP_HOST == '':
        logging.warning('FTP not configured, FTP syncing not possible.')
        return

    try:
        target = ftplib.FTP(config.FTP_HOST,
                            config.FTP_USER,
                            config.FTP_PASSWORD)

        for name, info in config.FTP_THROUGH.items():
            logging.info('Syncing {}...'.format(name))

            # Make the connection
            source = ftplib.FTP(
                info['host'],
                info['user'],
                info['password'],
            )

            # Change to proper directories
            source.cwd(info['path'])
            target.cwd(info['target'])

            # Sync
            ftp_sync(source=source, target=target)

            # Quit connections.
            source.quit()
        target.quit()
    except:
        logging.exception('Error:')
    logging.info('Sync done.')


def main():
    return sync()
