# vim:fileencoding=utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

try:
    from time import monotonic
except ImportError:
    from ebook_converter.constants import plugins

    monotonicp, err = plugins['monotonic']
    if err:
        raise RuntimeError('Failed to load the monotonic module with error: ' + err)
    monotonic = monotonicp.monotonic
    del monotonicp, err
