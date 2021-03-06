#
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
##
# mPlane Protocol Reference Implementation
# Client SDK API implementation
#
# (c) 2013-2015 mPlane Consortium (http://www.ict-mplane.eu)
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

import mplane.model
import mplane.utils
from datetime import datetime

import html.parser
import urllib3

# FIXME HACK
# some urllib3 versions let you disable warnings about untrusted CAs,
# which we use a lot in the project demo. Try to disable warnings if we can.
try:
    urllib3.disable_warnings()
except:
    pass

from threading import Thread
import queue

import tornado.web
import tornado.httpserver
import tornado.ioloop

import logging

CAPABILITY_PATH_ELEM = "capability"

FORGED_DN_HEADER = "Forged-MPlane-Identity"
DEFAULT_IDENTITY = "default"

DEFAULT_PORT = 8889
DEFAULT_HOST = "127.0.0.1"
DEFAULT_REGISTRATION_PATH = "register/capability"
DEFAULT_SPECIFICATION_PATH = "show/specification"
DEFAULT_RESULT_PATH = "register/result"

logger = logging.getLogger(__name__)

class BaseClient(object):
    """
    Core implementation of a generic programmatic client.
    Used for common client state management between
    HttpInitiatorClient and HttpListenerClient; 
    use one of these instead.

    """

    def __init__(self, tls_state, supervisor=False, exporter=None):
        self._tls_state = tls_state
        self.reset()
        self._ssn = -1
        self._supervisor = supervisor
        if self._supervisor:
            self._exporter = exporter

    def reset(self,args=None):
        self._capabilities = {}
        self._capability_labels = {}
        self._capability_identities = {}
        self._receipt_identities = {}
        self._receipts = {}
        self._receipt_labels = {}
        self._results = {}
        self._result_labels = {}
        # structures for capability expiration after timeout
        self._capability_timeouts = {}
        self._capabilities_by_identity = {}

    def _add_capability(self, msg, identity):
        """
        Add a capability to internal state. The capability will be recallable
        by token, and, if present, by label.

        Internal use only; use handle_message instead.

        """

        # FIXME retoken on token collision with another identity
        token = msg.get_token()
        self._capabilities[token] = msg
        self._capability_timeouts[token] = datetime.utcnow()

        if msg.get_label():
            self._capability_labels[msg.get_label()] = msg

        if identity:
            self._capability_identities[token] = identity
            mplane.utils.add_value_to(self._capabilities_by_identity, identity, token)

    def _remove_capability(self, token):
        """
        Remove a capability from all the structures

        """
        if token in self._capabilities:
            label = self._capabilities[token].get_label()
            del self._capabilities[token]
            del self._capability_timeouts[token]
            identity = self.identity_for(token)
            self._capabilities_by_identity[identity].remove(token)
            if label and label in self._capability_labels:
                del self._capability_labels[label]

    def _withdraw_capability(self, msg, identity):
        """
        Process a withdrawal. Match the withdrawal to the capability,
        first by token, then by schema. Withdrawals that do not match
        any known capabilities are dropped silently.

        Internal use only; use handle_message instead.

        """
        token = msg.get_token()

        # FIXME check identity, exception on mismatch

        if token in self._capabilities:
            self._remove_capability(token)
        else:
            # Search all capabilities by schema
            for cap in self.capabilities_matching_schema(msg):
                self._remove_capability(cap.get_token())

    def capability_for(self, token_or_label):
        """
        Retrieve a capability given a token or label.

        """
        if token_or_label in self._capability_labels:
            return self._capability_labels[token_or_label]
        elif token_or_label in self._capabilities:
            return self._capabilities[token_or_label]
        else:
            raise KeyError("no capability for token or label "+token_or_label)

    def identity_for(self, token_or_label, receipt=False):
        """
        Retrieve an identity given a capability token or label, or a receipt token.

        """
        if not receipt:
            if token_or_label in self._capability_identities:
                return self._capability_identities[token_or_label]
            elif token_or_label in self._capability_labels:
                return self._capability_identities[self._capability_labels[token_or_label].get_token()]
            else:
                raise KeyError("no identity for capability token or label "+token_or_label)
        else:
            if token_or_label in self._receipt_identities:
                return self._receipt_identities[token_or_label]
            else:
                raise KeyError("no identity for receipt token " + token_or_label)

    def capabilities_matching_schema(self, schema_capability):
        """
        Given a capability, return *all* known capabilities matching the
        given schema capability. A capability matches a schema capability
        if and only if: (1) the capability schemas match and (2) all
        constraints in the capability are contained by all constraints
        in the schema capability.

        Used to programmatically select capabilities matching an
        aggregation or other collection operation (e.g. at a supervisor).

        """
        # FIXME write this, maybe refactor part back into model.
        pass

    def _spec_for(self, cap_tol, when, params, relabel=None):
        """
        Given a capability token or label, a temporal scope, a dictionary
        of parameters, and an optional new label, derive a specification
        ready for invocation, and return the capability and specification.

        Used internally by derived classes; use invoke_capability instead.

        """
        cap = self.capability_for(cap_tol)
        spec = mplane.model.Specification(capability=cap)

        # set temporal scope
        spec.set_when(when)

        # fill in parameters
        # spec.set_single_values() # this is automatic now
        for pname in spec.parameter_names():
            if spec.get_parameter_value(pname) is None:
                if pname in params:
                    spec.set_parameter_value(pname, params[pname])
                else:
                    raise KeyError("missing parameter "+pname)

        # regenerate token based on parameters and temporal scope
        spec.retoken()

        # generate label
        if relabel:
            spec.set_label(relabel)
        else:
            spec.set_label(cap.get_label() + "-" + str(self._ssn))
        self._ssn += 1

        return (cap, spec)

    def _handle_receipt(self, msg, identity):
        self._add_receipt(msg, identity)

    def _add_receipt(self, msg, identity):
        """
        Add a receipt to internal state. The receipt will be recallable
        by token, and, if present, by label.

        Internal use only; use handle_message instead.

        """
        self._receipt_identities[msg.get_token()] = identity
        self._receipts[msg.get_token()] = msg
        if msg.get_label():
            self._receipt_labels[msg.get_label()] = msg

    def _remove_receipt(self, msg):
        """
        Remove a receipt from internal state.

        Internal use only; use handle_message instead.

        """
        token = msg.get_token()
        if token in self._receipts:
            receipt = self._receipts[token]
            del self._receipts[token]
            label = receipt.get_label()
            if label and label in self._receipt_labels:
                del self._receipt_labels[label]

    def _handle_result(self, msg, identity):
        # FIXME check the result identity against where we sent the specification to
        self._add_result(msg, identity)

    def _add_result(self, msg, identity=None):
        """
        Add a result to internal state. The result will supercede any receipt
        stored for the same token, and will be recallable by token, and,
        if present, by label.

        Internal use only; use handle_message instead.

        """
        receipt = None
        try:
            if isinstance(msg, mplane.model.Envelope):
                # if the result is an envelope containing multijob
                # results, keep the receipt until the multijob ends
                (start, end) = msg.when().datetimes()
                if end < datetime.utcnow():
                    if self._supervisor:
                        self._exporter.put_nowait([msg, identity])

                    receipt = self._receipts[msg.get_token()]
                    self._remove_receipt(receipt)
            else:
                receipt = self._receipts[msg.get_token()]
                self._remove_receipt(receipt)
        except KeyError:
            pass
        self._results[msg.get_token()] = msg

        if not isinstance(msg, mplane.model.Exception):
            if msg.get_label():
                self._result_labels[msg.get_label()] = msg
        else:
            # Exceptions are only added to result_labels if a receipt existed in receipts -WHY
            if receipt is not None:
                self._result_labels[receipt.get_label()] = msg

    def _remove_result(self, msg):
        token = msg.get_token()
        if token in self._results:
            label = self._results[token].get_label()
            del self._results[token]
            if label and label in self._result_labels:
                del self._result_labels[label]

    def result_for(self, token_or_label):
        """
        Return a result for the token if available;
        return the receipt for the token otherwise.

        """
        # first look in state
        if token_or_label in self._receipt_labels:
            return self._receipt_labels[token_or_label]
        elif token_or_label in self._receipts:
            return self._receipts[token_or_label]
        elif token_or_label in self._result_labels:
            return self._result_labels[token_or_label]
        elif token_or_label in self._results:
            return self._results[token_or_label]
        else:
            raise KeyError("no such token or label "+token_or_label)

    def _handle_exception(self, msg, identity):
        self._add_result(msg)

    def handle_message(self, msg, identity=None):
        """
        Handle a message. Used internally to process
        mPlane messages received from a component. Can also be used
        to inject messages into a client's state.

        """

        if (self._supervisor and
            not isinstance(msg, mplane.model.Envelope)):
            self._exporter.put_nowait([msg, identity])

        if isinstance(msg, mplane.model.Capability):
            self._add_capability(msg, identity)
        elif isinstance(msg, mplane.model.Withdrawal):
            self._withdraw_capability(msg, identity)
        elif isinstance(msg, mplane.model.Receipt):
            self._handle_receipt(msg, identity)
        elif isinstance(msg, mplane.model.Result):
            self._handle_result(msg, identity)
        elif isinstance(msg, mplane.model.Exception):
            self._handle_exception(msg, identity)
        elif isinstance(msg, mplane.model.Envelope):
            if msg.get_token() in self._receipts:
                self._handle_result(msg, identity)
            else:
                for imsg in msg.messages():
                    self.handle_message(imsg, identity)
        else:
            raise ValueError("Internal error: unknown message "+repr(msg))

    def forget(self, token_or_label):
        """
        forget all receipts and results for the given token or label
        """
        if token_or_label in self._result_labels:
            result = self._result_labels[token_or_label]
            del self._result_labels[token_or_label]
            del self._results[result.get_token()]

        if token_or_label in self._results:
            result = self._results[token_or_label]
            del self._results[token_or_label]
            if result.get_label():
                del self._result_labels[result.get_label()]

        if token_or_label in self._receipt_labels:
            receipt = self._receipt_labels[token_or_label]
            del self._receipt_labels[token_or_label]
            del self._receipts[receipt.get_token()]

        if token_or_label in self._receipts:
            receipt = self._receipts[token_or_label]
            del self._receipts[token_or_label]
            if receipt.get_label():
                del self._receipt_labels[receipt.get_label()]

    def receipt_tokens(self):
        """
        list all tokens for outstanding receipts
        """
        return tuple(self._receipts.keys())

    def receipt_labels(self):
        """
        list all labels for outstanding receipts
        """
        return tuple(self._receipt_labels.keys())

    def result_tokens(self):
        """
        list all tokens for stored results
        """
        return tuple(self._results.keys())

    def result_labels(self):
        """
        list all labels for stored results
        """
        return tuple(self._result_labels.keys())

    def capability_tokens(self):
        """
        list all tokens for stored capabilities
        """
        return tuple(self._capabilities.keys())

    def capability_labels(self):
        """
        list all labels for stored capabilities
        """
        return tuple(self._capability_labels.keys())

