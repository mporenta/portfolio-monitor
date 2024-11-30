#!/bin/sh

export DISPLAY=:1

rm -f /tmp/.X1-lock
Xvfb :1 -ac -screen 0 1024x768x16 &


echo "Attempting to execute /root/scripts/run_x11_vnc.sh"
ls -l /root/scripts/run_x11_vnc.sh

# Print the current working directory and the current user running the script
echo "Current working directory: $(pwd)"
echo "Current user: $(whoami)"

# List files under /root/scripts
echo "Listing files under /root/scripts:"
ls -l /root/scripts

echo "VNC_SERVER_PASSWORD is set to: $VNC_SERVER_PASSWORD"

# Now proceed with the rest of the script
if [ -n "$VNC_SERVER_PASSWORD" ]; then
  echo "Starting VNC server"
  if [ -f "/root/scripts/run_x11_vnc.sh" ]; then
    /root/scripts/run_x11_vnc.sh &
  else
    echo "ERROR: /root/scripts/run_x11_vnc.sh not found!"
  fi
fi

envsubst < "${IBC_INI}.tmpl" > "${IBC_INI}"

# Check if /root/scripts/fork_ports_delayed.sh exists before running it
if [ -f "/root/scripts/fork_ports_delayed.sh" ]; then
  echo "VNC: Forking ports"
  /root/scripts/fork_ports_delayed.sh &
else
  echo "ERROR: /root/scripts/fork_ports_delayed.sh not found!"
fi

# TBOT: run ngrok, flask and tbot
/home/tbot/develop/github/tbot-tradingboat/tbottmux/run_docker_flask_tbot.sh &

/root/ibc/scripts/ibcstart.sh "${TWS_MAJOR_VRSN}" -g \
     "--tws-path=${TWS_PATH}" \
     "--ibc-path=${IBC_PATH}" "--ibc-ini=${IBC_INI}" \
     "--user=${TWS_USERID}" "--pw=${TWS_PASSWORD}" "--mode=${TRADING_MODE}" \
     "--on2fatimeout=${TWOFA_TIMEOUT_ACTION}"