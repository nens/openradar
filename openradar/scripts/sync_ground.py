# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.
"""
Sync groundstations to a flat mirror and place new files atomically in an
import directory.
"""
from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

from os.path import basename, join
from urlparse import urljoin

import argparse
import logging
import os
import re
import shutil
import sys

import requests

from openradar import config

logger = logging.getLogger(__name__)

# directories
MIRROR_DIR = config.SYNC_GROUND['mirror']  # local flat cache of remote files
IMPORT_DIR = config.SYNC_GROUND['import']  # FEWS import dir

# url
URL = config.SYNC_GROUND['url']

# credentials
USER = config.SYNC_GROUND['user']
PASSWORD = config.SYNC_GROUND['password']

# link pattern
PATTERN = re.compile('<a href="(.*)">.*</a>')


def get_child_urls(url, auth):
    """
    Return the value of the links.
    """
    text = requests.get(url, auth=auth).text
    for line in text.split('\n'):
        match = PATTERN.search(line)
        if not match:
            continue
        link = match.groups()[0]
        if link != '../':
            yield urljoin(url, link)


def download(url, path, auth):
    """
    Download url to path.
    """
    response = requests.get(url, auth=auth)
    if response.status_code == 200:
        with open(path, 'wb') as f:
            f.write(response.content)


def sync_ground():
    # populate urls
    logger.info('Fetch urls.')
    urls = []
    auth = USER, PASSWORD
    for url in get_child_urls(URL, auth=auth):
        urls.extend(get_child_urls(url, auth=auth))

    # create a dictionary relating filenames to urls
    urls = dict(zip(map(basename, urls), urls))

    # make sets of remote and mirror filenames
    current = set(os.listdir(MIRROR_DIR))
    remote = set(urls)

    # remove files from mirror that are no longer on the remote
    delete = current - remote
    logger.info('Remove %s file(s).' % len(delete))
    for filename in delete:
        os.remove(join(MIRROR_DIR, filename))

    # download new remotes to mirror and copy-and-move to import
    retrieve = remote - current
    logger.info('Download %s file(s).' % len(retrieve))
    suffix = '.copy'
    for filename in retrieve:
        download(
            url=urls[filename],
            path=join(MIRROR_DIR, filename),
            auth=auth,
        )
        shutil.copy(
            join(MIRROR_DIR, filename),
            join(MIRROR_DIR, filename + suffix),
        )
        os.rename(
            join(MIRROR_DIR, filename + suffix),
            join(IMPORT_DIR, filename),
        )

    logger.info('Done.')


def get_parser():
    """ Return argument parser. """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbose', action='store_true')
    # parser.add_argument('path', metavar='FILE')
    return parser


def main():
    """ Call sync_ground with args from parser. """
    # logging
    kwargs = vars(get_parser().parse_args())
    if kwargs.pop('verbose'):
        logging.basicConfig(
            stream=sys.stderr,
            level=logging.INFO,
            format='%(message)s',
        )

    # run
    sync_ground(**kwargs)
