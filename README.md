# JalanJalan.AI

An AI-powered travel planner that generates personalised day-by-day itineraries through a chatbot interface, complete with images, accommodation suggestions, and flight search.

## Project Structure

```
jalanjalan_ai/
├── backend/
│   ├── app.py            # Flask app — all routes and API logic
│   ├── database.py       # PostgreSQL helper functions
│   ├── init_db.py        # Creates tables and seeds initial POI data
│   ├── prompts.py        # Gemini AI system prompt
│   ├── requirements.txt  # Python dependencies
│   ├── .env              # Your local secrets (not committed)
│   ├── .env.example      # Template — copy this to .env
│   └── sql/              # Reference SQL scripts
├── frontend/
│   ├── templates/        # HTML pages served by Flask
│   └── static/           # CSS, JS, and image assets
├── venv/                 # Python virtual environment
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.10+
- PostgreSQL 14+ running locally

## Quick Start

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd jalanjalan_ai
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
# From inside the backend/ folder:
cp .env.example .env
```

Open `backend/.env` and fill in your values:

| Variable | Where to get it |
|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) → Get API key |
| `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` | [Amadeus for Developers](https://developers.amadeus.com/) → Create app |
| `SKYSCANNER_API_KEY` | [RapidAPI — Skyscanner](https://rapidapi.com/skyscanner/api/skyscanner-flight-search) |
| `DB_PASSWORD` | Your local PostgreSQL password |
| `FLASK_SECRET_KEY` | Any long random string (e.g. run `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `ADMIN_PASS` | Choose a secure admin password |

### 5. Create the PostgreSQL database

Connect to PostgreSQL (via `psql` or pgAdmin) and run:

```sql
CREATE DATABASE itinerary_db;
```

### 6. Initialise the database

This creates all tables and seeds sample POI data:

```bash
# From inside the backend/ folder:
python init_db.py
```

### 7. Run the app

```bash
# From inside the backend/ folder:
python app.py
```

Open your browser at **http://localhost:5000**

---

## Login Details

| Role | Username | Password | URL |
|---|---|---|---|
| Admin | `admin` | *(value of `ADMIN_PASS` in `.env`)* | http://localhost:5000/admin |
| Regular user | *(register yourself)* | *(your choice)* | http://localhost:5000/user/signup |

---

## Key Pages

| URL | Description |
|---|---|
| `/` | Home / chatbot |
| `/trip` | Generate a new itinerary |
| `/mytrips` | View saved itineraries |
| `/user/signup` | Register a new account |
| `/user/login` | User login |
| `/admin` | Admin panel (manage POIs) |
| `/health` | Health check endpoint |

---

## Tech Stack

- **Backend** — Python, Flask, psycopg2
- **AI** — Google Gemini 1.5 Flash
- **Database** — PostgreSQL
- **Flight search** — Amadeus API
- **Frontend** — HTML, CSS, Vanilla JS
- **PDF export** — WeasyPrint *(optional — requires system GTK libraries on Windows)*
