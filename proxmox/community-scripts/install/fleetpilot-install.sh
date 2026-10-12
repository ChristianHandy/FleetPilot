#!/usr/bin/env bash

# Copyright (c) 2021-2026 community-scripts ORG
# Author: ChristianHandy
# License: MIT | https://github.com/community-scripts/DevScripts/raw/main/LICENSE
# Source: https://github.com/ChristianHandy/FleetPilot

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

msg_info "Installing Dependencies"
$STD apt install -y \
  nginx \
  smartmontools
msg_ok "Installed Dependencies"

fetch_and_deploy_gh_release "fleetpilot" "ChristianHandy/FleetPilot" "tarball"
PYTHON_VERSION="3.13" setup_uv

msg_info "Setting up Python Environment"
$STD uv venv /opt/fleetpilot/venv
$STD uv pip install -p /opt/fleetpilot/venv/bin/python -r /opt/fleetpilot/requirements.txt
msg_ok "Set up Python Environment"

msg_info "Configuring FleetPilot"
mkdir -p /opt/fleetpilot/data /opt/fleetpilot/logs /root/.ssh
chmod 700 /opt/fleetpilot/data /root/.ssh
# FleetPilot signs in to the servers it manages with this key.
ssh-keygen -q -t ed25519 -N "" -C "fleetpilot@$(hostname)" -f /root/.ssh/id_ed25519
cat <<EOT >/opt/fleetpilot/.env
SECRET_KEY=$(openssl rand -hex 32)
FLEETPILOT_DATA_DIR=/opt/fleetpilot/data
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=$(random_password)
GUNICORN_BIND=127.0.0.1:5000
FLEETPILOT_PRODUCTION=true
FLEETPILOT_TRUST_PROXY=true
FLEETPILOT_COOKIE_SECURE=true
FLEETPILOT_HSTS=false
EOT
chmod 600 /opt/fleetpilot/.env
msg_ok "Configured FleetPilot"

create_self_signed_cert "fleetpilot"

msg_info "Configuring Nginx"
cat <<EOT >/etc/nginx/sites-available/fleetpilot
server {
    listen 80;
    server_name _;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name _;

    ssl_certificate /etc/ssl/fleetpilot/fleetpilot.crt;
    ssl_certificate_key /etc/ssl/fleetpilot/fleetpilot.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 16m;

    location = /system/backups/restore {
        client_max_body_size 512m;
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }
}
EOT
nginx_enable_site "fleetpilot"
msg_ok "Configured Nginx"

msg_info "Creating Service"
cat <<EOT >/etc/systemd/system/fleetpilot.service
[Unit]
Description=FleetPilot
Wants=network-online.target
After=network-online.target

[Service]
Type=exec
User=root
WorkingDirectory=/opt/fleetpilot
EnvironmentFile=/opt/fleetpilot/.env
ExecStart=/opt/fleetpilot/venv/bin/gunicorn --config /opt/fleetpilot/gunicorn.conf.py app:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOT
systemctl enable -q --now fleetpilot
msg_ok "Created Service"

motd_ssh
customize
cleanup_lxc
