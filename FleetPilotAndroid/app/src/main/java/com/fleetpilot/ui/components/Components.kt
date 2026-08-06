package com.fleetpilot.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.fleetpilot.ui.theme.*

// ── Glass Card ────────────────────────────────────────────────────────────────
@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit
) {
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = FPSurface),
        border = androidx.compose.foundation.BorderStroke(1.dp, FPBorder)
    ) {
        Column(modifier = Modifier.padding(16.dp), content = content)
    }
}

// ── Status Badge ──────────────────────────────────────────────────────────────
@Composable
fun StatusBadge(status: String, modifier: Modifier = Modifier) {
    val color = statusColor(status)
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(20.dp))
            .background(color.copy(alpha = 0.15f))
            .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Box(
            modifier = Modifier
                .size(6.dp)
                .clip(CircleShape)
                .background(color)
        )
        Text(
            text = status.replaceFirstChar { it.uppercase() },
            color = color,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold
        )
    }
}

// ── Metric Card ───────────────────────────────────────────────────────────────
@Composable
fun MetricCard(
    label: String,
    value: String,
    unit: String = "",
    color: Color = FPPrimary,
    icon: ImageVector? = null,
    modifier: Modifier = Modifier
) {
    GlassCard(modifier = modifier) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(20.dp))
            Spacer(Modifier.height(8.dp))
        }
        Text(label, color = FPMuted, fontSize = 12.sp)
        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(value, color = color, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            if (unit.isNotEmpty()) {
                Text(unit, color = FPMuted, fontSize = 12.sp, modifier = Modifier.padding(bottom = 3.dp, start = 2.dp))
            }
        }
    }
}

// ── Progress Bar ──────────────────────────────────────────────────────────────
@Composable
fun LabeledProgress(
    label: String,
    value: Float,
    valueText: String,
    color: Color = FPPrimary,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(label, color = FPMuted, fontSize = 12.sp)
            Text(valueText, color = FPOnSurface, fontSize = 12.sp, fontWeight = FontWeight.Medium)
        }
        Spacer(Modifier.height(4.dp))
        LinearProgressIndicator(
            progress = { value.coerceIn(0f, 1f) },
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp)),
            color = color,
            trackColor = FPSurfaceVariant
        )
    }
}

// ── Section Header ────────────────────────────────────────────────────────────
@Composable
fun SectionHeader(title: String, icon: ImageVector? = null) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier.padding(vertical = 8.dp)
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = FPPrimary, modifier = Modifier.size(18.dp))
        }
        Text(title, color = FPOnBackground, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
    }
}

// ── Loading / Error States ────────────────────────────────────────────────────
@Composable
fun LoadingState(message: String = "Laden...") {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(color = FPPrimary)
            Spacer(Modifier.height(16.dp))
            Text(message, color = FPMuted)
        }
    }
}

@Composable
fun ErrorState(message: String, onRetry: (() -> Unit)? = null) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(32.dp)) {
            Text("⚠", fontSize = 48.sp)
            Spacer(Modifier.height(16.dp))
            Text(message, color = FPError, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            if (onRetry != null) {
                Spacer(Modifier.height(16.dp))
                Button(onClick = onRetry, colors = ButtonDefaults.buttonColors(containerColor = FPPrimaryVariant)) {
                    Text("Erneut versuchen")
                }
            }
        }
    }
}

// ── Confirm Dialog ────────────────────────────────────────────────────────────
@Composable
fun ConfirmDialog(
    title: String,
    message: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = FPSurface,
        title = { Text(title, color = FPOnBackground) },
        text = { Text(message, color = FPMuted) },
        confirmButton = {
            TextButton(onClick = onConfirm) { Text("Bestätigen", color = FPError) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Abbrechen", color = FPMuted) }
        }
    )
}

// ── Temp Indicator ────────────────────────────────────────────────────────────
@Composable
fun TempIndicator(temp: Double?, modifier: Modifier = Modifier) {
    val color = tempColor(temp)
    val text = if (temp != null) "${temp.toInt()}°C" else "N/A"
    Text(
        text = text,
        color = color,
        fontSize = 14.sp,
        fontWeight = FontWeight.Bold,
        modifier = modifier
    )
}
