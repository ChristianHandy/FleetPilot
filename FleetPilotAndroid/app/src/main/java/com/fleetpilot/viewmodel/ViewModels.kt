// SPDX-FileCopyrightText: Copyright the FleetPilot contributors
// SPDX-License-Identifier: GPL-3.0-or-later
package com.fleetpilot.viewmodel

import android.app.Application
import androidx.datastore.preferences.core.edit
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.fleetpilot.data.api.ApiClient
import com.fleetpilot.data.api.FleetPilotApi
import com.fleetpilot.data.api.PrefsKeys
import com.fleetpilot.data.api.UntrustedCertificateException
import com.fleetpilot.data.api.dataStore
import com.fleetpilot.data.models.*
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import retrofit2.Response

/** A readable message for a failed request. */
fun <T> Response<T>.problem(): String = when (code()) {
    401, 302, 303 -> "The API token is not valid any more. Sign out and enter a new one."
    403 -> "Your account or token is not allowed to do this."
    404 -> "Not found on the server (is FleetPilot up to date?)."
    else -> "The server answered ${code()}."
}

fun Throwable.problem(): String = when (this) {
    is java.net.UnknownHostException -> "Server not found. Check the address."
    is java.net.ConnectException, is java.net.SocketTimeoutException -> "The server does not answer."
    is javax.net.ssl.SSLException -> "Secure connection failed: ${message ?: "certificate problem"}"
    else -> message ?: this::class.java.simpleName
}

/** Shared state handling for the screens: loading flag, error and a short action message. */
abstract class ApiViewModel(app: Application) : AndroidViewModel(app) {
    protected val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading
    protected val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error
    protected val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message

    fun clearMessage() { _message.value = null }

    protected suspend fun api(): FleetPilotApi = ApiClient.getApi(getApplication())

    /** Runs [block] with the loading flag set; failures become [error]. */
    protected fun load(block: suspend () -> Unit) {
        viewModelScope.launch {
            _loading.value = true
            _error.value = null
            try { block() } catch (e: Exception) { _error.value = e.problem() } finally { _loading.value = false }
        }
    }

    /** Runs an action and shows its result as [message], then reloads. */
    protected fun act(call: suspend FleetPilotApi.() -> Response<ActionResult>, reload: () -> Unit) {
        viewModelScope.launch {
            try {
                val resp = api().call()
                _message.value = if (resp.isSuccessful) resp.body()?.text ?: "Done"
                                 else resp.body()?.text ?: resp.problem()
                reload()
            } catch (e: Exception) { _message.value = e.problem() }
        }
    }
}

// ── Sign-in ──────────────────────────────────────────────────────────────────
sealed class LoginState {
    object Idle : LoginState()
    object Loading : LoginState()
    data class ConfirmCertificate(val fingerprint: String, val subject: String) : LoginState()
    data class Success(val me: Me) : LoginState()
    data class Error(val message: String) : LoginState()
}

class AuthViewModel(app: Application) : AndroidViewModel(app) {
    private val _loginState = MutableStateFlow<LoginState>(LoginState.Idle)
    val loginState: StateFlow<LoginState> = _loginState

    val authToken = app.dataStore.data.map { it[PrefsKeys.AUTH_TOKEN] }
    val savedServer = app.dataStore.data.map { it[PrefsKeys.SERVER_URL] ?: "" }

    private val _me = MutableStateFlow<Me?>(null)
    val me: StateFlow<Me?> = _me

    /** Checks the server and token; asks to confirm a certificate Android does not trust. */
    fun login(serverUrl: String, token: String, trustedPin: String? = null) {
        viewModelScope.launch {
            _loginState.value = LoginState.Loading
            try {
                val base = ApiClient.normalise(serverUrl)
                var pin = trustedPin
                if (pin == null) {
                    val untrusted = ApiClient.probeCertificate(base)
                    if (untrusted != null) {
                        _loginState.value = LoginState.ConfirmCertificate(untrusted.fingerprint, untrusted.subject)
                        return@launch
                    }
                }
                ApiClient.reset()
                val resp = ApiClient.create(base, token.trim(), pin).me()
                val me = resp.body()
                if (resp.isSuccessful && me != null && me.username.isNotEmpty()) {
                    getApplication<Application>().dataStore.edit { prefs ->
                        prefs[PrefsKeys.SERVER_URL] = base
                        prefs[PrefsKeys.AUTH_TOKEN] = token.trim()
                        prefs[PrefsKeys.USERNAME] = me.username
                        if (pin != null) prefs[PrefsKeys.CERT_PIN] = pin else prefs.remove(PrefsKeys.CERT_PIN)
                    }
                    ApiClient.reset()
                    _me.value = me
                    _loginState.value = LoginState.Success(me)
                } else {
                    _loginState.value = LoginState.Error(
                        if (resp.isSuccessful || resp.code() in listOf(302, 303, 401)) "This API token is not valid."
                        else resp.problem())
                }
            } catch (e: Exception) {
                _loginState.value = LoginState.Error(e.problem())
            }
        }
    }

    fun cancelCertificate() { _loginState.value = LoginState.Idle }

    /** Refreshes who is signed in (roles and token scope decide which buttons are shown). */
    fun refreshMe() {
        viewModelScope.launch {
            try { ApiClient.getApi(getApplication()).me().body()?.let { _me.value = it } } catch (_: Exception) { }
        }
    }

