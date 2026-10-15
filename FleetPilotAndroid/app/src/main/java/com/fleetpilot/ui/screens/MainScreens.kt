// SPDX-FileCopyrightText: Copyright the FleetPilot contributors
// SPDX-License-Identifier: GPL-3.0-or-later
package com.fleetpilot.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.fleetpilot.data.models.*
import com.fleetpilot.ui.components.*
import com.fleetpilot.ui.theme.*
import com.fleetpilot.viewmodel.*

// ── Shared pieces ────────────────────────────────────────────────────────────

@Composable
private fun ScreenHeader(title: String, icon: ImageVector, onRefresh: () -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        SectionHeader(title, icon)
        IconButton(onClick = onRefresh) { Icon(Icons.Default.Refresh, "Refresh", tint = FPPrimary) }
    }
}

/** Shows the result of an action until it is dismissed. */
@Composable
private fun ActionMessage(message: String?, onDismiss: () -> Unit) {
    message ?: return
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = FPSurface,
        text = { Text(message, color = FPOnSurface) },
        confirmButton = { TextButton(onClick = onDismiss) { Text("OK", color = FPPrimary) } }
    )
}

@Composable
private fun EmptyCard(text: String) {
    GlassCard(Modifier.fillMaxWidth()) { Text(text, color = FPMuted, fontSize = 13.sp) }
}

@Composable
private fun ActionButton(text: String, color: Color, modifier: Modifier = Modifier, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier,
        colors = ButtonDefaults.outlinedButtonColors(contentColor = color),
        border = androidx.compose.foundation.BorderStroke(1.dp, color.copy(alpha = 0.5f)),
        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp)
    ) { Text(text, fontSize = 12.sp) }
}

private fun mb(bytes: Long?) = if (bytes == null) "?" else "${bytes / 1024 / 1024}"

// ── Dashboard ────────────────────────────────────────────────────────────────