class CrawlParser(html.parser.HTMLParser):
    """
    HTML parser class to extract all URLS in a href attributes in
    an HTML page. Used to extract links to Capabilities exposed
    as link collections.

    """
    def __init__(self, **kwargs):
        super(CrawlParser, self).__init__(**kwargs)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = {k: v for (k,v) in attrs}
        if tag == "a" and "href" in attrs:
            self.urls.append(attrs["href"])

class HttpInitiatorClient(BaseClient):
    """
    Core implementation of an mPlane JSON-over-HTTP(S) client.
    Supports client-initiated workflows. Intended for building
    client UIs and bots.

    """

    def __init__(self, tls_state, default_url=None,
                 supervisor=False, exporter=None):
        """
        initialize a client with a given
        default URL an a given TLS state
        """
        super().__init__(tls_state, supervisor=supervisor,
                        exporter=exporter)

        self._default_url = default_url

        # specification serial number
        # used to create labels programmatically
        self._ssn = 0

    def set_default_url(self, url):
        if isinstance(url, str):
            self._default_url = urllib3.util.parse_url(url)
        else:
            self._default_url = url

    def send_message(self, msg, dst_url=None):
        """
        send a message, store any result in client state.

        """
        # figure out where to send the message
        if not dst_url:
            dst_url = self._default_url

        if isinstance(dst_url, str):
            dst_url = urllib3.util.parse_url(dst_url)

        pool = self._tls_state.pool_for(dst_url.scheme, dst_url.host, dst_url.port)

        headers = {"Content-Type": "application/x-mplane+json"}
        if self._tls_state.forged_identity():
            headers[FORGED_DN_HEADER] = self._tls_state.forged_identity()

        if dst_url.path is not None:
            path = dst_url.path
        else:
            path = "/"

        # send message
        res = pool.urlopen('POST', path,
                           body=mplane.model.unparse_json(msg).encode("utf-8"),
                           headers=headers)

        # process reply
        if (res.status == 200 and
            res.getheader("Content-Type") == "application/x-mplane+json"):
            component_identity = self._tls_state.extract_peer_identity(dst_url)
            self.handle_message(mplane.model.parse_json(res.data.decode("utf-8")), component_identity)
        else:
            # Didn't get an mPlane reply. What now?
            pass

    def result_for(self, token_or_label):
        """
        return a result for the token if available;
        attempt to redeem the receipt for the token otherwise;
        if not yet redeemable, return the receipt instead.
        """
        # go get a raw receipt or result
        rr = super().result_for(token_or_label)

        # check if it's a Job or Multijob result
        if (isinstance(rr, mplane.model.Result) or
            isinstance(rr, mplane.model.Envelope)):

            # If it's a Multijob result, there may be a receipt
            # to retrieve further data.
            # In that case, ignore the current result and
            # retrieve up-to-date results from the component
            if (rr.get_token() not in self.receipt_tokens() and
                rr.get_label() not in self.receipt_labels()):
                return rr
            else:
                rr = self._receipts[rr.get_token()]
        elif isinstance(rr, mplane.model.Exception):
            return rr

        # if we're here, we have a receipt. try to redeem it.
        self.send_message(mplane.model.Redemption(receipt=rr))

        # see if we got a result
        if token_or_label in self._result_labels:
            return self._result_labels[token_or_label]
        elif token_or_label in self._results:
            return self._results[token_or_label]
        else:
            # Nope. Return the receipt.
            return rr

    def invoke_capability(self, cap_tol, when, params, relabel=None):
        """
        Given a capability token or label, a temporal scope, a dictionary
        of parameters, and an optional new label, derive a specification
        and send it to the appropriate destination.

        """
        (cap, spec) = self._spec_for(cap_tol, when, params, relabel)
        spec.validate()
        dst_url = cap.get_link()
        self.send_message(spec, dst_url)
        return spec

    def interrupt_capability(self, cap_tol):
        # get the receipt
        rr = super().result_for(cap_tol)
        interrupt = mplane.model.Interrupt(specification=rr)
        dst_url = urllib3.util.Url(scheme=self._default_url.scheme,
                                   host=self._default_url.host,
                                   port=self._default_url.port,
                                   path=self._default_url.path)
        self.send_message(interrupt, dst_url)

    def retrieve_capabilities(self, url, urlchain=[], pool=None, identity=None):
        """
        Connect to the given URL, retrieve and process the
        capabilities/withdrawals found there
        """

        # detect loops in capability links
        if url in urlchain:
            return

        if not self._default_url:
            self.set_default_url(url)

        if isinstance(url, str):
            url = urllib3.util.parse_url(url)

        if identity is None:
            identity = self._tls_state.extract_peer_identity(url)

        if pool is None:
            if url.host is not None:
                pool = self._tls_state.pool_for(url.scheme, url.host, url.port)
            else:
                raise ValueError("HttpInitiatorClient capability retrieval missing connection pool")

        if url.path is not None:
            path = url.path
        else:
            path = "/"
        res = pool.request('GET', path)

        if res.status == 200:
            ctype = res.getheader("Content-Type")
            if ctype == "application/x-mplane+json":

                # Probably an envelope. Process the message.
                self.handle_message(
                    mplane.model.parse_json(res.data.decode("utf-8")), identity)
            elif ctype == "text/html":
                # Treat as a list of links to capability messages.
                parser = CrawlParser()
                parser.feed(res.data.decode("utf-8"))
                parser.close()
                for capurl in parser.urls:
                    self.retrieve_capabilities(url=capurl,
                                               urlchain=urlchain + [url],
                                               pool=pool, identity=identity)

