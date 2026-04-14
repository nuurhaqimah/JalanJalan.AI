import os
import json
import urllib.parse
import psycopg2
import requests
import google.generativeai as genai
import re
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from database import save_itinerary, get_pois, query_db as db_query_db
from prompts import SYSTEM_PROMPT
from flask import Flask, request, jsonify, render_template, send_file, session, redirect
from flask_cors import CORS
from datetime import datetime
from amadeus import Client, ResponseError
import tempfile

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False
    HTML = None

# Load environment variables
load_dotenv()

# Configure APIs
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        print("GEMINI_API_KEY loaded: True")
    except Exception as e:
        print(f"Failed to configure Gemini: {e}")
else:
    print("GEMINI_API_KEY loaded: False")

secret_key = os.getenv("SECRET_KEY", "supersecretkey")  # for sessions

AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")

# Initialize Amadeus client
amadeus = None
if AMADEUS_API_KEY and AMADEUS_API_SECRET:
    try:
        amadeus = Client(
            client_id=AMADEUS_API_KEY,
            client_secret=AMADEUS_API_SECRET,
            hostname='test'  # Use 'production' for live environment
        )
    except Exception as e:
        print(f"Failed to initialize Amadeus client: {e}")

# Initialize the generative model for text with system prompt if API key available
gemini_model = None
try:
    if GEMINI_API_KEY:
        # Use imported SYSTEM_PROMPT for consistent behavior
        gemini_model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=SYSTEM_PROMPT
        )
except Exception as e:
    print(f"Failed to initialize Gemini model: {e}")
app = Flask(__name__,
    template_folder='../frontend/templates',
    static_folder='../frontend/static')
CORS(app)
app.config['JSON_SORT_KEYS'] = False
app.secret_key = secret_key

# In-memory token store for demo (replace in production)
TOKENS = {}

def generate_token(user_id):
    token = generate_password_hash(f"{user_id}:{datetime.utcnow().isoformat()}")
    TOKENS[token] = {"user_id": user_id, "created": datetime.utcnow()}
    return token

def token_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[-1]
        if not token or token not in TOKENS:
            return jsonify({"error": "Token missing or invalid"}), 401
        return f(user_id=TOKENS[token]["user_id"], *args, **kwargs)
    return decorated

def get_pollinations_image(query, destination=None):
    prompt = f"cinematic photograph of {query}"
    if destination:
        prompt += f" in {destination}"
    encoded = urllib.parse.quote_plus(prompt)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=600&height=400&nologo=true"

# -------------------------
# Auth endpoints
# -------------------------
@app.route("/signup", methods=["POST"])
def signup():
    payload = request.json or {}
    username = payload.get("username")
    password = payload.get("password")
    email = payload.get("email")
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    pw_hash = generate_password_hash(password)
    try:
        db_query_db("INSERT INTO app_user (username, password_hash, email) VALUES (%s,%s,%s)",
                 (username, pw_hash, email))
        user = db_query_db("SELECT id FROM app_user WHERE username=%s", (username,), one=True)
        token = generate_token(user[0])
        return jsonify({"message": "user created", "token": token})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Simple check (you can store in DB or .env for security)
        admin_user = os.getenv("ADMIN_USER", "admin")
        admin_pass = os.getenv("ADMIN_PASS", "password123")

        if username == admin_user and password == admin_pass:
            session["admin_logged_in"] = True
            return redirect("/admin")
        else:
            return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect("/login")

@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect("/login")
    return render_template("admin.html")

# -------------------------
# DB config
# -------------------------
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "itinerary_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432))
}

# Use the query_db function from database.py instead of duplicating
# Remove duplicate function definition

# -------------------------
# Itinerary CRUD
# -------------------------
@app.route("/itineraries", methods=["POST"])
@token_required
def create_itinerary(user_id):
    payload = request.json or {}
    title = payload.get("title", "Untitled Trip")
    description = payload.get("description", "")
    data = payload.get("data", {})
    db_query_db("INSERT INTO itinerary (user_id, title, description, data) VALUES (%s,%s,%s,%s)",
             (user_id, title, description, json.dumps(data)))
    created = db_query_db("SELECT id, created_at FROM itinerary WHERE user_id=%s ORDER BY created_at DESC LIMIT 1",
                       (user_id,), one=True)
    return jsonify({"message": "itinerary created", "id": created[0], "created_at": created[1].isoformat()})

@app.route("/itineraries", methods=["GET"])
@token_required
def list_itineraries(user_id):
    rows = db_query_db("SELECT id, title, description, created_at, updated_at FROM itinerary WHERE user_id=%s ORDER BY created_at DESC",
                    (user_id,))
    items = []
    for r in rows:
        items.append({"id": r[0], "title": r[1], "description": r[2],
                      "created_at": r[3].isoformat(), "updated_at": (r[4].isoformat() if r[4] else None)})
    return jsonify(items)

