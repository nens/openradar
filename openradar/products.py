# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

import h5py
import logging
import numpy as np
import os
import shutil

from openradar import config
from openradar import utils
from openradar import scans
from openradar.interpolation import DataLoader, Interpolator


class CopiedProduct(object):
    """ Represents a copy of an aggregate. """

    def __init__(self, datetime):
        self.datetime = datetime

        # determine product paths
        code = config.NOWCAST_PRODUCT_CODE
        self.path = utils.PathHelper(
            basedir=config.NOWCAST_CALIBRATE_DIR,
            code=code,
            template=config.PRODUCT_TEMPLATE,
        ).path(datetime)
        self.ftp_path = os.path.join(code, os.path.basename(self.path))

    def get(self):
        """
        Return h5 dataset opened in read mode.

        Crashes when the file does not exist. This should be catched by caller.
        """
        return h5py.File(self.path, 'r')

    def make(self):
        """ Copy aggregate. """
        source_path = utils.PathHelper(
            basedir=config.NOWCAST_AGGREGATE_DIR,
            code='5min',
            template='{code}_{timestamp}.h5',
        ).path(self.datetime)

        if not os.path.exists(source_path):
            return

        try:
            os.makedirs(os.path.dirname(self.path))
        except Exception:
            pass

        shutil.copy(source_path, self.path)
        logging.info('Create CopiedProduct {}'.format(
            os.path.basename(self.path)
        ))
        logging.debug(self.path)

    def __str__(self):
        return self.path


class CalibratedProduct(object):
    '''
    Depending on the product requested the produce method will create:
    E.g. At 2012-12-18-09:05 the products that can be made at that moment
        depending on the product are:
            real-time           => 2012-12-18-09:05
            near-real-time      => 2012-12-18-08:05
            afterwards          => 2012-12-16-09:05
    '''

    def __init__(self, prodcode, timeframe,
                 datetime, radars=None, declutter=None):
        # Attributes
        self.datetime = datetime
        self.prodcode = prodcode
        self.timeframe = timeframe
        # Derived attributes
        self.radars = config.ALL_RADARS if radars is None else radars
        if declutter is None:
            self.declutter = dict(size=config.DECLUTTER_SIZE,
                                  history=config.DECLUTTER_HISTORY)
        else:
            self.declutter = declutter

        # determine product paths
        code = config.PRODUCT_CODE[self.timeframe][self.prodcode]
        self.path = utils.PathHelper(
            basedir=config.CALIBRATE_DIR,
            code=code,
            template=config.PRODUCT_TEMPLATE,
        ).path(datetime)
        self.ftp_path = os.path.join(code, os.path.basename(self.path))

    def _get_aggregate(self):
        """ Return Aggregate object. """
        return scans.Aggregate(radars=self.radars,
                               datetime=self.datetime,
                               timeframe=self.timeframe,
                               declutter=self.declutter,
                               basedir=config.AGGREGATE_DIR,
                               multiscandir=config.MULTISCAN_DIR,
                               grid=scans.BASEGRID)

    def make(self):
        aggregate = self._get_aggregate()
        aggregate.make()
        metafile = os.path.join(config.MISC_DIR, 'grondstations.csv')
        stations_count = 0
        cal_station_ids = []
        cal_station_coords = []
        cal_station_measurements = []
        data_count = 0

        logging.info('Not calibrating because we stopped doing that.')
        calibration_method = 'None'
        dataloader = DataLoader(metafile=metafile,
                                aggregate=aggregate,
                                timeframe=self.timeframe)
        interpolator = Interpolator(dataloader)
        calibrated_radar = interpolator.precipitation

        self.metadata = dict(dataloader.dataset.attrs)
        utils.convert_to_lists_and_unicode(self.metadata)

        dataloader.dataset.close()
        # Append metadata about the calibration
        self.metadata.update(dict(
            cal_station_ids=cal_station_ids,
            cal_station_coords=cal_station_coords,
            cal_station_measurements=cal_station_measurements,
            cal_stations_count=stations_count,
            cal_data_count=data_count,
            cal_method=calibration_method,
        ))

        calibrated_ma = np.ma.masked_equal(
            calibrated_radar,
            config.NODATAVALUE,
        )

        logging.debug('Setting negative values to 0. Min was: {}'.format(
            calibrated_ma.min()),
        )
        calibrated_ma.data[np.ma.less(calibrated_ma, 0)] = 0

        utils.save_dataset(path=self.path,
                           meta=self.metadata,
                           data=dict(precipitation=calibrated_ma))

        logging.info('Created CalibratedProduct {}'.format(
            os.path.basename(self.path)
        ))
        logging.debug(self.path)

    def get(self):
        try:
            return h5py.File(self.path, 'r')
        except IOError:
            logging.warn(
                'Creating calibrated product {}, because it did not'
                ' exist'.format(self.path)),
            self.make()
        return h5py.File(self.path, 'r')

    def __str__(self):
        return self.path

    def previous(self):
        """
        Return product that comes before this one timewise.

        Only for realtime five minute products.
        """
        return self.__class__(
            prodcode=self.prodcode,
            timeframe=self.timeframe,
            datetime=self.datetime - config.TIMEFRAME_DELTA[self.timeframe],
        )


