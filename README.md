# AppImage Installer

A simple Python script to install AppImages system-wide with proper integration for application launchers and CLI usage.

## Why?

I love using **ulauncher** to quickly find and launch applications, and I also enjoy running programs from the command line (like `code .`). This script makes AppImages work seamlessly with both:

- Creates `.desktop` files for launcher integration (ulauncher, rofi, etc.)
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


## What it does

1. Moves AppImage to `~/.local/share/appimages/`
2. Creates symlink in `~/.local/bin/` for CLI access (make sure this is on your `PATH`)
3. Creates `.desktop` file in `~/.local/share/applications/` for launcher integration
