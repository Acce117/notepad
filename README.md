# Notas

Aplicación pequeña de notas para Linux, de acceso rápido, con edición de
texto **estilo Vim** y soporte para **múltiples notas**.

- **Interfaz**: ventana GTK4 (Python + PyGObject).
- **Editor**: motor Vim propio (modos normal / insertar / visual / comando,
  búsqueda, contadores, deshacer/rehacer).
- **Almacenamiento**: cada nota es un archivo `.md` plano en
  `~/Documents/Notes` (configurable con `NOTAS_DIR`).
- **Acceso rápido**: comando `note` en la terminal y atajo global
  `Ctrl+Alt+N`. Instancia única: si ya está abierta, se trae al frente.

## Requisitos

- Python 3.10+ con PyGObject y GTK4:
  - Debian/Ubuntu: `sudo apt install python3-gi gir1.2-gtk-4.0`
  - Fedora: `sudo dnf install python3-gobject gtk4`
- Nada más: no requiere Vim, nvim ni otras dependencias.

## Instalación

```bash
./install.sh
```

Esto instala:

1. El lanzador `~/.local/bin/note` (comando `note`).
2. La entrada de menú `notas.desktop` en `~/.local/share/applications`.
3. El atajo global `Ctrl+Alt+N` (solo en GNOME, vía `gsettings`).

Para desinstalar:

```bash
./install.sh --uninstall
```

## Uso

| Acción | Cómo |
| --- | --- |
| Abrir | `note` o `Ctrl+Alt+N` (si ya está abierta, la enfoca) |
| Crear nota | Botón `+`, `:new` en el editor, o crear un archivo `.md` en el directorio de notas |
| Renombrar | Botón de editar o `:rename` |
| Borrar | Botón de borrar o `:delete` |
| Guardar | `:w` (también se guarda solo al cambiar de nota y al cerrar) |
| Buscar | `/texto` (siguiente: `n`, anterior: `N`) |

## Comandos Vim soportados

**Modo normal** (por defecto):

- Movimientos: `h j k l`, `w e b ge`, `0 ^ $`, `gg G`, `f F t T ; ,`,
  `%`, `{ }`, con contadores (`3w`, `2j`).
- Edición: `i a A I o O`, `x X s S`, `d y c` (con movimientos, `dd yy cc`,
  `dw de db`, `d$ D C`), `p P`, `r R`, `J`, `~`, `u` (deshacer),
  `Ctrl-r` (rehacer), `.` (repite la última inserción).
- Visual: `v` (carácter), `V` (línea), `Ctrl-v` (bloque), `y d c x ~ o`.
- Buscar: `/patrón`, `?patrón`, `n`, `N`.
- Línea de comando `:`: `w`, `q`, `q!`, `wq`, `new`, `delete`, `rename`.

**Modo insertar**: escribir, `Esc`/`Ctrl-[` para volver a normal,
`Ctrl-w` (borra palabra), `Ctrl-u` (borra hasta inicio de línea),
`Ctrl-o` (un comando normal puntual), flechas.

**Modo reemplazar**: `R` entra, sobreescribe caracteres.

## Directorio de notas

Por defecto `~/Documents/Notes` (carpeta Documents del sistema). Si prefieres
otra ubicación:

```bash
export NOTAS_DIR=~/mis-notas   # antes de lanzar `note`
```

Si el directorio está vacío, al abrir la app se crea automáticamente una
primera nota para poder escribir de inmediato.

## Estructura del proyecto

```
notepad/
├── app/
│   ├── main.py        # punto de entrada (Gtk.Application, instancia única)
│   ├── window.py      # ventana: barra lateral + editor + barra de estado
│   ├── vim_engine.py  # motor Vim (lógica pura, testeable sin pantalla)
│   ├── vim_editor.py  # vista GTK que renderiza el motor y captura teclas
│   ├── notes.py       # almacenamiento de notas en disco
│   └── style.css      # hoja de estilos
├── bin/note           # lanzador
├── notas.desktop      # plantilla de entrada de escritorio
├── install.sh         # instalador / desinstalador
└── tests/
    └── test_engine.py # pruebas unitarias del motor Vim
```

## Desarrollo y pruebas

Ejecutar sin instalar:

```bash
python3 app/main.py
```

Probar el motor Vim (no necesita pantalla):

```bash
python3 -m unittest discover -s tests
```

## Notas de diseño

- **El motor es un modelo puro**: `VimEngine` no conoce GTK; la vista
  (`VimEditor`) lo renderiza y la ventana (`NotasWindow`) actúa como su
  `ui`. Esto permite probar toda la lógica de edición con `unittest` sin
  abrir una ventana.
- **Subconjunto de Vim**: la implementación cubre las operaciones más
  usadas para tomar notas rápidas, verificadas contra el comportamiento de
  Vim real (p. ej. `cw` borra la palabra y el espacio posterior, `ge` va al
  final de la palabra estrictamente anterior, etc.).
