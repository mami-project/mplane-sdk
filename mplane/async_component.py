# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
##
# mPlane Software Development Kit
# Component Framework
#
# (c) 2015 mPlane Consortium (http://www.ict-mplane.eu)
# (c) 2016 MAMI Project (http://mami-project.eu)
#     Authors: Brian Trammell <brian@trammell.ch>
#              Stefano Pentassuglia <stefano.pentassuglia@ssbprogetti.it>
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

import asyncio
import aiohttp
import logging
import websockets
import collections

import mplane.model

logger = logging.getLogger(__name__)

class Service(object):
    """
    A Service binds a coroutine to an
    mplane.model.Capability provided by a component.

    To use services with an mPlane scheduler, inherit from
    mplane.component.Service or one of its subclasses
    and implement run().

    """
    def __init__(self, capability):
        self._capability = capability

    def capability(self):
        """Returns the capability belonging to this service"""
        return self._capability

    def set_capability_link(self, link):
        """
        Sets the capability's link section, if it is not already set
        FIXME isn't there a better way to force link sections to point
        to the right place than having the framework reach down and mess
        with capabilities? See #16.
        """
        if self._capability.get_link() is None:
            self._capability.set_link(link)

    def __repr__(self):
        return "<Service for "+repr(self._capability)+">"

class ImmediateService(Service):
    """
    An ImmediateService is a Service whose coroutine gets called
    once per Specification invocation.
    """

    def __init__(self, capability):
        super().__init__(capability)

    async def run(self, specification, check_interrupt):
        """
        Coroutine to execute this service, given a specification 
        which matches the capability. This is called by the scheduler 
        when the specification's temporal scope is current.

        The implementation must run the measurement or query to the end:
        it extracts its parameters from a given Specification, and returns 
        its result values in a Result derived therefrom.

        Long-running run() methods should await any blocking call, and
        periodically yield (await asyncio.sleep()). run() methods should
        periodically call check_interrupt() to determine whether they have
        been interrupted, and return a Result if so.
        """
        raise NotImplementedError("Cannot instantiate an abstract Service")

class PeriodicService(Service):
    """
    An PeriodicService is a longer-running Service whose coroutine gets 
    called once per period specified in its Specification.
    """
    # FIXME work out the details of this
    pass

# Notes on replacing mplane.scheduler.Job:
# Job handles (1) scheduling the start of Tasks at some point in the future
#                 (we can use the runloop for this)
#             (2) cancellation of Tasks on the receipt of Interrupts
#                 (we can use the runloop for this, but need to keep a list 
#                  of pending and running things in Component)
#
# After the end of MultiJob, we'll need a way for 
# a Redemption to trigger a partial Result. 
# (run() gets a partial-result function it should call before awaiting?)
# 
# Actually running services in a ProcessPoolExecutor: 
# see http://stackoverflow.com/questions/22445054/

class ComponentClientContext:
    """
    Represents all the state a Component must keep 
    for a given Client: pending and running Specifications,
    Results, and information for re-establishing a connection to the
    client (for WSClientComponent).

    This class handles keeping all Component state on a per-client
    basis separate.

    When using TLS client certificates with WebSockets (default),
    client contexts are identified by peer identity. When no
    client certificate is available, client contexts are identified
    by peer IP address.

    """

    def __init__(self, cid):
        # Store client ID 
        self._cid = cid

        # Not yet running Specifications by token
        self.pending = {}
        # Running Specifications by token
        self.running = {}
        # Receipts for Specifications by token
        self.receipts = {}
        # Interrupts by token
        self.interrupts = {}
        # Partial and finished Results by token
        self.results = {}

        # Outgoing message queue
        self.outq = collections.deque()

    def purge_results(self):
        # FIXME need to specify API and implement;
        # this method should drop results that were returned
        # more than N seconds ago, and drop stale results,
        # i.e. never sent to a client but generated more than
        # M seconds ago. Add fields to Result to make this happen.
        pass

    def reply(self, msg):
        self.outq.push(msg)
 

