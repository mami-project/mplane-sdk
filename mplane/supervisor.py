#
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
##
# mPlane Protocol Reference Implementation
# Simple mPlane Supervisor (JSON over HTTP)
#
# (c) 2013-2015 mPlane Consortium (http://www.ict-mplane.eu)
#               Author: Stefano Pentassuglia <stefano.pentassuglia@ssbprogetti.it>
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

import mplane.model
import mplane.client
import mplane.component
import mplane.utils
import mplane.tls

import queue
import re
import tornado.web
from time import sleep
import threading
from threading import Thread

class RelayService(mplane.scheduler.Service):

    def __init__(self, cap, identity, client, lock, messages):
        self.relay = True
        self._identity = identity
        self._client = client
        self._lock = lock
        self._messages = messages
        super(RelayService, self).__init__(cap)

    def run(self, spec, check_interrupt):
        pattern = re.compile("-\d+$")
        trunc_pos = pattern.search(spec.get_label())
        trunc_label = spec.get_label()[:trunc_pos.start()]
        fwd_spec = self._client.invoke_capability(trunc_label, spec.when(), spec.parameter_values())
        result = None
        pending = False
        while result is None:
            if check_interrupt() and not pending:
                self._client.interrupt_capability(fwd_spec.get_token())
                pending = True
            sleep(1)
            with self._lock:
                if self._identity in self._messages:
                    for msg in self._messages[self._identity]:
                        if msg.get_token() == fwd_spec.get_token():
                            if (isinstance(msg, mplane.model.Result) or
                                isinstance(msg, mplane.model.Envelope)):
                                print("Received result for " + trunc_label + " from " + self._identity)
                            elif isinstance(msg, mplane.model.Exception):
                                print("Received exception for " + trunc_label + " from " + self._identity)
                            result = msg
                            self._messages[self._identity].remove(msg)
                            break

        if (not isinstance(result, mplane.model.Exception)
           and not isinstance(result, mplane.model.Envelope)):
            result.set_label(spec.get_label())
        result.set_token(spec.get_token())
        return result

