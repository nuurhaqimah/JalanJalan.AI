import psycopg2
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "itinerary_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432))
}

def init_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Users
        cur.execute("""
        CREATE TABLE IF NOT EXISTS app_user (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS itineraries (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            data JSONB,
            created_at TIMESTAMP DEFAULT NOW()
      )
      """)

        # Itineraries
        cur.execute("""
        CREATE TABLE IF NOT EXISTS itinerary (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES app_user(id) ON DELETE CASCADE,
            title TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            data JSONB
        );
        """)

        # Recreate POIs (drop + create fresh schema)
        cur.execute("DROP TABLE IF EXISTS poi CASCADE;")
        cur.execute("""
        CREATE TABLE poi (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,               -- e.g. nature/food/history/shopping
            description TEXT,
            location TEXT,               -- city/region
            country TEXT,                -- country name
            budget_level TEXT,           -- low/medium/high
            travel_style TEXT,           -- e.g. relaxing/cultural/adventure
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # Seed sample POIs across multiple countries
        sample_pois = [
            # USA
            ("Central Park", "nature", "Large park with trails and lakes.", "New York", "United States", "low", "relaxing"),
            ("The Met Museum", "history", "One of the world's largest art museums.", "New York", "United States", "medium", "cultural"),
            # France
            ("Louvre Museum", "history", "Famous art museum in Paris.", "Paris", "France", "medium", "cultural"),
            ("Montmartre Stroll", "nature", "Hilly neighborhood with scenic views.", "Paris", "France", "low", "relaxing"),
            # Japan
            ("Shibuya Crossing", "shopping", "Iconic scramble crossing and shopping area.", "Tokyo", "Japan", "low", "adventure"),
            ("Meiji Shrine", "history", "Serene Shinto shrine surrounded by forest.", "Tokyo", "Japan", "low", "cultural"),
            # Indonesia
            ("Uluwatu Temple", "history", "Sea temple perched on a cliff.", "Bali", "Indonesia", "low", "cultural"),
            ("Canggu Beach", "nature", "Surf-friendly beach with sunsets.", "Bali", "Indonesia", "low", "adventure"),
        ]
        for poi in sample_pois:
            cur.execute(
                """
                INSERT INTO poi (name, category, description, location, country, budget_level, travel_style)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                poi,
            )
        print("Sample POIs inserted (fresh table).")

        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized successfully!")

    except Exception as e:
        print(f"Error initializing database: {e}")

if __name__ == "__main__":
    init_db()
