# -*- coding: utf-8 -*-
"""
IGYR Admin Operations & Management Panel - Dedicated Standalone Server
Runs independently on port 5007 (or Render $PORT).
Interconnected with Public Platform and SOC via shared MongoDB cluster.
"""

from flask import Flask, request, jsonify, send_from_directory, make_response, redirect
from flask_cors import CORS
from pymongo import MongoClient
import os
import time
import json
import html as html_lib
from datetime import datetime
import urllib.request
import urllib.error
import urllib.parse
import platform

# Optional psutil for hardware telemetry
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app, resources={r"/*": {"origins": "*"}})

# Server start time for uptime
SERVER_START_TIME = time.time()

# Connect to MongoDB cluster (Shared across Public, Admin, and SOC)
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://auradispatch2026_db_user:611LdmEjTS7WeqKW@cluster0.z9xcllt.mongodb.net/?appName=Cluster0")
client = MongoClient(MONGO_URI)
db = client['igyr_database']

# Collections
institutes_col = db['institutes']
results_col = db['results']
notices_col = db['notices']
quicklinks_col = db['quicklinks']
schemes_col = db['schemes']
applications_col = db['applications']
settings_col = db['settings']
fcm_tokens_col = db['fcm_tokens']
banner_col = db['banner']
whatsapp_config_col = db['whatsapp_config']
whatsapp_logs_col = db['whatsapp_logs']
soc_control_col = db['soc_control']
soc_logs_col = db['soc_security_logs']

# Initialize Firebase Admin SDK for FCM Web Push
import firebase_admin
from firebase_admin import credentials, messaging

try:
    if not firebase_admin._apps:
        fb_creds_env = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        app_dir = os.path.dirname(os.path.abspath(__file__))
        sa_candidates = [
            os.path.join(app_dir, "firebase-service-account.json"),
            os.path.join(app_dir, "..", "firebase-service-account.json"),
            os.path.join(app_dir, "admin", "firebase-service-account.json"),
            "firebase-service-account.json"
        ]
        sa_file = next((f for f in sa_candidates if os.path.isfile(f)), None)

        if fb_creds_env:
            cred = credentials.Certificate(json.loads(fb_creds_env))
            firebase_admin.initialize_app(cred)
            print("✅ Firebase Admin SDK initialized from environment variable.")
        elif sa_file:
            cred = credentials.Certificate(sa_file)
            firebase_admin.initialize_app(cred)
            print(f"✅ Firebase Admin SDK initialized from file: {sa_file}")
        else:
            print("⚠️ Firebase Admin credentials not found.")
except Exception as fb_init_err:
    print("⚠️ Firebase Admin SDK initialization error:", fb_init_err)

def send_push_notification_to_all(title, body, url="/search-result.html"):
    try:
        if not firebase_admin._apps:
            return {"success": False, "error": "Firebase Admin not initialized"}

        tokens_docs = list(fcm_tokens_col.find({}, {"token": 1, "_id": 0}))
        tokens = [d['token'] for d in tokens_docs if d.get('token')]
        if not tokens:
            return {"success": True, "sent_count": 0, "message": "No registered devices yet."}

        success_count = 0
        failure_count = 0
        invalid_tokens = []

        full_url = url if str(url).startswith("http") else f"https://igyr-india-get-your-result.onrender.com{url}"
        icon_url = "https://igyr-india-get-your-result.onrender.com/favicon-192x192.png"
        badge_url = "https://igyr-india-get-your-result.onrender.com/favicon-96x96.png"

        chunk_size = 500
        for i in range(0, len(tokens), chunk_size):
            chunk = tokens[i:i + chunk_size]
            multicast_msg = messaging.MulticastMessage(
                notification=messaging.Notification(
                    title=str(title),
                    body=str(body),
                    image=icon_url
                ),
                data={
                    "title": str(title),
                    "body": str(body),
                    "url": str(url)
                },
                webpush=messaging.WebpushConfig(
                    headers={"Urgency": "high", "TTL": "86400"},
                    notification=messaging.WebpushNotification(
                        title=str(title),
                        body=str(body),
                        icon=icon_url,
                        badge=badge_url,
                        data={"url": str(url)},
                        require_interaction=True
                    )
                ),
                tokens=chunk
            )
            response = messaging.send_each_for_multicast(multicast_msg)
            success_count += response.success_count
            failure_count += response.failure_count

            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    err_code = resp.exception.code if resp.exception else "UNKNOWN"
                    if err_code in ["NOT_FOUND", "INVALID_ARGUMENT", "UNREGISTERED"]:
                        invalid_tokens.append(chunk[idx])

        if invalid_tokens:
            fcm_tokens_col.delete_many({"token": {"$in": invalid_tokens}})

        return {"success": True, "sent_count": success_count, "failed_count": failure_count}
    except Exception as e:
        return {"success": False, "error": str(e)}