@app.route("/itineraries/<int:it_id>", methods=["GET"])
@token_required
def get_itinerary(user_id, it_id):
    r = db_query_db("SELECT id, title, description, data, created_at, updated_at FROM itinerary WHERE id=%s AND user_id=%s",
                 (it_id, user_id), one=True)
    if not r:
        return jsonify({"error": "not found"}), 404
    return jsonify({"id": r[0], "title": r[1], "description": r[2], "data": r[3],
                    "created_at": r[4].isoformat(), "updated_at": (r[5].isoformat() if r[5] else None)})

@app.route("/itineraries/<int:it_id>", methods=["PUT"])
@token_required
def update_itinerary(user_id, it_id):
    payload = request.json or {}
    title = payload.get("title")
    description = payload.get("description")
    data = payload.get("data")
    query = "UPDATE itinerary SET updated_at=NOW()"
    args = []
    if title is not None:
        query += ", title=%s"
        args.append(title)
    if description is not None:
        query += ", description=%s"
        args.append(description)
    if data is not None:
        query += ", data=%s"
        args.append(json.dumps(data))
    query += " WHERE id=%s AND user_id=%s"
    args.extend([it_id, user_id])
    db_query_db(query, tuple(args))
    return jsonify({"message": "updated"})

@app.route("/itineraries/<int:it_id>", methods=["DELETE"])
@token_required
def delete_itinerary(user_id, it_id):
    db_query_db("DELETE FROM itinerary WHERE id=%s AND user_id=%s", (it_id, user_id))
    return jsonify({"message": "deleted"})

# -------------------------
# Export PDF
# -------------------------
@app.route("/export/<int:it_id>", methods=["GET"])
@token_required
def export_itinerary(user_id, it_id):
    if not WEASYPRINT_AVAILABLE:
        return jsonify({"error": "WeasyPrint not installed. Install weasyprint to enable PDF export."}), 500
    r = db_query_db("SELECT title, description, data FROM itinerary WHERE id=%s AND user_id=%s", (it_id, user_id), one=True)
    if not r:
        return jsonify({"error": "not found"}), 404
    title, description, data = r
    html = render_itinerary_html(title, description, data or {})
    pdf_dir = tempfile.gettempdir()
    pdf_path = os.path.join(pdf_dir, f"itinerary_{it_id}.pdf")
    HTML(string=html).write_pdf(pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name=f"itinerary_{it_id}.pdf")

def render_itinerary_html(title, description, data):
    items = data.get("schedule", []) if isinstance(data, dict) else []
    html = f"<html><head><meta charset='utf-8'><style>body{{font-family: Arial;padding:20px}}img{{max-width:600px}}.slot{{margin-bottom:12px;border-bottom:1px solid #ddd;padding-bottom:8px}}</style></head><body>"
    html += f"<h1>{title}</h1><p>{description}</p>"
    for s in items:
        start = s.get("start","")
        end = s.get("end","")
        name = s.get("name","")
        notes = s.get("notes","")
        img = s.get("image")
        html += f"<div class='slot'><h3>{start} - {end}: {name}</h3><p>{notes}</p>"
        if img:
            html += f"<img src='{img}'/>"
        html += "</div>"
    html += "</body></html>"
    return html

# -------------------------
# POI helper
# -------------------------


# -------------------------
# Conversation memory
# -------------------------
conversation_state = {}
# SYSTEM_PROMPT is imported from prompts.py

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

# -------------------------
# User auth (simple session-based)
# -------------------------
@app.route('/user/login', methods=['GET', 'POST'])
def user_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            return render_template('user_login.html', error='Username and password are required')

        # Look up user in DB
        row = db_query_db("SELECT id, password_hash FROM app_user WHERE username=%s", (username,), one=True)
        if not row:
            return render_template('user_login.html', error='Invalid username or password')
        user_id, pw_hash = row
        if not check_password_hash(pw_hash, password):
            return render_template('user_login.html', error='Invalid username or password')

        session['user'] = {"id": user_id, "name": username}
        return redirect('/trip')
    return render_template('user_login.html')

@app.route('/user/logout')
def user_logout():
    session.pop('user', None)
    return redirect('/')

@app.route('/user/signup', methods=['GET', 'POST'])
def user_signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip() or None
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')

        if not username or not password:
            return render_template('user_signup.html', error='Username and password are required')
        if password != confirm:
            return render_template('user_signup.html', error='Passwords do not match')

        # Check if username exists
        exists = db_query_db("SELECT 1 FROM app_user WHERE username=%s", (username,), one=True)
        if exists:
            return render_template('user_signup.html', error='Username already taken')

        pw_hash = generate_password_hash(password)
        db_query_db("INSERT INTO app_user (username, password_hash, email) VALUES (%s,%s,%s)", (username, pw_hash, email))
        # Fetch user id
        row = db_query_db("SELECT id FROM app_user WHERE username=%s", (username,), one=True)
        session['user'] = {"id": row[0], "name": username}
        return redirect('/trip')
    return render_template('user_signup.html')

