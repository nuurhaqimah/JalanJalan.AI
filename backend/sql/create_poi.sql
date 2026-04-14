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