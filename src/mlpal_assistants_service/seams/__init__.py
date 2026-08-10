"""Open-core seams: interfaces + self-contained OSS default implementations.

Each module here defines a small interface the app depends on plus its OSS
default (self-hosted, no MLPal-platform callout) and a composition-root factory
that binds the OSS default or the managed implementation based on config.

Dependency rule: this package imports only interfaces + domain types; the
MANAGED implementations live in their existing homes (repositories/, core/auth,
etc.) and are lazy-imported by the factory only when the managed backend is
selected — so an OSS build never imports platform-coupled code. At publish time
this package (interfaces + OSS defaults) ships; the managed impls do not.
"""
