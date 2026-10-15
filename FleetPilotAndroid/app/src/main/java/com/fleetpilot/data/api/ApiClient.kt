// SPDX-FileCopyrightText: Copyright the FleetPilot contributors
// SPDX-License-Identifier: GPL-3.0-or-later
package com.fleetpilot.data.api

import android.annotation.SuppressLint
import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.fleetpilot.data.models.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.*
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/** Server address, API token and trusted certificate, kept in the app's private storage. */
val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "fleetpilot")

object PrefsKeys {
    val SERVER_URL = stringPreferencesKey("server_url")
    val AUTH_TOKEN = stringPreferencesKey("api_token")
    val USERNAME = stringPreferencesKey("username")
    /** SHA-256 of the server certificate the user confirmed (for self-signed certificates). */
    val CERT_PIN = stringPreferencesKey("cert_sha256")
}

/** FleetPilot's REST API, authenticated with a personal API token (Security → API tokens). */
interface FleetPilotApi {
    @GET("api/me") suspend fun me(): Response<Me>

    @GET("api/hosts") suspend fun hosts(): Response<List<Host>>
    @POST("api/hosts/{name}/wol") suspend fun wakeHost(@Path("name") name: String): Response<ActionResult>
    @POST("api/hosts/{name}/shutdown") suspend fun shutdownHost(@Path("name") name: String): Response<ActionResult>

    @GET("api/vms") suspend fun vms(): Response<VmsResponse>
    @FormUrlEncoded
    @POST("api/vms/{id}/action")
    suspend fun vmAction(
        @Path("id") endpointId: Int,
        @Field("node") node: String,
        @Field("vmid") vmid: Int,
        @Field("rtype") type: String,
        @Field("action") action: String,
    ): Response<ActionResult>

    @GET("api/hw/live") suspend fun hwServers(): Response<List<HwServer>>
    @POST("api/hw/server/{id}/action")
    suspend fun hwAction(@Path("id") id: Int, @Body action: HwAction): Response<ActionResult>

    @GET("api/fans/devices") suspend fun fanDevices(): Response<List<FanDevice>>
    @GET("api/fans/{id}/status") suspend fun fanStatus(@Path("id") id: Int): Response<FanStatus>
    @FormUrlEncoded
    @POST("api/fans/{id}/set_fan")
    suspend fun setFan(
        @Path("id") id: Int,
        @Field("channel") channel: String,
        @Field("mode") mode: String,
        @Field("speed") speed: Int,
    ): Response<ActionResult>

    @GET("api/smart/summary") suspend fun smartSummary(): Response<SmartSummary>
    @GET("api/vulnerabilities") suspend fun vulnerabilities(): Response<VulnResponse>
    @GET("api/routers") suspend fun routers(): Response<RoutersResponse>
    @GET("api/backup/servers") suspend fun backupServers(): Response<List<BackupServer>>
}

/** The server's certificate is not trusted by Android; the user may confirm it by fingerprint. */
class UntrustedCertificateException(val fingerprint: String, val subject: String) :
    Exception("The server's certificate is not trusted.")

object ApiClient {
    @Volatile private var cached: Pair<String, FleetPilotApi>? = null

    /** The API for the saved server, token and certificate. Call [reset] after any of them changes. */
    suspend fun getApi(context: Context): FleetPilotApi {
        val prefs = context.dataStore.data.first()
        val base = prefs[PrefsKeys.SERVER_URL] ?: throw IllegalStateException("No FleetPilot server configured")
        return create(base, prefs[PrefsKeys.AUTH_TOKEN].orEmpty(), prefs[PrefsKeys.CERT_PIN])
    }

    fun create(serverUrl: String, token: String, pin: String?): FleetPilotApi {
        val base = normalise(serverUrl)
        val key = "$base|$token|${pin.orEmpty()}"
        cached?.let { (k, api) -> if (k == key) return api }
        val api = Retrofit.Builder()
            .baseUrl(base)
            .client(httpClient(token, pin))
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(FleetPilotApi::class.java)
        cached = key to api
        return api
    }

    fun reset() {
        cached = null
    }

    /** "fleetpilot.lan" -> "https://fleetpilot.lan/" (HTTPS unless the address says otherwise). */
    fun normalise(url: String): String {
        val trimmed = url.trim().trimEnd('/')
        require(trimmed.isNotEmpty()) { "Enter the address of your FleetPilot server." }
        val withScheme = if ("://" in trimmed) trimmed else "https://$trimmed"
        return "$withScheme/"
    }

    private fun httpClient(token: String, pin: String?): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .followRedirects(false)          // a redirect means "sign in", never follow it with the token
            .addInterceptor { chain ->
                val request = chain.request().newBuilder()
                if (token.isNotEmpty()) request.header("Authorization", "Bearer $token")
                chain.proceed(request.header("Accept", "application/json").build())
            }
        if (!pin.isNullOrEmpty()) {
            val trust = PinnedTrustManager(pin)
            val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
            builder.sslSocketFactory(ssl.socketFactory, trust)
            // The pinned certificate identifies the server; it may not name the address used.
            val standard = javax.net.ssl.HttpsURLConnection.getDefaultHostnameVerifier()
            builder.hostnameVerifier { host, session ->
                val pinned = (session.peerCertificates.firstOrNull() as? X509Certificate)?.let { sha256(it) == pin } == true
                pinned || standard.verify(host, session)
            }
        }
        return builder.build()
    }

    /**
     * Connects to [serverUrl] without credentials and reports whether Android trusts its certificate.
     * Returns null when it does (or the address is plain HTTP); otherwise the certificate's details.
     */
    suspend fun probeCertificate(serverUrl: String): UntrustedCertificateException? = withContext(Dispatchers.IO) {
        val base = normalise(serverUrl)
        if (!base.startsWith("https://")) return@withContext null
        try {
            OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).build()
                .newCall(Request.Builder().url(base + "api/live").build()).execute().close()
            null
        } catch (e: javax.net.ssl.SSLException) {
            val recorder = RecordingTrustManager()
            val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(recorder), null) }
            OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS)
                .sslSocketFactory(ssl.socketFactory, recorder)
                .hostnameVerifier { _, _ -> true }    // only reads the certificate; nothing is sent
                .build()
                .newCall(Request.Builder().url(base + "api/live").build()).execute().close()
            val leaf = recorder.chain.firstOrNull() ?: throw e
            UntrustedCertificateException(sha256(leaf), leaf.subjectX500Principal.name)
        }
    }

    fun sha256(cert: X509Certificate): String =
        MessageDigest.getInstance("SHA-256").digest(cert.encoded).joinToString(":") { "%02X".format(it) }

    private fun systemTrust(): X509TrustManager {
        val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        factory.init(null as KeyStore?)
        return factory.trustManagers.filterIsInstance<X509TrustManager>().first()
    }

    /** Trusts certificates Android trusts, plus exactly the one certificate the user confirmed. */
    private class PinnedTrustManager(private val pin: String) : X509TrustManager {
        private val system = systemTrust()
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) =
            system.checkClientTrusted(chain, authType)

        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            if (chain.isNotEmpty() && sha256(chain[0]) == pin) return
            system.checkServerTrusted(chain, authType)
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = system.acceptedIssuers
    }

    /** Accepts any certificate and keeps it, so its fingerprint can be shown. Never used to send data. */
    @SuppressLint("CustomX509TrustManager", "TrustAllX509TrustManager")
    private class RecordingTrustManager : X509TrustManager {
        var chain: List<X509Certificate> = emptyList()
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = Unit
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            this.chain = chain.toList()
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }
}
