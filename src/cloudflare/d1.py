create_users_table_sql = """
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL COLLATE NOCASE UNIQUE,
  name TEXT NOT NULL,
  access_service_token_id TEXT UNIQUE,
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
"""
add_access_service_token_id_column_sql = """
ALTER TABLE users ADD COLUMN access_service_token_id TEXT;
"""
create_access_service_token_id_index_sql = """
CREATE UNIQUE INDEX users_access_service_token_id_unique
ON users(access_service_token_id);
"""
create_credentials_table_sql = """
CREATE TABLE credentials (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  liftosaur_api_key TEXT NOT NULL,
  strava_access_token TEXT,
  strava_refresh_token TEXT NOT NULL,
  strava_expires_at INTEGER,
  updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
"""
insert_tome_in_users_sql = """
INSERT INTO users (id, email, name)
VALUES (
  '687a7c8d-b936-48ee-a2cb-8a23dbadcee6',
  'tome.pmg+cloudflare@gmail.com',
  'Tomé Magalhães Gouveia'
)
RETURNING id, email, name;
"""
