#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.rst.

import logging
import sys

from openradar import arguments
from openradar import files


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    argument = arguments.Argument()
    parser = argument.parser(['source_dir'])
    kwargs = vars(parser.parse_args())
    files.organize_from_path(path=kwargs['source_dir'])
