"""Tests for brim.stats."""
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
from json import dumps, loads
from StringIO import StringIO
from unittest import main, TestCase

from brim import wsgi_stats
from brim.conf import Conf


class FakeStats(object):

    def __init__(self, bucket_names, stats_conf):
        self.bucket_names = bucket_names
        self.stats_conf = stats_conf
        self.bucket_count = len(self.bucket_names)
        self.names, self.types = zip(*stats_conf.iteritems())
        self.stats = [{} for b in xrange(self.bucket_count)]

    def get(self, bucket_id, name):
        return self.stats[bucket_id].get(name, 0)

    def set(self, bucket_id, name, value):
        self.stats[bucket_id][name] = value

    def incr(self, bucket_id, name):
        self.stats[bucket_id][name] = self.stats[bucket_id].get(name, 0) + 1


class FakeSubserver(object):

    def __init__(self, server, name, worker_count, worker_names, stats_conf):
        self.server = server
        self.name = name
        self.worker_count = worker_count
        self.worker_names = worker_names
        self.stats_conf = stats_conf


WSGI, WSGI2, TCP, TCP2, UDP, UDP2, DAEMONS = xrange(7)


class FakeServer(object):

    def __init__(self):
        self.start_time = 1234
        self.subservers = [
            FakeSubserver(self, 'wsgi', 2, ['0', '1'], {
                'one': 'worker', 'two': 'sum', 'three': 'min',
                'four': 'max'}),
            FakeSubserver(self, 'wsgi2', 2, ['0', '1'], {
                'One': 'worker', 'Two': 'sum', 'Three': 'min',
                'Four': 'max'}),
            FakeSubserver(self, 'tcp', 2, ['0', '1'], {
                'one': 'worker', 'two': 'sum', 'three': 'min',
                'four': 'max'}),
            FakeSubserver(self, 'tcp2', 2, ['0', '1'], {
                'One': 'worker', 'Two': 'sum', 'Three': 'min',
                'Four': 'max'}),
            FakeSubserver(self, 'udp', 1, ['0'], {
                'one': 'worker', 'two': 'worker', 'three': 'worker',
                'four': 'worker'}),
            FakeSubserver(self, 'udp2', 1, ['0'], {
                'One': 'worker', 'Two': 'worker', 'Three': 'worker',
                'Four': 'worker'}),
            FakeSubserver(self, 'daemons', 2, ['a', 'b'], {
                'one': 'worker', 'two': 'worker', 'three': 'worker',
                'four': 'worker'})]
        self.bucket_stats = [
            FakeStats(s.worker_names, s.stats_conf) for s in self.subservers]


