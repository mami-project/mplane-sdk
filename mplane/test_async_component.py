import mplane.async_component
import logging
import asyncio
import sys

if __name__ == "__main__":

    # boot the registry
    mplane.model.initialize_registry()

    # see debug messages
    logging.basicConfig(level=logging.DEBUG)

    # get a loop
    loop = asyncio.get_event_loop()

    # get a component
    tc = mplane.async_component._make_test_component()

    # get a spec and set a duration
    spec = mplane.model.Specification(capability=tc.services[0].capability())
    spec.set_parameter_value('duration.s', 10)

    # simulate receipt of the specification
    tc.message_from(mplane.model.unparse_json(spec), "foo")

    # run until we can get a message
    res = loop.run_until_complete(tc._ccc['foo'].outq.get())

    # print the receipt
    print(mplane.model.render(res))

    # finish if it's an actual result
    if isinstance(res, mplane.model.Result):
        sys.exit(0)

    while True:
        # sleep a bit
        loop.run_until_complete(asyncio.sleep(1))

        # make a redemption
        red = mplane.model.Redemption(receipt=res)

        # simulate sending it
        tc.message_from(mplane.model.unparse_json(red), "foo")

        # get the result
        res = loop.run_until_complete(tc._ccc['foo'].outq.get())

        # finish if it's an actual result
        if isinstance(res, mplane.model.Result):
            break

    # print the result
    print(mplane.model.render(res))