class ConsistentProduct(object):
    """ Conisitified products are usually created by the consistifier. """

    def __init__(self, datetime, prodcode, timeframe):
        self.datetime = datetime
        self.date = datetime  # Backwards compatible
        self.prodcode = prodcode
        self.product = prodcode  # Backwards compatible
        self.timeframe = timeframe

        # determine product paths
        code = config.PRODUCT_CODE[self.timeframe][self.prodcode]
        self.path = utils.PathHelper(
            basedir=config.CONSISTENT_DIR,
            code=code,
            template=config.PRODUCT_TEMPLATE,
        ).path(datetime)
        self.ftp_path = os.path.join(code, os.path.basename(self.path))

    def get(self):
        """
        Return h5 dataset opened in read mode.

        Crashes when the file does not exist. This should be catched by caller.
        """
        return h5py.File(self.path, 'r')

    @classmethod
    def create(cls, product, factor, consistent_with):
        """
        Return ConsistentProduct.

        Creates a ConsistentProduct from product with data multiplied
        by factor and adds consistent_with to the metadata.
        """
        # Create the consistent product object
        consistent_product = cls(
            datetime=product.datetime,
            prodcode=product.prodcode,
            timeframe=product.timeframe,
        )

        # Create the h5 datafile for it
        with product.get() as h5:
            data = h5['precipitation']
            mask = np.equal(data, config.NODATAVALUE)
            data = dict(precipitation=np.ma.array(data, mask=mask) * factor)
            meta = dict(h5.attrs)
            meta.update(consistent_with=consistent_with)

        utils.convert_to_lists_and_unicode(meta)

        utils.save_dataset(
            data=data,
            meta=meta,
            path=consistent_product.path
        )

        # get() will now work, so return the object.
        filepath = consistent_product.path
        filename = os.path.basename(filepath)
        logging.info('Created ConsistentProduct {}'.format(filename))
        logging.debug('Created ConsistentProduct {}'.format(filepath))
        return consistent_product

    def __str__(self):
        return self.path


class Consistifier(object):
    """
    The products that are updated afterwards with new gaugestations need to
    be consistent with the aggregates of the same date.
    E.g. In the hour 12.00 there are 12 * 5 minute products and 1 one hour
    product. The 12 seperate 5 minutes need add up to the same amount of
    precipitation as the hourly aggregate.

    The consistent products are only necessary for 3 products:
        - 5 minute near-realtime
        - 5 minute afterwards
        - hour near-realtime

    Is a class purily for encapsulation purposes.
    """
    SUB_TIMEFRAME = {'d': 'h', 'h': 'f'}

    @classmethod
    def _reliable(cls, product):
        """
        Return if product enables consistification of other products.
        """
        prodcode, timeframe = product.prodcode, product.timeframe
        if prodcode in ['a', 'u']:
            if timeframe == 'd':
                return True
            if timeframe == 'h' and isinstance(product, ConsistentProduct):
                return True
        if prodcode == 'n' and timeframe == 'h':
            return True
        return False

    @classmethod
    def _subproduct_datetimes(cls, product):
        """ Return datetimes for subproducts of product. """
        amount_of_subproducts = dict(h=12, d=24)[product.timeframe]
        sub_timeframe = cls.SUB_TIMEFRAME[product.timeframe]
        sub_timedelta = config.TIMEFRAME_DELTA[sub_timeframe]
        for i in range(amount_of_subproducts):
            offset = sub_timedelta * (i - amount_of_subproducts + 1)
            yield product.datetime + offset

    @classmethod
    def _subproducts(cls, product):
        """ Return the CalibratedProducts to be consistified with product """
        sub_timeframe = cls.SUB_TIMEFRAME[product.timeframe]
        for pdatetime in cls._subproduct_datetimes(product):
            yield CalibratedProduct(datetime=pdatetime,
                                    prodcode=product.prodcode,
                                    timeframe=sub_timeframe)

    @classmethod
    def _precipitation_from_product(cls, product):
        """ Return precipitation as masked array. """
        with product.get() as h5:
            data = h5['precipitation']
            mask = np.equal(data, config.NODATAVALUE)
            precipitation = np.ma.array(data, mask=mask)
        return precipitation

    @classmethod
    def create_consistent_products(cls, product):
        """ Returns a list of consistent products that were created. """
        consistified_products = []
        if cls._reliable(product):
            # Calculate sum of subproducts
            subproduct_sum = np.zeros(scans.BASEGRID.get_shape())
            for subproduct in cls._subproducts(product):
                spp = cls._precipitation_from_product(subproduct).filled(0)

                # in the past kriging sometimes resulted in NaN values
                if np.isnan(spp).any():
                    logging.warning(
                        "Zeroing NaNs in %s", subproduct.path,
                    )
                    spp[np.isnan(spp)] = 0

                subproduct_sum += spp

            # Calculate factor
            factor = np.ones(scans.BASEGRID.get_shape())
            pp = cls._precipitation_from_product(product).filled(0)
            index = subproduct_sum > 0
            factor[index] = pp[index] / subproduct_sum[index]

            # Create consistent products
            for subproduct in cls._subproducts(product):
                consistified_products.append(
                    ConsistentProduct.create(
                        product=subproduct,
                        factor=factor,
                        consistent_with=os.path.basename(product.path)
                    )
                )
            # Run this method on those products as well, since some
            # consistified products allow for consistent products themselves,
            # For example a.d consistifies a.h which in turn consitifies a.f.
            more_consistified_products = []
            for consistified_product in consistified_products:
                more_consistified_products.extend(
                    cls.create_consistent_products(consistified_product)
                )
            consistified_products.extend(more_consistified_products)
        return consistified_products

    @classmethod
    def get_rescaled_products(cls, product):
        """ Return the rescaled products that are scaled to product. """
        rescaled_products = []
        if cls._reliable(product):
            rescaled_products.extend(
                [ConsistentProduct(datetime=p.datetime,
                                   prodcode=p.prodcode,
                                   timeframe=p.timeframe)
                 for p in cls._subproducts(product)],
            )
        extra_rescaled_products = []
        for rescaled_product in rescaled_products:
            extra_rescaled_products.extend(
                cls.get_rescaled_products(rescaled_product),
            )
        rescaled_products.extend(extra_rescaled_products)
        return rescaled_products