class HttpListenerClient(BaseClient):
    """
    Core implementation of an mPlane JSON-over-HTTP(S) client.
    Supports component-initiated workflows. Intended for building
    supervisors.

    """
    def __init__(self, config, tls_state=None,
                 supervisor=False, exporter=None, io_loop=None):
        super().__init__(tls_state, supervisor=supervisor,
                        exporter=exporter)

        listen_port = DEFAULT_PORT
        self.registration_path = DEFAULT_REGISTRATION_PATH
        self.specification_path = DEFAULT_SPECIFICATION_PATH
        self.result_path = DEFAULT_RESULT_PATH

        ipaddresses = None
        self._link = ""
        self.config = config

        # if config file contains the needed keys: use them. Otherwise use default values
        if self.config is not None and "Client" in self.config and "Listener" in self.config["Client"]:
            if "port" in self.config["Client"]["Listener"]:
                listen_port = int(self.config["Client"]["Listener"]["port"])

            if "capability-path" in self.config["Client"]["Listener"]:
                self.registration_path = self.config["Client"]["Listener"]["capability-path"]

            if "specification-path" in self.config["Client"]["Listener"]:
                self.specification_path = self.config["Client"]["Listener"]["specification-path"]

            if "result-path" in self.config["Client"]["Listener"]:
                self.result_path = self.config["Client"]["Listener"]["result-path"]

            if "interfaces" in self.config["Client"]["Listener"] and self.config["Client"]["Listener"]["interfaces"]:
                ipaddresses = self.config["Client"]["Listener"]["interfaces"]

                # 'link' construction: if there are multiple IPs to listen on, we have no way to determine
                # which will be the correct URI for a component. In this case, let's delegate the construction to the
                # request handlers (see InteractionsHandler.get())
                if len(ipaddresses) != 1:
                    self._link = ""
                else:
                    if "TLS" in self.config:
                        self._link = "https://"
                    else:
                        self._link = "http://"
                    self._link = self._link + ipaddresses[0] + ":"
                    if not self.result_path.startswith("/"):
                        self._link = self._link + self.config["Client"]["Listener"]["port"] + "/" + self.result_path
                    else:
                        self._link = self._link + self.config["Client"]["Listener"]["port"] + self.result_path

        if not self.registration_path.startswith("/"):
            self.registration_path = "/" + self.registration_path
        if not self.specification_path.startswith("/"):
            self.specification_path = "/" + self.specification_path
        if not self.result_path.startswith("/"):
            self.result_path = "/" + self.result_path

        # Outgoing messages per component identifier
        self._outgoing = {}

        # specification serial number
        # used to create labels programmatically
        self._ssn = 0

        # Capability
        self._callback_capability = {}

        # Create a request handler pointing at this client
        self._tornado_application = tornado.web.Application([
            (self.registration_path, InteractionsHandler, {'listenerclient': self, 'tlsState': self._tls_state}),
            (self.registration_path + "/", InteractionsHandler, {'listenerclient': self, 'tlsState': self._tls_state}),
            (self.specification_path, InteractionsHandler, {'listenerclient': self, 'tlsState': self._tls_state}),
            (self.specification_path + "/", InteractionsHandler, {'listenerclient': self, 'tlsState': self._tls_state}),
            (self.result_path, InteractionsHandler, {'listenerclient': self, 'tlsState': self._tls_state}),
            (self.result_path + "/", InteractionsHandler, {'listenerclient': self, 'tlsState': self._tls_state}),
        ])
        http_server = tornado.httpserver.HTTPServer(self._tornado_application, ssl_options=tls_state.get_ssl_options())

        # run the server
        if ipaddresses is not None:
            for ip in ipaddresses:
                http_server.listen(listen_port, ip)
        else:
            http_server.listen(listen_port)

        if io_loop is not None:
            cli_t = Thread(target=self.listen_in_background(io_loop))
            timeout_callback = tornado.ioloop.PeriodicCallback(self._check_timeouts, 5000, io_loop)
        else:
            cli_t = Thread(target=self.listen_in_background)
            timeout_callback = tornado.ioloop.PeriodicCallback(self._check_timeouts, 5000)
        timeout_callback.start()
        cli_t.daemon = True
        cli_t.start()

    def listen_in_background(self, io_loop=None):
        """ The server listens for requests in background """

        if io_loop is None:
            tornado.ioloop.IOLoop.instance().start()

    def _check_timeouts(self):
        """ Checks if capabilities are expired, and if so, delete them """

        expired_tokens = []
        for token in self._capability_timeouts:
            interval = datetime.utcnow() - self._capability_timeouts[token]
            if interval.total_seconds() >= 10:
                expired_tokens.append(token)

        for token in expired_tokens:
            cap_withdraw = mplane.model.Withdrawal(capability=self._capabilities[token])
            self.handle_message(cap_withdraw, self.identity_for(token))

    def _push_outgoing(self, identity, msg):
        if identity not in self._outgoing:
            self._outgoing[identity] = []
        self._outgoing[identity].append(msg)

    def invoke_capability(self, cap_tol, when, params, relabel=None, callback_when=None):
        """
        Given a capability token or label, a temporal scope, a dictionary
        of parameters, and an optional new label, derive a specification
        and queue it for retrieval by the appropriate identity (i.e., the
        one associated with the capability).

        If the identity has indicated it supports callback control,
        the optional callback_when parameter queues a callback spec to
        schedule the next callback.
        """
        logger.info("will invoke " + cap_tol + " with "  +repr(params))  
        # grab cap, spec, and identity
        (cap, spec) = self._spec_for(cap_tol, when, params, relabel)
        identity = self.identity_for(cap.get_token())
        spec.set_link(self._link)

        callback_cap = None
        if identity in self._callback_capability:
            # prepare a callback spec if we need to
            callback_cap = self._callback_capability[identity]
        if callback_cap and callback_when:
            callback_spec = mplane.model.Specification(capability=callback_cap)
            callback_spec.set_when(callback_when)
            envelope = mplane.model.Envelope()
            envelope.append_message(callback_spec)
            envelope.append_message(spec)
            self._push_outgoing(identity, envelope)
        else:
            self._push_outgoing(identity, spec)
        return spec

    def interrupt_capability(self, cap_tol):
        # get the receipt
        rr = super().result_for(cap_tol)
        identity = self.identity_for(rr.get_token(), receipt=True)
        interrupt = mplane.model.Interrupt(specification=rr)
        self._push_outgoing(identity, interrupt)

    def _add_capability(self, msg, identity):
        """
        Override Client's add_capability, check for callback control
        """
        if msg.verb() == mplane.model.VERB_CALLBACK:
            # FIXME this is kind of dodgy; we should do better checks to
            # make sure this is a real callback capability
            self._callback_capability[identity] = msg
        else:
            # not a callback control cap, just add the capability
            super()._add_capability(msg, identity)

