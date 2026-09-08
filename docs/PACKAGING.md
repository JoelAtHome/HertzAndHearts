# Packaging Guide (Windows, macOS, Linux)

Current beta target: **1.0.0-beta.2** (Python package version: `1.0.0b2`).

CI still produces Windows, macOS, and Linux artifacts. **Windows** is the platform we develop and smoke-test. **macOS** and **Linux** packages are **best-effort** (not actively tested; platform-specific issues may not be fixed).

## Prerequisites

- Python 3.12
- platform build toolchain
- project dependencies installed

## Build Outputs

- Windows: `dist/Hertz-and-Hearts-<version>-windows-x64.zip`
- macOS: `dist/Hertz-and-Hearts-<version>-macos.zip`
- Linux: `dist/Hertz-and-Hearts-<version>-linux-x64.tar.gz`
- Windows installer: `installer_output/Hertz-and-Hearts-Windows-Setup-<version>.exe`

## Windows

```powershell
pwsh packaging/windows/build_windows_package.ps1
```

Optional installer:

- Install Inno Setup
- Run: `iscc /DMyAppVersion=1.0.0-beta.2 installer.iss`

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

On release events, the workflow uploads artifacts directly to the GitHub Release. Linux and macOS jobs stay enabled so those packages remain available; they are not a local release gate.

The Android phone bridge APK is **not** built in this repository. It is published from **[ECG-Phone-Bridge](https://github.com/JoelAtHome/ECG-Phone-Bridge)** (GitHub Actions workflow `android-bridge` and that repo’s Releases as `PolarH10Bridge-debug-<tag>.apk`). See `docs/PHONE_BRIDGE_QUICKSTART.md` and `Android Bridge App/README.md` for download links.
