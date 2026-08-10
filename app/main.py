# -*- coding: utf-8 -*-
"""Punto de entrada de la aplicación Notas.

Usa Gtk.Application, lo que aporta dos ventajas:
  - Instancia única: si ya hay una ventana abierta, lanzar `notas` otra vez
    (o pulsar el atajo global) simplemente la trae al frente.
  - Integración con el escritorio (nombre de aplicación, .desktop, etc.).

El directorio de notas se elige en este orden:
  1. Variable de entorno NOTAS_DIR.
  2. ~/Documentos/Notas.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, Gtk

from app.notes import Notes
from app.window import NotasWindow

APP_ID = "io.github.notas.app"
STYLE_CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")


class NotasApplication(Gtk.Application):
    """Aplicación GTK de una sola ventana."""

    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._window = None

    def do_startup(self):
        """Carga la hoja de estilos antes de crear ventanas."""
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_path(STYLE_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        """Crea (o recupera) la ventana principal."""
        if self._window is None:
            self._window = NotasWindow(self)
        self._window.present()
        self._window.editor.grab_focus()

    def do_command_line(self, _command_line):
        # Tratamos la invocación como una activación simple.
        self.activate()
        return 0


def main():
    app = NotasApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
