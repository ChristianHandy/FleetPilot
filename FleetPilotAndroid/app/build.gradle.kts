// SPDX-FileCopyrightText: Copyright the FleetPilot contributors
// SPDX-License-Identifier: GPL-3.0-or-later
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)   // AGP 9 compiles Kotlin itself; this adds the Compose compiler
}

android {
    namespace = "com.fleetpilot"
    compileSdk = 37   // the AndroidX libraries need it; targetSdk decides runtime behaviour

    defaultConfig {
        applicationId = "com.fleetpilot"
        minSdk = 26
        targetSdk = 35
        versionCode = 19
        versionName = "1.8.1"
    }

    // Release signing key: kept outside the repository and passed in by the environment
    // (FLEETPILOT_KEYSTORE = path to the .jks, FLEETPILOT_KEYSTORE_PASSWORD). Without them the
    // release build is unsigned. Every release must use the same key, or updates cannot be installed.
    val keystore = providers.environmentVariable("FLEETPILOT_KEYSTORE")
    signingConfigs {
        create("release") {
            if (keystore.isPresent) {
                storeFile = file(keystore.get())
                storePassword = providers.environmentVariable("FLEETPILOT_KEYSTORE_PASSWORD").get()
                keyAlias = "fleetpilot"
                keyPassword = storePassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystore.isPresent) signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.gson)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.androidx.datastore)
    implementation(libs.coil.compose)
    debugImplementation(libs.androidx.ui.tooling)
}
