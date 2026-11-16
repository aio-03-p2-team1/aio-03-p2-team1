-- SQLite 품종 기준정보 스키마. Python 초기화 스크립트가 이 파일 전체를 실행한다.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS kinds (
    id INTEGER PRIMARY KEY,
    species TEXT NOT NULL CHECK (species IN ('dog', 'cat', 'other')),
    kind_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    search_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    source TEXT NOT NULL DEFAULT 'animal_api',
    source_updated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS kinds_search_name_idx
    ON kinds (species, search_name);
CREATE INDEX IF NOT EXISTS kinds_name_idx
    ON kinds (species, name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS kind_aliases (
    id INTEGER PRIMARY KEY,
    kind_code TEXT NOT NULL REFERENCES kinds(kind_code) ON UPDATE CASCADE ON DELETE CASCADE,
    alias TEXT NOT NULL,
    search_alias TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'curated',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (kind_code, search_alias)
);

CREATE INDEX IF NOT EXISTS kind_aliases_search_idx
    ON kind_aliases (search_alias);
CREATE INDEX IF NOT EXISTS kind_aliases_code_idx
    ON kind_aliases (kind_code);
