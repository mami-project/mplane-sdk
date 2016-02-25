import mplane.async_component
import mplane.model
import logging
import asyncio
import sys
import time
from datetime import datetime

logger = logging.getLogger(__name__)

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

def test_basic_component():
    # initialize environment
    mplane.model.initialize_registry()
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()

    # make a component and a client context
    tc = mplane.async_component.CommonComponent(None)
    tc.services.append(ComponentTestService())
    ccc = tc._client_context("foo")

    # get a spec and fill it in
    spec = mplane.model.Specification(capability=tc.services[0].capability())
    spec.set_parameter_value('duration.s', 10)
    spec.set_when(mplane.model.When("now"))

    # simulate receipt of the specification
    tc.message_from(spec, ccc)

    # run until we can get a message
    res = loop.run_until_complete(ccc.outq.get())

    # print the receipt
    print(mplane.model.render(res))

    # finish if it's an actual result
    if isinstance(res, mplane.model.Result):
        return

    while True:
        # sleep a bit
        loop.run_until_complete(asyncio.sleep(1))

        # make a redemption
        red = mplane.model.Redemption(receipt=res)

        # simulate sending it
        tc.message_from(red, ccc)

        # get the result
        res = loop.run_until_complete(ccc.outq.get())

        # finish if it's an actual result
        if isinstance(res, mplane.model.Result):
            break

    # print the result
    print(mplane.model.render(res))

async def shutdown_after(component, delay):
    await asyncio.sleep(delay)
    await component.shutdown()

def test_wsservercomponent_component():
    # initialize environment
    mplane.model.initialize_registry()
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()

    # get a component 
    tc = mplane.async_component.WSServerComponent({
            "Component" : {
                "WSListener" : {
                    "interface" : "",
                    "port" : 8727
                }
            }
        })
    tc.services.append(ComponentTestService())

    # run for 60s
    loop.create_task(shutdown_after(tc, 60))   
    tc.run_until_shutdown()

async def _test_wsservercomponent_client_hello():
    async with websockets.connect('ws://localhost:8727') as websocket:

        # get capability envelope
        jmsg = await websocket.recv()
        env = mplane.model.parse_json(jmsg)
        caps = [x for x in env.messages()]
        print(" got "+len(caps)+" capabilities.")

        # make a specification and fill it in
        spec = mplane.model.Specification(capability=caps[0])
        spec.set_parameter_value('duration.s', 10)
        spec.set_when(mplane.model.When("now"))

        # ship it
        await websocket.send(mplane.model.unparse_json(spec))

        # get a reply and print it
        res = mplane.model.parse_json(await websocket.recv())
        print(mplane.model.render(res))

        # finish if it's an actual result
        if isinstance(res, mplane.model.Result):
            return

        while True:
            # sleep a bit
            loop.run_until_complete(asyncio.sleep(1))

            # make a redemption
            red = mplane.model.Redemption(receipt=res)

            # send it
            await websocket.send(mplane.model.unparse_json(red))

            # get the reply
            res = mplane.model.parse_json(await websocket.recv())

            # finish if it's an actual result
            if isinstance(res, mplane.model.Result):
                break

        # print the result
        print(mplane.model.render(res))

def test_wsservercomponent_client():

    # initialize environment
    mplane.model.initialize_registry()
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()

    # run the client test
    loop.run_until_complete(_test_wsservercomponent_client_hello())
   