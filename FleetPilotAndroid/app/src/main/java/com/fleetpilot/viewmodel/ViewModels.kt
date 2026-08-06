package com.fleetpilot.viewmodel

import android.app.Application
import androidx.datastore.preferences.core.edit
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.fleetpilot.data.api.ApiClient
import com.fleetpilot.data.api.PrefsKeys
import com.fleetpilot.data.api.dataStore
import com.fleetpilot.data.models.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

// ── Auth ViewModel ────────────────────────────────────────────────────────────
class AuthViewModel(app: Application) : AndroidViewModel(app) {
    private val _loginState = MutableStateFlow<LoginState>(LoginState.Idle)
    val loginState: StateFlow<LoginState> = _loginState

    val serverUrl = app.dataStore.data.map { it[PrefsKeys.SERVER_URL] ?: "" }
    val authToken = app.dataStore.data.map { it[PrefsKeys.AUTH_TOKEN] }

    fun login(serverUrl: String, username: String, password: String) {
        viewModelScope.launch {
            _loginState.value = LoginState.Loading
            try {
                val api = ApiClient.getApi(getApplication(), serverUrl)
                val resp = api.login(LoginRequest(username, password))
                if (resp.isSuccessful && resp.body() != null) {
                    val body = resp.body()!!
                    getApplication<Application>().dataStore.edit { prefs ->
                        prefs[PrefsKeys.SERVER_URL] = serverUrl
                        prefs[PrefsKeys.AUTH_TOKEN] = body.token
                        prefs[PrefsKeys.USERNAME] = body.username
                    }
                    ApiClient.reset()
                    _loginState.value = LoginState.Success(body)
                } else {
                    _loginState.value = LoginState.Error("Ungültige Zugangsdaten")
                }
            } catch (e: Exception) {
                _loginState.value = LoginState.Error("Verbindungsfehler: ${e.message}")
            }
        }
    }

    fun logout() {
        viewModelScope.launch {
            getApplication<Application>().dataStore.edit { prefs ->
                prefs.remove(PrefsKeys.AUTH_TOKEN)
            }
            ApiClient.reset()
            _loginState.value = LoginState.Idle
        }
    }
}

sealed class LoginState {
    object Idle : LoginState()
    object Loading : LoginState()
    data class Success(val response: LoginResponse) : LoginState()
    data class Error(val message: String) : LoginState()
}

// ── Dashboard ViewModel ───────────────────────────────────────────────────────
class DashboardViewModel(app: Application) : AndroidViewModel(app) {
    private val _summary = MutableStateFlow<DashboardSummary?>(null)
    val summary: StateFlow<DashboardSummary?> = _summary
    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    init { load() }

    fun load() {
        viewModelScope.launch {
            _loading.value = true
            _error.value = null
            try {
                val api = ApiClient.getApi(getApplication())
                val resp = api.getDashboardSummary()
                if (resp.isSuccessful) _summary.value = resp.body()
                else _error.value = "Fehler: ${resp.code()}"
            } catch (e: Exception) {
                _error.value = e.message
            } finally {
                _loading.value = false
            }
        }
    }
}

// ── Hosts ViewModel ───────────────────────────────────────────────────────────
class HostsViewModel(app: Application) : AndroidViewModel(app) {
    private val _hosts = MutableStateFlow<List<ServerHost>>(emptyList())
    val hosts: StateFlow<List<ServerHost>> = _hosts
    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error
    private val _actionResult = MutableStateFlow<String?>(null)
    val actionResult: StateFlow<String?> = _actionResult

    init { load() }

    fun load() {
        viewModelScope.launch {
            _loading.value = true
            try {
                val api = ApiClient.getApi(getApplication())
                val resp = api.getHosts()
                if (resp.isSuccessful) _hosts.value = resp.body() ?: emptyList()
                else _error.value = "Fehler: ${resp.code()}"
            } catch (e: Exception) {
                _error.value = e.message
            } finally {
                _loading.value = false
            }
        }
    }

    fun deleteHost(id: Int) {
        viewModelScope.launch {
            try {
                ApiClient.getApi(getApplication()).deleteHost(id)
                load()
            } catch (e: Exception) { _error.value = e.message }
        }
    }

    fun checkStatus(id: Int) {
        viewModelScope.launch {
            try {
                val resp = ApiClient.getApi(getApplication()).checkHostStatus(id)
                if (resp.isSuccessful) load()
            } catch (e: Exception) { _error.value = e.message }
        }
    }

    fun executeCommand(id: Int, command: String) {
        viewModelScope.launch {
            try {
                val resp = ApiClient.getApi(getApplication()).executeCommand(id, ExecuteRequest(command))
                if (resp.isSuccessful) {
                    _actionResult.value = resp.body()?.output ?: "Kein Output"
                }
            } catch (e: Exception) { _error.value = e.message }
        }
    }

    fun clearActionResult() { _actionResult.value = null }
}

