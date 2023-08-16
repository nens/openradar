# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import config
from openradar import scans

from datetime import datetime as Datetime
from datetime import timedelta as Timedelta
from os.path import abspath, dirname, exists, join

import logging
import os
import shutil

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


class Dataset:
    URL = (
        "https://api.dataplatform.knmi.nl/open-data/"
        "datasets/{dataset}/versions/{version}/files/"
    )
    HEADERS = {"Authorization": config.API_KEY}

    def __init__(self, dataset, version, step, pattern):
        """Represents a Dataplatform Dataset.

        Args:
            dataset (str): dataset name
            version (str): dataset version
        """
        self.url = self.URL.format(dataset=dataset, version=version)
        self.pattern = pattern

    def latest(self, count=1):
        """Return list of (filename, datetime) tuples.

        Args:
            count (int): Number of files in the past to list.
        """
        response = requests.get(
            self.url,
            headers=self.HEADERS,
            params={"maxKeys": count, "sorting": "desc"},
        )
        result = []
        for item in response.json()["files"]:
            filename = item["filename"]
            datetime = Datetime.strptime(filename, self.pattern)
            result.append({"filename": filename, "datetime": datetime})

        return result

    def _get_download_url(self, filename):
        """ Return temporary download url for filename.
        """
        response = requests.get(
            "{url}/{filename}/url".format(url=self.url, filename=filename),
            headers=self.HEADERS,
        )
        return response.json().get("temporaryDownloadUrl")

    def retrieve(self, filename):
        url = self._get_download_url(filename)
        return requests.get(url).content


def get_download_path(scan_name):
    """Return download path or None.

    None means the scan is already downloaded.
    """
    download_path = join(config.SOURCE_DIR, scan_name)
    if exists(download_path):
        return

    scan_signature = scans.ScanSignature(scan_name=scan_name)
    scan_path = scan_signature.get_scanpath()
    if exists(scan_path):
        return

    return download_path


def fetch_knmi_volume_files(source, count):
    dataset = Dataset(**source['platform'])
    for item in dataset.latest(count):
        scan_name = item["filename"]
        download_path = get_download_path(scan_name)
        if download_path is None:
            continue

        # download
        content = dataset.retrieve(scan_name)
        with open(download_path, 'wb') as f:
            f.write(content)
        logging.info("Retrieved %s", scan_name)


def fetch_dwd_volume_files(source, count, dt_last):
    step = Timedelta(minutes=5)
    for stepcount in range(1 - count, 1):
        dt_current = dt_last + step

        scan_name = dt_current.strftime(source['scan'])
        download_path = get_download_path(scan_name)
        if download_path is None:
            continue

        # download
        url = dt_current.strftime(source['url'])
        response = requests.get(url, auth=source['auth'])
        if response.status_code != 200:
            continue
        with open(download_path, 'wb') as f:
            f.write(response.content)
        logging.info("Retrieved %s", scan_name)


def fetch_volume_files(dt_calculation):
    """
    """
    # the radar file is 5 minutes before the product file.
    dt_last = dt_calculation - Timedelta(minutes=5)
    count = 12

    # Add radars to expected files.
    for source in config.VOLUME_SOURCES:
        if "platform" in source:
            fetch_knmi_volume_files(source, count=count)
        else:
            fetch_dwd_volume_files(source=source, count=count, dt_last=dt_last)