class CommonComponent:
    def __init__(self, config):
        # Available services
        self.services = []

        # Client component contexts by client ID
        self._ccc = {}

        self._loop = asyncio.get_event_loop()

        # Add services
        pass

    def _client_context(self, cid):
        """
        Get a client context for a given client ID,
        creating a new one if necessary.

        """
        if cid not in self._ccc:
            self._ccc[cid] = ComponentClientContext(cid, component)
        return self._ccc[cid]

    def _invoke_inner(self, ccc, spec, service):
        token = spec.get_token()

        # then schedule the coroutine
        task = self._loop.create_task(service.run(spec, lambda: token in ccc.interrupts))

        # WORK POINTER do something with the task (a future wrapping the coroutine)

    def _invoke(self, ccc, spec):
        """
        Invoke a Specification in a given client context

        """
        # Find a matching service
        service = None
        for candidate in self.services:
            if spec.fulfills(candidate.capability()):
                if self.azn._check(candidate.capability(), user):
                    service = candidate
                    break

        if not service:
            logger.warning("no capability for "+repr(spec))
            return mplane.model.Exception(token=token, errmsg="no capability matches specification")

        token = spec.get_token()

        # determine when to schedule it
        if spec.is_schedulable():
            # Schedulable. Try to do so.
            (start_delay, end_delay) = spec.get_when().timer_delays()
            if start_delay is None:
                # Too late. This is a no-op.
                # FIXME really an exception?
                return mplane.model.Exception(token=token, errmsg="specification already expired")
            
            # Start the interrupt timer
            self._loop.call_later(end_delay, lambda: self._interrupt(ccc, token))

            if start_delay == 0:
                self._invoke_inner(service, spec)
            else:
                self._loop.call_later(start_delay, lambda: self._invoke_inner(ccc, spec, service))
        else:
            # no need to mess with timers, just run the thing
            self._invoke_inner(service, spec)

        # schedule it

        # add to pending or running
        pass

    def _redeem(self, ccc, msg):
        """
        Given a redemption and a client context, return an
        appropriate result. 

        """
        #
        pass

    def _interrupt(self, ccc, token):
        """
        Interrupt a running Specification in this client context

        """
        pass

    def message_from(jmsg, cid):
        """
        Handle a JSON message from a given client ID.

        """
        # Get client context
        ccc = self._client_context(cid)

        # Parse message
        msg = mplane.model.parse_json(jmsg)
        token = msg.get_token()

        reply = None
        if isinstance(msg, mplane.model.Specification):
            if token in ccc.pending or token in ccc.running:
                # Specification already submitted. Idempotent.
                reply = ccc.receipts[token]
            elif token in check_for_specs.results:
                # Specification already submitted and results are available.
                reply = ccc.results[token]
            else:
                # Specification we know nothing about. Invoke it.
                # (Note that Redemptions can be used to )
                reply = self._invoke(ccc, msg)
        elif isinstance(msg, mplane.model.Redemption):
            if token in ccc.results:
                # We have some results. Redeem, and do partial redemption 
                # according to redemption's temporal scope as appropriate
                reply = self._redeem(ccc, msg)
            elif token in ccc.receipts:
                # We have a receipt. Return it.
                reply = ccc.receipts[token]
            else:
                # We've never seen this redemption before. Try to invoke it?
                reply = self._invoke(ccc, msg)
        elif isinstance(msg, mplane.model.Interrupt):
            if token in ccc.pending or token in ccc.running:
                # Interrupt.
                reply = self._interrupt(ccc, token)
            else:
                reply = mplane.model.Exception(token=token, errmsg="interrupt for unknown specification")
                logger.warning(repr(msg)+" for unknown task")
        else:
            reply = mplane.model.Exception(token=token, errmsg="bad message type for component")
            logger.warning("component cannot handle message "+repr(msg))

        # Stick the reply in our outgoing message queue
        ccc.reply(reply)

class WSServerComponent(CommonComponent):
    pass

class WSClientComponent(CommonComponent):
    pass



