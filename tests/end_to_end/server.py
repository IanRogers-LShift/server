"""
Servers to assist in testing
"""
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging
import os
import random
import tempfile
import shlex
import string
import subprocess

import requests

import tests.utils as utils


ga4ghPort = 8001
remotePort = 8002


class ServerForTesting(object):
    """
    The base class of a test server
    """
    def __init__(self, port):
        # suppress requests package log messages
        logging.getLogger("requests").setLevel(logging.CRITICAL)
        self.port = port
        self.outFile = None
        self.errFile = None
        self.server = None
        self.serverUrl = "http://localhost:{}".format(self.port)

    def getUrl(self):
        """
        Return the url at which the server is configured to run
        """
        return self.serverUrl

    def getCmdLine(self):
        """
        Return the command line string used to launch the server.
        Subclasses must override this method.
        """
        raise NotImplementedError()

    def start(self):
        """
        Start the server
        """
        assert not self.isRunning(), "Another server is running"
        self.outFile = tempfile.TemporaryFile()
        self.errFile = tempfile.TemporaryFile()
        splits = shlex.split(self.getCmdLine())
        self.server = subprocess.Popen(
            splits, stdout=self.outFile,
            stderr=self.errFile)
        self._waitForServerStartup()

    def shutdown(self):
        """
        Shut down the server
        """
        if self.isRunning():
            self.server.kill()
        if self.server is not None:
            self.server.wait()
            self._assertServerShutdown()
        if self.outFile is not None:
            self.outFile.close()
        if self.errFile is not None:
            self.errFile.close()

    def restart(self):
        """
        Restart the server
        """
        self.shutdown()
        self.start()

    def isRunning(self):
        """
        Returns true if the server is running, false otherwise
        """
        try:
            response = self.ping()
            if response.status_code != 200:
                msg = ("Ping of server returned non-200 status code "
                       "({})").format(response.status_code)
                assert False, msg
            return True
        except requests.ConnectionError:
            return False

    def ping(self):
        """
        Pings the server by doing a GET request to /
        """
        response = requests.get(self.serverUrl)
        return response

    def getOutLines(self):
        """
        Return the lines of the server stdout file
        """
        return utils.getLinesFromLogFile(self.outFile)

    def getErrLines(self):
        """
        Return the lines of the server stderr file
        """
        return utils.getLinesFromLogFile(self.errFile)

    def printDebugInfo(self):
        """
        Print debugging information about the server
        """
        className = self.__class__.__name__
        print('\n')
        print('*** {} CMD ***'.format(className))
        print(self.getCmdLine())
        print('*** {} STDOUT ***'.format(className))
        print(''.join(self.getOutLines()))
        print('*** {} STDERR ***'.format(className))
        print(''.join(self.getErrLines()))

    @utils.Timeout()
    @utils.Repeat()
    def _waitForServerStartup(self):
        self.server.poll()
        if self.server.returncode is not None:
            self._waitForErrLines()
            message = "Server process unexpectedly died; stderr: {0}"
            failMessage = message.format(''.join(self.getErrLines()))
            assert False, failMessage
        return not self.isRunning()

    @utils.Timeout()
    @utils.Repeat()
    def _waitForErrLines(self):
        # not sure why there's some delay in getting the server
        # process' stderr (at least for the ga4gh server)...
        return self.getErrLines() == []

    def _assertServerShutdown(self):
        shutdownString = "Server did not shut down correctly"
        assert self.server.returncode is not None, shutdownString
        assert not self.isRunning(), shutdownString


class Ga4ghServerForTesting(ServerForTesting):
    """
    A ga4gh test server
    """
    def __init__(self):
        super(Ga4ghServerForTesting, self).__init__(ga4ghPort)
        self.configFile = None

    def getConfig(self):
        config = """
SIMULATED_BACKEND_NUM_VARIANT_SETS = 10
SIMULATED_BACKEND_VARIANT_DENSITY = 1
DATA_SOURCE = "__SIMULATED__"
DEBUG = True"""
        return config

    def getCmdLine(self):
        if self.configFile is None:
            self.configFile = tempfile.NamedTemporaryFile()
        config = self.getConfig()
        self.configFile.write(config)
        self.configFile.flush()
        configFilePath = self.configFile.name
        cmdLine = """
python server_dev.py
--dont-use-reloader
--config TestConfig
--config-file {}
--port {} """.format(configFilePath, self.port)
        return cmdLine

    def shutdown(self):
        super(Ga4ghServerForTesting, self).shutdown()
        if self.configFile is not None:
            self.configFile.close()

    def printDebugInfo(self):
        super(Ga4ghServerForTesting, self).printDebugInfo()
        className = self.__class__.__name__
        print('*** {} CONFIG ***'.format(className))
        print(self.getConfig())


class RemoteServerForTesting(ServerForTesting):
    """
    Simulates a remote server on localhost
    """
    def __init__(self, path):
        super(RemoteServerForTesting, self).__init__(remotePort)
        self.path = path
        self.pidFileName = \
            ''.join(random.sample(string.letters, 10)) + '.pid'

    def getCmdLine(self):
        cmdLine = "twistd  --pidfile={} -no web -p {} --path={}".format(
            self.pidFileName, self.port, self.path)
        return cmdLine

    def shutdown(self):
        super(RemoteServerForTesting, self).shutdown()
        if os.path.exists(self.pidFileName):
            os.remove(self.pidFileName)
