// SPDX-FileCopyrightText: Copyright the FleetPilot contributors
// SPDX-License-Identifier: GPL-3.0-or-later
package com.fleetpilot.data.api

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.fleetpilot.data.models.*
import kotlinx.coroutines.flow.first
import okhttp3.OkHttpClient
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.*
import java.util.concurrent.TimeUnit

/** Server address, sign-in token and user name, kept on the device. */
val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "fleetpilot")

object PrefsKeys {
    val SERVER_URL = stringPreferencesKey("server_url")
    val AUTH_TOKEN = stringPreferencesKey("auth_token")
    val USERNAME = stringPreferencesKey("username")
}

/** The FleetPilotCS REST API. */
interface FleetPilotApi {
    @POST("api/auth/login")
    suspend fun login(@Body request: LoginRequest): Response<LoginResponse>

    @GET("api/dashboard/summary")
    suspend fun getDashboardSummary(): Response<DashboardSummary>

    @GET("api/hosts")
    suspend fun getHosts(): Response<List<ServerHost>>

    @DELETE("api/hosts/{id}")
    suspend fun deleteHost(@Path("id") id: Int): Response<Unit>

    @GET("api/hosts/{id}/status")
    suspend fun checkHostStatus(@Path("id") id: Int): Response<HostStatus>

    @POST("api/hosts/{id}/execute")
    suspend fun executeCommand(@Path("id") id: Int, @Body request: ExecuteRequest): Response<ExecuteResponse>

    @GET("api/vm/endpoints")
    suspend fun getVmEndpoints(): Response<List<VmEndpoint>>

    @GET("api/vm/all")
    suspend fun getAllVms(): Response<List<AllVmsResponse>>

    @POST("api/vm/endpoints/{id}/vms/{node}/{vmId}/{type}/action")
    suspend fun vmAction(
        @Path("id") endpointId: Int,
        @Path("node") node: String,
        @Path("vmId") vmId: String,
        @Path("type") type: String,
        @Body request: VmActionRequest,
    ): Response<SimpleResult>

    @GET("api/hw/servers")
    suspend fun getHwServers(): Response<List<HwServer>>

    @POST("api/hw/servers/{id}/stress/start")
    suspend fun startStressTest(@Path("id") id: Int): Response<SimpleResult>

    @POST("api/hw/servers/{id}/stress/stop")
    suspend fun stopStressTest(@Path("id") id: Int): Response<SimpleResult>

    @GET("api/hw/servers/{id}/alerts")
    suspend fun getAlerts(@Path("id") serverId: Int): Response<List<HwAlert>>

    @POST("api/hw/alerts/{alertId}/ack")
    suspend fun ackAlert(@Path("alertId") alertId: Int, @Body request: AckAlertRequest): Response<SimpleResult>

    @GET("api/fans")
    suspend fun getFanControllers(): Response<List<FanController>>

    @POST("api/fans/{id}/set")
    suspend fun setFan(@Path("id") controllerId: Int, @Body request: FanSetRequest): Response<SimpleResult>
}

object ApiClient {
    @Volatile private var cached: Pair<String, FleetPilotApi>? = null

    /**
     * The API for [serverUrl], or for the saved server when it is null. The saved
     * sign-in token is sent as a bearer token. Call [reset] after signing in or out.
     */
    suspend fun getApi(context: Context, serverUrl: String? = null): FleetPilotApi {
        val prefs = context.dataStore.data.first()
        val base = normalise(serverUrl ?: prefs[PrefsKeys.SERVER_URL]
            ?: throw IllegalStateException("No FleetPilot server configured"))
        val token = if (serverUrl == null) prefs[PrefsKeys.AUTH_TOKEN] else null
        val key = "$base|${token.orEmpty()}"
        cached?.let { (k, api) -> if (k == key) return api }

        val http = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val request = chain.request().newBuilder()
                if (!token.isNullOrEmpty()) request.header("Authorization", "Bearer $token")
                chain.proceed(request.build())
            }
            .build()
        val api = Retrofit.Builder()
            .baseUrl(base)
            .client(http)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(FleetPilotApi::class.java)
        cached = key to api
        return api
    }

    fun reset() {
        cached = null
    }

    /** "fleetpilot.lan:5000" -> "http://fleetpilot.lan:5000/" */
    internal fun normalise(url: String): String {
        val trimmed = url.trim().trimEnd('/')
        require(trimmed.isNotEmpty()) { "Enter the server address" }
        val withScheme = if ("://" in trimmed) trimmed else "http://$trimmed"
        return "$withScheme/"
    }
}
