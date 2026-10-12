#!/usr/bin/env bash
_CS_DEFAULT_URL="https://raw.githubusercontent.com/community-scripts/DevScripts/main"
_cs_boot="${COMMUNITY_SCRIPTS_CORE_DIR:-$(dirname "${BASH_SOURCE[0]}")/../../core}/core/build.func"
source "$_cs_boot" 2>/dev/null || source <(curl -fsSL "${COMMUNITY_SCRIPTS_CORE_URL:-https://raw.githubusercontent.com/community-scripts/core/main}/core/build.func")
# Copyright (c) 2021-2026 community-scripts ORG
# Author: ChristianHandy
# License: MIT | https://github.com/community-scripts/DevScripts/raw/main/LICENSE
# Source: https://github.com/ChristianHandy/FleetPilot

APP="FleetPilot"
var_tags="${var_tags:-monitoring;infrastructure}"
var_cpu="${var_cpu:-2}"
var_ram="${var_ram:-2048}"
var_disk="${var_disk:-8}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
#var_arm64="${var_arm64:-no}" # unset = ask the user; set yes/no only when verified
var_unprivileged="${var_unprivileged:-1}"

header_info "$APP"
variables
color
catch_errors

function update_script() {
  header_info
  check_container_storage
  check_container_resources

  if [[ ! -d /opt/fleetpilot ]]; then
    msg_error "No FleetPilot Installation Found!"
    exit
  fi

  if check_for_gh_release "fleetpilot" "ChristianHandy/FleetPilot"; then
    msg_info "Stopping FleetPilot"
    systemctl stop fleetpilot
    msg_ok "Stopped FleetPilot"

    create_backup /opt/fleetpilot/.env

    CLEAN_INSTALL=1 CLEAN_INSTALL_KEEP="data logs venv" fetch_and_deploy_gh_release "fleetpilot" "ChristianHandy/FleetPilot" "tarball"

    restore_backup
    PYTHON_VERSION="3.13" setup_uv

    msg_info "Updating Python Environment"
    $STD uv pip install -p /opt/fleetpilot/venv/bin/python -r /opt/fleetpilot/requirements.txt
    msg_ok "Updated Python Environment"

    msg_info "Starting FleetPilot"
    systemctl start fleetpilot
    msg_ok "Started FleetPilot"
    msg_ok "Updated successfully!"
  fi
  exit
}

start
build_container
description

msg_ok "Completed Successfully!\n"
echo -e "${CREATING}${GN}${APP} setup has been successfully initialized!${CL}"
echo -e "${INFO}${YW}Access it using the following URL:${CL}"
echo -e "${GATEWAY}${BGN}https://${IP}${CL}"
