# -*- coding: utf-8 -*-
"""Pruebas unitarias del motor Vim (sin GTK, se ejecutan con `python3 -m unittest`)."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.vim_engine import VimEngine


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = VimEngine()
        self.engine.renderer = lambda: None  # sin vista en tests

    # Utilidades --------------------------------------------------------

    def key(self, char):
        """Simula una tecla en modo normal/visual."""
        self.engine.handle_key(char, char)

    def type_text(self, text):
        """Escribe texto en modo insertar."""
        for ch in text:
            if ch == "\n":
                self.engine.handle_key("Return", "")
            else:
                self.engine.handle_key(ch, ch)

    def set_text(self, text):
        self.engine.set_text(text)

    @property
    def lines(self):
        return self.engine.lines

    @property
    def cursor(self):
        return self.engine.cursor

    # Movimientos -------------------------------------------------------

    def test_cursor_initial(self):
        self.set_text("hola")
        self.assertEqual(self.cursor, (0, 0))

    def test_hjkl(self):
        self.set_text("ab\ncd")
        self.key("l")
        self.assertEqual(self.cursor, (0, 1))
        self.key("j")
        self.assertEqual(self.cursor, (1, 1))
        self.key("h")
        self.assertEqual(self.cursor, (1, 0))
        self.key("k")
        self.assertEqual(self.cursor, (0, 0))

    def test_w_e_b(self):
        self.set_text("hola mundo adios")
        self.key("w")
        self.assertEqual(self.cursor, (0, 5))
        self.key("w")
        self.assertEqual(self.cursor, (0, 11))
        self.key("e")
        self.assertEqual(self.cursor, (0, 15))
        self.key("b")
        self.assertEqual(self.cursor, (0, 11))
        self.key("b")
        self.assertEqual(self.cursor, (0, 5))

    def test_ge(self):
        self.set_text("hola mundo")
        self.key("$")
        self.key("ge")
        # Verificado en Vim real: desde el EOL, ge va al final de la palabra
        # estrictamente anterior a la ocupada por el cursor -> "hola".
        self.assertEqual(self.cursor, (0, 3))

    def test_gg_G(self):
        self.set_text("a\nb\nc")
        self.key("G")
        self.assertEqual(self.cursor, (2, 0))
        self.key("gg")
        self.assertEqual(self.cursor, (0, 0))

    def test_dollar(self):
        self.set_text("hola")
        self.key("$")
        self.assertEqual(self.cursor, (0, 4))

    def test_zero_vs_count(self):
        self.set_text("a\nb\nc")
        self.key("j")
        self.key("j")
        self.key("0")
        self.assertEqual(self.cursor, (2, 0))
        self.key("1")
        self.key("0")
        self.key("G")
        self.assertEqual(self.cursor, (2, 0))  # 10G se ajusta a la última línea

    def test_count_motion(self):
        self.set_text("uno dos tres cuatro")
        self.key("2")
        self.key("w")
        self.assertEqual(self.cursor, (0, 8))  # "tres"

    def test_three_w(self):
        self.set_text("uno dos tres cuatro")
        self.key("3")
        self.key("w")
        self.assertEqual(self.cursor, (0, 13))  # "cuatro"

    def test_percent(self):
        self.set_text("a(b(c)d)e")
        self.engine.cursor = (0, 1)
        self.key("%")
        self.assertEqual(self.cursor, (0, 7))  # cierra el paréntesis exterior
        self.key("%")
        self.assertEqual(self.cursor, (0, 1))

    # Edición -----------------------------------------------------------

    def test_insert_text(self):
        self.set_text("")
        self.key("i")
        self.type_text("hola")
        self.key("Escape")
        self.assertEqual("".join(self.lines), "hola")
        self.assertEqual(self.cursor, (0, 4))

    def test_a_append(self):
        self.set_text("hola")
        self.key("a")
        self.type_text(" mundo")
        self.key("Escape")
        self.assertEqual("".join(self.lines), "h mundoola")

    def test_A_append_end(self):
        self.set_text("hola")
        self.key("A")
        self.type_text(" mundo")
        self.key("Escape")
        self.assertEqual("".join(self.lines), "hola mundo")

    def test_o_O(self):
        self.set_text("hola")
        self.key("o")
        self.type_text("mundo")
        self.key("Escape")
        self.assertEqual(self.lines, ["hola", "mundo"])
        self.key("O")
        self.type_text("primero")
        self.key("Escape")
        self.assertEqual(self.lines, ["hola", "primero", "mundo"])

    def test_x(self):
        self.set_text("hola")
        self.key("x")
        self.assertEqual("".join(self.lines), "ola")

    def test_dd(self):
        self.set_text("a\nb\nc")
        self.key("j")
        self.key("d")
        self.key("d")
        self.assertEqual(self.lines, ["a", "c"])
        self.assertEqual(self.cursor, (1, 0))

    def test_dd_count(self):
        self.set_text("a\nb\nc\nd")
        self.key("2")
        self.key("d")
        self.key("d")
        self.assertEqual(self.lines, ["c", "d"])

    def test_dw(self):
        self.set_text("hola mundo")
        self.key("d")
        self.key("w")
        self.assertEqual("".join(self.lines), "mundo")

    def test_de(self):
        self.set_text("hola mundo")
        self.key("d")
        self.key("e")
        self.assertEqual("".join(self.lines), " mundo")

    def test_ddollar(self):
        self.set_text("hola mundo")
        self.key("w")
        self.key("D")
        self.assertEqual(self.lines, ["hola "])

    def test_cw(self):
        self.set_text("hola mundo")
        self.key("c")
        self.key("w")
        self.type_text("adios")
        self.key("Escape")
        # Verificado en Vim real: cw borra la palabra y el espacio posterior.
        self.assertEqual("".join(self.lines), "adiosmundo")

    def test_yy_p(self):
        self.set_text("a\nb\nc")
        self.key("y")
        self.key("y")
        self.key("j")
        self.key("p")
        self.assertEqual(self.lines, ["a", "b", "a", "c"])

    def test_P(self):
        self.set_text("a\nb\nc")
        self.key("y")
        self.key("y")
        self.key("j")
        self.key("P")
        self.assertEqual(self.lines, ["a", "a", "b", "c"])

    def test_x_then_p(self):
        self.set_text("hola")
        self.key("x")  # borra 'h', registro="h"
        self.key("$")
        self.key("p")
        self.assertEqual("".join(self.lines), "olah")

    def test_undo_redo(self):
        self.set_text("hola")
        self.key("x")  # -> ola
        self.engine.handle_key("r", "", {"ctrl"})  # Ctrl-r? no, usamos 'u'
        self.key("u")
        self.assertEqual("".join(self.lines), "hola")
        self.key("u")
        self.assertEqual("".join(self.lines), "hola")  # no hay más que deshacer

    def test_undo_insert(self):
        self.set_text("hola")
        self.key("i")
        self.type_text("XXX")
        self.key("Escape")
        self.assertEqual("".join(self.lines), "XXXhola")
        self.key("u")
        self.assertEqual("".join(self.lines), "hola")

    def test_redo(self):
        self.set_text("hola")
        self.key("i")
        self.type_text("X")
        self.key("Escape")
        self.key("u")
        self.engine.handle_key("r", "", {"ctrl"})
        self.assertEqual("".join(self.lines), "Xhola")

    def test_replace(self):
        self.set_text("hola")
        self.key("r")
        self.engine.handle_key("x", "x")
        self.assertEqual("".join(self.lines), "xola")

    def test_join(self):
        self.set_text("hola\nmundo")
        self.key("J")
        self.assertEqual(self.lines, ["hola mundo"])

    def test_tilde(self):
        self.set_text("hola")
        self.key("~")
        self.assertEqual("".join(self.lines), "Hola")

    # Búsqueda ----------------------------------------------------------

    def test_search_forward(self):
        self.set_text("hola\nmundo\nhola")
        self.engine.handle_key("/", "/")
        self.type_text("mundo")
        self.engine.handle_key("Return", "")
        self.assertEqual(self.cursor, (1, 0))

    def test_search_n(self):
        self.set_text("hola\nmundo\nhola")
        self.engine.handle_key("/", "/")
        self.type_text("hola")
        self.engine.handle_key("Return", "")
        # La búsqueda parte tras el cursor (0,0), por lo que va a la 2ª coincidencia.
        self.assertEqual(self.cursor, (2, 0))
        self.key("n")
        self.assertEqual(self.cursor, (0, 0))

    # Visual ------------------------------------------------------------

    def test_visual_line_delete(self):
        self.set_text("a\nb\nc")
        self.key("j")
        self.key("V")
        self.key("j")
        self.key("d")
        self.assertEqual(self.lines, ["a"])

    def test_visual_char_yank(self):
        self.set_text("hola mundo")
        self.key("l")
        self.key("v")
        self.key("l")
        self.key("l")
        self.key("y")
        self.assertEqual(self.engine.reg["text"], "ola")
        self.assertEqual(self.engine.mode, "normal")

    def test_visual_block(self):
        self.set_text("abc\nabc\nabc")
        self.engine.cursor = (0, 1)
        self.key("v")
        # cambiar a bloque con Ctrl-v
        self.engine.mode = "normal"
        self.engine.handle_key("v", "", {"ctrl"})
        self.engine.cursor = (2, 2)
        self.key("d")
        self.assertEqual(self.lines, ["ac", "ac", "ac"])

    # Línea de comando --------------------------------------------------

    def test_command_new(self):
        calls = []
        class UI:
            def new_note(self):
                calls.append("new")
        self.engine.ui = UI()
        self.engine.handle_key(":", ":")
        self.type_text("new")
        self.engine.handle_key("Return", "")
        self.assertEqual(calls, ["new"])
        self.assertEqual(self.engine.mode, "normal")

    def test_command_save(self):
        calls = []
        class UI:
            def save_note(self):
                calls.append("save")
        self.engine.ui = UI()
        self.engine.handle_key(":", ":")
        self.type_text("w")
        self.engine.handle_key("Return", "")
        self.assertEqual(calls, ["save"])

    def test_backspace_in_command(self):
        self.engine.handle_key(":", ":")
        self.type_text("wd")
        self.engine.handle_key("BackSpace", "")
        self.assertEqual(self.engine._prompt_text, "w")
        self.engine.handle_key("Escape", "")


    def test_find_char(self):
        self.set_text("hola mundo")
        self.key("f")
        self.engine.handle_key("m", "m")  # 'm' está en el índice 5
        self.assertEqual(self.cursor, (0, 5))
        self.key(";")
        # No hay otra 'm' en la línea: no se mueve.
        self.assertEqual(self.cursor, (0, 5))

    def test_find_t(self):
        self.set_text("hola mundo")
        self.key("f")
        self.engine.handle_key("n", "n")  # 'n' está en el índice 7
        self.assertEqual(self.cursor, (0, 7))
        self.key("t")
        self.engine.handle_key("n", "n")  # t n -> justo antes de la 'n' (col 6)
        self.assertEqual(self.cursor, (0, 6))

    def test_dw_end_of_line(self):
        self.set_text("hola")
        self.key("d")
        self.key("w")
        self.assertEqual(self.lines, [""])

    def test_replace_mode(self):
        self.set_text("hola")
        self.key("R")
        self.type_text("xyz")
        self.key("Escape")
        self.assertEqual("".join(self.lines), "xyza")

    def test_block_insert(self):
        self.set_text("ab\nab\nab")
        self.engine.cursor = (0, 1)
        self.engine.handle_key("v", "", {"ctrl"})  # visual bloque
        self.engine.cursor = (2, 1)
        self.key("I")
        self.type_text("X")
        self.key("Escape")
        self.assertEqual(self.lines, ["aXb", "aXb", "aXb"])

    def test_search_backward(self):
        self.set_text("hola\nmundo\nhola")
        self.engine.handle_key("?", "?")
        self.type_text("hola")
        self.engine.handle_key("Return", "")
        # Búsqueda hacia atrás desde (0,0): encuentra la última coincidencia.
        self.assertEqual(self.cursor, (2, 0))

    def test_cursor_arrows_insert(self):
        self.set_text("hola")
        self.key("i")
        self.engine.handle_key("Right", "")
        self.type_text("!")
        self.key("Escape")
        self.assertEqual("".join(self.lines), "h!ola")

    def test_undo_visual_delete(self):
        self.set_text("a\nb\nc")
        self.key("V")
        self.key("d")
        self.assertEqual(self.lines, ["b", "c"])
        self.key("u")
        self.assertEqual(self.lines, ["a", "b", "c"])

    # Enter en modo insertar ---------------------------------------------

    def test_insert_enter_at_end(self):
        self.set_text("hola")
        self.key("A")  # cursor al final de línea + modo insertar
        self.engine.handle_key("Return", "")
        self.assertEqual(self.lines, ["hola", ""])
        self.assertEqual(self.cursor, (1, 0))

    def test_insert_enter_middle(self):
        self.set_text("hola")
        self.engine.cursor = (0, 2)
        self.key("i")
        self.engine.handle_key("Return", "")
        self.assertEqual(self.lines, ["ho", "la"])
        self.assertEqual(self.cursor, (1, 0))

    def test_insert_enter_at_line_start(self):
        self.set_text("hola")
        self.engine.cursor = (0, 0)
        self.key("i")
        self.engine.handle_key("Return", "")
        self.assertEqual(self.lines, ["", "hola"])
        self.assertEqual(self.cursor, (1, 0))

    def test_insert_enter_then_type(self):
        self.set_text("hola")
        self.key("A")
        self.engine.handle_key("Return", "")
        self.type_text("mundo")
        self.key("Escape")
        self.assertEqual(self.engine.text, "hola\nmundo")

    def test_insert_enter_undo(self):
        self.set_text("hola")
        self.key("A")
        self.engine.handle_key("Return", "")
        self.assertEqual(self.lines, ["hola", ""])
        self.key("Escape")
        self.key("u")
        self.assertEqual(self.lines, ["hola"])

    def test_insert_enter_then_backspace(self):
        self.set_text("hola")
        self.key("A")
        self.engine.handle_key("Return", "")
        self.engine.handle_key("BackSpace", "")
        self.assertEqual(self.lines, ["hola"])
        self.assertEqual(self.cursor, (0, 4))

    def test_backspace_at_line_start_noop(self):
        self.set_text("hola\nmundo")
        self.engine.cursor = (1, 0)
        self.key("i")
        self.engine.handle_key("BackSpace", "")
        self.assertEqual(self.lines, ["hola", "mundo"])
        self.assertEqual(self.cursor, (1, 0))

    def test_ctrlw_at_line_start_noop(self):
        self.set_text("hola\nmundo")
        self.engine.cursor = (1, 0)
        self.key("i")
        self.engine.handle_key("w", "", {"ctrl"})
        self.assertEqual(self.lines, ["hola", "mundo"])
        self.assertEqual(self.cursor, (1, 0))

    def test_backspace_empties_last_line_stays(self):
        self.set_text("hola\nmundo")
        self.engine.cursor = (1, 5)
        self.key("i")
        for _ in range(5):
            self.engine.handle_key("BackSpace", "")
        self.assertEqual(self.lines, ["hola", ""])
        self.assertEqual(self.cursor, (1, 0))

    def test_backspace_empty_line_joins_previous(self):
        self.set_text("hola\nmundo")
        self.engine.cursor = (1, 5)
        self.key("i")
        for _ in range(6):
            self.engine.handle_key("BackSpace", "")
        self.assertEqual(self.lines, ["hola"])
        self.assertEqual(self.cursor, (0, 4))

    def test_backspace_empty_middle_line_joins(self):
        self.set_text("hola\n\nmundo")
        self.engine.cursor = (1, 0)
        self.key("i")
        self.engine.handle_key("BackSpace", "")
        self.assertEqual(self.lines, ["hola", "mundo"])
        self.assertEqual(self.cursor, (0, 4))

    def test_backspace_empty_first_line_noop(self):
        self.set_text("")
        self.engine.cursor = (0, 0)
        self.key("i")
        self.engine.handle_key("BackSpace", "")
        self.assertEqual(self.lines, [""])
        self.assertEqual(self.cursor, (0, 0))

    def test_ctrlw_empties_last_line_stays(self):
        self.set_text("hola\nmundo")
        self.engine.cursor = (1, 5)
        self.key("i")
        self.engine.handle_key("w", "", {"ctrl"})
        self.assertEqual(self.lines, ["hola", ""])
        self.assertEqual(self.cursor, (1, 0))


    # Entrada del método de entrada (commit del IM) ----------------------
    # La vista entrega el texto compuesto (´+a -> "á") al motor con
    # handle_key("", texto). Simula la señal "commit" de Gtk.IMContext.

    def test_im_commit_insert(self):
        self.set_text("")
        self.key("i")
        self.engine.handle_key("", "á")
        self.engine.handle_key("", "ñ")
        self.key("Escape")
        self.assertEqual(self.engine.text, "áñ")
        self.assertEqual(self.cursor, (0, 2))

    def test_im_commit_mid_word(self):
        self.set_text("ola")
        self.key("i")
        self.engine.handle_key("", "ó")
        self.key("Escape")
        self.assertEqual(self.engine.text, "óola")
        self.assertEqual(self.cursor, (0, 1))

    def test_im_commit_then_normal_keys(self):
        # Flujo real: ´+a compone "á" (commit); la siguiente tecla es una
        # letra normal que llega por key-pressed. No debe sustituirse la "á".
        self.set_text("")
        self.key("i")
        self.engine.handle_key("", "á")
        self.engine.handle_key("b", "b")
        self.engine.handle_key("c", "c")
        self.key("Escape")
        self.assertEqual(self.engine.text, "ábc")
        self.assertEqual(self.cursor, (0, 3))

    def test_im_commit_replace_mode(self):
        self.set_text("hola")
        self.key("R")
        self.engine.handle_key("", "é")
        self.key("Escape")
        self.assertEqual(self.engine.text, "éola")

    def test_im_commit_in_search_prompt(self):
        self.set_text("más y más")
        self.key("/")
        self.engine.handle_key("", "más")
        self.engine.handle_key("Return", "")
        self.assertEqual(self.engine.search_pattern, "más")

    def test_im_commit_normal_mode_ignored(self):
        self.set_text("hola")
        self.engine.handle_key("", "á")
        self.assertEqual(self.engine.text, "hola")


if __name__ == "__main__":
    unittest.main()
