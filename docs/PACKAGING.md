# Packaging Guide (Windows, macOS, Linux)

Current beta target: **1.0.0-beta.1** (Python package version: `1.0.0b1`).

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
- Run: `iscc /DMyAppVersion=1.0.0-beta.1 installer.iss`

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

To attach (or re-attach) the APK without cutting a new release: run **Actions → android-bridge → Run workflow**, set **upload_to_release_tag** to an **already published** release tag. Leave that field empty for a build-only run (APK stays as the workflow artifact).
