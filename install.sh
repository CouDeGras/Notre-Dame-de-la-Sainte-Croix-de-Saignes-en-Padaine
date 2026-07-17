#!/usr/bin/env bash
set -euo pipefail

PROJ="/home/josue/saignes_en_padaine"

echo "==> Installing paho-mqtt system package"
apt-get install -y python3-paho-mqtt

echo "==> Installing systemd units"
cp "$PROJ/saignes-dashboard.service"        /etc/systemd/system/
cp "$PROJ/saignes-weather.service"          /etc/systemd/system/
cp "$PROJ/saignes-weather.timer"            /etc/systemd/system/
cp "$PROJ/saignes-weather-current.service"  /etc/systemd/system/
cp "$PROJ/saignes-weather-current.timer"    /etc/systemd/system/
cp "$PROJ/saignes-ack-listener.service"     /etc/systemd/system/

echo "==> Installing Avahi service advertisement"
cp "$PROJ/saignes-dashboard.xml" /etc/avahi/services/

systemctl daemon-reload

echo "==> Enabling and starting dashboard (auto-starts on boot)"
systemctl enable --now saignes-dashboard.service

echo "==> Enabling weather timer (runs every 3 hours: 00:00, 03:00, 06:00, ... 21:00)"
systemctl enable --now saignes-weather.timer

echo "==> Enabling hourly airport current-conditions timer (runs at :30 past every hour)"
systemctl enable --now saignes-weather-current.timer

echo "==> Enabling and starting the pump-ack listener (always-on, separate from the forecast cycle)"
systemctl enable --now saignes-ack-listener.service

echo "==> Reloading Avahi so the mDNS advertisement goes live"
systemctl reload avahi-daemon

echo ""
echo "Done. Dashboard: http://localhost:8080/"
echo "      mDNS:      http://$(hostname).local:8080/"
echo ""
echo "Run the weather job right now (instead of waiting for the next 3-hour slot):"
echo "  sudo systemctl start saignes-weather.service"
echo ""
echo "Check logs:"
echo "  journalctl -u saignes-dashboard        -f"
echo "  journalctl -u saignes-weather          -e"
echo "  journalctl -u saignes-weather-current  -e"
echo "  journalctl -u saignes-ack-listener      -f"
echo "  systemctl list-timers 'saignes-weather*'"
