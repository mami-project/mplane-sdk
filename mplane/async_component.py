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

# for test code
import time
from datetime import datetime


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

    This class handles keeping all Component state on a per-client
    basis separate.

    When using TLS client certificates with WebSockets (default),
    client contexts are identified by peer identity. When no
    client certificate is available, client contexts are identified
    by peer IP address.

    """

    def __init__(self, cid):
        # Store client ID 
        self.cid = cid

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

        logger.debug("new client context: "+repr(self))

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
        # M seconds ago. Add fields to Result to make this happen.
        pass

    def reply(self, msg):
        self.outq.put_nowait(msg)

    def __repr__(self):
        return "ComponentClientContext("+repr(self.cid)+")"

class CommonComponent:
    def __init__(self, config):
        # Available services
        self.services = []

        # Client component contexts by client ID
        self._ccc = {}

        self._loop = asyncio.get_event_loop()

        # get an authorization object
        self.azn = mplane.azn.Authorization(config)

        # FIXME load services


    def _client_context(self, cid):
        """
        Get a client context for a given client ID,
        creating a new one if necessary.

        """
        if cid not in self._ccc:
            self._ccc[cid] = ComponentClientContext(cid)
        return self._ccc[cid]

    def _invoke_inner(self, ccc, spec, service):
        # schedule the coroutine and stash the task
        token = spec.get_token()
        task = self._loop.create_task(service.run(spec, lambda: ccc.interrupted(token)))
        ccc.tasks[token] = task
        logger.info("invoke "+repr(spec))

    def _invoke(self, ccc, spec):
        """
        Invoke a Specification in a given client context

        """
        # Find a matching service
        service = None
        for candidate in self.services:
            if spec.fulfills(candidate.capability()):
                if self.azn.check(candidate.capability(), ccc.cid):
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

    def message_from(self, jmsg, ccc):
        """
        Handle a JSON message from a given client ID.

        """
        # Parse message
        msg = mplane.model.parse_json(jmsg)
        token = msg.get_token()

        reply = None
        if (    isinstance(msg, mplane.model.Specification) or 
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

        # Stick the reply in our outgoing message queue
        ccc.reply(reply)

#######################################################################
# Common component runtime testing
#######################################################################

class ComponentTestService():
    def capability(self):
        return mplane.model.message_from_dict({
            "capability"    : "test",
            "version"       : 0,
            "registry"      : mplane.model.REGURI_DEFAULT,
            "label"         : "test-async-client",
            "when"          : "now ... future",
            "parameters"    : { "duration.s" : "*"},
            "results"       : ["duration.s"]
        })

    async def run(self, specification, check_interrupt):
        # get requested sleep time and note when
        reqtime = specification.get_parameter_value("duration.s")
        start = time.time()

        # now sleep a little at a time, checking interrupt
        acttime = 0
        for ignored in range(reqtime):
            if check_interrupt():
                break
            await asyncio.sleep(1)
            acttime += 1

        # now create and return a result
        end = time.time()

        result = mplane.model.Result(specification = specification)
        result.set_result_value("duration.s", acttime)      
        result.set_when(mplane.model.When(a=datetime.fromtimestamp(start), 
                                          b=datetime.fromtimestamp(end)))

        logger.debug("result is "+repr(result))

        return result

def _make_test_component():
    tc = CommonComponent(None)
    tc.services.append(ComponentTestService())
    return tc

#######################################################################
# Websocket server component
#######################################################################

class WSServerComponent(CommonComponent):
    
    def __init__(self, config):
        super().__init__(config)

        interface = config["Component"]["WSListener"]["interface"]
        port = int(config["Component"]["WSListener"]["port"])
        tls = mplane.tls.TlsState(config)
        
        self._start_server = websockets.server.serve(self.serve, interface, port, ssl=tls.get_ssl_context())

    async def serve(websocket, path):
        # get my client context
        ccc = self._client_context("foo")

        # dump all capabilities in an envelope
        cap_envelope = mplane.model.Envelope()

        for service in self.services():
            if self.azn.check(candidate.capability(), ccc.cid):
                cap_envelope


        # now exchange messages forever
        while True:
            rx = asyncio.ensure_future(websocket.recv())
            tx = asyncio.ensure_future(ccc.outq.get())
            done, pending = await asyncio.wait([rx, tx], 
                                return_when=asyncio.FIRST_COMPLETED)

            if rx in done:
                self.message_from(rx.result(), ccc)
            else:
                rx.cancel()

            if tx in done:
                await websocket.send(tx.result())
            else:
                tx.cancel()

    def run_forever():
        asyncio.get_event_loop().run_until_complete(self._start_server)
        asyncio.get_event_loop().run_forever()


#######################################################################
# Websocket client component
#######################################################################

class WSClientComponent(CommonComponent):
    pass



