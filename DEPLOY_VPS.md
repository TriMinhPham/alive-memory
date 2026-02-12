# VPS Deployment (TCP Server)

## 1. Provision

```bash
sudo apt update
sudo apt install -y python3 python3-venv
```

## 2. Install app

```bash
git clone https://github.com/TriMinhPham/shopkeeper.git
cd shopkeeper
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configure environment

```bash
cp .env.example .env
```

Set values in `.env`:

- `ANTHROPIC_API_KEY`
- `SHOPKEEPER_SERVER_TOKEN` (long random value)
- `SHOPKEEPER_HOST=0.0.0.0`
- `SHOPKEEPER_PORT=9999`

## 4. Run manually (smoke test)

```bash
set -a
source .env
set +a
python3 heartbeat_server.py
```

From another machine:

- Set `SHOPKEEPER_HOST=<vps-ip>`
- Set matching `SHOPKEEPER_PORT`
- Set matching `SHOPKEEPER_SERVER_TOKEN`
- Run `python3 terminal.py --connect`

## 5. Run as systemd service

Create `/etc/systemd/system/shopkeeper.service`:

```ini
[Unit]
Description=Shopkeeper Heartbeat Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/shopkeeper
EnvironmentFile=/home/ubuntu/shopkeeper/.env
ExecStart=/home/ubuntu/shopkeeper/.venv/bin/python3 /home/ubuntu/shopkeeper/heartbeat_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now shopkeeper
sudo systemctl status shopkeeper
```

## 6. Firewall

Open only the configured TCP port:

```bash
sudo ufw allow 9999/tcp
sudo ufw enable
```
