// SPDX-FileCopyrightText: Copyright the FleetPilot contributors
// SPDX-License-Identifier: GPL-3.0-or-later
package com.fleetpilot.data.models

import com.google.gson.annotations.SerializedName

// JSON shapes of the FleetPilotCS REST API (ASP.NET, camelCase). Every field has a
// default so a missing field never crashes the app.

// ── Authentication ───────────────────────────────────────────────────────────
data class LoginRequest(val username: String, val password: String)

data class LoginResponse(
    val token: String = "",
    val username: String = "",
    val role: String = "",
    val expires: String? = null,
)

// ── Dashboard ────────────────────────────────────────────────────────────────
data class HostCounts(val total: Int = 0, val online: Int = 0, val offline: Int = 0)

data class DashboardSummary(
    @SerializedName("hosts") private val _hosts: HostCounts? = null,
    val vmEndpoints: Int = 0,
    val backupServers: Int = 0,
    val hwServers: Int = 0,
    val activeAlerts: Int = 0,
    val fanControllers: Int = 0,
    val lastUpdated: String? = null,
) {
    val hosts: HostCounts get() = _hosts ?: HostCounts()
}

// ── Hosts ────────────────────────────────────────────────────────────────────
data class ServerHost(
    val id: Int = 0,
    val name: String = "",
    val address: String = "",
    val user: String = "root",
    val port: Int = 22,
    val mac: String? = null,
    val description: String? = null,
    val group: String? = null,
    val location: String? = null,
    val environment: String? = null,
    val criticality: String? = null,
    val lastSeen: String? = null,
    val isOnline: Boolean = false,
)

data class HostStatus(
    val id: Int = 0,
    val name: String = "",
    val address: String = "",
    val isOnline: Boolean = false,
    val lastSeen: String? = null,
)

data class ExecuteRequest(val command: String, val timeoutSeconds: Int = 30)

data class ExecuteResponse(
    val success: Boolean = false,
    val output: String? = null,
    val error: String? = null,
    val exitCode: Int? = null,
)

// ── Virtual machines (Proxmox) ───────────────────────────────────────────────
data class VmEndpoint(
    val id: Int = 0,
    val name: String = "",
    val address: String = "",
    val port: Int = 8006,
    val type: String = "proxmox",
    val node: String? = null,
)

data class EndpointRef(val id: Int = 0, val name: String = "")

data class VmInfo(
    val vmId: String = "",
    val name: String = "",
    val status: String = "",
    val cpus: Int = 0,
    val maxMem: Long = 0,
    val mem: Long = 0,
    val disk: Long = 0,
    val uptime: Double = 0.0,
    val type: String = "qemu",
    val node: String = "",
    val tags: String? = null,
    val cpuUsage: Double? = null,
)

data class AllVmsResponse(
    @SerializedName("endpoint") private val _endpoint: EndpointRef? = null,
    @SerializedName("vms") private val _vms: List<VmInfo>? = null,
) {
    val endpoint: EndpointRef get() = _endpoint ?: EndpointRef()
    val vms: List<VmInfo> get() = _vms ?: emptyList()
}

data class VmActionRequest(val action: String)

// ── HW Monitor ───────────────────────────────────────────────────────────────
data class FanData(
    val name: String = "",
    val rpm: Double? = null,
    val dutyCycle: Double? = null,
    val temp: Double? = null,
)

data class LiveMetrics(
    val cpuTemp: Double? = null,
    val cpuUsage: Double? = null,
    val gpuTemp: Double? = null,
    val gpuUsage: Double? = null,
    val gpuVendor: String? = null,
    val ramUsedMb: Long? = null,
    val ramTotalMb: Long? = null,
    val netRxKbps: Double? = null,
    val netTxKbps: Double? = null,
    val diskReadKbps: Double? = null,
    val diskWriteKbps: Double? = null,
    @SerializedName("fans") private val _fans: List<FanData>? = null,
    val isOnline: Boolean = false,
    val error: String? = null,
) {
    val fans: List<FanData> get() = _fans ?: emptyList()
}

data class HwServer(
    val id: Int = 0,
    val name: String = "",
    val address: String = "",
    val port: Int = 22,
    val sshUser: String = "root",
    val stressTestRunning: Boolean = false,
    val lastSeen: String? = null,
    @SerializedName("metrics") private val _metrics: LiveMetrics? = null,
) {
    val metrics: LiveMetrics get() = _metrics ?: LiveMetrics()
}

data class HwAlert(
    val id: Int = 0,
    val serverId: Int = 0,
    val alertType: String = "",
    val message: String = "",
    val acknowledged: Boolean = false,
    val ackNote: String? = null,
    val createdAt: String? = null,
)

data class AckAlertRequest(val alertId: Int, val note: String?)

// ── Fan controllers ──────────────────────────────────────────────────────────
data class FanController(
    val id: Int = 0,
    val name: String = "",
    val hostId: Int = 0,
    val controllerType: String = "lm_sensors",
    val matchString: String? = null,
    val lastPolled: String? = null,
)

data class FanSetRequest(val channel: String, val dutyCycle: Int)

data class SimpleResult(val success: Boolean = false, val error: String? = null)
