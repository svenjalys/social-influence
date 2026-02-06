# Transparency Label Study (Flask + Prolific)

This study is built with Flask and deployed with Gunicorn. It supports both local testing and production-ready deployment on a server.

---

## 🔧 Local Development (on Mac/Linux)

1. **Clone the repository** (or copy the source files).

2. **Create a virtual environment**:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Run the app with Flask**:
```bash
flask --app app run --debug
```

The study will be available at: [http://127.0.0.1:5000/?PROLIFIC_PID=example123](http://127.0.0.1:5000/?PROLIFIC_PID=example123)

---

## 🌐 Server Deployment (Ubuntu 22.04 or newer)

## 🚀 NREC Instance Deployment (public Prolific link)

This app serves pages *and* writes `responses.db` on the same VM where the Flask/Gunicorn process runs.
For a smooth public deployment on an NREC VM, use Gunicorn behind Nginx and store the SQLite DB in a persistent directory.

### 0) NREC / OpenStack prerequisites

- Assign a **floating IP** (or DNS name) to the VM.
- Open security group / firewall ports: **22** (SSH), **80** (HTTP), **443** (HTTPS).
- Recommended: use a DNS name (or use `nip.io` for quick DNS that supports TLS):
	- Example: if your floating IP is `203.0.113.10`, you can use `203.0.113.10.nip.io`.

### 0.5) SSH into the VM (from your own laptop)

You run `ssh ...` in **Terminal on your Mac/Linux machine**, not inside the VM.

For Ubuntu images the username is typically `ubuntu`.

```bash
# Make sure your private key file is not world-readable
chmod 600 ~/Downloads/nrec_key.pem

# Connect using only that key
ssh -i ~/Downloads/nrec_key.pem -o IdentitiesOnly=yes ubuntu@YOUR_FLOATING_IP
```

If you get `Permission denied (publickey)`, it almost always means the VM was created with a *different* key pair.
Check the instance details in the NREC/OpenStack UI for **Key Pair**, and confirm it matches the private key you are using.

Helpful debug command (paste the last lines if you need help):

```bash
ssh -vvv -i ~/Downloads/nrec_key.pem -o IdentitiesOnly=yes ubuntu@YOUR_FLOATING_IP
```

### 1) Install OS dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx
```

### 2) Create an app user + deploy folder

```bash
sudo useradd -r -m -s /usr/sbin/nologin prolific
sudo mkdir -p /opt/social-influence /var/lib/prolific-study
sudo chown -R prolific:prolific /opt/social-influence /var/lib/prolific-study
```

### 3) Clone + install

```bash
sudo -u prolific git clone <YOUR_REPO_URL> /opt/social-influence
cd /opt/social-influence
sudo -u prolific python3 -m venv venv
sudo -u prolific ./venv/bin/pip install -r requirements.txt
```

### 4) Configure environment (secrets + DB location)

Create `/etc/default/prolific-study`:

```bash
sudo tee /etc/default/prolific-study >/dev/null <<'EOF'
# Required in production
FLASK_SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_VALUE

# Store the SQLite DB somewhere persistent (NOT in /tmp)
RESPONSES_DB_PATH=/var/lib/prolific-study/responses.db

# Recommended behind Nginx + HTTPS
USE_PROXY_FIX=1
SESSION_COOKIE_SECURE=1

# Optional: lock down admin/debug endpoints in production
ADMIN_TOKEN=CHANGE_ME_TOO
EOF
sudo chmod 600 /etc/default/prolific-study
```

Generate secrets locally if you want:

```bash
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

### 5) Run Gunicorn as a systemd service

- Copy the template service file from [deploy/prolific-study.service](deploy/prolific-study.service) to `/etc/systemd/system/prolific-study.service` and edit paths if needed.

```bash
sudo cp deploy/prolific-study.service /etc/systemd/system/prolific-study.service
sudo systemctl daemon-reload
sudo systemctl enable --now prolific-study
sudo journalctl -u prolific-study -f
```

### 6) Put Nginx in front (public port 80/443)

- Copy [deploy/nginx-social-influence.conf](deploy/nginx-social-influence.conf) to `/etc/nginx/sites-available/social-influence`.
- Update `server_name` and the `/opt/social-influence` path.

```bash
sudo cp deploy/nginx-social-influence.conf /etc/nginx/sites-available/social-influence
sudo ln -sf /etc/nginx/sites-available/social-influence /etc/nginx/sites-enabled/social-influence
sudo nginx -t
sudo systemctl reload nginx
```

### 7) Enable HTTPS (recommended for Prolific)

If you have a domain (or use `nip.io`), use Let’s Encrypt:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN
```

### 8) Verify Prolific entry URL

Use your public URL:

`https://YOUR_DOMAIN/?PROLIFIC_PID=example123`

### Admin/debug endpoints (production)

In production, these endpoints are disabled unless `ADMIN_TOKEN` is set and provided as `?token=...`:
- `/reset-db`
- `/debug-init-db`, `/debug-articles`, `/debug-article/<id>`

### Manual Run with Gunicorn (Debug OFF)

1. **SSH into your server**, activate venv and run:
```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

2. Your app will be available via the server’s IP address:  
`http://<your-server-ip>:5000/?PROLIFIC_PID=XXXX`

---

### 🔁 Systemd Service Setup (Production)

1. Copy the `prolific-study.service` to `/etc/systemd/system/`.

2. Reload services and start:
```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl start prolific-study
sudo systemctl enable prolific-study
```

3. To view logs:
```bash
journalctl -u prolific-study -f
```

---

## 🔄 Restart/Stop Service
```bash
sudo systemctl restart prolific-study
sudo systemctl stop prolific-study
```

---

## 📎 Example Prolific Completion URL

Add this as the redirect after the thank you page:
```
https://app.prolific.com/submissions/complete?cc=CBRC2BEO
```
