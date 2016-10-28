# mPlane Protocol Software Development Kit (MAMI Edition)

This module contains the mPlane Software Development Kit. 

This fork of the mPlane SDK is intended as a basis for mPlane applications in
the H2020 MAMI project. It is current to the release candidate for version
1.0, including bugfixes made by ETH and during the mPlane project
demonstration preparation process, also including multiple value support and
JSON configuration file support.

The mPlane Protocol provides control and data interchange for passive and
active network measurement tasks. It is built around a simple workflow in
which __Capabilities__ are published by __Components__, which can accept
__Specifications__ for measurements based on these Capabilities, and provide
__Results__, either inline or via an indirect export mechanism negotiated
using the protocol.

Measurement statements are fundamentally based on schemas divided into
Parameters, representing information required to run a measurement or query;
and Result Columns, the information produced by the measurement or query.
Measurement interoperability is provided at the element level; that is,
measurements containing the same Parameters and Result Columns are considered
to be of the same type and therefore comparable.

## Learning More

See [doc/HOWTO.md](doc/HOWTO.md) for information on getting started with the mPlane SDK for demonstration purposes.

See [doc/conf.md](doc/conf.md) for an introduction to the mPlane SDK configuration file format.

See [doc/client-shell.md](doc/client-shell.md) for an introduction to `mpcli` debug client shell.

See [doc/component-dev.md](doc/component-dev.md) for an introduction to developing components with the mPlane SDK and running them with the `mpcom` runtime.

See [doc/protocol-spec.md](doc/protocol-spec.md) for the mPlane protocol specification.

## Contents

See [https://mplane-sdk.readthedocs.org](https://mplane-sdk.readthedocs.org) for Sphinx documentation of the SDK modules. The SDK is made up of several modules:

- `mplane.model`: Information model and JSON representation of mPlane messages.
- `mplane.tls`: Handles TLS, mapping local and peer certificates to identities and providing TLS connectivity over HTTPS.
- `mplane.azn`: Handles access control, mapping identities to roles and authorizing roles to use specific services.
- `mplane.client`: mPlane client framework. Handles client-initiated (`WSClientClient`) and component-initiated (`WSServerClient`) workflows.
- `mplane.component: mPlane component framework. Handles client-initiated (`WSServerComponent`) and component-initiated (`WSClientComponent`) workflows. Defines the Service interface for implementing services to run on components.

There are two scripts installed with the package, as well:

- `mpcli`: Simple client with command-line shell for debugging.
- `mpcom`: mPlane component runtime. Handles client-initiated and component-initiated workflows.
