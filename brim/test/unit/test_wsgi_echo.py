"""Tests for brim.wsgi_echo."""
"""Copyright and License.

Copyright 2012-2014 Gregory Holt

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this file except in compliance with the License. You may obtain
a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from StringIO import StringIO
from unittest import main, TestCase

from brim import wsgi_echo
from brim.conf import Conf


class FakeStats(object):

    def __init__(self):
        self.stats = {}

    def get(self, name):
        return self.stats.get(name, 0)

    def set(self, name, value):
        self.stats[name] = value

    def incr(self, name):
        self.stats[name] = self.stats.get(name, 0) + 1


class TestWSGIEcho(TestCase):

    def setUp(self):
        self.next_app_calls = []
        self.start_response_calls = []

        def _next_app(env, start_response):
            self.next_app_calls.append((env, start_response))
            start_response('204 No Content', ('Content-Length', '0'))
            return []

        def _start_response(*args):
            self.start_response_calls.append(args)

        self.next_app = _next_app
        self.start_response = _start_response
        self.env = {'PATH_INFO': '/testpath', 'brim.stats': FakeStats(),
                    'wsgi.input': StringIO('testbody')}
        self.parsed_conf = {'path': '/testpath', 'max_echo': 10}

    def test_call_ignores_non_path(self):
        self.env['PATH_INFO'] = '/'
        wsgi_echo.WSGIEcho('test', self.parsed_conf,
                           self.next_app)(self.env, self.start_response)
        self.assertEqual(
            self.next_app_calls, [(self.env, self.start_response)])
        self.assertEqual(self.start_response_calls, [
            ('204 No Content', ('Content-Length', '0'))])

    def test_call_non_path_no_stat_incr(self):
        self.env['PATH_INFO'] = '/'
        wsgi_echo.WSGIEcho('test', self.parsed_conf, self.next_app)(
            self.env, self.start_response)
        self.assertEqual(self.env['brim.stats'].get('test.requests'), 0)

    def test_call_stat_incr(self):
        wsgi_echo.WSGIEcho('test', self.parsed_conf, self.next_app)(
            self.env, self.start_response)
        self.assertEqual(self.env['brim.stats'].get('test.requests'), 1)

    def test_call_echo(self):
        body = ''.join(wsgi_echo.WSGIEcho(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [
            ('200 OK', [('Content-Length', '8')])])
        self.assertEqual(body, 'testbody')

    def test_call_echo_capped(self):
        self.env['wsgi.input'] = StringIO('1234567890123')
        body = ''.join(wsgi_echo.WSGIEcho(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [
            ('200 OK', [('Content-Length', '10')])])
        self.assertEqual(body, '1234567890')

    def test_call_echo_exception_on_read(self):
        del self.env['wsgi.input']
        body = ''.join(wsgi_echo.WSGIEcho(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [
            ('200 OK', [('Content-Length', '0')])])
        self.assertEqual(body, '')

    def test_parse_conf(self):
        c = wsgi_echo.WSGIEcho.parse_conf('test', Conf({}))
        self.assertEqual(c, {'path': '/echo', 'max_echo': 65536})
        c = wsgi_echo.WSGIEcho.parse_conf(
            'test', Conf({'test': {'path': '/blah', 'max_echo': 1}}))
        self.assertEqual(c, {'path': '/blah', 'max_echo': 1})
        c = wsgi_echo.WSGIEcho.parse_conf(
            'test', Conf({'test2': {'path': '/blah', 'max_echo': 1}}))
        self.assertEqual(c, {'path': '/echo', 'max_echo': 65536})

    def test_stats_conf(self):
        self.assertEqual(wsgi_echo.WSGIEcho.stats_conf(
            'test', self.parsed_conf), [('test.requests', 'sum')])


if __name__ == '__main__':
    main()
