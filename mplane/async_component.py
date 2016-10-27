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
import logging
import websockets
import collections

import mplane.model
import mplane.azn
import mplane.tls
import uuid

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

    def __repr__(self):
        return "<Service for "+repr(self._capability)+">"

# Notes on replacing mplane.scheduler.Job:
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

    """

    def __init__(self, clid, url=None):
        # Store connection URL and client identity
        self.url = url
        self.clid = clid

        # Tasks for running Services by token
        self.tasks = {}
        # Receipts for Specifications by token
        self.receipts = {}
        # Pending interrupts by token
        self.interrupts = {}
        # Available Results by token
        self.results = {}

        # FIXME how to handle partial results?

        # Outgoing message queue
        self.outq = asyncio.Queue()

        logger.debug("created: "+repr(self))

    def interrupt(self, token):
        """
        Interrupt a running Specification in this client context

        """        
        logger.debug("interrupt "+str(token)+" in "+repr(self))
        self.interrupts[token] = True

    def interrupted(self, token):
        """
        Check for an interrupt given a token in this client context

        """
        return token in self.interrupts

    def purge_results(self):
        # FIXME need to specify API and implement;
        # this method should drop results that were returned
        # more than N seconds ago, and drop stale results,
        # i.e. never sent to a client but generated more than
        # M seconds ago. These should be configuable.
        # Add fields to Result to make this happen.
        pass

    def reply(self, msg):
        self.outq.put_nowait(msg)

    def __repr__(self):
        return "ComponentClientContext(%s, %s)" % (repr(self.clid), repr(self.url))

class CommonComponent:
    """
    Core implementation of a generic asynchronous component.
    Used for common component state management for WSServerComponent 
    and WSClientComponent.

    """

    def __init__(self, config):
        # Client component contexts by client ID
        self._ccc = {}
        self._loop = asyncio.get_event_loop()

        # get an authorization object
        self.azn = mplane.azn.Authorization(config)

        # stach config and load services
        self.config = config
        self._reload_configured_services()

    def _reload_configured_services(self):
        self.services = []

        if self.config is not None and \
                "Component" in self.config and \
                "Modules" in self.config["Component"]:
            for mod_name in self.config["Component"]["Modules"]:
                module = importlib.import_module(mod_name)
                kwargs = {}
                for arg in self.config["Component"]["Modules"][mod_name]:
                    kwargs[arg] = self.config["Component"]["Modules"][mod_name][arg]
                for service in module.services(**kwargs):
                    services.append(service)

    def _client_context(self, clid, url=None):
        """
        Get a client context for a given client ID,
        creating a new one if necessary.

        """
        if clid not in self._ccc:
            self._ccc[clid] = ComponentClientContext(clid, url)
        return self._ccc[clid]

    async def _async_reply(self, ccc, service_task):
        # wait until the task is complete
        done, pending = await asyncio.wait([service_task])
        if service_task in done:
            ccc.reply(service_task.result())

    def _invoke_inner(self, ccc, spec, service):
        # schedule a coroutine to run the service and stash the task
        token = spec.get_token()
        task = self._loop.create_task(service.run(spec, lambda: ccc.interrupted(token)))
        ccc.tasks[token] = task
        logger.info("invoke "+repr(spec))

        # schedule a coroutine to await the service task and send a reply
        self._loop.create_task(self._async_reply(ccc, task))

    def _invoke(self, ccc, spec):
        """
        Invoke a Specification in a given client context

        """
        # Find a matching service
        service = None
        for candidate in self.services:
            if spec.fulfills(candidate.capability()):
                if self.azn.check(candidate.capability(), ccc.clid):
                    service = candidate
                    break

        if not service:
            logger.warning("no capability for "+repr(spec))
            return mplane.model.Exception(token=token, errmsg="no capability matches specification")

        token = spec.get_token()

        # determine when to schedule it
        if spec.is_schedulable():
            # Schedulable. Try to do so.
            (start_delay, end_delay) = spec.when().timer_delays()
            if start_delay is None:
                # Too late. This is a no-op.
                # FIXME really an exception?
                logger.warning("specification already expired: "+repr(spec))
                return mplane.model.Exception(token=token, errmsg="specification already expired")
            
            # Start the interrupt timer if necessary
            if end_delay:
                logger.debug("will interrupt in %.2fs: %s" % (end_delay, repr(spec)))
                self._loop.call_later(end_delay, lambda: ccc.interrupt(token))

            # Delay start if necessary
            if start_delay == 0:
                self._invoke_inner(ccc, spec, service)
            else:
                logger.debug("will start in %.2fs: %s" % (start_delay, repr(spec)))
                self._loop.call_later(start_delay, lambda: self._invoke_inner(ccc, spec, service))
        else:
            # Not schedulable, just run the thing.
            self._invoke_inner(ccc, spec, service)

        # Stash and return a receipt
        ccc.receipts[token] = mplane.model.Receipt(specification=spec)
        return ccc.receipts[token]

    def message_from(self, msg, ccc):
        """
        Handle a (parsed) message from a given client.

        """
        token = msg.get_token()

        reply = None
        if isinstance(msg, mplane.model.Envelope):
            for emsg in msg.messages():
                self.message_from(emsg, ccc)
            return
        elif isinstance(msg, mplane.model.Exception):
            logger.error("exception from "+repr(ccc)+": "+repr(msg))
            return
        elif (  isinstance(msg, mplane.model.Specification) or 
                isinstance(msg, mplane.model.Redemption)):
            if token in ccc.results:
                # Results are available. Treat as redemption.
                reply = ccc.results[token]
                logger.debug("returned existing result for "+repr(msg))
            elif token in ccc.tasks and ccc.tasks[token].done():
                # Specification invoked and complete, 
                # remove from running state.
                ccc.results[token] = ccc.tasks[token].result()
                try:
                    del(ccc.tasks[token])
                    del(ccc.receipts[token])
                    del(ccc.interrupts[token])
                except:
                    pass
                reply = ccc.results[token]
                logger.debug("completed task for "+repr(msg))
            elif token in ccc.receipts:
                # We have a receipt, return it
                reply = ccc.receipts[token]
                logger.debug("returned receipt for "+repr(msg))
            else:
                # Know nothing about this spec. Try to invoke it.
                reply = self._invoke(ccc,msg)
        elif isinstance(msg, mplane.model.Interrupt):
            if token in ccc.receipts:
                reply = ccc.interrupt(token)
            else:
                reply = mplane.model.Exception(token=token, errmsg="interrupt for specification not running")
                logger.warning(repr(msg)+" for unknown task")
        else:
            reply = mplane.model.Exception(token=token, errmsg="bad message type for component")
            logger.warning("component cannot handle message "+repr(msg))

        # Stick the JSON reply in our outgoing message queue
        ccc.reply(reply)

#######################################################################
# Websocket server component
#######################################################################

def websocket_clid(websocket, path=None):
    """
    Get a client ID from the websocket's peer certificate (for wss:// URLs),
    allow the client to provide a client ID on the websocket path 
    (for ws:// URLs), or default to a UUID for anonymous clients

    """ 

    # Extract CID from subject common name 
    # (see https://docs.python.org/3/library/ssl.html#ssl.SSLSocket.getpeercert)
    # Problem: WebSocketServerProtocol doesn't implement get_extra_info :(
    # Possible solution: look at the source and use private fields :(
    #
    # peercert = websocket.get_extra_info("peercert", default=None)
    # if peercert:
    #     for rdn in peercert['subject']:
    #         if rdn[0][0] == "commonName":
    #             return rdn[0][1]

    # No peer cert. Extract CID from path
    if path and path != "/":
        return path

    # No peer cert and no path. Generate a UUID for an anonymous client
    return str(uuid.uuid4())

class WSServerComponent(CommonComponent):
    """
    A Component which acts as a WebSockets server
    (for client-initiated connection establishment). 
    """
    
    def __init__(self, config):
        super().__init__(config)

        # Shutdown events
        self._sde = asyncio.Event()

        # Connection information
        interface = config["Component"]["WSListener"]["interface"]
        port = int(config["Component"]["WSListener"]["port"])
        tls = mplane.tls.TlsState(config)
        
        # Coroutine to bring the server up
        self._start_server = websockets.server.serve(self.serve, interface, port, ssl=tls.get_ssl_context())

    async def serve(self, websocket, path):
        # get my client context
        ccc = self._client_context(websocket_clid(websocket, path))
        logger.debug("component got connection from "+ccc.clid)

        try:
            # dump all capabilities the client can use in an envelope
            cap_envelope = mplane.model.Envelope()
            for service in self.services:
                if self.azn.check(service.capability(), ccc.clid):
                    cap_envelope.append_message(service.capability())
            await websocket.send(mplane.model.unparse_json(cap_envelope))

            # now exchange messages forever
            while not self._sde.is_set():

                rx = asyncio.ensure_future(websocket.recv())
                tx = asyncio.ensure_future(ccc.outq.get())
                sd = asyncio.ensure_future(self._sde.wait())

                done, pending = await asyncio.wait([rx, tx], 
                                    return_when=asyncio.FIRST_COMPLETED)

                if rx in done:
                    try:
                        msg = mplane.model.parse_json(rx.result())
                    except Exception as e:
                        ccc.reply(mplane.model.Exception(errmsg="parse error: "+repr(e)))
                    else:
                        self.message_from(mplane.model.parse_json(rx.result()), ccc)
                else:
                    rx.cancel()

                if tx in done:
                    await websocket.send(mplane.model.unparse_json(tx.result()))
                else:
                    tx.cancel()

                if sd in done:
                    break
                else:
                    sd.cancel()

        except websockets.exceptions.ConnectionClosed:
            logger.debug("connection from "+ccc.clid+" closed")
        finally:
            logger.debug("shutting down")

    def run_forever(self):
        asyncio.get_event_loop().run_until_complete(self._start_server)
        asyncio.get_event_loop().run_forever()

    def run_until_shutdown(self):
        self.wssvr = asyncio.get_event_loop().run_until_complete(self._start_server)
        asyncio.get_event_loop().run_until_complete(self._sde.wait())
        self.wssvr.close()

    def start_running(self):
        self.wssvr = asyncio.get_event_loop().run_until_complete(self._start_server)

    def stop_running(self):
        self._sde.set()
        self.wssvr.close()
        asyncio.get_event_loop().run_until_complete(self.wssvr.wait_closed())



#######################################################################
# Websocket client component (not yet tested)
#######################################################################

class WSClientComponent(CommonComponent):
    """
    A Component which acts as a WebSockets server
    (for component-initiated connection establishment). 
    """
    def __init__(self, config):
        super().__init__(config)

        # Shutdown event
        self._sde = asyncio.Event()

        self.url = config["Component"]["WSInitiator"]["url"]
        self.tls = mplane.tls.TlsState(config)
        
    async def connect(self):
        # connect to the client
        async with websockets.connect(self.url) as websocket:

            # get my client context
            ccc = self._client_context(self.url, self.url)
            logger.debug("connected to client "+ccc.clid)

            try:
                # dump all capabilities the client can use in an envelope
                cap_envelope = mplane.model.Envelope()
                for service in self.services:
                    if self.azn.check(service.capability(), ccc.clid):
                        cap_envelope.append_message(service.capability())
                await websocket.send(mplane.model.unparse_json(cap_envelope))

                # now exchange messages until the shutdown flag is true
                # FIXME need to wait on SDE too. 

                while not self._sde.is_set():

                    rx = asyncio.ensure_future(websocket.recv())
                    tx = asyncio.ensure_future(ccc.outq.get())
                    sd = asyncio.ensure_future(self._sde.wait())

                    done, pending = await asyncio.wait([rx, tx, sd], 
                                        return_when=asyncio.FIRST_COMPLETED)

                    if rx in done:
                        self.message_from(mplane.model.parse_json(rx.result()), ccc)
                    else:
                        rx.cancel()

                    if tx in done:
                        await websocket.send(mplane.model.unparse_json(tx.result()))
                    else:
                        tx.cancel()

                    if sd in done:
                        break
                    else:
                        sd.cancel()

            except websockets.exceptions.ConnectionClosed:
                # FIXME schedule a reconnection attempt
                logger.debug("connection to "+ccc.clid+" closed")

    def start_running(self):
        self._task = asyncio.ensure_future(self.connect())
        logger.debug("component started task "+repr(self._task))

    def stop_running(self):
        logger.debug("signaling shutdown")
        self._sde.set()
        asyncio.get_event_loop().run_until_complete(self._task)

    def run_until_shutdown(self):
        wscli = asyncio.get_event_loop().run_until_complete(self.connect())
        wscli.close()

    async def shutdown(self):
        logger.debug("signaling shutdown")
        self._sde.set()



