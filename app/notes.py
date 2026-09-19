# -*- coding: utf-8 -*-
"""Almacenamiento de las notas en el sistema de archivos.

Cada nota es un archivo `.md` plano dentro de un directorio configurable
(p. ej. `~/Documents/Notes`). La clase `Notes` es la única capa que toca
el disco; la ventana y el motor Vim trabajan siempre a través de ella.
"""

import os
import re
import subprocess
from datetime import datetime


def _documents_dir():
    """Directorio 'Documents' del sistema, vía xdg-user-dir si está disponible."""
    try:
        out = subprocess.run(
            ["xdg-user-dir", "DOCUMENTS"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        if out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def default_notes_dir():
    """Directorio por defecto: la variable NOTAS_DIR o ~/Documents/Notes."""
    env = os.environ.get("NOTAS_DIR")
    if env:
        return os.path.expanduser(env)
    return os.path.join(_documents_dir(), "Notes")


class Notes:
    """Gestión de archivos de nota en un directorio."""

    def __init__(self, directory=None):
        self.directory = directory or default_notes_dir()

    def ensure(self):
        """Crea el directorio de notas si no existe."""
        os.makedirs(self.directory, exist_ok=True)

    def path(self, stem):
        """Ruta completa de una nota por su nombre (sin extensión)."""
        return os.path.join(self.directory, stem + ".md")

    def list(self):
        """Nombres de todas las notas (sin extensión), ordenados."""
        self.ensure()
        if not os.path.isdir(self.directory):
            return []
        names = []
        for entry in os.listdir(self.directory):
            if entry.endswith(".md"):
                names.append(entry[:-3])
        return sorted(names)

    def read(self, stem):
        """Contenido de una nota como texto."""
        path = self.path(stem)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def write(self, stem, text):
        """Guarda el contenido de una nota."""
        self.ensure()
        with open(self.path(stem), "w", encoding="utf-8") as f:
            f.write(text)

    def _sanitize(self, name):
        """Limpia un nombre propuesto: sin separadores de ruta ni extensión."""
        name = name.strip()
        name = re.sub(r"[\r\n\t/\\]+", "", name)
        if name.endswith(".md"):
            name = name[:-3]
        return name

    def _unique(self, stem):
        """Asegura un nombre libre añadiendo -2, -3, ... si existe."""
        candidate = stem
        n = 2
        while os.path.exists(self.path(candidate)):
            candidate = f"{stem}-{n}"
            n += 1
        return candidate

    def create(self, name=None):
        """Crea una nota nueva y devuelve su nombre (con nombre único)."""
        self.ensure()
        if not name:
            name = datetime.now().strftime("nota-%Y%m%d-%H%M%S")
        stem = self._sanitize(name) or "nota"
        stem = self._unique(stem)
        if not os.path.exists(self.path(stem)):
            self.write(stem, "")
        return stem

    def delete(self, stem):
        """Borra una nota del disco."""
        path = self.path(stem)
        if os.path.exists(path):
            os.remove(path)

    def rename(self, old, new):
        """Renombra una nota. Devuelve el nuevo nombre o None si falla."""
        new = self._sanitize(new)
        if not new or new == old:
            return None
        new = self._unique(new)
        if not os.path.exists(self.path(old)):
            return None
        os.rename(self.path(old), self.path(new))
        return new
