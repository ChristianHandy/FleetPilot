package com.fleetpilot.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.fleetpilot.data.models.*
import com.fleetpilot.ui.components.*
import com.fleetpilot.ui.theme.*
import com.fleetpilot.viewmodel.*

// ── Dashboard Screen ──────────────────────────────────────────────────────────
@Composable
fun DashboardScreen(viewModel: DashboardViewModel) {
    val summary by viewModel.summary.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(FPBackground)
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        SectionHeader("Dashboard", Icons.Default.Dashboard)
        Spacer(Modifier.height(8.dp))

        if (loading && summary == null) {
            LoadingState()
            return@Column
        }
        error?.let { ErrorState(it) { viewModel.load() }; return@Column }

        summary?.let { s ->
            // Stat Grid
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricCard(
                    "Server", "${s.hosts.online}/${s.hosts.total}", " online",
                    if (s.hosts.offline > 0) FPWarning else FPSuccess,
                    Icons.Default.Dns, Modifier.weight(1f)
                )
                MetricCard(
                    "VMs", "${s.vmEndpoints}", " Endpunkte",
                    FPPrimary, Icons.Default.Computer, Modifier.weight(1f)
                )
            }
            Spacer(Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricCard(
                    "Alerts", "${s.activeAlerts}", " aktiv",
                    if (s.activeAlerts > 0) FPError else FPSuccess,
                    Icons.Default.Warning, Modifier.weight(1f)
                )
                MetricCard(
                    "Backup", "${s.backupServers}", " Server",
                    FPSecondary, Icons.Default.Backup, Modifier.weight(1f)
                )
            }
            Spacer(Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricCard(
                    "HW Monitor", "${s.hwServers}", " Server",
                    FPPrimary, Icons.Default.Memory, Modifier.weight(1f)
                )
                MetricCard(
                    "Fans", "${s.fanControllers}", " Controller",
                    FPSecondary, Icons.Default.Air, Modifier.weight(1f)
                )
            }
        }

        Spacer(Modifier.height(16.dp))
        Button(
            onClick = { viewModel.load() },
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = FPSurfaceVariant)
        ) {
            Icon(Icons.Default.Refresh, null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Aktualisieren")
        }
    }
}

// ── Hosts Screen ──────────────────────────────────────────────────────────────
@Composable
fun HostsScreen(viewModel: HostsViewModel) {
    val hosts by viewModel.hosts.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()
    val actionResult by viewModel.actionResult.collectAsState()
    var showDeleteDialog by remember { mutableStateOf<Int?>(null) }
    var showCommandDialog by remember { mutableStateOf<ServerHost?>(null) }

    if (loading && hosts.isEmpty()) { LoadingState(); return }
    error?.let { ErrorState(it) { viewModel.load() }; return }

    actionResult?.let { result ->
        AlertDialog(
            onDismissRequest = { viewModel.clearActionResult() },
            containerColor = FPSurface,
            title = { Text("Ausgabe", color = FPOnBackground) },
            text = { Text(result, color = FPOnSurface, fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace, fontSize = 12.sp) },
            confirmButton = { TextButton(onClick = { viewModel.clearActionResult() }) { Text("OK", color = FPPrimary) } }
        )
    }

    showDeleteDialog?.let { id ->
        ConfirmDialog(
            "Server löschen",
            "Soll dieser Server wirklich gelöscht werden?",
            onConfirm = { viewModel.deleteHost(id); showDeleteDialog = null },
            onDismiss = { showDeleteDialog = null }
        )
    }

    showCommandDialog?.let { host ->
        var cmd by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showCommandDialog = null },
            containerColor = FPSurface,
            title = { Text("Befehl ausführen — ${host.name}", color = FPOnBackground) },
            text = {
                OutlinedTextField(
                    value = cmd, onValueChange = { cmd = it },
                    label = { Text("Befehl") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = fpTextFieldColors()
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.executeCommand(host.id, cmd)
                    showCommandDialog = null
                }) { Text("Ausführen", color = FPPrimary) }
            },
            dismissButton = { TextButton(onClick = { showCommandDialog = null }) { Text("Abbrechen", color = FPMuted) } }
        )
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                SectionHeader("Server (${hosts.size})", Icons.Default.Dns)
                IconButton(onClick = { viewModel.load() }) {
                    Icon(Icons.Default.Refresh, null, tint = FPPrimary)
                }
            }
        }
        items(hosts) { host ->
            HostCard(
                host = host,
                onCheckStatus = { viewModel.checkStatus(host.id) },
                onCommand = { showCommandDialog = host },
                onDelete = { showDeleteDialog = host.id }
            )
        }
    }
}