class MPlaneHandler(tornado.web.RequestHandler):
    """
    Abstract tornado RequestHandler that allows a
    handler to respond with an mPlane Message.

    """

    def _respond_message(self, msg):
        """
        Returns an HTTP response containing a JSON message

        """
        self.set_status(200)
        self.set_header("Content-Type", "application/x-mplane+json")
        self.write(mplane.model.unparse_json(msg))
        self.finish()

    def _respond_plain_text(self, code, text = None):
        """
        Returns an HTTP response containing a plain text message

        """
        self.set_status(code)
        if text is not None:
            self.set_header("Content-Type", "text/plain")
            self.write(text)
        self.finish()

    def _respond_json_text(self, code, text = None):
        """
        Returns an HTTP response containing a plain text message

        """
        self.set_status(code)
        if text is not None:
            self.set_header("Content-Type", "application/x-mplane+json")
            self.write(text)
        self.finish()

# FIXME figure out what this class is for
class InteractionsHandler(MPlaneHandler):
    """
    Handles the probes that want to register to this supervisor
    Each capability is registered independently

    Exposes the specifications, that will be periodically pulled by the
    components

    Receives results of specifications

    """
    def initialize(self, listenerclient, tlsState):
        self._listenerclient = listenerclient
        self._tls = tlsState

    def post(self):
        """
        Receives POST requests that may contain Capabilities, Results, Receipts and Exceptions

        """

        # unwrap json message from body
        if self.request.headers["Content-Type"] == "application/x-mplane+json":
            env = mplane.model.parse_json(self.request.body.decode("utf-8"))
        else:
            self._respond_plain_text(400, "Invalid format")
            return

        if self._listenerclient.registration_path != self._listenerclient.result_path:
            # registration and result path are different, we need to check if the requests have been
            # sent on the correct path

            # if is a Result, Receipt, Exception or Envelope (containing results)
            if self.request.path == self._listenerclient.result_path:
                if isinstance(env, mplane.model.Result) \
                        or isinstance(env, mplane.model.Receipt) \
                        or isinstance(env, mplane.model.Exception):
                    self._listenerclient.handle_message(env, self._tls.extract_peer_identity(self.request))
                    self._respond_plain_text(200)
                elif isinstance(env, mplane.model.Envelope):
                    for msg in env.messages():
                        if not isinstance(msg, mplane.model.Result) \
                                and not isinstance(msg, mplane.model.Receipt) \
                                and not isinstance(msg, mplane.model.Exception):
                            self._respond_plain_text(401, "Not a result (or receipt) received on result path")
                            return
                    # fall through
                    self._listenerclient.handle_message(env, self._tls.extract_peer_identity(self.request))
                    self._respond_plain_text(200)
                    return
                else:
                    self._respond_plain_text(401, "Not authorized: not a result (or receipt) received on result path")
                    return

            # if is an Envelope (containing capabilities)
            elif self.request.path == self._listenerclient.registration_path:
                if isinstance(env, mplane.model.Envelope):
                    self._listenerclient.handle_message(env, self._tls.extract_peer_identity(self.request))
                    response = self.generate_response(env)
                    self._respond_json_text(200, response)
                    return
                else:
                    self._respond_plain_text(400, "Not a capability / Wrong format")
                    return
        else:
            # registration and result path are the same, so we need to differentiate the handling of the
            # request based on what's in the request body
            if isinstance(env, mplane.model.Result) \
                    or isinstance(env, mplane.model.Receipt) \
                    or isinstance(env, mplane.model.Exception):
                self._listenerclient.handle_message(env, self._tls.extract_peer_identity(self.request))
                self._respond_plain_text(200)
                return
            elif isinstance(env, mplane.model.Envelope):
                self._listenerclient.handle_message(env, self._tls.extract_peer_identity(self.request))
                for msg in env.messages():
                    if isinstance(msg, mplane.model.Result) or isinstance(env, mplane.model.Receipt):
                        self._respond_plain_text(200)
                        return
                    elif isinstance(msg, mplane.model.Capability) or isinstance(msg, mplane.model.Withdrawal):
                        response = self.generate_response(env)
                        self._respond_json_text(200, response)
                        return
            else:
                self._respond_plain_text(401, "Not authorized")
                return

    # FIXME noncompliant, see issue #4
    def generate_response(self, env):
        """
        Generate the response for the request containing the capabilities

        """
        response = ""
        for msg in env.messages():
            if isinstance(msg, mplane.model.Capability):
                response += "\"" + msg.get_label() + "\":{\"registered\":\"ok\"},"
            elif isinstance(msg, mplane.model.Withdrawal):
                response += "\"" + msg.get_label() + "\":{\"registered\":\"no\", \"reason\":\"Withdrawn\"},"
            else:
                response += "\"" + msg.get_label() + "\":{\"registered\":\"no\", \"reason\":\"Not a capability\"},"
        response = "{" + response[:-1].replace("\n", "") + "}"
        return response

    # FIXME here's where the 428 comes from, noncompliant, see issue #4
    def get(self):
        """
        Receives GET specification requests
        """

        # FIXME verify this works -- dodgy merge?
        # check if the path is correct (since we can receive a GET request also on registration_path or result_path)
        if self.request.path == self._listenerclient.specification_path:
            identity = self._tls.extract_peer_identity(self.request)

            if identity in self._listenerclient._capabilities_by_identity:

                # specification requests from a component are used as keep-alive,
                # so let's reset timeouts for capabilities from that component when we receive one
                for token in self._listenerclient._capabilities_by_identity[identity]:
                    self._listenerclient._capability_timeouts[token] = datetime.utcnow()

                specs = self._listenerclient._outgoing.pop(identity, [])
                env = mplane.model.Envelope()
                for spec in specs:

                    # if the 'link' field is empty, compose it using the host requested by the component/supervisor
                    if not spec.get_link():
                        if self._listenerclient.config is not None and "TLS" in self._listenerclient.config:
                            link = "https://"
                        else:
                            link = "http://"
                        link = link + self.request.host + self._listenerclient.result_path
                        spec.set_link(link)

                    logger.info("[fixme] AppendSpec %s" % spec)
                    env.append_message(spec)
                    if isinstance(spec, mplane.model.Specification):
                        logger.info("[fixme] Specification " + spec.get_label() + " successfully pulled by " + identity)
                    else:
                        logger.info("[fixme] Interrupt " + spec.get_token() + " successfully pulled by " + identity)

                self._respond_json_text(200, mplane.model.unparse_json(env))
            else:
                self._respond_plain_text(428, "not registered")
        else:
            self._respond_plain_text(401, "Wrong path for specification requests")