@app.route('/trip')
def trip():
    # Require user login before accessing the trip planner
    if not session.get('user'):
        return redirect('/user/login')
    return render_template('trip.html')

@app.route('/mytrips')
def mytrips():
    # Require user login to view saved trips
    user = session.get('user')
    if not user:
        return redirect('/user/login')
    user_id = user.get('id')
    rows = db_query_db(
        "SELECT id, title, description, created_at FROM itinerary WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,)
    )
    trips = [
        {
            "id": r[0],
            "title": r[1],
            "description": r[2],
            "created_at": r[3].isoformat() if hasattr(r[3], 'isoformat') else str(r[3]),
        }
        for r in (rows or [])
    ]
    return render_template('mytrips.html', trips=trips)

@app.route('/trip/<int:it_id>')
def view_trip(it_id):
    # Require user login and ownership
    user = session.get('user')
    if not user:
        return redirect('/user/login')
    row = db_query_db(
        "SELECT id, title, description, data, created_at FROM itinerary WHERE id=%s AND user_id=%s",
        (it_id, user.get('id')),
        one=True
    )
    if not row:
        return redirect('/mytrips')
    trip = {
        "id": row[0],
        "title": row[1],
        "description": row[2],
        "data": row[3] or {},
        "created_at": row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]),
    }
    # If data is a string JSON, try to load
    if isinstance(trip["data"], str):
        try:
            trip["data"] = json.loads(trip["data"])
        except Exception:
            trip["data"] = {}
    return render_template('trip_detail.html', trip=trip)

@app.route('/mytrips/<int:it_id>/delete', methods=['DELETE'])
def delete_trip(it_id):
    user = session.get('user')
    if not user:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401
    db_query_db("DELETE FROM itinerary WHERE id=%s AND user_id=%s", (it_id, user.get('id')))
    return jsonify({"status": "success"})

@app.route("/admin/add", methods=["POST"])
def admin_add():
    try:
        data = request.form
        name = data.get("name")
        category = data.get("category")
        budget_level = data.get("budget_level")
        travel_style = data.get("travel_style")
        location = data.get("location")
        country = data.get("country")
        description = data.get("description")

        # Normalize values to match DB expectations and filters
        category_map = {
            "alam": "nature",
            "nature": "nature",
            "kuliner": "food",
            "food": "food",
            "sejarah": "history",
            "history": "history",
            "belanja": "shopping",
            "shopping": "shopping",
        }
        budget_map = {
            "cheap": "low",
            "low": "low",
            "moderate": "medium",
            "medium": "medium",
            "luxury": "high",
            "high": "high",
        }

        norm_category = category_map.get((category or "").lower(), category)
        norm_budget = budget_map.get((budget_level or "").lower(), budget_level)

        # Insert without latitude/longitude
        db_query_db(
            "INSERT INTO poi (name, category, description, location, country, budget_level, travel_style) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (name, norm_category, description, location, country, norm_budget, travel_style),
        )

        return jsonify({"status": "success", "message": f"POI '{name}' added successfully!"})
    except Exception as e:
        print(f"[ADMIN] Error inserting POI: {e}")
        return jsonify({"status": "error", "message": "Failed to insert POI"}), 500

@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def devtools():
    return '', 204

# -------------------------
# Amadeus helpers (flights + hotels)
# -------------------------
@app.route("/admin/pois", methods=["GET"])
def admin_list_pois():
    try:
        # Try selecting with travel_style and created_at ordering
        try:
            rows = db_query_db(
                "SELECT id, name, category, description, location, country, budget_level, travel_style FROM poi ORDER BY created_at DESC"
            )
            pois = [
                {
                    "id": r[0],
                    "name": r[1],
                    "category": r[2],
                    "description": r[3],
                    "location": r[4],
                    "country": r[5],
                    "budget_level": r[6],
                    "travel_style": r[7]
                }
                for r in rows
            ]
        except Exception:
            # Fallback if column travel_style isn't present in older schema
            rows = db_query_db(
                "SELECT id, name, category, description, location, country, budget_level FROM poi ORDER BY id DESC"
            )
            pois = [
                {
                    "id": r[0],
                    "name": r[1],
                    "category": r[2],
                    "description": r[3],
                    "location": r[4],
                    "country": r[5],
                    "budget_level": r[6],
                    "travel_style": None,
                }
                for r in rows
            ]
        return jsonify({"status": "success", "data": pois})
    except Exception as e:
        print(f"[ADMIN] Error listing POIs: {e}")
        return jsonify({"status": "error", "message": "Failed to list POIs"}), 500