@Composable
fun HostCard(
    host: ServerHost,
    onCheckStatus: () -> Unit,
    onCommand: () -> Unit,
    onDelete: () -> Unit
) {
    GlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(host.name, color = FPOnBackground, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                Text("${host.address}:${host.port}", color = FPMuted, fontSize = 12.sp)
                host.group?.let { Text(it, color = FPSecondary, fontSize = 11.sp) }
            }
            StatusBadge(if (host.isOnline) "online" else "offline")
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = onCheckStatus,
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = FPPrimary),
                border = androidx.compose.foundation.BorderStroke(1.dp, FPBorder)
            ) { Text("Status", fontSize = 12.sp) }
            OutlinedButton(
                onClick = onCommand,
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = FPPrimary),
                border = androidx.compose.foundation.BorderStroke(1.dp, FPBorder)
            ) { Text("Befehl", fontSize = 12.sp) }
            IconButton(onClick = onDelete, modifier = Modifier.size(36.dp)) {
                Icon(Icons.Default.Delete, null, tint = FPError, modifier = Modifier.size(18.dp))
            }
        }
    }
}

// ── VM Screen ─────────────────────────────────────────────────────────────────
@Composable
fun VmScreen(viewModel: VmViewModel) {
    val allVms by viewModel.allVms.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()
    val actionResult by viewModel.actionResult.collectAsState()

    if (loading && allVms.isEmpty()) { LoadingState(); return }
    error?.let { ErrorState(it) { viewModel.load() }; return }

    actionResult?.let {
        LaunchedEffect(it) {
            kotlinx.coroutines.delay(2000)
            viewModel.clearActionResult()
        }
        Snackbar(modifier = Modifier.padding(16.dp), containerColor = FPSuccess) {
            Text(it, color = FPBackground)
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                SectionHeader("Virtuelle Maschinen", Icons.Default.Computer)
                IconButton(onClick = { viewModel.load() }) {
                    Icon(Icons.Default.Refresh, null, tint = FPPrimary)
                }
            }
        }
        allVms.forEach { group ->
            item {
                Text(
                    "● ${group.endpoint.name}",
                    color = FPPrimary, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(vertical = 4.dp)
                )
            }
            items(group.vms) { vm ->
                VmCard(vm = vm, endpointId = group.endpoint.id, onAction = { action ->
                    viewModel.vmAction(group.endpoint.id, vm.node, vm.vmId, vm.type, action)
                })
            }
        }
    }
}

