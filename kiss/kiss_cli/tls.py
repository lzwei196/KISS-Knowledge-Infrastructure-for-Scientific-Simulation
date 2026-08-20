"""TLS contexts that follow the operating system's trust decisions.

The frozen macOS app carries OpenSSL but not the ``cert.pem`` symlink created
by python.org's ``Install Certificates.command``.  Plain ``urllib`` therefore
rejects endpoints that Safari and ``curl`` trust.  More importantly, a static
CA bundle would still miss certificates installed by an institution or IT
administrator in the macOS Keychain.

``truststore`` exposes the native Keychain/CryptoAPI/OpenSSL stores through the
``ssl.SSLContext`` interface.  We use a request-scoped context rather than
injecting it globally so importing KISS cannot change TLS behaviour for code
that embeds the package.
"""

from __future__ import annotations

import ssl


def context() -> ssl.SSLContext:
    """Return a verified client context, preferring the native trust store."""
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except (ImportError, OSError):
        # Source installs on platforms where truststore is unavailable still
        # get Python's normal verified context.  certifi is a final fallback
        # for frozen/community Python builds that shipped no default CA file.
        ctx = ssl.create_default_context()
        try:
            import certifi

            ctx.load_verify_locations(cafile=certifi.where())
        except (ImportError, OSError, ssl.SSLError):
            pass
        return ctx
