# Below are some sections copied from wradlib-1.5.0/io/radolan.py
# Copyright (c) 2011-2018, wradlib developers.
# Distributed under the MIT License. See LICENSE.txt for more info.

import io

from datetime import datetime as Datetime
from datetime import timezone

import re

import numpy as np

# current DWD file naming pattern (2008) for example:
# raa00-dx_10488-200608050000-drs---bin
dwdpattern = re.compile('raa..-(..)[_-]([0-9]{5})-([0-9]*)-(.*?)---bin')


def _get_timestamp_from_filename(filename):
    """Helper function doing the actual work of get_dx_timestamp"""
    time = dwdpattern.search(filename).group(3)
    if len(time) == 10:
        time = '20' + time
    return Datetime.strptime(time, '%Y%m%d%H%M')


def get_dx_timestamp(name):
    """Converts a dx-timestamp (as part of a dx-product filename) to a
    python datetime.object.

    Parameters
    ----------
    name : string
        representing a DWD product name

    Returns
    -------
    time : timezone-aware datetime.datetime object
    """
    return _get_timestamp_from_filename(name).replace(timezone.utc)


def unpack_dx(raw):
    """function removes DWD-DX-product bit-13 zero packing"""
    # data is encoded in the first 12 bits
    data = 4095
    # the zero compression flag is bit 13
    flag = 4096

    beam = []

    # # naive version
    # # 49193 function calls in 0.772 CPU seconds
    # # 20234 function calls in 0.581 CPU seconds
    # for item in raw:
    #     if item & flag:
    #         beam.extend([0]* (item & data))
    #     else:
    #         beam.append(item & data)

    # performance version - hopefully
    # 6204 function calls in 0.149 CPU seconds

    # get all compression cases
    flagged = np.where(raw & flag)[0]

    # if there is no zero in the whole data, we can return raw as it is
    if flagged.size == 0:
        assert raw.size == 128
        return raw

    # everything until the first flag is normal data
    beam.extend(raw[0:flagged[0]])

    # iterate over all flags except the last one
    for this, nxt in zip(flagged[:-1], flagged[1:]):
        # create as many zeros as there are given within the flagged
        # byte's data part
        beam.extend([0] * (raw[this] & data))
        # append the data until the next flag
        beam.extend(raw[this + 1:nxt])

    # process the last flag
    # add zeroes
    beam.extend([0] * (raw[flagged[-1]] & data))

    # add remaining data
    beam.extend(raw[flagged[-1] + 1:])

    # return the data
    return np.array(beam)


def parse_dx_header(header):
    """Internal function to retrieve and interpret the ASCII header of a DWD
    DX product file.

    Parameters
    ----------
    header : string
        string representation of DX header
    """
    # empty container
    out = {}
    # RADOLAN product type def
    out["producttype"] = header[0:2]
    # time stamp from file header as Python datetime object
    out["datetime"] = Datetime.strptime(
        header[2:8] + header[13:17] + "00",
        "%d%H%M%m%y%S"
    )
    # Make it aware of its time zone (UTC)
    out["datetime"] = out["datetime"].replace(tzinfo=timezone.utc)
    # radar location ID (always 10000 for composites)
    out["radarid"] = header[8:13]
    pos_by = header.find("BY")
    pos_vs = header.find("VS")
    pos_co = header.find("CO")
    pos_cd = header.find("CD")
    pos_cs = header.find("CS")
    pos_ep = header.find("EP")
    pos_ms = header.find("MS")

    out['bytes'] = int(header[pos_by + 2:pos_by + 7])
    out['version'] = header[pos_vs + 2:pos_vs + 4]
    out['cluttermap'] = int(header[pos_co + 2:pos_co + 3])
    out['dopplerfilter'] = int(header[pos_cd + 2:pos_cd + 3])
    out['statfilter'] = int(header[pos_cs + 2:pos_cs + 3])
    out['elevprofile'] = [float(header[pos_ep + 2 + 3 * i:pos_ep + 2 + 3 * (i + 1)]) for i in range(8)]  # noqa
    out['message'] = header[pos_ms + 5:pos_ms + 5 + int(header[pos_ms + 2:pos_ms + 5])]  # noqa

    return out


