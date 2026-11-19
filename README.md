# ⚙️ IGYR Admin Operations Deck (Dedicated Standalone Server)

This folder contains the **dedicated Admin Operations Server** that runs independently from the Public portal and SOC.

---

## 🔑 Admin Login Credentials
* **Username:** `admin`
* **Password:** `cutiee`
* **Token:** `igyr_super_secret_auth_token_8829`

---

## 🔗 Architecture & Interconnection
* **Shared Database:** Connected to the same MongoDB `igyr_database` cluster as Public and SOC.
* **Instant Updates:** Approving institutes, uploading results, creating schemes, or sending push broadcasts immediately synchronizes across the Public Portal.
* **SOC Integrated:** Reports health, operational telemetry, and metrics to the SOC Command Center via `/health`.

---

## 🚀 Running Locally
```bash
cd admin
pip install -r requirements.txt
python app.py
```
Default URL: `http://localhost:5007/`

---

## ☁️ Deploying on Render as a Web Service
* **Name:** `igyr-admin-panel`
* **Root Directory:** `admin`
* **Build Command:** `pip install -r requirements.txt`
* **Start Command:** `gunicorn app:app`
* **Health Check Path:** `/health`
* **Environment Variables:**
  * `MONGO_URI` = `mongodb+srv://auradispatch2026_db_user:611LdmEjTS7WeqKW@cluster0.z9xcllt.mongodb.net/?appName=Cluster0`
  * `PYTHON_VERSION` = `3.9.16`
