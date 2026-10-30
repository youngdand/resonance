# Security

Resonance and the engine HTTP interface are intended to bind only to loopback. The engine's peer protocol port is separate. Never expose the UI, private configuration, database or backups through public hosting.

Report a vulnerability privately through GitHub's private vulnerability reporting if enabled, or contact a maintainer without including live secrets. Public issues must not contain API keys, passwords, databases, private YAML, messages or unreviewed diagnostic archives. Rotate a credential if it has been disclosed to an unintended audience.

The release builder uses an explicit allowlist, rejects runtime data and checks for secret-shaped content. This is a release safeguard, not a guarantee that arbitrary contributed material is safe. Review diffs and dependencies. OS user permissions protect locally stored configuration; the application is not an encrypted vault.
