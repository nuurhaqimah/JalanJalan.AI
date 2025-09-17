import os
import json
import urllib.parse
import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template, redirect, url_for, session
from flask_cors import CORS
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import google.generativeai as genai
from backend.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from backend.database import database

# -------------------------
# Load environment + API setup
# -------------------------
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")
CORS(app)

# -------------------------
# Login Management
# -------------------------
login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id_, name, email):
        self.id = id_
        self.name = name
        self.email = email

# In-memory user store (replace later with DB if you want persistence)
users = {}

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

# -------------------------
# OAuth Setup
# -------------------------
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)



# -------------------------
# Database Config
# -------------------------
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "itinerary_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", 5432),
}

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

def query_db(query, args=(), one=False):
    conn = get_db_connection()
    cur = conn.cursor()
    rv = None
    try:
        cur.execute(query, args)
        if cur.description:
            rv = cur.fetchall()
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB] error: {e}")
        raise
    finally:
        cur.close()
        conn.close()
    return (rv[0] if rv else None) if one else rv

# -------------------------
# Routes (Frontend)
# -------------------------
@app.route("/")
def index():
    return render_template("index.html", user=current_user if current_user.is_authenticated else None)

@app.route("/about")
def about():
    return render_template("about.html", user=current_user if current_user.is_authenticated else None)

@app.route("/contact")
def contact():
    return render_template("contact.html", user=current_user if current_user.is_authenticated else None)

@app.route("/trip")
@login_required
def trip():
    return render_template("trip.html", user=current_user)

@app.route("/mytrips")
@login_required
def mytrips():
    return render_template("mytrips.html", user=current_user)

# -------------------------
# Auth Routes
# -------------------------
@app.route("/login")
def login():
    redirect_uri = url_for("auth_callback", _external=True)
    return google.authorize_redirect(
        redirect_uri,
        prompt="select_account"   # <-- Forces account selection each time
    )

@app.route("/auth/callback")
def auth_callback():
    try:
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.userinfo()
        print("[GOOGLE USERINFO]", user_info)

        user_id = user_info["sub"]
        # Create user object for Flask-Login
        user = User(id_=user_id, name=user_info["name"], email=user_info["email"])
        users[user_id] = user
        login_user(user)  # <-- This logs in the user for Flask-Login

        # Save extra info in session for navbar/profile
        session["user"] = {
            "id": user_id,
            "name": user_info["name"],
            "email": user_info["email"],
            "picture": user_info["picture"],
        }

        return redirect(url_for("index"))
    except Exception as e:
        print("[AUTH CALLBACK ERROR]", e)
        return jsonify({"error": "Login failed, check server logs"}), 500


@app.route("/logout")
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("index"))


# -------------------------
# Chatbot Endpoint
# -------------------------
conversation_state = {}
CHAT_SYSTEM_PROMPT = """You are JalanJalan.AI, a friendly travel assistant.
Guide the user step-by-step to create a weekend trip.
Always respond conversationally and provide buttons for budget, travel style, and interests."""

