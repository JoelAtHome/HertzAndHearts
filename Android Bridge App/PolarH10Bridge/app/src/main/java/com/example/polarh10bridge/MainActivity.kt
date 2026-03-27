package com.example.polarh10bridge

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.example.polarh10bridge.ui.theme.PolarH10BridgeTheme
import com.polar.androidcommunications.api.ble.model.DisInfo
import com.polar.sdk.api.PolarBleApi
import com.polar.sdk.api.PolarBleApiCallback
import com.polar.sdk.api.PolarBleApiDefaultImpl
import com.polar.sdk.api.model.PolarDeviceInfo
import com.polar.sdk.api.model.PolarEcgData
import com.polar.sdk.api.model.PolarHealthThermometerData
import com.polar.sdk.api.model.PolarSensorSetting
import io.reactivex.rxjava3.android.schedulers.AndroidSchedulers
import io.reactivex.rxjava3.disposables.CompositeDisposable
import io.reactivex.rxjava3.disposables.Disposable
import io.reactivex.rxjava3.schedulers.Schedulers
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.Locale
import java.util.concurrent.Executors

private val BannerRed = Color(0xFFC1121F)
private val UiWhite = Color.White
private val TextDark = Color(0xFF1A1A1A)

/** UDP port: Hertz & Hearts broadcasts here; we reply so the PC can find this phone. */
private const val PHONE_UDP_DISCOVERY_PORT = 45124

private const val PHONE_UDP_DISCOVER_PREFIX = "HnH_PHONE_BRIDGE_DISCOVER_V1"
private const val BLE_ROW_STALE_MS = 5_000L
private const val BLE_ROW_PRUNE_INTERVAL_MS = 1_000L
private const val BLE_RSSI_RESUBSCRIBE_MS = 1_500L
private const val BLE_RSSI_SCAN_WINDOW_MS = 1_000L

private data class BleDeviceRow(
    val deviceId: String,
    val address: String,
    val displayName: String,
    val rssi: Int,
    val lastSeenElapsedMs: Long,
)

private fun normBleAddr(s: String): String = s.trim().lowercase().replace(":", "")

private fun looksLikeBleMac(s: String): Boolean {
    val t = s.trim()
    return t.contains(':') && t.length >= 12
}

private fun samePhysicalBleRow(row: BleDeviceRow, info: PolarDeviceInfo): Boolean {
    if (row.deviceId.equals(info.deviceId, ignoreCase = true)) return true
    val ra = normBleAddr(row.address)
    val ia = normBleAddr(info.address)
    if (ra.length >= 8 && ia.length >= 8 && ra == ia) return true
    val rid = normBleAddr(row.deviceId)
    val iid = normBleAddr(info.deviceId)
    if (ia.isNotEmpty() && rid == ia) return true
    if (ra.isNotEmpty() && iid == ra) return true
    return false
}

private fun mergePolarScanRow(row: BleDeviceRow, info: PolarDeviceInfo): BleDeviceRow {
    val rssi = maxOf(row.rssi, info.rssi)
    val displayName =
        when {
            info.rssi > row.rssi && info.name.isNotBlank() -> info.name.trim()
            row.displayName.isNotBlank() -> row.displayName
            else -> info.name.ifBlank { "Polar device" }
        }
    val deviceId = preferredPolarConnectId(row.deviceId, info.deviceId)
    val address =
        when {
            info.address.isNotBlank() -> info.address
            else -> row.address
        }
    return BleDeviceRow(
        deviceId = deviceId,
        address = address,
        displayName = displayName,
        rssi = rssi,
        lastSeenElapsedMs = SystemClock.elapsedRealtime(),
    )
}

private fun preferredPolarConnectId(a: String, b: String): String {
    val aMac = looksLikeBleMac(a)
    val bMac = looksLikeBleMac(b)
    return when {
        !aMac && bMac -> a
        aMac && !bMac -> b
        else -> b
    }
}

private fun connectedSensorSingleLine(name: String, deviceId: String): String {
    val n = name.trim()
    val id = deviceId.trim()
    if (n.isEmpty()) return id.ifEmpty { "Sensor" }
    if (id.isEmpty()) return n
    if (n.equals(id, ignoreCase = true)) return n
    val nu = n.uppercase(Locale.US)
    val iu = id.uppercase(Locale.US)
    if (nu.endsWith(iu)) return n.trimEnd()
    if (nu.contains(iu)) return n
    return n
}

