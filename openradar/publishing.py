# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

import ftplib
import logging
import os

from openradar import config
from openradar import images
from openradar import utils
from openradar import products


class FtpPublisher(object):
    """Context manager for FTP publishing."""

    def __enter__(self):
        """
        Make the connection to the FTP server.

        If necessary, create the directories.
        """
        self.ftp = ftplib.FTP(config.FTP_HOST,
                              config.FTP_USER,
                              config.FTP_PASSWORD)
        # Create directories when necessary
        ftp_paths = self.ftp.nlst()
        for path in [path
                     for d in config.PRODUCT_CODE.values()
                     for path in d.values()] + [config.NOWCAST_PRODUCT_CODE]:
            if path not in ftp_paths:
                self.ftp.mkd(path)

        # Set empty dictionary for nlst caching
        self._nlst = {}
        return self

    def __exit__(self, exception_type, error, traceback):
        """ Close ftp connection. """
        self.ftp.quit()

    def publish(self, product, overwrite=True):
        """ Publish the product in the correct folder. """
        ftp_file = product.ftp_path
        logging.debug(ftp_file)

        if not overwrite:
            if not os.path.exists(product.path):
                logging.debug('Local file does not exist, skipping.')
                return
            dirname = os.path.dirname(ftp_file)
            if dirname not in self._nlst:
                self._nlst[dirname] = self.ftp.nlst(dirname)
            if ftp_file in self._nlst[dirname]:
                logging.debug('FTP file already exists, skipping.')
                return

        with open(product.path, 'rb') as product_file:
            response = self.ftp.storbinary(
                'STOR {}'.format(ftp_file),
                product_file,
            )

        logging.debug('ftp response: {}'.format(response))
        logging.info(
            'Stored FTP file {}'.format(os.path.basename(ftp_file)),
        )


class Publisher(object):
    """
    Publish radar files in a variety of ways.

    Datetimes can be a sequence of datetimes or a rangetext string.
    """
    def __init__(self, datetimes, prodcodes, timeframes, nowcast):
        """ If cascade . """
        self.datetimes = datetimes
        self.prodcodes = prodcodes
        self.timeframes = timeframes
        self.nowcast = nowcast

    def ftp_publications(self, cascade=False):
        """ Return product generator. """
        if isinstance(self.datetimes, (list, tuple)):
            datetimes = self.datetimes
        else:
            # Generate datetimes from rangetext string.
            datetimes = utils.MultiDateRange(self.datetimes).iterdatetimes()
        combinations = utils.get_product_combinations(
            datetimes=datetimes,
            prodcodes=self.prodcodes,
            timeframes=self.timeframes,
        )
        for combination in combinations:
            if combination.pop('nowcast') and self.nowcast:
                yield products.CopiedProduct(datetime=combination['datetime'])
            # ignore the rest, only publish to ftp for nowcast from now on
            continue

            nowcast = combination.pop('nowcast')
            if nowcast != self.nowcast:
                continue

            if nowcast:
                yield products.CopiedProduct(datetime=combination['datetime'])
                continue

            consistent = utils.consistent_product_expected(
                prodcode=combination['prodcode'],
                timeframe=combination['timeframe'],
            )
            product = products.CalibratedProduct(**combination)
            if not consistent:
                yield product
            if cascade:
                rps = products.Consistifier.get_rescaled_products(product)
                for rescaled_product in rps:
                    yield rescaled_product

    def publications(self, cascade=False):
        for publication in self.ftp_publications(cascade=cascade):
            if not isinstance(publication, products.CopiedProduct):
                yield publication

    def image_publications(self):
        """ Return product generator of real-time, five-minute products. """
        if self.nowcast:
            return

        if isinstance(self.datetimes, (list, tuple)):
            datetimes = self.datetimes
        else:
            # Generate datetimes from rangetext string.
            datetimes = utils.MultiDateRange(self.datetimes).iterdatetimes()
        combinations = utils.get_product_combinations(
            datetimes=datetimes,
            prodcodes=self.prodcodes,
            timeframes=self.timeframes,
        )
        for combination in combinations:
            if combination.pop('nowcast'):
                continue
            if combination['prodcode'] != 'r':
                continue
            if combination['timeframe'] != 'f':
                continue
            yield products.CalibratedProduct(**combination)

    def publish_image(self, cascade=False):
        """ Publish to geotiff image for webviewer. """
        publications = list(self.image_publications())

        # if this is the normal operational image, add the previous one to
        # reduce flicker
        if len(publications) == 1:
            publications.append(publications[0].previous())

        images.create_png_for_animated_gif(publications)

    def publish_ftp(self, cascade=False, overwrite=True):
        """ Publish to FTP configured in config. """
        if hasattr(config, 'FTP_HOST'):
            if config.FTP_HOST != '':
                with FtpPublisher() as ftp_publisher:
                    for publication in self.ftp_publications(cascade=cascade):
                        ftp_publisher.publish(product=publication,
                                              overwrite=overwrite)
                logging.info('FTP publishing complete.')
        else:
            logging.warning('FTP not configured, FTP publishing not possible.')
