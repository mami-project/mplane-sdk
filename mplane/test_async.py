import mplane.component
import mplane.client
import mplane.model
import websockets
import logging
import asyncio
import sys
import time
from datetime import datetime

logger = logging.getLogger(__name__)

TEST_DURATION = 4

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

    # make a component and a client context
    tc = mplane.component.CommonComponent(None)
    tc.services.append(ComponentTestService())
    ccc = tc._client_context("/i_am_citizen_three")

    # get a spec and fill it in
    spec = mplane.model.Specification(capability=tc.services[0].capability())
    spec.set_parameter_value('duration.s', TEST_DURATION)
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
    logger.debug("will shutdown after "+str(delay)+"s")
    await asyncio.sleep(delay)
    await component.shutdown()

async def _test_wsservercomponent_client_hello():
    await asyncio.sleep(1)
    async with websockets.connect('ws://localhost:8727/i_am_citizen_four') as websocket:

        # get capability envelope
        jmsg = await websocket.recv()
        env = mplane.model.parse_json(jmsg)
        caps = [x for x in env.messages()]
        print(" got "+str(len(caps))+" capabilities.")

        # make a specification and fill it in
        spec = mplane.model.Specification(capability=caps[0])
        spec.set_parameter_value('duration.s', TEST_DURATION)
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
            await asyncio.sleep(1)

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

def test_wsserver_component(delay=30):
    loop = asyncio.get_event_loop()

    # get a component 
    tc = mplane.component.WSServerComponent({
            "Component" : {
                "Listener" : {
                    "interfaces" : [],
                    "port" : 8727
                }
            }
        })
    tc.services.append(ComponentTestService())

    # schedule client startup
    client_task = loop.create_task(_test_wsservercomponent_client_hello())

    # schedule component shutdown after 60s
    loop.create_task(shutdown_after(tc, delay))   

    # run the component
    tc.run_until_shutdown()

    # wait for client shutdown
    loop.run_until_complete(client_task)


def test_client_initiated(delay=30):
    loop = asyncio.get_event_loop()
    #loop.set_debug(True)

    # get a component and kick it off
    tcom = mplane.component.WSServerComponent({
            "Component" : {
                "Listener" : {
                    "interfaces" : [],
                    "port" : 8727
                }
            }
        })
    tcom.services.append(ComponentTestService())

    # kick off the component
    tcom.start_running()
    logger.info("Component up")

    # now get a client
    tcli = mplane.client.WSClientClient({
        "Client" : {
            "Initiator" : {
                "url": "ws://localhost:8727/i_am_citizen_five"
                }
            }
        })

    # connect
    tcli.start_running()
    logger.info("Client connected")

    # run the client until we have capabilities
    loop.run_until_complete(tcli.await_capabilities())

    # find the capability and verify it has the fields we want
    pass

    # invoke it
    spec = loop.run_until_complete(tcli.await_invocation(cap_tol = 'test-async-client', 
                                                        when = mplane.model.When('now'), 
                                                        params = { 'duration.s': TEST_DURATION }))
    logger.info("Test specification invoked")

    # now wait for the result 
    res = loop.run_until_complete(tcli.await_result(spec.get_token()))
    logger.info("Result available")

    # verify the result
    pass

    # then shut down the client and component
    tcli.stop_running()
    logger.info("Client disconnected")

    loop.run_until_complete(asyncio.sleep(1))

    tcom.stop_running()
    logger.info("Component shutdown")

def test_component_initiated(delay=30):
    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    # get a client
    tcli = mplane.client.WSServerClient({
        "Client" : {
                "Listener" : {
                    "interfaces" : [],
                    "port" : 8727
                } 
            }
        })
    tcli.start_running()

    logger.info("Client up")

    # get a component 
    tcom = mplane.component.WSClientComponent({
            "Component" : {
                "Initiator" : {
                    "url": "ws://localhost:8727/i_am_citizen_six"
                }
            }
        })
    tcom.services.append(ComponentTestService())

    # connect
    tcom.start_running()

    logger.info("Component connected")


    # run the client until we have capabilities
    loop.run_until_complete(tcli.await_capabilities())

    logger.info("Capabilities available")


    # find the capability and verify it has the fields we want
    pass

    # invoke it
    spec = loop.run_until_complete(tcli.await_invocation(cap_tol = 'test-async-client', 
                                                        when = mplane.model.When('now'), 
                                                        params = { 'duration.s': TEST_DURATION }))

    logger.info("Test specification invoked")


    # now wait for the result 
    res = loop.run_until_complete(tcli.await_result(spec.get_token()))

    logger.info("Result available")


    # verify the result
    pass

    # then shut down the client and component
    tcom.stop_running()
    logger.info("Component disconnected")

    loop.run_until_complete(asyncio.sleep(1))

    tcli.stop_running()
    logger.info("Client shutdown")

if __name__ == "__main__":
    # initialize environment
    mplane.model.initialize_registry()
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger('websockets').setLevel(logging.INFO)

    #test_basic_component()
    #test_wsserver_component()
    logger.info("######################################################################")
    logger.info("########### testing client-initiated #################################")
    logger.info("######################################################################")
    test_client_initiated()
    logger.info("######################################################################")
    logger.info("########### testing component-initiated ##############################")
    logger.info("######################################################################")
    test_component_initiated()
   