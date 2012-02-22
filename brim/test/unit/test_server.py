# Copyright 2012 Gregory Holt
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from contextlib import contextmanager
from pickle import dumps as pickle_dumps, loads as pickle_loads
from json import dumps as json_dumps, loads as json_loads
from StringIO import StringIO
from socket import error as socket_error
from sys import exc_info
from time import mktime, strptime, time
from unittest import main, TestCase
from uuid import uuid4

from brim import server, version
from brim.conf import Conf
from brim.service import get_listening_tcp_socket


class TestLogQuote(TestCase):

    def test_log_quote(self):
        self.assertEquals(
            server._log_quote(''.join(chr(c) for c in xrange(256))),
            '%00%01%02%03%04%05%06%07%08%09%0A%0B%0C%0D%0E%0F'
            '%10%11%12%13%14%15%16%17%18%19%1A%1B%1C%1D%1E%1F'
            '%20!"#$%25&\'()*+,-./0123456789:;<=>?@'
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`'
            'abcdefghijklmnopqrstuvwxyz{|}~%7F'
            '%80%81%82%83%84%85%86%87%88%89%8A%8B%8C%8D%8E%8F'
            '%90%91%92%93%94%95%96%97%98%99%9A%9B%9C%9D%9E%9F'
            '%A0%A1%A2%A3%A4%A5%A6%A7%A8%A9%AA%AB%AC%AD%AE%AF'
            '%B0%B1%B2%B3%B4%B5%B6%B7%B8%B9%BA%BB%BC%BD%BE%BF'
            '%C0%C1%C2%C3%C4%C5%C6%C7%C8%C9%CA%CB%CC%CD%CE%CF'
            '%D0%D1%D2%D3%D4%D5%D6%D7%D8%D9%DA%DB%DC%DD%DE%DF'
            '%E0%E1%E2%E3%E4%E5%E6%E7%E8%E9%EA%EB%EC%ED%EE%EF'
            '%F0%F1%F2%F3%F4%F5%F6%F7%F8%F9%FA%FB%FC%FD%FE%FF')


class TestStats(TestCase):

    def test_bucket_stats(self):
        bs = server._BucketStats(['testbucket'], {'test': 'worker'})
        self.assertEquals(bs.get(0, 'test'), 0)
        bs.set(0, 'test', 123)
        self.assertEquals(bs.get(0, 'test'), 123)
        bs.incr(0, 'test')
        self.assertEquals(bs.get(0, 'test'), 124)

        self.assertEquals(bs.get(0, 'test2'), 0)
        bs.set(0, 'test2', 123)
        self.assertEquals(bs.get(0, 'test2'), 0)
        bs.incr(0, 'test2')
        self.assertEquals(bs.get(0, 'test2'), 0)

        self.assertRaises(IndexError, bs.get, 1, 'test')
        self.assertRaises(IndexError, bs.set, 1, 'test', 123)
        self.assertRaises(IndexError, bs.incr, 1, 'test')

    def test_null_bucket_stats(self):
        bs = server._BucketStats([], {})
        self.assertEquals(bs.get(0, 'test'), 0)
        bs.set(0, 'test', 123)
        self.assertEquals(bs.get(0, 'test'), 0)
        bs.incr(0, 'test')
        self.assertEquals(bs.get(0, 'test'), 0)

        bs = server._BucketStats([], {'test': 'worker'})
        self.assertEquals(bs.get(0, 'test'), 0)
        bs.set(0, 'test', 123)
        self.assertEquals(bs.get(0, 'test'), 0)
        bs.incr(0, 'test')
        self.assertEquals(bs.get(0, 'test'), 0)

    def test_stats(self):
        bs = server._BucketStats(['testbucket'], ['test'])
        s = server._Stats(bs, 0)
        self.assertEquals(s.get('test'), 0)
        s.set('test', 123)
        self.assertEquals(s.get('test'), 123)
        s.incr('test')
        self.assertEquals(s.get('test'), 124)

        self.assertEquals(s.get('test2'), 0)
        s.set('test2', 123)
        self.assertEquals(s.get('test2'), 0)
        s.incr('test2')
        self.assertEquals(s.get('test2'), 0)

        s = server._Stats(bs, 1)
        self.assertRaises(IndexError, s.get, 'test')
        self.assertRaises(IndexError, s.set, 'test', 123)
        self.assertRaises(IndexError, s.incr, 'test')


class TestWsgiInput(TestCase):

    def setUp(self):
        self.sio = StringIO('1234567890')
        self.env = {'wsgi.input': self.sio, 'brim._bytes_in': 0}
        self.inp = server._WsgiInput(self.env, 3)

    def test_sets_as_self(self):
        self.assertEquals(self.env['wsgi.input'], self.inp)

    def test_close(self):
        self.inp.close()
        exc = None
        try:
            self.inp.read()
        except Exception, err:
            exc = err
        self.assertEquals(str(err), 'I/O operation on closed file')

    def test_flush(self):
        self.inp.flush()

    def test_fileno(self):
        exc = None
        try:
            self.inp.fileno()
        except Exception, err:
            exc = err
        self.assertEquals(str(err),
                          "StringIO instance has no attribute 'fileno'")

    def test_iterator(self):
        self.assertEquals([c for c in self.inp], ['123', '456', '789', '0'])
        self.assertEquals(self.env['brim._bytes_in'], 10)

    def test_read(self):
        self.assertEquals(self.inp.read(4), '1234')
        self.assertEquals(self.env['brim._bytes_in'], 4)
        self.assertEquals(self.inp.read(), '567890')
        self.assertEquals(self.env['brim._bytes_in'], 10)

    def test_readline(self):
        self.sio = StringIO('1234567890\nabcdefghij\nklmnopqrst')
        self.env = {'wsgi.input': self.sio, 'brim._bytes_in': 0}
        self.inp = server._WsgiInput(self.env, 3)
        self.assertEquals(self.inp.readline(), '1234567890\n')
        self.assertEquals(self.env['brim._bytes_in'], 11)
        self.assertEquals(self.inp.readline(2), 'ab')
        self.assertEquals(self.env['brim._bytes_in'], 13)
        self.assertEquals(self.inp.readline(20), 'cdefghij\n')
        self.assertEquals(self.env['brim._bytes_in'], 22)
        self.assertEquals(self.inp.readline(), 'klmnopqrst')
        self.assertEquals(self.env['brim._bytes_in'], 32)

    def test_readlines(self):
        self.sio = StringIO('1234567890\nabcdefghij\nklmnopqrst\nuvwxyz')
        self.env = {'wsgi.input': self.sio, 'brim._bytes_in': 0}
        self.inp = server._WsgiInput(self.env, 3)
        self.assertEquals(self.inp.readlines(15),
                          ['1234567890\n', 'abcdefghij\n'])
        self.assertEquals(self.env['brim._bytes_in'], 22)
        self.assertEquals(self.inp.readlines(), ['klmnopqrst\n', 'uvwxyz'])
        self.assertEquals(self.env['brim._bytes_in'], 39)


class TestWsgiOutput(TestCase):

    def test_wsgi_output(self):
        env = {'brim._bytes_out': 0}
        o = server._WsgiOutput(['123', '456', '78', '90'], env)
        self.assertEquals(o.next(), '123')
        self.assertEquals(env['brim._bytes_out'], 3)
        self.assertEquals([c for c in o], ['456', '78', '90'])


class TestSendPidSig(TestCase):

    def setUp(self):
        self.orig_kill = server.kill
        self.orig_time = server.time
        self.orig_sleep = server.sleep
        self.orig_unlink = server.unlink
        self.open_calls = []
        self.open_retval = [StringIO('12345')]
        self.kill_calls = []
        self.time_calls = []
        self.sleep_calls = []
        self.unlink_calls = []

        @contextmanager
        def _open(*args):
            self.open_calls.append(args)
            yield self.open_retval[0]

        def _kill(*args):
            self.kill_calls.append(args)

        def _time(*args):
            self.time_calls.append(args)
            return len(self.time_calls)

        def _sleep(*args):
            self.sleep_calls.append(args)

        def _unlink(*args):
            self.unlink_calls.append(args)

        server.open = _open
        server.kill = _kill
        server.time = _time
        server.sleep = _sleep
        server.unlink = _unlink

    def tearDown(self):
        del server.open
        server.kill = self.orig_kill
        server.time = self.orig_time
        server.sleep = self.orig_sleep
        server.unlink = self.orig_unlink

    def test_open_not_found(self):

        @contextmanager
        def _open(*args):
            exc = IOError('testing')
            exc.errno = server.ENOENT
            raise exc

        server.open = _open
        self.assertEquals(server._send_pid_sig('some.pid', 0), (False, 0))

    def test_open_exception(self):

        @contextmanager
        def _open(*args):
            raise IOError('testing')

        server.open = _open
        exc = None
        try:
            server._send_pid_sig('some.pid', 0)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), 'testing')

    def test_pid_file_no_int(self):
        self.open_retval[0] = StringIO('')
        self.assertEquals(server._send_pid_sig('some.pid', 0), (False, 0))

    def test_kill_inactive_pid(self):

        def _kill(*args):
            exc = OSError('testing')
            exc.errno = server.ESRCH
            raise exc

        server.kill = _kill
        self.open_retval[0] = StringIO('12345')
        self.assertEquals(server._send_pid_sig('some.pid', 0), (False, 12345))

    def test_kill_exception(self):

        def _kill(*args):
            raise OSError('testing')

        server.kill = _kill
        self.open_retval[0] = StringIO('12345')
        exc = None
        try:
            server._send_pid_sig('some.pid', 0)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), 'testing')

    def test_kill_worked(self):
        self.open_retval[0] = StringIO('12345')
        self.assertEquals(server._send_pid_sig('some.pid', 0), (True, 12345))

    def test_kill_expect_exit_timeout(self):
        self.open_retval[0] = StringIO('12345')
        exc = None
        try:
            server._send_pid_sig('some.pid', 0, expect_exit=True)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc),
            '12345 did not exit after %s seconds.' % server.PID_WAIT_TIME)
        self.assertEquals(self.time_calls, [()] * (server.PID_WAIT_TIME + 1))
        self.assertEquals(self.sleep_calls,
                          [(1,)] * (server.PID_WAIT_TIME - 1))
        self.assertEquals(self.unlink_calls, [])

    def test_kill_expect_exit_worked(self):
        kill_calls = []

        def _kill(*args):
            kill_calls.append(args)
            if len(kill_calls) > 3:
                exc = OSError()
                exc.errno = server.ESRCH
                raise exc

        server.kill = _kill
        self.open_retval[0] = StringIO('12345')
        server._send_pid_sig('some.pid', 0, expect_exit=True)
        self.assertEquals(self.time_calls, [()] * 3)
        self.assertEquals(self.sleep_calls, [(1,)] * 2)
        self.assertEquals(self.unlink_calls, [('some.pid',)])

    def test_kill_expect_exit_kill_exception(self):
        kill_calls = []

        def _kill(*args):
            kill_calls.append(args)
            if len(kill_calls) > 3:
                raise OSError('testing')

        server.kill = _kill
        self.open_retval[0] = StringIO('12345')
        exc = None
        try:
            server._send_pid_sig('some.pid', 0, expect_exit=True)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), 'testing')
        self.assertEquals(self.time_calls, [()] * 3)
        self.assertEquals(self.sleep_calls, [(1,)] * 2)
        self.assertEquals(self.unlink_calls, [])

    def test_kill_expect_exit_unlink_not_found(self):
        kill_calls = []
        unlink_calls = []

        def _kill(*args):
            kill_calls.append(args)
            if len(kill_calls) > 1:
                exc = OSError()
                exc.errno = server.ESRCH
                raise exc

        def _unlink(*args):
            unlink_calls.append(args)
            exc = OSError()
            exc.errno = server.ENOENT
            raise exc

        server.kill = _kill
        server.unlink = _unlink
        self.open_retval[0] = StringIO('12345')
        self.assertEquals(server._send_pid_sig('some.pid', 0,
                                               expect_exit=True),
                          (True, 12345))
        self.assertEquals(unlink_calls, [('some.pid',)])

    def test_kill_expect_exit_unlink_exception(self):
        kill_calls = []

        def _kill(*args):
            kill_calls.append(args)
            if len(kill_calls) > 1:
                exc = OSError()
                exc.errno = server.ESRCH
                raise exc

        def _unlink(*args):
            raise OSError('testing')

        server.kill = _kill
        server.unlink = _unlink
        self.open_retval[0] = StringIO('12345')
        exc = None
        try:
            server._send_pid_sig('some.pid', 0, expect_exit=True)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), 'testing')


class FakeLogger(object):

    def __init__(self):
        self.debug_calls = []
        self.info_calls = []
        self.notice_calls = []
        self.error_calls = []
        self.exception_calls = []

    def debug(self, *args):
        self.debug_calls.append(args)

    def info(self, *args):
        self.info_calls.append(args)

    def notice(self, *args):
        self.notice_calls.append(args)

    def error(self, *args):
        self.error_calls.append(args)

    def exception(self, *args):
        self.exception_calls.append((args, exc_info()))


class DaemonWithInvalidInit(object):

    def __init__(self):
        pass


class DaemonWithInvalidCall(object):

    def __init__(self, name, conf):
        pass

    def __call__(self):
        pass


class DaemonWithNoCall(object):

    def __init__(self, name, conf):
        pass


class DaemonWithInvalidParseConf(object):

    def __init__(self, name, conf):
        pass

    def __call__(self, server, stats):
        pass

    @classmethod
    def parse_conf(cls):
        pass


class DaemonWithInvalidParseConf2(object):

    parse_conf = 'blah'

    def __init__(self, name, conf):
        pass

    def __call__(self, server, stats):
        pass


class DaemonWithNoParseConf(object):

    def __init__(self, name, conf):
        pass

    def __call__(self, server, stats):
        pass


class DaemonWithParseConf(object):

    def __init__(self, name, conf):
        pass

    def __call__(self, server, stats):
        pass

    @classmethod
    def parse_conf(cls, name, conf):
        return {'ok': True}


class DaemonWithInvalidStatsConf(object):

    def __init__(self, name, conf):
        pass

    def __call__(self, server, stats):
        pass

    @classmethod
    def stats_conf(cls):
        pass


class DaemonWithInvalidStatsConf2(object):

    stats_conf = 'blah'

    def __init__(self, name, conf):
        pass

    def __call__(self, server, stats):
        pass


class DaemonWithNoStatsConf(object):

    def __init__(self, name, conf):
        pass

    def __call__(self, server, stats):
        pass


class DaemonWithStatsConf(object):

    call_calls = []

    def __init__(self, name, conf):
        pass

    def __call__(self, server, stats):
        stats.set('ok', 123)
        DaemonWithStatsConf.call_calls.append((server, stats))

    @classmethod
    def stats_conf(cls, name, conf):
        return ['ok']


class AppWithInvalidInit(object):

    def __init__(self):
        pass


class AppWithInvalidCall(object):

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self):
        pass


class AppWithNoCall(object):

    def __init__(self, name, conf, next_app):
        pass


class AppWithInvalidParseConf(object):

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self, env, start_response):
        pass

    @classmethod
    def parse_conf(cls):
        pass


class AppWithInvalidParseConf2(object):

    parse_conf = 'blah'

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self, env, start_response):
        pass


class AppWithNoParseConf(object):

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self, env, start_response):
        pass


class AppWithParseConf(object):

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self, env, start_response):
        pass

    @classmethod
    def parse_conf(cls, name, conf):
        return {'ok': True}


class AppWithInvalidStatsConf(object):

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self, env, start_response):
        pass

    @classmethod
    def stats_conf(cls):
        pass


class AppWithInvalidStatsConf2(object):

    stats_conf = 'blah'

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self, env, start_response):
        pass


class AppWithNoStatsConf(object):

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self, env, start_response):
        pass


class AppWithStatsConf(object):

    def __init__(self, name, conf, next_app):
        pass

    def __call__(self, env, start_response):
        if env['PATH_INFO'] == '/exception':
            raise Exception('testing')
        start_response('200 OK', [('Content-Length', '0')])
        return []

    @classmethod
    def stats_conf(cls, name, conf):
        return [('ok', 'sum')]


class TestServer(TestCase):

    def setUp(self):
        self.orig_read_conf = server.read_conf
        self.orig_fork = server.fork
        self.orig_sleep = server.sleep
        self.orig_send_pid_sig = server._send_pid_sig
        self.orig_droppriv = server.droppriv
        self.orig_get_logger = server.get_logger
        self.orig_capture_exceptions_stdout_stderr = \
            server.capture_exceptions_stdout_stderr
        self.read_conf_calls = []
        self.conf = Conf({})
        self.fork_calls = []
        self.fork_retval = [12345]
        self.sleep_calls = []
        self.send_pid_sig_calls = []
        self.send_pid_sig_retval = [True, 12345]
        self.droppriv_calls = []
        self.get_logger_calls = []
        self.capture_calls = []

        def _read_conf(*args):
            self.read_conf_calls.append(args)
            return self.conf

        def _fork(*args):
            self.fork_calls.append(args)
            if len(self.fork_retval) > 1:
                return self.fork_retval.pop(0)
            return self.fork_retval[0]

        def _sleep(*args):
            self.sleep_calls.append(args)

        def _send_pid_sig(*args, **kwargs):
            self.send_pid_sig_calls.append((args, kwargs))
            return self.send_pid_sig_retval

        def _droppriv(*args):
            self.droppriv_calls.append(args)

        def _get_logger(*args):
            self.get_logger_calls.append(args)
            return FakeLogger()

        def _capture_exceptions_stdout_stderr(*args, **kwargs):
            self.capture_calls.append((args, kwargs))

        server.read_conf = _read_conf
        server.fork = _fork
        server.sleep = _sleep
        server._send_pid_sig = _send_pid_sig
        server.droppriv = _droppriv
        server.get_logger = _get_logger
        server.capture_exceptions_stdout_stderr = \
            _capture_exceptions_stdout_stderr
        self.stdin = StringIO()
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.serv = server.Server([], self.stdin, self.stdout, self.stderr)

    def tearDown(self):
        server.read_conf = self.orig_read_conf
        server.fork = self.orig_fork
        server.sleep = self.orig_sleep
        server._send_pid_sig = self.orig_send_pid_sig
        server.droppriv = self.orig_droppriv
        server.get_logger = self.orig_get_logger
        server.capture_exceptions_stdout_stderr = \
            self.orig_capture_exceptions_stdout_stderr

    def test_uses_standard_items_by_default(self):
        serv = server.Server()
        self.assertEquals(serv.args, server.sys_argv[1:])
        self.assertEquals(serv.stdin, server.sys_stdin)
        self.assertEquals(serv.stdout, server.sys_stdout)
        self.assertEquals(serv.stderr, server.sys_stderr)

    def test_main(self):
        self.conf = Conf({'brim': {'port': '0'}, 'wsgi': {}})
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        server_calls = []

        def _server(*args, **kwargs):
            server_calls.append((args, kwargs))

        orig_wsgi_server = server.wsgi.server
        try:
            server.wsgi.server = _server
            self.assertEquals(self.serv.main(), 0)
        finally:
            server.wsgi.server = orig_wsgi_server

    def test_args_exception(self):
        self.serv.args = [123]
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(),
                          "'int' object is unsubscriptable\n")

    def test_args_help1(self):
        self.serv.args = ['-?']
        try:
            self.assertEquals(self.serv.main(), 0)
        except SystemExit:
            pass
        self.assertTrue('Usage: ' in self.stdout.getvalue())
        self.assertTrue("Command (defaults to 'no-daemon'):" in
                        self.stdout.getvalue())
        self.assertTrue('Options:' in self.stdout.getvalue())
        self.assertEquals(self.stderr.getvalue(), '')

    def test_args_help2(self):
        self.serv.args = ['-h']
        try:
            self.assertEquals(self.serv.main(), 0)
        except SystemExit:
            pass
        self.assertTrue('Usage: ' in self.stdout.getvalue())
        self.assertTrue("Command (defaults to 'no-daemon'):" in
                        self.stdout.getvalue())
        self.assertTrue('Options:' in self.stdout.getvalue())
        self.assertEquals(self.stderr.getvalue(), '')

    def test_args_help3(self):
        self.serv.args = ['--help']
        try:
            self.assertEquals(self.serv.main(), 0)
        except SystemExit:
            pass
        self.assertTrue('Usage: ' in self.stdout.getvalue())
        self.assertTrue("Command (defaults to 'no-daemon'):" in
                        self.stdout.getvalue())
        self.assertTrue('Options:' in self.stdout.getvalue())
        self.assertEquals(self.stderr.getvalue(), '')

    def test_args_default_conf(self):
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.read_conf_calls, [(server.DEFAULT_CONF_FILES,)])

    def test_args_override_conf1(self):
        self.serv.args = ['-c', 'one.conf']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.read_conf_calls, [(['one.conf'],)])
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_args_override_conf2(self):
        self.serv.args = ['-c', 'one.conf', '--conf', 'two.conf']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.read_conf_calls, [(['one.conf', 'two.conf'],)])
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_args_default_pid_file(self):
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.serv.pid_file, '/var/run/brimd.pid')

    def test_args_override_pid_file1(self):
        self.serv.args = ['-p', 'pidfile']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.serv.pid_file, 'pidfile')

    def test_args_override_pid_file2(self):
        self.serv.args = ['--pid-file', 'pidfile']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.serv.pid_file, 'pidfile')

    def test_args_default_nodaemon_output(self):
        self.assertEquals(self.serv.main(), 1)
        self.assertTrue(self.serv.output)

    def test_args_default_start_output(self):
        self.serv.args = ['start']
        self.send_pid_sig_retval[0] = False
        self.assertEquals(self.serv.main(), 1)
        self.assertFalse(self.serv.output)

    def test_args_override_output1(self):
        self.serv.args = ['start', '-o']
        self.send_pid_sig_retval[0] = False
        self.assertEquals(self.serv.main(), 1)
        self.assertTrue(self.serv.output)

    def test_args_override_output2(self):
        self.serv.args = ['start', '--output']
        self.send_pid_sig_retval[0] = False
        self.assertEquals(self.serv.main(), 1)
        self.assertTrue(self.serv.output)

    def test_version(self):
        self.serv.args = ['--version']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(),
                          'Brim.Net Core Server %s\n' % version)
        self.assertEquals(self.stderr.getvalue(), '')

    def test_parser_error(self):
        self.serv.args = ['--invalid']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(),
                          'no such option: --invalid\n')

    def test_too_many_commands(self):
        self.serv.args = ['one', 'two']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(),
                          'Too many commands given; only one allowed.\n')

    def test_default_command_no_daemon1(self):
        self.assertEquals(self.serv.main(), 1)
        self.assertTrue(self.serv.no_daemon)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_default_command_no_daemon2(self):
        self.serv.args = ['start']
        self.send_pid_sig_retval[0] = False
        self.assertEquals(self.serv.main(), 1)
        self.assertFalse(self.serv.no_daemon)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_start_already_running(self):
        self.serv.args = ['start']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), '12345 already running\n')
        self.assertEquals(self.stderr.getvalue(), '')

    def test_start_no_conf(self):
        self.serv.args = ['start']
        self.send_pid_sig_retval[0] = False
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_start_has_conf(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['start']
        self.send_pid_sig_retval[0] = False
        self.assertEquals(self.serv._parse_args(), self.conf)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')

    def test_restart_no_conf(self):
        self.serv.args = ['restart']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_restart_has_conf(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['restart']
        self.assertEquals(self.serv._parse_args(), self.conf)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.fork_calls, [()])

    def test_restart_has_conf_fork_side(self):
        self.fork_retval[0] = 0
        self.conf.files = ['ok.conf']
        self.serv.args = ['restart']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.fork_calls, [()])
        self.assertEquals(self.send_pid_sig_calls,
            [((self.serv.pid_file, 0), {}),
             ((self.serv.pid_file, server.SIGHUP),
              {'expect_exit': True, 'pid_override': 12345})])

    def test_reload_no_conf(self):
        self.serv.args = ['reload']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_reload_has_conf(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['reload']
        self.assertEquals(self.serv._parse_args(), self.conf)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.fork_calls, [()])

    def test_reload_has_conf_fork_side(self):
        self.fork_retval[0] = 0
        self.conf.files = ['ok.conf']
        self.serv.args = ['reload']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.fork_calls, [()])
        self.assertEquals(self.send_pid_sig_calls,
            [((self.serv.pid_file, 0), {}),
             ((self.serv.pid_file, server.SIGHUP),
              {'expect_exit': True, 'pid_override': 12345})])

    def test_force_reload_no_conf(self):
        self.serv.args = ['force-reload']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_force_reload_has_conf(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['force-reload']
        self.assertEquals(self.serv._parse_args(), self.conf)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.fork_calls, [()])

    def test_force_reload_has_conf_fork_side(self):
        self.fork_retval[0] = 0
        self.conf.files = ['ok.conf']
        self.serv.args = ['force-reload']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.fork_calls, [()])
        self.assertEquals(self.send_pid_sig_calls,
            [((self.serv.pid_file, 0), {}),
             ((self.serv.pid_file, server.SIGHUP),
              {'expect_exit': True, 'pid_override': 12345})])

    def test_shutdown(self):
        self.serv.args = ['shutdown']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.send_pid_sig_calls,
            [((self.serv.pid_file, server.SIGHUP), {'expect_exit': True})])

    def test_stop(self):
        self.serv.args = ['stop']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.send_pid_sig_calls,
            [((self.serv.pid_file, server.SIGTERM), {'expect_exit': True})])

    def test_status_running(self):
        self.serv.args = ['status']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), '12345 is running\n')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.send_pid_sig_calls,
                          [((self.serv.pid_file, 0), {})])

    def test_status_not_running(self):
        self.send_pid_sig_retval[0] = False
        self.serv.args = ['status']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), '12345 is not running\n')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.send_pid_sig_calls,
                          [((self.serv.pid_file, 0), {})])

    def test_status_not_running_no_pid(self):
        self.send_pid_sig_retval[0] = False
        self.send_pid_sig_retval[1] = 0
        self.serv.args = ['status']
        self.assertEquals(self.serv.main(), 0)
        self.assertEquals(self.stdout.getvalue(), 'not running\n')
        self.assertEquals(self.stderr.getvalue(), '')
        self.assertEquals(self.send_pid_sig_calls,
                          [((self.serv.pid_file, 0), {})])

    def test_no_daemon_no_conf(self):
        self.serv.args = ['no-daemon']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), 'No configuration found.\n')

    def test_no_daemon_has_conf(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.assertEquals(self.serv._parse_args(), self.conf)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(), '')

    def test_unknown_command(self):
        self.serv.args = ['unknown']
        self.assertEquals(self.serv.main(), 1)
        self.assertEquals(self.stdout.getvalue(), '')
        self.assertEquals(self.stderr.getvalue(),
                          "Unknown command 'unknown'.\n")

    def test_parse_conf_default(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'wsgi': {}}))
        self.assertEquals(self.serv.user, None)
        self.assertEquals(self.serv.group, None)
        self.assertEquals(self.serv.umask, 0022)
        self.assertEquals(self.serv.log_name, 'brim')
        self.assertEquals(self.serv.log_level, 'INFO')
        self.assertEquals(self.serv.log_facility, 'LOG_LOCAL0')
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.ip, '*')
        self.assertEquals(subserv.port, 80)
        self.assertEquals(subserv.backlog, 4096)
        self.assertEquals(subserv.listen_retry, 30)
        self.assertEquals(subserv.certfile, None)
        self.assertEquals(subserv.keyfile, None)
        self.assertEquals(subserv.worker_count, 0)
        self.assertEquals(subserv.log_name, 'brimwsgi')
        self.assertEquals(subserv.log_level, 'INFO')
        self.assertEquals(subserv.log_facility, 'LOG_LOCAL0')
        self.assertEquals(subserv.client_timeout, 60)
        self.assertEquals(subserv.eventlet_hub, 'poll')
        self.assertEquals(subserv.concurrent_per_worker, 1024)
        self.assertEquals(subserv.wsgi_input_iter_chunk_size, 4096)
        self.assertEquals(subserv.log_headers, False)
        self.assertEquals(subserv.json_dumps, json_dumps)
        self.assertEquals(subserv.json_loads, json_loads)
        self.assertEquals(subserv.count_status_codes, [404, 408, 499, 501])

    def test_parse_conf_ip(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'ip': '1.2.3.4'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.ip, '1.2.3.4')

    def test_parse_conf_port(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'port': '1234'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.port, 1234)
        exc = None
        try:
            self.serv._parse_conf(Conf({'brim': {'port': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Configuration value [brim] port of "
                                    "'abc' cannot be converted to int.")

    def test_parse_conf_backlog(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'backlog': '123'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.backlog, 123)
        exc = None
        try:
            self.serv._parse_conf(Conf({'brim': {'backlog': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Configuration value [brim] backlog "
                                    "of 'abc' cannot be converted to int.")

    def test_parse_conf_listen_retry(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'brim': {'listen_retry': '123'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.listen_retry, 123)
        exc = None
        try:
            self.serv._parse_conf(Conf({'brim': {'listen_retry': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Configuration value [brim] "
            "listen_retry of 'abc' cannot be converted to int.")

    def test_parse_conf_certfile(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'certfile': 'file'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.certfile, 'file')

    def test_parse_conf_keyfile(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'keyfile': 'file'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.keyfile, 'file')

    def test_parse_conf_user(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'user': 'name'}}))
        self.assertEquals(self.serv.user, 'name')

    def test_parse_conf_group(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'group': 'name'}}))
        self.assertEquals(self.serv.group, 'name')

    def test_parse_conf_umask(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'umask': '0777'}}))
        self.assertEquals(self.serv.umask, 0777)
        exc = None
        try:
            self.serv._parse_conf(Conf({'brim': {'umask': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Invalid umask value 'abc'.")
        exc = None
        try:
            self.serv._parse_conf(Conf({'brim': {'umask': '99'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Invalid umask value '99'.")

    def test_parse_conf_worker_count(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['start']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'workers': '123'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.worker_count, 123)
        exc = None
        try:
            self.serv._parse_conf(Conf({'brim': {'workers': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Configuration value [brim] "
            "workers of 'abc' cannot be converted to int.")

    def test_parse_conf_worker_count_no_daemon(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'workers': '123'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.worker_count, 0)
        self.serv._parse_conf(Conf({'brim': {'workers': 'abc'}}))
        self.assertEquals(subserv.worker_count, 0)

    def test_parse_conf_log_name(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'log_name': 'name'}}))
        self.assertEquals(self.serv.log_name, 'name')

    def test_parse_conf_log_level(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'brim': {'log_level': 'DEBUG'}}))
        self.assertEquals(self.serv.log_level, 'DEBUG')
        exc = None
        try:
            self.serv._parse_conf(Conf({'brim': {'log_level': 'invalid'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(err), "Invalid [brim] log_level 'INVALID'.")

    def test_parse_conf_log_facility(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'brim': {'log_facility': 'LOG_LOCAL1'}}))
        self.assertEquals(self.serv.log_facility, 'LOG_LOCAL1')
        self.serv._parse_conf(Conf({'brim': {'log_facility': 'LOCAL2'}}))
        self.assertEquals(self.serv.log_facility, 'LOG_LOCAL2')
        exc = None
        try:
            self.serv._parse_conf(
                Conf({'brim': {'log_facility': 'invalid'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(err),
                          "Invalid [brim] log_facility 'LOG_INVALID'.")

    def test_parse_conf_client_timeout(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'brim': {'client_timeout': '123'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.client_timeout, 123)
        exc = None
        try:
            self.serv._parse_conf(
                Conf({'brim': {'client_timeout': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Configuration value [brim] "
            "client_timeout of 'abc' cannot be converted to int.")

    def test_parse_conf_eventlet_hub(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'brim': {'eventlet_hub': 'name'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.eventlet_hub, 'name')

    def test_parse_conf_concurrent_per_worker(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'brim': {'concurrent_per_worker': '123'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.concurrent_per_worker, 123)
        exc = None
        try:
            self.serv._parse_conf(
                Conf({'brim': {'concurrent_per_worker': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Configuration value [brim] "
            "concurrent_per_worker of 'abc' cannot be converted to int.")

    def test_parse_conf_wsgi_input_iter_chunk_size(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'wsgi': {'wsgi_input_iter_chunk_size': '123'}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.wsgi_input_iter_chunk_size, 123)
        exc = None
        try:
            self.serv._parse_conf(
                Conf({'wsgi': {'wsgi_input_iter_chunk_size': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Configuration value [wsgi] "
            "wsgi_input_iter_chunk_size of 'abc' cannot be converted to int.")

    def test_parse_conf_log_headers(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(Conf({'wsgi': {'log_headers': 'yes'}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.log_headers, True)
        exc = None
        try:
            self.serv._parse_conf(Conf({'brim': {'log_headers': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Configuration value [brim] "
            "log_headers of 'abc' cannot be converted to boolean.")

    def test_parse_conf_json_dumps(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'brim': {'json_dumps': 'pickle.dumps'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.json_dumps, pickle_dumps)
        exc = None
        try:
            self.serv._parse_conf(Conf({'wsgi': {'json_dumps': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Invalid [wsgi] json_dumps value 'abc'.")
        exc = None
        try:
            self.serv._parse_conf(
                Conf({'wsgi': {'json_dumps': 'pickle.blah'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc),
            "Could not load function 'pickle.blah' for [wsgi] json_dumps.")

    def test_parse_conf_json_loads(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'brim': {'json_loads': 'pickle.loads'}, 'wsgi': {}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.json_loads, pickle_loads)
        exc = None
        try:
            self.serv._parse_conf(Conf({'wsgi': {'json_loads': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Invalid [wsgi] json_loads value 'abc'.")
        exc = None
        try:
            self.serv._parse_conf(
                Conf({'wsgi': {'json_loads': 'pickle.blah'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc),
            "Could not load function 'pickle.blah' for [wsgi] json_loads.")

    def test_parse_conf_count_status_codes(self):
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(
            Conf({'wsgi': {'count_status_codes': '1'}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.count_status_codes, [1])
        self.serv._parse_conf(
            Conf({'wsgi': {'count_status_codes': '1 2 345'}}))
        subserv = self.serv.subservers[0]
        self.assertEquals(subserv.count_status_codes, [1, 2, 345])
        exc = None
        try:
            self.serv._parse_conf(
                Conf({'wsgi': {'count_status_codes': 'abc'}}))
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Invalid [wsgi] count_status_codes 'abc'.")

    def test_configure_daemons_none(self):
        subserv = server.DaemonsSubserver(self.serv)
        subserv._parse_conf(Conf({}))
        self.assertEquals(subserv.daemons, [])

    def test_configure_daemons(self):
        conf = Conf({
            'daemons': {'daemons': 'one two'},
            'one': {'call': 'brim.daemon_sample.DaemonSample'},
            'two': {'call': 'brim.daemon_sample.DaemonSample'}})
        subserv = server.DaemonsSubserver(self.serv)
        subserv._parse_conf(conf)
        self.assertEquals(len(subserv.daemons), 2)
        self.assertEquals(subserv.daemons[0][0], 'one')
        self.assertEquals(subserv.daemons[1][0], 'two')
        self.assertEquals(subserv.daemons[0][1].__name__, 'DaemonSample')
        self.assertEquals(subserv.daemons[1][1].__name__, 'DaemonSample')
        self.assertEquals(subserv.daemons[0][2],
                          subserv.daemons[0][1].parse_conf('one', conf))
        self.assertEquals(subserv.daemons[1][2],
                          subserv.daemons[1][1].parse_conf('two', conf))

    def test_configure_daemons_conf_no_call(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'cll': 'brim.daemon_sample.DaemonSample'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc),
                          "Daemon [one] not configured with 'call' option.")

    def test_configure_daemons_conf_invalid_call(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call': 'brim_daemon_sample_DaemonSample'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Invalid call value "
            "'brim_daemon_sample_DaemonSample' for daemon [one].")

    def test_configure_daemons_no_load(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call': 'brim.daemon_sample.aemonSample'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Could not load class "
            "'brim.daemon_sample.aemonSample' for daemon [one].")

    def test_configure_daemons_not_a_class(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call': 'brim.server._send_pid_sig'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Would not be able to instantiate "
            "'brim.server._send_pid_sig' for daemon [one]. Probably not a "
            "class.")

    def test_configure_daemons_invalid_init(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {
              'call': 'brim.test.unit.test_server.DaemonWithInvalidInit'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Would not be able to instantiate "
            "'brim.test.unit.test_server.DaemonWithInvalidInit' for "
            "daemon [one]. Incorrect number of args, 1, should be 3 (self, "
            "name, conf).")

    def test_configure_daemons_invalid_call(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {
              'call': 'brim.test.unit.test_server.DaemonWithInvalidCall'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Would not be able to use "
            "'brim.test.unit.test_server.DaemonWithInvalidCall' for "
            "daemon [one]. Incorrect number of __call__ args, 1, should be 3 "
            "(self, subserver, stats).")

    def test_configure_daemons_no_call(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {
              'call': 'brim.test.unit.test_server.DaemonWithNoCall'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Would not be able to use "
            "'brim.test.unit.test_server.DaemonWithNoCall' for daemon "
            "[one]. Probably no __call__ method.")

    def test_configure_daemons_invalid_parse_conf1(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.DaemonWithInvalidParseConf'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Cannot use "
            "'brim.test.unit.test_server.DaemonWithInvalidParseConf' for "
            "daemon [one]. Incorrect number of parse_conf args, 1, should be "
            "3 (cls, name, conf).")

    def test_configure_daemons_invalid_parse_conf2(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.DaemonWithInvalidParseConf2'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Cannot use "
            "'brim.test.unit.test_server.DaemonWithInvalidParseConf2' for "
            "daemon [one]. parse_conf probably not a method.")

    def test_configure_daemons_no_parse_conf(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.DaemonWithNoParseConf'}})
        subserv = server.DaemonsSubserver(self.serv)
        subserv._parse_conf(conf)
        self.assertEquals(subserv.daemons[0][2], conf)

    def test_configure_daemons_with_parse_conf(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.DaemonWithParseConf'}})
        subserv = server.DaemonsSubserver(self.serv)
        subserv._parse_conf(conf)
        self.assertEquals(subserv.daemons[0][2], {'ok': True})

    def test_configure_daemons_invalid_stats_conf1(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.DaemonWithInvalidStatsConf'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Cannot use "
            "'brim.test.unit.test_server.DaemonWithInvalidStatsConf' for "
            "app [one]. Incorrect number of stats_conf args, 1, should be 3 "
            "(cls, name, conf).")

    def test_configure_daemons_invalid_stats_conf2(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.DaemonWithInvalidStatsConf2'}})
        exc = None
        try:
            server.DaemonsSubserver(self.serv)._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Cannot use "
            "'brim.test.unit.test_server.DaemonWithInvalidStatsConf2' for "
            "app [one]. stats_conf probably not a method.")

    def test_configure_daemons_no_stats_conf(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.DaemonWithNoStatsConf'}})
        subserv = server.DaemonsSubserver(self.serv)
        subserv._parse_conf(conf)
        self.assertEquals(subserv.stats_conf, {'start_time': 'worker'})

    def test_configure_daemons_with_stats_conf(self):
        conf = Conf({
            'daemons': {'daemons': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.DaemonWithStatsConf'}})
        subserv = server.DaemonsSubserver(self.serv)
        subserv._parse_conf(conf)
        self.assertEquals(subserv.stats_conf,
                          {'start_time': 'worker', 'ok': 'worker'})

    def test_configure_wsgi_apps_none(self):
        self.serv.no_daemon = False
        subserv = server.WSGISubserver(self.serv, 'wsgi')
        subserv._parse_conf(Conf({}))
        self.assertEquals(subserv.apps, [])

    def test_configure_wsgi_apps(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one two'},
            'one': {'call': 'brim.wsgi_echo.WSGIEcho'},
            'two': {'call': 'brim.wsgi_echo.WSGIEcho'}})
        subserv = server.WSGISubserver(self.serv, 'wsgi')
        subserv._parse_conf(conf)
        self.assertEquals(len(subserv.apps), 2)
        self.assertEquals(subserv.apps[0][0], 'one')
        self.assertEquals(subserv.apps[1][0], 'two')
        self.assertEquals(subserv.apps[0][1].__name__, 'WSGIEcho')
        self.assertEquals(subserv.apps[1][1].__name__, 'WSGIEcho')
        self.assertEquals(subserv.apps[0][2],
                          subserv.apps[0][1].parse_conf('one', conf))
        self.assertEquals(subserv.apps[1][2],
                          subserv.apps[1][1].parse_conf('two', conf))

    def test_configure_wsgi_apps_conf_no_call(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'cll': 'brim.wsgi_echo.WSGIEcho'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc),
                          "App [one] not configured with 'call' option.")

    def test_configure_wsgi_apps_conf_invalid_call(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call': 'brim_wsgi_echo_WSGIEcho'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Invalid call value "
            "'brim_wsgi_echo_WSGIEcho' for app [one].")

    def test_configure_wsgi_apps_no_load(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call': 'brim.wsgi_echo.sgi_cho'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Could not load class "
            "'brim.wsgi_echo.sgi_cho' for app [one].")

    def test_configure_wsgi_apps_not_a_class(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call': 'brim.server._send_pid_sig'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Would not be able to instantiate "
            "'brim.server._send_pid_sig' for app [one]. Probably not a "
            "class.")

    def test_configure_wsgi_apps_invalid_init(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {
              'call': 'brim.test.unit.test_server.AppWithInvalidInit'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Would not be able to instantiate "
            "'brim.test.unit.test_server.AppWithInvalidInit' for app "
            "[one]. Incorrect number of args, 1, should be 4 (self, name, "
            "conf, next_app).")

    def test_configure_wsgi_apps_invalid_call(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {
              'call': 'brim.test.unit.test_server.AppWithInvalidCall'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Would not be able to use "
            "'brim.test.unit.test_server.AppWithInvalidCall' for app "
            "[one]. Incorrect number of __call__ args, 1, should be 3 (self, "
            "env, start_response).")

    def test_configure_wsgi_apps_no_call(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {
              'call': 'brim.test.unit.test_server.AppWithNoCall'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Would not be able to use "
            "'brim.test.unit.test_server.AppWithNoCall' for app "
            "[one]. Probably no __call__ method.")

    def test_configure_wsgi_apps_invalid_parse_conf1(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.AppWithInvalidParseConf'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Cannot use "
            "'brim.test.unit.test_server.AppWithInvalidParseConf' for "
            "app [one]. Incorrect number of parse_conf args, 1, should be "
            "3 (cls, name, conf).")

    def test_configure_wsgi_apps_invalid_parse_conf2(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.AppWithInvalidParseConf2'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Cannot use "
            "'brim.test.unit.test_server.AppWithInvalidParseConf2' for "
            "app [one]. parse_conf probably not a method.")

    def test_configure_wsgi_apps_no_parse_conf(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.AppWithNoParseConf'}})
        subserv = server.WSGISubserver(self.serv, 'wsgi')
        subserv._parse_conf(conf)
        self.assertEquals(subserv.apps[0][2], conf)

    def test_configure_wsgi_apps_with_parse_conf(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.AppWithParseConf'}})
        subserv = server.WSGISubserver(self.serv, 'wsgi')
        subserv._parse_conf(conf)
        self.assertEquals(subserv.apps[0][2], {'ok': True})

    def test_configure_wsgi_apps_invalid_stats_conf1(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.AppWithInvalidStatsConf'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Cannot use "
            "'brim.test.unit.test_server.AppWithInvalidStatsConf' for "
            "app [one]. Incorrect number of stats_conf args, 1, should be 3 "
            "(cls, name, conf).")

    def test_configure_wsgi_apps_invalid_stats_conf2(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.AppWithInvalidStatsConf2'}})
        exc = None
        try:
            server.WSGISubserver(self.serv, 'wsgi')._parse_conf(conf)
        except Exception, err:
            exc = err
        self.assertEquals(str(exc), "Cannot use "
            "'brim.test.unit.test_server.AppWithInvalidStatsConf2' for "
            "app [one]. stats_conf probably not a method.")

    def test_configure_wsgi_apps_no_stats_conf(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.AppWithNoStatsConf'}})
        subserv = server.WSGISubserver(self.serv, 'wsgi')
        subserv._parse_conf(conf)
        self.assertEquals(subserv.stats_conf,
            {'start_time': 'worker', 'status_5xx_count': 'sum',
             'status_3xx_count': 'sum', 'request_count': 'sum',
             'status_4xx_count': 'sum', 'status_2xx_count': 'sum'})

    def test_configure_wsgi_apps_with_stats_conf(self):
        self.serv.no_daemon = False
        conf = Conf({
            'wsgi': {'apps': 'one'},
            'one': {'call':
                'brim.test.unit.test_server.AppWithStatsConf'}})
        subserv = server.WSGISubserver(self.serv, 'wsgi')
        subserv._parse_conf(conf)
        self.assertEquals(subserv.stats_conf,
            {'ok': 'sum', 'start_time': 'worker', 'status_5xx_count': 'sum',
             'status_3xx_count': 'sum', 'request_count': 'sum',
             'status_4xx_count': 'sum', 'status_2xx_count': 'sum'})

    def test_start(self):
        self.conf = Conf({'brim': {'port': '0'}, 'wsgi': {}})
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(self.conf)
        subserv = self.serv.subservers[0]
        subserv._parse_conf(self.conf)
        sustain_workers_calls = []

        def _sustain_workers(*args, **kwargs):
            sustain_workers_calls.append((args, kwargs))

        orig_sustain_workers = server.sustain_workers
        try:
            server.sustain_workers = _sustain_workers
            self.serv._start()
        finally:
            server.sustain_workers = orig_sustain_workers
        self.assertEquals(sustain_workers_calls,
            [((0, subserv._wsgi_worker), {'logger': subserv.logger})])

    def test_start_no_bind(self):
        sock = get_listening_tcp_socket('*', 0)
        self.conf = Conf({'brim': {'port': sock.getsockname()[1],
                                       'listen_retry': '0'}, 'wsgi': {}})
        self.conf.files = ['ok.conf']
        self.serv.args = ['no-daemon']
        self.serv._parse_args()
        self.serv._parse_conf(self.conf)
        subserv = self.serv.subservers[0]
        subserv._parse_conf(self.conf)
        sustain_workers_calls = []

        def _sustain_workers(*args, **kwargs):
            sustain_workers_calls.append((args, kwargs))

        orig_sustain_workers = server.sustain_workers
        exc = None
        try:
            server.sustain_workers = _sustain_workers
            self.serv._start()
        except Exception, err:
            exc = err
        finally:
            server.sustain_workers = orig_sustain_workers
        self.assertEquals(str(exc), 'Could not bind to *:%s: Could not bind '
            'to 0.0.0.0:%s after trying for 0 seconds.' %
            (sock.getsockname()[1], sock.getsockname()[1]))
        self.assertEquals(sustain_workers_calls, [])

    def test_start_daemoned_parent_side(self):
        self.conf = Conf({'brim': {'port': '0'}, 'wsgi': {}})
        self.conf.files = ['ok.conf']
        self.serv.args = ['start']
        self.serv._parse_args()
        self.serv._parse_conf(self.conf)
        subserv = self.serv.subservers[0]
        subserv._parse_conf(self.conf)
        sustain_workers_calls = []
        open_retval = [StringIO()]
        open_calls = []

        def _sustain_workers(*args, **kwargs):
            sustain_workers_calls.append((args, kwargs))

        @contextmanager
        def _open(*args):
            open_calls.append(args)
            yield open_retval[0]

        orig_sustain_workers = server.sustain_workers
        try:
            server.sustain_workers = _sustain_workers
            server.open = _open
            self.serv._start()
        finally:
            server.sustain_workers = orig_sustain_workers
            del server.open
        self.assertEquals(sustain_workers_calls, [])
        self.assertEquals(open_calls, [('/var/run/brimd.pid', 'w')])
        self.assertEquals(open_retval[0].getvalue(), '12345\n')

    def test_start_daemoned_child_side(self):
        self.conf = Conf({'brim': {'port': '0'}, 'wsgi': {}})
        self.conf.files = ['ok.conf']
        self.serv.args = ['start']
        self.serv._parse_args()
        self.serv._parse_conf(self.conf)
        subserv = self.serv.subservers[0]
        subserv._parse_conf(self.conf)
        sustain_workers_calls = []
        self.fork_retval[0] = 0

        def _sustain_workers(*args, **kwargs):
            sustain_workers_calls.append((args, kwargs))

        orig_sustain_workers = server.sustain_workers
        try:
            server.sustain_workers = _sustain_workers
            self.serv._start()
        finally:
            server.sustain_workers = orig_sustain_workers
        self.assertEquals(sustain_workers_calls,
            [((1, self.serv._start_subserver), {'logger': self.serv.logger})])
        self.assertEquals(self.capture_calls, [
            ((), {'exceptions': self.serv._capture_exception,
                  'stdout_func': self.serv._capture_stdout,
                  'stderr_func': self.serv._capture_stderr})])

    def test_start_daemoned_child_side_console_mode(self):
        self.conf = Conf({'brim': {'port': '0'}, 'wsgi': {}})
        self.conf.files = ['ok.conf']
        self.serv.args = ['-o', 'start']
        self.serv._parse_args()
        self.serv._parse_conf(self.conf)
        subserv = self.serv.subservers[0]
        subserv._parse_conf(self.conf)
        sustain_workers_calls = []
        self.fork_retval[0] = 0

        def _sustain_workers(*args, **kwargs):
            sustain_workers_calls.append((args, kwargs))

        orig_sustain_workers = server.sustain_workers
        try:
            server.sustain_workers = _sustain_workers
            self.serv._start()
        finally:
            server.sustain_workers = orig_sustain_workers
        self.assertEquals(sustain_workers_calls,
            [((1, self.serv._start_subserver), {'logger': self.serv.logger})])
        self.assertEquals(self.capture_calls, [])

    def test_capture_exception(self):
        self.serv.logger = FakeLogger()
        self.serv._capture_exception()
        self.assertEquals(self.serv.logger.error_calls,
                          [("UNCAUGHT EXCEPTION: main None ['None']",)])

        self.serv.logger = FakeLogger()
        try:
            raise Exception('testing')
        except Exception:
            self.serv._capture_exception(*exc_info())
        self.assertEquals(len(self.serv.logger.error_calls), 1)
        self.assertEquals(len(self.serv.logger.error_calls[0]), 1)
        self.assertTrue(self.serv.logger.error_calls[0][0].startswith(
            'UNCAUGHT EXCEPTION: main Exception: testing [\'Traceback '
            '(most recent call last):\''))
        self.assertTrue(self.serv.logger.error_calls[0][0].endswith(
            '    raise Exception(\'testing\')", \'Exception: testing\']'))

    def test_capture_stdout(self):
        self.serv.logger = FakeLogger()
        self.serv._capture_stdout('one\ntwo\nthree\n')
        self.assertEquals(self.serv.logger.info_calls,
            [('STDOUT: main one',), ('STDOUT: main two',),
             ('STDOUT: main three',)])

        self.serv.logger = FakeLogger()
        self.serv._capture_stdout('one\ntwo\nthree\n')
        self.assertEquals(self.serv.logger.info_calls,
            [('STDOUT: main one',), ('STDOUT: main two',),
             ('STDOUT: main three',)])

    def test_capture_stderr(self):
        self.serv.logger = FakeLogger()
        self.serv._capture_stderr('one\ntwo\nthree\n')
        self.assertEquals(self.serv.logger.error_calls,
            [('STDERR: main one',), ('STDERR: main two',),
             ('STDERR: main three',)])

        self.serv.logger = FakeLogger()
        self.serv._capture_stderr('one\ntwo\nthree\n')
        self.assertEquals(self.serv.logger.error_calls,
            [('STDERR: main one',), ('STDERR: main two',),
             ('STDERR: main three',)])


if __name__ == '__main__':
    main()