#########################################################################
# Old code down here
#########################################################################





import mplane.utils
import mplane.model
import mplane.azn
import mplane.tls
import importlib
import logging
import asyncio
import websockets

from datetime import datetime
import time
import urllib3
import threading
import socket
import random

# FIXME HACK
# some urllib3 versions let you disable warnings about untrusted CAs,
# which we use a lot in the project demo. Try to disable warnings if we can.
try:
    urllib3.disable_warnings()
except:
    pass

import json

logger = logging.getLogger(__name__)

DEFAULT_MPLANE_PORT = 8890
SLEEP_QUANTUM = 0.250

def peer_identity(websocket):
    """
    Extract the peer identity from a websocket.
    This is currently defined as the remote address.
    We really need to get information out of the websocket's SSL/TLS context,
    only falling back to remote address when insecure 
    """
    return websocket.remote_address


class CommonComponent(object):
    """
    Implements protocol-independent Component functionality: 
    contains a Scheduler for exposing Services and running Jobs,
    initializes registry.
    """

    # FIXME
    # This class should also handle incoming and 
    # outgoing message queues on a per-client basis.
    #

    def __init__(self, config):
        # Stash configuration
        self.config = config

        # Initialize registry
        registry_uri = None
        if config is not None:
            if "Registries" in config:
                if "preload" in config["Registries"]:
                    for reg in config["Registries"]["preload"]:
                        mplane.model.preload_registry(reg)
                if "default" in config["Registries"]:
                    registry_uri = config["Registries"]["default"]       

        mplane.model.initialize_registry(registry_uri)

        # Intialize TLS state
        self._tls = mplane.tls.TlsState(self.config)

        # Initialize scheduler
        self._scheduler = mplane.scheduler.Scheduler(self.config)
        for service in self._load_services():
            self._scheduler.add_service(service)

        # Immediate reply delay in seconds
        self._immediate_delay = 3

    def _load_services(self):
        services = []
        if config is not None:
            # load all the modules that are present in the 'Modules' section
            if "Modules" in self.config["Component"]:
                for mod_name in self.config["Component"]["Modules"]:
                    module = importlib.import_module(mod_name)
                    kwargs = {}
                    for arg in self.config["Component"]["Modules"][mod_name]:
                            kwargs[arg] = self.config["Component"]["Modules"][mod_name][arg]
                    for service in module.services(**kwargs):
                        services.append(service)
        return services

     def remove_capability(self, capability):
        for service in self.scheduler.services:
            # FIXME add the ability to do a  == on the capabilities to model
            if service.capability().get_token == capability.get_token():
                self.scheduler.remove_service(service)
                return

        # Fall through: warn on no matching capability
        logger.warning("can't remove capability, no service matches "+repr(capability))

    def message_from(jmsg, client_id):
        """
        Handle a message from a given client
        """

        # Parse message
        msg = mplane.model.parse_json(jmsg)

        # Hand it to the scheduler
        reply = self.scheduler.process_message(client_id, msg)

        # If we got a receipt, wait a bit for the scheduler to 
        # process it to save a roundtrip
        if self._immediate_delay > 0 and \
                isinstance(msg, mplane.model.Specification) and \
                isinstance(reply, mplane.model.Receipt):
            job = self.scheduler.job_for_message(reply)
            wait_start = datetime.utcnow()
            while (datetime.utcnow() - wait_start).total_seconds() < self._immediate_delay:
                # FIXME this gets called from a coroutine, so slow
                time.sleep(SLEEP_QUANTUM)
                if job.failed() or job.finished():
                    reply = job.get_reply()
                    break

        

class WebsocketListenerComponent(CommonComponent):

    def __init__(self, config):
        super().__init__(config)

        self._server = websockets.server.serve(self.handle_client)

    def handle_client(self, websocket, uri):
        # Get the client's identity from the peer address
        client_id = peer_identity(websocket)

        while self._running:
            try:
                self.message_from(await websocket.recv(), client_id)
            except ConnectionClosed:
                break

