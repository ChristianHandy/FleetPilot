package com.fleetpilot.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.fleetpilot.ui.theme.*
import com.fleetpilot.viewmodel.AuthViewModel
import com.fleetpilot.viewmodel.LoginState

@Composable
fun LoginScreen(viewModel: AuthViewModel, onLoginSuccess: () -> Unit) {
    var serverUrl by remember { mutableStateOf("http://192.168.1.100:8080") }
    var username by remember { mutableStateOf("admin") }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }

    val loginState by viewModel.loginState.collectAsState()

    LaunchedEffect(loginState) {
        if (loginState is LoginState.Success) onLoginSuccess()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(FPBackground),
        contentAlignment = Alignment.Center
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            // Logo
            Text("⚡", fontSize = 56.sp)
            Spacer(Modifier.height(8.dp))
            Text(
                "FleetPilot",
                fontSize = 32.sp,
                fontWeight = FontWeight.Bold,
                color = FPPrimary
            )
            Text("Server Management", color = FPMuted, fontSize = 14.sp)
            Spacer(Modifier.height(40.dp))

            // Login Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = FPSurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, FPBorder)
            ) {
                Column(modifier = Modifier.padding(24.dp)) {
                    Text("Anmelden", color = FPOnBackground, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(20.dp))

                    // Server URL
                    OutlinedTextField(
                        value = serverUrl,
                        onValueChange = { serverUrl = it },
                        label = { Text("Server URL") },
                        leadingIcon = { Icon(Icons.Default.Dns, null, tint = FPMuted) },
                        modifier = Modifier.fillMaxWidth(),
                        colors = fpTextFieldColors(),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri)
                    )
                    Spacer(Modifier.height(12.dp))

                    // Username
                    OutlinedTextField(
                        value = username,
                        onValueChange = { username = it },
                        label = { Text("Benutzername") },
                        leadingIcon = { Icon(Icons.Default.Person, null, tint = FPMuted) },
                        modifier = Modifier.fillMaxWidth(),
                        colors = fpTextFieldColors(),
                        singleLine = true
                    )
                    Spacer(Modifier.height(12.dp))

                    // Password
                    OutlinedTextField(
                        value = password,
                        onValueChange = { password = it },
                        label = { Text("Passwort") },
                        leadingIcon = { Icon(Icons.Default.Lock, null, tint = FPMuted) },
                        trailingIcon = {
                            IconButton(onClick = { showPassword = !showPassword }) {
                                Icon(
                                    if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                    null, tint = FPMuted
                                )
                            }
                        },
                        visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth(),
                        colors = fpTextFieldColors(),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password)
                    )
                    Spacer(Modifier.height(20.dp))

                    // Error
                    if (loginState is LoginState.Error) {
                        Text(
                            (loginState as LoginState.Error).message,
                            color = FPError,
                            fontSize = 13.sp,
                            modifier = Modifier.padding(bottom = 12.dp)
                        )
                    }

                    // Login Button
                    Button(
                        onClick = { viewModel.login(serverUrl, username, password) },
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        enabled = loginState !is LoginState.Loading,
                        colors = ButtonDefaults.buttonColors(containerColor = FPPrimaryVariant),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        if (loginState is LoginState.Loading) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                color = FPOnBackground,
                                strokeWidth = 2.dp
                            )
                        } else {
                            Text("Anmelden", fontWeight = FontWeight.SemiBold)
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
