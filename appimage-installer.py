#!/usr/bin/env python3

import argparse
import builtins
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from functools import partial
from pathlib import Path

# Make output visible immediately, even in buffered or GUI-launched runs.
print = partial(builtins.print, flush=True)

# Install locations per mode. "user" installs for the current user only,
# "global" installs system-wide for all users (requires root).
USER_DIRS = {
    "appimages": "~/.local/share/appimages",
    "bin": "~/.local/bin",
    "desktop": "~/.local/share/applications",
    "icons": "~/.local/share/icons",
}

GLOBAL_DIRS = {
    "appimages": "/opt/appimages",
    "bin": "/usr/local/bin",
    "desktop": "/usr/share/applications",
    "icons": "/usr/share/icons",
}

DESKTOP_FILE_TEMPLATE = """
[Desktop Entry]
Name={app_name}
Exec={app_path}
Icon={icon_path}
Type=Application
Categories=Utility;
Terminal={terminal}
StartupNotify=true
StartupWMClass={startup_wm_class}
"""


def _appimage_extract(appimage_path, pattern, dest):
    """Run `--appimage-extract <pattern>` into dest. Returns True on success."""
    try:
        result = subprocess.run(
            [str(appimage_path), "--appimage-extract", pattern],
            cwd=dest,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _read_embedded_desktop(appimage_path):
    """Parse the AppImage's embedded .desktop file into a dict of keys.

    Used for the Terminal= setting and the Icon= name. Returns {} if it
    can't be determined.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            if not _appimage_extract(appimage_path, "*.desktop", tmp):
                return {}
            squashfs_root = Path(tmp) / "squashfs-root"
            for desktop in sorted(squashfs_root.rglob("*.desktop")):
                entries = {}
                for line in desktop.read_text(errors="ignore").splitlines():
                    line = line.strip()
                    if "=" in line and not line.startswith("["):
                        key, value = line.split("=", 1)
                        entries.setdefault(key.strip().lower(), value.strip())
                if entries:
                    return entries
    except Exception:
        pass
    return {}


def _png_size(path):
    """Return (width, height) of a PNG file, or None if unreadable."""
    try:
        with open(path, "rb") as f:
            header = f.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
    except Exception:
        return None


def _xpm_size(path):
    """Return (width, height) of an XPM file from its header, or None."""
    try:
        with open(path, "r", errors="ignore") as f:
            for _ in range(4):
                line = f.readline().strip().strip('"')
                parts = line.split()
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None


def _icon_rank(path):
    """Sort key: prefer larger raster icons, then vector, then xpm."""
    suffix = path.suffix.lower()
    if suffix == ".svg" or suffix == ".svgz":
        return (1, 0)
    if suffix == ".png":
        size = _png_size(path)
        return (0, -(size[0] * size[1]) if size else 0)
    if suffix == ".xpm":
        size = _xpm_size(path)
        return (2, -(size[0] * size[1]) if size else 0)
    return (3, 0)


class AppimageInstaller():
    _destination_path = None
    def __init__(self, source_path, app_name, global_install=False):
        self.source = Path(source_path).resolve() if source_path else None
        self.app_name = app_name
        self.global_install = global_install
        self._embedded = None

        if self.source is not None and not self.source.exists():
            print(f"Error: File not found: {self.source}")
            raise FileNotFoundError

        prefix = GLOBAL_DIRS if global_install else USER_DIRS
        self.dirs = {key: os.path.expanduser(path) for key, path in prefix.items()}

        if global_install and os.geteuid() != 0:
            print("Error: --global requires root privileges.")
            print("Run again with: sudo python3 appimage-installer.py ...")
            raise PermissionError

        if self.source is not None:
            # Create directories if they don't exist
            for directory in self.dirs.values():
                os.makedirs(directory, exist_ok=True)

            # Check if the symlink dir is in PATH
            self._check_symlink_path()

    def _check_symlink_path(self):
        """Check if the symlink dir is in PATH and warn if not"""
        path_env = os.environ.get('PATH', '')
        symlink_dir = self.dirs["bin"]
        if symlink_dir not in path_env:
            if self.global_install:
                print(f"Warning: {symlink_dir} is not in your PATH.")
            else:
                print(f"Warning: {symlink_dir} is not in your PATH.")
                print("Add this line to your ~/.zshrc:")
                print('export PATH="$HOME/.local/bin:$PATH"')

    def _existing_installation(self):
        """Return info about an existing installation of this app, or None.

        An app counts as installed if its .desktop file already exists. The
        Exec= line is parsed to locate the AppImage of the previous version.
        """
        desktop_file = Path(self.dirs["desktop"]) / f"{self.app_name}.desktop"
        if not desktop_file.exists():
            return None

        old_appimage = None
        try:
            for line in desktop_file.read_text(errors="ignore").splitlines():
                if line.strip().lower().startswith("exec="):
                    # Exec may carry arguments; the AppImage is the first token
                    token = line.split("=", 1)[1].strip().split()[0].strip('"')
                    if token:
                        old_appimage = Path(token)
                    break
        except Exception:
            pass
        return {"desktop": desktop_file, "appimage": old_appimage}

    def _remove_icon_artifacts(self):
        """Remove installed icon files for this app from the hicolor theme."""
        hicolor = Path(self.dirs["icons"]) / "hicolor"
        if not hicolor.exists():
            return

        allowed_suffixes = {".png", ".svg", ".svgz", ".xpm"}
        for icon_file in hicolor.rglob("*"):
            if (
                icon_file.is_file()
                and icon_file.stem == self.app_name
                and icon_file.suffix.lower() in allowed_suffixes
            ):
                icon_file.unlink()

    def _refresh_caches(self):
        """Refresh desktop/icon caches so menus and docks pick up changes."""
        desktop_dir = self.dirs["desktop"]
        icon_theme_dir = Path(self.dirs["icons"]) / "hicolor"

        for command in (
            ["update-desktop-database", desktop_dir],
            ["gtk-update-icon-cache", "-f", "-t", str(icon_theme_dir)],
        ):
            try:
                subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except FileNotFoundError:
                pass

    def remove(self):
        """Remove a previously installed AppImage and its integration files."""
        existing = self._existing_installation()
        if not existing:
            print(f"Error: {self.app_name} is not installed.")
            raise FileNotFoundError

        appimage_path = existing["appimage"]
        if not appimage_path:
            print(f"Error: {self.app_name} does not have a removable AppImage path.")
            print("Refusing to remove anything not installed as an AppImage.")
            raise ValueError

        if not appimage_path.name.lower().endswith(".appimage"):
            print(f"Error: Refusing to remove non-AppImage target: {appimage_path}")
            raise ValueError

        if appimage_path.exists():
            appimage_path.unlink()
            print(f"Removed AppImage: {appimage_path}")

        symlink_path = Path(self.dirs["bin"]) / self.app_name
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
            print(f"Removed symlink: {symlink_path}")

        if existing["desktop"].exists():
            existing["desktop"].unlink()
            print(f"Removed desktop file: {existing['desktop']}")

        self._remove_icon_artifacts()
        print(f"Removed icon entries for {self.app_name} (if present).")

        self._refresh_caches()
        print("Refreshed desktop/icon caches.")

        print(f"{self.app_name} removed {'globally' if self.global_install else 'for current user'}.")

    @property
    def destination_path(self):
        if not self._destination_path:
            self._destination_path = self._move_appimage()
        return self._destination_path

    def _move_appimage(self):
        final_destination = Path(self.dirs["appimages"]) / self.source.name

        # Source is already in place (e.g. re-running the installer on an
        # installed AppImage); nothing to copy.
        if self.source == final_destination:
            os.chmod(final_destination, 0o755)
            self._destination_path = final_destination
            return final_destination

        # Copy instead of move so the original AppImage is preserved.
        shutil.copy2(str(self.source), str(final_destination))
        os.chmod(final_destination, 0o755)
        self._destination_path = final_destination
        return final_destination

    def _update_symlink(self):
        symlink_path = Path(self.dirs["bin"]) / self.app_name
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        os.symlink(self.destination_path, symlink_path)

    def _embedded_desktop(self):
        """Read and cache the embedded .desktop entries of the AppImage."""
        if self._embedded is None:
            self._embedded = _read_embedded_desktop(self.destination_path)
        return self._embedded

    def _extract_icon_file(self):
        """Extract the embedded icon from the AppImage and return its path.

        Looks for the icon named by the embedded desktop file's Icon= key
        (plus .DirIcon as a fallback) among the extracted files and picks
        the best candidate (largest PNG preferred, then SVG, then XPM).
        Returns None if no icon can be found.
        """
        icon_name = self._embedded_desktop().get("icon", "").strip()
        icon_name = os.path.basename(icon_name)
        if icon_name.endswith((".png", ".svg", ".svgz", ".xpm")):
            icon_name = os.path.splitext(icon_name)[0]

        patterns = [".DirIcon"]
        if icon_name:
            patterns.append(f"*{icon_name}*")

        try:
            with tempfile.TemporaryDirectory() as tmp:
                squashfs_root = Path(tmp) / "squashfs-root"
                for pattern in patterns:
                    _appimage_extract(self.destination_path, pattern, tmp)

                # .DirIcon is often a symlink to the real icon file; extract
                # the target as well so we can use it.
                dir_icon = squashfs_root / ".DirIcon"
                if dir_icon.is_symlink():
                    target_name = Path(os.readlink(dir_icon)).name
                    if target_name and f"*{target_name}*" not in patterns:
                        _appimage_extract(self.destination_path, f"*{target_name}*", tmp)

                candidates = []
                if icon_name:
                    wanted = icon_name.lower()
                    candidates = [
                        p for p in squashfs_root.rglob("*")
                        if p.is_file()
                        and p.suffix.lower() in (".png", ".svg", ".svgz", ".xpm")
                        and p.stem.lower() == wanted
                    ]
                if not candidates:
                    # Fall back to .DirIcon itself (real file or symlink target)
                    for p in {dir_icon, dir_icon.resolve()}:
                        if p.is_file() and p.suffix.lower() in (".png", ".svg", ".svgz", ".xpm"):
                            candidates.append(p)

                if not candidates:
                    return None

                selected = sorted(candidates, key=_icon_rank)[0]
                # Copy the selected icon to a persistent temp file because the
                # TemporaryDirectory used for extraction is removed on exit.
                suffix = selected.suffix.lower() if selected.suffix else ""
                fd, temp_path = tempfile.mkstemp(prefix=f"{self.app_name}-icon-", suffix=suffix)
                os.close(fd)
                shutil.copy2(str(selected), temp_path)
                return Path(temp_path)
        except Exception:
            return None

    def _install_icon(self):
        """Install the AppImage's icon into the icon theme and return its name.

        The icon is copied into the hicolor theme (sized directory for
        rasters, scalable/ for SVGs) under the app's name, so launchers can
        resolve `Icon=<app_name>`. Returns None if no icon was found.
        """
        icon_file = None
        try:
            icon_file = self._extract_icon_file()
            if icon_file is None:
                print("Warning: could not find an embedded icon; using a fallback icon.")
                return None

            suffix = icon_file.suffix.lower()
            hicolor = Path(self.dirs["icons"]) / "hicolor"

            if suffix in (".svg", ".svgz"):
                icon_dir = hicolor / "scalable" / "apps"
                dest_name = f"{self.app_name}.svg"
            elif suffix == ".xpm":
                size = _xpm_size(icon_file) or (32, 32)
                icon_dir = hicolor / f"{size[0]}x{size[1]}" / "apps"
                dest_name = f"{self.app_name}.xpm"
            else:
                size = _png_size(icon_file) or (256, 256)
                icon_dir = hicolor / f"{size[0]}x{size[1]}" / "apps"
                dest_name = f"{self.app_name}.png"

            os.makedirs(icon_dir, exist_ok=True)
            icon_dest = icon_dir / dest_name
            shutil.copy(str(icon_file), str(icon_dest))
            os.chmod(icon_dest, 0o644)

            return self.app_name
        except Exception as exc:
            print(f"Warning: icon installation failed: {exc}")
            return None
        finally:
            try:
                if icon_file is not None and icon_file.exists():
                    icon_file.unlink()
            except Exception:
                pass

    def _create_desktop_file(self, icon_name=None):
        try:
            desktop_file_path = Path(self.dirs["desktop"]) / f"{self.app_name}.desktop"

            # Resolve Icon= via the installed theme entry; fall back to the
            # generic executable icon if none was found.
            icon_name = icon_name or "application-x-executable"
            terminal = self._embedded_desktop().get("terminal", "false")
            startup_wm_class = self._embedded_desktop().get("startupwmclass", self.app_name)
            desktop_content = DESKTOP_FILE_TEMPLATE.format(
                app_name=self.app_name,
                app_path=self.destination_path,
                icon_path=icon_name,
                terminal="true" if terminal.lower() == "true" else "false",
                startup_wm_class=startup_wm_class,
            )

            with open(desktop_file_path, "w") as f:
                f.write(desktop_content.strip())

            os.chmod(desktop_file_path, 0o644)
            self._refresh_caches()
        except Exception as exc:
            print(f"Error: failed to create desktop file: {exc}")
            raise

    def install(self):
        try:
            existing = self._existing_installation()

            print("Step: preparing AppImage copy...")
            self._move_appimage()
            if existing:
                print(f"Existing installation found, updating {self.app_name}...")
            print(f'AppImage moved to {self.destination_path}')

            # Remove the previous version's AppImage if it differs from the new
            # one (e.g. the new file is versioned differently)
            if existing:
                old_appimage = existing["appimage"]
                if (
                    old_appimage
                    and old_appimage.exists()
                    and old_appimage.resolve() != self.destination_path.resolve()
                ):
                    print("Step: removing previous installed copy...")
                    old_appimage.unlink()
                    print(f"Removed previous version: {old_appimage}")

            print("Step: creating symlink...")
            self._update_symlink()
            print(f"Symlink created: {self.dirs['bin']}/{self.app_name}")

            print("Step: installing icon...")
            icon_name = self._install_icon()
            if icon_name:
                print(f"Icon installed: {icon_name}")

            print("Step: writing desktop file...")
            self._create_desktop_file(icon_name)
            print(f".desktop file created: {self.dirs['desktop']}/{self.app_name}.desktop")

            if existing:
                print(f"{self.app_name} updated {'globally' if self.global_install else 'for current user'}.")
            else:
                print(f"Installed {'globally' if self.global_install else 'for current user'}.")
        except Exception as exc:
            print(f"Error: installation failed for {self.app_name}: {exc}")
            raise


def main():
    parser = argparse.ArgumentParser(
        description="Install an AppImage with launcher and CLI integration."
    )
    parser.add_argument(
        "--remove",
        metavar="APP_NAME",
        help="Remove a previously installed AppImage by name",
    )
    parser.add_argument("appimage", nargs="?", help="Path to the AppImage to install")
    parser.add_argument("app_name", nargs="?", help="Name to install the app as")
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Install for all users (requires root). Installs to /opt/appimages, "
             "/usr/local/bin, /usr/share/applications and the system icon theme.",
    )
    args = parser.parse_args()

    try:
        print("Starting AppImage installer...")
        if args.remove:
            print(f"Removing installed AppImage: {args.remove}")
            print("Step: initializing remover...")
            AppimageInstaller(None, args.remove, args.global_install).remove()
        else:
            if not args.appimage or not args.app_name:
                parser.error("install requires <path_to_appimage> and <app_name>")
            print(f"Installing AppImage: {args.appimage} -> {args.app_name}")
            print("Step: initializing installer...")
            AppimageInstaller(args.appimage, args.app_name, args.global_install).install()
    except (FileNotFoundError, PermissionError) as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except Exception:
        print("Error: unexpected failure")
        traceback.print_exc()
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    main()
