---
title: mPlane Protocol Specification
abbrev: mPlane Protocol
docname: draft-trammell-mplane-protocol-01
date: 2016-3-18
category: info
ipr: trust200902
pi: [toc]


author:
  -
   ins: B. Trammell
   name: Brian Trammell
   role: editor
   org: ETH Zurich
   email: ietf@trammell.ch
   street: Gloriastrasse 35
   city: 8092 Zurich
   country: Switzerland
  -
   ins: M. Kuehlewind
   name: Mirja Kuehlewind
   role: editor
   org: ETH Zurich
   email: mirja.kuehlewind@tik.ee.ethz.ch
   street: Gloriastrasse 35
   city: 8092 Zurich
   country: Switzerland
informative:
  RFC3205:
  RFC3339:
  RFC4291:
  RFC5246:
  RFC5905:
  RFC5952:
  RFC6455:
  RFC7011:
  RFC7159:
  RFC7230:
  RFC7373:
  D14:
    target: https://www.ict-mplane.eu/sites/default/files//public/public-page/public-deliverables//1095mplane-d14.pdf
    title: mPlane Architecture Specification
    author:
      name: Brian Trammell
      ins: B. Trammell
    date: 2015-04-15


--- abstract

This document defines the mPlane architecture for
coordination of heterogeneous network measurement components: probes and
repositories that measure, analyze, and store network measurements,
data derived from measurements, and other ancillary data about elements
of the network. The architecture is defined in terms of relationships
between components and clients which communicate using the mPlane protocol
defined in this document.

This revision of the document describes Version 2 of the mPlane protocol. 

--- middle

# Introduction

This document describes the mPlane architecture and protocol, which is
designed to provide control and coordination of heterogeneous network
measurement tools. It is based heavily on the mPlane project's deliverable 1.4
{{D14}}, and is submitted for the information of the Internet engineering
community. {{overview-of-the-mplane-architecture}} gives an overview of the
mPlane architecture, {{protocol-information-model}} defines the protocol
information model, and {{representations-and-session-protocols}} defines the
representations of this data model and session protocols over which mPlane is
supported.

Present implementation work is focused on mPlane represented in JSON using
WebSockets {{RFC6455}} as a session protocol. {{workflows-in-websockets}}
demonstrates how mPlane's separation of connection initiation and message
initiation works in this environment. Previous versions of the mPlane protocol
used HTTPS as a session protocol {{RFC3205}}, but the asynchronous message-
oriented exchanges on which mPlane is built is more suited to a channel-
oriented session layer such as WebSockets.

This revision of the document describes Version 2 of the mPlane protocol. 

## Changes from Revision -00 (Protocol version 1)

- WebSockets has been added as a session protocol for the mPlane protocol.
- Redemptions have been expanded to allow temporally-scoped partial redemption of long-running measurements.
- The "object" primitive type has been added to allow structured objects to be represented directly in mPlane messages using the underlying representation.
- A number of obsolete features have been deprecated, and removed from the protcol description:
  - The Indirection message type, as the same functionality is available for all message types using the link section.
  - HTTPS as a session protocol, as it is a poor fit for mPlane's exchanges
  - Callback control, as it is no longer needed without the limitations of HTTPS as a session protocol
  - Repeating measurements, as their functionality has been replaced by partial redemption
- References to the "core" registry have been removed, as all element registries must in any case be explicitly defined in mPlane capabilities, specifications, and results. An eventual proposed standard mPlane protocol, if such is ever proposed, would refer to an IANA-managed core registry.

# Terminology