@Composable
fun VmCard(vm: VmInfo, endpointId: Int, onAction: (String) -> Unit) {
    var showActions by remember { mutableStateOf(false) }
    GlassCard(modifier = Modifier.fillMaxWidth().clickable { showActions = !showActions }) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Icon(
                        if (vm.type == "lxc") Icons.Default.ViewInAr else Icons.Default.Computer,
                        null, tint = FPMuted, modifier = Modifier.size(14.dp)
                    )
                    Text(vm.name, color = FPOnBackground, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    Text("(${vm.vmId})", color = FPMuted, fontSize = 11.sp)
                }
                Text("${vm.node} · ${vm.type.uppercase()}", color = FPMuted, fontSize = 11.sp)
                vm.cpuUsage?.let {
                    Text("CPU: ${(it * 100).toInt()}% · RAM: ${vm.mem / 1024 / 1024}/${vm.maxMem / 1024 / 1024} MB",
                        color = FPMuted, fontSize = 11.sp)
                }
            }
            StatusBadge(vm.status)
        }
        if (showActions) {
            Spacer(Modifier.height(10.dp))
            Divider(color = FPBorder)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (vm.status != "running") {
                    OutlinedButton(
                        onClick = { onAction("start") },
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = FPSuccess),
                        border = androidx.compose.foundation.BorderStroke(1.dp, FPSuccess.copy(alpha = 0.5f)),
                        modifier = Modifier.weight(1f)
                    ) { Text("▶ Start", fontSize = 11.sp) }
                }
                if (vm.status == "running") {
                    OutlinedButton(
                        onClick = { onAction("stop") },
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = FPError),
                        border = androidx.compose.foundation.BorderStroke(1.dp, FPError.copy(alpha = 0.5f)),
                        modifier = Modifier.weight(1f)
                    ) { Text("■ Stop", fontSize = 11.sp) }
                    OutlinedButton(
                        onClick = { onAction("reboot") },
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = FPWarning),
                        border = androidx.compose.foundation.BorderStroke(1.dp, FPWarning.copy(alpha = 0.5f)),
                        modifier = Modifier.weight(1f)
                    ) { Text("↺ Reboot", fontSize = 11.sp) }
                }
            }
        }
    }
}

// ── HW Monitor Screen ─────────────────────────────────────────────────────────
@Composable
fun HwMonitorScreen(viewModel: HwViewModel) {
    val servers by viewModel.servers.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()

    if (loading && servers.isEmpty()) { LoadingState(); return }
    error?.let { ErrorState(it) { viewModel.load() }; return }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                SectionHeader("HW Monitor", Icons.Default.Memory)
                IconButton(onClick = { viewModel.load() }) {
                    Icon(Icons.Default.Refresh, null, tint = FPPrimary)
                }
            }
        }
        items(servers) { server ->
            HwServerCard(server = server,
                onStartStress = { viewModel.startStress(server.id) },
                onStopStress = { viewModel.stopStress(server.id) }
            )
        }
    }
}

@Composable
fun HwServerCard(server: HwServer, onStartStress: () -> Unit, onStopStress: () -> Unit) {
    val m = server.metrics
    GlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(server.name, color = FPOnBackground, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                Text(server.address, color = FPMuted, fontSize = 12.sp)
            }
            StatusBadge(if (m?.isOnline == true) "online" else "offline")
        }

        if (m?.isOnline == true) {
            Spacer(Modifier.height(12.dp))
            // CPU
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("CPU Temp", color = FPMuted, fontSize = 11.sp)
                    TempIndicator(m.cpuTemp)
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text("CPU Last", color = FPMuted, fontSize = 11.sp)
                    Text("${m.cpuUsage?.toInt() ?: "N/A"}%", color = FPPrimary, fontWeight = FontWeight.Bold)
                }
                m.gpuTemp?.let {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("GPU (${m.gpuVendor?.uppercase() ?: ""})", color = FPMuted, fontSize = 11.sp)
                        TempIndicator(it)
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            // RAM
            val ramPct = if ((m.ramTotalMb ?: 0) > 0)
                (m.ramUsedMb ?: 0).toFloat() / (m.ramTotalMb ?: 1) else 0f
            LabeledProgress(
                "RAM",
                ramPct,
                "${m.ramUsedMb ?: 0} / ${m.ramTotalMb ?: 0} MB",
                FPSecondary
            )
            Spacer(Modifier.height(8.dp))
            // Network
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("↓ ${m.netRxKbps?.toInt() ?: 0} KB/s", color = FPSuccess, fontSize = 12.sp, modifier = Modifier.weight(1f))
                Text("↑ ${m.netTxKbps?.toInt() ?: 0} KB/s", color = FPPrimary, fontSize = 12.sp, modifier = Modifier.weight(1f))
            }
            // Fans
            if (m.fans.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text("Lüfter", color = FPMuted, fontSize = 11.sp)
                m.fans.forEach { fan ->
                    Text("${fan.name}: ${fan.rpm?.toInt() ?: "N/A"} RPM", color = FPOnSurface, fontSize = 11.sp)
                }
            }
            Spacer(Modifier.height(12.dp))
            Divider(color = FPBorder)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (server.stressTestRunning) {
                    OutlinedButton(
                        onClick = onStopStress,
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = FPError),
                        border = androidx.compose.foundation.BorderStroke(1.dp, FPError.copy(alpha = 0.5f))
                    ) { Text("■ Stop Test", fontSize = 12.sp) }
                } else {
                    OutlinedButton(
                        onClick = onStartStress,
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = FPSuccess),
                        border = androidx.compose.foundation.BorderStroke(1.dp, FPSuccess.copy(alpha = 0.5f))
                    ) { Text("▶ Stress Test", fontSize = 12.sp) }
                }
            }
        } else {
            Spacer(Modifier.height(8.dp))
            Text(m?.error ?: "Server nicht erreichbar", color = FPError, fontSize = 12.sp)
        }
    }
}