def read_dx(filename):
    """Data reader for German Weather Service DX product raw radar data files.

    This product uses a simple algorithm to compress zero values to reduce data
    file size.

    Notes
    -----
    While the format appears to be well defined, there have been reports on DX-
    files that seem to produce errors. e.g. while one file usually contains a
    360 degree by 128 1km range bins, there are files, that contain 361 beams.
    Also, while usually azimuths are stored monotonously in ascending order,
    this is not guaranteed by the format. This routine does not (yet) check
    for this and directly returns the data in the order found in the file.
    If you are in doubt, check the 'azim' attribute.
    Be aware that this function does no extensive checking on its output.
    If e.g. beams contain different numbers of range bins, the resulting data
    will not be a 2-D array but a 1-D array of objects, which will most
    probably break calling code. It was decided to leave the handling of these
    (hopefully) rare events to the user, who might still be able to retrieve
    some reasonable data, instead of raising an exception, making it impossible
    to get any data from a file containing errors.

    Parameters
    ----------
    filename : string
        binary file of DX raw data

    Returns
    -------
    data : :func:`numpy:numpy.array`
        of image data [dBZ]; shape (360,128)
    attributes : dict
        dictionary of attributes - currently implemented keys:

        - 'azim' - azimuths np.array of shape (360,)
        - 'elev' - elevations (1 per azimuth); np.array of shape (360,)
        - 'clutter' - clutter mask; boolean array of same shape as `data`;
          corresponds to bit 15 set in each dataset.
        - 'bytes'- the total product length (including header).
          Apparently, this value may be off by one byte for unknown reasons
        - 'version'- a product version string - use unknown
        - 'cluttermap' - number of the (DWD internal) cluttermap used
        - 'dopplerfilter' - number of the dopplerfilter used (DWD internal)
        - 'statfilter' - number of a statistical filter used (DWD internal)
        - 'elevprofile' - as stated in the format description, this list
          indicates the elevations in the eight 45 degree sectors. These
          sectors need not start at 0 degrees north, so it is advised to
          explicitly evaluate the `elev` attribute, if elevation information
          is needed.
        - 'message' - additional text stored in the header.

    Examples
    --------
    See :ref:`/notebooks/fileio/wradlib_reading_dx.ipynb`.
    """

    azimuthbitmask = 2 ** (14 - 1)
    databitmask = 2 ** (13 - 1) - 1
    clutterflag = 2 ** 15
    dataflag = 2 ** 13 - 1

    f = open(filename, 'rb')

    # header string for later processing
    header = ''
    atend = False

    # read header
    while True:
        mychar = f.read(1)
        # 0x03 signals the end of the header but sometimes there might be
        # an additional 0x03 char after that

        if mychar == b'\x03':
            atend = True
        if mychar != b'\x03' and atend:
            break
        header += str(mychar.decode())

    attrs = parse_dx_header(header)

    # position file at end of header
    f.seek(len(header))

    # read number of bytes as declared in the header
    # intermediate fix:
    # if product length is uneven but header is even (e.g. because it has two
    # chr(3) at the end, read one byte less
    buflen = attrs['bytes'] - len(header)
    if (buflen % 2) != 0:
        # make sure that this is consistent with our assumption
        # i.e. contact DWD again, if DX files show up with uneven byte lengths
        # *and* only one 0x03 character
        # assert header[-2] == chr(3)
        buflen -= 1

    buf = f.read(buflen)
    # we can interpret the rest directly as a 1-D array of 16 bit unsigned ints
    raw = np.frombuffer(buf, dtype='uint16')

    # reading finished, close file, but only if we opened it.
    if isinstance(f, io.IOBase):
        f.close()

    # a new ray/beam starts with bit 14 set
    # careful! where always returns its results in a tuple, so in order to get
    # the indices we have to retrieve element 0 of this tuple
    newazimuths = np.where(raw == azimuthbitmask)[0]  # Thomas kontaktieren!

    # for the following calculations it is necessary to have the end of the
    # data as the last index
    newazimuths = np.append(newazimuths, len(raw))

    # initialize our list of rays/beams
    beams = []
    # initialize our list of elevations
    elevs = []
    # initialize our list of azimuths
    azims = []

    # iterate over all beams
    for i in range(newazimuths.size - 1):
        # unpack zeros
        beam = unpack_dx(raw[newazimuths[i] + 3:newazimuths[i + 1]])
        beams.append(beam)
        elevs.append((raw[newazimuths[i] + 2] & databitmask) / 10.)
        azims.append((raw[newazimuths[i] + 1] & databitmask) / 10.)

    beams = np.array(beams)

    # attrs =  {}
    attrs['elev'] = np.array(elevs)
    attrs['azim'] = np.array(azims)
    attrs['clutter'] = (beams & clutterflag) != 0

    # converting the DWD rvp6-format into dBZ data and return as numpy array
    # together with attributes
    return (beams & dataflag) * 0.5 - 32.5, attrs