@app.route("/api/poi/filters", methods=["GET"])
def poi_filters():
    try:
        cats = db_query_db("SELECT DISTINCT category FROM poi WHERE category IS NOT NULL AND category <> '' ORDER BY category")
        budgets = db_query_db("SELECT DISTINCT budget_level FROM poi WHERE budget_level IS NOT NULL AND budget_level <> '' ORDER BY budget_level")
        styles = db_query_db("SELECT DISTINCT travel_style FROM poi WHERE travel_style IS NOT NULL AND travel_style <> '' ORDER BY travel_style")
        # Optional filter: country to narrow locations
        country_filter = request.args.get('country')
        if country_filter:
            locs = db_query_db(
                "SELECT DISTINCT location FROM poi WHERE location IS NOT NULL AND location <> '' AND country ILIKE %s ORDER BY location",
                (country_filter,)
            )
        else:
            locs = db_query_db("SELECT DISTINCT location FROM poi WHERE location IS NOT NULL AND location <> '' ORDER BY location")
        countries = db_query_db("SELECT DISTINCT country FROM poi WHERE country IS NOT NULL AND country <> '' ORDER BY country")
        return jsonify({
            "categories": [c[0] for c in cats],
            "budget_levels": [b[0] for b in budgets],
            "travel_styles": [s[0] for s in styles],
            "locations": [l[0] for l in locs],
            "countries": [x[0] for x in countries],
        })
    except Exception as e:
        print(f"[API] filters error: {e}")
        return jsonify({"error": "Failed to load filters"}), 500


@app.route("/admin/poi/<int:poi_id>", methods=["DELETE"])
def admin_delete_poi(poi_id):
    try:
        db_query_db("DELETE FROM poi WHERE id=%s", (poi_id,))
        return jsonify({"status": "success", "message": "POI deleted"})
    except Exception as e:
        print(f"[ADMIN] Error deleting POI: {e}")
        return jsonify({"status": "error", "message": "Failed to delete POI"}), 500


@app.route("/admin/poi/<int:poi_id>", methods=["PUT"])
def admin_update_poi(poi_id):
    try:
        data = request.form if request.form else (request.json or {})
        # Fields allowed to update
        name = data.get("name")
        category = data.get("category")
        budget_level = data.get("budget_level")
        travel_style = data.get("travel_style")
        location = data.get("location")
        country = data.get("country")
        description = data.get("description")

        # Normalize like /admin/add
        category_map = {
            "alam": "nature",
            "nature": "nature",
            "kuliner": "food",
            "food": "food",
            "sejarah": "history",
            "history": "history",
            "belanja": "shopping",
            "shopping": "shopping",
        }
        budget_map = {
            "cheap": "low",
            "low": "low",
            "moderate": "medium",
            "medium": "medium",
            "luxury": "high",
            "high": "high",
        }
        if category:
            category = category_map.get((category or "").lower(), category)
        if budget_level:
            budget_level = budget_map.get((budget_level or "").lower(), budget_level)

        query = "UPDATE poi SET "
        sets = []
        args = []
        if name is not None:
            sets.append("name=%s")
            args.append(name)
        if category is not None:
            sets.append("category=%s")
            args.append(category)
        if description is not None:
            sets.append("description=%s")
            args.append(description)
        if location is not None:
            sets.append("location=%s")
            args.append(location)
        if country is not None:
            sets.append("country=%s")
            args.append(country)
        if budget_level is not None:
            sets.append("budget_level=%s")
            args.append(budget_level)
        if travel_style is not None:
            sets.append("travel_style=%s")
            args.append(travel_style)

        if not sets:
            return jsonify({"status": "error", "message": "No fields to update"}), 400

        query += ", ".join(sets) + " WHERE id=%s"
        args.append(poi_id)
        db_query_db(query, tuple(args))
        return jsonify({"status": "success", "message": "POI updated"})
    except Exception as e:
        print(f"[ADMIN] Error updating POI: {e}")
        return jsonify({"status": "error", "message": "Failed to update POI"}), 500
def get_amadeus_token():
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET,
    }
    res = requests.post(url, headers=headers, data=data).json()
    return res.get("access_token")

def search_amadeus_flights(origin, destination, date):
    token = get_amadeus_token()
    url = f"https://test.api.amadeus.com/v2/shopping/flight-offers?originLocationCode={origin}&destinationLocationCode={destination}&departureDate={date}&adults=1&max=3"
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers).json()

    flights = []
    for offer in res.get("data", []):
        price = offer["price"]["total"]
        itinerary = offer["itineraries"][0]["segments"][0]
        flights.append({
            "airline": itinerary["carrierCode"],
            "flight_number": itinerary["number"],
            "departure": itinerary["departure"]["iataCode"],
            "arrival": itinerary["arrival"]["iataCode"],
            "price": price,
            "currency": res["meta"]["currency"]
        })
    return flights

