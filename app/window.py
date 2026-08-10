# -*- coding: utf-8 -*-
"""Ventana principal de la aplicación.

Distribución:
  - Barra de herramientas: crear, renombrar y borrar nota.
  - Panel izquierdo: lista de notas (una por archivo .md).
  - Panel derecho: editor estilo Vim (VimEditor + VimEngine).
  - Barra de estado inferior: modo actual, comandos pendientes y mensajes.

La ventana implementa la interfaz que el motor Vim utiliza para pedir
acciones de la aplicación (guardar, salir, crear/borrar/renombrar nota),
así como el guardado automático al cambiar de nota o cerrar la ventana.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from app.notes import Notes
from app.vim_engine import VimEngine
from app.vim_editor import VimEditor


class NotasWindow(Gtk.ApplicationWindow):
    def __init__(self, app, notes=None):
        super().__init__(application=app)
        self.app = app
        self.notes = notes or Notes()

        self.set_title("Notas")
        self.set_default_size(900, 600)
        self.add_css_class("app-window")

        # Motor Vim + editor. El `ui` se engancha al final del constructor,
        # cuando la barra de estado ya existe (el motor avisa al crearse).
        self.engine = VimEngine()
        self.editor = VimEditor(self.engine)

        self.current = None

        self._build_ui()
        self.engine.ui = self
        self._reload_list(select_first=True)

        # Si no existía ninguna nota, creamos una para poder escribir ya.
        if self.current is None:
            self.load_note(self.notes.create())

        # Auto-guardado al cerrar la ventana.
        self.connect("close-request", self._on_close_request)

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz                                        #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(root)

        root.append(self._build_toolbar())

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.append(body)

        # Lista de notas a la izquierda (Gtk.ListBox: filas seleccionables).
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.connect("row-selected", self._on_row_selected)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self._list)
        scroller.set_size_request(220, -1)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body.append(scroller)

        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        body.append(separator)

        # Editor a la derecha.
        editor_scroller = Gtk.ScrolledWindow()
        editor_scroller.set_child(self.editor)
        editor_scroller.set_hexpand(True)
        editor_scroller.set_vexpand(True)
        body.append(editor_scroller)

        # Barra de estado inferior.
        self._status = Gtk.Label(label="")
        self._status.set_halign(Gtk.Align.START)
        self._status.set_margin_start(8)
        self._status.set_margin_end(8)
        self._status.set_margin_top(4)
        self._status.set_margin_bottom(4)
        self._status.add_css_class("statusbar")
        root.append(self._status)

    def _build_toolbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)
        bar.set_margin_start(6)
        bar.set_margin_end(6)

        new_btn = Gtk.Button(icon_name="document-new-symbolic")
        new_btn.set_tooltip_text("Nueva nota (:new)")
        new_btn.connect("clicked", lambda _b: self.new_note())
        bar.append(new_btn)

        rename_btn = Gtk.Button(icon_name="document-edit-symbolic")
        rename_btn.set_tooltip_text("Renombrar nota (:rename)")
        rename_btn.connect("clicked", lambda _b: self.rename_note())
        bar.append(rename_btn)

        delete_btn = Gtk.Button(icon_name="edit-delete-symbolic")
        delete_btn.set_tooltip_text("Borrar nota (:delete)")
        delete_btn.connect("clicked", lambda _b: self.delete_note())
        bar.append(delete_btn)

        return bar

    # ------------------------------------------------------------------ #
    # Lista de notas                                                      #
    # ------------------------------------------------------------------ #

    def _add_row(self, stem):
        """Añade una fila con el nombre de la nota a la lista."""
        row = Gtk.ListBoxRow()
        row.stem = stem
        label = Gtk.Label(label=stem)
        label.set_xalign(0.0)
        label.set_margin_start(10)
        label.set_margin_top(7)
        label.set_margin_bottom(7)
        label.set_margin_end(10)
        row.set_child(label)
        self._list.append(row)
        return row

    def _reload_list(self, select_first=False):
        """Recarga la lista de notas desde disco."""
        child = self._list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt

        stems = self.notes.list()
        for stem in stems:
            self._add_row(stem)

        if select_first and stems and self.current not in stems:
            self.load_note(stems[0])

    def _select_row(self, stem):
        """Marca la fila correspondiente en la lista."""
        child = self._list.get_first_child()
        while child is not None:
            if getattr(child, "stem", None) == stem:
                self._list.select_row(child)
                return
            child = child.get_next_sibling()

    def _on_row_selected(self, _list, row):
        if row is not None and getattr(row, "stem", None) != self.current:
            self.load_note(row.stem)

    # ------------------------------------------------------------------ #
    # Carga / guardado                                                   #
    # ------------------------------------------------------------------ #

    def load_note(self, stem):
        """Cambia a la nota `stem` guardando antes la actual."""
        self.save_current()
        self.current = stem
        self.engine.set_text(self.notes.read(stem))
        self.set_title(f"Notas — {stem}")
        self._select_row(stem)

    def save_current(self):
        """Guarda la nota activa en disco (si hay alguna)."""
        if self.current is not None:
            self.notes.write(self.current, self.engine.text)

    # ------------------------------------------------------------------ #
    # Interfaz usada por el motor Vim (engine.ui)                        #
    # ------------------------------------------------------------------ #

    def set_status(self, text):
        self._status.set_text(text)

    def save_note(self):
        self.save_current()

    def quit_app(self, save=True):
        if not save:
            # :q! descarta los cambios: recargamos desde disco y cerramos.
            if self.current is not None:
                self.engine.set_text(self.notes.read(self.current))
        self.save_current()
        self.close()

    def new_note(self):
        self._prompt("Nombre de la nota", self._on_new_note, "")

    def _on_new_note(self, name):
        if name is None:
            return
        stem = self.notes.create(name or None)
        self._reload_list()
        self.load_note(stem)
        self._select_row(stem)

    def rename_note(self):
        if self.current is None:
            return
        self._prompt("Nuevo nombre", self._on_rename_note, self.current)

    def _on_rename_note(self, new):
        if new is None:
            return
        renamed = self.notes.rename(self.current, new)
        if renamed:
            self.current = renamed
            self.set_title(f"Notas — {renamed}")
            self._reload_list()
            self._select_row(renamed)

    def delete_note(self):
        if self.current is None:
            return
        self._confirm(f"¿Borrar «{self.current}»?", self._on_delete_note)

    def _on_delete_note(self, ok):
        if not ok:
            return
        self.notes.delete(self.current)
        self.current = None
        self._reload_list(select_first=True)
        if not self.notes.list():
            self.engine.set_text("")
            self.set_title("Notas")

    # ------------------------------------------------------------------ #
    # Diálogos auxiliares                                                #
    # ------------------------------------------------------------------ #

    def _prompt(self, title, on_result, default=""):
        """Diálogo de entrada de texto (no bloqueante).

        Llama `on_result(texto)` al aceptar o `on_result(None)` al cancelar.
        En GTK4 `Gtk.Dialog.run()` no existe; se usa la señal `response`."""
        dialog = Gtk.Dialog(title=title, transient_for=self)
        dialog.set_modal(True)
        btn_cancel = dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        btn_ok = dialog.add_button("Aceptar", Gtk.ResponseType.OK)

        # Separación y aire alrededor de los botones de acción.
        btn_cancel.set_margin_end(8)
        btn_cancel.set_margin_top(12)
        btn_cancel.set_margin_bottom(12)
        btn_ok.set_margin_top(12)
        btn_ok.set_margin_bottom(12)
        btn_ok.set_margin_end(12)

        entry = Gtk.Entry()
        entry.set_text(default)
        entry.set_activates_default(True)
        entry.set_margin_start(12)
        entry.set_margin_end(12)
        entry.set_margin_top(12)
        dialog.get_content_area().append(entry)
        dialog.set_default_response(Gtk.ResponseType.OK)

        def on_response(_dlg, response):
            text = entry.get_text() if response == Gtk.ResponseType.OK else None
            dialog.destroy()
            on_result(text)

        dialog.connect("response", on_response)
        dialog.present()
        entry.grab_focus()

    def _confirm(self, message, on_result):
        """Diálogo Sí/No (no bloqueante). Llama `on_result(bool)`."""
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION)
        dialog.set_markup(message)
        btn_no = dialog.add_button("No", Gtk.ResponseType.NO)
        btn_yes = dialog.add_button("Sí", Gtk.ResponseType.YES)

        def on_response(_dlg, response):
            dialog.destroy()
            on_result(response == Gtk.ResponseType.YES)

        dialog.connect("response", on_response)
        dialog.present()

    # ------------------------------------------------------------------ #
    # Cierre                                                             #
    # ------------------------------------------------------------------ #

    def _on_close_request(self, _window):
        self.save_current()
        return False
