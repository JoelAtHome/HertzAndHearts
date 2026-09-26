# Phone Bridge Quickstart

This guide gets `Phone Bridge` mode running with the least friction.

## Goal

- Phone connects to Polar H10 (or Feather) over BLE.
- Phone forwards live data to your PC over Wi-Fi.
- HnH on PC receives that stream in `Phone Bridge` mode.
- `Phone Bridge` is the only path in the HnH toolbar. Direct `PC BLE` code remains in the repo but is not selectable.

## Before you start

- The desktop app always starts in `Phone Bridge`. A saved `PC BLE` preference is rewritten so it cannot reconnect on its own.
- The patient breathing pacer lives on the phone. HnH does not show a PC pacer.
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

1. Open HnH. It starts in `Phone Bridge` (there is no connection-mode dropdown).
2. Click `Scan` to discover bridges on the LAN, **or** set `Host` to your phone's Wi-Fi IP (example: `192.168.1.42`).
3. Set `Port` to your bridge app port (default in HnH is `8765`; discovery can fill this in).
4. Click `Connect`.

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
- `type=ecg`: `samples_mv` (or `samples`) is consumed by HnH. `sample_rate_hz` sets the ECG time base (Polar 130 Hz, Feather 250 Hz). Missing rate falls back to 130 Hz.
- On connect, HnH sends `client_info` with `pc_user`, `client_app: "hertz_and_hearts"`, and `client_version`.
- HnH also re-sends `client_info` on every Switch User / active profile change while linked (`pc_user` = subject profile name). Phone β.59+ may soft-match that to a Feather patient and show Tech Keep/Switch on the phone; HnH shows those `status` lines as a non-blocking banner (no second confirm on PC).
- Discovery uses UDP probe prefix `HnH_PHONE_BRIDGE_DISCOVER_V1` on port **45124**. Scan also TCP-probes the typed host and the last 4 successful IPs first (`~/.hnh_last_phone_bridge.json`).
- Official `type: rmssd` snapshots (phone-computed) appear in the side column as **Bridge RMSSD**. In Stream mode the phone sends those about every **30 s** (Record: on Stop); the phone UI may show a local preview sooner. That is a cross-check only — the live **RMSSD** chip and charts stay PC-computed.
- Soft preference: Stream or Record are both fine. The phone stays mode authority. HnH does not send `session_control`.
- **Feather lead-off (LOD):** when Phone Bridge edge-forwards MCU status with `use_leads_off` / `leads_off` (**β.68+**), HnH shows a sticky **Check electrodes** banner only when both are true (ignore `leads_off` when `use_leads_off` is false). Not Polar `sensor_quality`. Example:

```json
{"type":"status","message":"Feather lead-off","connected":true,"use_leads_off":true,"leads_off":true,"source_device":"FEATHER"}
```

  **β.69+:** while LOD is active the phone **stops** live NDJSON `ecg` (and ritual ECG buffering); Tech strip may still move. HnH ECG can pause until `leads_off:false` — that is expected, not a host bug. IBI stays MCU-quiet via the publish gate. Wire docs: [PROTOCOL.md §3.1](https://github.com/JoelAtHome/ECG-Phone-Bridge/blob/main/docs/PROTOCOL.md) and [FEATHER_BLE_GATT.md](https://github.com/JoelAtHome/ECG-Phone-Bridge/blob/main/docs/FEATHER_BLE_GATT.md). MCU detail: [FEATHER_BLE.md](https://github.com/JoelAtHome/ECG-Box/blob/main/docs/FEATHER_BLE.md). HnH does not invent contact from ECG SNR.
- **Saved HRV (Record on phone):** after Stop, the phone may push a durable package on connect (`delayed_push`), when you use Tech **Send HRV**, or when HnH requests it. HnH replies with `ritual_ack`, dedupes by phone `session_id`, and writes **Session History** (IBIs + bridge RMSSD + ECG as `session.edf` when present). A package that arrives while live charts are running is saved quietly — no mode flip.
- On connect, HnH also sends `ritual_request` with no `session_id` (newest unacked package, otherwise the newest). That no-id meaning stays until FlareTracker ships the same picker.
- While linked, **More → Saved recordings…** sends `ritual_list` and shows the phone's stored Record sessions (local time, RMSSD, duration, patient name when the phone has one, sent or pending). Pick a row to send `ritual_request` with that `session_id`. If the phone deleted it, HnH drops the row on `ritual_unavailable` and asks for the list again. Phones whose discover `features` omit `ritual_list` keep **More → Request saved HRV** (the no-id pull). If Scan has not reported features yet, the list is tried first and **Request latest** appears when the phone does not answer.
- User-facing copy says **HRV** / **saved HRV** — never “ritual” (wire types stay `ritual_*`).

**Still ignored / parked:** `session_control`, host–mode conflict UI, and other unknown `type` values. Discover fields `protocol` / `features` / `bridge_version` are accepted. See [ECG-Phone-Bridge PROTOCOL.md](https://github.com/JoelAtHome/ECG-Phone-Bridge/blob/main/docs/PROTOCOL.md) and [HOST_HANDOFF.md](https://github.com/JoelAtHome/ECG-Phone-Bridge/blob/main/docs/HOST_HANDOFF.md).

## 5) Smoke test sequence

1. Start bridge app on phone.
2. Verify bridge app reports BLE connected to H10.
3. In HnH, click `Connect` in `Phone Bridge` mode.
4. Confirm HnH status shows connected.
5. Confirm HR/RMSSD move within ~5-15 seconds.
6. Open ECG window; verify waveform if ECG packets are forwarded.
7. Optional saved-HRV check: phone **Record HRV** alone → Stop → connect HnH (or **More → Saved recordings…** and pick the row) → status mentions Session History → **More → Session History…** shows the row (ECG in **More → Session Replay…** when the package included it).

## 6) Reliability notes

`PC BLE` is not in the toolbar. Compare a Phone Bridge session against an older build only if you still need that history:

- disconnect count
- time-to-first-beat
- visible dropouts
- average RMSSD continuity

## If Connect fails after charts freeze or you restart HnH

The phone holds **one** PC TCP session. Recording on the phone can keep running even when the PC link is wedged (that is why a phone-only session can still land in FlareTracker later).

1. Force-stop or swipe away the phone bridge app, then open it again.
2. Confirm it is still connected to the strap.
3. In HnH, click `Connect` again.

Restarting HnH alone is not enough if the phone never saw the old PC socket close. After a Phone Bridge app update that **replaces** on a new inbound connection, a second Connect from HnH should steal the slot without cycling the phone.
