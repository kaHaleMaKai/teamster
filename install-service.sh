#!/bin/bash
set -euo pipefail

CUR_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]:-.}")")"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
SERVICE_FILE="${SYSTEMD_DIR}/teamster.service"

template-service() {
  echo "#######################################
#   THIS FILE CREATED AUTOMATICALLY   #
#######################################

[Unit]
Description=Teamster – background image server for MS Teams
Documentation=https://github.com/kaHaleMaKai/teamster.git

[Service]
Type=simple

WorkingDirectory=${CUR_DIR}
ExecStart=${CUR_DIR}/.venv/bin/python ${CUR_DIR}/teamster.py

StandardOut=journal
StandardError=journal

Restart=always
RestartSec=1

[Install]
WantedBy=default.target
"
}

main() {
  if ! [[ -d "$SYSTEMD_DIR" ]]; then
    echo "creating systemd user dir ${SYSTEMD_DIR}" >&2
    mkdir -p "$SYSTEMD_DIR"
  fi
  template-service > "$SERVICE_FILE"
  echo "service installed into ${SERVICE_FILE} ✔" >&2
  systemctl --user daemon-reload
  echo 'daemon reloaded ✔' >&2

  echo >&2
  echo 'Now, you can run

  systemctl --user enable teamster.service

to enable the service after booting, and

  systemctl --user start teamster.service

to start it directly.
' >&2
}

main "$@"

# vim: ft=sh