class WebsocketInitiatorComponent(CommonComponent):

    def __init__(self, config):
        super().__init__(config)

def initialize_components_for(config):
    """
    Given a configuration, initialize appropriate component(s) 
    and return them.
    """
    pass

#########################################################################
# Really old code down here
#########################################################################


class BaseComponent(object):

    def __init__(self, config):
        self.config = config

        # registry initialization phase (preload + fetch from URI)
        registry_uri = None
        if config is not None:
            if "Registries" in config:
                if "preload" in config["Registries"]:
                    for reg in config["Registries"]["preload"]:
                        mplane.model.preload_registry(reg)
                if "default" in config["Registries"]:
                    registry_uri = config["Registries"]["default"]

        mplane.model.initialize_registry(registry_uri)
        self.tls = mplane.tls.TlsState(self.config)
        self.scheduler = mplane.scheduler.Scheduler(config)

        self._ipaddresses = None  # list of IPs to listen on, if the component is Listener

        services = self._load_services()

        # Iterate over services, fixing up link sections
        if config is not None and "Listener" in config["Component"]:
            if "interfaces" in config["Component"]["Listener"] and \
                               config["Component"]["Listener"]["interfaces"]:
                self._ipaddresses = config["Component"]["Listener"]["interfaces"]

                if len(self._ipaddresses) == 1:
                    # Only do link fix-up if we have only one IP address. If listening 
                    # on multiple, need to delegate link fix-up to the request handlers 
                    # (see DiscoveryHandler._respond_capability())
                    if "TLS" in config:
                        link = "https://"
                    else:
                        link = "http://"
                    link += config["Component"]["Listener"]["interfaces"][0] + ":"
                    link += config["Component"]["Listener"]["port"] + SPECIFICATION_PATH_ELEM

                    for service in services:
                        service.set_capability_link(link)

        # Now add all the services to the scheduler
        for service in services:
            self.scheduler.add_service(service)



class ListenerHttpComponent(BaseComponent):
    def __init__(self, config, io_loop=None, as_daemon=False):
        self._port = DEFAULT_MPLANE_PORT
        if config is not None and "Component" in config and "Listener" in config["Component"]:
            if "port" in config["Component"]["Listener"]:
                self._port = int(config["Component"]["Listener"]["port"])

        self._path = SPECIFICATION_PATH_ELEM

        super(ListenerHttpComponent, self).__init__(config)

        application = tornado.web.Application([
            (r"/", MessagePostHandler, {'scheduler': self.scheduler, 'tlsState': self.tls}),
            (r"/" + CAPABILITY_PATH_ELEM, DiscoveryHandler, {'scheduler': self.scheduler,
                                                             'tlsState': self.tls,
                                                             'config': config}),
            (r"/" + CAPABILITY_PATH_ELEM + "/.*", DiscoveryHandler, {'scheduler': self.scheduler,
                                                                     'tlsState': self.tls,
                                                                     'config': config}),
        ])

        http_server = tornado.httpserver.HTTPServer(
                                application,
                                ssl_options=self.tls.get_ssl_options())

        # run the server
        if self._ipaddresses is not None:
            for ip in self._ipaddresses:
                http_server.listen(self._port, ip)
        else:
            http_server.listen(self._port)

        logger.info("ListenerHttpComponent running on port " + str(self._port))
        comp_t = Thread(target=self.listen_in_background, args=(io_loop,))
        comp_t.setDaemon(as_daemon)
        comp_t.start()

    def listen_in_background(self, io_loop):
        """ The component listens for requests in background """
        if io_loop is None:
            tornado.ioloop.IOLoop.instance().start()