[EDITOR'S NOTE: these terms are not capitalized within the document at this time. Fix this.]

Client:
: An entity which implements the mPlane protocol, receives capabilities published by one or more components, and sends specifications to those component(s) to perform measurements and analysis. See {{components-and-clients}}.

Component:
: An entity which implements the mPlane protocol specified
within this document, advertises its capabilities and accepts specifications which request the use of those capabilities. The measurements, analyses, storage facilities and other services provided by a component are completely defined by its capabilities. See {{components-and-clients}}.

mPlane Message:
: The atomic unit of exchange in the mPlane protocol. The treatment of a message at a client or component receiving it is based upon its type; see {{message-types}}.

Capability:
: An mPlane message that contains a statement of a component's ability and willingness to perform a specific operation, conveyed from a component to a client. A capability does not represent a guarantee that the specific operation can or will be performed at a specific point in time. See {{capability-and-withdrawal}}

Specification:
: An mPlane message that contains a statement of a client's
desire that a component should perform a specific operation, conveyed from a
client to a component. It can be conceptually viewed as a capability whose
parameters have been filled in with values. See {{specification-and-interrupt}}.

Result:
: An mPlane message containing a statement produced by a component that a
particular measurement was taken and the given values were observed, or that a
particular operation or analysis was performed and a the given values were
produced. It can be conceptually viewed as a specification whose result
columns have been filled in with values. See {{result}}.

Element:
: An identifier for a parameter or result column in a capability, specification, or result, binding a name to a primitive type. Elements are contained in registries that contain the vocabulary from which mPlane capabilities, specifications, and results can be built. See {{element-registry}}.

# Overview of the mPlane Architecture

mPlane is built around an architecture in which components provide network measurement services and access to stored measurement data which they advertise via capabilities completely describing these services and data. A client makes use of these capabilities by sending specifications that respond to them back to the components. Components may then either return results directly to the clients or sent to some third party via indirect export using an external protocol. The capabilities, specifications, and results are carried over the mPlane protocol, defined in detail in this document. An mPlane measurement infrastructure is built up from these basic blocks.

Components can be roughly classified into probes which generate measurement data and repositories which store and analyze measurement data, though the difference between a probe and a repository in the architecture is merely a matter of the capabilities it provides. Components can be pulled together into an infrastructure by a supervisor, which presents a client interface to subordinate components and a component interface to superordinate clients, aggregating capabilities into higher-level measurements and distributing specifications to perform them.

This arrangement is shown in schematic form in the diagram below.

~~~~~~~~~~
             __________
            /           \
            |   Client  |
            \           /
             -----------
                  ^
                  | specification/capability/result
                  v
          ------------------
          |                |
          |   Supervisor   |
          |                |
          ------------------
                  ^
                  | specification/capability/result
                  |
        ---------------------
       |                     |
       v                     v
  /---------\ indirect \____________/
 < component >-------->| repository |
  \_________/  export  \____________/
~~~~~~~~~~
{: #overview title="General arrangement of entities in the mPlane architecture"}

The mPlane protocol is, in essence, a self-describing, error- and delay-tolerant remote procedure call (RPC) protocol: each capability exposes an entry point in the API provided by the component; each specification embodies an API call; and each result returns the results of an API call.

## Key Architectural Principles and Features

mPlane differs from a simple RPC facility in several important ways, detailed in the subsections below.

### Flexibility and Extensibility

First, given the heterogeneity of the measurement tools and techniques applied, it is necessary for the protocol to be as flexible and extensible as possible. Therefore, the architecture in its simplest form consists of only two entities and one relationship, as shown in the diagram below: n clients connect to m components via the mPlane protocol. Anything which can speak the mPlane protocol and exposes capabilities thereby is a component; anything which can understand these capabilities and send specifications to invoke them is a client. Everything a component can do, from the point of view of mPlane, is entirely described by its capabilities. Capabilities are even used to expose optional internal features of the protocol itself, and provide a method for built-in protocol extensibility.

### Schema-centric Measurement Definition

Second, given the flexibility required above, the key to measurement interoperability is the comparison of data types. Each capability, specification, and result contains a schema, comprising the set of parameters required to execute a measurement or query and the columns in the data set that results. From the point of view of mPlane, the schema completely describes the measurement. This implies that when exposing a measurement using mPlane, the developer of a component must build each capabilities it advertises such that the semantics of the measurement are captured by the set of columns in its schema. The elements from which schemas can be built are captured in a type registry. The mPlane platform provides a core registry for common measurement use cases within the project, and the registry facility is itself fully extensible as well, for supporting new applications without requiring central coordination beyond the domain or set of domains running the application.

### Iterative Measurement Support

Third, the exchange of messages in the protocol was chosen to support iterative measurement in which the aggregated, high-level results of a measurement are used as input to a decision process to select the next measurement. Specifically, the protocol blends control messages (capabilities and specifications) and data messages (results) into a single workflow.

<!-- this is shown in the diagram below.

 ![Iterative measurement in mPlane](./iterative-measurement.png)  -->

### Weak Imperativeness

Fourth, the mPlane protocol is weakly imperative. A capability represents a willingness and an ability to perform a given measurement or execute a query, but not a guarantee or a reservation to do so. Likewise, a specification contains a set of parameters and a temporal scope for a measurement a client wishes a component to perform on its behalf, but execution of specifications is best-effort. A specification is not an instruction which must result either in data or in an error. This property arises from our requirement to support large-scale measurement infrastructures with thousands of similar components, including resource- and connectivity-limited probes such as smartphones and customer-premises equipment (CPE) like home routers. These may be connected to a supervisor only intermittently. In this environment, the operability and conditions in which the probes find themselves may change more rapidly than can be practicably synchronized with a central supervisor; requiring reliable operation would compromise scalability of the architecture.

To support weak imperativeness, each message in the mPlane protocol is self-contained, and contains all the information required to understand the message. For instance, a specification contains the complete information from the capability which it responds to, and a result contains its specification. In essence, this distributes the state of the measurements running in an infrastructure across all components, and any state resynchronization that is necessary after a disconnect happens implicitly as part of message exchange. The failure of a component during a large-scale measurement can be detected and corrected after the fact, by examining the totality of the generated data.

This distribution of state throughout the measurement infrastructure carries with it a distribution of responsibility: a component holding a specification is responsible for ensuring that the measurement or query that the specification describes is carried out, because the client or supervisor which has sent the specification does not necessarily keep any state for it.

Error handling in a weakly imperative environment is different to that in traditional RPC protocols. The exception facility provided by mPlane is designed only to report on failures of the handling of the protocol itself. Each component and client makes its best effort to interpret and process any authorized, well-formed mPlane protocol message it receives, ignoring those messages which are spurious or no longer relevant. This is in contrast with traditional RPC protocols, where even common exceptional conditions are signaled, and information about missing or otherwise defective data must be correlated from logs about measurement control. This traditional design pattern is not applicable in infrastructures where the supervisor has no control over the functionality and availability of its associated probes.

## Entities and Relationships

The entities in the mPlane protocol and the relationships among them are described in more detail in the subsections below.

### Components and Clients

Specifically, a component is any entity which implements the mPlane protocol specified
within this document, advertises its capabilities and accepts specifications which request the use of those capabilities. The measurements, analyses, storage facilities and other services provided by a component are completely defined by its capabilities.

Conversely, a client is any entity which implements the mPlane protocol, receives capabilities published by one or more components, and sends specifications to those component(s) to perform  measurements and analysis.

Every interaction in the mPlane protocol takes place between a component and a client. Indeed, the simplest instantiation of the mPlane architecture consists of one or more clients taking capabilities from one or more components, and sending specifications to invoke those capabilities, as shown in the diagram below. An mPlane domain may consist of as little as a single client and a single component. In this arrangement, mPlane provides a measurement-oriented RPC mechanism.

~~~~~~~~~~
          ________________
          |              |
          |    client    |
          |              |
          ----------------
            ^   n|     |
 capability |    |     | specification
            |    |m    v
          ________________
          |              |
          |  component   |
          |              |
          ----------------
~~~~~~~~~~
{: #simple title="The simplest form of the mPlane architecture"}

### Probes and Repositories

Measurement components can be roughly divided into two categories: probes and repositories. Probes perform measurements, and repositories provide access to stored measurements, analysis of stored measurements, or other access to related external data sources. External databases and data sources (e.g., routing looking glasses, WHOIS services, DNS, etc.) can be made available to mPlane clients through repositories acting as gateways to these external sources, as well.

Note that this categorization is very rough: what a component can do is completely described by its capabilities, and some components may combine properties of both probes and repositories.

### Supervisors and Federation

An entity which implements both the client and component interfaces can be used to build and federate domains of mPlane components. This supervisor is responsible for collecting capabilities from a set of components, and providing capabilities based on these to its clients. Application-specific algorithms at the supervisor aggregate the lower-level capabilities provided by these components into higher-level capabilities exposed to its clients. This arrangement is shown in the figure below.

~~~~~~~~~~
                    ________________
                    |              |
                    |    client    |
                    |              |
                    ----------------
                      ^   n|     |
           capability |    |     | specification
                      |    |1    v
                    ________________
                  .-|   component  |-.
                 |  ----------------  |
                 |     supervisor     |
                 |  ________________  |
                  \_|    client    |_/
                    ----------------
                      ^   1|     |
           capability |    |     | specification
                      |    |m    v
                    ________________
                    |              |
                    |  component   |
                    |              |
                    ----------------
~~~~~~~~~~
{: #simple-supervisor title="Simple mPlane architecture with a supervisor"}

The set of components which respond to specifications from a single supervisor
is referred to as an mPlane domain. Domain membership is also determined by the issuer of the certificates identifying the clients, components, and supervisor. Within a given domain, each client and component connects to only one supervisor. Underlying measurement components and clients may indeed participate in multiple domains, but these are separate entities from the point of view of the architecture. Interdomain measurement is supported by federation among supervisors: a local supervisor delegates measurements in a remote domain to that domain's supervisor.

<!-- , as shown in the figure below.

![Federation between supervisors](./federation-architecture.png) -->

In addition to capability composition and specification decomposition, supervisors are responsible for client and component registration and authentication, as well as access control based on  identity information provided by the session protocol (WebSockets) in the general case.

Since the logic for aggregating control and data for a given application is very specific to that application, note that there is no generic supervisor implementation provided with the mPlane SDK.

### External Interfaces to mPlane Entities

The mPlane protocol specified in this document is designed for the exchange of control messages in an iterative measurement process, and the retrieval of low volumes of highly aggregated data, primarily that leads to decisions about subsequent measurements and/or a final determination.

For measurements generating large amounts of data (e.g. passive observations of high-rate links, or high-frequency active measurements), mPlane supports indirect export. For indirect export, a client or supervisor directs one component (generally a probe) to send results to another component (generally a repository). This indirect export protocol is completely external to the mPlane protocol; the client must only know that the two components support the same protocol and that the schema of the data produced by the probe matches that accepted by the repository. The typical example consists of passive mPlane-controlled probes exporting volumes of data (e.g., anonymized traces, logs, statistics), to an mPlane-accessible repository out-of-band. The use of out-of-band indirect export is justified to avoid serialization overhead, and to ensure fidelity and reliability of the transfer.

For exploratory analysis of large amounts of data at a repository, it is presumed that clients will have additional back-channel direct access beyond those interactions mediated by mPlane. For instance, a repository backed by a relational database could have a web-based graphical user interface that interacts directly with the database.


## Message Types and Message Exchange Sequences

The basic messages in the mPlane protocol are capabilities, specifications, and results, as described above. The full protocol contains other message types as well. Withdrawals cancel capabilities (i.e., indicate that the component is no longer capable or willing to perform a given measurement) and interrupts cancel specifications (i.e., indicate that the component should stop performing the measurement). Receipts can be given in lieu of results for not-yet completed measurements or queries, and redemptions can be used to retrieve results referred to by a receipt. Exceptions can be sent by clients or components at any time to signal protocol-level errors to their peers.

<!-- ![Potential sequences of messages in the mPlane protocol](./message-paths.png) -->

In the nominal sequence, a capability leads to a specification leads to a result, where results may be transmitted by some other protocol. All the paths through the sequence of messages are shown in the diagram below; message types are described in detail in {{message-types}}. In the diagram, solid lines mean a message is sent in reply to the previous message in sequence (i.e. a component sends a capability, and a client replies or follows with a specification), and dashed lines mean a message is sent as a followup (i.e., a component sends a capability, then sends a withdrawal to cancel that capability). Messages at the top of the diagram are sent by components, at the bottom by clients.

Separate from the sequence of messages, the mPlane protocol supports two connection establishment patterns:

  - Client-initiated, in which clients connect directly to components at known, stable URLs. Client-initiated workflows are intended for use between clients and supervisors, for access to repositories, and for access to probes embedded within a network infrastructure.

  - Component-initiated, in which components initiate connections to clients. Component-initiated workflows are intended for use between components without stable routable addresses and supervisors, e.g. for small probes on embedded devices, mobile devices, or software probes embedded in browsers on personal computers behind network-address translators (NATs) or firewalls which prevent a client from establishing a connection to them.

Within a given mPlane domain, these patterns can be combined (along with indirect export and direct access) to facilitate complex interactions among clients and components according to the requirements imposed by the application and the deployment of components in the network.


## Integrating Measurement Tools into mPlane

mPlane's flexibility and the self-description of measurements provided by the capability-specification-result cycle was designed to allow a wide variety of existing measurement tools, both probes and repositories, to be integrated into an mPlane domain. In both cases, the key to integration is to define a capability for each of the measurements the tool can perform or the queries the repository needs to make available within an mPlane domain. Each capability has a set of parameters - information required to run the measurement or the query - and a set of result columns - information which the measurement or query returns.

The parameters and result columns make up the measurement's schema, and are chosen from an extensible registry of elements. Practical details are given in {{designing-measurement-and-repository-schemas}}.


## From Architecture to Protocol Specification

The remainder of this document builds the protocol specification based on this architecture from the bottom up. First, we define the protocol's information model from the element registry through the types of mPlane messages and the sections they are composed of. We then define a concrete representation of this information model using Javascript Object Notation (JSON, {{RFC7159}}), and define bindings to WebSockets {{RFC6455}}} over TLS as a session protocol. 

# Protocol Information Model

The mPlane protocol is message-oriented, built on the representation- and session-protocol-independent exchange of messages between clients and components. This section describes the information model, starting from the element registry which defines the elements from which capabilities can be built, then detailing each type of message, and the sections that make these messages up. It then provides advice on using the information model to model measurements and queries.

## Element Registry

An element registry makes up the vocabulary by which mPlane components and clients can express the meaning of parameters, metadata, and result columns for mPlane statements. A registry is represented as a JSON {{RFC7159}} object with the following keys:

- registry-format: currently `mplane-0`, determines the supported features of the registry format.
- registry-uri: the URI identifying the registry. The URI must be dereferencable to retrieve the canonical version of this registry.
- registry-revision: a serial number starting with 0 and incremented with each revision to the content of the registry.
- includes: a list of URLs to retrieve additional registries from. Included registries will be evaluated in depth-first order, and elements with identical names will be replaced by registries parsed later.
- elements: a list of objects, each of which has the following three keys:
    - name: The name of the element.
- prim: The name of the primitive type of the element, from the list of primitives in {{primitive-types}}.
    - desc: An English-language description of the meaning of the element.

Since the element names will be used as keys in mPlane messages, mPlane binds to JSON, and JSON mandates lowercase key names, element names must use only lowercase letters.

An example registry with two elements and no includes follows:

~~~~~~~~~~
{ "registry-format": "mplane-0",
  "registry-uri", "https://example.com/mplane/registry/core",
  "registry-revision": 0,
  "includes": [],
  "elements": [
      { "name": "full.structured.name",
        "prim": "string",
        "desc": "A representation of foo..."
      },
      { "name": "another.structured.name",
        "prim": "string",
        "desc": "A representation of bar..."
      },
  ]
}
~~~~~~~~~~

Fully qualified element names consist of the element's name as an anchor after the URI from which the element came, e.g. `https://example.com/mplane/registry/core#full.structured.name`. Elements within the type registry are considered globally equal based on their fully qualified names. However, within a given mPlane message, elements are considered equal based on unqualified names.

### Structured Element Names

To ease understanding of mPlane type registries, element names are structured by convention; that is, an element name is made up of the following structural parts in order, separated by the dot ('.') character:

- basename: exactly one, the name of the property the element specifies or measures. All elements with the same basename describe the same basic property. For example, all elements with basename '`source`' relate to the source of a packet, flow, active measurement, etc.; and elements with basename '`delay`'' relate to the measured delay of an operation.
- modifier: zero or more, additional information differentiating elements with the same basename from each other. Modifiers may associate the element with a protocol layer, or a particular variety of the property named in the basename. All elements with the same basename and modifiers refer to exactly the same property. Examples for the `delay` basename include `oneway` and `twoway`, differentiating whether a delay refers to the path from the source to the destination or from the source to the source via the destination; and `icmp` and `tcp`, describing the protocol used to measure the delay.
- units: zero or one, present if the quantity can be measured in different units.
- aggregation: zero or one, if the property is a metric derived from multiple singleton measurements. Supported aggregations are:
  - `min`: minimum value
  - `max`: maximum value
  - `mean`: mean value
  - `sum`: sum of values
  - `NNpct` (where NN is a two-digit number 01-99): percentile
  - `median`: shorthand for and equivalent to `50pct`.
  - `count`: count of values aggregated

When mapping mPlane structured names into contexts in which dots have special meaning (e.g. SQL column names or variable names in many programming languages), the dots may be replaced by underscores ('_'). When using external type registries (e.g. the IPFIX Information Element Registry), element names are not necessarily structured.

### Primitive Types {#primitive-types}

The mPlane protocol supports the following primitive types for elements in the type registry:

- string: a sequence of Unicode characters
- natural: an unsigned integer
- real: a real (floating-point) number
- bool: a true or false (boolean) value
- time: a timestamp, expressed in terms of UTC. The precision of the timestamp is taken to be unambiguous based on its representation.
- address: an identifier of a network-level entity, including an address family. The address family is presumed to be implicit in the format of the message, or explicitly stored. Addresses may represent specific endpoints or entire networks.
- url: a uniform resource locator
- object: a structured object, serialized according to the serialization rules of the underlying representation.

### Augmented Registry Information

Additional keys beyond prim, desc, and name may appear in an mPlane registry to augment information about each element. The following additional registry keys have been found useful by some implementors of the protocol:

- units: If applicable, string describing the units in which the element is expressed; equal to the units part of a structured name if present.
- ipfix-eid: The element ID of the equivalent IPFIX {{RFC7011}} Information Element.
- ipfix-pen: The SMI Private Enterprise Number of the equivalent IPFIX {{RFC7011}} Information Element, if any.

## Message Types {#message-types}

Workflows in mPlane are built around the capability - specification - result cycle. Capabilities, specifications, and results are kinds of statements: a capability is a statement that a component can perform some action (generally a measurement); a specification is a statement that a client would like a component to perform the action advertised in a capability; and a result is a statement that a component measured a given set of values at a given point in time according to a specification.

Other types of messages outside this nominal cycle are referred to as notifications. Types of notifications include Withdrawals, Interrupts, Receipts, Redemptions, and Exceptions. These notify clients or components of conditions within the measurement infrastructure itself, as opposed to directly containing information about measurements or observations.

Messages may also be grouped together into a single envelope message. Envelopes allow multiple messages to be represented within a single message, for example multiple Results pertaining to the same Receipt; and multiple Capabilities or Specifications to be transferred in a single transaction in the underlying session protocol.

The following types of messages are supported by the mPlane protocol:

### Capability and Withdrawal

A capability is a statement of a component's ability and willingness to
perform a specific operation, conveyed from a component to a client. It does
not represent a guarantee that the specific operation can or will be performed
at a specific point in time.

A withdrawal is a notification of a component's inability or unwillingness to
perform a specific operation. It cancels a previously advertised capability. A
withdrawal can also be sent in reply to a specification which attempts to
invoke a capability no longer offered.

### Specification and Interrupt

A specification is a statement that a component should perform a specific
operation, conveyed from a client to a component. It can be conceptually
viewed as a capability whose parameters have been filled in with values.

An interrupt is a notification that a component should stop performing a
specific operation, conveyed from client to component. It terminates a
previously sent specification. If the specification uses indirect export, the
indirect export will simply stop running. If the specification has pending
results, those results are returned in response to the interrupt.

### Result

A result is a statement produced by a component that a particular measurement
was taken and the given values were observed, or that a particular operation or
analysis was performed and a the given values were produced. It can be
conceptually viewed as a specification whose result columns have been filled in with
values. Note that, in keeping with the stateless nature of the mPlane protocol, a
result contains the full set of parameters from which it was derived.

Note that not every specification will lead to a result being returned; for example,
in case of indirect export, only a receipt which can be used for future interruption
will be returned, as the results will be conveyed to a third component using an
external protocol.

### Receipt and Redemption

A receipt is returned instead of a result by a component in response to a specification which either:

- will never return results, as it initiated an indirect export, or
- will not return results immediately, as the operation producing the results will have a long run time.

Receipts have the same content specification they are returned for.
A component may optionally add a token section, which can be used
in future redemptions or interruptions by the client. The content of
the token is an opaque string generated by the component.

A redemption is sent from a client to a component for a previously received
receipt to attempt to retrieve delayed results. It may contain only the token
section, the token and temporal scope, or all sections of the received
receipt.

When the temporal scope of a redemption for a running measurement is different
than the temporal scope of the original specification, it is treated by the
component as a partial redemption: all rows resulting from the measurement
within the specified temporal scope are returned as a result. Otherwise, a
component responds with a result only when the measurement is complete;
otherwise, another receipt is returned.

### Exception

An exception is sent from a client to a component or from a component to a client to signal an exceptional condition within the infrastructure itself. They are not meant to signal exceptional conditions within a measurement performed by a component; see {{error-handling-in-mplane-workflows}} for more. An exception contains only two sections: an optional token referring back to the message to which the exception is related (if any), and a message section containing free-form, preferably human readable information about the exception.

### Envelope

An envelope is used to contain other messages. Message containment is necessary in contexts in which multiple mPlane messages must be grouped into a single transaction in the underlying session protocol. It is legal to group any kind of message, and to mix messages of different types, in an envelope. However, in the current revision of the protocol, envelopes are primarily intended to be used for three distinct purposes:

- To group multiple capabilities together within a single message (e.g., all the capabilities a given component has).
- To return multiple results for a single receipt or specification.
- To group multiple specifications into a single message.

## Message Sections

Each message is made up of sections, as described in the subsection below. The following table shows the presence of each of these sections in each of the message types supported by mPlane: "req." means the section is required, "opt." means it is optional; see the subsection on each message section for details.

~~~~~~~~~~
| Section        | Capability | Spec. | Result | Receipt    | Envelope |
| -------------- | ---------- | ----- | ------ |------------|----------|
| Verb           | req.       | req   | req.   | req.       |          |
| Content Type   |            |       |        |            | req.     |
| `version`      | req.       | req.  | req.   | req.       | req.     |
| `registry`     | req.       | req.  | req.   | opt.       |          |
| `label`        | opt.       | opt.  | opt.   | opt.       | opt.     |
| `when`         | req.       | req.  | req.   | req.       |          |
| `parameters`   | req./token | req.  | req.   | opt./token |          |
| `metadata`     | opt./token | opt.  | opt.   | opt./token |          |
| `results`      | req./token | req.  | req.   | opt./token |          |
| `resultvalues` |            |       | req.   |            |          |
| `export`       | opt.       | opt.  | opt.   | opt.       |          |
| `link`         | opt.       | opt.  |        |            |          |
| `token`        | opt.       | opt.  | opt.   | opt.       | opt.     |
| `contents`     |            |       |        |            | req.     |
~~~~~~~~~~
{: #table-messages title="Message Sections for Each Message Type"}

Withdrawals take the same sections as capabilities; and redemptions
and interrupts take the same sections as receipts. Exceptions are not shown in this table.

### Message Type and Verb

The verb is the action to be performed by the component. The following verbs
are supported by the base mPlane protocol, but arbitrary verbs may be specified
by applications:

- `measure`: Perform a measurement
- `query`: Query a database about a past measurement
- `collect`: Receive results via indirect export
- `callback`: Used for callback control in component-initiated workflows

In the JSON representation of mPlane messages, the verb is the value of the key corresponding to the message's type, represented as a lowercase string (e.g. `capability`, `specification`, `result` and so on).

Roughly speaking, probes implement `measure` capabilities, and repositories
implement `query` and `collect` capabilities. Of course, any single component
can implement capabilities with any number of different verbs.

Within the SDK, the primary difference between `measure` and `query` is that the temporal scope of a `measure` specification is taken to refer to when the measurement should be scheduled, while the temporal scope of a  `query` specification is taken to refer to the time window (in the past) of a query.

Envelopes have no verb; instead, the value of the `envelope` key is the kind of messages the envelope contains, or `message` if the envelope contains a mixture of different unspecified kinds of messages.

### Version

The `version` section contains the version of the mPlane protocol to which the message conforms, as an integer serially incremented with each new protocol revision. This section is required in all messages. This document describes version 2 of the protocol.

### Registry

The `registry` section contains the URL identifying the element registry used by this message, and from which the registry can be retrieved. This section is required in all messages containing element names (statements, and receipts/redemptions/interrupts not using tokens for identification; see the `token` section).

### Label

The `label` section of a statement contains a human-readable label identifying it, intended solely for use when displaying information about messages in user interfaces. Results, receipts, redemptions, and interrupts inherit their label from the specification from which they follow; otherwise, client and component software can arbitrarily assign labels . The use of labels is optional in all messages, but as labels do greatly ease human-readability of arbitrary messages within user interfaces, their use is recommended.

mPlane clients and components should never use the label as a unique identifier for a message, or assume any semantic meaning in the label -- the test of message equality and relatedness is always based upon the schema and values as in {{message-uniqueness-and-idempotence}}.

### Temporal Scope (When) {#temporal-scope}

The `when` section of a statement contains its temporal scope.

A temporal scope refers to when a measurement can be run (in a capability), when it should be run (in a specification), or when it was run (in a result). Temporal scopes can be either absolute or relative, and may have an optional period, referring to how often single measurements should be taken.

The general form of a temporal scope (in BNF-like syntax) is as follows:

~~~~~~~~~~
when = <singleton> |                # A single point in time
           <range> |                # A range in time
         <range> ' / ' <duration>   # A range with a period

singleton = <iso8601> | # absolute singleton
            'now'       # relative singleton

range = <iso8601> ' ... ' <iso8601> | # absolute range
        <iso8601> ' + ' <duration> |  # relative range
        'now' ' ... ' <iso8061> |     # definite future
        'now' ' + ' <duration> |      # relative future
        <iso8601> ' ... ' 'now' |     # definite past
        'past ... now' |              # indefinite past
        'now ... future' |            # indefinite future
        <iso8601> ' ... ' 'future' |  # absolute indefinite future
        'past ... future' |           # forever

duration = [ <n> 'd' ] # days
           [ <n> 'h' ] # hours
           [ <n> 'm' ] # minute
           [ <n> 's' ] # seconds

iso8601 = <n> '-' <n> '-' <n> [' ' <n> ':' <n> ':' <n> [ '.' <n> ]]
~~~~~~~~~~

All absolute times are always given in UTC and expressed in ISO8601 format with variable precision.

In capabilities, if a period is given it represents the minimum period supported by the measurement; this is done to allow rate limiting. If no period is given, the measurement is not periodic. A capability with a period can only be fulfilled by a specification with period greater than or equal to the period in the capability. Conversely, a capability without a period can only be fulfilled by a specification without a period.

Within a result, only absolute ranges are allowed within the temporal scope, and refers to the time range of the measurements contributing to the result. Note that the use of absolute times here implies that the components and clients within a domain should have relatively well-synchronized clocks, e.g., to be synchronized using the Network Time Protocol {{RFC5905}} in order for results to be temporally meaningful.

So, for example, an absolute range in time might be expressed as:

`when: 2009-02-20 13:02:15 ... 2014-04-04 04:27:19`

A relative range covering three and a half days might be:

`when: 2009-04-04 04:00:00 + 3d12h`

In a specification for running an immediate measurement for three hours every seven and a half minutes:

`when: now + 3h / 7m30s`

In a capability noting that a Repository can answer questions about the past:

`when: past ... now`.

In a specification requesting that a measurement run from a specified point in time until interrupted:

`when: 2017-11-23 18:30:00 ... future`

### Parameters {#parameters}

The `parameters` section of a message contains an ordered list of the parameters for a given measurement: values which must be provided by a client to a component in a specification to convey the specifics of the measurement to perform. Each parameter in an mPlane message is a key-value pair, where the key is the name of an element from the element registry. In specifications and results, the value is the value of the parameter. In capabilities, the value is a constraint on the possible values the component will accept for the parameter in a subsequent specification.

Four kinds of constraints are currently supported for mPlane parameters:

- No constraint: all values are allowed. This is signified by the special constraint string '`*`'.
- Single value constraint: only a single value is allowed. This is intended for use for capabilities which are conceivably configurable, but for which a given component only supports a single value for a given parameter due to its own out-of-band configuration or the permissions of the client for which the capability is valid. For example, the source address of an active measurement of a single-homed probe might be given as '`source.ip4: 192.0.2.19`'.
- Set constraint: multiple values are allowed, and are explicitly listed, separated by the '`,`' character. For example, a multi-homed probe allowing two potential source addresses on two different networks might be given as '`source.ip4: 192.0.2.19, 192.0.3.21`'.
- Range constraint: multiple values are allowed, between two ordered values, separated by the special string '`...`'. Range constraints are inclusive. A measurement allowing a restricted range of source ports might be expressed as '`source.port: 32768 ... 65535`'
- Prefix constraint: multiple values are allowed within a single network, as specified by a network address and a prefix. A prefix constraint may be satisfied by any network of host address completely contained within the prefix. An example allowing probing of any host within a given /24 might be '`destination.ip4: 192.0.2.0/24`'.

Parameter and constraint values must be a representation of an instance of the primitive type of the associated element.

### Metadata

The `metadata` section contains measurement metadata: key-value pairs associated with a capability inherited by its specification and results. Metadata can also be thought of as immutable parameters. This is intended to represent information which can be used to make decisions at the client as to the applicability of a given capability (e.g. details of algorithms used or implementation-specific information) as well as to make adjustments at post-measurement analysis time when contained within results.

An example metadata element might be '`measurement.identifier: qof`', which identifies the underlying tool taking measurements, such that later analysis can correct for known peculiarities in the implementation of the tool.  Another example might be '`location.longitude = 8.55272`', which while not particularly useful for analysis purposes, can be used to draw maps of measurements.

### Result Columns and Values

Results are represented using two sections: `results` which identify the elements to be returned by the measurement, and `resultvalues` which contains the actual values. `results` appear in all statements, while `resultvalues` appear only in result messages.

The `results` section contains an ordered list of result columns for a given measurement: names of elements which will be returned by the measurement. The result columns are identified by the names of the elements from the element registry.

The `resultvalues` section contains an ordered list of ordered lists (or, rather, a two dimensional array) of values of results for a given measurement, in row-major order. The columns in the result values appear in the same order as the columns in the `results` section.

Values for each column must be a representation of an instance of the primitive type of the associated result column element.

### Export

The `export` section contains a URL or partial URL for indirect export. Its meaning depends on the kind and verb of the message:

- For capabilities with the `collect` verb, the `export` section contains the URL of the collector which can accept indirect export for the schema defined by the `parameters` and `results` sections of the capability, using the protocol identified by the URL's schema.

- For capabilities with any verb other than `collect`, the `export` section contains either the URL of a collector to which the component can indirectly export results, or a URL schema identifying a protocol over which the component can export to arbitrary collectors.
- For specifications with any verb other than `collect`, the `export` section contains the URL of a collector to which the component should indirectly export results. A receipt will be returned for such specifications.

If a component can indirectly export or indirectly collect using multiple protocols, each of those protocols must be identified by its own capability; capabilities with an `export` section can only be used by specifications with a matching `export` section.

### Link

The `link` section contains the URL to which messages in the next step in the
workflow (i.e. a specification for a capability, a result or receipt for a
specification) can be sent, providing indirection. The link URL must currently
have the schema `wss`, and refers to the URL to which to initiate a
connection.

If present in a capability, the client must send specifications for the given capability to the component at the URL given in order to use the capability, connecting to the URL if no connection is currently established. If present in a specification, the component must send results for the given specification back to the client at the URL given, connecting to the URL if no connection is currently established.

### Token

The `token` section contains an arbitrary string by which a message may be identified in subsequent communications in an abbreviated fashion. Unlike labels, tokens are not necessarily intended to be human-readable; instead, they provide a way to reduce redundancy on the wire by replacing the parameters, metadata, and results sections in messages within a workflow, at the expense of requiring more state at clients and components. Their use is optional.

Tokens are scoped to the association between the component and client in which they are first created; i.e., at a component, the token will be associated with the client's identity, and vice-versa at a client. Tokens should be created with sufficient entropy to avoid collision from independent processes at the same client or token reuse in the case of client or component state loss at restart.

If a capability contains a token, it may be subsequently withdrawn by the same component using a withdrawal containing the token instead of the parameters, metadata, and results sections.

If a specification contains a token, it may be answered by the component with a receipt containing the token instead of the parameters, metadata, and results sections. A specification containing a token may likewise be interrupted by the client with an interrupt containing the token. A component must not answer a specification with a token with a receipt or result containing a different token, but the token may be omitted in subsequent receipts and results.

If a receipt contains a token, it may be redeemed by the same client using a redemption containing the token instead of the parameters, metadata, and results sections.

When grouping multiple results from a repeating specification into an envelope, the envelope may contain the token of the repeating specification.

### Contents

The `contents` section appears only in envelopes, and is an ordered list of messages. If the envelope's kind identifies a message kind, the contents may contain only messages of the specified kind, otherwise if the kind is `message`, the contents may contain a mix of any kind of message.

## Message Uniqueness and Idempotence {#message-uniqueness-and-idempotence}

Messages in the mPlane protocol are intended to support state distribution: capabilities, specifications, and results are meant to be complete declarations of the state of a given measurement. In order for this to hold, it must be possible for messages to be uniquely identifiable, such that duplicate messages can be recognized. With one important exception (i.e., specifications with relative temporal scopes), messages are idempotent: the receipt of a duplicate message at a client or component is a null operation.

### Message Schema

The combination of elements in the `parameters` and `results` sections, together with the registry from which these elements are drawn, is referred to as a message's schema. The schema of a measurement can be loosely thought of as the definition of the table, rows of which the message represents.

The schema contributes not only to the identity of a message, but also to the semantic interpretation of the parameter and result values. The meanings of element values in mPlane are dependent on the other elements present in the message; in other words, the key to interpreting an mPlane message is that the unit of semantic identity is a message. For example, the element '`destination.ip4`' as a parameter means "the target of a given active measurement" when together with elements describing an active metric (e.g. '`delay.twoway.icmp.us`'), but "the destination of the packets in a flow" when together with other elements in result columns describing a passively-observed flow.

The interpretation of the semantics of an entire message is application-specific. The protocol does not forbid the transmission of messages representing semantically meaningless or ambiguous schemas.

### Message Identity

A message's identity is composed of its schema, together with its temporal scope, metadata, parameter values, and indirect export properties. Concretely, the full content of the `registry`, `when`, `parameters`, `metadata`, `results`, and `export` sections taken together comprise the message's identity.

One convenience feature complicates this somewhat: when the temporal scope is not absolute, multiple specifications may have the same literal temporal scope but refer to different measurements. In this case, the current time at the client or component when a message is invoked must be taken as part of the message's identity as well. Implementations may use hashes over the values of the message's identity sections to uniquely identify messages; e.g. to generate message tokens.

## Designing Measurement and Repository Schemas

As noted, the key to integrating a measurement tool into an mPlane infrastructure is properly defining the schemas for the measurements and queries it performs, then defining those schemas in terms of mPlane capabilities. Specifications and results follow naturally from capabilities, and the mPlane SDK allows Python methods to be bound to capabilities in order to execute them. A schema should be defined such that the set of parameters, the set of result columns, and the verb together naturally and uniquely define the measurement or the query being performed. For simple metrics, this is achieved by encoding the entire meaning of the  metric in its name. For example, `delay.twoway.icmp.us` as a result column together with `source.ip4` and `destination.ip4` as parameters uniquely defines a single ping measurement, measured via ICMP, expressed in microseconds.

Aggregate measurements are defined by returning metrics with aggregations: `delay.twoway.icmp.min.us`, `delay.twoway.icmp.max.us`, `delay.twoway.icmp.mean.us`, and `delay.twoway.icmp.count.us` as result columns represent aggregate ping measurements with multiple samples.

Note that mPlane results may contain multiple rows. In this case, the parameter values in the result, taken from the specification, apply to all rows. In this case, the rows are generally differentiated by the values in one or more result columns; for example, the `time` element can be used to represent time series, or the `hops.ip` different elements along a path between source and destination, as in a traceroute measurement.

For measurements taken instantaneously, the verb `measure` should be used; for direct queries from repositories, the verb `query` should be used. Other actions that cannot be differentiated by schema alone should be differentiated by a custom verb.

When integrating a repository into an mPlane infrastructure, only a subset of the queries the repository can perform will generally be exposed via the mPlane interface. Consider a generic repository which provides an SQL interface for querying data; wrapping the entire set of possible queries in specific capabilities would be impossible, while providing direct access to the underlying SQL (for instance, by creating a custom registry with a `query.sql` string element to be used as a parameter) would make it impossible to differentiate capabilities by schema (thereby making the interoperability benefits of mPlane integration pointless). Instead, specific queries to be used by clients in concert with capabilities provided by other components are each wrapped within a separate capability, analogous to stored procedure programming in many database engines. Of course, clients which do speak the precise dialect of SQL necessary can integrate directly with the repository separate from the capabilities provided over mPlane.

# Representations and Session Protocols

The mPlane protocol is built atop an abstract data model in order to support multiple representations and session protocols. The canonical representation supported by the present SDK involves JSON {{RFC7159}} objects transported via Websockets {{RFC6455}} over TLS {{RFC5246}} (known by the "wss" URL schema).

## JSON representation

In the JSON representation, an mPlane message is a JSON object, mapping sections by name to their contents. The name of the message type is a special section key, which maps to the message's verb, or to the message's content type in the case of an envelope.

Each section name key in the object has a value represented in JSON as follows:

- `version` : an integer identifying the mPlane protocol version used by the message.
- `registry` : a URL identifying the registry from which element names are taken.
- `label` : an arbitrary string.
- `when` : a string containing a temporal scope, as described in {{temporal-scope}}.
- `parameters` : a JSON object mapping (non-qualified) element names, either to constraints or to parameter values, as appropriate, and as described in {{parameters}}.
- `metadata` : a JSON object mapping (non-qualified) element names to metadata values.
- `results` : an array of element names.
- `resultvalues` : an array of arrays of element values in row major order, where each row array contains values in the same order as the element names in the `results` section.
- `export` : a URL for indirect export.
- `link` : a URL for message indirection.
- `token` : an arbitrary string.
- `contents` : an array of objects containing messages.

### Textual representations of element values

Each primitive type is represented as a value in JSON as follows, following the Textual Representation of IPFIX Abstract Data Types defined in {{RFC7373}}.

Natural and real values are represented in JSON using native JSON representation for numbers.

Booleans are represented by the reserved words `true` and `false`.

Strings and URLs are represented as JSON strings, subject to JSON escaping rules.

Addresses are represented as dotted quads for IPv4 addresses as they would be in URLs, and canonical IPv6 textual addresses as in section 2.2 of {{RFC4291}} as updated by section 4 of {{RFC5952}}. When representing networks, addresses may be suffixed as in CIDR notation, with a '`/`' character followed by the mask length in bits n, provided that the least significant 32 − n or 128 − n bits of the address are zero, for IPv4 and IPv6 respectively.

Timestamps are represented in {{RFC3339}} and ISO 8601, with two important differences. First, all mPlane timestamps are are expressed in terms of UTC, so time zone offsets are neither required nor supported, and are always taken to be 0. Second, fractional seconds are represented with a variable number of digits after an optional decimal point after the fraction.

Objects are represented as JSON objects.

### Example mPlane Capabilities and Specifications in JSON

To illustrate how mPlane messages are encoded, we consider first two capabilities for a very simple application -- ping -- as mPlane JSON capabilities. The following capability states that the component can measure ICMP two-way delay from 192.0.2.19 to anywhere on the IPv4 Internet, with a minimum delay between individual pings of 1 second, returning aggregate statistics:

~~~~~~~~~~
{
  "capability": "measure",
  "version":    0,
  "registry":   "https://example.com/mplane/registry/core",
  "label":      "ping-aggregate",
  "when":       "now ... future / 1s",
  "parameters": {"source.ip4":      "192.0.2.19",
                 "destination.ip4": "*"},
  "results":    ["delay.twoway.icmp.us.min",
                 "delay.twoway.icmp.us.mean",
                 "delay.twoway.icmp.us.50pct",
                 "delay.twoway.icmp.us.max",
                 "delay.twoway.icmp.count"]
}
~~~~~~~~~~

In contrast, the following capability would return timestamped singleton delay measurements given the same parameters:

~~~~~~~~~~
{
  "capability": "measure",
  "version":    0,
  "registry":   "https://example.com/mplane/registry/core",
  "label":      "ping-singletons",
  "when":       "now ... future / 1s",
  "parameters": {"source.ip4":      "192.0.2.19",
                 "destination.ip4": "*"},
  "results":    ["time",
                 "delay.twoway.icmp.us"]
}
~~~~~~~~~~

A specification is merely a capability with filled-in parameters, e.g.:

~~~~~~~~~~
{
  "specification":  "measure",
  "version":        0,
  "registry":       "https://example.com/mplane/registry/core",
  "label":          "ping-aggregate-three-thirtythree",
  "token":          "0f31c9033f8fce0c9be41d4942c276e4",
  "when":           "now + 30s / 1s",
  "parameters": {"source.ip4":      "192.0.2.19",
                 "destination.ip4": "192.0.3.33"},
  "results":    ["delay.twoway.icmp.us.min",
                 "delay.twoway.icmp.us.mean",
                 "delay.twoway.icmp.us.50pct",
                 "delay.twoway.icmp.us.max",
                 "delay.twoway.icmp.count"]
}
~~~~~~~~~~

Results are merely specifications with result values filled in and an absolute temporal scope:

~~~~~~~~~~
{
  "result":   "measure",
  "version":  0,
  "registry": "https://example.com/mplane/registry/core",
  "label":    "ping-aggregate-three-thirtythree",
  "token":    "0f31c9033f8fce0c9be41d4942c276e4",
  "when":     2014-08-25 14:51:02.623 ... 2014-08-25 14:51:32.701 / 1s",
  "parameters": {"source.ip4":      "192.0.2.19",
                 "destination.ip4": "192.0.3.33"},
  "results":    ["delay.twoway.icmp.us.min",
                 "delay.twoway.icmp.us.mean",
                 "delay.twoway.icmp.us.50pct",
                 "delay.twoway.icmp.us.max",
                 "delay.twoway.icmp.count"],
  "resultvalues": [ [ 23901,
                      29833,
                      27619,
                      66002,
                      30] ]
}
~~~~~~~~~~

More complex measurements can be modeled by mapping them back to tables with multiple rows. For example, a traceroute capability would be defined as follows:

~~~~~~~~~~
{
  "capability": "measure",
  "version":    0,
  "registry":   "https://example.com/mplane/registry/core",
  "label":      "traceroute",
  "when":       "now ... future / 1s",
  "parameters": {"source.ip4":      "192.0.2.19",
                 "destination.ip4": "*",
                 "hops.ip.max": "0..32"},
  "results":    ["time",
                 "intermediate.ip4",
                 "hops.ip",
                 "delay.twoway.icmp.us"]
}
~~~~~~~~~~

with a corresponding specification:

~~~~~~~~~~
{
  "specification": "measure",
  "version":    0,
  "registry":   "https://example.com/mplane/registry/core",
  "label":      "traceroute-three-thirtythree",
  "token":      "2f4123588b276470b3641297ae85376a",
  "when":       "now",
  "parameters": {"source.ip4":      "192.0.2.19",
                 "destination.ip4": "192.0.3.33",
                 "hops.ip.max": 32},
  "results":    ["time",
                 "intermediate.ip4",
                 "hops.ip",
                 "delay.twoway.icmp.us"]
}
~~~~~~~~~~

and an example result:

~~~~~~~~~~
{
  "result": "measure",
  "version":    0,
  "registry":   "https://example.com/mplane/registry/core",
  "label":      "traceroute-three-thirtythree",
  "token":      "2f4123588b276470b3641297ae85376a,
  "when":       "2014-08-25 14:53:11.019 ... 2014-08-25 14:53:12.765",
  "parameters": {"source.ip4":      "192.0.2.19",
                 "destination.ip4": "192.0.3.33",
                 "hops.ip.max": 32},
  "results":    ["time",
                 "intermediate.ip4",
                 "hops.ip",
                 "delay.twoway.icmp.us"],
  "resultvalues": [ [ "2014-08-25 14:53:11.019", "192.0.2.1",
                      1, 162 ],
                    [ "2014-08-25 14:53:11.220", "217.147.223.101",
                      2, 15074 ],
                    [ "2014-08-25 14:53:11.570", "77.109.135.193",  
                      3, 30093 ],
                    [ "2014-08-25 14:53:12.091", "77.109.135.34",
                      4, 34979 ],
                    [ "2014-08-25 14:53:12.310", "192.0.3.1",
                      5, 36120 ],
                    [ "2014-08-25 14:53:12.765", "192.0.3.33",
                      6, 36202 ]
                  ]

}
~~~~~~~~~~

Indirect export to a repository with subsequent query requires three capabilities: one in which the repository advertises its ability to accept data over a given external protocol, one in which the probe advertises its ability to export data of the same type using that protocol, and one in which the repository advertises its ability to answer queries about the stored data. Returning to the aggregate ping measurement, first let's consider a repository which can accept these measurements via direct POST of mPlane result messages:

~~~~~~~~~~
{
  "capability": "collect",
  "version":    0,
  "registry":   "https://example.com/mplane/registry/core",
  "label":      "ping-aggregate-collect",
  "when":       "past ... future",
  "export":     "wss://repository.example.com:4343/",
  "parameters": {"source.ip4":      "*",
                 "destination.ip4": "*"},
  "results":    ["delay.twoway.icmp.us.min",
                 "delay.twoway.icmp.us.mean",
                 "delay.twoway.icmp.us.50pct",
                 "delay.twoway.icmp.us.max",
                 "delay.twoway.icmp.count"]
}
~~~~~~~~~~

This capability states that the repository at `wss://repository.example.com:4343/` will accept mPlane result messages matching the specified schema, without any limitations on time. Note that this schema matches that of the export capability provided by the probe:

~~~~~~~~~~
{
  "capability": "measure",
  "version":    0,
  "registry":   "https://example.com/mplane/registry/core",
  "label":      "ping-aggregate-export",
  "when":       "now ... future / 1s",
  "export":     "wss",
  "parameters": {"source.ip4":      "192.0.2.19",
                 "destination.ip4": "*"},
  "results":    ["delay.twoway.icmp.us.min",
                 "delay.twoway.icmp.us.mean",
                 "delay.twoway.icmp.us.50pct",
                 "delay.twoway.icmp.us.max",
                 "delay.twoway.icmp.count"]
}
~~~~~~~~~~

which differs only from the previous probe capability in that it states that results can be exported via the `wss` protocol. Subsequent queries can be sent to the repository in response to the query capability:

~~~~~~~~~~
{
  "capability": "query",
  "version":    0,
  "registry":   "https://example.com/mplane/registry/core",
  "label":      "ping-aggregate-query",
  "when":       "past ... future",
  "link":       "wss://res.example.com:4343/",
  "parameters": {"source.ip4":      "*",
                 "destination.ip4": "*"},
  "results":    ["delay.twoway.icmp.us.min",
                 "delay.twoway.icmp.us.mean",
                 "delay.twoway.icmp.us.50pct",
                 "delay.twoway.icmp.us.max",
                 "delay.twoway.icmp.count"]
}
~~~~~~~~~~

The examples in this section use the following registry:

~~~~~~~~~~
[TODO]
~~~~~~~~~~

## mPlane over WebSockets over TLS

The default session protocol for mPlane is WebSockets {{RFC6455}}. Once a
WebSockets handshake between client and component is complete, messages are
simply exchanged as outlined in {{message-types}} as JSON objects in
WebSockets text frames over the channel.

When WebSockets is used as a session protocol for mPlane, it MUST be used over
TLS for mPlane message exchanges. Both TLS clients and servers MUST present
certificates for TLS mutual authentication. mPlane components MUST use the
certificate presented by the mPlane client to determine the client's identity,
and therefore the capabilities which it is authorized to invoke. mPlane
clients MUST use the certificate presented by the mPlane component to
authenticate the results received. mPlane clients and components MUST NOT use
network-layer address or name (e.g. derived from DNS PTR queries) information
to identify peers.

mPlane components may either act as WebSockets servers, for client-initiated
connection establishment, or as WebSockets clients, for component-initiated
connection establishment. In either case, it is the responsibility of the
connection initiator to re-establish connection in case it is lost. In this
case, the entity acting as WebSockets server SHOULD maintain a queue of
pending mPlane messages to identified peers to be sent on reconnection.

### mPlane PKI for WebSockets

The clients and components within an mPlane domain generally share a single
certificate issuer, specific to a single mPlane domain. Issuing a certificate
to a client or component then grants it membership within the domain. Any
client or component within the domain can then communicate with components and
clients within that domain. In a domain containing one or more supervisors, all clients
and components within the domain can connect to a supervisor. This
deployment pattern can be used to scale mPlane domains to large numbers of
clients and components without needing to specifically configure each client
and component identity at the supervisor.

In the case of interdomain federation, where supervisors connect to each
other, each supervisor will have its own issuer. In this case, each supervisor
must be configured to trust each remote domain's issuer, but only to identify
that domain's supervisor. This compartmentalization is necessary to keep one
domain from authorizing clients within another domain.

### Capability Advertisement for WebSockets

When a connection is first established between a client and a component,
regardless of whether the client or the component initiates the connection,
the component sends an envelope containing all the capabilities it wishes to
advertise to the client, based on the client's identity.

### mPlane Link and Export URLs for WebSockets

Components acting as WebSockets servers (for client-initiated connection
establishment) are identified in the Link sections of capabilities and
receipts by URLs with the `wss:` schema. Similarly, clients acting as WebSockets
servers (for component-initated connection establishment) are identified in
the Link sections of specifications by URLs with the `wss:` schema.

When the `wss:` schema appears in the export section of the capability, this
represents the component's willingness to establish a WebSockets connection
over which mPlane result messages will be pushed. A `wss:` schema URL in a
specification export section, similarly, directs the component to the
WebSockets server to push results to.

Path information in WebSockets URLs is presently unused by the mPlane
protocol, but path information MUST be conserved. mPlane clients and
components acting as WebSockets servers can use path information as they see
fit, for example to separate client and component workflows on the same server
(as on a supervisor), to run mPlane and other protocols over WebSockets on the
same server, and/or to pass cryptographic tokens for additional context
separation or authorization purposes. Future versions of the mPlane protocol
may use path information in WebSockets URLs, but this path information will be
relative to this conserved "base" URL, as opposed to relative to the root.

# Deployment Considerations

This section outlines considerations for building larger-scale infrastructures
from the building blocks defined in this document.

## The Role of the Supervisor

For simple infrastructures, a set of components may be controlled directly by a client. However, in more complex infrastructures providing support for multiple clients, a supervisor can mediate between clients and components.  From the point of view of the mPlane protocol, a supervisor is merely a combined component and client. The logic binding client and component interfaces within the supervisor is application-specific, as it involves the following operations according to the semantics of each application:

- translating lower-level capabilities from subordinate components into higher-level (composed) capabilities, according to the application's semantics
- translating higher-level specifications from subordinate components into lower-level (decomposed) specifications
- relaying or aggregating results from subordinate components to supervisor clients

The workflows on each side of the supervisor are independent; indeed, the supervisor itself will generally respond to client-initiated exchanges, and use both component-initiated and supervisor-initiated exchanges with subordinate components.

Supervisors can of course be nested in this arrangement, e.g. allowing high-level measurements to be aggregated from a set of subdomains, or federation of measurement across administrative domain boundaries.

In the general case, the component first registers with the supervisor, POSTing its capabilities. The supervisor creates composed capabilities derived from these component capabilities, and makes them available to its client, which GETs them when it connects.

The client then initiates a measurement by POSTing a specification to the supervisor, which decomposes it into a more-specific specification to pass to the component, and hands the client a receipt for a the measurement. When the component polls the supervisor -- controlled, perhaps, by callback control as described above -- the supervisor passes this derived specification to the component, which executes it and POSTs its results back to the supervisor. When the client redeems its receipt, the supervisor returns results composed from those received from the component.

This simple example illustrates the three main responsibilities of the supervisor, which are described in more detail below.

### Component Registration

In order to be able to use components to perform measurements, the supervisor must register the components associated with it. For client-initiated workflows -- large repositories and the address of the components is often a configuration parameter of the supervisor. Capabilities describing the available measurements and queries at large-scale components can even be part of the supervisor's externally managed static configuration, or can be dynamically retrieved and updated from the components or from a capability discovery server.

For component-initiated workflows, components connect to the supervisor and POST capabilities and withdrawals, which requires the supervisor to maintain a set of capabilities associated with a set of components currently part of the mPlane infrastructure it supervises.

### Client Authentication

For many components -- probes and simple repositories -- very simple authentication often suffices, such that any client with a certificate with an issuer recognized as valid is acceptable, and all capabilities are available to. Larger repositories often need finer grained control, mapping specific peer certificates to identities internal to the repository's access control system (e.g. database users).

In an mPlane infrastructure, it is therefore the supervisor's responsibility to map client identities to the set of capabilities each client is authorized to access. This mapping is part of the supervisor's configuration.

### Capability Composition and Specification Decomposition

The most dominant responsibility of the supervisor is composing capabilities from its subordinate components into aggregate capabilities, and decomposing specifications from clients to more-specific specifications to pass to each component. This operation is always application-specific, as the semantics of the composition and decomposition operations depend on the capabilities available from the components, the granularity of the capabilities to be provided to the clients. It is for this reason that the mPlane SDK does not provide a generic supervisor.

## Indirect Export

Many common measurement infrastructures involve a large number of probes exporting large volumes of data to a (much) smaller number of repositories, where data is reduced and analyzed. Since (1) the mPlane protocol is not particularly well-suited to the bulk transfer of data and (2) fidelity is better ensured when minimizing translations between representations, the channel between the probes and the repositories is in this case external to mPlane. This indirect export channel runs either a standard export protocol such as IPFIX, or a proprietary protocol unique to the probe/repository pair. It coordinates an exporter which will produce and export data with a collector which will receive it. All that is necessary is that (1) the client, exporter, and collector agree on a schema to define the data to be transferred and (2) the exporter and collector share a common protocol for export.

Here, we consider a client speaking to an exporter and a collector. The client first receives an export capability from the exporter (with verb `measure` and with a protocol identified in the `export` section) and a collection capability from the collector (with the verb `collect` and with a URL in the `export` section describing where the exporter should export), either via a client-initiated workflow or a capability discovery server. The client then sends a specification to the exporter, which matches the schema and parameter constraints of both the export and collection capabilities, with the collector's URL in the `export` section.

The exporter initiates export to the collector using the specified protocol, and replies with a receipt that can be used to interrupt the export, should it have an indefinite temporal scope. In the meantime, it sends data matching the capability's schema directly to the collector.

This data, or data derived from the analysis thereof, can then be subsequently retrieved by a client using a client-initiated workflow to the collector.

## Error Handling in mPlane Workflows {#error-handling-in-mplane-workflows}

Any component may signal an error to its client or supervisor at any time by
sending an exception message. While the taxonomy of error messages is at this
time left up to each individual component, given the weakly imperative nature
of the mPlane protocol, exceptions should be used sparingly, and only to
notify components and clients of errors with the mPlane infrastructure itself.

It is generally presumed that diagnostic information about errors which may
require external human intervention to correct will be logged at each
component; the mPlane exception facility is not intended as a replacement
for logging facilities (such as syslog).

Specifically, components using component-initiated connection establishment
should not use the exception mechanism for common error conditions (e.g.,
device losing connectivity for small network-edge probes) -- specifications
sent to such components are expected to be best-effort. Exceptions should
also not be returned for specifications which would normally not be delayed
but are due to high load -- receipts should be used in this case, instead.
Likewise, specifications which cannot be fulfilled because they request the
use of capabilities that were once available but are no longer should be
answered with withdrawals.

Exceptions should always be sent in reply to messages sent to
components or clients which cannot be handled due to a syntactic or semantic
error in the message itself.

# Security Considerations

The mPlane protocol allows the control of network measurement devices. The
protocol itself uses WebSockets using TLS as a session layer. TLS mutual
authentication must be used for the exchange of mPlane messages, as access
control decisions about which clients and components are trusted for which
capabilities take identity information from the certificates TLS clients and
servers use to identify themselves. Current operational best security
practices for the deployment of TLS-secured protocols must be followed for the
deployment of mPlane.

Indirect export, as a design feature, presents a potential for information
leakage, as indirectly exported data is necessarily related to measurement
data and control transported with the mPlane protocol. Though out of scope for
this document, indirect export protocols used within an mPlane domain must be
secured at least as well as the mPlane protocol itself.

# IANA Considerations

This document has no actions for IANA. Future versions of this document, should it become a standards-track specification, may specify the initial contents of a core mPlane registry to be managed by IANA.

# Contributors

This document is based on Deliverable 1.4, the architecture and protocol
specification document produced by the mPlane project {{D14}}, which is the
work of the mPlane consortium, specifically Brian Trammell and Mirja
Kuehlewind (the editors of this document), as well as Marco Mellia, Alessandro
Finamore, Stefano Pentassuglia, Gianni De Rosa, Fabrizio Invernizzi, Marco
Milanesio, Dario Rossi, Saverio Niccolini, Ilias Leontiadis, Tivadar Szemethy,
Balas Szabo, Rolf Winter, Michael Faath, Benoit Donnet, and Dimitri
Papadimitriou.

# Acknowledgments

Thanks to Lingli Deng and Robert Kisteleki for feedback leading to the
improvement of this document and the protocol. 

This work is supported by the European Commission under grant agreement
FP7-318627 mPlane and H2020-688421 MAMI, and by the Swiss State Secretariat
for Education, Research, and Innovation under contract no. 15.0268. This
support does not imply endorsement of the contents of this document.
