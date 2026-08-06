package com.fleetpilot.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// ── FleetPilot Color Palette ──────────────────────────────────────────────────
val FPBackground = Color(0xFF0D1117)
val FPSurface = Color(0xFF161B22)
val FPSurfaceVariant = Color(0xFF21262D)
val FPBorder = Color(0xFF30363D)
val FPPrimary = Color(0xFF58A6FF)
val FPPrimaryVariant = Color(0xFF1F6FEB)
val FPSecondary = Color(0xFFA371F7)
val FPSuccess = Color(0xFF3FB950)
val FPWarning = Color(0xFFD29922)
val FPError = Color(0xFFF85149)
val FPOnBackground = Color(0xFFE6EDF3)
val FPOnSurface = Color(0xFFCDD9E5)
val FPMuted = Color(0xFF8B949E)

private val DarkColorScheme = darkColorScheme(
    primary = FPPrimary,
    onPrimary = Color(0xFF0D1117),
    primaryContainer = FPPrimaryVariant,
    secondary = FPSecondary,
    background = FPBackground,
    surface = FPSurface,
    surfaceVariant = FPSurfaceVariant,
    onBackground = FPOnBackground,
    onSurface = FPOnSurface,
    error = FPError,
    outline = FPBorder
)

@Composable
fun FleetPilotTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography(),
        content = content
    )
}

// ── Status Colors ─────────────────────────────────────────────────────────────
fun statusColor(status: String): Color = when (status.lowercase()) {
    "running", "online", "ok", "passed" -> FPSuccess
    "stopped", "offline", "failed" -> FPError
    "paused", "suspended", "warning" -> FPWarning
    else -> FPMuted
}

fun tempColor(temp: Double?): Color = when {
    temp == null -> FPMuted
    temp >= 90 -> FPError
    temp >= 80 -> FPWarning
    temp >= 70 -> Color(0xFFE3B341)
    else -> FPSuccess
}