class MPlaneHandler(tornado.web.RequestHandler):
    """
    Abstract tornado RequestHandler that allows a
    handler to respond with an mPlane Message or an Exception.

    """
    def _respond_message(self, msg):
        self.set_status(200)
        self.set_header("Content-Type", "application/x-mplane+json")
        self.write(mplane.model.unparse_json(msg))
        self.finish()

    def _respond_error(self, errmsg=None, exception=None, token=None, status=400):
        if exception:
            if len(exception.args) == 1:
                errmsg = str(exception.args[0])
            else:
                errmsg = repr(exception.args)

        elif errmsg is None:
            raise RuntimeError("_respond_error called without message or exception")

        mex = mplane.model.Exception(token=token, errmsg=errmsg)
        self.set_status(status)
        self.set_header("Content-Type", "application/x-mplane+json")
        self.write(mplane.model.unparse_json(mex))
        self.finish()

class DiscoveryHandler(MPlaneHandler):
    """
    Exposes the capabilities registered with a given scheduler.
    URIs ending with "capability" will result in an HTML page
    listing links to each capability.

    """

    def initialize(self, scheduler, tlsState, config):
        self.scheduler = scheduler
        self.tls = tlsState
        self.config = config

    def get(self):
        # capabilities
        path = self.request.path.split("/")[1:]
        if path[0] == CAPABILITY_PATH_ELEM:
            if len(path) == 1 or path[1] is None:
                self._respond_capability_links()
            else:
                self._respond_capability(path[1])
        else:
            self._respond_error(errmsg="I only know how to handle /"+CAPABILITY_PATH_ELEM+" URLs via HTTP GET", status=405)

    def _respond_capability_links(self):
        self.set_status(200)
        self.set_header("Content-Type", "text/html")
        self.write("<html><head><title>Capabilities</title></head><body>")
        no_caps_exposed = True
        for key in self.scheduler.capability_keys():
            if (not isinstance(self.scheduler.capability_for_key(key), mplane.model.Withdrawal) and
                    self.scheduler.azn.check(self.scheduler.capability_for_key(key),
                                             self.tls.extract_peer_identity(self.request))):
                no_caps_exposed = False
                self.write("<a href='/capability/" + key + "'>" + key + "</a><br/>")
        self.write("</body></html>")

        if no_caps_exposed is True:
            logger.warning("Discovery: no capabilities available to "+ 
                            self.tls.extract_peer_identity(self.request)+
                            ", check authorizations")
        self.finish()

    def _respond_capability(self, key):
        cap = self.scheduler.capability_for_key(key)

        # if the 'link' field is empty, compose it using the host requested by the client/supervisor
        if not cap.get_link():
            if self.config is not None and "TLS" in self.config:
                link = "https://"
            else:
                link = "http://"
            link = link + self.request.host + SPECIFICATION_PATH_ELEM
            cap.set_link(link)
        self._respond_message(cap)

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
        self.write("This is a client-initiated mPlane component. POST mPlane messages to this URL to use.<br/>")
        self.write("<a href='/"+CAPABILITY_PATH_ELEM+"'>Capabilities</a> provided by this server:<br/>")
        for key in self.scheduler.capability_keys():
            if (not isinstance(self.scheduler.capability_for_key(key), mplane.model.Withdrawal) and
                    self.scheduler.azn.check(self.scheduler.capability_for_key(key),
                                             self.tls.extract_peer_identity(self.request))):
                self.write("<br/><pre>")
                self.write(mplane.model.unparse_json(self.scheduler.capability_for_key(key)))
        self.write("</body></html>")
        self.finish()

    def post(self):
        # unwrap json message from body
        if (self.request.headers["Content-Type"] == "application/x-mplane+json"):
            try:
                msg = mplane.model.parse_json(self.request.body.decode("utf-8"))
            except Exception as e:
                self._respond_error(exception=e)
        else:
            self._respond_error(errmsg="I only know how to handle mPlane JSON messages via HTTP POST", status="406")

        # check if requested capability is withdrawn
        is_withdrawn = False
        if isinstance(msg, mplane.model.Specification):
            for key in self.scheduler.capability_keys():
                cap = self.scheduler.capability_for_key(key)
                if msg.fulfills(cap) and isinstance(cap, mplane.model.Withdrawal):
                    is_withdrawn = True
                    self._respond_message(cap)

        if not is_withdrawn:
            # hand message to scheduler
            reply = self.scheduler.process_message(self.tls.extract_peer_identity(self.request), msg)

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

    def __init__(self, config, supervisor=False):
        self._supervisor = supervisor
        self._callback_token = "comp-cb" + str(random.random())
        super(InitiatorHttpComponent, self).__init__(config)

        # configuration of URLs that will be used for requests
        if self.config is not None and "Component" in self.config and "Initiator" in self.config["Component"]:
            if ("capability-url" in self.config["Component"]["Initiator"]
                and "specification-url" in self.config["Component"]["Initiator"]
                and "result-url" in self.config["Component"]["Initiator"]):
                self.registration_url = urllib3.util.parse_url(
                    self.config["Component"]["Initiator"]["capability-url"])
                self.specification_url = urllib3.util.parse_url(
                    self.config["Component"]["Initiator"]["specification-url"])
                self.result_url = urllib3.util.parse_url(
                    self.config["Component"]["Initiator"]["result-url"])
            elif "url" in self.config["Component"]["Initiator"]:
                self.registration_url = urllib3.util.parse_url(self.config["Component"]["Initiator"]["url"])
                self.specification_url = self.registration_url
                self.result_url = self.registration_url
            else:
                raise ValueError("Config file is missing information on URLs in Component.Initiator. "
                                 "See documentation for details")
        else:
            self.registration_url = urllib3.util.parse_url(DEFAULT_CAPABILITY_URL)
            self.specification_url = urllib3.util.parse_url(DEFAULT_SPECIFICATION_URL)
            self.result_url = urllib3.util.parse_url(DEFAULT_RESULT_URL)

        self.pool = self.tls.pool_for(self.registration_url.scheme,
                                      self.registration_url.host,
                                      self.registration_url.port)

        self._result_url = dict()
        self.register_to_client()

        self._callback_lock = threading.Lock()

        # periodically poll the Client/Supervisor for Specifications
        t = Thread(target=self.check_for_specs)
        t.start()

    def register_to_client(self, caps=None):
        """
        Sends a list of capabilities to the Client, in order to register them
        """
        env = mplane.model.Envelope()

        logger.info("Component: registering my capabilities to "+self.registration_url)

        # try to register capabilities, if URL is unreachable keep trying every 5 seconds
        connected = False
        while not connected:
            try:
                self._client_identity = self.tls.extract_peer_identity(self.registration_url)
                connected = True
            except:
                logger.info("Component: client unreachable, will retry in "+str(RETRY_QUANTUM)+" sec.")
                sleep(RETRY_QUANTUM)

        # If caps is not None, register them
        if caps is not None:
            for cap in caps:
                if self.scheduler.azn.check(cap, self._client_identity):
                    env.append_message(cap)
        else:
            # generate the envelope containing the capability list
            no_caps_exposed = True
            for key in self.scheduler.capability_keys():
                cap = self.scheduler.capability_for_key(key)
                if self.scheduler.azn.check(cap, self._client_identity):
                    env.append_message(cap)
                    no_caps_exposed = False

            if no_caps_exposed is True:
                logger.warning("Component: no capabilities available to "+ 
                                self._client_identity +", check authorizations")
                if not self._supervisor:
                    exit(0)

            # add callback capability to the list
            # FIXME NOOO see issue #3
            callback_cap = mplane.model.Capability(label="callback", 
                when = "now ... future", token = self._callback_token)
            
            env.append_message(callback_cap)

        # send the envelope to the client
        res = self.send_message(self.registration_url, "POST", env)

        # handle response message

        if res.status == 200:
            logger.info("Component: successfully registered to "+self.registration_url)
            # FIXME this does not appear to have anything 
            # to do with the protocol specification, see issue #4
            # body = json.loads(res.data.decode("utf-8"))
            # print("\nCapability registration outcome:")
            # for key in body:
            #     if body[key]['registered'] == "ok":
            #         print(key + ": Ok")
            #     else:
            #         print(key + ": Failed (" + body[key]['reason'] + ")")
            # print("")
        else:
            logger.critical("Capability registration to "+self.registration_url+" failed:"+
                             str(res.status) + " - " + res.data.decode("utf-8"))

    def check_for_specs(self):
        """
        Poll the client for specifications

        """
        while True:
            # FIXME configurable default idle time.
            self.idle_time = 5

            # try to send a request for specifications. If URL is unreachable means that the Supervisor (or Client) has
            # most probably died, so we need to re-register capabilities
            try:
                logger.info("Polling for specifications at " + self.specification_url)
                res = self.send_message(self.specification_url, "GET")
            except Exception as e:
                logger.warning("Specification poll at " + self.specification_url + "failed :" + repr(e))
                logger.warning("Attempting reregistration")
                self.register_to_client()

            if res.status == 200:
                # specs retrieved: split them if there is more than one
                env = mplane.model.parse_json(res.data.decode("utf-8"))
                for spec in env.messages():
                    # handle callbacks
                    # FIXME NO NO NO see issue #3
                    if spec.get_label() == "callback":
                        self.idle_time = spec.when().timer_delays()[1]
                        break

                    # hand spec to scheduler, making sure the callback is called after
                    with self._callback_lock:
                        reply = self.scheduler.process_message(self._client_identity, spec, callback=self.return_results)
                        if not isinstance(spec, mplane.model.Interrupt):
                            self._result_url[spec.get_token()] = spec.get_link()

                        # send receipt to the Client/Supervisor
                        res = self.send_message(self._result_url[spec.get_token()], "POST", reply)

            # not registered on supervisor, need to re-register
            # FIXME what's 428 for? See issue #4
            elif res.status == 428:
                logger.warning("Specification poll got 428, attempting reregistration")
                self.register_to_client()

            else:
                logger.critical("Specification poll to "+self.specification_url+" failed:"+
                                 str(res.status) + " - " + res.data.decode("utf-8"))
 
            sleep(self.idle_time)
 
    def return_results(self,receipt):
        """
        Checks if a job is complete, and in case sends it to the Client/Supervisor

        """
        #wait for scheduling process above
        with self._callback_lock:
            pass
        job = self.scheduler.job_for_message(receipt)
        reply = job.get_reply()

        # check if job is completed
        if (job.finished() is not True and
                job.failed() is not True):
            logger.debug("Component: not returning partial result (%s len: %d, label: %s)" 
                          % (type(reply).__name__, len(reply), reply.get_label()))
            return

        # send result to the Client/Supervisor
        res = self.send_message(self._result_url[reply.get_token()], "POST", reply)

        # handle response
        label = reply.get_label()

        if res.status == 200:
            logger.info("posted "+ repr(reply) +
                         " to "+self._result_url[reply.get_token()])
        else:
            logger.critical("Result post to "+self._result_url[reply.get_token()]+" failed:"+
                                 str(res.status) + " - " + res.data.decode("utf-8"))

    def send_message(self, url_or_str, method, msg=None):
        # if the URL is empty (meaning that the 'link' section was empty), use the default url for results
        if not url_or_str:
            url_or_str = self.result_url

        if isinstance(url_or_str, str):
            url = urllib3.util.parse_url(url_or_str)
        else:
            url = url_or_str

        # if the URL has a different host from the one used for 
        # capabilities registration, we need a new connectionPool
        if self.pool.is_same_host(mplane.utils.unparse_url(url)):
            pool = self.pool
        else:
            pool = self.tls.pool_for(url.scheme, url.host, url.port)

        if method == "POST" and msg is not None:
            # post message
            res = pool.urlopen('POST', url.path,
                               body=mplane.model.unparse_json(msg).encode("utf-8"),
                               headers={"content-type": "application/x-mplane+json"})
        elif method == "GET":
            # get message
            res = pool.request('GET', url.path)

        return res

    def remove_capability(self, capability):
        super(InitiatorHttpComponent, self).remove_capability(capability)
        withdrawn_cap = mplane.model.Withdrawal(capability=capability)
        self.register_to_client([withdrawn_cap])
