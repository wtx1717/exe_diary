PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  local_id TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL UNIQUE,
  activity_name TEXT NOT NULL,
  sport_type TEXT NOT NULL,
  start_time TEXT NOT NULL,
  start_date TEXT NOT NULL,
  fit_path TEXT NOT NULL UNIQUE,
  fit_sha256 TEXT NOT NULL UNIQUE,
  distance_m REAL,
  duration_s REAL,
  moving_time_s REAL,
  avg_pace_s_per_km REAL,
  avg_hr INTEGER,
  max_hr INTEGER,
  avg_cadence REAL,
  avg_stride_m REAL,
  elevation_gain_m REAL,
  calories INTEGER,
  training_effect REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL,
  point_index INTEGER NOT NULL,
  timestamp TEXT,
  elapsed_s REAL,
  distance_m REAL,
  latitude REAL,
  longitude REAL,
  altitude_m REAL,
  speed_mps REAL,
  pace_s_per_km REAL,
  heart_rate INTEGER,
  cadence_spm REAL,
  stride_m REAL,
  power_w INTEGER,
  temperature_c INTEGER,
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
  UNIQUE(activity_id, point_index)
);

CREATE TABLE IF NOT EXISTS activity_laps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL,
  lap_index INTEGER NOT NULL,
  start_time TEXT,
  elapsed_s REAL,
  moving_time_s REAL,
  distance_m REAL,
  avg_pace_s_per_km REAL,
  avg_hr INTEGER,
  max_hr INTEGER,
  avg_cadence_spm REAL,
  max_cadence_spm REAL,
  avg_stride_m REAL,
  ascent_m REAL,
  descent_m REAL,
  calories INTEGER,
  trigger TEXT,
  intensity TEXT,
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
  UNIQUE(activity_id, lap_index)
);

CREATE TABLE IF NOT EXISTS activity_fit_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL,
  message_index INTEGER NOT NULL,
  message_name TEXT NOT NULL,
  local_index INTEGER NOT NULL,
  fields_json TEXT NOT NULL,
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
  UNIQUE(activity_id, message_index)
);

CREATE TABLE IF NOT EXISTS activity_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL UNIQUE,
  fatigue_level INTEGER,
  soreness_level INTEGER,
  sleep_quality INTEGER,
  mood TEXT,
  rpe INTEGER,
  pain_note TEXT,
  summary TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  status TEXT NOT NULL,
  message TEXT,
  new_fit_count INTEGER NOT NULL DEFAULT 0,
  parsed_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_activities_start_date ON activities(start_date);
CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities(start_time);
CREATE INDEX IF NOT EXISTS idx_activity_notes_activity_id ON activity_notes(activity_id);
CREATE INDEX IF NOT EXISTS idx_activity_records_activity_id ON activity_records(activity_id);
CREATE INDEX IF NOT EXISTS idx_activity_laps_activity_id ON activity_laps(activity_id);
CREATE INDEX IF NOT EXISTS idx_activity_fit_messages_activity_id ON activity_fit_messages(activity_id);
CREATE INDEX IF NOT EXISTS idx_activity_fit_messages_name ON activity_fit_messages(activity_id, message_name);
