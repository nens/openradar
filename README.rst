openradar
==========================================

Radar
-----
This repository was made for a project to improve the rain monitoring for 
national precipitation in the Netherlands. The rain forecast and monitoring
was believed to thoroughly be improved with the use of more than just the
two Dutch radar stations:
    * De Bilt (Lat: 52.10168, Lon: 5.17834) and 
    * Den Helder (Lat: 52.95334, 4.79997) 
by using relevant radar stations of the neighbouring countries Belgium and Germany.

The project lives at http://nationaleregenradar.nl

The master script ``bin/master`` organizes and aggregates data (if necessary), 
both radar and gauge (ground stations) data. The products are delivered 
real-time, near-real-time and afterwards. Every product is delivered for
different time-steps: 5 minutes, 1 hour and 24 hours. 

Every 5 minutes data is collected from the different radars and gauge stations. 
Especially rain gauge data is not always delivered for that time interval. The
near-real-time data product thus should give more reliable data as more data
has arrived at that time. The aggregates (hourly and daily) are also used to 
calibrate the 5 minute data.

Installation
------------
Install using system repositories (e.g. apt-get, brew, pacman)::

    $ sudo apt-get install <<EOF
    python-gdal
    python-matplotlib
    python-pandas
    python-psycopg2
    python-rpy2
    python-scipy
    python-tornado
    redis-server
    libgeos-dev
    libhdf5-serial-dev
    libnetcdf-dev
    imagemagick
    # type EOF and press Enter

Then, to install the 'gstat' package, in the R interpreter::
    
    > install.packages('gstat')

The standard buildout deployment::
    
    $ pip install zc.buildout
    $ buildout

Then to setup the radar server production use, for Nelen & Schuurmans
the easiest way is to clone the nens/radar repository as development
package and symlink the necessary configuration files::
    
    $ bin/develop checkout radar
    $ bin/buildout  # Again, yes.
    $ ln -s ../src/radar/misc var/misc
    $ ln -s ../src/radar/radar/productionconfig.py openradar/localconfig.py

Scripts
-------
Scripts can be found in openradar/scripts

Scripts have an option --direct, to run without the task system.
Tasks have an argument --cascade. For most scripts this means creating
tasks for logical next steps. For the publish task, it means 'publish
any rescaled products as well.'

TODO: cover sync* scripts and partial scripts here, too.

Timezone
--------
Timezones:
- The time zones for all of the data is in UTC time.

Clutter filter
--------------
To update the clutter filter, execute this command::
    
    bin/clutter YYYYMMDD-YYYYMMDD -t ./my-clutter-file.h5

Put this file in the misc directory and update DECLUTTER_FILEPATH to
point to this file. The basename is enough, but an absolute path will
probably work, too.

Troubleshooting
---------------
The realtime products are a good indication for the times at which
master execution has not succesfully completed. To get a list of missing
products in the past 7 days run::

    $ bin/repair 7d

To get a hint about which masters to re-run.

Lately, there have been tasks hanging due to difficulties reaching or
writing to a configured share. In that case, try to stop celery, kill
any celery workers and start celery to see if the problem persists::

    $ bin/supervisorctl shutdown

    Actions to kill remaining celery workers...

    $ bin/supervisord

In extreme cases you could purge the task queue, but chances are that
the problem lies not in the tasks itself. It brings a lot of work to
resubmit the lost tasks. Anyway::

    $ bin/celery --app=openradar.tasks.app purge


Cronjobs on production server
-----------------------------

::

    # m    h dom mon dow command
    # availability
    @reboot              /srv/openradar/bin/supervisord
    1      7 *   *   *   /srv/openradar/bin/supervisorctl restart celery
    2      7 *   *   *   /srv/openradar/bin/sync_radar_to_ftp  # repairs missed ftp pubs
    # production and cleanup
    13     * *   *   *   /srv/openradar/bin/cleanup
    */5    * *   *   *   /srv/openradar/bin/master
    43     * *   *   *   /srv/openradar/bin/sync  # synops is last written at about 38!
    # Remove old things
    11     * *   *   *   find /srv/openradar/var/nowcast_multiscan -mmin +59 -delete
    12     * *   *   *   find /srv/openradar/var/nowcast_aggregate -mmin +59 -delete
    13     * *   *   *   find /srv/openradar/var/nowcast_calibrate -mmin +59 -delete
    14     7 *   *   *   find /mnt/fews-g/data-archive/img -mtime +3 -delete


Product table
-------------
This table shows how the products should be calibrated and which products
should be consistent with which other products. *) Delivery can not
be earlier than the aggregated product that the consistent product is
based upon.

::


    Timeframe | Product | Delivery*     | Calibration | Consistent with
    ----------+---------+---------------+-------------+----------------
              |    R    | Immediate     | Corr. Field |
    5 minutes |    N    | 1 hour        | Corr. Field | N - 1 hour
              |    A    | 12 hours      | Corr. Field | A - 1 hour
              |    U    | 30 days       | Corr. Field | U - 1 hour
    ----------+---------+---------------+-------------+----------------
              |    R    | Immediate     | Corr. Field |
     1 hour   |    N    | 1 hour        | Corr. Field |
              |    A    | 12 hours      | Kriging     | A - 1 day
              |    U    | 30 days       | Kriging     | U - 1 day
    ----------+---------+---------------+-------------+----------------
              |    R    | Immediate     | Corr. Field |
      1 day   |    N    | 1 hour        | Corr. Field |
              |    A    | 12 hours      | Kriging     |
              |    U    | 30 days       | Kriging     |

