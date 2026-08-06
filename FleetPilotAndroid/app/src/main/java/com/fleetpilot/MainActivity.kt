package com.fleetpilot

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.*
import com.fleetpilot.data.api.PrefsKeys
import com.fleetpilot.data.api.dataStore
import com.fleetpilot.ui.screens.*
import com.fleetpilot.ui.theme.*
import com.fleetpilot.viewmodel.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            FleetPilotTheme {
                FleetPilotApp()
            }
        }
    }
}

sealed class Screen(val route: String, val label: String, val icon: ImageVector) {
    object Dashboard : Screen("dashboard", "Dashboard", Icons.Default.Dashboard)
    object Hosts : Screen("hosts", "Server", Icons.Default.Dns)
    object VMs : Screen("vms", "VMs", Icons.Default.Computer)
    object HwMonitor : Screen("hw", "HW Monitor", Icons.Default.Memory)
    object Fans : Screen("fans", "Fans", Icons.Default.Air)
}

val bottomNavItems = listOf(
    Screen.Dashboard, Screen.Hosts, Screen.VMs, Screen.HwMonitor, Screen.Fans
)

@Composable
fun FleetPilotApp() {
    val authViewModel: AuthViewModel = viewModel()
    val loginState by authViewModel.loginState.collectAsState()
    val authToken by authViewModel.authToken.collectAsState(initial = null)

    // Check if already logged in
    val isLoggedIn = authToken != null

    if (!isLoggedIn && loginState !is LoginState.Success) {
        LoginScreen(viewModel = authViewModel, onLoginSuccess = {})
    } else {
        MainApp(authViewModel = authViewModel)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainApp(authViewModel: AuthViewModel) {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination

    Scaffold(
        containerColor = FPBackground,
        topBar = {
            TopAppBar(
                title = { Text("⚡ FleetPilot", color = FPPrimary) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = FPSurface),
                actions = {
                    IconButton(onClick = { authViewModel.logout() }) {
                        Icon(Icons.Default.Logout, "Abmelden", tint = FPMuted)
                    }
                }
            )
        },
        bottomBar = {
            NavigationBar(
                containerColor = FPSurface,
                tonalElevation = 0.dp
            ) {
                bottomNavItems.forEach { screen ->
                    NavigationBarItem(
                        icon = { Icon(screen.icon, screen.label) },
                        label = { Text(screen.label) },
                        selected = currentDestination?.hierarchy?.any { it.route == screen.route } == true,
                        onClick = {
                            navController.navigate(screen.route) {
                                popUpTo(navController.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = FPPrimary,
                            selectedTextColor = FPPrimary,
                            unselectedIconColor = FPMuted,
                            unselectedTextColor = FPMuted,
                            indicatorColor = FPPrimaryVariant.copy(alpha = 0.2f)
                        )
                    )
                }
            }
        }
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Screen.Dashboard.route,
            modifier = Modifier.padding(innerPadding)
        ) {
            composable(Screen.Dashboard.route) {
                val vm: DashboardViewModel = viewModel()
                DashboardScreen(vm)
            }
            composable(Screen.Hosts.route) {
                val vm: HostsViewModel = viewModel()
                HostsScreen(vm)
            }
            composable(Screen.VMs.route) {
                val vm: VmViewModel = viewModel()
                VmScreen(vm)
            }
            composable(Screen.HwMonitor.route) {
                val vm: HwViewModel = viewModel()
                HwMonitorScreen(vm)
            }
            composable(Screen.Fans.route) {
                val vm: FanViewModel = viewModel()
                FanScreen(vm)
            }
        }
    }
}