private data class BridgeScreenState(
    val bleDialogVisible: Boolean = false,
    val bleScanning: Boolean = false,
    val bleRows: List<BleDeviceRow> = emptyList(),
    val bleSelectedId: String? = null,
    val bleConnecting: Boolean = false,
    val sensorConnected: Boolean = false,
    val connectedSensorName: String = "",
    val connectedSensorId: String = "",
    val connectedSensorAddress: String = "",
    val connectedSensorRssi: Int? = null,
    val phoneWifiIpv4: String? = null,
    /** Outbound TCP session: PC connected to this phone's bridge port. */
    val pcBridgeConnected: Boolean = false,
    val pcBridgeIp: String? = null,
)

class MainActivity : ComponentActivity() {
    private lateinit var polarApi: PolarBleApi
    private val disposables = CompositeDisposable()
    private val bridgeExecutor = Executors.newSingleThreadExecutor()
    private val discoveryExecutor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())

    private var rrStreamingStarted = false
    private var ecgStreamingStarted = false

    private var hrDisposable: io.reactivex.rxjava3.disposables.Disposable? = null
    private var ecgDisposable: io.reactivex.rxjava3.disposables.Disposable? = null
    private var bleSearchDisposable: Disposable? = null
    private var bleRssiMonitorDisposable: Disposable? = null

    private val writerLock = Any()

    @Volatile
    private var bridgeWriter: java.io.PrintWriter? = null
    private var bridgeClient: Socket? = null

    private val discoverySocketLock = Any()
    @Volatile
    private var udpDiscoverySocket: DatagramSocket? = null

    private val screenState = mutableStateOf(BridgeScreenState())

    private val bleScanStopRunnable = Runnable { stopBleScan() }
    private val bleRssiResubscribeRunnable =
        object : Runnable {
            override fun run() {
                val state = screenState.value
                if (!state.sensorConnected) return
                if (state.bleScanning) {
                    mainHandler.postDelayed(this, BLE_RSSI_RESUBSCRIBE_MS)
                    return
                }
                stopConnectedRssiMonitor()
                startConnectedRssiMonitor()
                mainHandler.postDelayed({ stopConnectedRssiMonitor() }, BLE_RSSI_SCAN_WINDOW_MS)
                mainHandler.postDelayed(this, BLE_RSSI_RESUBSCRIBE_MS)
            }
        }
    private val bleRowPruneRunnable =
        object : Runnable {
            override fun run() {
                if (!screenState.value.bleScanning) return
                pruneStaleBleRows()
                mainHandler.postDelayed(this, BLE_ROW_PRUNE_INTERVAL_MS)
            }
        }

    private fun pruneStaleBleRows() {
        val now = SystemClock.elapsedRealtime()
        updateScreen { current ->
            val pruned = current.bleRows.filter { now - it.lastSeenElapsedMs <= BLE_ROW_STALE_MS }
            val selected =
                current.bleSelectedId
                    ?.takeIf { id -> pruned.any { it.deviceId == id } }
            current.copy(bleRows = pruned, bleSelectedId = selected)
        }
    }

    private fun updateScreen(copy: (BridgeScreenState) -> BridgeScreenState) {
        mainHandler.post { screenState.value = copy(screenState.value) }
    }

    private fun sendBridgeJsonLine(json: String) {
        val w = bridgeWriter ?: return
        synchronized(writerLock) {
            try {
                w.println(json)
            } catch (e: Exception) {
                Log.e("HnHBridge", "bridge write failed", e)
            }
        }
    }

    private fun extractEcgMillivolts(ecgData: PolarEcgData): List<Float> {
        val out = ArrayList<Float>(ecgData.samples.size)
        for (sample in ecgData.samples) {
            try {
                val cls = sample.javaClass

                val uvValue: Number? = run {
                    val candidates = arrayOf("voltage", "microVolts", "uV", "uv", "value")
                    for (name in candidates) {
                        try {
                            val f = cls.getDeclaredField(name)
                            f.isAccessible = true
                            val v = f.get(sample)
                            if (v is Number) return@run v
                        } catch (_: Exception) {
                        }
                    }
                    null
                }

                if (uvValue != null) {
                    out.add(uvValue.toFloat() / 1000f)
                    continue
                }

                val m = Regex("-?\\d+").find(sample.toString())
                if (m != null) {
                    out.add(m.value.toFloat() / 1000f)
                }
            } catch (_: Exception) {
            }
        }
        return out
    }

    private fun stopBleScan() {
        mainHandler.removeCallbacks(bleScanStopRunnable)
        mainHandler.removeCallbacks(bleRowPruneRunnable)
        bleSearchDisposable?.dispose()
        bleSearchDisposable = null
        updateScreen { it.copy(bleScanning = false) }
    }

    private fun startConnectedRssiMonitor() {
        val state = screenState.value
        if (!state.sensorConnected) return
        val connectedId = state.connectedSensorId
        val connectedAddress = state.connectedSensorAddress
        val connectedName = state.connectedSensorName
        if (connectedId.isEmpty() && connectedAddress.isEmpty() && connectedName.isEmpty()) return
        if (bleRssiMonitorDisposable?.isDisposed == false) return

        val connectedRow =
            BleDeviceRow(
                deviceId = connectedId,
                address = connectedAddress,
                displayName = connectedName,
                rssi = Int.MIN_VALUE,
                lastSeenElapsedMs = SystemClock.elapsedRealtime(),
            )
        try {
            bleRssiMonitorDisposable = polarApi.searchForDevice()
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(
                    { info ->
                        if (samePhysicalBleRow(connectedRow, info) ||
                            sameConnectedDevice(connectedId, connectedAddress, connectedName, info)
                        ) {
                            updateScreen { current ->
                                if (!current.sensorConnected) return@updateScreen current
                                current.copy(connectedSensorRssi = info.rssi)
                            }
                        }
                    },
                    { err -> Log.d("HnHBridge", "RSSI monitor stopped: ${err.message}") },
                )
        } catch (e: Exception) {
            Log.d("HnHBridge", "RSSI monitor unavailable: ${e.message}")
        }
    }

    private fun stopConnectedRssiMonitor() {
        bleRssiMonitorDisposable?.dispose()
        bleRssiMonitorDisposable = null
    }

    private fun stopConnectedRssiPolling() {
        mainHandler.removeCallbacks(bleRssiResubscribeRunnable)
        stopConnectedRssiMonitor()
    }

    private fun sameConnectedDevice(
        connectedId: String,
        connectedAddress: String,
        connectedName: String,
        info: PolarDeviceInfo,
    ): Boolean {
        if (connectedId.equals(info.deviceId, ignoreCase = true)) return true
        if (connectedAddress.equals(info.address, ignoreCase = true) && connectedAddress.isNotBlank()) return true
        val cid = normBleAddr(connectedId)
        val cad = normBleAddr(connectedAddress)
        val iid = normBleAddr(info.deviceId)
        val iad = normBleAddr(info.address)
        if ((cid.isNotEmpty() && cid == iid) || (cid.isNotEmpty() && cid == iad)) return true
        if ((cad.isNotEmpty() && cad == iid) || (cad.isNotEmpty() && cad == iad)) return true
        return connectedName.isNotBlank() &&
            info.name.isNotBlank() &&
            connectedName.equals(info.name, ignoreCase = true)
    }

    private fun scheduleBleScanAutoStop() {
        mainHandler.removeCallbacks(bleScanStopRunnable)
        mainHandler.postDelayed(bleScanStopRunnable, 12_000L)
    }

    private fun beginSensorScan() {
        mainHandler.removeCallbacks(bleScanStopRunnable)
        mainHandler.removeCallbacks(bleRowPruneRunnable)
        stopConnectedRssiPolling()

        bleSearchDisposable?.dispose()
        bleSearchDisposable = null

        updateScreen {
            it.copy(
                bleDialogVisible = true,
                bleScanning = true,
                bleRows = emptyList(),
                bleSelectedId = null,
                bleConnecting = false,
            )
        }

        try {
            bleSearchDisposable = polarApi.searchForDevice()
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(
                    { info: PolarDeviceInfo ->
                        val now = SystemClock.elapsedRealtime()
                        val oldRows = screenState.value.bleRows
                        val oldCount = oldRows.size
                        val rows =
                            oldRows
                                .filter { now - it.lastSeenElapsedMs <= BLE_ROW_STALE_MS }
                                .toMutableList()
                        val idx = rows.indexOfFirst { samePhysicalBleRow(it, info) }
                        var sel = screenState.value.bleSelectedId
                        if (idx >= 0) {
                            val prev = rows[idx]
                            rows[idx] = mergePolarScanRow(prev, info)
                            if (sel != null &&
                                (sel == prev.deviceId || normBleAddr(sel) == normBleAddr(prev.address))
                            ) {
                                sel = rows[idx].deviceId
                            }
                        } else {
                            rows.add(
                                BleDeviceRow(
                                    deviceId = info.deviceId,
                                    address = info.address,
                                    displayName = info.name.ifBlank { "Polar device" },
                                    rssi = info.rssi,
                                    lastSeenElapsedMs = now,
                                ),
                            )
                        }
                        val newList = rows.sortedByDescending { it.rssi }
                        when {
                            newList.size == 1 -> sel = newList.first().deviceId
                            newList.size > 1 && oldCount == 1 -> sel = null
                            newList.isEmpty() -> sel = null
                        }
                        screenState.value =
                            screenState.value.copy(bleRows = newList, bleSelectedId = sel)
                    },
                    { err ->
                        Log.e("HnHBridge", "BLE search error", err)
                        stopBleScan()
                    },
                )
        } catch (e: Exception) {
            Log.e("HnHBridge", "BLE search start failed", e)
            updateScreen {
                it.copy(bleScanning = false)
            }
        }
        mainHandler.post(bleRowPruneRunnable)
        scheduleBleScanAutoStop()
    }

    private fun cancelSensorDialog() {
        stopBleScan()
        updateScreen {
            it.copy(
                bleDialogVisible = false,
                bleConnecting = false,
                bleSelectedId = null,
                bleRows = emptyList(),
            )
        }
        if (screenState.value.sensorConnected) {
            startConnectedRssiMonitor()
            mainHandler.removeCallbacks(bleRssiResubscribeRunnable)
            mainHandler.post(bleRssiResubscribeRunnable)
        }
    }

    private fun confirmSensorSelection() {
        val id = screenState.value.bleSelectedId ?: return
        val connectedId = screenState.value.connectedSensorId
        val isAlreadyConnectedSelection =
            screenState.value.sensorConnected &&
                connectedId.isNotEmpty() &&
                connectedId.equals(id, ignoreCase = true)

        if (isAlreadyConnectedSelection) {
            stopBleScan()
            updateScreen {
                it.copy(
                    bleDialogVisible = false,
                    bleConnecting = false,
                    bleRows = emptyList(),
                    bleSelectedId = null,
                )
            }
            return
        }

        stopBleScan()
        try {
            if (screenState.value.sensorConnected && connectedId.isNotEmpty()) {
                try {
                    polarApi.disconnectFromDevice(connectedId)
                } catch (e: Exception) {
                    Log.w("HnHBridge", "disconnect before sensor switch", e)
                }
            }
            polarApi.connectToDevice(id)
            updateScreen { it.copy(bleConnecting = true) }
        } catch (e: Exception) {
            Log.e("HnHBridge", "connectToDevice failed", e)
            updateScreen { it.copy(bleConnecting = false) }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            requestPermissions(
                arrayOf(
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT,
                ),
                1001,
            )
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            requestPermissions(
                arrayOf(Manifest.permission.ACCESS_FINE_LOCATION),
                1001,
            )
        } else {
            requestPermissions(
                arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION),
                1001,
            )
        }

        polarApi = PolarBleApiDefaultImpl.defaultImplementation(
            applicationContext,
            setOf(
                PolarBleApi.PolarBleSdkFeature.FEATURE_HR,
                PolarBleApi.PolarBleSdkFeature.FEATURE_BATTERY_INFO,
                PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_SDK_MODE,
                PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_ONLINE_STREAMING,
            ),
        )

        polarApi.setApiCallback(
            object : PolarBleApiCallback() {
                override fun deviceConnected(polarDeviceInfo: PolarDeviceInfo) {
                    Log.d("HnHBridge", "Polar connected: ${polarDeviceInfo.deviceId}")
                    val rssi =
                        screenState.value.bleRows.find {
                            it.deviceId == polarDeviceInfo.deviceId ||
                                normBleAddr(it.address) == normBleAddr(polarDeviceInfo.address) ||
                                normBleAddr(it.deviceId) == normBleAddr(polarDeviceInfo.deviceId)
                        }?.rssi
                    mainHandler.post {
                        val nameFromRow =
                            screenState.value.bleRows.find {
                                it.deviceId == polarDeviceInfo.deviceId ||
                                    normBleAddr(it.address) == normBleAddr(polarDeviceInfo.address)
                            }?.displayName
                        screenState.value =
                            screenState.value.copy(
                                bleDialogVisible = false,
                                bleConnecting = false,
                                sensorConnected = true,
                                connectedSensorName =
                                    polarDeviceInfo.name.ifBlank {
                                        nameFromRow ?: "Polar H10"
                                    },
                                connectedSensorId = polarDeviceInfo.deviceId,
                                connectedSensorAddress = polarDeviceInfo.address.orEmpty(),
                                connectedSensorRssi = rssi,
                                bleRows = emptyList(),
                                bleSelectedId = null,
                            )
                        startConnectedRssiMonitor()
                        mainHandler.removeCallbacks(bleRssiResubscribeRunnable)
                        mainHandler.post(bleRssiResubscribeRunnable)
                    }
                }

                override fun deviceDisconnected(polarDeviceInfo: PolarDeviceInfo) {
                    Log.d("HnHBridge", "Polar disconnected: ${polarDeviceInfo.deviceId}")

                    hrDisposable?.dispose()
                    hrDisposable = null
                    rrStreamingStarted = false

                    ecgDisposable?.dispose()
                    ecgDisposable = null
                    ecgStreamingStarted = false

                    mainHandler.post {
                        screenState.value =
                            screenState.value.copy(
                                sensorConnected = false,
                                connectedSensorName = "",
                                connectedSensorId = "",
                                connectedSensorAddress = "",
                                connectedSensorRssi = null,
                            )
                    }
                    stopConnectedRssiPolling()
                }

                override fun disInformationReceived(identifier: String, disInfo: DisInfo) {}

                override fun htsNotificationReceived(
                    identifier: String,
                    data: PolarHealthThermometerData,
                ) {}

                override fun bleSdkFeatureReady(
                    identifier: String,
                    feature: PolarBleApi.PolarBleSdkFeature,
                ) {
                    Log.d("HnHBridge", "feature ready: $feature for $identifier")
                    if (feature != PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_ONLINE_STREAMING) return

                    if (hrDisposable?.isDisposed == false) {
                        Log.d("HnHBridge", "HR stream subscription already active; skip")
                    } else {
                        rrStreamingStarted = true
                        Log.d("HnHBridge", "Starting HR stream once")

                        hrDisposable = polarApi.startHrStreaming(identifier)
                            .observeOn(Schedulers.io())
                            .subscribe(
                                { hrData ->
                                    for (sample in hrData.samples) {
                                        Log.d("HnHBridge", "HR=${sample.hr} rr=${sample.rrsMs}")
                                        for (rr in sample.rrsMs) {
                                            if (rr > 0) {
                                                sendBridgeJsonLine("""{"type":"rr","rr_ms":$rr}""")
                                            }
                                        }
                                    }
                                },
                                { err -> Log.e("HnHBridge", "HR stream error", err) },
                            )
                        disposables.add(hrDisposable!!)
                    }

                    if (ecgDisposable?.isDisposed == false || ecgStreamingStarted) {
                        Log.d("HnHBridge", "ECG stream already active; skip")
                        return
                    }

                    ecgStreamingStarted = true
                    Log.d("HnHBridge", "Starting ECG stream once")

                    ecgDisposable = polarApi.requestStreamSettings(
                        identifier,
                        PolarBleApi.PolarDeviceDataType.ECG,
                    )
                        .toFlowable()
                        .flatMap { sensorSetting: PolarSensorSetting ->
                            Log.d("HnHBridge", "ECG settings ready")
                            polarApi.startEcgStreaming(identifier, sensorSetting.maxSettings())
                        }
                        .observeOn(Schedulers.io())
                        .subscribe(
                            { ecgData: PolarEcgData ->
                                val samplesMv = extractEcgMillivolts(ecgData)
                                if (samplesMv.isEmpty()) {
                                    Log.d("HnHBridge", "ECG batch empty after parse; skipping")
                                    return@subscribe
                                }

                                val batch = if (samplesMv.size > 130) samplesMv.takeLast(130) else samplesMv
                                val json = """{"type":"ecg","sample_rate_hz":130,"samples_mv":$batch}"""
                                sendBridgeJsonLine(json)
                                Log.d("HnHBridge", "ECG batch sent size=${batch.size}")
                            },
                            { err ->
                                Log.e("HnHBridge", "ECG stream error", err)
                                ecgStreamingStarted = false
                            },
                        )
                    disposables.add(ecgDisposable!!)
                }
            },
        )

        discoveryExecutor.execute {
            val buf = ByteArray(2048)
            while (!Thread.currentThread().isInterrupted) {
                var socket: DatagramSocket? = null
                try {
                    socket =
                        DatagramSocket().apply {
                            reuseAddress = true
                            bind(InetSocketAddress(PHONE_UDP_DISCOVERY_PORT))
                        }
                    synchronized(discoverySocketLock) {
                        udpDiscoverySocket = socket
                    }
                    Log.d("HnHBridge", "UDP discovery listening on port $PHONE_UDP_DISCOVERY_PORT")
                    while (!Thread.currentThread().isInterrupted) {
                        val p = DatagramPacket(buf, buf.size)
                        socket.receive(p)
                        val text = String(p.data, 0, p.length, Charsets.UTF_8).trim()
                        if (!text.startsWith(PHONE_UDP_DISCOVER_PREFIX)) continue
                        val hostLabel = Build.MODEL.orEmpty().ifBlank { "Android" }
                        val replyJson =
                            JSONObject()
                                .put("app", "PolarH10Bridge")
                                .put("role", "phone_bridge")
                                .put("hostname", hostLabel)
                                .put("port", 8765)
                                .toString() + "\n"
                        val replyBytes = replyJson.toByteArray(Charsets.UTF_8)
                        socket.send(DatagramPacket(replyBytes, replyBytes.size, p.socketAddress))
                    }
                } catch (e: SocketException) {
                    if (Thread.currentThread().isInterrupted) break
                    Log.d("HnHBridge", "UDP discovery: ${e.message}")
                } catch (e: Exception) {
                    Log.e("HnHBridge", "UDP discovery error", e)
                } finally {
                    synchronized(discoverySocketLock) {
                        if (udpDiscoverySocket === socket) {
                            udpDiscoverySocket = null
                        }
                    }
                    try {
                        socket?.close()
                    } catch (_: Exception) {
                    }
                    if (!Thread.currentThread().isInterrupted) {
                        try {
                            Thread.sleep(1500)
                        } catch (_: InterruptedException) {
                            break
                        }
                    }
                }
            }
        }

        bridgeExecutor.execute {
            while (!Thread.currentThread().isInterrupted) {
                try {
                    ServerSocket().use { server ->
                        server.reuseAddress = true
                        server.bind(InetSocketAddress(8765))
                        Log.d("HnHBridge", "TCP listening on port 8765")

                        while (!Thread.currentThread().isInterrupted) {
                            server.accept().use { client ->
                                client.keepAlive = true
                                client.tcpNoDelay = true
                                Log.d("HnHBridge", "PC connected from ${client.inetAddress.hostAddress}")

                                bridgeClient = client
                                val writer = java.io.PrintWriter(
                                    java.io.OutputStreamWriter(client.getOutputStream(), Charsets.UTF_8),
                                    true,
                                )
                                bridgeWriter = writer
                                mainHandler.post {
                                    screenState.value =
                                        screenState.value.copy(
                                            pcBridgeConnected = true,
                                            pcBridgeIp = client.inetAddress?.hostAddress,
                                        )
                                }

                                sendBridgeJsonLine("""{"type":"status","message":"Phone bridge connected","connected":true}""")

                                try {
                                    val input = client.getInputStream()
                                    val buf = ByteArray(1024)
                                    while (true) {
                                        val n = input.read(buf)
                                        if (n == -1) {
                                            Log.d("HnHBridge", "PC closed TCP (EOF)")
                                            break
                                        }
                                    }
                                } catch (e: SocketException) {
                                    Log.d("HnHBridge", "TCP connection lost: ${e.message}")
                                } catch (e: Exception) {
                                    Log.e("HnHBridge", "TCP read error", e)
                                } finally {
                                    bridgeWriter = null
                                    bridgeClient = null
                                    mainHandler.post {
                                        screenState.value =
                                            screenState.value.copy(
                                                pcBridgeConnected = false,
                                                pcBridgeIp = null,
                                            )
                                    }
                                    Log.d("HnHBridge", "Bridge session closed")
                                }
                            }
                        }
                    }
                } catch (e: Exception) {
                    if (Thread.currentThread().isInterrupted) break
                    Log.e("HnHBridge", "Bridge server error", e)
                    try {
                        Thread.sleep(2000)
                    } catch (_: InterruptedException) {
                        break
                    }
                }
            }
        }

        setContent {
            PolarH10BridgeTheme {
                val state by screenState
                BridgeMainScreen(
                    state = state,
                    onScanSensors = { beginSensorScan() },
                )
                if (state.bleDialogVisible) {
                    SensorListDialog(
                        scanning = state.bleScanning,
                        connecting = state.bleConnecting,
                        rows = state.bleRows,
                        selectedId = state.bleSelectedId,
                        onSelect = { id ->
                            screenState.value = screenState.value.copy(bleSelectedId = id)
                        },
                        onDismissRequest = { cancelSensorDialog() },
                        onCancel = { cancelSensorDialog() },
                        onOk = { confirmSensorSelection() },
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        screenState.value =
            screenState.value.copy(phoneWifiIpv4 = wifiIpv4String(this))
    }

    override fun onDestroy() {
        rrStreamingStarted = false
        ecgStreamingStarted = false

        hrDisposable?.dispose()
        hrDisposable = null

        ecgDisposable?.dispose()
        ecgDisposable = null

        bleSearchDisposable?.dispose()
        bleSearchDisposable = null
        stopConnectedRssiPolling()

        synchronized(discoverySocketLock) {
            try {
                udpDiscoverySocket?.close()
            } catch (_: Exception) {
            }
            udpDiscoverySocket = null
        }

        disposables.clear()
        discoveryExecutor.shutdownNow()
        bridgeExecutor.shutdownNow()

        if (::polarApi.isInitialized) {
            polarApi.shutDown()
        }
        super.onDestroy()
    }
}

@Composable
private fun BridgeMainScreen(
    state: BridgeScreenState,
    onScanSensors: () -> Unit,
) {
    val context = LocalContext.current
    val versionName = remember(context) { context.appVersionName() }

    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .background(UiWhite),
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .windowInsetsPadding(
                            WindowInsets.statusBars.union(
                                WindowInsets.displayCutout.only(WindowInsetsSides.Top),
                            ),
                        )
                        .background(BannerRed)
                        .padding(horizontal = 16.dp, vertical = 14.dp),
            ) {
                Text(
                    text = "Polar H10-to-PC Bridge",
                    color = UiWhite,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center,
                )
            }
            Column(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                val wifiIp = state.phoneWifiIpv4 ?: wifiIpv4String(LocalContext.current)
                if (wifiIp != null) {
                    Text(
                        text = "Open Hertz & Hearts on your PC and connect to $wifiIp:8765",
                        color = TextDark.copy(alpha = 0.78f),
                        fontSize = 11.sp,
                        lineHeight = 11.sp,
                        style =
                            TextStyle(
                                lineHeightStyle =
                                    LineHeightStyle(
                                        alignment = LineHeightStyle.Alignment.Center,
                                        trim = LineHeightStyle.Trim.Both,
                                    ),
                            ),
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .padding(bottom = 6.dp),
                    )
                }

                BridgeFlowDiagram(
                    sensorConnected = state.sensorConnected,
                    pcBridgeConnected = state.pcBridgeConnected,
                    onScanSensors = onScanSensors,
                    modifier = Modifier.padding(bottom = 8.dp),
                )

                if (state.sensorConnected) {
                    Text(
                        text = "Connected to:",
                        color = TextDark,
                        fontSize = 13.sp,
                        lineHeight = 13.sp,
                        fontWeight = FontWeight.Medium,
                        style =
                            TextStyle(
                                lineHeightStyle =
                                    LineHeightStyle(
                                        alignment = LineHeightStyle.Alignment.Center,
                                        trim = LineHeightStyle.Trim.Both,
                                    ),
                            ),
                        modifier = Modifier.align(Alignment.Start),
                    )
                    Spacer(modifier = Modifier.height(1.dp))
                    Text(
                        text = buildString {
                            append(
                                connectedSensorSingleLine(
                                    state.connectedSensorName,
                                    state.connectedSensorId,
                                ),
                            )
                            state.connectedSensorRssi?.let { rssi ->
                                append(" ($rssi dBm signal)")
                            }
                        },
                        color = TextDark,
                        fontSize = 12.sp,
                        lineHeight = 12.sp,
                        style =
                            TextStyle(
                                lineHeightStyle =
                                    LineHeightStyle(
                                        alignment = LineHeightStyle.Alignment.Center,
                                        trim = LineHeightStyle.Trim.Both,
                                    ),
                            ),
                        modifier = Modifier.align(Alignment.Start),
                    )
                    val phoneIp = state.phoneWifiIpv4 ?: wifiIpv4String(LocalContext.current) ?: "unknown"
                    val pcIp = state.pcBridgeIp ?: "not connected"
                    Spacer(modifier = Modifier.height(1.dp))
                    Text(
                        text = "Phone: $phoneIp",
                        color = TextDark,
                        fontSize = 11.sp,
                        lineHeight = 11.sp,
                        style =
                            TextStyle(
                                lineHeightStyle =
                                    LineHeightStyle(
                                        alignment = LineHeightStyle.Alignment.Center,
                                        trim = LineHeightStyle.Trim.Both,
                                    ),
                            ),
                        modifier = Modifier.align(Alignment.Start),
                    )
                    Text(
                        text = "PC: $pcIp",
                        color = TextDark,
                        fontSize = 11.sp,
                        lineHeight = 11.sp,
                        style =
                            TextStyle(
                                lineHeightStyle =
                                    LineHeightStyle(
                                        alignment = LineHeightStyle.Alignment.Center,
                                        trim = LineHeightStyle.Trim.Both,
                                    ),
                            ),
                        modifier = Modifier.align(Alignment.Start),
                    )
                    Spacer(modifier = Modifier.height(2.dp))
                }
            }
        }

        if (versionName.isNotEmpty()) {
            Text(
                text = "Version $versionName",
                color = TextDark.copy(alpha = 0.45f),
                fontSize = 11.sp,
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .windowInsetsPadding(WindowInsets.navigationBars)
                        .padding(bottom = 12.dp),
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun RedActionButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Button(
        onClick = onClick,
        modifier = modifier.height(52.dp),
        colors =
            ButtonDefaults.buttonColors(
                containerColor = BannerRed,
                contentColor = UiWhite,
            ),
        elevation =
            ButtonDefaults.buttonElevation(
                defaultElevation = 4.dp,
                pressedElevation = 8.dp,
                hoveredElevation = 5.dp,
                focusedElevation = 4.dp,
                disabledElevation = 0.dp,
            ),
        shape = RoundedCornerShape(14.dp),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Text(text = text, fontWeight = FontWeight.Bold, fontSize = 14.sp)
    }
}

@Composable
private fun SensorListDialog(
    scanning: Boolean,
    connecting: Boolean,
    rows: List<BleDeviceRow>,
    selectedId: String?,
    onSelect: (String) -> Unit,
    onDismissRequest: () -> Unit,
    onCancel: () -> Unit,
    onOk: () -> Unit,
) {
    Dialog(onDismissRequest = onDismissRequest) {
        Surface(
            shape = RoundedCornerShape(8.dp),
            color = UiWhite,
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "Devices found:",
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 16.sp,
                    color = TextDark,
                )
                Spacer(modifier = Modifier.height(12.dp))
                when {
                    scanning && rows.isEmpty() -> {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(modifier = Modifier.size(28.dp))
                            Spacer(modifier = Modifier.size(12.dp))
                            Text(text = "Scanning for sensors…", color = TextDark, fontSize = 14.sp)
                        }
                    }

                    rows.isEmpty() && !scanning -> {
                        Text(text = "No devices found.", color = TextDark, fontSize = 14.sp)
                    }

                    else -> {
                        LazyColumn(
                            modifier =
                                Modifier
                                    .fillMaxWidth()
                                    .heightIn(max = 320.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            items(rows, key = { it.deviceId }) { row ->
                                val sel = selectedId == row.deviceId
                                val line1 =
                                    connectedSensorSingleLine(row.displayName, row.deviceId)
                                val line2 =
                                    if (line1.contains(row.deviceId, ignoreCase = true)) {
                                        "${row.rssi} dBm"
                                    } else {
                                        "ID ${row.deviceId} · ${row.rssi} dBm"
                                    }
                                Row(
                                    modifier =
                                        Modifier
                                            .fillMaxWidth()
                                            .selectable(
                                                selected = sel,
                                                onClick = { onSelect(row.deviceId) },
                                                role = Role.RadioButton,
                                            )
                                            .padding(vertical = 6.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    RadioButton(
                                        selected = sel,
                                        onClick = null,
                                        colors =
                                            RadioButtonDefaults.colors(
                                                selectedColor = BannerRed,
                                            ),
                                    )
                                    Column(modifier = Modifier.padding(start = 4.dp)) {
                                        Text(
                                            text = line1,
                                            fontSize = 14.sp,
                                            color = TextDark,
                                            fontWeight = FontWeight.Medium,
                                        )
                                        Text(
                                            text = line2,
                                            fontSize = 12.sp,
                                            color = TextDark,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
                if (connecting) {
                    Spacer(modifier = Modifier.height(12.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.size(24.dp))
                        Spacer(modifier = Modifier.size(8.dp))
                        Text("Connecting…", fontSize = 14.sp, color = TextDark)
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                ) {
                    TextButton(onClick = onCancel) {
                        Text("Cancel", color = BannerRed)
                    }
                    TextButton(
                        onClick = onOk,
                        enabled = !connecting && selectedId != null && rows.isNotEmpty(),
                    ) {
                        Text("Connect", color = BannerRed, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Suppress("DEPRECATION")
private fun Context.appVersionName(): String =
    try {
        packageManager.getPackageInfo(packageName, 0).versionName.orEmpty()
    } catch (_: Exception) {
        ""
    }

@SuppressLint("MissingPermission")
private fun wifiIpv4String(context: Context): String? {
    val cm = context.applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        ?: return null

    // Prefer Wi-Fi interfaces; active network can be VPN/cellular and return misleading IPs.
    val networks = cm.allNetworks.toList()
    val ordered = buildList {
        addAll(
            networks.filter { n ->
                val caps = cm.getNetworkCapabilities(n) ?: return@filter false
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
            },
        )
        addAll(networks.filterNot { contains(it) })
    }

    for (network in ordered) {
        val lp = cm.getLinkProperties(network) ?: continue
        for (la in lp.linkAddresses) {
            val a = la.address
            if (a is Inet4Address && !a.isLoopbackAddress) {
                return a.hostAddress
            }
        }
    }
    return null
}