def get_radolan_header_token():
    """Return array with known header token of radolan composites

    Returns
    -------
    head : dict
        with known header token, value set to None
    """
    head = {'BY': None, 'VS': None, 'SW': None, 'PR': None,
            'INT': None, 'GP': None, 'MS': None, 'LV': None,
            'CS': None, 'MX': None, 'BG': None, 'ST': None,
            'VV': None, 'MF': None, 'QN': None, 'VR': None,
            'U': None}
    return head


def get_radolan_header_token_pos(header):
    """Get Token and positions from DWD radolan header

    Parameters
    ----------
    header : string
        (ASCII header)

    Returns
    -------
    head : dictionary
        with found header tokens and positions
    """

    head_dict = get_radolan_header_token()

    for token in head_dict.keys():
        d = header.rfind(token)
        if d > -1:
            head_dict[token] = d
    head = {}

    result_dict = {}
    result_dict.update((k, v) for k, v in head_dict.items() if v is not None)
    for k, v in head_dict.items():
        if v is not None:
            start = v + len(k)
            filt = [x for x in result_dict.values() if x > v]
            if filt:
                stop = min(filt)
            else:
                stop = len(header)
            head[k] = (start, stop)
        else:
            head[k] = v

    return head


def parse_dwd_composite_header(header):
    """Parses the ASCII header of a DWD quantitative composite file

    Parameters
    ----------
    header : string
        (ASCII header)

    Returns
    -------
    output : dictionary
        of metadata retrieved from file header
    """
    # empty container
    out = {}

    # RADOLAN product type def
    out["producttype"] = header[0:2]
    # file time stamp as Python datetime object
    out["datetime"] = Datetime.strptime(
        header[2:8] + header[13:17] + "00",
        "%d%H%M%m%y%S",
    )
    # radar location ID (always 10000 for composites)
    out["radarid"] = header[8:13]

    # get dict of header token with positions
    head = get_radolan_header_token_pos(header)
    # iterate over token and fill output dict accordingly
    # for k, v in head.iteritems():
    for k, v in head.items():
        if v:
            if k == 'BY':
                out['datasize'] = int(header[v[0]:v[1]]) - len(header) - 1
            if k == 'VS':
                out["maxrange"] = {0: "100 km and 128 km (mixed)",
                                   1: "100 km",
                                   2: "128 km",
                                   3: "150 km"}.get(int(header[v[0]:v[1]]),
                                                    "100 km")
            if k == 'SW':
                out["radolanversion"] = header[v[0]:v[1]].strip()
            if k == 'PR':
                out["precision"] = float('1' + header[v[0]:v[1]].strip())
            if k == 'INT':
                out["intervalseconds"] = int(header[v[0]:v[1]]) * 60
            if k == 'U':
                out["intervalunit"] = int(header[v[0]:v[1]])
                if out["intervalunit"] == 1:
                    out["intervalseconds"] *= 1440
            if k == 'GP':
                dimstrings = header[v[0]:v[1]].strip().split("x")
                out["nrow"] = int(dimstrings[0])
                out["ncol"] = int(dimstrings[1])
            if k == 'BG':
                dimstrings = header[v[0]:v[1]]
                dimstrings = (dimstrings[:int(len(dimstrings) / 2)],
                              dimstrings[int(len(dimstrings) / 2):])
                out["nrow"] = int(dimstrings[0])
                out["ncol"] = int(dimstrings[1])
            if k == 'LV':
                lv = header[v[0]:v[1]].split()
                out['nlevel'] = np.int(lv[0])
                out['level'] = np.array(lv[1:]).astype('float')
            if k == 'MS':
                locationstring = (header[v[0]:].strip().split("<")[1].
                                  split(">")[0])
                out["radarlocations"] = locationstring.split(",")
            if k == 'ST':
                locationstring = (header[v[0]:].strip().split("<")[1].
                                  split(">")[0])
                out["radardays"] = locationstring.split(",")
            if k == 'CS':
                out['indicator'] = {0: "near ground level",
                                    1: "maximum",
                                    2: "tops"}.get(int(header[v[0]:v[1]]))
            if k == 'MX':
                out['imagecount'] = int(header[v[0]:v[1]])
            if k == 'VV':
                out['predictiontime'] = int(header[v[0]:v[1]])
            if k == 'MF':
                out['moduleflag'] = int(header[v[0]:v[1]])
            if k == 'QN':
                out['quantification'] = int(header[v[0]:v[1]])
            if k == 'VR':
                out['reanalysisversion'] = header[v[0]:v[1]].strip()
    return out