@Composable
fun DashboardScreen(viewModel: DashboardViewModel, me: Me?) {
    val summary by viewModel.summary.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item { ScreenHeader("Dashboard", Icons.Default.Dashboard, viewModel::refresh) }
        me?.let { item { Text("Signed in as ${it.username} · ${it.roles.joinToString()} · ${if (it.canWrite) "read/write" else "read-only"} token",
                              color = FPMuted, fontSize = 12.sp) } }
        val s = summary
        when {
            loading && s == null -> item { LoadingState() }
            error != null && s == null -> item { ErrorState(error!!, viewModel::refresh) }
            s != null -> {
                item {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        MetricCard("Servers", "${s.hostsReachable}/${s.hostsTotal}", " reachable",
                            if (s.hostsReachable < s.hostsTotal) FPWarning else FPSuccess, Icons.Default.Dns, Modifier.weight(1f))
                        MetricCard("VMs", s.vmsTotal?.let { "${s.vmsRunning}/$it" } ?: "–", " running",
                            FPPrimary, Icons.Default.Computer, Modifier.weight(1f))
                    }
                }
                item {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        val d = s.disks
                        MetricCard("Disks", d?.let { if (it.problems > 0) "${it.problems}" else "${it.total}" } ?: "–",
                            d?.let { if (it.problems > 0) " need attention" else " healthy" } ?: "",
                            if ((d?.problems ?: 0) > 0) FPError else FPSuccess, Icons.Default.Storage, Modifier.weight(1f))
                        val v = s.vulnerabilities
                        MetricCard("CVEs", v?.let { "${it.critical + it.high}" } ?: "–", " critical/high",
                            if ((v?.critical ?: 0) > 0) FPError else if ((v?.high ?: 0) > 0) FPWarning else FPSuccess,
                            Icons.Default.Security, Modifier.weight(1f))
                    }
                }
                item {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        MetricCard("Routers", s.routersTotal?.let { "${s.routersOnline}/$it" } ?: "–", " online",
                            if ((s.routersOnline ?: 0) < (s.routersTotal ?: 0)) FPWarning else FPSuccess,
                            Icons.Default.Router, Modifier.weight(1f))
                        MetricCard("Backups", s.backupTotal?.let { "${it - (s.backupProblems ?: 0)}/$it" } ?: "–", " OK",
                            if ((s.backupProblems ?: 0) > 0) FPError else FPSecondary, Icons.Default.Backup, Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

// ── Hosts ────────────────────────────────────────────────────────────────────

@Composable
fun HostsScreen(viewModel: HostsViewModel, me: Me?) {
    val hosts by viewModel.hosts.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()
    val message by viewModel.message.collectAsState()
    var confirmShutdown by remember { mutableStateOf<Host?>(null) }

    ActionMessage(message, viewModel::clearMessage)
    confirmShutdown?.let { host ->
        ConfirmDialog("Shut down ${host.name}?", "The machine at ${host.host} powers off now.",
            onConfirm = { viewModel.shutdown(host); confirmShutdown = null }, onDismiss = { confirmShutdown = null })
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item { ScreenHeader("Servers (${hosts.size})", Icons.Default.Dns, viewModel::refresh) }
        when {
            loading && hosts.isEmpty() -> item { LoadingState() }
            error != null && hosts.isEmpty() -> item { ErrorState(error!!, viewModel::refresh) }
            hosts.isEmpty() -> item { EmptyCard("No servers yet. Add them in FleetPilot's web interface.") }
        }
        items(hosts, key = { it.name }) { host ->
            GlassCard(Modifier.fillMaxWidth()) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(host.name, color = FPOnBackground, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                        Text("${host.host}:${host.port}", color = FPMuted, fontSize = 12.sp)
                        listOf(host.os, host.group, host.environment).filter { it.isNotBlank() }.joinToString(" · ")
                            .takeIf { it.isNotEmpty() }?.let { Text(it, color = FPSecondary, fontSize = 11.sp) }
                    }
                    StatusBadge(host.state.replace('_', ' '))
                }
                if (me?.isOperator == true) {
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (host.canWake) ActionButton("Wake (WoL)", FPSuccess, Modifier.weight(1f)) { viewModel.wake(host) }
                        ActionButton("Shut down", FPError, Modifier.weight(1f)) { confirmShutdown = host }
                    }
                }
            }
        }
    }
}

// ── Virtual machines ─────────────────────────────────────────────────────────

@Composable
fun VmScreen(viewModel: VmViewModel, me: Me?) {
    val endpoints by viewModel.endpoints.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()
    val message by viewModel.message.collectAsState()
    var confirm by remember { mutableStateOf<Triple<VmEndpoint, Vm, String>?>(null) }

    ActionMessage(message, viewModel::clearMessage)
    confirm?.let { (ep, vm, action) ->
        ConfirmDialog("${action.replaceFirstChar { it.uppercase() }} ${vm.name ?: vm.vmid}?",
            "On ${ep.name} / ${vm.node}.",
            onConfirm = { viewModel.action(ep, vm, action); confirm = null }, onDismiss = { confirm = null })
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item { ScreenHeader("Virtual machines", Icons.Default.Computer, viewModel::refresh) }
        when {
            loading && endpoints.isEmpty() -> item { LoadingState() }
            error != null && endpoints.isEmpty() -> item { ErrorState(error!!, viewModel::refresh) }
            endpoints.isEmpty() -> item { EmptyCard("No VM controllers yet. Add Proxmox under VM controllers in the web interface.") }
        }
        endpoints.forEach { ep ->
            item(key = "ep-${ep.id}") {
                Text("● ${ep.name}", color = FPPrimary, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp))
                ep.error?.let { Text(it, color = FPError, fontSize = 12.sp) }
                if (ep.platform != "proxmox") Text("${ep.platform}: open the web interface for details.", color = FPMuted, fontSize = 12.sp)
            }
            items(ep.vms, key = { "vm-${ep.id}-${it.node}-${it.vmid}" }) { vm ->
                var open by remember { mutableStateOf(false) }
                GlassCard(Modifier.fillMaxWidth().clickable { open = !open }) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("${vm.name ?: "VM"}  (${vm.vmid})", color = FPOnBackground, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            Text("${vm.node} · ${if (vm.type == "lxc") "Container" else "VM"}", color = FPMuted, fontSize = 11.sp)
                            if (vm.status == "running") {
                                Text("CPU ${((vm.cpu ?: 0.0) * 100).toInt()}% · RAM ${mb(vm.mem)}/${mb(vm.maxmem)} MB",
                                     color = FPMuted, fontSize = 11.sp)
                            }
                        }
                        StatusBadge(vm.status)
                    }
                    if (open && me?.isAdmin == true && vm.vmid != null) {
                        Spacer(Modifier.height(10.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (vm.status != "running") {
                                ActionButton("Start", FPSuccess, Modifier.weight(1f)) { viewModel.action(ep, vm, "start") }
                            } else {
                                ActionButton("Shut down", FPWarning, Modifier.weight(1f)) { confirm = Triple(ep, vm, "shutdown") }
                                ActionButton("Reboot", FPWarning, Modifier.weight(1f)) { confirm = Triple(ep, vm, "reboot") }
                                ActionButton("Stop", FPError, Modifier.weight(1f)) { confirm = Triple(ep, vm, "stop") }
                            }
                        }
                    } else if (open && me?.isAdmin != true) {
                        Text("Power actions need an admin account and a read/write token.", color = FPMuted, fontSize = 11.sp)
                    }
                }
            }
        }
    }
}

