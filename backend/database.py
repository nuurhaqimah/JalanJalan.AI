import psycopg2
import os
import json
from dotenv import load_dotenv
from datetime import datetime

CATEGORY_MAP = {
    "food": ["food", "kuliner", "makan", "dining"],
    "nature": ["nature", "alam", "outdoor", "park", "beach"],
    "history": ["history", "sejarah", "heritage", "museum", "temple"],
    "shopping": ["shopping", "belanja", "mall", "market"]
}

# Load env
load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "itinerary_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432))
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def save_itinerary(user_id, title, description, itinerary):
    conn = get_conn()
    cur = conn.cursor()

    if isinstance(user_id, str):  # if "guest" or "demo-user"
        user_id = None

    cur.execute("""
        INSERT INTO itinerary (user_id, title, description, created_at, updated_at, data)
        VALUES (%s, %s, %s, NOW(), NOW(), %s)
        RETURNING id;
    """, (user_id, title, description, json.dumps(itinerary)))

    itinerary_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return itinerary_id


def get_itineraries(user_id):
    """Fetch all itineraries for a user"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, description, created_at, data
        FROM itinerary
        WHERE user_id = %s
        ORDER BY created_at DESC;
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0],
            "title": r[1],
            "description": r[2],
            "created_at": r[3].isoformat(),
            "data": r[4]
        } for r in rows
    ]

def delete_itinerary(itinerary_id, user_id):
    """Delete itinerary by ID (only if owned by user)"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM itinerary
        WHERE id = %s AND user_id = %s
        RETURNING id;
    """, (itinerary_id, user_id))
    deleted = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return deleted is not None

def query_db(query, args=(), one=False):
    """
    Generic helper to run database queries.
    Compatible with the app.py usage pattern.
    """
    conn = get_conn()
    cur = conn.cursor()
    rv = None
    try:
        cur.execute(query, args)
        if cur.description:  # Only fetch if there are results to fetch
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

def normalize_category(user_category: str):
    """Map user input category (English/Bahasa) to canonical DB category."""
    user_category = user_category.lower()
    for canonical, aliases in CATEGORY_MAP.items():
        if user_category in aliases:
            return canonical
    return None

def get_pois(category=None, budget_level=None, travel_style=None, location=None, country=None, limit=5):
    """
    Fetch POIs filtered by category (English/Bahasa normalized) and budget level.
    Returns a list of dicts.
    """
    conn = get_conn()
    cur = conn.cursor()

    query = """
        SELECT id, name, category, description, location, budget_level, travel_style, country
        FROM poi
        WHERE 1=1
    """
    params = []

    if category:
        normalized = normalize_category(category)
        if normalized:
            query += " AND category ILIKE %s"
            params.append(normalized)

    if budget_level:
        query += " AND budget_level = %s"
        params.append(budget_level)

    if travel_style:
        query += " AND travel_style ILIKE %s"
        params.append(travel_style)

    if location:
        query += " AND location ILIKE %s"
        params.append(location)

    if country:
        query += " AND country ILIKE %s"
        params.append(country)

    query += " ORDER BY RANDOM() LIMIT %s"
    params.append(limit)

    try:
        cur.execute(query, params)
        rows = cur.fetchall()
    except Exception as e:
        # If the query fails (e.g., travel_style column missing), retry without travel_style
        try:
            conn.rollback()
        except Exception:
            pass
        if travel_style:
            try:
                query_no_style = "\n        SELECT id, name, category, description, location, budget_level, NULL as travel_style, country\n        FROM poi\n        WHERE 1=1\n    "
                params2 = []
                if category:
                    normalized = normalize_category(category)
                    if normalized:
                        query_no_style += " AND category ILIKE %s"
                        params2.append(normalized)
                if budget_level:
                    query_no_style += " AND budget_level = %s"
                    params2.append(budget_level)
                if location:
                    query_no_style += " AND location ILIKE %s"
                    params2.append(location)
                if country:
                    query_no_style += " AND country ILIKE %s"
                    params2.append(country)
                query_no_style += " ORDER BY RANDOM() LIMIT %s"
                params2.append(limit)
                cur.execute(query_no_style, params2)
                rows = cur.fetchall()
            except Exception:
                rows = []
        else:
            rows = []
    cur.close()
    conn.close()

    return [
        {
            "id": r[0],
            "name": r[1],
            "category": r[2],
            "description": r[3],
            "location": r[4],
            "budget_level": r[5],
            "travel_style": r[6],
            "country": r[7] if len(r) > 7 else None,
        }
        for r in rows
    ]
