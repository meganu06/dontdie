#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv git ca-certificates curl
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
Description=Don't Die seven-agent Slack bot
After=network-online.target
Wants=network-online.target
[Service]
User=dontdie
Group=dontdie
WorkingDirectory=/opt/dontdie
ExecStartPre=/opt/dontdie/.venv/bin/python -u /opt/dontdie/bot.py --check-cloud
ExecStart=/opt/dontdie/.venv/bin/python -u /opt/dontdie/bot.py
TimeoutStartSec=600
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
systemctl daemon-reload
systemctl enable dontdie.service
systemctl restart dontdie.service
systemctl is-active dontdie.service
echo 'DONTDIE_BOOT_READY'