def search_amadeus_hotels(city_code):
    token = get_amadeus_token()
    url = f"https://test.api.amadeus.com/v1/reference-data/locations?subType=CITY&keyword={city_code}"
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers).json()
    hotels = []
    for item in res.get("data", []):
        hotels.append({
            "name": item["name"],
            "address": item["address"]["cityName"],
            "price": "TBD",
            "currency": "USD",
            "rating": "4.5",
            "image": "/static/assets/hotel1.jpg"
        })
    return hotels

# -------------------------
# Chatbot endpoint
# -------------------------
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json or {}
    except Exception as e:
        # Log bad JSON and continue with defaults
        print(f"/chat JSON parse error: {e}")
        data = {}
    print(f"/chat request: data={data}")
    user_message = data.get("message", "")
    user_id = data.get("user_id", session.get('user', {}).get('id', 'guest'))
    prefs = data.get("prefs", {})  # expects keys: interests (category), budget, travel_style, location

    # --- STEP 1: Gemini System Prompt is configured globally via prompts.SYSTEM_PROMPT ---
    # If Gemini is not available, we will still proceed with rule-based flow and friendly fallbacks.
    # --- STEP 2: Amadeus check ---
    lower_msg = user_message.lower()
    try:
        if "flight" in lower_msg or "pesawat" in lower_msg:
            flights = search_amadeus_flights("CGK", "DPS", "2025-10-01")  # Example params
            return jsonify({
               "reply": "✈️ Here are some flight options you might consider:",
               "flights": flights,
               "itinerary": None,
               "hotels": None
           })

        if "hotel" in lower_msg or "penginapan" in lower_msg:
            hotels = search_amadeus_hotels("Bali")  # Example params
            return jsonify({
               "reply": "🏨 Here are some hotel options you might like:",
               "hotels": hotels,
               "flights": None,
               "itinerary": None
            })
    except Exception:
        # Silently ignore Amadeus errors and continue with conversational flow
        pass


    # --- STEP 3: Conversational flow + itinerary ---
    try:
        # Per-user state
        state = conversation_state.setdefault(str(user_id), {
            "country": None,
            "budget": None,
            "interests": [],
            "travel_style": None,
            "location": None,
        })

        # Load reference lists from DB with safe fallbacks
        preset_countries = ["Brunei", "Malaysia", "Thailand", "Singapore", "Indonesia", "Philippines"]
        preset_categories = ["nature", "food", "history", "shopping"]
        preset_styles = ["relaxing", "adventure", "cultural", "family"]

        try:
            available_countries = [r[0] for r in (db_query_db("SELECT DISTINCT country FROM poi WHERE country IS NOT NULL AND country <> '' ORDER BY country") or [])]
        except Exception:
            available_countries = []
        if not available_countries:
            available_countries = preset_countries

        try:
            categories = [r[0] for r in (db_query_db("SELECT DISTINCT category FROM poi WHERE category IS NOT NULL AND category <> '' ORDER BY category") or [])]
        except Exception:
            categories = []
        if not categories:
            categories = preset_categories

        try:
            styles = [r[0] for r in (db_query_db("SELECT DISTINCT travel_style FROM poi WHERE travel_style IS NOT NULL AND travel_style <> '' ORDER BY travel_style") or [])]
        except Exception:
            styles = []
        if not styles:
            styles = preset_styles

        def contains_any(text, choices):
            t = (text or "").lower()
            for c in choices:
                if c and c.lower() in t:
                    return c
            return None

        # COUNTRY
        if not state["country"]:
            wanted = (prefs.get("country") if isinstance(prefs, dict) else None) or contains_any(user_message, available_countries)
            if wanted:
                match = next((c for c in available_countries if c.lower() == str(wanted).lower()), None)
                if match:
                    state["country"] = match
                else:
                    return jsonify({"reply": "Sorry, I can only help with these countries.", "countries": available_countries, "options": available_countries, "next": "country"})
            else:
                return jsonify({"reply": "Hi! Which country would you like to visit this weekend?", "countries": available_countries, "options": available_countries, "next": "country"})

        # BUDGET
        if not state["budget"]:
            wanted = (prefs.get("budget") if isinstance(prefs, dict) else None) or contains_any(user_message, ["low","medium","high","cheap","moderate","luxury"])
            if wanted:
                norm = {"cheap":"low","moderate":"medium","luxury":"high"}.get(str(wanted).lower(), str(wanted).lower())
                if norm in ["low","medium","high"]:
                    state["budget"] = norm
                else:
                    return jsonify({"reply": "Please choose a budget:", "options": ["low","medium","high"], "next": "budget"})
            else:
                country_name = state.get("country") or "That"
                highlights = {
                    "Japan": "food, culture and nature",
                    "Singapore": "world-class food and city sights",
                    "Thailand": "beaches, temples and night markets",
                    "Indonesia": "islands, volcano treks and local cuisine",
                    "Malaysia": "multicultural food and lush nature",
                    "Philippines": "island hopping and white-sand beaches",
                    "Brunei": "peaceful forests and cultural landmarks",
                    "Vietnam": "street food and heritage towns",
                    "South Korea": "K-culture, shopping and palaces",
                }
                flair = highlights.get(str(country_name), "great experiences")
                reply_txt = (
                    f"{country_name} is a great choice! To generate a perfect trip for you, could you tell me the budget for your travels? "
                    f"We’ll tailor activities around {flair}."
                )
                return jsonify({
                    "reply": reply_txt,
                    "options": ["low","medium","high"],
                    "next": "budget",
                    "context": {"country": country_name}
                })

        # INTERESTS (1–2)
        if not state["interests"]:
            chosen = []
            if isinstance(prefs, dict) and prefs.get("interests"):
                in_list = prefs.get("interests") if isinstance(prefs.get("interests"), list) else [prefs.get("interests")]
                for x in in_list:
                    m = next((c for c in categories if c.lower()==str(x).lower()), None)
                    if m: chosen.append(m)
            else:
                for c in categories:
                    if c and c.lower() in lower_msg:
                        chosen.append(c)
            # Indonesian aliases + common synonyms that aren't valid category names
            alias_map = {
                "alam": "nature", "kuliner": "food", "sejarah": "history", "belanja": "shopping",
                "cultural": "history", "culture": "history", "museum": "history",
                "eat": "food", "eating": "food", "restaurant": "food", "cuisine": "food",
                "shop": "shopping", "mall": "shopping",
                "outdoor": "nature", "beach": "nature", "park": "nature",
            }
            for alias, mapped in alias_map.items():
                if alias in lower_msg and mapped not in chosen:
                    chosen.append(mapped)
            chosen = list(dict.fromkeys(chosen))[:2]
            if chosen:
                state["interests"] = chosen
            else:
                ctry = state.get("country")
                suggest_map = {
                    "Japan": ["food", "history", "nature"],
                    "Singapore": ["food", "shopping", "history"],
                    "Thailand": ["nature", "shopping", "history"],
                    "Indonesia": ["nature", "food", "shopping"],
                    "Malaysia": ["food", "nature", "history"],
                    "Philippines": ["nature", "shopping"],
                    "Brunei": ["history", "nature"],
                }
                hints = ", ".join(suggest_map.get(str(ctry), [])[:2])
                base = f"Awesome! For {ctry}, what are you into? Pick 1–2 interests."
                if hints:
                    base += f" Popular choices: {hints}."
                return jsonify({"reply": base, "options": categories, "next": "interests"})

        # STYLE (optional but we’ll ask if available)
        if not state["travel_style"] and styles:
            wanted = (prefs.get("travel_style") if isinstance(prefs, dict) else None) or contains_any(user_message, styles)
            if wanted:
                state["travel_style"] = next((s for s in styles if s.lower()==str(wanted).lower()), wanted)
            else:
                ctry = state.get("country")
                style_txt = f"Great! To fine-tune your {ctry} trip, what travel style do you prefer?"
                return jsonify({"reply": style_txt, "options": styles, "next": "travel_style"})

        # Optional location
        if not state["location"] and isinstance(prefs, dict) and prefs.get("location"):
            state["location"] = prefs.get("location")

        # Build itinerary
        interests = state["interests"]
        budget = state["budget"]
        travel_style = state.get("travel_style")
        country = state.get("country")

        time_blocks = [(9,11), (11,13), (14,16), (17,19)]
        needed_pois = len(time_blocks) * 2

        collected = []
        idx = 0
        failed_streak = 0
        while len(collected) < needed_pois and interests:
            interest = interests[idx % len(interests)]
            pois = get_pois(category=interest, budget_level=budget, travel_style=travel_style, location=state.get("location"), country=country, limit=1)
            if pois:
                collected.extend(pois)
                failed_streak = 0
            else:
                failed_streak += 1
                if failed_streak >= len(interests):
                    break
            idx += 1
        # Fallback 1: drop category filter, keep budget + style + country
        if len(collected) < needed_pois:
            extra = get_pois(budget_level=budget, travel_style=travel_style, location=state.get("location"), country=country, limit=needed_pois - len(collected))
            collected.extend(extra)
        # Fallback 2: drop budget + style, keep country only
        if len(collected) < needed_pois:
            extra = get_pois(country=country, limit=needed_pois - len(collected))
            collected.extend(extra)
        # Fallback 3: any POI at all
        if len(collected) < needed_pois:
            extra = get_pois(limit=needed_pois - len(collected))
            collected.extend(extra)
        collected = collected[:needed_pois]

        itinerary = []
        days = ["Saturday", "Sunday"]
        k = 0
        for d in range(2):
            for tb in time_blocks:
                poi = collected[k % len(collected)] if collected else None
                k += 1
                if poi:
                    itinerary.append({
                        "day": days[d],
                        "time": f"{tb[0]:02d}:00 - {tb[1]:02d}:00",
                        "title": poi["name"],
                        "location": poi.get("location"),
                        "category": poi.get("category"),
                        "notes": poi.get("description"),
                    })

        schedule_text = "Awesome! I’ve put together a relaxed weekend plan. Feel free to tweak anything—want more food spots or nature?\n\n"
        current_day = None
        for item in itinerary:
            if item["day"] != current_day:
                current_day = item["day"]
                schedule_text += f"{current_day}:\n"
            schedule_text += f"- {item['time']}: {item['title']} ({item.get('category','')}) — {item.get('location','')}\n"

        # Persist the itinerary automatically
        try:
            # Save to legacy table 'itineraries' (string user_id allowed; store schedule as JSON)
            try:
                legacy_user_id = str(session.get('user', {}).get('id')) if session.get('user') else str(user_id)
            except Exception:
                legacy_user_id = str(user_id)
            db_query_db(
                "INSERT INTO itineraries (user_id, data) VALUES (%s, %s)",
                (legacy_user_id, json.dumps({"schedule": itinerary}))
            )
        except Exception as e:
            # Do not block the chat response on legacy save errors
            print(f"/chat: failed to save legacy itinerary: {e}")

        # Also save to primary table 'itinerary' when a real user session exists
        try:
            sess_user = session.get('user')
            if sess_user and sess_user.get('id') is not None:
                title = f"{country or 'Trip'} Weekend Trip"
                if budget:
                    title = f"{title} ({budget.title()})"
                description = f"Auto-generated itinerary for {country or 'your destination'}"
                db_query_db(
                    "INSERT INTO itinerary (user_id, title, description, data) VALUES (%s,%s,%s,%s)",
                    (sess_user.get('id'), title, description, json.dumps({"schedule": itinerary}))
                )
        except Exception as e:
            print(f"/chat: failed to save primary itinerary: {e}")

        # Reset for next conversation; keep country as default
        conversation_state[str(user_id)] = {"country": state.get("country"), "budget": None, "interests": [], "travel_style": None, "location": None}

        return jsonify({
            "reply": schedule_text.strip(),
            "itinerary": itinerary,
            "flights": None,
            "hotels": None
        })
    except Exception as e:
        # Log and fallback to Gemini for graceful response (always 200)
        print(f"/chat error in rule-based flow: {e}")
        try:
            if gemini_model:
                response = gemini_model.generate_content(f"User: {user_message}\nAssistant:")
                reply_text = (response.text or "").strip()
            else:
                raise RuntimeError("Gemini not initialized")
        except Exception:
            reply_text = "Hi! Let’s plan a weekend trip. Which country would you like to visit?"
        return jsonify({"reply": reply_text, "itinerary": None, "flights": None, "hotels": None})

