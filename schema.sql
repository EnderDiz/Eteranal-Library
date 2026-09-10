CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user'
        CHECK (role IN ('admin', 'creator', 'user')),
    avatar_filename TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- =============================================================
-- Контент менеджер тир листа
-- =============================================================

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    description TEXT,
    image_filename TEXT,
    release_status TEXT NOT NULL DEFAULT 'released'
        CHECK (release_status IN ('released', 'upcoming')),
    release_date TEXT,
    content_cycle_label TEXT,
    content_cycle INTEGER NOT NULL DEFAULT 1,
    publication_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (publication_status IN ('draft', 'published', 'archived')),
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_games_name_nocase
    ON games(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_games_status ON games(publication_status);
CREATE INDEX IF NOT EXISTS idx_games_release_status ON games(release_status);

-- Для креатора
CREATE TABLE IF NOT EXISTS creator_game_access (
    user_id INTEGER NOT NULL,
    game_id INTEGER NOT NULL,
    scope TEXT NOT NULL DEFAULT 'tierlists'
        CHECK (scope IN ('tierlists')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, game_id, scope),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

-- Видимые секции в сайд баре
CREATE TABLE IF NOT EXISTS game_sidebar_sections (
    game_id INTEGER NOT NULL,
    section_key TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, section_key),
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

-- Опциональные модули внутри игры.
CREATE TABLE IF NOT EXISTS game_character_modules (
    game_id INTEGER NOT NULL,
    module_key TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, module_key),
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

-- Категории тиров
CREATE TABLE IF NOT EXISTS tier_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (game_id, slug),
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tier_categories_game
    ON tier_categories(game_id, sort_order);

-- Определения для персонажа
CREATE TABLE IF NOT EXISTS game_character_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'select'
        CHECK (field_type IN ('text', 'number', 'select')),
    options_json TEXT NOT NULL DEFAULT '[]',
    filterable INTEGER NOT NULL DEFAULT 0 CHECK (filterable IN (0, 1)),
    sortable INTEGER NOT NULL DEFAULT 0 CHECK (sortable IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (game_id, field_key),
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_character_fields_game
    ON game_character_fields(game_id, sort_order);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    image_filename TEXT NOT NULL,
    avatar_background TEXT NOT NULL DEFAULT 'assr'
        CHECK (avatar_background IN ('assr', 'ssr', 'sr', 'r', 'n')),
    summary TEXT,
    manual_changed_cycle INTEGER,
    publication_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (publication_status IN ('draft', 'published', 'archived')),
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (game_id, slug),
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_characters_game
    ON characters(game_id, publication_status, name);

CREATE TABLE IF NOT EXISTS character_field_values (
    character_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    value TEXT,
    PRIMARY KEY (character_id, field_id),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (field_id) REFERENCES game_character_fields(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS character_ratings (
    character_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    tier_value TEXT NOT NULL
        CHECK (tier_value IN ('SSS', 'SS', 'S', 'A', 'B', 'C', 'D')),
    previous_tier_value TEXT
        CHECK (previous_tier_value IS NULL OR previous_tier_value IN ('SSS', 'SS', 'S', 'A', 'B', 'C', 'D')),
    change_status TEXT
        CHECK (change_status IS NULL OR change_status IN ('promoted', 'demoted')),
    change_cycle INTEGER,
    PRIMARY KEY (character_id, category_id),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES tier_categories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS character_text_content (
    character_id INTEGER PRIMARY KEY,
    profile_text TEXT,
    review_text TEXT,
    other_information_text TEXT,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS character_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    skill_type TEXT,
    name TEXT NOT NULL,
    description TEXT,
    extra_info TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_character_skills_character
    ON character_skills(character_id, sort_order);

CREATE TABLE IF NOT EXISTS character_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_character_stats_character
    ON character_stats(character_id, sort_order);

CREATE TABLE IF NOT EXISTS character_pros_cons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('pro', 'con')),
    text TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_character_pros_cons_character
    ON character_pros_cons(character_id, kind, sort_order);

CREATE TABLE IF NOT EXISTS content_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL
        CHECK (entity_type IN ('game', 'character')),
    entity_id INTEGER NOT NULL,
    game_id INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_by INTEGER,
    reason TEXT NOT NULL DEFAULT 'edit'
        CHECK (reason IN ('edit', 'before_rollback')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_content_revisions_entity
    ON content_revisions(entity_type, entity_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_content_revisions_game
    ON content_revisions(game_id, id DESC);