class BaseSupervisor(object):
    
    def __init__(self, config):
        self._caps = []
        self.config = config

        if config is not None:
            # preload any registries necessary
            if "Registries" in config:
                if "preload" in config["Registries"]:
                    for reg in config["Registries"]["preload"]:
                        mplane.model.preload_registry(reg)
                if "default" in config["Registries"]:
                    registry_uri = config["Registries"]["default"]
                else:
                    registry_uri = None
            else:
                registry_uri = None
        else:
            registry_uri = None

        # load default registry
        mplane.model.initialize_registry(registry_uri)

        tls_state = mplane.tls.TlsState(config)

        self.from_cli = queue.Queue()
        self._lock = threading.RLock()
        self._spec_messages = dict()
        self._io_loop = tornado.ioloop.IOLoop.instance()
        if config is None:
            self._client = mplane.client.HttpListenerClient(config=config,
                                                            tls_state=tls_state, supervisor=True,
                                                            exporter=self.from_cli,
                                                            io_loop=self._io_loop)

            self._component = mplane.component.ListenerHttpComponent(config,
                                                                     io_loop=self._io_loop)
        else:
            if ("Initiator" in self.config["Client"]
                    and "Listener" in self.config["Client"]):
                raise ValueError("The supervisor client-side cannot be 'Initiator' and 'Listener' simultaneously. "
                                 "Remove one of them from " + self.config + "[\"Client\"]")
            elif "Listener" in self.config["Client"]:
                self._client = mplane.client.HttpListenerClient(config=self.config,
                                                                tls_state=tls_state, supervisor=True,
                                                                exporter=self.from_cli,
                                                                io_loop=self._io_loop)
            elif "Initiator" in self.config["Client"]:
                self._client = mplane.client.HttpInitiatorClient(tls_state=tls_state, supervisor=True,
                                                                 exporter=self.from_cli)
                self._urls = self.config["Client"]["capability-url"]
            else:
                raise ValueError("Need either a 'Initiator' or 'Listener' object under 'Client' in config file")

            if ("Initiator" in self.config["Component"]
                and "Listener" in self.config["Component"]):
                raise ValueError("The supervisor component-side cannot be 'Initiator' and 'Listener' simultaneously. "
                                 "Remove one of them from " + args.config + "[\"Component\"]")
            elif "Initiator" in self.config["Component"]:
                self._component = mplane.component.InitiatorHttpComponent(self.config,
                                                                          supervisor=True)
            elif "Listener" in self.config["Component"]:
                self._component = mplane.component.ListenerHttpComponent(self.config,
                                                                         io_loop=self._io_loop)
            else:
                raise ValueError("Need either a 'Initiator' or 'Listener' object under 'Component' in config file")

        self.run()

    def run(self):
        if ("Listener" in self.config["Client"] or
            "Listener" in self.config["Component"]):
            t_listen = Thread(target=self.listen_in_background)
            t_listen.daemon = True
            t_listen.start()
        if "Initiator" in self.config["Client"]:
            t_poll = Thread(target=self.poll_in_background)
            t_poll.daemon = True
            t_poll.start()
        while True:
            if not self.from_cli.empty():
                [msg, identity] = self.from_cli.get()
                self.handle_message(msg, identity)
            sleep(0.1)

    def handle_message(self, msg, identity):
        if isinstance(msg, mplane.model.Capability):
            if [msg.get_label(), identity] not in self._caps:
                self._caps.append([msg.get_label(), identity])
                serv = RelayService(msg, identity, self._client,
                                    self._lock, self._spec_messages)
                self._component.scheduler.add_service(serv)

                if "Listener" in self.config["Component"]:
                    if "interfaces" in self.config["Component"]["Listener"] and \
                            self.config["Component"]["Listener"]["interfaces"]:
                        if "TLS" in self.config:
                            link = "https://"
                        else:
                            link = "http://"
                        link = link + self.config["Component"]["Listener"]["interfaces"][0] + ":"
                        link = link + self.config["Component"]["Listener"]["port"] + "/"
                        serv.set_capability_link(link)
                    else:
                        serv.set_capability_link("")

                if "Initiator" in self.config["Component"] and \
                        not msg.get_label() == "callback":
                    self._component.register_to_client([serv.capability()])

        elif isinstance(msg, mplane.model.Receipt):
            pass
            
        elif (isinstance(msg, mplane.model.Result) or
            isinstance(msg, mplane.model.Exception)):
            with self._lock:
                mplane.utils.add_value_to(self._spec_messages, identity, msg)
            
        elif isinstance(msg, mplane.model.Withdrawal):
            if not msg.get_label() == "callback":
                self._component.remove_capability(self._component.scheduler.capability_for_key(msg.get_token()))
                self._caps.remove([msg.get_label(), identity])

        elif isinstance(msg, mplane.model.Envelope):
            for imsg in msg.messages():
                if isinstance(imsg, mplane.model.Result):
                    mplane.utils.add_value_to(self._spec_messages, identity, msg)
                    break
                else:
                    self.handle_message(imsg, identity)
        else:
            raise ValueError("Internal error: unknown message "+repr(msg))

    def listen_in_background(self):
        """ Start the listening server """
        self._io_loop.start()

    def poll_in_background(self):
        """ Periodically poll components """
        while True:
            for url in self._urls:
                try:
                    self._client.retrieve_capabilities(url)
                except:
                    print(str(url) + " unreachable. Retrying in 5 seconds")

            # poll for results
            for label in self._client.receipt_labels():
                self._client.result_for(label)

            for token in self._client.receipt_tokens():
                self._client.result_for(token)

            for label in self._client.result_labels():
                self._client.result_for(label)

            for token in self._client.result_tokens():
                self._client.result_for(token)

            sleep(5)