# Simple health endpoint for connectivity checks
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

# -------------------------
# Session-based: Save itinerary to primary table and export to PDF
# -------------------------
@app.route('/mytrips/save', methods=['POST'])
def mytrips_save():
    user = session.get('user')
    if not user:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401
    payload = request.json or {}
    title = payload.get('title') or 'Weekend Trip'
    description = payload.get('description') or ''
    data = payload.get('data') or {}
    try:
        db_query_db(
            "INSERT INTO itinerary (user_id, title, description, data) VALUES (%s,%s,%s,%s)",
            (user.get('id'), title, description, json.dumps(data))
        )
        row = db_query_db(
            "SELECT id, created_at FROM itinerary WHERE user_id=%s ORDER BY created_at DESC LIMIT 1",
            (user.get('id'),),
            one=True
        )
        return jsonify({"status": "success", "id": row[0], "created_at": getattr(row[1], 'isoformat', lambda: str(row[1]))()})
    except Exception as e:
        print(f"[MYTRIPS SAVE] error: {e}")
        return jsonify({"status": "error", "message": "Failed to save"}), 500

@app.route('/mytrips/<int:it_id>/export', methods=['GET'])
def mytrips_export(it_id):
    user = session.get('user')
    if not user:
        return redirect('/user/login')
    if not WEASYPRINT_AVAILABLE:
        return jsonify({"error": "WeasyPrint not installed. Install weasyprint to enable PDF export."}), 500
    r = db_query_db("SELECT title, description, data FROM itinerary WHERE id=%s AND user_id=%s", (it_id, user.get('id')), one=True)
    if not r:
        return redirect('/mytrips')
    title, description, data = r
    html = render_itinerary_html(title, description, data or {})
    pdf_dir = tempfile.gettempdir()
    pdf_path = os.path.join(pdf_dir, f"itinerary_{it_id}.pdf")
    HTML(string=html).write_pdf(pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name=f"itinerary_{it_id}.pdf")