// ── HW Monitor ───────────────────────────────────────────────────────────────

@Composable
fun HwMonitorScreen(viewModel: HwViewModel, me: Me?) {
    val servers by viewModel.servers.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()
    val message by viewModel.message.collectAsState()
    var confirmStress by remember { mutableStateOf<HwServer?>(null) }

    ActionMessage(message, viewModel::clearMessage)
    confirmStress?.let { s ->
        ConfirmDialog("Start the stress test on ${s.name}?",
            "CPU, RAM, disks and GPU run at full load until you stop it.",
            onConfirm = { viewModel.stress(s, true); confirmStress = null }, onDismiss = { confirmStress = null })
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item { ScreenHeader("HW Monitor", Icons.Default.Memory, viewModel::refresh) }
        when {
            loading && servers.isEmpty() -> item { LoadingState() }
            error != null && servers.isEmpty() -> item { ErrorState(error!!, viewModel::refresh) }
            servers.isEmpty() -> item { EmptyCard("No servers in the HW Monitor yet.") }
        }
        items(servers, key = { it.id }) { s ->
            GlassCard(Modifier.fillMaxWidth()) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Column {
                        Text(s.name, color = FPOnBackground, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                        Text(s.ip, color = FPMuted, fontSize = 12.sp)
                    }
                    StatusBadge(if (s.online) "online" else "offline")
                }
                if (s.online) {
                    Spacer(Modifier.height(10.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Column(Modifier.weight(1f)) { Text("CPU temp", color = FPMuted, fontSize = 11.sp); TempIndicator(s.cpuTemp) }
                        Column(Modifier.weight(1f)) {
                            Text("CPU load", color = FPMuted, fontSize = 11.sp)
                            Text(s.cpuPct?.let { "${it.toInt()}%" } ?: "–", color = FPPrimary, fontWeight = FontWeight.Bold)
                        }
                        s.gpuTemp?.let {
                            Column(Modifier.weight(1f)) {
                                Text("GPU ${s.gpuVendor?.uppercase().orEmpty()}", color = FPMuted, fontSize = 11.sp)
                                TempIndicator(it)
                            }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    val total = s.ramTotalMb ?: 0
                    LabeledProgress("RAM", if (total > 0) (s.ramUsedMb ?: 0).toFloat() / total else 0f,
                        "${s.ramUsedMb ?: 0} / $total MB", FPSecondary)
                    Spacer(Modifier.height(6.dp))
                    Text("↓ ${s.netRxKbps?.toInt() ?: 0} KB/s   ↑ ${s.netTxKbps?.toInt() ?: 0} KB/s", color = FPOnSurface, fontSize = 12.sp)
                    s.fans.filter { it.rpm != null }.forEach { fan ->
                        Text("${fan.label ?: fan.name ?: "Fan"}: ${fan.rpm!!.toInt()} RPM", color = FPOnSurface, fontSize = 11.sp)
                    }
                    if (s.stressTestRunning) {
                        Text("Stress test running${s.stressPhase?.let { ": $it" }.orEmpty()}", color = FPWarning, fontSize = 12.sp,
                             modifier = Modifier.padding(top = 6.dp))
                    }
                }
                if (me?.isOperator == true) {
                    Spacer(Modifier.height(10.dp))
                    if (s.stressTestRunning) ActionButton("Stop stress test", FPError, Modifier.fillMaxWidth()) { viewModel.stress(s, false) }
                    else if (s.online) ActionButton("Start stress test", FPWarning, Modifier.fillMaxWidth()) { confirmStress = s }
                }
            }
        }
    }
}

// ── Fans ─────────────────────────────────────────────────────────────────────

@Composable
fun FanScreen(viewModel: FanViewModel, me: Me?) {
    val controllers by viewModel.controllers.collectAsState()
    val loading by viewModel.loading.collectAsState()
    val error by viewModel.error.collectAsState()
    val message by viewModel.message.collectAsState()

    ActionMessage(message, viewModel::clearMessage)

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FPBackground).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item { ScreenHeader("Fans", Icons.Default.Air, viewModel::refresh) }
        when {
            loading && controllers.isEmpty() -> item { LoadingState() }
            error != null && controllers.isEmpty() -> item { ErrorState(error!!, viewModel::refresh) }
            controllers.isEmpty() -> item { EmptyCard("No fan controllers yet. Add them under Fans in the web interface.") }
        }
        items(controllers, key = { it.device.id }) { fc ->
            val st = fc.status
            GlassCard(Modifier.fillMaxWidth()) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Column {
                        Text(fc.device.name, color = FPOnBackground, fontWeight = FontWeight.SemiBold)
                        Text("${fc.device.controllerType.replace('_', ' ')} · ${fc.device.host}", color = FPSecondary, fontSize = 11.sp)
                    }
                    StatusBadge(when { st == null -> "unknown"; st.ok -> "ok"; else -> "failed" })
                }
                st?.error?.let { Text(it, color = FPError, fontSize = 12.sp) }
                st?.temperatures?.take(4)?.forEach { t ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(t.label, color = FPMuted, fontSize = 11.sp, modifier = Modifier.weight(1f))
                        TempIndicator(t.value)
                    }
                }
                st?.fans?.forEach { f ->
                    Text("${f.label}: ${f.rpm?.let { "$it RPM" } ?: f.percent?.let { "${it.toInt()}%" } ?: "–"}",
                         color = FPOnSurface, fontSize = 11.sp)
                }
                if (me?.isOperator == true) {
                    st?.pwmNodes?.forEach { node ->
                        FanSlider(node.label ?: node.path.substringAfterLast('/'), node.percent ?: 50) { percent ->
                            viewModel.setSpeed(fc.device, node.path, percent)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FanSlider(label: String, initial: Int, onSet: (Int) -> Unit) {
    var value by remember(initial) { mutableFloatStateOf(initial.toFloat()) }
    Spacer(Modifier.height(8.dp))
    Text("$label: ${value.toInt()}%", color = FPOnSurface, fontSize = 13.sp)
    Row(verticalAlignment = Alignment.CenterVertically) {
        Slider(value = value, onValueChange = { value = it }, valueRange = 0f..100f, modifier = Modifier.weight(1f),
               colors = SliderDefaults.colors(thumbColor = FPPrimary, activeTrackColor = FPPrimary))
        Spacer(Modifier.width(8.dp))
        Button(onClick = { onSet(value.toInt()) }, colors = ButtonDefaults.buttonColors(containerColor = FPPrimaryVariant),
               contentPadding = PaddingValues(horizontal = 12.dp)) { Text("Set", fontSize = 12.sp) }
    }
}
