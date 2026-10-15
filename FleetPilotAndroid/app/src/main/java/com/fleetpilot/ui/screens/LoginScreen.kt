// SPDX-FileCopyrightText: Copyright the FleetPilot contributors
// SPDX-License-Identifier: GPL-3.0-or-later
package com.fleetpilot.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.fleetpilot.R
import com.fleetpilot.ui.theme.*
import com.fleetpilot.viewmodel.AuthViewModel
import com.fleetpilot.viewmodel.LoginState

@Composable
fun LoginScreen(viewModel: AuthViewModel) {
    val saved by viewModel.savedServer.collectAsState(initial = "")
    var serverUrl by remember(saved) { mutableStateOf(saved.removeSuffix("/")) }
    var token by remember { mutableStateOf("") }
    var showToken by remember { mutableStateOf(false) }
    val loginState by viewModel.loginState.collectAsState()

    (loginState as? LoginState.ConfirmCertificate)?.let { cert ->
        AlertDialog(
            onDismissRequest = { viewModel.cancelCertificate() },
            containerColor = FPSurface,
            title = { Text("Trust this certificate?", color = FPOnBackground) },
            text = {
                Column {
                    Text("Android does not know the certificate of this server. FleetPilot creates its own " +
                         "certificate when it is installed, so this is normal the first time.",
                         color = FPOnSurface, fontSize = 13.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("Only continue if this fingerprint matches your server's: your browser shows it in the " +
                         "certificate details of the FleetPilot page, or run on the server: " +
                         "sudo openssl x509 -in /etc/fleetpilot/tls/fullchain.pem -noout -fingerprint -sha256",
                         color = FPMuted, fontSize = 12.sp)
                    Spacer(Modifier.height(8.dp))
                    Text(cert.subject, color = FPOnSurface, fontSize = 12.sp)
                    Text("SHA-256", color = FPMuted, fontSize = 11.sp)
                    Text(cert.fingerprint, color = FPPrimary, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
                }
            },
            confirmButton = {
                TextButton(onClick = { viewModel.login(serverUrl, token, cert.fingerprint) }) {
                    Text("Trust and sign in", color = FPPrimary)
                }
            },
            dismissButton = { TextButton(onClick = { viewModel.cancelCertificate() }) { Text("Cancel", color = FPMuted) } }
        )
    }

    Box(modifier = Modifier.fillMaxSize().background(FPBackground), contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Icon(painterResource(R.drawable.ic_launcher_foreground), null, tint = FPPrimary, modifier = Modifier.size(96.dp))
            Text("FleetPilot", fontSize = 32.sp, fontWeight = FontWeight.Bold, color = FPPrimary)
            Text("Your homelab, in your pocket", color = FPMuted, fontSize = 14.sp)
            Spacer(Modifier.height(32.dp))

            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = FPSurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, FPBorder)
            ) {
                Column(modifier = Modifier.padding(24.dp)) {
                    Text("Connect", color = FPOnBackground, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(16.dp))
                    OutlinedTextField(
                        value = serverUrl,
                        onValueChange = { serverUrl = it },
                        label = { Text("Server address") },
                        placeholder = { Text("https://fleetpilot.lan") },
                        leadingIcon = { Icon(Icons.Default.Dns, null, tint = FPMuted) },
                        modifier = Modifier.fillMaxWidth(),
                        colors = fpTextFieldColors(),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri)
                    )
                    if (serverUrl.trim().startsWith("http://")) {
                        Text("Plain HTTP: the token crosses the network unencrypted. Use https:// if you can.",
                             color = FPWarning, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
                    }
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = token,
                        onValueChange = { token = it },
                        label = { Text("API token") },
                        placeholder = { Text("fp_…") },
                        leadingIcon = { Icon(Icons.Default.Key, null, tint = FPMuted) },
                        trailingIcon = {
                            IconButton(onClick = { showToken = !showToken }) {
                                Icon(if (showToken) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                     if (showToken) "Hide token" else "Show token", tint = FPMuted)
                            }
                        },
                        visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth(),
                        colors = fpTextFieldColors(),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password)
                    )
                    Text("Create a token in FleetPilot under Sign-in & security → API tokens. " +
                         "A read-only token can look at everything; a read/write token can also wake, " +
                         "shut down and control, within your role.",
                         color = FPMuted, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
                    Spacer(Modifier.height(16.dp))

                    (loginState as? LoginState.Error)?.let {
                        Text(it.message, color = FPError, fontSize = 13.sp, modifier = Modifier.padding(bottom = 12.dp))
                    }
                    Button(
                        onClick = { viewModel.login(serverUrl, token) },
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        enabled = loginState !is LoginState.Loading && serverUrl.isNotBlank() && token.isNotBlank(),
                        colors = ButtonDefaults.buttonColors(containerColor = FPPrimaryVariant),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        if (loginState is LoginState.Loading) {
                            CircularProgressIndicator(modifier = Modifier.size(20.dp), color = FPOnBackground, strokeWidth = 2.dp)
                        } else {
                            Text("Connect", fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun fpTextFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = FPPrimary,
    unfocusedBorderColor = FPBorder,
    focusedLabelColor = FPPrimary,
    unfocusedLabelColor = FPMuted,
    cursorColor = FPPrimary,
    focusedTextColor = FPOnBackground,
    unfocusedTextColor = FPOnSurface,
    focusedContainerColor = FPSurfaceVariant,
    unfocusedContainerColor = FPSurfaceVariant
)
