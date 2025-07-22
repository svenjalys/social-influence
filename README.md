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