# -------------------------
# Save itinerary (legacy table 'itineraries')
# -------------------------
@app.route("/itineraries/legacy", methods=["POST"])
def save_itinerary_legacy():
    try:
        payload = request.json or {}
    except Exception:
        payload = {}
    user = session.get('user')
    user_id = str(user.get('id')) if user and user.get('id') is not None else 'guest'

    data = payload.get("data")  # expected to be a dict like { schedule: [...] }
    title = payload.get("title")  # optional, ignored by legacy schema
    description = payload.get("description")  # optional, ignored by legacy schema

    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "data must be an object"}), 400

    try:
        row = db_query_db(
            "INSERT INTO itineraries (user_id, data) VALUES (%s, %s) RETURNING id",
            (user_id, json.dumps(data)),
            one=True
        )
        new_id = row[0] if row else None
        return jsonify({"status": "success", "id": new_id})
    except Exception as e:
        print(f"[LEGACY SAVE] error: {e}")
        return jsonify({"status": "error", "message": "Failed to save"}), 500

# -------------------------
# Flights Search (Amadeus)
# -------------------------
@app.route("/flights/search", methods=["POST"])
@token_required
def search_flights(user_id):
    payload = request.json or {}
    origin = payload.get("origin")       # e.g. "NYC"
    destination = payload.get("destination") # e.g. "LON"
    depart_date = payload.get("depart_date") # e.g. "2025-10-01"
    return_date = payload.get("return_date") # optional
    adults = payload.get("adults", 1)

    if not origin or not destination or not depart_date:
        return jsonify({"error": "origin, destination, and depart_date required"}), 400

    try:
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": depart_date,
            "adults": adults,
            "currencyCode": "USD",
            "max": 5
        }
        if return_date:
            params["returnDate"] = return_date

        if not amadeus:
            return jsonify({"error": "Amadeus client not initialized. Check API credentials."}), 500
        response = amadeus.shopping.flight_offers_search.get(**params)
        offers = []
        for item in response.data:
            price = item["price"]["total"]
            segments = []
            for itin in item["itineraries"]:
                for seg in itin["segments"]:
                    segments.append({
                        "from": seg["departure"]["iataCode"],
                        "to": seg["arrival"]["iataCode"],
                        "depart": seg["departure"]["at"],
                        "arrive": seg["arrival"]["at"],
                        "carrier": seg["carrierCode"]
                    })
            offers.append({"price": price, "segments": segments})
        return jsonify(offers)
    except ResponseError as e:
        return jsonify({"error": str(e)}), 500
    
