#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv git ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https
curl --fail --silent --show-error https://dl.cloudsmith.io/public/caddy/stable/gpg.key -o /tmp/dontdie-caddy-key
gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg /tmp/dontdie-caddy-key
curl --fail --silent --show-error https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
apt-get update -q
apt-get install -y -q caddy
id dontdie >/dev/null 2>&1 || useradd --system --create-home dontdie
systemctl stop dontdie.service 2>/dev/null || true
install -d -o dontdie -g dontdie /opt/dontdie
metadata() { curl --fail --silent --show-error -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/$1"; }
revision=$(metadata instance/attributes/dontdie-revision)
if [ ! -d /opt/dontdie/.git ]; then
  runuser -u dontdie -- git clone https://github.com/meganu06/dontdie.git /opt/dontdie
fi
cd /opt/dontdie
runuser -u dontdie -- git fetch origin
runuser -u dontdie -- git checkout --detach "$revision"
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -r requirements.txt
# Fetch secrets without putting them in command arguments, logs or instance metadata.
python3 - <<'PY'
import base64,json,os,urllib.request
def metadata(path):
    req=urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/'+path,headers={'Metadata-Flavor':'Google'})
    with urllib.request.urlopen(req,timeout=20) as r: return r.read().decode()
token=json.loads(metadata('instance/service-accounts/default/token'))['access_token']
project=metadata('project/project-id')
secret=metadata('instance/attributes/dontdie-secret')
url=f'https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{secret}/versions/latest:access'
req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token})
with urllib.request.urlopen(req,timeout=20) as r: value=json.load(r)
fd=os.open('/opt/dontdie/.env',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'wb') as f: f.write(base64.b64decode(value['payload']['data']))
PY
chown -R dontdie:dontdie /opt/dontdie
cat > /etc/systemd/system/dontdie.service <<'UNIT'
[Unit]
Description=Don't Die control room, Slack and scheduler
After=network-online.target
Wants=network-online.target
[Service]
User=dontdie
Group=dontdie
WorkingDirectory=/opt/dontdie
ExecStartPre=/opt/dontdie/.venv/bin/python -u /opt/dontdie/bot.py --check-cloud
ExecStart=/opt/dontdie/.venv/bin/python -u /opt/dontdie/server.py
TimeoutStartSec=600
TimeoutStopSec=240
UMask=0077
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/dontdie/runs
ProtectHome=true
StandardOutput=journal+console
StandardError=journal+console
[Install]
WantedBy=multi-user.target
UNIT
install -d -o dontdie -g dontdie /opt/dontdie/runs
chmod 700 /opt/dontdie/runs
systemctl daemon-reload
# The Google startup script owns boot sequencing. Enabling this unit at boot
# starts a competing preflight before the pinned checkout is installed.
# systemd still restarts the running service automatically on failure.
systemctl disable dontdie.service
systemctl restart dontdie.service
systemctl is-active dontdie.service
web_host=$(metadata instance/attributes/dontdie-web-host)
[[ "$web_host" =~ ^[a-zA-Z0-9.-]+$ ]]
cat > /etc/caddy/Caddyfile <<CADDY
$web_host {
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy 127.0.0.1:8080
}
CADDY
caddy validate --config /etc/caddy/Caddyfile
systemctl enable caddy
systemctl reload caddy
echo 'DONTDIE_BOOT_READY'
