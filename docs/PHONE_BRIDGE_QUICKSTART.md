# Phone Bridge Quickstart

This guide gets `Phone Bridge` mode running with the least friction.

## Goal

- Phone connects to Polar H10 over BLE.
- Phone forwards live data to your PC over Wi-Fi.
- HnH on PC receives that stream in `Phone Bridge` mode.
- `Phone Bridge` is optional, but can be more reliable when your PC's BLE stack is unstable.

## Before you start

- Use `Phone Bridge` if direct `PC BLE` mode is unreliable on your machine.
- Keep phone and PC on the same Wi-Fi network.
- Android 8.0+ is required by the reference app (`minSdk = 26`).

## Install the Android bridge app

Choose one route:

### A) Download prebuilt APK from GitHub Actions (recommended for most users)

1. Open the repo Actions tab and select workflow `android-bridge`.
2. Open the latest successful run for `main`.
3. Download artifact `PolarH10Bridge-debug-apk`.
4. Extract and copy `app-debug.apk` to your phone.
5. On Android, enable install from unknown sources for your file manager/browser.
6. Install the APK.

### B) Build locally from source

1. Open `Android Bridge App/PolarH10Bridge` in Android Studio.
2. Let Gradle sync finish.
3. Build and install Debug app on your Android phone.
   - CLI option: run `./gradlew assembleDebug` in that folder and install `app/build/outputs/apk/debug/app-debug.apk`.

## 1) PC setup (HnH)

1. Open HnH.
2. In the toolbar `Connection Mode`, select `Phone Bridge`.
3. Set `Host` to your phone's Wi-Fi IP (example: `192.168.1.42`).
4. Set `Port` to your bridge app port (default in HnH is `8765`).
5. Click `Connect`.

## 2) Phone setup

Use one of these options:

- Use the in-repo reference app (`PolarH10Bridge`) from the install section above.
- Or try an existing Android app first (fastest validation), then move to dedicated bridge app if it is not HnH-compatible.

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

Examples:

```json
{"type":"status","message":"Phone bridge connected to H10","connected":true,"battery":87}
{"type":"rr","timestamp_ms":1742879800123,"rr_ms":812}
{"type":"ecg","timestamp_ms":1742879800130,"sample_rate_hz":130,"samples_mv":[0.12,0.18,0.22]}
```

Notes:

- `type=status`: optional `battery` (0-100) is supported.
- `type=rr`: `rr_ms` (or `ibi_ms`) is consumed by HnH.
- `type=ecg`: `samples_mv` (or `samples`) list is consumed by HnH.

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
