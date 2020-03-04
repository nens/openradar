# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

from openradar import config
from openradar import gridtools
from openradar import loghelper
from openradar import utils

from osgeo import gdal
from osgeo import gdalconst

from scipy import interpolate

import csv
import datetime
import logging
import numpy as np
import os

loghelper.setup_logging()


class Aggregator(object):

    KEYS = 'X', 'Y', 'NAAM', 'REGIO'

    METHODS = {
        1: 'radar weging [mm/dag]',
        2: 'radar laagste hoek [mm/dag]',
        3: 'radar gewogen hoek [mm/dag]',
    }

    CODES = {
        1: 'p.radar.m1',
        2: 'p.radar.m2',
        3: 'm3',
    }
    
    def __init__(self, datapath, coordspath, outputpath):
        
        coordsdict = {}
        with open(coordspath) as coords:
            coordsreader = csv.DictReader(coords)
            for d in coordsreader:
                coordsdict[d['ID']] = {k.lower(): d[k] for k in self.KEYS}

        self.stations = coordsdict
        self.datapath = datapath
        self.outputpath = outputpath

        self.ids, self.coords = zip(*[(k, (int(v['x']), int(v['y'])))
                                      for k, v in self.stations.items()])


    def _aggregate_radar(self, aggregatedatetime, method):
        
        template = 'aggregate.m{method}_%Y%m%d%H%M%S.{extension}'
        path = os.path.join(
            config.AGGREGATE_DIR,
            aggregatedatetime.strftime(template).format(
                method=method, extension='tif',
            ),
        )
        if os.path.exists(path):
            logging.debug('We have this one in cache: {}'.format(
                os.path.basename(path),
            ))
            return gdal.Open(path)


        logging.info('doing {}'.format(aggregatedatetime))
        phkwargs = dict(
            basedir=config.COMPOSITE_DIR,
            template='{code}_{timestamp}.tif',
        )
        ph = utils.PathHelper(code=self.CODES[method], **phkwargs)

        datetime_start = aggregatedatetime - datetime.timedelta(days=1)
        datetime_stop = aggregatedatetime - datetime.timedelta(minutes=5)

        text = '{}-{}'.format(
            datetime_start.strftime('%Y%m%d%H%M'),
            datetime_stop.strftime('%Y%m%d%H%M'),
        )

        scandatetimes = utils.DateRange(text).iterdatetimes()

        dataset = gdal.GetDriverByName(b'mem').CreateCopy(
            b'', gdal.Open(ph.path(
                datetime.datetime(2011,1,1),
            )),
        )

        rain = np.ma.zeros(gridtools.BaseGrid(dataset).get_shape())
        count = np.zeros(gridtools.BaseGrid(dataset).get_shape())

        for scandatetime in scandatetimes:
            logging.debug('adding {}'.format(scandatetime))
            composite = gdal.Open(ph.path(scandatetime))
            if composite is None:
                logging.warn('No composite found for method {} at {}'.format(
                    method, scandatetime,
                ))
                continue
            ma = gridtools.ds2ma(composite)
            count += ~ma.mask  # Where no mask, we count rain
            rain += ma.filled(0)

        rain /= 12  # Composite unit is mm/hr, but we add every 5 minutes.

        rain.mask = np.less(count, 1)
        dataset.GetRasterBand(1).WriteArray(rain.filled(config.NODATAVALUE))

        gdal.GetDriverByName(b'GTiff').CreateCopy(
            path, dataset, 0, ['COMPRESS=DEFLATE']
        )

        gridtools.RasterLayer(dataset, **utils.rain_kwargs(name='jet')).save(
            path.replace('.tif', '.png'),
        )

        # Adding the counts as tif
        count_dataset = gdal.GetDriverByName(b'gtiff').Create(
            path.replace('.tif', '_count.tif'),
            dataset.RasterXSize, dataset.RasterYSize, 1,
            gdalconst.GDT_UInt16,
        )
        count_dataset.GetRasterBand(1).WriteArray(count)

        return dataset

    def _interpolate(self, dataset):

        x_in, y_in = gridtools.BaseGrid(dataset).get_grid()
        values = gridtools.ds2ma(dataset)
        x_out, y_out = np.array(self.coords).transpose()

        return interpolate.griddata(
            (x_in.reshape(-1), y_in.reshape(-1)),
            values.reshape(-1),
            (x_out, y_out),
            method='linear',
            fill_value=config.NODATAVALUE,
        )


    def main(self):

        data = open(self.datapath)
        output = open(self.outputpath, 'w')

        outputwriter = csv.DictWriter(
            output,
            (
                'station',
                'type',
                'waarde station [mm/dag]',
                self.METHODS[1],
                self.METHODS[2],
                self.METHODS[3],
                'datum',
            )
        )
        outputwriter.writeheader()

        datareader = csv.DictReader(data)
        datareader.next()  # Skip the value type row

        for d in datareader:
            result = {}
            aggregatedatetime = datetime.datetime.strptime(
                d[''], '%Y-%m-%d %H:%M:%S',
            )
            logging.debug(aggregatedatetime)
            for method in self.METHODS:
                aggregate = self._aggregate_radar(
                    aggregatedatetime=aggregatedatetime, method=method,
                )
                result[method] = self._interpolate(aggregate)

            for i in range(len(self.stations)):
                id = self.ids[i]
                try:
                    outputwriter.writerow({
                        'station': self.stations[id]['naam'],
                        'type': self.stations[id]['regio']
                                   .replace("'", "")
                                   .replace('&', 'en'),
                        'waarde station [mm/dag]': d[id],
                        self.METHODS[1]: result[1][i],
                        self.METHODS[2]: result[2][i],
                        self.METHODS[3]: result[3][i],
                        'datum': aggregatedatetime.strftime('%Y%m%d')
                    })
                except KeyError as e:
                    logging.error(e)
                        

        data.close()
        output.close()
