#
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
##
# mPlane Protocol Reference Implementation
# Authorization context for mPlane components
#
# (c) 2015 mPlane Consortium (http://www.ict-mplane.eu)
#     Author: Stefano Pentassuglia <stefano.pentassuglia@ssbprogetti.it>
#             Brian Trammell <brian@trammell.ch>
#
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
#

import mplane.utils
import mplane.model
import mplane.azn
import mplane.tls
import importlib
import configparser
import tornado.web
import tornado.httpserver
from datetime import datetime
import time

SLEEP_QUANTUM = 0.250
CAPABILITY_PATH_ELEM = "capability"

class BaseComponent(object):
    
    def __init__(self, config_file):
        mplane.model.initialize_registry()
        self.config = mplane.utils.search_path(config_file)
        self.tls = mplane.tls.TlsState(self.config)
        self.scheduler = mplane.scheduler.Scheduler(mplane.azn.Authorization(self.config))
        for service in self._services():
            self.scheduler.add_service(service)
    
    def _services(self):
        # Read the configuration file
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(mplane.utils.search_path(self.config))
        services = []
        for section in config.sections():
            if section.startswith("module_"):
                module = importlib.import_module(config[section]["module"])
                kwargs = {}
                for arg in config[section]:
                    if not arg.startswith("module"):
                        kwargs[arg] = config[section][arg]
                for service in module.services(**kwargs):
                    services.append(service)
        return services

class ListenerHttpComponent(BaseComponent):
    
    def __init__(self, config_file, port = 8888):
        super(ListenerHttpComponent, self).__init__(config_file)
        
        application = tornado.web.Application([
            (r"/", MessagePostHandler, dict(scheduler=self.scheduler, tlsState=self.tls)),
            (r"/"+CAPABILITY_PATH_ELEM, DiscoveryHandler, {'scheduler': self.scheduler, 'tlsState': self.tls}),
            (r"/"+CAPABILITY_PATH_ELEM+"/.*", DiscoveryHandler, {'scheduler': self.scheduler, 'tlsState': self.tls})
        ])
        http_server = tornado.httpserver.HTTPServer(application, ssl_options=self.tls.get_ssl_options())
        http_server.listen(port)
        tornado.ioloop.IOLoop.instance().start()

class MPlaneHandler(tornado.web.RequestHandler):
    """
    Abstract tornado RequestHandler that allows a 
    handler to respond with an mPlane Message.

    """
    def _respond_message(self, msg):
        self.set_status(200)
        self.set_header("Content-Type", "application/x-mplane+json")
        self.write(mplane.model.unparse_json(msg))
        self.finish()

class DiscoveryHandler(MPlaneHandler):
    """
    Exposes the capabilities registered with a given scheduler. 
    URIs ending with "capability" will result in an HTML page 
    listing links to each capability. 

    """

    def initialize(self, scheduler, tlsState):
        self.scheduler = scheduler
        self.tls = tlsState

    def get(self):
        # capabilities
        path = self.request.path.split("/")[1:]
        if path[0] == CAPABILITY_PATH_ELEM:
            if (len(path) == 1 or path[1] is None):
                self._respond_capability_links()
            else:
                self._respond_capability(path[1])
        else:
            # FIXME how do we tell tornado we don't want to handle this?
            raise ValueError("I only know how to handle /"+CAPABILITY_PATH_ELEM+" URLs via HTTP GET")

    def _respond_capability_links(self):
        self.set_status(200)
        self.set_header("Content-Type", "text/html")
        self.write("<html><head><title>Capabilities</title></head><body>")
        for key in self.scheduler.capability_keys():
            if self.scheduler.azn.check(self.scheduler.capability_for_key(key), self.tls.extract_peer_identity(self.request)):
            	self.write("<a href='/capability/" + key + "'>" + key + "</a><br/>")
        self.write("</body></html>")
        self.finish()

    def _respond_capability(self, key):
        self._respond_message(self.scheduler.capability_for_key(key))

class MessagePostHandler(MPlaneHandler):
    """
    Receives mPlane messages POSTed from a client, and passes them to a 
    scheduler for processing. After waiting for a specified delay to see 
    if a Result is immediately available, returns a receipt for future
    redemption.

    """
    def initialize(self, scheduler, tlsState, immediate_ms = 5000):
        self.scheduler = scheduler
        self.tls = tlsState
        self.immediate_ms = immediate_ms

    def get(self):
        # message
        self.set_status(200)
        self.set_header("Content-Type", "text/html")
        self.write("<html><head><title>mplane.httpsrv</title></head><body>")
        self.write("This is an mplane.httpsrv instance. POST mPlane messages to this URL to use.<br/>")
        self.write("<a href='/"+CAPABILITY_PATH_ELEM+"'>Capabilities</a> provided by this server:<br/>")
        for key in self.scheduler.capability_keys():
            if self.scheduler.azn.check(self.scheduler.capability_for_key(key), self.tls.extract_peer_identity(self.request)):
                self.write("<br/><pre>")
                self.write(mplane.model.unparse_json(self.scheduler.capability_for_key(key)))
        self.write("</body></html>")
        self.finish()

    def post(self):
        # unwrap json message from body
        if (self.request.headers["Content-Type"] == "application/x-mplane+json"):
            msg = mplane.model.parse_json(self.request.body.decode("utf-8"))
        else:
            # FIXME how do we tell tornado we don't want to handle this?
            raise ValueError("I only know how to handle mPlane JSON messages via HTTP POST")

        # hand message to scheduler
        reply = self.scheduler.receive_message(self.user, msg)

        # wait for immediate delay
        if self.immediate_ms > 0 and \
           isinstance(msg, mplane.model.Specification) and \
           isinstance(reply, mplane.model.Receipt):
            job = self.scheduler.job_for_message(reply)
            wait_start = datetime.utcnow()
            while (datetime.utcnow() - wait_start).total_seconds() * 1000 < self.immediate_ms:
                time.sleep(SLEEP_QUANTUM)
                if job.failed() or job.finished():
                    reply = job.get_reply()
                    break

        # return reply
        self._respond_message(reply)
    
class InitiatorHttpComponent(BaseComponent):
    pass

if __name__ == "__main__":
    
    # ONLY FOR TEST PURPOSES
    comp = ListenerHttpComponent("./conf/component.conf")