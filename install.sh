#!/usr/bin/env bash
# Instalador de la aplicación Notas.
#
#   ./install.sh            instala (lanzador, .desktop y atajo global)
#   ./install.sh --uninstall  desinstala
#
# Instala:
#   - ~/.local/bin/note          (comando `note` en la terminal)
#   - ~/.local/share/applications/notas.desktop  (menú del escritorio)
#   - Atajo global Ctrl+Alt+N (solo en GNOME, vía gsettings)
#
# Requiere: python3 con PyGObject (GTK 4).

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="$PROJECT_DIR/bin/note"
BIN_TARGET="$HOME/.local/bin/note"
DESKTOP_SOURCE="$PROJECT_DIR/notas.desktop"
DESKTOP_TARGET="$HOME/.local/share/applications/notas.desktop"

# Clave de gsettings para el atajo global (GNOME).
GBUS="org.gnome.settings-daemon.plugins.media-keys"
GKEY_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/notas/"
SHORTCUT_BINDING="<Primary><Alt>n"

check_deps() {
    python3 - <<'PY' >/dev/null 2>&1 || true
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
PY
    if ! python3 -c 'import gi' >/dev/null 2>&1; then
        echo "Error: no se encuentra PyGObject. Instala python3-gi (o python3-gi-gtk4)." >&2
        exit 1
    fi
}

install_shortcut() {
    # El atajo solo se configura si hay un escritorio GNOME.
    if ! command -v gsettings >/dev/null 2>&1; then
        echo "  (gsettings no disponible; el atajo global se omite)"
        return
    fi

    # Añade la ruta de la tecla a la lista de atajos personalizados sin
    # perder los existentes. Se usa python3 (requisito de la app) para
    # manipular el array de gsettings con seguridad.
    local current new
    current="$(gsettings get "$GBUS" custom-keybindings 2>/dev/null || true)"
    new="$(NOTAS_GKEY="$GKEY_PATH" python3 -c '
import ast, os, sys
path = os.environ["NOTAS_GKEY"]
cur = sys.stdin.read().strip() or "[]"
items = ast.literal_eval(cur)
if not isinstance(items, list):
    items = []
if path not in items:
    items.append(path)
print(repr(items))
' <<<"$current")"
    gsettings set "$GBUS" custom-keybindings "$new" 2>/dev/null || true

    local key_path="$GBUS.custom-keybinding:$GKEY_PATH"
    gsettings set "$key_path" name "Notas" 2>/dev/null || true
    gsettings set "$key_path" command "$BIN_TARGET" 2>/dev/null || true
    gsettings set "$key_path" binding "$SHORTCUT_BINDING" 2>/dev/null || true
    echo "  Atajo global: Ctrl+Alt+N -> $BIN_TARGET"
}

uninstall_shortcut() {
    if ! command -v gsettings >/dev/null 2>&1; then
        return
    fi
    local current new
    current="$(gsettings get "$GBUS" custom-keybindings 2>/dev/null || true)"
    new="$(NOTAS_GKEY="$GKEY_PATH" python3 -c '
import ast, os, sys
path = os.environ["NOTAS_GKEY"]
cur = sys.stdin.read().strip() or "[]"
items = ast.literal_eval(cur)
if isinstance(items, list):
    items = [i for i in items if i != path]
print(repr(items))
' <<<"$current")"
    gsettings set "$GBUS" custom-keybindings "$new" 2>/dev/null || true
    gsettings reset-recursively "$GBUS.custom-keybinding:$GKEY_PATH" 2>/dev/null || true
    echo "  Atajo global eliminado"
}

do_install() {
    check_deps
    mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"

    ln -sf "$LAUNCHER" "$BIN_TARGET"
    echo "Lanzador: $BIN_TARGET"

    sed "s|@PROJECT_DIR@|$PROJECT_DIR|g" "$DESKTOP_SOURCE" > "$DESKTOP_TARGET"
    echo "Entrada de menú: $DESKTOP_TARGET"

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
    fi

    install_shortcut
    echo "Listo. Abre con: note  (o Ctrl+Alt+N)"
}

do_uninstall() {
    rm -f "$BIN_TARGET"
    echo "Eliminado: $BIN_TARGET"
    rm -f "$DESKTOP_TARGET"
    echo "Eliminado: $DESKTOP_TARGET"
    uninstall_shortcut
    echo "Desinstalado."
}

case "${1:-}" in
    --uninstall|-u) do_uninstall ;;
    --help|-h) sed -n '1,14p' "$0" ;;
    *) do_install ;;
esac
