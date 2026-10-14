# Roadmap

Where FleetPilot is heading from October 2026 to October 2027. This is a statement of intent, not a promise: plans change with what users report and what contributors bring. Proposals are welcome in [Discussions](https://github.com/ChristianHandy/FleetPilot/discussions). The maintainer reviews this roadmap at least once a year and with every minor release.

## Planned

### Security and quality

- **OpenSSF Best Practices silver**, then as much of gold as a project with one maintainer can meet ([status](https://www.bestpractices.dev/projects/15465)).
- **Test coverage:** at least 80% of statements, then 90% of statements and 80% of branches, measured in CI.
- **Secure network defaults:** TLS certificate verification on by default for every device connection, HTTPS instead of HTTP where a device supports it, and plain-text protocols only when you turn them on for a device.
- **A stricter Content Security Policy:** move inline scripts into files so the CSP no longer needs `'unsafe-inline'`.
- **Sign-in throttling that survives restarts** and is shared between workers.
- **Every release** signed, with build provenance, an SBOM and checksums.

### Features

- Deeper support for the devices FleetPilot already manages (Proxmox, TrueNAS, Unraid, backup servers, routers) rather than many new platforms.
- The vulnerability scan for more systems and package formats.
- Keeping the [live demo](https://christianhandy.github.io/FleetPilot/demo/) in step with every release, so you can try each version before installing it.

### Project

- Find a second maintainer, so that changes get a second review and the project does not depend on one person (see [GOVERNANCE.md](GOVERNANCE.md)).
- Small tasks for new contributors, labelled [good first issue](https://github.com/ChristianHandy/FleetPilot/labels/good%20first%20issue).

## Not planned

- **An agent on managed machines.** FleetPilot stays agentless: SSH and the devices' own APIs.
- **A hosted (cloud or SaaS) version, or telemetry.** FleetPilot runs on your own hardware and only talks to the internet for the features you turn on.
- **Multi-tenant or service-provider features** such as separate customers in one installation.
- **Running the FleetPilot server on Windows or macOS.** It runs on Linux; Windows machines can still be managed.

## Past releases

What each release changed is in [CHANGELOG.md](CHANGELOG.md).
