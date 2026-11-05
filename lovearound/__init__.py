"""Love Around for Linux."""
import gi

# GTK 3, for gtk-layer-shell as Ubuntu 24.04 ships it; set before any module imports Gtk.
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Soup", "3.0")
