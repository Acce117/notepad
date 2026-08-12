# -*- coding: utf-8 -*-
"""
Motor de edición estilo Vim (sin dependencias de GTK).

Contiene toda la lógica de edición: modos (normal, insertar, visual,
comando, búsqueda), movimientos, operadores, contadores, registros,
deshacer/rehacer y búsqueda con resaltado.

Diseño: el motor es un *modelo* puro. No conoce nada de GTK. La vista
(GTK) se engancha a través de dos callbacks:
  - `renderer`: función sin argumentos que refresca la interfaz
    (Gtk.TextView) leyendo el estado del motor.
  - `ui`: objeto que implementa la interfaz de la aplicación
    (guardar/cerrar/crear/borrar/renombrar nota y barra de estado).

Esto permite probar el motor de forma unitaria sin una pantalla (ver
tests/test_engine.py).
"""

import re

# Modificadores de teclado normalizados (minúsculas).
CTRL = "ctrl"
SHIFT = "shift"
ALT = "alt"
SUPER = "super"

_BRACKET_OPEN = "([{"
_BRACKET_CLOSE = ")]}"

# Comandos de la línea `:` que delegan en la aplicación (ventana).
_APP_COMMANDS = {
    "w": "save", "wa": "save",
    "wq": "quit_save", "x": "quit_save", "wq!": "quit_save", "wqa": "quit_save",
    "q": "quit", "q!": "quit_force",
    "n": "new", "new": "new", "newnote": "new",
    "d": "delete", "del": "delete", "delete": "delete",
    "r": "rename", "rename": "rename",
}


def is_blank(ch):
    """Separador de palabra: espacio o tabulador."""
    return ch in " \t"


def _skip_nb_fwd(line, i):
    """Avanza desde i mientras haya caracteres no blancos (fin de palabra)."""
    while i < len(line) and not is_blank(line[i]):
        i += 1
    return i


def _skip_nb_bwd(line, i):
    """Desde i (exclusivo), retrocede al inicio de la palabra actual."""
    while i > 0 and not is_blank(line[i - 1]):
        i -= 1
    return i


def _skip_b_fwd(line, i):
    """Salta espacios/tabuladores hacia delante desde i."""
    while i < len(line) and is_blank(line[i]):
        i += 1
    return i


def _skip_b_bwd(line, i):
    """Salta espacios/tabuladores hacia atrás desde i (exclusivo)."""
    while i > 0 and is_blank(line[i - 1]):
        i -= 1
    return i


def _next_word_start(lines, row, col):
    """Inicio de la siguiente palabra (`w`)."""
    n = len(lines)
    if n == 0:
        return None
    row = min(row, n - 1)
    col = min(col, len(lines[row]))
    if col < len(lines[row]) and not is_blank(lines[row][col]):
        col = _skip_nb_fwd(lines[row], col)
    while True:
        col = _skip_b_fwd(lines[row], col)
        if col < len(lines[row]):
            return (row, col)
        if row + 1 < n:
            row += 1
            col = 0
        else:
            return None


def _end_word(lines, row, col):
    """Fin de la palabra actual o siguiente (`e`)."""
    n = len(lines)
    if n == 0:
        return None
    row = min(row, n - 1)
    col = min(col, len(lines[row]))
    while True:
        col = _skip_b_fwd(lines[row], col)
        if col < len(lines[row]):
            return (row, _skip_nb_fwd(lines[row], col) - 1)
        if row + 1 < n:
            row += 1
            col = 0
        else:
            return None


def _prev_word_start(lines, row, col):
    """Inicio de la palabra anterior (`b`)."""
    n = len(lines)
    if n == 0:
        return None
    row = min(row, n - 1)
    col = min(col, len(lines[row]))
    while True:
        col = _skip_b_bwd(lines[row], col)
        if col > 0:
            return (row, _skip_nb_bwd(lines[row], col))
        if row > 0:
            row -= 1
            col = len(lines[row])
        else:
            return None


def _prev_word_end(lines, row, col):
    """Fin de la palabra *anterior* a la del cursor (`ge`).

    Verificado contra Vim real: desde dentro/final de una palabra, desde un
    espacio o desde el final de línea, `ge` salta al final de la palabra
    estrictamente anterior a la que ocupa el cursor."""
    n = len(lines)
    if n == 0:
        return None
    row = min(row, n - 1)
    col = min(col, len(lines[row]))
    while True:
        line = lines[row]
        if col > 0 and not is_blank(line[col - 1]):
            # Estamos dentro (o al final) de una palabra: fin de la anterior.
            start = _skip_nb_bwd(line, col)
            i = _skip_b_bwd(line, start)
            if i > 0:
                return (row, i - 1)
            if row > 0:
                row -= 1
                col = len(lines[row])
                continue
            return None
        # Cursor sobre un blanco o al final de línea.
        i = _skip_b_bwd(line, col)
        if i > 0:
            return (row, i - 1)
        if row > 0:
            row -= 1
            col = len(lines[row])
        else:
            return None


