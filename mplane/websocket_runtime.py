#
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
##
# mPlane Protocol Software Development Kit for Python 3
# WebSocket Runtime Helper Classes 
#
# (c) 2016      the MAMI Project (https://mami-project.eu)
#               Author: Brian Trammell <brian@trammell.ch>
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

import asyncio
import websockets
import mplane.model
import uuid

def websocket_peer_id(websocket, path=None):
    """
    Get a component ID from the websocket's peer certificate (for wss:// URLs),
    allow the component to provide a component ID on the websocket path 
    (for ws:// URLs), or default to a UUID for anonymous components

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

    # No peer cert and no path. Generate a UUID for an anonymous peer
    return str(uuid.uuid4())

class CommonEntity:
    """
    CommonEntity implements internals common to clients and components
    """

    def __init__(self, config):
        # Configuration
        self.config = config

        # Event loop
        self._loop = asyncio.get_event_loop()

        # Shutdown event
        self._sde = asyncio.Event()

    async def handle_websocket(self, websocket, ccc):
        while not self._sde.is_set():

            rx = asyncio.ensure_future(websocket.recv())
            tx = asyncio.ensure_future(ccc.outq.get())
            sd = asyncio.ensure_future(self._sde.wait())
            done, pending = await asyncio.wait([rx, tx, sd], 
                                return_when=asyncio.FIRST_COMPLETED)

            if rx in done:
                try:
                    msg = mplane.model.parse_json(rx.result())
                except Exception as e:
                    ccc.send(mplane.model.Exception(errmsg="parse error: "+repr(e)))
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

