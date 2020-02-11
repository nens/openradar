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


Development installation
------------------------

For development, you can use a docker-compose setup::

    $ docker-compose build --build-arg uid=`id -u` --build-arg gid=`id -g` lib
    $ docker-compose up --no-start
    $ docker-compose start
    $ docker-compose exec lib bash

Create & activate a virtualenv::

    (docker)$ virtualenv --system-site-packages .venv
    (docker)$ source bin/activate

Install stuff and run the tests::

    (docker)(virtualenv)$ pip install -r requirements.txt --index-url https://packages.lizard.net
    (docker)(virtualenv)$ pytest

Update packages::
    
    (docker)$ rm -rf .venv
    (docker)$ virtualenv --system-site-packages .venv
    (docker)$ source bin/activate
    (docker)(virtualenv)$ pip install -e .[test] --index-url https://packages.lizard.net
    (docker)(virtualenv)$ pip freeze > requirements.txt


Server installation
-------------------

Global dependencies (apt)::

    git
    imagemagick
    libgdal-dev
    libhdf5-serial-dev
    locales
    python3-pip
    python3-rpy2
    redis-server

Then, to install the 'gstat' package, in the R interpreter::
    
    > install.packages('gstat')

Finally, the python part::
    $ sudo pip3 install --upgrade pip virtualenv
    $ virtualenv --system-site-packages .venv
    $ source bin/activate
    (virtualenv)$ pip install -r requirements.txt --index-url https://packages.lizard.net


Use symbolic links to link to external var/misc and localconfig files.

# TODO running celery on server and in development


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
    # m  h      dom mon dow command
    */5    * *   *   *   /srv/openradar/bin/master
    13     * *   *   *   /srv/openradar/bin/cleanup
    43     * *   *   *   /srv/openradar/bin/sync  # only Evap and Eps
    */10   * *   *   *   /srv/openradar/bin/sync_ground

    # Remove old things
    11     * *   *   *   find /srv/openradar/var/nowcast_multiscan -mmin +59 -delete
    12     * *   *   *   find /srv/openradar/var/nowcast_aggregate -mmin +59 -delete
    13     * *   *   *   find /srv/openradar/var/nowcast_calibrate -mmin +59 -delete
    14     7 *   *   *   find /mnt/fews-g/data-archive/img -mtime +3 -delete

    # extra cleanups (heavy KNMI volumes)
    # m    h dom mon dow command
    13     * *   *   *   find /119-fs-c01/regenrprod/radar/NL61 -mtime +7 -delete
    13     * *   *   *   find /119-fs-c01/regenrprod/radar/NL62 -mtime +7 -delete


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

