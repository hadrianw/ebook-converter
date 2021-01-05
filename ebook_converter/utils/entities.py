"""
Misc util functions for converting HTML/XML entites to unicode.
"""
import html
import functools
import re

from ebook_converter.ebooks.html_entities import html5_entities


ENT_PAT = re.compile(r'&(\S+?);')


def entity_to_unicode(match, exceptions=[], encoding='cp1252',
                      result_exceptions={}):
    """
    :param match: A match object such that '&'+match.group(1)';' is the entity.

    :param exceptions: A list of entities to not convert (Each entry is the
                       name of the entity, for e.g. 'apos' or '#1234'

    :param encoding: The encoding to use to decode numeric entities between
                     128 and 256. If None, the Unicode UCS encoding is used.
                     A common encoding is cp1252.

    :param result_exceptions: A mapping of characters to entities. If the
                              result is in result_exceptions,
                              result_exception[result] is returned instead.
                              Convenient way to specify exception for things
                              like < or > that can be specified by various
                              actual entities.
    """

    def my_unichr(num):
        try:
            return chr(num)
        except (ValueError, OverflowError):
            return '?'

    def check(ch):
        return result_exceptions.get(ch, ch)

    ent = match.group(1)
    if ent in exceptions:
        return '&'+ent+';'
    # squot is generated by some broken CMS software
    if ent in {'apos', 'squot'}:
        return check("'")
    if ent == 'hellips':
        ent = 'hellip'
    if ent.startswith('#'):
        try:
            if ent[1] in ('x', 'X'):
                num = int(ent[2:], 16)
            else:
                num = int(ent[1:])
        except Exception:
            return '&'+ent+';'
        if encoding is None or num > 255:
            return check(my_unichr(num))
        try:
            return check(bytes(bytearray((num,))).decode(encoding))
        except UnicodeDecodeError:
            return check(my_unichr(num))
    try:
        return check(html5_entities[ent])
    except KeyError:
        pass
    try:
        return check(my_unichr(html.entities.name2codepoint[ent]))
    except KeyError:
        return '&'+ent+';'


xml_entity_to_unicode = functools.partial(entity_to_unicode,
                                          result_exceptions={'"': '&quot;',
                                                             "'": '&apos;',
                                                             '<': '&lt;',
                                                             '>': '&gt;',
                                                             '&': '&amp;'})


def replace_entities(raw, encoding='cp1252'):
    return ENT_PAT.sub(functools.partial(entity_to_unicode, encoding=encoding),
                       raw)


def xml_replace_entities(raw, encoding='cp1252'):
    return ENT_PAT.sub(functools.partial(xml_entity_to_unicode,
                                         encoding=encoding), raw)


def prepare_string_for_xml(raw, attribute=False):
    raw = ENT_PAT.sub(entity_to_unicode, raw)
    raw = raw.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    if attribute:
        raw = raw.replace('"', '&quot;').replace("'", '&apos;')
    return raw