# WhatsApp Automation Helpers
def get_whatsapp_config():
    doc = whatsapp_config_col.find_one({"id": "whatsapp_config"}, {"_id": 0})
    if not doc:
        return {
            "enabled": False,
            "verify_token": "igyr_wa_verify_2026",
            "phone_number_id": "",
            "waba_id": "",
            "token": "",
            "welcome_message": "Namaste! Welcome to India Get Your Result (IGYR) Automated Helpdesk.",
            "not_found_message": "We could not locate any active record matching your query."
        }
    return doc

def send_whatsapp_message(to_phone, text):
    cfg = get_whatsapp_config()
    phone_number_id = cfg.get("phone_number_id")
    token = cfg.get("token")
    if not phone_number_id or not token:
        return {"success": False, "error": "WhatsApp Cloud API credentials not configured"}

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {"preview_url": False, "body": text}
    }
    data_bytes = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode('utf-8')
            return {"success": True, "data": json.loads(resp_body)}
    except urllib.error.HTTPError as http_err:
        err_msg = http_err.read().decode('utf-8', errors='ignore')
        return {"success": False, "error": f"HTTP {http_err.code}: {err_msg}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def build_whatsapp_automated_response(query_text, sender_name=""):
    q = (query_text or "").strip()
    q_lower = q.lower()
    salutation = f"Namaste {sender_name}!" if sender_name else "Namaste!"
    help_menu = (
        f"{salutation}\n\n"
        "Welcome to *India Get Your Result (IGYR)* Automated Helpdesk.\n\n"
        "Reply with any of the following to get instant details:\n"
        "• *RESULTS* - Check recent published exam results\n"
        "• *INSTITUTES* - View registered boards & universities\n"
        "• *SCHEMES* - Explore active education scholarships\n"
        "• *VERIFY* - How to authenticate marksheet credentials\n"
        "• Or send your *Registration / Roll Number* to look up published marks."
    )
    if not q or q_lower in ["hi", "hello", "hey", "help", "menu", "namaste", "start"]:
        return help_menu

    if "result" in q_lower:
        results = list(results_col.find({}, {"_id": 0}).limit(5))
        if not results:
            return "No examination results are currently published. Please check back later."
        lines = ["*Latest Published Examination Results:*"]
        for idx, r in enumerate(results, 1):
            title = r.get("title") or r.get("name") or "Examination"
            inst = r.get("instituteName") or r.get("institute_name") or ""
            lines.append(f"{idx}. {title}" + (f" ({inst})" if inst else ""))
        lines.append("\nVisit https://igyr-india-get-your-result.onrender.com/search-result.html to view full marks.")
        return "\n".join(lines)

    if "scheme" in q_lower:
        schemes = list(schemes_col.find({}, {"_id": 0}).limit(5))
        if not schemes:
            return "No scholarships or schemes are currently listed."
        lines = ["*Active Education Schemes & Scholarships:*"]
        for idx, s in enumerate(schemes, 1):
            lines.append(f"{idx}. {s.get('name') or s.get('title')}")
        lines.append("\nView scheme details: https://igyr-india-get-your-result.onrender.com/schemes.html")
        return "\n".join(lines)

    if "institute" in q_lower or "school" in q_lower or "college" in q_lower:
        inst_count = institutes_col.count_documents({})
        return (
            f"IGYR is connected to over *{inst_count} verified institutions* across India.\n"
            "Browse affiliated boards: https://igyr-india-get-your-result.onrender.com/"
        )

    # Match by student roll or registration
    matched_results = list(results_col.find({"$or": [{"rollNo": q}, {"regNo": q}, {"roll_no": q}]}, {"_id": 0}).limit(1))
    if matched_results:
        res = matched_results[0]
        return (
            f"*Record Located for {res.get('candidateName', 'Candidate')}!*\n"
            f"Roll No: {res.get('rollNo', q)}\n"
            f"Class / Course: {res.get('class', 'N/A')}\n"
            f"Marks Status: {res.get('status', 'Published')}\n\n"
            f"View verified marksheet: https://igyr-india-get-your-result.onrender.com/result.html?roll={q}"
        )

    cfg = get_whatsapp_config()
    return cfg.get("not_found_message") or "We could not find records matching your query. Reply *MENU* to see options."

# Authentication & Tokens
def verify_token():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return False
    token = auth_header.split(' ')[1]
    return token in ["igyr_super_secret_auth_token_8829", "igyr_inst_secret_auth_token_7731"]

# Sync Cache
_sync_cache = None
_sync_cache_time = 0
CACHE_TTL = 15

def invalidate_sync_cache():
    global _sync_cache
    _sync_cache = None


# ==========================================
# HEALTH PROBE (For Render & SOC Monitoring)
# ==========================================

@app.route('/health')
@app.route('/api/health')
@app.route('/admin/health')
def admin_health():
    now = time.time()
    uptime_sec = int(now - SERVER_START_TIME)
    days, rem = divmod(uptime_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s" if days > 0 else f"{hours}h {minutes}m {seconds}s"

    db_status = "Disconnected"
    db_latency_ms = -1
    try:
        t0 = time.time()
        db.command('ping')
        db_latency_ms = round((time.time() - t0) * 1000, 2)
        db_status = "Connected"
    except Exception as e:
        db_status = f"Degraded ({str(e)[:30]})"

    # Quick entity counts
    inst_count = institutes_col.count_documents({})
    results_count = results_col.count_documents({})
    app_count = applications_col.count_documents({})
    schemes_count = schemes_col.count_documents({})

    cpu_val = 0.0
    mem_used = 0
    if PSUTIL_AVAILABLE:
        try:
            cpu_val = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            mem_used = round(mem.used / (1024 * 1024), 1)
        except Exception:
            pass

    return jsonify({
        "service": "IGYR Admin Operations Deck",
        "role": "administrative_and_institutional_management",
        "status": "healthy" if db_status == "Connected" else "degraded",
        "uptime": uptime_str,
        "uptime_seconds": uptime_sec,
        "database": {
            "status": db_status,
            "latency_ms": db_latency_ms
        },
        "stats": {
            "institutes": inst_count,
            "results": results_count,
            "applications": app_count,
            "schemes": schemes_count
        },
        "telemetry": {
            "cpu_percent": cpu_val,
            "memory_used_mb": mem_used
        },
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }), 200


# ==========================================
# PAGE ROUTING (Admin & Institute)
# ==========================================

@app.route('/')
def admin_root():
    """Default root route redirects to admin login."""
    return send_from_directory('.', 'admin-login.html')

@app.route('/admin-login.html')
@app.route('/admin-login')
def serve_admin_login():
    return send_from_directory('.', 'admin-login.html')

@app.route('/admin-dashboard.html')
@app.route('/admin-dashboard')
def serve_admin_dashboard():
    return send_from_directory('.', 'admin-dashboard.html')

@app.route('/admin-applications.html')
@app.route('/admin-applications')
def serve_admin_applications():
    return send_from_directory('.', 'admin-applications.html')

@app.route('/admin-broadcast.html')
@app.route('/admin-broadcast')
def serve_admin_broadcast():
    return send_from_directory('.', 'admin-broadcast.html')

@app.route('/admin-institutes.html')
@app.route('/admin-institutes')
def serve_admin_institutes():
    return send_from_directory('.', 'admin-institutes.html')

@app.route('/admin-schemes.html')
@app.route('/admin-schemes')
def serve_admin_schemes():
    return send_from_directory('.', 'admin-schemes.html')

@app.route('/admin-settings.html')
@app.route('/admin-settings')
def serve_admin_settings():
    return send_from_directory('.', 'admin-settings.html')

@app.route('/admin-login-institute.html')
def serve_admin_login_institute():
    return send_from_directory('.', 'admin-login-institute.html')

@app.route('/institute-dashboard.html')
def serve_inst_dash():
    return send_from_directory('.', 'institute-dashboard.html')

@app.route('/institute-drafts.html')
def serve_inst_drafts():
    return send_from_directory('.', 'institute-drafts.html')

@app.route('/institute-register.html')
def serve_inst_register():
    return send_from_directory('.', 'institute-register.html')

@app.route('/institute-settings.html')
def serve_inst_settings():
    return send_from_directory('.', 'institute-settings.html')

@app.route('/institute-tabulation.html')
def serve_inst_tab():
    return send_from_directory('.', 'institute-tabulation.html')

@app.route('/institute-upload-result.html')
def serve_inst_upload():
    return send_from_directory('.', 'institute-upload-result.html')


# ==========================================
# AUTHENTICATION APIS
# ==========================================

@app.route('/api/auth/admin', methods=['POST'])
def admin_login():
    data = request.json or {}
    if data.get('username') == 'admin' and data.get('password') == 'cutiee':
        return jsonify({"success": True, "token": "igyr_super_secret_auth_token_8829"}), 200
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@app.route('/api/auth/institute', methods=['POST'])
def institute_login():
    data = request.json or {}
    inst_id = data.get('id')
    password = data.get('password')
    inst = institutes_col.find_one({"id": inst_id, "password": password})
    if inst:
        return jsonify({"success": True, "token": "igyr_inst_secret_auth_token_7731"}), 200
    return jsonify({"success": False, "message": "Invalid credentials"}), 401


# ==========================================
# DATA MANAGEMENT APIS (Interconnected)
# ==========================================

@app.route('/api/sync', methods=['GET'])
def sync_data():
    global _sync_cache, _sync_cache_time
    now = time.time()
    if _sync_cache is not None and (now - _sync_cache_time) < CACHE_TTL:
        return jsonify(_sync_cache)

    try:
        institutes = list(institutes_col.find({}, {'_id': 0}))
        for inst in institutes:
            inst.pop('password', None)
        results = list(results_col.find({}, {'_id': 0}))
        notices = list(notices_col.find({}, {'_id': 0}))

        ql_doc = quicklinks_col.find_one({}, {'_id': 0})
        quicklinks = ql_doc['links'] if ql_doc and 'links' in ql_doc else []

        schemes = list(schemes_col.find({}, {'_id': 0}))
        applications = list(applications_col.find({}, {'_id': 0}))
        settings_doc = settings_col.find_one({}, {'_id': 0})
        settings = settings_doc if settings_doc else {}

        _sync_cache = {
            "institutes": institutes,
            "results": results,
            "notices": notices,
            "quicklinks": quicklinks,
            "schemes": schemes,
            "applications": applications,
            "settings": settings
        }
        _sync_cache_time = now
        return jsonify(_sync_cache)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/institutes', methods=['POST'])
def save_institutes():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if data:
        current_institutes = {inst['id']: inst.get('password') for inst in institutes_col.find({}, {'id': 1, 'password': 1, '_id': 0}) if 'id' in inst}
        for inst in data:
            if 'id' in inst and inst['id'] in current_institutes and current_institutes[inst['id']]:
                inst['password'] = current_institutes[inst['id']]
        institutes_col.delete_many({})
        institutes_col.insert_many(data)
        invalidate_sync_cache()
    return jsonify({"message": "Institutes saved"})

@app.route('/api/results', methods=['POST'])
def save_results():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if data:
        results_col.delete_many({})
        results_col.insert_many(data)
        invalidate_sync_cache()
        try:
            latest = data[-1] if isinstance(data, list) else data
            title = latest.get("title") or latest.get("candidateName") or "New Result Published"
            body = f"Examination results published for {latest.get('examName', 'Students')}. Tap to check marks."
            send_push_notification_to_all(title, body, url="/search-result.html")
        except Exception:
            pass
    return jsonify({"message": "Results saved"})

@app.route('/api/notices', methods=['POST'])
def save_notices():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if data:
        notices_col.delete_many({})
        notices_col.insert_many(data)
        invalidate_sync_cache()
    return jsonify({"message": "Notices saved"})

@app.route('/api/quicklinks', methods=['POST'])
def save_quicklinks():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if data:
        quicklinks_col.delete_many({})
        quicklinks_col.insert_one({"links": data})
        invalidate_sync_cache()
    return jsonify({"message": "Quicklinks saved"})

@app.route('/api/schemes', methods=['POST'])
def save_schemes():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if data:
        schemes_col.delete_many({})
        schemes_col.insert_many(data)
        invalidate_sync_cache()
        try:
            latest = data[-1] if isinstance(data, list) else data
            title = latest.get("name") or "New Government Scheme Announced"
            body = latest.get("benefit") or "Check your eligibility and apply online now on IGYR."
            send_push_notification_to_all(title, body, url="/schemes.html")
        except Exception:
            pass
    return jsonify({"message": "Schemes saved"})

@app.route('/api/applications', methods=['POST'])
def save_application():
    data = request.json
    if data:
        applications_col.update_one({"id": data.get("id")}, {"$set": data}, upsert=True)
        invalidate_sync_cache()
    return jsonify({"message": "Application saved successfully"})

@app.route('/api/applications/save-all', methods=['POST'])
def save_all_applications():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if data is not None:
        applications_col.delete_many({})
        if len(data) > 0:
            applications_col.insert_many(data)
        invalidate_sync_cache()
    return jsonify({"message": "All applications saved successfully"})

@app.route('/api/settings', methods=['POST'])
def save_settings():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if data:
        settings_col.update_one({"id": "system_settings"}, {"$set": data}, upsert=True)
        invalidate_sync_cache()
    return jsonify({"message": "Settings saved"})

@app.route('/api/banner', methods=['GET'])
def get_banner():
    banner = banner_col.find_one({"id": "active_banner"}, {"_id": 0})
    if not banner:
        return jsonify({
            "enabled": False,
            "title": "",
            "message": "",
            "type": "info",
            "linkText": "",
            "linkUrl": "",
            "audience": "all",
            "startDate": "",
            "endDate": "",
            "dismissible": True
        })
    return jsonify(banner)

@app.route('/api/admin/banner', methods=['POST'])
def save_banner():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if not data:
        return jsonify({"error": "Invalid payload"}), 400
    data["id"] = "active_banner"
    data["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    banner_col.update_one({"id": "active_banner"}, {"$set": data}, upsert=True)
    return jsonify({"success": True, "message": "Banner announcement saved successfully", "banner": data})

@app.route('/api/admin/broadcast-notification', methods=['POST'])
def broadcast_notification():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    url = (data.get('url') or '/search-result.html').strip()

    if not title or not body:
        return jsonify({"success": False, "error": "Title and Message Body are required."}), 400

    result = send_push_notification_to_all(title, body, url)
    return jsonify(result)

@app.route('/api/admin/notifications/stats', methods=['GET'])
def get_notification_stats():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    total_tokens = fcm_tokens_col.count_documents({})
    return jsonify({"success": True, "total_subscribers": total_tokens})

@app.route('/api/admin/notifications/sync-subscribers', methods=['POST'])
def sync_subscribers():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    tokens = data.get('tokens') or []
    if not tokens or not isinstance(tokens, list):
        return jsonify({"success": False, "error": "tokens array required"}), 400

    count = 0
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    for t in tokens:
        if t and isinstance(t, str):
            fcm_tokens_col.update_one(
                {"token": t.strip()},
                {"$set": {"token": t.strip(), "updated_at": now}},
                upsert=True
            )
            count += 1
    return jsonify({"success": True, "message": f"Synced {count} subscribers."})

# WhatsApp Endpoints
@app.route('/api/admin/whatsapp/config', methods=['GET'])
def api_get_whatsapp_config():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    cfg = get_whatsapp_config()
    cfg_safe = cfg.copy()
    raw_token = cfg_safe.get("token") or ""
    if raw_token:
        cfg_safe["token_masked"] = raw_token[:6] + "..." + raw_token[-4:]
        cfg_safe["has_token"] = True
    else:
        cfg_safe["token_masked"] = ""
        cfg_safe["has_token"] = False
    cfg_safe.pop("token", None)
    return jsonify({"success": True, "config": cfg_safe})

@app.route('/api/admin/whatsapp/config', methods=['POST'])
def api_set_whatsapp_config():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    doc = {
        "id": "whatsapp_config",
        "enabled": bool(data.get("enabled", False)),
        "verify_token": (data.get("verify_token") or "igyr_wa_verify_2026").strip(),
        "phone_number_id": (data.get("phone_number_id") or "").strip(),
        "waba_id": (data.get("waba_id") or "").strip(),
        "welcome_message": (data.get("welcome_message") or "").strip(),
        "not_found_message": (data.get("not_found_message") or "").strip(),
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }
    new_token = (data.get("token") or "").strip()
    if new_token:
        doc["token"] = new_token
    else:
        existing = whatsapp_config_col.find_one({"id": "whatsapp_config"})
        if existing and existing.get("token"):
            doc["token"] = existing["token"]

    whatsapp_config_col.update_one({"id": "whatsapp_config"}, {"$set": doc}, upsert=True)
    return jsonify({"success": True, "message": "WhatsApp configuration updated successfully."})

@app.route('/api/admin/whatsapp/test-send', methods=['POST'])
def test_send_whatsapp():
    if not verify_token(): return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    to_phone = (data.get('to_phone') or "").strip()
    test_query = (data.get('query') or "HI").strip()
    if not to_phone:
        return jsonify({"success": False, "error": "Please provide a recipient phone number."}), 400

    automated_message = build_whatsapp_automated_response(test_query, sender_name="Admin Test")
    res = send_whatsapp_message(to_phone, automated_message)

    try:
        whatsapp_logs_col.insert_one({
            "from": to_phone,
            "sender_name": "Admin Tester",
            "incoming_message": f"[TEST SIMULATION] {test_query}",
            "reply_message": automated_message,
            "dispatch_status": "SENT" if res.get("success") else "FAILED",
            "dispatch_error": res.get("error"),
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "epoch": int(datetime.utcnow().timestamp())
        })
    except Exception:
        pass

    return jsonify({
        "success": res.get("success", False),
        "message_preview": automated_message,
        "dispatch_result": res
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5007))
    print(f"🚀 IGYR Dedicated Admin Server running on http://0.0.0.0:{port}/")
    app.run(host='0.0.0.0', port=port, debug=False)