// ── Fan Control Screen ────────────────────────────────────────────────────────
@Composable
fun FanScreen(viewModel: FanViewModel) {
    val controllers by viewModel.controllers.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()
    val actionResult by viewModel.actionResult.collectAsState()

    if (loading && controllers.isEmpty()) { LoadingState(); return }
    error?.let { ErrorState(it) { viewModel.load() }; return }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item { SectionHeader("Fan Control", Icons.Default.Air) }
        if (controllers.isEmpty()) {
            item {
                GlassCard(modifier = Modifier.fillMaxWidth()) {
                    Text("Keine Fan Controller konfiguriert.", color = FPMuted)
                    Spacer(Modifier.height(8.dp))
                    Text("Füge Controller über das Web-Dashboard hinzu.", color = FPMuted, fontSize = 12.sp)
                }
            }
        }
        items(controllers) { fc ->
            FanControllerCard(fc = fc, onSetFan = { channel, duty ->
                viewModel.setFan(fc.id, channel, duty)
            })
        }
    }
}

@Composable
fun FanControllerCard(fc: FanController, onSetFan: (String, Int) -> Unit) {
    var sliderValue by remember { mutableStateOf(50f) }
    GlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(fc.name, color = FPOnBackground, fontWeight = FontWeight.SemiBold)
                Text(fc.controllerType.uppercase(), color = FPSecondary, fontSize = 11.sp)
            }
            Icon(Icons.Default.Air, null, tint = FPPrimary)
        }
        Spacer(Modifier.height(12.dp))
        Text("Lüftergeschwindigkeit: ${sliderValue.toInt()}%", color = FPOnSurface, fontSize = 13.sp)
        Slider(
            value = sliderValue,
            onValueChange = { sliderValue = it },
            valueRange = 0f..100f,
            steps = 9,
            colors = SliderDefaults.colors(thumbColor = FPPrimary, activeTrackColor = FPPrimary)
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(0 to "Min", 50 to "50%", 100 to "Max").forEach { (v, label) ->
                OutlinedButton(
                    onClick = { sliderValue = v.toFloat(); onSetFan("fan1", v) },
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = FPPrimary),
                    border = androidx.compose.foundation.BorderStroke(1.dp, FPBorder),
                    contentPadding = PaddingValues(4.dp)
                ) { Text(label, fontSize = 11.sp) }
            }
            Button(
                onClick = { onSetFan("fan1", sliderValue.toInt()) },
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(containerColor = FPPrimaryVariant),
                contentPadding = PaddingValues(4.dp)
            ) { Text("Setzen", fontSize = 11.sp) }
        }
    }
}