class TestWSGIStats(TestCase):

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
        self.env = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/testpath',
            'brim': FakeServer().subservers[0],
            'wsgi.input': StringIO('testbody'),
            'brim.json_dumps': dumps,
            'brim.json_loads': loads,
            'QUERY_STRING': ''}
        self.parsed_conf = {'path': '/testpath'}

    def test_call_ignores_non_path(self):
        self.env['PATH_INFO'] = '/'
        wsgi_stats.WSGIStats('test', self.parsed_conf, self.next_app)(
            self.env, self.start_response)
        self.assertEqual(
            self.next_app_calls, [(self.env, self.start_response)])
        self.assertEqual(self.start_response_calls, [
            ('204 No Content', ('Content-Length', '0'))])

    def test_call_not_implemented(self):
        self.env['REQUEST_METHOD'] = 'PUT'
        body = ''.join(wsgi_stats.WSGIStats(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [
            ('501 Not Implemented', [('Content-Length', '0')])])
        self.assertEqual(body, '')

    def test_call_stats_zeroed(self):
        body = ''.join(wsgi_stats.WSGIStats(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [('200 OK', [
            ('Content-Length', '107'), ('Content-Type', 'application/json')])])
        body = loads(body)
        a = {
            'start_time': 1234, 'wsgi': {}, 'wsgi2': {}, 'tcp': {}, 'tcp2': {},
            'udp': {}, 'udp2': {}, 'daemons': {}}
        self.assertEqual(body['start_time'], a['start_time'])
        self.assertEqual(body['wsgi'], a['wsgi'])
        self.assertEqual(body['wsgi2'], a['wsgi2'])
        self.assertEqual(body['tcp'], a['tcp'])
        self.assertEqual(body['tcp2'], a['tcp2'])
        self.assertEqual(body['udp'], a['udp'])
        self.assertEqual(body['udp2'], a['udp2'])
        self.assertEqual(body['daemons'], a['daemons'])
        self.assertEqual(body, a)

    def test_jsonp(self):
        self.env['QUERY_STRING'] = 'jsonp=jptest1'
        body = ''.join(wsgi_stats.WSGIStats(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [('200 OK', [
            ('Content-Length', '115'),
            ('Content-Type', 'application/javascript')])])
        self.assertEqual(True, body.startswith('jptest1('))

    def test_jsonp_callback(self):
        self.env['QUERY_STRING'] = 'callback=jptest2'
        body = ''.join(wsgi_stats.WSGIStats(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [('200 OK', [
            ('Content-Length', '115'),
            ('Content-Type', 'application/javascript')])])
        self.assertEqual(True, body.startswith('jptest2('))

    def test_jsonp_over_callback1(self):
        self.env['QUERY_STRING'] = 'jsonp=jptest3&callback=jptest4'
        body = ''.join(wsgi_stats.WSGIStats(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [('200 OK', [
            ('Content-Length', '115'),
            ('Content-Type', 'application/javascript')])])
        self.assertEqual(True, body.startswith('jptest3('))

    def test_jsonp_over_callback2(self):
        self.env['QUERY_STRING'] = 'callback=jptest3&jsonp=jptest4'
        body = ''.join(wsgi_stats.WSGIStats(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [('200 OK', [
            ('Content-Length', '115'),
            ('Content-Type', 'application/javascript')])])
        self.assertEqual(True, body.startswith('jptest4('))

    def test_call_stats_zeroed_head(self):
        self.env['REQUEST_METHOD'] = 'HEAD'
        body = ''.join(wsgi_stats.WSGIStats(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [('200 OK', [
            ('Content-Length', '107'), ('Content-Type', 'application/json')])])
        self.assertEqual(body, '')

    def test_call_stats(self):
        bstats = self.env['brim'].server.bucket_stats[WSGI]
        wsgi_tag = 100
        bstats.set(0, 'one', wsgi_tag + 1)
        bstats.set(0, 'two', wsgi_tag + 2)
        bstats.set(0, 'three', wsgi_tag + 3)
        bstats.set(0, 'four', wsgi_tag + 4)
        bstats.set(1, 'one', wsgi_tag + 11)
        bstats.set(1, 'two', wsgi_tag + 12)
        bstats.set(1, 'three', wsgi_tag + 13)
        bstats.set(1, 'four', wsgi_tag + 14)
        bstats = self.env['brim'].server.bucket_stats[WSGI2]
        wsgi2_tag = 200
        bstats.set(0, 'One', wsgi2_tag + 1)
        bstats.set(0, 'Two', wsgi2_tag + 2)
        bstats.set(0, 'Three', wsgi2_tag + 3)
        bstats.set(0, 'Four', wsgi2_tag + 4)
        bstats.set(1, 'One', wsgi2_tag + 11)
        bstats.set(1, 'Two', wsgi2_tag + 12)
        bstats.set(1, 'Three', wsgi2_tag + 13)
        bstats.set(1, 'Four', wsgi2_tag + 14)
        bstats = self.env['brim'].server.bucket_stats[TCP]
        tcp_tag = 300
        bstats.set(0, 'one', tcp_tag + 1)
        bstats.set(0, 'two', tcp_tag + 2)
        bstats.set(0, 'three', tcp_tag + 3)
        bstats.set(0, 'four', tcp_tag + 4)
        bstats.set(1, 'one', tcp_tag + 11)
        bstats.set(1, 'two', tcp_tag + 12)
        bstats.set(1, 'three', tcp_tag + 13)
        bstats.set(1, 'four', tcp_tag + 14)
        bstats = self.env['brim'].server.bucket_stats[TCP2]
        tcp2_tag = 400
        bstats.set(0, 'One', tcp2_tag + 1)
        bstats.set(0, 'Two', tcp2_tag + 2)
        bstats.set(0, 'Three', tcp2_tag + 3)
        bstats.set(0, 'Four', tcp2_tag + 4)
        bstats.set(1, 'One', tcp2_tag + 11)
        bstats.set(1, 'Two', tcp2_tag + 12)
        bstats.set(1, 'Three', tcp2_tag + 13)
        bstats.set(1, 'Four', tcp2_tag + 14)
        bstats = self.env['brim'].server.bucket_stats[UDP]
        udp_tag = 500
        bstats.set(0, 'one', udp_tag + 1)
        bstats.set(0, 'two', udp_tag + 2)
        bstats.set(0, 'three', udp_tag + 3)
        bstats.set(0, 'four', udp_tag + 4)
        bstats = self.env['brim'].server.bucket_stats[UDP2]
        udp2_tag = 600
        bstats.set(0, 'One', udp2_tag + 1)
        bstats.set(0, 'Two', udp2_tag + 2)
        bstats.set(0, 'Three', udp2_tag + 3)
        bstats.set(0, 'Four', udp2_tag + 4)
        bstats = self.env['brim'].server.bucket_stats[DAEMONS]
        daemons_tag = 700
        bstats.set(0, 'one', daemons_tag + 1)
        bstats.set(0, 'two', daemons_tag + 2)
        bstats.set(0, 'three', daemons_tag + 3)
        bstats.set(0, 'four', daemons_tag + 4)
        bstats.set(1, 'one', daemons_tag + 11)
        bstats.set(1, 'two', daemons_tag + 12)
        bstats.set(1, 'three', daemons_tag + 13)
        bstats.set(1, 'four', daemons_tag + 14)
        body = ''.join(wsgi_stats.WSGIStats(
            'test', self.parsed_conf,
            self.next_app)(self.env, self.start_response))
        self.assertEqual(self.start_response_calls, [('200 OK', [
            ('Content-Length', '945'), ('Content-Type', 'application/json')])])
        body = loads(body)
        a = {
            'start_time': 1234,
            'wsgi': {
                'two': sum((wsgi_tag + 2, wsgi_tag + 12)),
                'three': min((wsgi_tag + 3, wsgi_tag + 13)),
                'four': max((wsgi_tag + 4, wsgi_tag + 14)),
                '0': {
                    'one': wsgi_tag + 1, 'two': wsgi_tag + 2,
                    'three': wsgi_tag + 3, 'four': wsgi_tag + 4},
                '1': {
                    'one': wsgi_tag + 11, 'two': wsgi_tag + 12,
                    'three': wsgi_tag + 13, 'four': wsgi_tag + 14}},
            'wsgi2': {
                'Two': sum((wsgi2_tag + 2, wsgi2_tag + 12)),
                'Three': min((wsgi2_tag + 3, wsgi2_tag + 13)),
                'Four': max((wsgi2_tag + 4, wsgi2_tag + 14)),
                '0': {
                    'One': wsgi2_tag + 1, 'Two': wsgi2_tag + 2,
                    'Three': wsgi2_tag + 3, 'Four': wsgi2_tag + 4},
                '1': {
                    'One': wsgi2_tag + 11, 'Two': wsgi2_tag + 12,
                    'Three': wsgi2_tag + 13, 'Four': wsgi2_tag + 14}},
            'tcp': {
                'two': sum((tcp_tag + 2, tcp_tag + 12)),
                'three': min((tcp_tag + 3, tcp_tag + 13)),
                'four': max((tcp_tag + 4, tcp_tag + 14)),
                '0': {
                    'one': tcp_tag + 1, 'two': tcp_tag + 2,
                    'three': tcp_tag + 3, 'four': tcp_tag + 4},
                '1': {
                    'one': tcp_tag + 11, 'two': tcp_tag + 12,
                    'three': tcp_tag + 13, 'four': tcp_tag + 14}},
            'tcp2': {
                'Two': sum((tcp2_tag + 2, tcp2_tag + 12)),
                'Three': min((tcp2_tag + 3, tcp2_tag + 13)),
                'Four': max((tcp2_tag + 4, tcp2_tag + 14)),
                '0': {
                    'One': tcp2_tag + 1, 'Two': tcp2_tag + 2,
                    'Three': tcp2_tag + 3, 'Four': tcp2_tag + 4},
                '1': {
                    'One': tcp2_tag + 11, 'Two': tcp2_tag + 12,
                    'Three': tcp2_tag + 13, 'Four': tcp2_tag + 14}},
            'udp': {
                '0': {
                    'one': udp_tag + 1, 'two': udp_tag + 2,
                    'three': udp_tag + 3, 'four': udp_tag + 4}},
            'udp2': {
                '0': {
                    'One': udp2_tag + 1, 'Two': udp2_tag + 2,
                    'Three': udp2_tag + 3, 'Four': udp2_tag + 4}},
            'daemons': {
                'a': {
                    'one': daemons_tag + 1,
                    'two': daemons_tag + 2,
                    'three': daemons_tag + 3,
                    'four': daemons_tag + 4},
                'b': {
                    'one': daemons_tag + 11,
                    'two': daemons_tag + 12,
                    'three': daemons_tag + 13,
                    'four': daemons_tag + 14}}}
        self.assertEqual(body['start_time'], a['start_time'])
        self.assertEqual(body['wsgi'], a['wsgi'])
        self.assertEqual(body['wsgi2'], a['wsgi2'])
        self.assertEqual(body['tcp'], a['tcp'])
        self.assertEqual(body['tcp2'], a['tcp2'])
        self.assertEqual(body['udp'], a['udp'])
        self.assertEqual(body['udp2'], a['udp2'])
        self.assertEqual(body['daemons'], a['daemons'])
        self.assertEqual(body, a)

    def test_parse_conf(self):
        c = wsgi_stats.WSGIStats.parse_conf('test', Conf({}))
        self.assertEqual(c, {'path': '/stats'})
        c = wsgi_stats.WSGIStats.parse_conf(
            'test', Conf({'test': {'path': '/blah'}}))
        self.assertEqual(c, {'path': '/blah'})
        c = wsgi_stats.WSGIStats.parse_conf(
            'test', Conf({'test2': {'path': '/blah'}}))
        self.assertEqual(c, {'path': '/stats'})


if __name__ == '__main__':
    main()
