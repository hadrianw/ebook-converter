import functools
import mimetypes
import os
import re
import urllib.parse

from ebook_converter.customize.conversion import InputFormatPlugin
from ebook_converter.customize.conversion import OptionRecommendation
from ebook_converter.utils.localization import get_lang
from ebook_converter.utils.filenames import ascii_filename
from ebook_converter.utils.imghdr import what


def sanitize_file_name(x):
    ans = re.sub(r'\s+', ' ', re.sub(r'[?&=;#]', '_',
                                     ascii_filename(x))).strip().rstrip('.')
    ans, ext = ans.rpartition('.')[::2]
    return (ans.strip() + '.' + ext.strip()).rstrip('.')


class HTMLInput(InputFormatPlugin):

    name = 'HTML Input'
    author = 'Kovid Goyal'
    description = 'Convert HTML and OPF files to an OEB'
    file_types = {'opf', 'html', 'htm', 'xhtml', 'xhtm', 'shtm', 'shtml'}
    commit_name = 'html_input'

    options = {
        OptionRecommendation(name='breadth_first',
            recommended_value=False, level=OptionRecommendation.LOW,
            help='Traverse links in HTML files breadth first. Normally, '
                    'they are traversed depth first.'
        ),

        OptionRecommendation(name='max_levels',
            recommended_value=5, level=OptionRecommendation.LOW,
            help='Maximum levels of recursion when following links in '
                   'HTML files. Must be non-negative. 0 implies that no '
                   'links in the root HTML file are followed. Default is '
                   '%default.'
        ),

        OptionRecommendation(name='dont_package',
            recommended_value=False, level=OptionRecommendation.LOW,
            help='Normally this input plugin re-arranges all the input '
                'files into a standard folder hierarchy. Only use this option '
                'if you know what you are doing as it can result in various '
                'nasty side effects in the rest of the conversion pipeline.'
        ),

    }

    def convert(self, stream, opts, file_ext, log,
                accelerators):
        basedir = os.getcwd()
        self.opts = opts

        fname = None
        if hasattr(stream, 'name'):
            basedir = os.path.dirname(stream.name)
            fname = os.path.basename(stream.name)

        if file_ext != 'opf':
            if opts.dont_package:
                raise ValueError('The --dont-package option is not supported for an HTML input file')
            from ebook_converter.ebooks.metadata.html import get_metadata
            mi = get_metadata(stream)
            if fname:
                from ebook_converter.ebooks.metadata.meta import metadata_from_filename
                fmi = metadata_from_filename(fname)
                fmi.smart_update(mi)
                mi = fmi
            oeb = self.create_oebbook(stream.name, basedir, opts, log, mi)
            return oeb

        from ebook_converter.ebooks.conversion.plumber import create_oebbook
        return create_oebbook(log, stream.name, opts,
                encoding=opts.input_encoding)

    def create_oebbook(self, htmlpath, basedir, opts, log, mi):
        import uuid
        from ebook_converter.ebooks.conversion.plumber import create_oebbook
        from ebook_converter.ebooks.oeb.base import (DirContainer,
            rewrite_links, urlnormalize, BINARY_MIME, OEB_STYLES,
            xpath, urlquote)
        from ebook_converter.ebooks.oeb.transforms.metadata import \
            meta_info_to_oeb_metadata
        from ebook_converter.ebooks.html.input import get_filelist
        from ebook_converter.ebooks.metadata import string_to_authors
        from ebook_converter.utils.localization import canonicalize_lang
        import css_parser, logging
        css_parser.log.setLevel(logging.WARN)
        self.OEB_STYLES = OEB_STYLES
        oeb = create_oebbook(log, None, opts, self,
                encoding=opts.input_encoding, populate=False)
        self.oeb = oeb

        metadata = oeb.metadata
        meta_info_to_oeb_metadata(mi, metadata, log)
        if not metadata.language:
            l = canonicalize_lang(getattr(opts, 'language', None))
            if not l:
                oeb.logger.warning('Language not specified')
                l = get_lang().replace('_', '-')
            metadata.add('language', l)
        if not metadata.creator:
            a = getattr(opts, 'authors', None)
            if a:
                a = string_to_authors(a)
            if not a:
                oeb.logger.warning('Creator not specified')
                a = [self.oeb.translate('Unknown')]
            for aut in a:
                metadata.add('creator', aut)
        if not metadata.title:
            oeb.logger.warning('Title not specified')
            metadata.add('title', self.oeb.translate('Unknown'))
        bookid = str(uuid.uuid4())
        metadata.add('identifier', bookid, id='uuid_id', scheme='uuid')
        for ident in metadata.identifier:
            if 'id' in ident.attrib:
                self.oeb.uid = metadata.identifier[0]
                break

        filelist = get_filelist(htmlpath, basedir, opts, log)
        filelist = [f for f in filelist if not f.is_binary]
        htmlfile_map = {}
        for f in filelist:
            path = f.path
            oeb.container = DirContainer(os.path.dirname(path), log,
                    ignore_opf=True)
            bname = os.path.basename(path)
            id, href = oeb.manifest.generate(id='html', href=sanitize_file_name(bname))
            htmlfile_map[path] = href
            item = oeb.manifest.add(id, href, 'text/html')
            if path == htmlpath and '%' in path:
                bname = urlquote(bname)
            item.html_input_href = bname
            oeb.spine.add(item, True)

        self.added_resources = {}
        self.log = log
        self.log.info('Normalizing filename cases')
        for path, href in htmlfile_map.items():
            self.added_resources[path] = href
        self.urlnormalize, self.DirContainer = urlnormalize, DirContainer
        self.urldefrag = urllib.parse.urldefrag
        self.BINARY_MIME = BINARY_MIME

        self.log.info('Rewriting HTML links')
        for f in filelist:
            path = f.path
            dpath = os.path.dirname(path)
            oeb.container = DirContainer(dpath, log, ignore_opf=True)
            href = htmlfile_map[path]
            try:
                item = oeb.manifest.hrefs[href]
            except KeyError:
                item = oeb.manifest.hrefs[urlnormalize(href)]
            rewrite_links(item.data,
                          functools.partial(self.resource_adder, base=dpath))

        for item in oeb.manifest.values():
            if item.media_type in self.OEB_STYLES:
                dpath = None
                for path, href in self.added_resources.items():
                    if href == item.href:
                        dpath = os.path.dirname(path)
                        break
                css_parser.replaceUrls(item.data,
                        functools.partial(self.resource_adder, base=dpath))

        toc = self.oeb.toc
        self.oeb.auto_generated_toc = True
        titles = []
        headers = []
        for item in self.oeb.spine:
            if not item.linear:
                continue
            html = item.data
            title = ''.join(xpath(html, '/h:html/h:head/h:title/text()'))
            title = re.sub(r'\s+', ' ', title.strip())
            if title:
                titles.append(title)
            headers.append('(unlabled)')
            for tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'strong'):
                expr = '/h:html/h:body//h:%s[position()=1]/text()'
                header = ''.join(xpath(html, expr % tag))
                header = re.sub(r'\s+', ' ', header.strip())
                if header:
                    headers[-1] = header
                    break
        use = titles
        if len(titles) > len(set(titles)):
            use = headers
        for title, item in zip(use, self.oeb.spine):
            if not item.linear:
                continue
            toc.add(title, item.href)

        oeb.container = DirContainer(os.getcwd(), oeb.log, ignore_opf=True)
        return oeb

    def link_to_local_path(self, link_, base=None):
        from ebook_converter.ebooks.html.input import Link
        if not isinstance(link_, str):
            try:
                link_ = link_.decode('utf-8', 'error')
            except:
                self.log.warning('Failed to decode link %r. Ignoring', link_)
                return None, None
        try:
            l = Link(link_, base if base else os.getcwd())
        except:
            self.log.exception('Failed to process link: %r', link_)
            return None, None
        if l.path is None:
            # Not a local resource
            return None, None
        link = l.path.replace('/', os.sep).strip()
        frag = l.fragment
        if not link:
            return None, None
        return link, frag

    def resource_adder(self, link_, base=None):
        link, frag = self.link_to_local_path(link_, base=base)
        if link is None:
            return link_
        try:
            if base and not os.path.isabs(link):
                link = os.path.join(base, link)
            link = os.path.abspath(link)
        except:
            return link_
        if not os.access(link, os.R_OK):
            return link_
        if os.path.isdir(link):
            self.log.warning(link_, 'is a link to a directory. Ignoring.')
            return link_
        if link not in self.added_resources:
            bhref = os.path.basename(link)
            id, href = self.oeb.manifest.generate(id='added', href=sanitize_file_name(bhref))
            guessed = mimetypes.guess_type(href)[0]
            media_type = guessed or self.BINARY_MIME
            if media_type == 'text/plain':
                self.log.warning('Ignoring link to text file %r', link_)
                return None
            if media_type == self.BINARY_MIME:
                # Check for the common case, images
                try:
                    img = what(link)
                except EnvironmentError:
                    pass
                else:
                    if img:
                        media_type = mimetypes.guess_type('dummy.'+img)[0] or self.BINARY_MIME

            self.oeb.log.debug('Added %s', link)
            self.oeb.container = self.DirContainer(os.path.dirname(link),
                    self.oeb.log, ignore_opf=True)
            # Load into memory
            item = self.oeb.manifest.add(id, href, media_type)
            # bhref refers to an already existing file. The read() method of
            # DirContainer will call unquote on it before trying to read the
            # file, therefore we quote it here.
            # XXX(gryf): why the heck it was changed to bytes?
            item.html_input_href = urllib.parse.quote(bhref)
            if guessed in self.OEB_STYLES:
                item.override_css_fetch = functools.partial(
                        self.css_import_handler, os.path.dirname(link))
            item.data
            self.added_resources[link] = href

        nlink = self.added_resources[link]
        if frag:
            nlink = '#'.join((nlink, frag))
        return nlink

    def css_import_handler(self, base, href):
        link, frag = self.link_to_local_path(href, base=base)
        if link is None or not os.access(link, os.R_OK) or os.path.isdir(link):
            return (None, None)
        try:
            with open(link, 'rb') as f:
                raw = f.read().decode('utf-8', 'replace')
            raw = self.oeb.css_preprocessor(raw, add_namespace=False)
        except:
            self.log.exception('Failed to read CSS file: %r', link)
            return (None, None)
        return (None, raw)