@app.route("/chat", methods=["POST"])
@login_required
def chat():
    try:
        data = request.json
        user_id = current_user.id
        user_message = data.get("message", "").strip()

        if not conversation_state.get(user_id):
            conversation_state[user_id] = {
                "history": [],
                "stage": "idle",
                "prefs": {},
                "pois": []
            }

        state = conversation_state[user_id]
        state["history"].append({"role": "user", "content": user_message})

        # Stage 1: Start trip planning
        if state["stage"] == "idle" and "create" in user_message.lower() and "trip" in user_message.lower():
            state["stage"] = "ask_budget"
            reply = """
            Great! Let's plan your weekend trip 🗺️<br>
            <b>Select your budget:</b><br>
            <button class='preference-btn' data-type='budget' data-value='low'>Low</button>
            <button class='preference-btn' data-type='budget' data-value='medium'>Medium</button>
            <button class='preference-btn' data-type='budget' data-value='high'>High</button>
            """
            return jsonify({"reply": reply})

        # Parse button data (budget, style, interests)
        try:
            pref_data = json.loads(user_message)
            pref_type = pref_data.get("preference_type")
            value = pref_data.get("value")
        except Exception:
            pref_type = value = None

        if state["stage"] == "ask_budget" and pref_type == "budget":
            state["prefs"]["budget"] = value
            state["stage"] = "ask_travel_style"
            reply = f"""
            Got it! Budget: <b>{value}</b><br>
            Select your travel style:<br>
            <button class='preference-btn' data-type='travel_style' data-value='relaxed'>Relaxed</button>
            <button class='preference-btn' data-type='travel_style' data-value='adventurous'>Adventurous</button>
            <button class='preference-btn' data-type='travel_style' data-value='family-friendly'>Family-friendly</button>
            """
            return jsonify({"reply": reply})

        if state["stage"] == "ask_travel_style" and pref_type == "travel_style":
            state["prefs"]["travel_style"] = value
            state["stage"] = "ask_interests"
            state["prefs"]["interests"] = []
            reply = """
            Great! Now select your interests:<br>
            <button class='preference-btn' data-type='interest' data-value='alam'>Alam</button>
            <button class='preference-btn' data-type='interest' data-value='kuliner'>Kuliner</button>
            <button class='preference-btn' data-type='interest' data-value='sejarah'>Sejarah</button>
            <button class='preference-btn' data-type='interest' data-value='belanja'>Belanja</button>
            <button class='preference-btn' data-type='interest' data-value='santai'>Santai</button><br>
            <button class='preference-btn' data-type='confirm_interests' data-value='done'>Done</button>
            """
            return jsonify({"reply": reply})

        if state["stage"] == "ask_interests" and pref_type == "interest":
            if value not in state["prefs"]["interests"]:
                state["prefs"]["interests"].append(value)
            return jsonify({"reply": f"Added interest: <b>{value}</b>"})

        if state["stage"] == "ask_interests" and pref_type == "confirm_interests":
            state["stage"] = "suggest_options"
            pois = get_pois(state["prefs"]["budget"], state["prefs"]["interests"], state["prefs"]["travel_style"])
            state["pois"] = pois
            reply = "<b>Here are suggested POIs for your trip:</b><br>"
            for p in pois:
                reply += f"- {p['name']} ({p['category']}): {p['description']}<br>"
            reply += "<br><button class='preference-btn' data-type='generate_itinerary' data-value='yes'>Confirm & Generate Hourly Itinerary</button>"
            return jsonify({"reply": reply, "pois": pois})

        if state["stage"] == "suggest_options" and pref_type == "generate_itinerary":
            prefs = state["prefs"]
            poi_text = "\n".join([f"- {p['name']} ({p['category']})" for p in state["pois"]])
            prompt = f"""
            You are JalanJalan.AI. User preferences: Budget {prefs['budget']}, Travel style {prefs['travel_style']}, Interests {', '.join(prefs['interests'])}.
            Suggested POIs: {poi_text}
            Generate a weekend itinerary, hour-by-hour, JSON array with fields: time, title, description, poi_name, lat, lon
            """
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            try:
                itinerary = json.loads(response.text)
                # Enrich itinerary with images
                for item in itinerary:
                    if item.get("poi_name"):
                        item["photo"] = get_pollinations_image(item["poi_name"], "destination")
                reply = "✅ Hour-by-hour itinerary generated!"
            except Exception:
                itinerary = [{"time": "", "title": "Itinerary", "description": response.text, "poi_name": None}]
                reply = "✅ Itinerary generated, but could not parse as JSON. Showing as text."

            state["stage"] = "completed"
            return jsonify({"reply": reply, "itinerary": itinerary})

        # Default AI Fallback
        model = genai.GenerativeModel("gemini-1.5-flash")
        full_prompt = f"{CHAT_SYSTEM_PROMPT}\n\nConversation history:\n"
        for turn in state["history"]:
            full_prompt += f"{turn['role']}: {turn['content']}\n"
        full_prompt += f"user: {user_message}"
        ai_response = model.generate_content(full_prompt)
        state["history"].append({"role": "assistant", "content": ai_response.text})
        return jsonify({"reply": ai_response.text})

    except Exception as e:
        print(f"[CHAT] error: {e}")
        return jsonify({"reply": "⚠️ Internal server error. Please try again later."}), 500

# -------------------------
# DevTools Stub
# -------------------------
@app.route("/.well-known/appspecific/com.chrome.devtools.json")
def devtools():
    return "", 204

# -------------------------
# Run App
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
