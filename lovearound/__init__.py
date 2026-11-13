"""Love Around for Linux."""
import gi

from .deps import TYPELIBS

# Set before any module imports from gi.repository.
for namespace, version in TYPELIBS:
    gi.require_version(namespace, version)
