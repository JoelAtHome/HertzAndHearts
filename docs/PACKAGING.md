# Packaging Guide (Windows, macOS, Linux)

Current beta target: **1.0.0-beta** (Python package version: `1.0.0b0`).

## Prerequisites

- Python 3.12
- platform build toolchain
- project dependencies installed

## Build Outputs

- Windows: `dist/Hertz-and-Hearts-windows-x64.zip`
- macOS: `dist/Hertz-and-Hearts-macos.zip`
- Linux: `dist/Hertz-and-Hearts-linux-x64.tar.gz`

## Windows

```powershell
pwsh packaging/windows/build_windows_package.ps1
```

Optional installer:

- Install Inno Setup
- Run: `iscc /DMyAppVersion=1.0.0-beta installer.iss`

## macOS

```bash
bash packaging/macos/build_macos_package.sh
```

## Linux

```bash
bash packaging/linux/build_linux_package.sh
```

## CI Packaging

The GitHub Actions workflow `.github/workflows/build.yml` builds packages on:

- Ubuntu 24.04
- Windows 2022
- macOS 14

On release events, the workflow uploads artifacts directly to the GitHub Release.

The **android-bridge** workflow (`.github/workflows/android-bridge.yml`) also runs on **`release` (published)** and attaches **`PolarH10Bridge-debug-<tag>.apk`** to the same release, so the phone bridge download stays alongside the desktop packages.
