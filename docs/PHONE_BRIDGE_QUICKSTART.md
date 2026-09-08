# Phone Bridge Quickstart

This guide gets `Phone Bridge` mode running with the least friction.

## Goal

- Phone connects to Polar H10 (or Feather) over BLE.
- Phone forwards live data to your PC over Wi-Fi.
- HnH on PC receives that stream in `Phone Bridge` mode.
- `Phone Bridge` is optional, but can be more reliable when your PC's BLE stack is unstable.

## Before you start

- Use `Phone Bridge` if direct `PC BLE` mode is unreliable on your machine.
- Keep phone and PC on the same Wi-Fi network.
- Android 8.0+ is required by the reference app (`minSdk = 26`).

## Install the Android bridge app

The bridge lives in a separate repo: **[ECG-Phone-Bridge](https://github.com/JoelAtHome/ECG-Phone-Bridge)**  
(local pointer: `Android Bridge App/README.md` in this repo).

Choose one route:

### A) Download prebuilt APK from GitHub Releases (recommended for most users)

1. Open [ECG-Phone-Bridge Releases](https://github.com/JoelAtHome/ECG-Phone-Bridge/releases).
2. Choose a recent release.
3. Download the published debug/release APK for PolarH10Bridge.
4. Copy it to your phone and install (enable install from unknown sources for your file manager or browser if Android asks).

### B) Download from GitHub Actions (bleeding-edge / not on a release yet)

1. Open the [ECG-Phone-Bridge Actions](https://github.com/JoelAtHome/ECG-Phone-Bridge/actions) tab.
2. Open the latest successful Android APK build on `main`.
3. Download the APK artifact from that run.
4. Extract and copy the APK to your phone, then install as above.

### C) Build locally from source

1. Clone or open [ECG-Phone-Bridge](https://github.com/JoelAtHome/ECG-Phone-Bridge) in Android Studio (the `PolarH10Bridge` project).
2. Let Gradle sync finish.
3. Build and install Debug app on your Android phone.
   - CLI option: run `./gradlew assembleDebug` in that folder and install `app/build/outputs/apk/debug/app-debug.apk`.

## 1) PC setup (HnH)

1. Open HnH.
2. In the toolbar `Connection Mode`, select `Phone Bridge`.
3. Click `Scan` (or `Find phones`) to discover bridges on the LAN, **or** set `Host` to your phone's Wi-Fi IP (example: `192.168.1.42`).
4. Set `Port` to your bridge app port (default in HnH is `8765`; discovery can fill this in).
5. Click `Connect`.

## 2) Phone setup

Use the ECG-Phone-Bridge Android app from the install section above.

### Required phone permissions/settings

- Bluetooth: enabled
- Location services: enabled (required on many Android versions for BLE scan)
- App permissions: Bluetooth + Nearby devices + Location (as requested)
- In app `Connection settings`, keep `Keep bridge active in background` enabled for best stability
- Disable battery optimization for the bridge app (prevents background dropouts on aggressive OEM firmware)
- Keep phone and PC on the same Wi-Fi network

### Background keep-alive behavior

- When background keep-alive is enabled and a bridge session is active, Android shows a persistent foreground notification.
- You can tap the notification to return to the app.
- Notification action `Stop background keep-alive` turns off keep-alive if you no longer need background streaming.
- This does not block normal phone use (calls, texts, other apps), but may increase battery use while active.

## 3) Network checks

- Confirm phone and PC are on same subnet (for example `192.168.1.x`).
- If connection fails, allow the port in Windows Firewall on the PC side if needed.
- Avoid guest Wi-Fi networks that block client-to-client traffic.

## 4) Minimal bridge protocol expected by HnH

HnH expects newline-delimited JSON (`NDJSON`), one JSON object per line.

**Shipping today** (required for live charts):

```json
{"type":"status","message":"Phone bridge connected to H10","connected":true,"battery":87}
{"type":"rr","timestamp_ms":1742879800123,"rr_ms":812}
{"type":"ecg","timestamp_ms":1742879800130,"sample_rate_hz":130,"samples_mv":[0.12,0.18,0.22]}
```

Notes:

- `type=status`: optional `battery` (0-100) is supported.
- `type=rr`: `rr_ms` (or `ibi_ms`) is consumed by HnH.
- `type=ecg`: `samples_mv` (or `samples`) list is consumed by HnH.
- On connect, HnH sends `client_info` with `pc_user`, `client_app: "hertz_and_hearts"`, and `client_version`.
- Discovery uses UDP probe prefix `HnH_PHONE_BRIDGE_DISCOVER_V1` on port **45124**.

**Coming next** (ignored safely until the phone emits them): `rmssd` snapshots, `session_control` / `session_state`, and discover fields `protocol` / `features` / `bridge_version`. See [ECG-Phone-Bridge PROTOCOL.md](https://github.com/JoelAtHome/ECG-Phone-Bridge/blob/main/docs/PROTOCOL.md) and [HOST_HANDOFF.md](https://github.com/JoelAtHome/ECG-Phone-Bridge/blob/main/docs/HOST_HANDOFF.md).

## 5) Smoke test sequence

1. Start bridge app on phone.
2. Verify bridge app reports BLE connected to H10.
3. In HnH, click `Connect` in `Phone Bridge` mode.
4. Confirm HnH status shows connected.
5. Confirm HR/RMSSD move within ~5-15 seconds.
6. Open ECG window; verify waveform if ECG packets are forwarded.

## 6) A/B reliability test

Run two 10-minute sessions:

- Session A: `PC BLE`
- Session B: `Phone Bridge`

Compare:

- disconnect count
- time-to-first-beat
- visible dropouts
- average RMSSD continuity

If `Phone Bridge` is clearly better, keep it as your routine mode.
