"""Love Around for Linux."""
import gi

from .deps import TYPELIBS

# GTK 3, for gtk-layer-shell as Ubuntu 24.04 ships it; set before any module imports Gtk.
for namespace, version in TYPELIBS:
    gi.require_version(namespace, version)
