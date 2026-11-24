-- Proximity Wars metrics tables (Turso / SQLite).
-- Create them with `python db.py create` (uses .env), or paste this into the Turso dashboard's SQL console.
-- Players are numbered 1 and 2 (Player 1 / Player 2) everywhere in the database.

CREATE TABLE IF NOT EXISTS FeedbackLog (
  id TEXT(16) PRIMARY KEY NOT NULL,
  at TEXT(32),                         -- UTC, e.g. 2026-11-24T14:05:00Z
  text TEXT,                           -- up to 2000 characters
  rating INTEGER,                      -- 1-5, or NULL
  match_id TEXT(16),                   -- the match it was sent after, or NULL
  source TEXT(32)
);

-- One row per match, written when the match ends (finished, someone left, or a bot match was closed).
CREATE TABLE IF NOT EXISTS MatchLog (
  id TEXT(16) PRIMARY KEY NOT NULL,
  room TEXT(8),                        -- match code (online), NULL offline
  mode TEXT(16) NOT NULL,              -- online | offline
  p1_kind TEXT(8) NOT NULL,            -- human | bot
  p2_kind TEXT(8) NOT NULL,
  started_at TEXT(32),                 -- UTC
  ended_at TEXT(32),                   -- UTC
  duration_s REAL,                     -- total duration in seconds
  result TEXT(16) NOT NULL,            -- finished | disconnected | stopped
  winner INTEGER,                      -- 1 or 2, NULL if nobody won
  winner_kind TEXT(8),                 -- human | bot | NULL
  p1_disconnected INTEGER NOT NULL DEFAULT 0,  -- 1 if Player 1 left mid-match
  p2_disconnected INTEGER NOT NULL DEFAULT 0,
  p1_moves INTEGER NOT NULL DEFAULT 0,
  p1_cures INTEGER NOT NULL DEFAULT 0, -- times Player 1 used the cure
  p1_attacks INTEGER NOT NULL DEFAULT 0,
  p1_picks INTEGER NOT NULL DEFAULT 0,
  p1_rejected INTEGER NOT NULL DEFAULT 0,  -- actions the rules refused (not counted in p1_total)
  p1_total INTEGER NOT NULL DEFAULT 0, -- moves + cures + attacks + picks
  p2_moves INTEGER NOT NULL DEFAULT 0,
  p2_cures INTEGER NOT NULL DEFAULT 0,
  p2_attacks INTEGER NOT NULL DEFAULT 0,
  p2_picks INTEGER NOT NULL DEFAULT 0,
  p2_rejected INTEGER NOT NULL DEFAULT 0,
  p2_total INTEGER NOT NULL DEFAULT 0,
  max_hp INTEGER,                      -- the rules the match was played with
  cure_mode TEXT(16),
  cure_ends_turn INTEGER,              -- 0 / 1
  cures_per_turn INTEGER,
  attack_mode TEXT(16),
  attacks TEXT                         -- JSON list of the card names in play
);

CREATE INDEX IF NOT EXISTS MatchLog_ended_at ON MatchLog (ended_at);

-- The action log: one row per action of a match, in order.
CREATE TABLE IF NOT EXISTS MatchAction (
  match_id TEXT(16) NOT NULL REFERENCES MatchLog (id),
  seq INTEGER NOT NULL,                -- 1, 2, 3... order within the match
  t REAL,                              -- seconds since the match started
  player INTEGER NOT NULL,             -- 1 or 2
  actor TEXT(8),                       -- human | bot
  action TEXT(16),                     -- move | heal | attack | pick
  direction INTEGER,                   -- move: -1 or 1
  card INTEGER,                        -- attack: the card's slot in the hand
  pick_index INTEGER,                  -- pick: which offered card was chosen
  card_name TEXT(64),                  -- attack / pick: the card's name
  p1_hp INTEGER,                       -- HP after the action
  p2_hp INTEGER,
  events TEXT,                         -- JSON list of what happened, as shown to the player
  error TEXT,                          -- why the action was refused, NULL if it was accepted
  PRIMARY KEY (match_id, seq)
);