# -------------------------
# Hotels Search (Amadeus)
# -------------------------
@app.route("/hotels/search", methods=["POST"])
@token_required
def search_hotels(user_id):
    payload = request.json or {}
    city_code = payload.get("city_code")    # e.g. "NYC"
    check_in = payload.get("check_in")      # e.g. "2025-10-01"
    check_out = payload.get("check_out")    # e.g. "2025-10-05"
    adults = payload.get("adults", 1)

    if not city_code or not check_in or not check_out:
        return jsonify({"error": "city_code, check_in, and check_out required"}), 400

    try:
        if not amadeus:
            return jsonify({"error": "Amadeus client not initialized. Check API credentials."}), 500
        response = amadeus.shopping.hotel_offers.get(
            cityCode=city_code,
            checkInDate=check_in,
            checkOutDate=check_out,
            adults=adults
        )
        hotels = []
        for h in response.data:
            hotel = h["hotel"]
            offers = h.get("offers", [])
            hotels.append({
                "name": hotel.get("name"),
                "address": hotel.get("address", {}).get("lines"),
                "rating": hotel.get("rating"),
                "offers": [
                    {
                        "price": o["price"]["total"],
                        "checkInDate": o.get("checkInDate"),
                        "checkOutDate": o.get("checkOutDate"),
                        "room": o.get("room", {}).get("typeEstimated", {}).get("category")
                    }
                    for o in offers
                ]
            })
        return jsonify(hotels)
    except ResponseError as e:
        return jsonify({"error": str(e)}), 500


# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))