// ── VM ViewModel ──────────────────────────────────────────────────────────────
class VmViewModel(app: Application) : AndroidViewModel(app) {
    private val _endpoints = MutableStateFlow<List<VmEndpoint>>(emptyList())
    val endpoints: StateFlow<List<VmEndpoint>> = _endpoints
    private val _allVms = MutableStateFlow<List<AllVmsResponse>>(emptyList())
    val allVms: StateFlow<List<AllVmsResponse>> = _allVms
    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error
    private val _actionResult = MutableStateFlow<String?>(null)
    val actionResult: StateFlow<String?> = _actionResult

    init { load() }

    fun load() {
        viewModelScope.launch {
            _loading.value = true
            try {
                val api = ApiClient.getApi(getApplication())
                val epResp = api.getVmEndpoints()
                if (epResp.isSuccessful) _endpoints.value = epResp.body() ?: emptyList()
                val vmsResp = api.getAllVms()
                if (vmsResp.isSuccessful) _allVms.value = vmsResp.body() ?: emptyList()
            } catch (e: Exception) {
                _error.value = e.message
            } finally {
                _loading.value = false
            }
        }
    }

    fun vmAction(endpointId: Int, node: String, vmId: String, type: String, action: String) {
        viewModelScope.launch {
            try {
                val resp = ApiClient.getApi(getApplication())
                    .vmAction(endpointId, node, vmId, type, VmActionRequest(action))
                if (resp.isSuccessful) {
                    _actionResult.value = "Aktion '$action' erfolgreich"
                    delay(1000)
                    load()
                } else {
                    _error.value = "Aktion fehlgeschlagen: ${resp.code()}"
                }
            } catch (e: Exception) { _error.value = e.message }
        }
    }

    fun clearActionResult() { _actionResult.value = null }
}

// ── HW Monitor ViewModel ──────────────────────────────────────────────────────
class HwViewModel(app: Application) : AndroidViewModel(app) {
    private val _servers = MutableStateFlow<List<HwServer>>(emptyList())
    val servers: StateFlow<List<HwServer>> = _servers
    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error
    private val _alerts = MutableStateFlow<List<HwAlert>>(emptyList())
    val alerts: StateFlow<List<HwAlert>> = _alerts

    init {
        load()
        startAutoRefresh()
    }

    private fun startAutoRefresh() {
        viewModelScope.launch {
            while (true) {
                delay(8000)
                loadSilent()
            }
        }
    }

    fun load() {
        viewModelScope.launch {
            _loading.value = true
            loadSilent()
            _loading.value = false
        }
    }

    private suspend fun loadSilent() {
        try {
            val api = ApiClient.getApi(getApplication())
            val resp = api.getHwServers()
            if (resp.isSuccessful) _servers.value = resp.body() ?: emptyList()
        } catch (e: Exception) { _error.value = e.message }
    }

    fun startStress(id: Int) {
        viewModelScope.launch {
            try { ApiClient.getApi(getApplication()).startStressTest(id); load() }
            catch (e: Exception) { _error.value = e.message }
        }
    }

    fun stopStress(id: Int) {
        viewModelScope.launch {
            try { ApiClient.getApi(getApplication()).stopStressTest(id); load() }
            catch (e: Exception) { _error.value = e.message }
        }
    }

    fun ackAlert(alertId: Int, note: String?) {
        viewModelScope.launch {
            try {
                ApiClient.getApi(getApplication()).ackAlert(alertId, AckAlertRequest(alertId, note))
                load()
            } catch (e: Exception) { _error.value = e.message }
        }
    }

    fun loadAlerts(serverId: Int) {
        viewModelScope.launch {
            try {
                val resp = ApiClient.getApi(getApplication()).getAlerts(serverId)
                if (resp.isSuccessful) _alerts.value = resp.body() ?: emptyList()
            } catch (e: Exception) { _error.value = e.message }
        }
    }
}

// ── Fan ViewModel ─────────────────────────────────────────────────────────────
class FanViewModel(app: Application) : AndroidViewModel(app) {
    private val _controllers = MutableStateFlow<List<FanController>>(emptyList())
    val controllers: StateFlow<List<FanController>> = _controllers
    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error
    private val _actionResult = MutableStateFlow<String?>(null)
    val actionResult: StateFlow<String?> = _actionResult

    init { load() }

    fun load() {
        viewModelScope.launch {
            _loading.value = true
            try {
                val resp = ApiClient.getApi(getApplication()).getFanControllers()
                if (resp.isSuccessful) _controllers.value = resp.body() ?: emptyList()
            } catch (e: Exception) { _error.value = e.message }
            finally { _loading.value = false }
        }
    }

    fun setFan(controllerId: Int, channel: String, dutyCycle: Int) {
        viewModelScope.launch {
            try {
                val resp = ApiClient.getApi(getApplication())
                    .setFan(controllerId, FanSetRequest(channel, dutyCycle))
                _actionResult.value = if (resp.isSuccessful) "Lüfter auf $dutyCycle% gesetzt" else "Fehler"
            } catch (e: Exception) { _error.value = e.message }
        }
    }

    fun clearActionResult() { _actionResult.value = null }
}
