# Stock Ubuntu Kiosk Provisioning

Use this path when you want a standard Ubuntu install and then configure Hertz & Hearts as a kiosk app.

## One-command setup

On the Ubuntu target machine:

```bash
cd /path/to/Hertz-and-Hearts
chmod +x scripts/provision_kiosk_stock_ubuntu.sh
./scripts/provision_kiosk_stock_ubuntu.sh
```

This script installs dependencies, clones/updates the repo, creates a venv, installs Hertz & Hearts, creates the launcher, and writes autostart config.
It also writes an app-menu launcher so you can relaunch Hertz & Hearts from the desktop app picker.

## Optional overrides

```bash
HNH_BRANCH=main \
HNH_REPO_URL=https://github.com/JoelAtHome/HertzAndHearts.git \
HNH_REPO_DIR="$HOME/apps/Hertz-and-Hearts" \
./scripts/provision_kiosk_stock_ubuntu.sh
```

## Desktop template

If you need to install autostart manually, use:

- `kiosk/stock-ubuntu/hnh.desktop.template`

Copy it to:

- `~/.config/autostart/hnh.desktop`

and replace `REPLACE_WITH_USERNAME`.

## Relaunch command

Use this command to relaunch manually:

```bash
~/.local/bin/hnh-kiosk-launch.sh
```