    fun logout() {
        viewModelScope.launch {
            getApplication<Application>().dataStore.edit { prefs ->
                prefs.remove(PrefsKeys.AUTH_TOKEN)
                prefs.remove(PrefsKeys.CERT_PIN)
            }
            ApiClient.reset()
            _me.value = null
            _loginState.value = LoginState.Idle
        }
    }
}

// ── Dashboard ────────────────────────────────────────────────────────────────
class DashboardViewModel(app: Application) : ApiViewModel(app) {
    private val _summary = MutableStateFlow<DashboardSummary?>(null)
    val summary: StateFlow<DashboardSummary?> = _summary

    init { refresh() }

    fun refresh() = load {
        val api = api()
        val hosts = viewModelScope.async { api.hosts() }
        val vms = viewModelScope.async { runCatching { api.vms().body() }.getOrNull() }
        val smart = viewModelScope.async { runCatching { api.smartSummary().body() }.getOrNull() }
        val vulns = viewModelScope.async { runCatching { api.vulnerabilities().body() }.getOrNull() }
        val routers = viewModelScope.async { runCatching { api.routers().body() }.getOrNull() }
        val backups = viewModelScope.async { runCatching { api.backupServers().body() }.getOrNull() }

        val hostResp = hosts.await()
        if (!hostResp.isSuccessful) throw IllegalStateException(hostResp.problem())
        val hostList = hostResp.body().orEmpty()
        val allVms = vms.await()?.endpoints?.flatMap { it.vms }
        val routerList = routers.await()?.routers
        val backupList = backups.await()?.filter { it.enabled == 1 }
        _summary.value = DashboardSummary(
            hostsTotal = hostList.size,
            hostsReachable = hostList.count { it.reachable },
            vmsRunning = allVms?.count { it.status == "running" },
            vmsTotal = allVms?.size,
            disks = smart.await(),
            vulnerabilities = vulns.await()?.summary,
            routersOnline = routerList?.count { it.online },
            routersTotal = routerList?.size,
            backupProblems = backupList?.count { it.lastStatus == "error" },
            backupTotal = backupList?.size,
        )
    }
}

// ── Hosts ────────────────────────────────────────────────────────────────────
class HostsViewModel(app: Application) : ApiViewModel(app) {
    private val _hosts = MutableStateFlow<List<Host>>(emptyList())
    val hosts: StateFlow<List<Host>> = _hosts

    init { refresh() }

    fun refresh() = load {
        val resp = api().hosts()
        if (resp.isSuccessful) _hosts.value = resp.body().orEmpty().sortedBy { it.name.lowercase() }
        else throw IllegalStateException(resp.problem())
    }

    fun wake(host: Host) = act({ wakeHost(host.name) }, ::refresh)
    fun shutdown(host: Host) = act({ shutdownHost(host.name) }, ::refresh)
}

// ── Virtual machines ─────────────────────────────────────────────────────────
class VmViewModel(app: Application) : ApiViewModel(app) {
    private val _endpoints = MutableStateFlow<List<VmEndpoint>>(emptyList())
    val endpoints: StateFlow<List<VmEndpoint>> = _endpoints

    init { refresh() }

    fun refresh() = load {
        val resp = api().vms()
        if (resp.isSuccessful) _endpoints.value = resp.body()?.endpoints.orEmpty()
        else throw IllegalStateException(resp.problem())
    }

    fun action(endpoint: VmEndpoint, vm: Vm, action: String) {
        val vmid = vm.vmid ?: return
        act({ vmAction(endpoint.id, vm.node, vmid, vm.type, action) }) {
            viewModelScope.launch { delay(1500); refresh() }   // Proxmox needs a moment
        }
    }
}

// ── HW Monitor ───────────────────────────────────────────────────────────────
class HwViewModel(app: Application) : ApiViewModel(app) {
    private val _servers = MutableStateFlow<List<HwServer>>(emptyList())
    val servers: StateFlow<List<HwServer>> = _servers

    init {
        refresh()
        viewModelScope.launch {
            while (true) {                      // live values; stops with the screen
                delay(10_000)
                try { api().hwServers().body()?.let { _servers.value = it } } catch (_: Exception) { }
            }
        }
    }

    fun refresh() = load {
        val resp = api().hwServers()
        if (resp.isSuccessful) _servers.value = resp.body().orEmpty()
        else throw IllegalStateException(resp.problem())
    }

    fun stress(server: HwServer, start: Boolean) =
        act({ hwAction(server.id, HwAction(if (start) "start" else "stop")) }, ::refresh)
}

// ── Fans ─────────────────────────────────────────────────────────────────────
data class FanController(val device: FanDevice, val status: FanStatus?)

class FanViewModel(app: Application) : ApiViewModel(app) {
    private val _controllers = MutableStateFlow<List<FanController>>(emptyList())
    val controllers: StateFlow<List<FanController>> = _controllers

    init { refresh() }

    fun refresh() = load {
        val api = api()
        val resp = api.fanDevices()
        if (!resp.isSuccessful) throw IllegalStateException(resp.problem())
        val devices = resp.body().orEmpty().filter { it.enabled == 1 }
        _controllers.value = devices.map { d ->
            viewModelScope.async { FanController(d, runCatching { api.fanStatus(d.id).body() }.getOrNull()) }
        }.map { it.await() }
    }

    fun setSpeed(device: FanDevice, channel: String, percent: Int) =
        act({ setFan(device.id, channel, "fixed", percent) }, ::refresh)
}
