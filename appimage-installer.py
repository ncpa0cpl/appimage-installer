#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = os.path.expanduser("~")
APPIMAGE_DIR = os.path.join(HOME, ".local/share/appimages")
SYMLINK_DIR = os.path.join(HOME, ".local/bin")
DESKTOP_DIR = os.path.join(HOME, ".local/share/applications")

DESKTOP_FILE_TEMPLATE = """
[Desktop Entry]
Name={app_name}
Exec={app_path}
Icon={icon_path}
Type=Application
Categories=Utility;
Terminal={terminal}
"""


def _read_embedded_terminal(appimage_path):
    """Return True if the AppImage's embedded .desktop sets Terminal=true.

    Terminal apps (TUIs) must be launched in a terminal, otherwise they fail
    silently when started from a launcher. Defaults to False if it can't be
    determined.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [str(appimage_path), "--appimage-extract", "*.desktop"],
                cwd=tmp,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            for desktop in Path(tmp).rglob("*.desktop"):
                for line in desktop.read_text(errors="ignore").splitlines():
                    if line.strip().lower().startswith("terminal="):
                        return line.split("=", 1)[1].strip().lower() == "true"
    except Exception:
        pass
    return False

class AppimageInstaller():
    _destination_path = None
    def __init__(self, source_path, app_name):
        self.source = Path(source_path).resolve()
        self.app_name = app_name
        if not self.source.exists():
            print(f"Error: File not found: {self.source}")
            raise FileNotFoundError
        
        # Create directories if they don't exist
        os.makedirs(APPIMAGE_DIR, exist_ok=True)
        os.makedirs(SYMLINK_DIR, exist_ok=True)
        os.makedirs(DESKTOP_DIR, exist_ok=True)
        
        # Check if ~/.local/bin is in PATH
        self._check_symlink_path()
        
    def _check_symlink_path(self):
        """Check if ~/.local/bin is in PATH and warn if not"""
        path_env = os.environ.get('PATH', '')
        if SYMLINK_DIR not in path_env:
            print(f"Warning: {SYMLINK_DIR} is not in your PATH.")
            print("Add this line to your ~/.zshrc:")
            print('export PATH="$HOME/.local/bin:$PATH"')

    
    @property
    def destination_path(self):
        if not self._destination_path:
            self._destination_path = self._move_appimage()
        return self._destination_path
    
    def _move_appimage(self):
        final_destination = Path(APPIMAGE_DIR) / self.source.name
        shutil.move(str(self.source), str(final_destination))
        os.chmod(final_destination, 0o755)
        self._destination_path = final_destination
        return final_destination
        
    def _update_symlink(self):
        symlink_path = Path(SYMLINK_DIR) / self.app_name
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        os.symlink(self.destination_path, symlink_path)
        
    def _create_desktop_file(self, icon_path=None):
        desktop_file_path = Path(DESKTOP_DIR) / f"{self.app_name}.desktop"

        icon_path = icon_path or "application-x-executable"
        terminal = _read_embedded_terminal(self.destination_path)
        desktop_content = DESKTOP_FILE_TEMPLATE.format(
            app_name=self.app_name,
            app_path=self.destination_path,
            icon_path=icon_path,
            terminal="true" if terminal else "false"
        )

        with open(desktop_file_path, "w") as f:
            f.write(desktop_content.strip())
        
        # Make desktop file executable
        os.chmod(desktop_file_path, 0o755)
        
    def install(self):
        self._move_appimage()
        print(f'AppImage moved to {self.destination_path}')
        
        self._update_symlink()
        print(f"Symlink created: {SYMLINK_DIR}/{self.app_name}")
        
        self._create_desktop_file()
        print(".desktop file created")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: appimage-installer.py <path_to_appimage> <app_name>")
        sys.exit(1)

    source_path = sys.argv[1]
    app_name = sys.argv[2]

    AppimageInstaller(source_path, app_name).install()
