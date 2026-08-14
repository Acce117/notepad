# -*- coding: utf-8 -*-
"""Vista GTK del editor: un Gtk.TextView que pinta el estado del motor Vim.

El motor (VimEngine) es la única fuente de verdad del contenido. Esta clase
solo lo *renderiza*:
  - Reemplaza el texto del buffer cuando cambia.
  - Coloca el cursor y la selección visual.
  - Aplica el resaltado de búsqueda.
  - Desplaza la vista al cursor.
  - Captura las teclas (fase CAPTURE) y las entrega al motor, devolviendo
    True para que GTK no inserte texto por su cuenta.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from app.vim_engine import VimEngine, CTRL, SHIFT, ALT, SUPER


class VimEditor(Gtk.TextView):
    """Editor estilo Vim sobre un Gtk.TextView."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        # La vista solo *renderiza* el estado del motor; el texto lo edita
        # siempre el motor. Evitamos que GTK/el IM escriban en el buffer a
        # espaldas del motor (rompería el texto compuesto con teclas muertas).
        self.set_editable(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_monospace(True)
        self.set_name("vim-editor")

        # Etiqueta para el resaltado de búsqueda.
        self._search_tag = self.get_buffer().create_tag(
            "search", background="yellow", foreground="black")

        # El motor llama a `refresh()` tras cada cambio de estado.
        self.engine.renderer = self.refresh

        # Capturamos todas las teclas ANTES de que GTK inserte texto.
        controller = Gtk.EventControllerKey.new()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self._on_key_pressed)

        # Método de entrada (IM): se consulta ANTES de emitir `key-pressed`,
        # así las teclas muertas (´, ~, ¨, ^, ...) y Compose se componen aquí
        # y llegan al motor ya formadas a través de la señal `commit`
        # (p. ej. ´ + a -> commit "á"). El motor nunca ve la tecla muerta
        # suelta ni el carácter sin componer.
        self._im_context = Gtk.IMContextSimple.new()
        self._im_context.set_client_widget(self)
        self._im_context.connect("commit", self._on_im_commit)
        controller.set_im_context(self._im_context)

        self.add_controller(controller)

        # Clic del ratón: coloca el cursor en modo normal.
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

    # ------------------------------------------------------------------ #
    # Teclado                                                            #
    # ------------------------------------------------------------------ #

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        name = Gdk.keyval_name(keyval)
        unicode_val = Gdk.keyval_to_unicode(keyval)
        char = chr(unicode_val) if unicode_val else ""

        mods = set()
        if state & Gdk.ModifierType.CONTROL_MASK:
            mods.add(CTRL)
        if state & Gdk.ModifierType.SHIFT_MASK:
            mods.add(SHIFT)
        if state & Gdk.ModifierType.ALT_MASK:
            mods.add(ALT)
        if state & Gdk.ModifierType.SUPER_MASK:
            mods.add(SUPER)

        self.engine.handle_key(name, char, frozenset(mods))
        # True = reclamamos el evento: GTK no aplica su comportamiento por
        # defecto (no inserta el carácter en el buffer).
        return True

    def _on_im_commit(self, _im_context, text):
        """Texto compuesto por el método de entrada (p. ej. "á" tras ´+a).

        Se entrega al motor como texto ya compuesto. En los modos insertar,
        reemplazar y en los prompts (/, :) se inserta o añade correctamente;
        en modo normal se ignora (sin efecto)."""
        if not text:
            return
        self.engine.handle_key("", text, frozenset())

    # ------------------------------------------------------------------ #
    # Ratón                                                              #
    # ------------------------------------------------------------------ #

    def _on_click(self, _controller, _n_press, x, y):
        try:
            it, _trailing = self.get_iter_at_position(x, y)
        except Exception:
            return
        row, col = it.get_line(), it.get_line_offset()
        self.engine.cursor = (row, col)
        self.engine.mode = "normal"
        self.grab_focus()
        self.refresh()

    # ------------------------------------------------------------------ #
    # Renderizado del estado del motor                                   #
    # ------------------------------------------------------------------ #

    def refresh(self):
        """Sincroniza el TextView con el estado actual del motor."""
        buf = self.get_buffer()

        # Texto.
        text = self.engine.text
        current = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        if current != text:
            buf.set_text(text, -1)

        # Cursor.
        row, col = self.engine.cursor
        _ok, cursor_it = buf.get_iter_at_line_offset(row, col)
        buf.place_cursor(cursor_it)

        # Selección visual.
        sel = self.engine.selection()
        if sel:
            kind, r1, _r2, o1, o2 = sel
            if kind == "block":
                # No es un rectángulo real: marcamos el área que lo contiene.
                anchor = self.engine._vis_anchor
                end = self.engine.cursor
                _o1, a = buf.get_iter_at_line_offset(*min(anchor, end))
                _o2, b = buf.get_iter_at_line_offset(*max(anchor, end))
                b.forward_char()
                buf.select_range(a, b)
            else:
                start = buf.get_iter_at_offset(o1)
                end = buf.get_iter_at_offset(o2)
                buf.select_range(start, end)
        else:
            buf.select_range(cursor_it, cursor_it)

        # Resaltado de búsqueda.
        buf.remove_tag(self._search_tag, buf.get_start_iter(), buf.get_end_iter())
        for start_off, end_off in self.engine.search_matches:
            s = buf.get_iter_at_offset(start_off)
            e = buf.get_iter_at_offset(end_off)
            buf.apply_tag(self._search_tag, s, e)

        self._scroll_to_cursor()

    def _scroll_to_cursor(self):
        """Mantiene el cursor visible (con un pequeño margen)."""
        buf = self.get_buffer()
        mark = buf.get_insert()
        self.scroll_to_mark(mark, 0.05, False, 0.0, 0.0)
