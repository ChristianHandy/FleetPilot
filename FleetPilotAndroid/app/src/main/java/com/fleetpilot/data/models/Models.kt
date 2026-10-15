// SPDX-FileCopyrightText: Copyright the FleetPilot contributors
// SPDX-License-Identifier: GPL-3.0-or-later
package com.fleetpilot.data.models

import com.google.gson.annotations.SerializedName

// JSON shapes of FleetPilot's REST API (/api/...), as returned for a personal API token.
// Every field has a default and lists are read through non-null accessors, so a
// missing or null field never crashes the app.

// ── Account ──────────────────────────────────────────────────────────────────
data class Me(
    val username: String = "",
    @SerializedName("roles") private val _roles: List<String>? = null,
    val auth: String = "",
    val scope: String = "read",
) {
    val roles: List<String> get() = _roles ?: emptyList()
    val canWrite: Boolean get() = scope == "write"
    val isOperator: Boolean get() = canWrite && roles.any { it == "operator" || it == "admin" }
    val isAdmin: Boolean get() = canWrite && "admin" in roles
}

/** The answer of host, VM and fan actions. */
data class ActionResult(
    val ok: Boolean = false,
    val message: String? = null,
    val error: String? = null,
    val output: String? = null,
) {
    val text: String get() = message ?: error ?: output ?: if (ok) "Done" else "Failed"
}

// ── Hosts ────────────────────────────────────────────────────────────────────
data class Host(
    val name: String = "",
    val host: String = "",
    val user: String = "",
    val port: Int = 22,
    val environment: String = "",
    val os: String = "",
    val description: String = "",
    val group: String = "",
    /** manageable | web_only | unreachable | unknown */
    val state: String = "unknown",
    @SerializedName("can_wake") val canWake: Boolean = false,
) {
    val reachable: Boolean get() = state == "manageable" || state == "web_only"
}

// ── Virtual machines ─────────────────────────────────────────────────────────
data class Vm(
    val vmid: Int? = null,
    val name: String? = null,
    val status: String = "unknown",
    val node: String = "",
    val type: String = "qemu",
    val cpu: Double? = null,
    val cpus: Int? = null,
    val mem: Long? = null,
    val maxmem: Long? = null,
    val uptime: Long? = null,
)

data class VmEndpoint(
    val id: Int = 0,
    val name: String = "",
    val platform: String = "",
    @SerializedName("vms") private val _vms: List<Vm>? = null,
    val error: String? = null,
) {
    val vms: List<Vm> get() = _vms ?: emptyList()
}

data class VmsResponse(@SerializedName("endpoints") private val _endpoints: List<VmEndpoint>? = null) {
    val endpoints: List<VmEndpoint> get() = _endpoints ?: emptyList()
}

// ── HW Monitor ───────────────────────────────────────────────────────────────
data class HwFan(val name: String? = null, val label: String? = null, val rpm: Double? = null)

data class HwServer(
    val id: Int = 0,
    val name: String = "",
    val ip: String = "",
    val reachable: Int? = null,
    @SerializedName("cpu_pct") val cpuPct: Double? = null,
    @SerializedName("cpu_temp") val cpuTemp: Double? = null,
    @SerializedName("ram_used_mb") val ramUsedMb: Long? = null,
    @SerializedName("ram_total_mb") val ramTotalMb: Long? = null,
    @SerializedName("net_rx_kbps") val netRxKbps: Double? = null,
    @SerializedName("net_tx_kbps") val netTxKbps: Double? = null,
    @SerializedName("gpu_temp") val gpuTemp: Double? = null,
    @SerializedName("gpu_vendor") val gpuVendor: String? = null,
    @SerializedName("stress_running") val stressRunning: Int? = null,
    @SerializedName("stress_phase") val stressPhase: String? = null,
    @SerializedName("fans") private val _fans: List<HwFan>? = null,
) {
    val online: Boolean get() = reachable == 1
    val stressTestRunning: Boolean get() = stressRunning == 1
    val fans: List<HwFan> get() = _fans ?: emptyList()
}

data class HwAction(val action: String)

// ── Fan controllers ──────────────────────────────────────────────────────────
data class FanDevice(
    val id: Int = 0,
    val name: String = "",
    val host: String = "",
    @SerializedName("controller_type") val controllerType: String = "",
    val enabled: Int = 1,
)

data class FanReading(val label: String = "", val rpm: Int? = null, val percent: Double? = null)

data class TempReading(val label: String = "", val value: Double? = null)

/** A fan channel that can be set: a sysfs PWM node, or a controller channel. */
data class PwmNode(val path: String = "", val label: String? = null, val percent: Int? = null, val channel: Int? = null)

data class FanStatus(
    val ok: Boolean = false,
    val error: String? = null,
    @SerializedName("fans") private val _fans: List<FanReading>? = null,
    @SerializedName("temperatures") private val _temps: List<TempReading>? = null,
    @SerializedName("pwm_nodes") private val _pwm: List<PwmNode>? = null,
) {
    val fans: List<FanReading> get() = _fans ?: emptyList()
    val temperatures: List<TempReading> get() = _temps ?: emptyList()
    val pwmNodes: List<PwmNode> get() = _pwm ?: emptyList()
}

// ── Dashboard sources ────────────────────────────────────────────────────────
data class SmartSummary(
    val total: Int = 0,
    @SerializedName("counts") private val _counts: Map<String, Int>? = null,
    @SerializedName("active_alerts") val activeAlerts: Int = 0,
) {
    val counts: Map<String, Int> get() = _counts ?: emptyMap()
    val problems: Int get() = (counts["WARNING"] ?: 0) + (counts["CRITICAL"] ?: 0) + (counts["FAILED"] ?: 0)
}

data class VulnSummary(
    val total: Int = 0,
    val critical: Int = 0,
    val high: Int = 0,
    val fixable: Int = 0,
    @SerializedName("last_scan") val lastScan: String? = null,
)

data class VulnResponse(@SerializedName("summary") private val _summary: VulnSummary? = null) {
    val summary: VulnSummary get() = _summary ?: VulnSummary()
}

data class Router(val name: String = "", val online: Boolean = false, val updates: Int? = null)

data class RoutersResponse(@SerializedName("routers") private val _routers: List<Router>? = null) {
    val routers: List<Router> get() = _routers ?: emptyList()
}

data class BackupServer(
    val name: String = "",
    @SerializedName("server_type") val serverType: String = "",
    @SerializedName("last_status") val lastStatus: String? = null,
    val enabled: Int = 1,
)

/** What the dashboard shows, collected from several endpoints. Null means "not available". */
data class DashboardSummary(
    val hostsTotal: Int = 0,
    val hostsReachable: Int = 0,
    val vmsRunning: Int? = null,
    val vmsTotal: Int? = null,
    val disks: SmartSummary? = null,
    val vulnerabilities: VulnSummary? = null,
    val routersOnline: Int? = null,
    val routersTotal: Int? = null,
    val backupProblems: Int? = null,
    val backupTotal: Int? = null,
)
