# AppImage Installer

A simple Python script to install AppImages with proper integration for application launchers and CLI usage — either for the current user or globally for all users.

## Why?

I love using **ulauncher** to quickly find and launch applications, and I also enjoy running programs from the command line (like `code .`). This script makes AppImages work seamlessly with both:

- Creates `.desktop` files for launcher integration (ulauncher, rofi, etc.)
- Extracts the AppImage's embedded icon and installs it into the hicolor icon theme so the launcher shows the app's real icon
- Refreshes desktop/icon caches after install/remove so menus and docks pick up changes
- Creates CLI symlinks so you can run apps from terminal
- Organizes AppImages in `~/.local/share/appimages/`
- Honors each AppImage's own `Terminal=` setting so terminal apps (TUIs) launch correctly

## Usage

```bash
    python3 appimage-installer.py <path_to_appimage> <app_name>
```

or install it on the path with

```
make install
```

### Global install (all users)

```bash
    sudo python3 appimage-installer.py <path_to_appimage> <app_name> --global
```

### Remove an installed AppImage

```bash
    python3 appimage-installer.py --remove <app_name>
```

To remove a globally installed AppImage:

```bash
    sudo python3 appimage-installer.py --remove <app_name> --global
```

## What it does

### User install (default)

1. Copies AppImage to `~/.local/share/appimages/` (the original file is kept)
2. Creates symlink in `~/.local/bin/` for CLI access (make sure this is on your `PATH`)
3. Extracts the embedded icon and installs it to `~/.local/share/icons/hicolor/`
4. Creates `.desktop` file in `~/.local/share/applications/` for launcher integration
5. Refreshes the desktop and icon caches

### Global install (`--global`, requires root)

1. Copies AppImage to `/opt/appimages/` (the original file is kept)
2. Creates symlink in `/usr/local/bin/` for CLI access (all users)
3. Extracts the embedded icon and installs it to `/usr/share/icons/hicolor/`
4. Creates `.desktop` file in `/usr/share/applications/` for launcher integration
5. Refreshes the desktop and icon caches

If the AppImage has no usable embedded icon, the `.desktop` file falls back to the generic `application-x-executable` icon.

### Updates

Running the installer again for an app that is already installed (its `.desktop` file exists) performs an **update**: the new AppImage replaces the old one, the previous version's file is removed if the new AppImage has a different filename, and the symlink, icon, and `.desktop` entry are refreshed.

### Remove behavior

The `--remove` option only uninstalls apps that were installed as AppImages by this script. It checks the recorded `Exec=` target in the `.desktop` file and refuses to remove anything unless the target ends with `.AppImage`.

The installer also sets `StartupWMClass` in the `.desktop` file when possible, which helps GNOME-based docks and menus associate the running window with the launcher icon.