class VimEngine:
    """Editor modal estilo Vim sobre una lista de líneas de texto."""

    def __init__(self, text="", ui=None, renderer=None):
        # Enlaces hacia la aplicación y la vista (se configuran al crear la UI).
        self.ui = ui
        self.renderer = renderer

        self.lines = [""]
        self.cursor = (0, 0)
        self.mode = "normal"   # normal|insert|replace|visual|visual-line|visual-block|command|search
        self.status = ""
        self._message = ""

        # Estado de comandos pendientes en modo normal.
        self.count = ""
        self.op = None
        self._pending_g = False
        self._pending_f = None
        self._pending_replace = False
        self._find = None

        # Registro sin nombre (para y/p/P).
        self.reg = {"text": "", "kind": "char"}

        # Deshacer / rehacer (instantáneas del buffer + cursor).
        self._undo = []
        self._redo = []
        self._insert_pushed = False
        self._insert_chars = ""
        self._last_insert = ""
        self._pending_normal_once = False

        # Modo visual.
        self._vis_anchor = (0, 0)

        # Inserción en bloque (Ctrl-v + I).
        self._block_col = 0
        self._block_rows = []
        self._block_active = False

        # Búsqueda de texto.
        self.search_pattern = None
        self.search_matches = []
        self._search_dir = "f"
        self._prompt_backward = False
        self._prompt_text = ""

        self.set_text(text)

    # ------------------------------------------------------------------ #
    # Utilidades de conversión de coordenadas                            #
    # ------------------------------------------------------------------ #

    def _to_off(self, pos):
        """(fila, columna) -> offset global en el texto unido."""
        row, col = pos
        return sum(len(l) + 1 for l in self.lines[:row]) + col

    def _to_pos(self, off):
        """offset global -> (fila, columna)."""
        for row, line in enumerate(self.lines):
            if off <= len(line):
                return (row, off)
            off -= len(line) + 1
        last = len(self.lines) - 1
        return (last, len(self.lines[last]))

    def _clamp(self, pos):
        row = min(max(0, pos[0]), len(self.lines) - 1)
        col = min(max(0, pos[1]), len(self.lines[row]))
        return (row, col)

    def _text(self):
        return "\n".join(self.lines)

    @property
    def text(self):
        """Texto completo del buffer (acceso público para la vista)."""
        return self._text()

    def selection(self):
        """Rango de selección visual actual: (tipo, o1, o2, pos1, pos2).

        tipo: 'char' | 'line' | 'block'. Fuera de modo visual devuelve None."""
        if self.mode not in ("visual", "visual-line", "visual-block"):
            return None
        kind, r1, r2, o1, o2 = self._visual_range()
        return (kind, r1, r2, o1, o2)

    def _set_buffer(self, text, cursor=None):
        if text == "":
            self.lines = [""]
        else:
            self.lines = text.split("\n")
            if text.endswith("\n"):
                self.lines.pop()
            if not self.lines:
                self.lines = [""]
        self.cursor = self._clamp(cursor) if cursor else (0, 0)

    def _changed(self):
        """Notifica a la vista que el estado cambió (refresco + estado)."""
        if self.renderer:
            self.renderer()
        if self.ui is not None and hasattr(self.ui, "set_status"):
            self.ui.set_status(self._status_text())

    def _status_text(self):
        """Texto de la barra de estado (modo + comando pendiente + mensajes)."""
        if self.mode == "search":
            prompt = "?" if self._prompt_backward else "/"
            return prompt + self._prompt_text
        if self.mode == "command":
            return ":" + self._prompt_text
        if self._message:
            return self._message
        base = {"normal": "", "insert": "-- INSERTAR --",
                "replace": "-- REEMPLAZAR --",
                "visual": "-- VISUAL --",
                "visual-line": "-- VISUAL LÍNEA --",
                "visual-block": "-- VISUAL BLOQUE --"}[self.mode]
        pend = self.count or ""
        if self.op:
            pend += self.op
        elif self._pending_g:
            pend += "g"
        return base + ((" " + pend) if pend else "")

    # ------------------------------------------------------------------ #
    # Deshacer / rehacer                                                 #
    # ------------------------------------------------------------------ #

    def _snapshot(self):
        return (list(self.lines), self.cursor)

    def _push_undo(self):
        self._undo.append(self._snapshot())
        if len(self._undo) > 500:
            self._undo.pop(0)
        self._redo.clear()

    def _undo_action(self):
        if not self._undo:
            self._message = "Nada que deshacer"
            self._changed()
            return
        self._redo.append(self._snapshot())
        self.lines, self.cursor = self._undo.pop()
        self.cursor = self._clamp(self.cursor)
        self.mode = "normal"
        self._clear_pending_silent()
        self._message = "Deshacer"
        self._changed()

    def _redo_action(self):
        if not self._redo:
            self._message = "Nada que rehacer"
            self._changed()
            return
        self._undo.append(self._snapshot())
        self.lines, self.cursor = self._redo.pop()
        self.cursor = self._clamp(self.cursor)
        self.mode = "normal"
        self._clear_pending_silent()
        self._message = "Rehacer"
        self._changed()

    # ------------------------------------------------------------------ #
    # Carga inicial / contenido completo                                 #
    # ------------------------------------------------------------------ #

    def set_text(self, text):
        """Carga el contenido de una nota; limpia deshacer y búsqueda."""
        self._set_buffer(text)
        self.mode = "normal"
        self._clear_pending_silent()
        self._undo.clear()
        self._redo.clear()
        self._last_insert = ""
        self.search_pattern = None
        self.search_matches = []
        self._message = ""
        self._changed()

    def _clear_pending_silent(self):
        self.count = ""
        self.op = None
        self._pending_g = False
        self._pending_f = None
        self._pending_replace = False
        self._pending_normal_once = False

    def _clear_pending(self):
        self._clear_pending_silent()
        self._changed()

    def _count_int(self):
        """Contador tecleado como entero (1 si está vacío)."""
        try:
            return int(self.count) if self.count else 1
        except ValueError:
            return 1

    # ------------------------------------------------------------------ #
    # Entrada de teclado (punto único de entrada)                        #
    # ------------------------------------------------------------------ #

    def handle_key(self, name, char="", mods=frozenset()):
        """Procesa una tecla. `name` es el keyval GTK (p. ej. 'Return'),
        `char` el carácter Unicode ('' si no produce), `mods` un conjunto
        con ctrl/shift/alt/super."""
        if self.mode in ("search", "command"):
            self._handle_prompt_key(name, char, mods)
        elif self.mode in ("insert", "replace"):
            self._handle_insert_key(name, char, mods)
        elif self.mode in ("visual", "visual-line", "visual-block"):
            self._handle_normal_key(name, char, mods, visual=True)
        else:
            self._handle_normal_key(name, char, mods, visual=False)

    # ------------------------------------------------------------------ #
    # Modo normal / visual                                               #
    # ------------------------------------------------------------------ #

    def _handle_normal_key(self, name, char, mods, visual):
        if CTRL in mods:
            if name == "r":
                self._redo_action()
            elif name == "v":
                self._enter_visual("block")
            elif name == "[":
                self._clear_pending()
            return
        if ALT in mods or SUPER in mods:
            return

        # f/F/t/T esperan un carácter.
        if self._pending_f is not None:
            c = char if char else name
            if c:
                self._exec_find(self._pending_f, c)
                self._pending_f = None
            return

        # r espera el carácter de reemplazo.
        if self._pending_replace:
            self._pending_replace = False
            if char:
                self._do_replace(char)
            return

        # Prefijo 'g' (gg, ge).
        if self._pending_g:
            self._pending_g = False
            if char == "g":
                if self.op:
                    self._exec_operator_motion("g", "gg")
                else:
                    self._goto_line(self._count_int() - 1)
            elif char == "e":
                self._apply_motion_or_op("e", ge=True)
            else:
                self.count = ""
                self._changed()
            return

        # Contadores.
        if char in "0123456789":
            if char == "0" and not self.count and not self.op:
                self._apply_motion_or_op("0")
            else:
                self.count += char
            return

        if not visual:
            if char == ":":
                self._enter_prompt("command")
                return
            if char == "/":
                self._prompt_backward = False
                self._enter_prompt("search")
                return
            if char == "?":
                self._prompt_backward = True
                self._enter_prompt("search")
                return

        if visual:
            if char in ("v", "V"):
                self.mode = "normal"
                self._changed()
                return
            if name == "Escape":
                self.mode = "normal"
                self._changed()
                return
            if char == "o":
                self.cursor, self._vis_anchor = self._vis_anchor, self.cursor
                self._changed()
                return
            if char in ("y", "d", "c", "x", "~"):
                self._visual_operator(char)
                return
            if char in ("I", "A"):
                self._block_insert(char)
                return

        # Operadores d / y / c (doble = dd/yy/cc).
        if char in ("d", "y", "c"):
            if self.op == char:
                self._exec_operator(char, self._count_int())
                self.op = None
                self.count = ""
            elif self.op is not None:
                self.op = char
                self.count = ""
                self._changed()
            else:
                self.op = char
                self._changed()
            return

        # Comandos de una sola letra.
        if self._dispatch_single(char, visual):
            return

        # Cualquier otra letra = movimiento (o se ignora).
        self._apply_motion_or_op(char)

    def _dispatch_single(self, char, visual):
        if visual:
            return False
        table = {
            "x": self._cmd_x, "X": self._cmd_X, "s": self._cmd_s,
            "S": self._cmd_S, "D": self._cmd_D, "C": self._cmd_C,
            "p": self._cmd_p, "P": self._cmd_P, "r": self._cmd_r,
            "R": self._cmd_R, "J": self._cmd_J, "~": self._cmd_tilde,
            "u": self._undo_action,
            "n": self._cmd_n, "N": self._cmd_N,
            "i": self._enter_insert, "a": self._cmd_a, "A": self._cmd_A,
            "I": self._cmd_I, "o": self._cmd_o, "O": self._cmd_O,
            "v": lambda: self._enter_visual("char"),
            "V": lambda: self._enter_visual("line"),
            ".": self._cmd_dot,
            "g": self._cmd_g,
        }
        if char in table:
            table[char]()
            return True
        return False

    # ------------------------------------------------------------------ #
    # Aplicación de movimientos / operador + movimiento                  #
    # ------------------------------------------------------------------ #

    def _apply_motion_or_op(self, mname, ge=False):
        """Aplica un movimiento; si hay operador pendiente, lo ejecuta."""
        if self.op:
            self._exec_operator_motion(self.op, mname)
            self.op = None
            self.count = ""
        else:
            self._exec_motion(mname, ge=ge)

    def _motion_target(self, mname, count=None, ge=False):
        """Devuelve (pos_destino, linewise) para un movimiento, o None."""
        cnt = count if count is not None else self._count_int()
        cur = self.cursor
        n = len(self.lines)
        row, col = cur

        if mname == "h":
            for _ in range(cnt):
                col -= 1
                if col < 0:
                    if row > 0:
                        row -= 1
                        col = len(self.lines[row])
                    else:
                        col = 0
            return (row, col), False
        if mname == "l":
            for _ in range(cnt):
                if col < len(self.lines[row]):
                    col += 1
            return (row, col), False
        if mname in ("j", "k"):
            step = 1 if mname == "j" else -1
            for _ in range(cnt):
                nr = row + step
                if 0 <= nr < n:
                    row = nr
                    col = min(col, len(self.lines[row]))
            return (row, col), True
        if mname == "w":
            return self._word_target("w", cnt), False
        if mname == "e":
            return self._word_target("e", cnt), False
        if mname == "b":
            return self._word_target("b", cnt), False
        if mname == "ge" or ge:
            return self._word_target("ge", cnt), False
        if mname == "0":
            return (row, 0), False
        if mname == "^":
            return (row, _skip_b_fwd(self.lines[row], 0)), False
        if mname == "$":
            target = min(row + cnt - 1, n - 1)
            return (target, len(self.lines[target])), False
        if mname == "gg":
            return (0, 0), True
        if mname == "G":
            target = min(cnt - 1, n - 1) if self.count else n - 1
            return (target, 0), True
        if mname == "%":
            return self._bracket_match(cur), False
        if mname == "{":
            return self._paragraph(cur, -1), True
        if mname == "}":
            return self._paragraph(cur, +1), True
        if mname in ("f", "F", "t", "T"):
            self._pending_f = mname
            return None
        if mname in (";", ","):
            return self._repeat_find_target(mname), False
        return None

    def _word_target(self, kind, cnt):
        pos = self.cursor
        for _ in range(cnt):
            if kind == "w":
                pos = _next_word_start(self.lines, *pos)
            elif kind == "e":
                pos = _end_word(self.lines, *pos)
            elif kind == "b":
                pos = _prev_word_start(self.lines, *pos)
            elif kind == "ge":
                pos = _prev_word_end(self.lines, *pos)
            if pos is None:
                return self.cursor
        return pos

    def _exec_motion(self, mname, ge=False):
        t = self._motion_target(mname, ge=ge)
        if t is None:
            return
        pos, linewise = t
        self.cursor = self._clamp(pos)
        self.count = ""
        self._changed()

    def _goto_line(self, line):
        self.cursor = self._clamp((line, 0))
        self.count = ""
        self._changed()

    def _bracket_match(self, cur):
        row, col = cur
        line = self.lines[row]
        if col >= len(line):
            return cur
        ch = line[col]
        text = self._text()
        off = self._to_off(cur)
        if ch in _BRACKET_OPEN:
            depth = 1
            i = off + 1
            close = {"(": ")", "[": "]", "{": "}"}[ch]
            while i < len(text):
                c = text[i]
                if c in _BRACKET_OPEN:
                    depth += 1
                elif c in _BRACKET_CLOSE:
                    depth -= 1
                    if depth == 0:
                        return self._to_pos(i)
                i += 1
            return cur
        if ch in _BRACKET_CLOSE:
            depth = 1
            i = off - 1
            while i >= 0:
                c = text[i]
                if c in _BRACKET_CLOSE:
                    depth += 1
                elif c in _BRACKET_OPEN:
                    depth -= 1
                    if depth == 0:
                        return self._to_pos(i)
                i -= 1
            return cur
        return cur

    def _paragraph(self, cur, step):
        row, col = cur
        n = len(self.lines)
        r = row + step
        while 0 <= r < n:
            if self.lines[r].strip() == "":
                return (r, 0)
            r += step
        return (row, 0) if step < 0 else (n - 1, 0)

    def _exec_find(self, mname, c):
        """Resuelve f/F/t/T: mueve el cursor o completa un operador pendiente."""
        row, col = self.cursor
        line = self.lines[row]
        step = 1 if mname in ("f", "t") else -1
        k = col if step == 1 else col - 1
        found = -1
        while 0 <= k < len(line):
            if line[k] == c:
                found = k
                break
            k += step
        if found != -1:
            fwd = mname in ("f", "t")
            till = mname in ("t", "T")
            self._find = {"char": c, "fwd": fwd, "till": till}
            if self.op:
                # f/F incluyen el carácter; t/T lo excluyen.
                so = self._to_off(self.cursor)
                to = self._to_off((row, found))
                if fwd:
                    rng = ("char", so, to + (0 if till else 1))
                else:
                    rng = ("char", to + (1 if till else 0), so)
                self._exec_operator_range(self.op, rng)
                self.op = None
            else:
                # Movimiento: f/F aterrizan sobre el carácter; t/T justo antes.
                if mname in ("f", "F"):
                    target = found
                else:
                    target = found - 1 if fwd else found + 1
                self.cursor = (row, max(0, min(target, len(line))))
        else:
            self._find = None
            self._message = f"'{c}' no encontrado"
        self.count = ""
        self._changed()

    def _repeat_find_target(self, mname):
        if not self._find:
            return self.cursor
        f = self._find
        fwd = f["fwd"] if mname == ";" else not f["fwd"]
        step = 1 if fwd else -1
        row, col = self.cursor
        line = self.lines[row]
        k = col if step == 1 else col - 1
        while 0 <= k < len(line):
            if line[k] == f["char"]:
                target = k - 1 if (f["till"] and fwd) else (k + 1 if f["till"] else k)
                return (row, max(0, min(target, len(line))))
            k += step
        return self.cursor

    # ------------------------------------------------------------------ #
    # Operadores d / y / c                                               #
    # ------------------------------------------------------------------ #

    def _exec_operator(self, op, count):
        """Ejecuta un operador doble (dd, yy, cc) sobre `count` líneas."""
        row = self.cursor[0]
        r1 = row
        r2 = min(row + count - 1, len(self.lines) - 1)
        self._exec_operator_range(op, ("line", r1, r2))
        self.count = ""
        self._changed()

    def _exec_operator_motion(self, op, mname):
        """Ejecuta operador + movimiento (p. ej. dw, y$, cw)."""
        rng = self._op_range(mname)
        if rng is None:
            return
        self._exec_operator_range(op, rng)
        self.count = ""
        self._changed()

    def _op_range(self, mname):
        """Devuelve el rango sobre el que actúa un operador con el movimiento
        `mname`. Formato: ('char', o1, o2) o ('line', r1, r2). None = sin rango.

        La inclusividad de cada movimiento sigue el comportamiento de Vim real:
          - w, b, 0, ^, l, h, t, T  -> exclusivos
          - e, ge, $, f, F, %       -> inclusivos
          - j, k, gg, G, {, }       -> por líneas
        """
        start = self.cursor
        row, col = start
        line = self.lines[row]
        so = self._to_off(start)
        n = len(self.lines)
        cnt = self._count_int()

        if mname == "w":
            t = _next_word_start(self.lines, row, col)
            if t is None:
                return ("char", so, self._to_off((row, len(line))))
            return ("char", so, self._to_off(t))
        if mname == "e":
            t = _end_word(self.lines, row, col)
            if t is None:
                return ("char", so, self._to_off((row, len(line))))
            return ("char", so, self._to_off(t) + 1)
        if mname == "b":
            t = _prev_word_start(self.lines, row, col)
            if t is None:
                return ("char", so, so)
            return ("char", self._to_off(t), so)
        if mname == "ge":
            t = _prev_word_end(self.lines, row, col)
            if t is None:
                return ("char", so, so)
            return ("char", self._to_off(t), so)
        if mname == "h":
            c0 = max(0, col - cnt)
            return ("char", self._to_off((row, c0)), so)
        if mname == "l":
            c1 = min(col + cnt, len(line))
            return ("char", so, self._to_off((row, c1)))
        if mname == "j":
            r2 = min(row + cnt, n - 1)
            return ("line", row, r2)
        if mname == "k":
            r1 = max(0, row - cnt)
            return ("line", r1, row)
        if mname == "0":
            return ("char", self._to_off((row, 0)), so)
        if mname == "^":
            return ("char", self._to_off((row, _skip_b_fwd(line, 0))), so)
        if mname == "$":
            tr = min(row + cnt - 1, n - 1)
            return ("char", so, self._to_off((tr, len(self.lines[tr]))))
        if mname == "gg":
            return ("line", 0, row)
        if mname == "G":
            tr = min(cnt - 1, n - 1) if self.count else n - 1
            return ("line", min(row, tr), max(row, tr))
        if mname == "%":
            t = self._bracket_match(start)
            if t == start:
                return ("char", so, so)
            return ("char", min(so, self._to_off(t)), max(so, self._to_off(t)) + 1)
        if mname == "{":
            return ("line", max(0, self._paragraph(start, -1)[0]), row)
        if mname == "}":
            return ("line", row, min(self._paragraph(start, +1)[0], n - 1))
        if mname in ("f", "F", "t", "T"):
            # Requiere un carácter; se resuelve en `_exec_find`.
            return None
        if mname in (";", ","):
            t = self._repeat_find_target(mname)
            if t == start:
                return ("char", so, so)
            f = self._find or {}
            fwd = (f.get("fwd", True)) if mname == ";" else (not f.get("fwd", True))
            till = f.get("till", False)
            to = self._to_off(t)
            if fwd:
                return ("char", so, to + (0 if till else 1))
            return ("char", to + (1 if till else 0), so)
        return None

    def _exec_operator_range(self, op, rng):
        """Aplica un operador (d/y/c) sobre un rango."""
        kind = rng[0]
        self._push_undo()
        if kind == "line":
            _, r1, r2 = rng
            if op == "y":
                text = "\n".join(self.lines[r1:r2 + 1]) + "\n"
                self.reg = {"text": text, "kind": "line"}
            else:
                self._delete_lines(r1, r2)
                if op == "c":
                    self._enter_insert()
        else:
            _, o1, o2 = rng
            if o2 < o1:
                o1, o2 = o2, o1
            if o1 == o2:
                self._message = "Sin cambio"
            elif op == "y":
                self.reg = {"text": self._text()[o1:o2], "kind": "char"}
            else:
                self._delete_range(o1, o2)
                if op == "c":
                    self._enter_insert()

    def _delete_lines(self, r1, r2):
        """Borra líneas [r1, r2] completas; cursor al inicio de la siguiente."""
        if r1 == 0 and r2 == len(self.lines) - 1:
            self._set_buffer("")
            return
        o1 = self._to_off((r1, 0))
        if r2 == len(self.lines) - 1:
            o2 = len(self._text())
        else:
            o2 = self._to_off((r2 + 1, 0))
        self._delete_range(o1, o2)
        self.cursor = self._clamp((r1, 0))

    def _delete_range(self, start, end):
        text = self._text()
        new = text[:start] + text[end:]
        self._set_buffer(new, self._to_pos(start))

    def _insert_at(self, off, s, cursor_after=None):
        """Inserta `s` en el offset global `off`."""
        text = self._text()
        new = text[:off] + s + text[off:]
        self._set_buffer(new, (0, 0))
        if cursor_after is None:
            cursor_after = self._to_pos(off + len(s))
        self.cursor = self._clamp(cursor_after)

    # --- comandos de una letra ---

    def _cmd_x(self):
        self._push_undo()
        cnt = self._count_int()
        row, col = self.cursor
        line = self.lines[row]
        end = min(col + cnt, len(line))
        self.reg = {"text": line[col:end], "kind": "char"}
        self._delete_range(self._to_off((row, col)), self._to_off((row, end)))
        self.count = ""
        self._changed()

    def _cmd_X(self):
        self._push_undo()
        cnt = self._count_int()
        row, col = self.cursor
        start = max(0, col - cnt)
        self.reg = {"text": self.lines[row][start:col], "kind": "char"}
        self._delete_range(self._to_off((row, start)), self._to_off((row, col)))
        self.cursor = (row, start)
        self.count = ""
        self._changed()

    def _cmd_s(self):
        self._push_undo()
        row, col = self.cursor
        end = min(col + 1, len(self.lines[row]))
        self.reg = {"text": self.lines[row][col:end], "kind": "char"}
        self._delete_range(self._to_off((row, col)), self._to_off((row, end)))
        self.cursor = (row, col)
        self._enter_insert()
        self.count = ""
        self._changed()

    def _cmd_S(self):
        self._exec_operator("c", self._count_int())

    def _cmd_D(self):
        self._push_undo()
        row, col = self.cursor
        o1 = self._to_off((row, col))
        o2 = self._to_off((row, len(self.lines[row])))
        self.reg = {"text": self._text()[o1:o2], "kind": "char"}
        self._delete_range(o1, o2)
        self.count = ""
        self._changed()

    def _cmd_C(self):
        self._push_undo()
        row, col = self.cursor
        o1 = self._to_off((row, col))
        o2 = self._to_off((row, len(self.lines[row])))
        self.reg = {"text": self._text()[o1:o2], "kind": "char"}
        self._delete_range(o1, o2)
        self.cursor = (row, col)
        self._enter_insert()
        self.count = ""
        self._changed()

    def _cmd_p(self):
        self._paste(after=True)

    def _cmd_P(self):
        self._paste(after=False)

    def _paste(self, after):
        if not self.reg["text"]:
            self._message = "Registro vacío"
            self._changed()
            return
        self._push_undo()
        if self.reg["kind"] == "line":
            # Pegado a nivel de línea: debajo (p) o encima (P) de la actual.
            rows = self.reg["text"].splitlines()
            row = self.cursor[0] + 1 if after else self.cursor[0]
            self.lines[row:row] = rows
            self.cursor = self._clamp((row, 0))
        else:
            # Pegado a nivel de carácter en el offset del cursor.
            text = self.reg["text"]
            row, col = self.cursor
            off = self._to_off((row, col))
            if after and col < len(self.lines[row]):
                off += 1  # p: tras el carácter bajo el cursor
            new = self._text()
            new = new[:off] + text + new[off:]
            self._set_buffer(new, self._to_pos(off + len(text)))
        self.count = ""
        self._changed()

    def _cmd_r(self):
        # r espera el carácter de reemplazo (se resuelve en handle_key).
        self._pending_replace = True
        self._changed()

    def _do_replace(self, ch):
        """Reemplaza `count` caracteres bajo el cursor por `ch`."""
        self._push_undo()
        row, col = self.cursor
        cnt = max(1, self._count_int())
        line = self.lines[row]
        end = min(col + cnt, len(line))
        self.lines[row] = line[:col] + ch * (end - col) + line[end:]
        self.cursor = (row, end)
        self.count = ""
        self._changed()

    def _cmd_R(self):
        self.mode = "replace"
        self._insert_pushed = False
        self._insert_chars = ""
        self._pending_normal_once = False
        self._changed()

    def _cmd_J(self):
        self._push_undo()
        row = self.cursor[0]
        if row >= len(self.lines) - 1:
            self._message = "Sin línea siguiente"
            self._changed()
            return
        left = self.lines[row]
        right = self.lines[row + 1]
        sep = "" if left and left[-1].isspace() else " "
        merged = left + sep + right.lstrip()
        self.lines[row:row + 2] = [merged]
        self.cursor = (row, len(left))
        self.count = ""
        self._changed()

    def _cmd_tilde(self):
        self._push_undo()
        cnt = self._count_int()
        row, col = self.cursor
        line = self.lines[row]
        if col < len(line):
            end = min(col + cnt, len(line))
            chunk = line[col:end]
            self.lines[row] = line[:col] + self._swapcase(chunk) + line[end:]
            self.cursor = (row, min(end, len(self.lines[row])))
        self.count = ""
        self._changed()

    @staticmethod
    def _swapcase(s):
        return "".join(ch.lower() if ch.isupper() else ch.upper() for ch in s)

    def _cmd_g(self):
        self._pending_g = True
        self._changed()

    def _cmd_n(self):
        self._goto_next_search(forward=True)

    def _cmd_N(self):
        self._goto_next_search(forward=False)

    def _cmd_dot(self):
        if self._last_insert:
            self._push_undo()
            self._insert_at(self._to_off(self.cursor), self._last_insert)
            self._changed()

    # --- entrada en modo insertar ---

    def _enter_insert(self):
        self.mode = "insert"
        self._insert_pushed = False
        self._insert_chars = ""
        self._pending_normal_once = False
        self._block_active = False
        self._changed()

    def _cmd_a(self):
        row, col = self.cursor
        if col < len(self.lines[row]):
            self.cursor = (row, col + 1)
        self._enter_insert()
        self.count = ""
        self._changed()

    def _cmd_A(self):
        row, col = self.cursor
        self.cursor = (row, len(self.lines[row]))
        self._enter_insert()
        self.count = ""
        self._changed()

    def _cmd_I(self):
        row, col = self.cursor
        self.cursor = (row, _skip_b_fwd(self.lines[row], 0))
        self._enter_insert()
        self.count = ""
        self._changed()

    def _cmd_o(self):
        self._push_undo()
        cnt = max(1, self._count_int())
        row = self.cursor[0] + 1
        self.lines[row:row] = [""] * cnt
        self.cursor = (row, 0)
        self._enter_insert()
        self.count = ""
        self._changed()

    def _cmd_O(self):
        self._push_undo()
        cnt = max(1, self._count_int())
        row = self.cursor[0]
        self.lines[row:row] = [""] * cnt
        self.cursor = (row, 0)
        self._enter_insert()
        self.count = ""
        self._changed()

    # --- modo insertar / reemplazar ---

    def _handle_insert_key(self, name, char, mods):
        # Inserción en bloque: acumulamos el texto y lo aplicamos a todas las
        # líneas seleccionadas al salir con Escape.
        if self._block_active:
            if name == "Escape":
                self._leave_insert()
            elif name == "BackSpace":
                self._insert_chars = self._insert_chars[:-1]
                self._changed()
            elif char and char != "\n":
                self._insert_chars += char
                self._changed()
            return

        if CTRL in mods:
            if name == "[":
                self._leave_insert()
                return
            if name == "w":
                self._insert_delete_word_back()
                return
            if name == "u":
                self._insert_delete_line_start()
                return
            if name == "o":
                self._pending_normal_once = True
                self._changed()
                return
            if name in ("a", "e"):
                row, col = self.cursor
                self.cursor = (row, 0 if name == "a" else len(self.lines[row]))
                self._changed()
                return
            if name == "d":
                row, col = self.cursor
                self._delete_range(self._to_off((row, col)), self._to_off((row, len(self.lines[row]))))
                self._changed()
                return
        if ALT in mods or SUPER in mods:
            return

        # Ctrl-O: un comando normal puntual y volvemos a insertar.
        if self._pending_normal_once:
            self._pending_normal_once = False
            self._handle_normal_key(name, char, mods, visual=False)
            if self.mode == "normal":
                self.mode = "insert"
                self._changed()
            return

        if name == "Escape":
            self._leave_insert()
            return
        if name in ("Return", "KP_Enter"):
            self._insert_text("\n")
            return
        if name == "BackSpace":
            self._insert_backspace()
            return
        if name == "Delete":
            self._insert_delete_fwd()
            return
        if name == "Tab":
            self._insert_text("\t")
            return
        if name in ("Left", "Right", "Up", "Down"):
            self._insert_arrow(name)
            return
        if name == "Home":
            row, col = self.cursor
            self.cursor = (row, 0)
            self._changed()
            return
        if name == "End":
            row, col = self.cursor
            self.cursor = (row, len(self.lines[row]))
            self._changed()
            return
        if char:
            if self.mode == "replace" and char != "\n":
                self._replace_char(char)
            else:
                self._insert_text(char)

    def _leave_insert(self):
        if self._block_active:
            self._apply_block_insert()
        self._last_insert = self._insert_chars
        self.mode = "normal"
        self._clear_pending_silent()
        self._block_active = False
        self._changed()

    def _insert_text(self, s):
        if not self._insert_pushed:
            self._push_undo()
            self._insert_pushed = True
        self._insert_chars += s
        if s == "\n":
            # Salto de línea a nivel de líneas: conserva la línea vacía final
            # (la ruta por `_set_buffer` la descartaría al final del texto).
            row, col = self.cursor
            line = self.lines[row]
            self.lines[row:row + 1] = [line[:col], line[col:]]
            self.cursor = (row + 1, 0)
        else:
            self._insert_at(self._to_off(self.cursor), s)
        self._changed()

    def _replace_char(self, ch):
        if not self._insert_pushed:
            self._push_undo()
            self._insert_pushed = True
        self._insert_chars += ch
        row, col = self.cursor
        line = self.lines[row]
        if col < len(line):
            self.lines[row] = line[:col] + ch + line[col + 1:]
            self.cursor = (row, col + 1)
        else:
            self._insert_at(self._to_off((row, col)), ch, cursor_after=(row, col + 1))
        self._changed()

    def _insert_backspace(self):
        row, col = self.cursor
        if col == 0:
            # Al inicio de una línea, Backspace no hace nada (no une con la
            # línea anterior).
            return
        if not self._insert_pushed:
            self._push_undo()
            self._insert_pushed = True
        line = self.lines[row]
        self.lines[row] = line[:col - 1] + line[col:]
        self.cursor = (row, col - 1)
        self._changed()

    def _insert_delete_fwd(self):
        row, col = self.cursor
        if col < len(self.lines[row]):
            self._delete_range(self._to_off((row, col)), self._to_off((row, col + 1)))
        elif row < len(self.lines) - 1:
            self.lines[row] = self.lines[row] + self.lines[row + 1]
            del self.lines[row + 1]
        self._changed()

    def _insert_delete_word_back(self):
        row, col = self.cursor
        line = self.lines[row]
        if col == 0 and row > 0:
            self._insert_backspace()
            return
        if not self._insert_pushed:
            self._push_undo()
            self._insert_pushed = True
        start = _skip_b_bwd(line, col)
        start = _skip_nb_bwd(line, start)
        if start == col:
            return
        self.lines[row] = line[:start] + line[col:]
        self.cursor = (row, start)
        self._changed()

    def _insert_delete_line_start(self):
        if not self._insert_pushed:
            self._push_undo()
            self._insert_pushed = True
        row, col = self.cursor
        self._delete_range(self._to_off((row, 0)), self._to_off((row, col)))
        self.cursor = (row, 0)
        self._changed()

    def _insert_arrow(self, name):
        row, col = self.cursor
        if name == "Left" and col > 0:
            self.cursor = (row, col - 1)
        elif name == "Left" and col == 0 and row > 0:
            self.cursor = (row - 1, len(self.lines[row - 1]))
        elif name == "Right" and col < len(self.lines[row]):
            self.cursor = (row, col + 1)
        elif name == "Right" and col == len(self.lines[row]) and row < len(self.lines) - 1:
            self.cursor = (row + 1, 0)
        elif name == "Up" and row > 0:
            self.cursor = (row - 1, min(col, len(self.lines[row - 1])))
        elif name == "Down" and row < len(self.lines) - 1:
            self.cursor = (row + 1, min(col, len(self.lines[row + 1])))
        self._changed()

    # ------------------------------------------------------------------ #
    # Modo visual                                                        #
    # ------------------------------------------------------------------ #

    def _enter_visual(self, kind):
        self.mode = {"char": "visual", "line": "visual-line", "block": "visual-block"}[kind]
        self._vis_anchor = self.cursor
        self.count = ""
        self._changed()

    def _visual_range(self):
        """Devuelve el rango de la selección según el tipo visual."""
        a = self._vis_anchor
        b = self.cursor
        if self.mode == "visual-line":
            r1, r2 = min(a[0], b[0]), max(a[0], b[0])
            o1 = self._to_off((r1, 0))
            if r2 == len(self.lines) - 1:
                o2 = len(self._text())
            else:
                o2 = self._to_off((r2 + 1, 0))
            return "line", r1, r2, o1, o2
        if self.mode == "visual-block":
            r1, r2 = min(a[0], b[0]), max(a[0], b[0])
            c1, c2 = min(a[1], b[1]), max(a[1], b[1])
            return "block", r1, r2, (c1, c2), None
        if a <= b:
            o1 = self._to_off(a)
            o2 = self._to_off(b) + 1  # visual incluye el carácter del cursor
        else:
            o1 = self._to_off(b)
            o2 = self._to_off(a) + 1
        return "char", a, b, o1, o2

    def _visual_operator(self, op):
        kind, r1, r2, o1, o2 = self._visual_range()
        if kind == "block":
            c1, c2 = o1
            self._push_undo()
            if op == "y":
                lines = []
                for r in range(r1, r2 + 1):
                    line = self.lines[r]
                    e = min(c2, len(line))
                    lines.append(line[c1:e] if c1 < e else "")
                self.reg = {"text": "\n".join(lines), "kind": "char"}
            elif op in ("d", "x", "c"):
                for r in range(r1, r2 + 1):
                    line = self.lines[r]
                    e = min(c2, len(line))
                    if c1 < e:
                        self.lines[r] = line[:c1] + line[e:]
                self.cursor = (r1, c1)
                if op == "c":
                    self._enter_insert()
            elif op == "~":
                for r in range(r1, r2 + 1):
                    line = self.lines[r]
                    e = min(c2, len(line))
                    if c1 < e:
                        self.lines[r] = line[:c1] + self._swapcase(line[c1:e]) + line[e:]
        else:
            self._push_undo()
            if op == "y":
                text = self._text()[o1:o2]
                if kind == "line":
                    text += "\n"
                self.reg = {"text": text, "kind": "line" if kind == "line" else "char"}
            elif op in ("d", "x", "c"):
                self._delete_range(o1, o2)
                if kind == "char":
                    self.cursor = self._clamp(self._to_pos(o1))
                else:
                    self.cursor = (min(r1, len(self.lines) - 1), 0)
                if op == "c":
                    self._enter_insert()
            elif op == "~":
                text = self._text()
                new = text[:o1] + self._swapcase(text[o1:o2]) + text[o2:]
                self._set_buffer(new, self._to_pos(o1))
        self.mode = "normal"
        self.count = ""
        self._changed()

    def _block_insert(self, kind):
        """Inserción en modo visual-bloque (I: al inicio, A: al final del bloque)."""
        if self.mode != "visual-block":
            return
        r1 = min(self._vis_anchor[0], self.cursor[0])
        r2 = max(self._vis_anchor[0], self.cursor[0])
        c1 = min(self._vis_anchor[1], self.cursor[1])
        c2 = max(self._vis_anchor[1], self.cursor[1])
        self._block_rows = list(range(r1, r2 + 1))
        if kind == "I":
            self._block_col = c1
        else:
            # A: inserta justo después del bloque en cada línea.
            self._block_col = c2 + 1 if c2 > c1 else c1 + 1
        self._block_active = True
        self.mode = "insert"
        self._insert_pushed = False
        self._insert_chars = ""
        self._pending_normal_once = False
        self._push_undo()
        self.cursor = (r1, 0)
        self._changed()

    def _apply_block_insert(self):
        text = self._insert_chars
        if not text:
            return
        for r in self._block_rows:
            if r >= len(self.lines):
                break
            line = self.lines[r]
            col = min(self._block_col, len(line))
            self.lines[r] = line[:col] + text + line[col:]
        self._block_active = False
        self.cursor = self._clamp(self.cursor)

    # ------------------------------------------------------------------ #
    # Prompt (búsqueda y línea de comando)                               #
    # ------------------------------------------------------------------ #

    def _enter_prompt(self, kind):
        self.mode = kind
        self._prompt_text = ""
        self._pending_f = None
        self._changed()

    def _handle_prompt_key(self, name, char, mods):
        if CTRL in mods and name == "c":
            self.mode = "normal"
            self._changed()
            return
        if name == "Escape":
            self.mode = "normal"
            self._changed()
            return
        if name == "Return" or name == "KP_Enter":
            self._exec_prompt()
            return
        if name == "BackSpace":
            self._prompt_text = self._prompt_text[:-1]
            self._changed()
            return
        if name == "space":
            self._prompt_text += " "
            self._changed()
            return
        if char and char not in "\n\t":
            self._prompt_text += char
            self._changed()

    def _exec_prompt(self):
        mode = self.mode
        text = self._prompt_text
        self.mode = "normal"
        if mode == "search":
            self._do_search(text)
        else:
            self._exec_command(text)

    # ------------------------------------------------------------------ #
    # Búsqueda                                                           #
    # ------------------------------------------------------------------ #

    def _do_search(self, pattern):
        if not pattern:
            self._changed()
            return
        try:
            rx = re.compile(pattern)
        except re.error:
            self._message = "Patrón inválido"
            self._changed()
            return
        text = self._text()
        self.search_pattern = pattern
        self.search_matches = [(m.start(), m.end()) for m in rx.finditer(text)]
        self._search_dir = "b" if self._prompt_backward else "f"
        self._goto_next_search(forward=self._search_dir == "f")
        self._changed()

    def _goto_next_search(self, forward):
        if not self.search_pattern:
            self._message = "Sin búsqueda previa"
            self._changed()
            return
        text = self._text()
        cur_off = self._to_off(self.cursor)
        matches = self.search_matches
        if not matches:
            self._changed()
            return
        target = None
        if forward:
            for m in matches:
                if m[0] > cur_off:
                    target = m
                    break
            if target is None:
                target = matches[0]
        else:
            for m in reversed(matches):
                if m[1] < cur_off:
                    target = m
                    break
            if target is None:
                target = matches[-1]
        self.cursor = self._to_pos(target[0])
        self._changed()

    # ------------------------------------------------------------------ #
    # Línea de comando (:w, :q, ...)                                     #
    # ------------------------------------------------------------------ #

    def _exec_command(self, text):
        raw = text.strip()
        if not raw:
            self._changed()
            return
        cmd = raw.split()[0].lower()
        arg = raw[len(cmd):].strip()
        mapped = _APP_COMMANDS.get(cmd)
        if mapped == "save":
            self._message = "Guardado"
            self._changed()
            if self.ui is not None:
                self.ui.save_note()
        elif mapped == "quit":
            if self.ui is not None:
                self.ui.quit_app(save=True)
        elif mapped == "quit_force":
            if self.ui is not None:
                self.ui.quit_app(save=False)
        elif mapped == "quit_save":
            if self.ui is not None:
                self.ui.save_note()
                self.ui.quit_app(save=True)
        elif mapped == "new":
            if self.ui is not None:
                self.ui.new_note()
        elif mapped == "delete":
            if self.ui is not None:
                self.ui.delete_note()
        elif mapped == "rename":
            if self.ui is not None:
                self.ui.rename_note()
        elif cmd.startswith("q"):
            if self.ui is not None:
                self.ui.quit_app(save=False)
        elif cmd.startswith("e"):
            self._message = "Sin nota alterna"
            self._changed()
        else:
            self._message = f"Comando desconocido: :{cmd}"
            self._changed()
