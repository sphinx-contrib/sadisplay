# -*- coding: utf-8 -*-
import os
import sys
import logging
import subprocess
from errno import ENOENT

try:
    from hashlib import sha1
except ImportError:  # Python<2.5
    from sha import sha as sha1  # pyflakes:ignore

from docutils.parsers.rst import Directive
from docutils.parsers.rst import directives
from docutils import nodes

from sphinx.errors import SphinxWarning, SphinxError, ExtensionError
from sphinx.util.osutil import ensuredir

import sadisplay

log = logging.getLogger(__name__)


def warn(self, message):
    method = getattr(self.builder, 'warn', None)
    method = method or getattr(self, 'warn', None)
    method = method or log.warning
    method(message)


class RendererError(SphinxError):
    pass


class SaNode(nodes.General, nodes.Element):
    pass


class SadisplayDirective(Directive):
    """Directive to display SQLAlchemy models

    Example::

        .. sadisplay::
           :module: myapp.model

    """
    has_content = False
    option_spec = {
        'alt': directives.unchanged,
        'link': directives.flag,
        'render': directives.unchanged,
        'module': directives.unchanged,
        'include': directives.unchanged,
        'exclude': directives.unchanged,
    }

    def run(self):
        node = SaNode()
        node['alt'] = self.options.get('alt', None)
        node['link'] = True if 'link' in self.options else False
        node['render'] = self.options.get('render', None)

        def tolist(val):
            if val:
                return list(map(lambda i: i.strip(), val.split(',')))
            return []

        node['module'] = tolist(self.options.get('module', ''))
        node['include'] = tolist(self.options.get('include', None))
        node['exclude'] = tolist(self.options.get('exclude', None))

        if node['include'] and node['exclude']:
            raise SphinxWarning('sadisplay directive error - \
                    both defined :include: and :exclude:')

        return [node]


def generate_name(self, content):
    key = sha1(content.encode('utf-8')).hexdigest()
    fname = 'sadisplay-%s.png' % key
    imgpath = getattr(self.builder, 'imgpath', None)
    if imgpath:
        return ('/'.join((self.builder.imgpath, fname)),
                os.path.join(self.builder.outdir, '_images', fname))
    else:
        return fname, os.path.join(self.builder.outdir, fname)


def generate_plantuml_args(self):
    if isinstance(self.builder.config.plantuml, str):
        args = [self.builder.config.plantuml]
    else:
        args = list(self.builder.config.plantuml)
    args.extend('-pipe -charset utf-8'.split())
    return args


def generate_graphviz_args(self):
    if isinstance(self.builder.config.graphviz, str):
        args = [self.builder.config.graphviz]
    else:
        args = list(self.builder.config.graphviz)
    return args


def render_image(self, content, command):
    refname, outfname = generate_name(self, content)
    if os.path.exists(outfname):
        return refname  # don't regenerate
    ensuredir(os.path.dirname(outfname))
    f = open(outfname, 'wb')
    try:
        try:
            p = subprocess.Popen(
                command,
                stdout=f,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE)
        except OSError as err:
            if err.errno != ENOENT:
                raise
            raise RendererError('command %r cannot be run' % command)
        serr = p.communicate(content.encode('utf-8'))[1]
        if p.returncode != 0:
            raise RendererError('error while running %r\n\n' % command + serr)
        return refname
    finally:
        f.close()


def render(self, node):

    all_names = []

    for module_name in node['module']:
        __import__(module_name, globals(), locals())
        module = sys.modules[module_name]

        for attr in dir(module):
            try:
                m = getattr(module, attr)

                # !!!
                # Ugly hack
                repr(m)  # without this statement - exception raises
                # any ideas?

                all_names.append(m)
            except:
                pass

    names = []

    if node['exclude']:
        for i in all_names:
            try:
                if i.__name__ not in node['exclude']:
                    names.append(i)
            except AttributeError:
                pass

    elif node['include']:
        for i in all_names:
            try:
                if i.__name__ in node['include']:
                    names.append(i)
            except AttributeError:
                pass

    else:
        names = all_names

    desc = sadisplay.describe(names)

    render = node['render'] or self.builder.config.sadisplay_default_render

    if render == 'plantuml':
        content = sadisplay.plantuml(desc)
        command = generate_plantuml_args(self)
    elif render == 'graphviz':
        content = sadisplay.dot(desc)
        command = generate_graphviz_args(self)

    return render_image(self, content, command)


def html_visit(self, node):
    try:
        refname = render(self, node)
    except Exception as err:
        log.exception(err)
        warn(self, 'sadisplay render error: %s' % err)
        raise nodes.SkipNode
    self.body.append(self.starttag(node, 'p', CLASS='sadisplay'))

    if node['link']:
        template = '<a href="%s">%s</a>\n'
    else:
        template = '<img src="%s" alt="%s" />\n'

    self.body.append(template % (self.encode(refname),
                                 self.encode(node['alt'] or node['module'])))

    self.body.append('</p>\n')
    raise nodes.SkipNode


def latex_visit(self, node):
    try:
        refname = render(self, node)
    except Exception as err:
        warn(self, 'sadisplay render error: %s' % err)
        raise nodes.SkipNode
    self.body.append('\\includegraphics{%s}' % self.encode(refname))
    raise nodes.SkipNode


def setup(app):

    try:
        app.add_config_value('plantuml', [], False)
    except ExtensionError:
        pass

    try:
        app.add_config_value('graphviz', [], False)
    except ExtensionError:
        pass

    app.add_config_value('sadisplay_default_render', 'graphviz', False)

    if not getattr(app, '_sanode_registered', False):
        app.add_node(
            SaNode,
            html=(html_visit, None),
            latex=(latex_visit, None),
        )
        setattr(app, '_sanode_registered', True)

    app.add_directive('sadisplay', SadisplayDirective)
