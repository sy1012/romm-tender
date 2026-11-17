-- =============================================================================
-- 046_add_rom_install_extra_content.sql — an install records the extra content
-- downloaded into its game's folder
-- =============================================================================
--
--   * rom_install_extra_content — one row per update or DLC file of a game
--     downloaded into the game's folder (the RomInstall aggregate's
--     extra_content), keyed by the game and RomM's id for the file. `rel_path`
--     is where it lies inside the install's rom_dir, so a folder the home
--     migration moves keeps its rows true; `size_bytes` is RomM's size of the
--     file. The install's repository writes and drops these rows with the
--     rom_installs row; the cascade from roms takes them with a removed game.
--
-- Created empty: no download fetched extra content before this migration.
--
-- Transaction-safe DDL only — the runner (adapters/sqlite_migrations.py) wraps
-- BEGIN/COMMIT and stamps PRAGMA user_version = 46.
-- -----------------------------------------------------------------------------
CREATE TABLE rom_install_extra_content (
    rom_id     INTEGER NOT NULL REFERENCES roms(rom_id) ON DELETE CASCADE,
    file_id    INTEGER NOT NULL,                 -- RomM's id for the file
    rel_path   TEXT    NOT NULL CHECK (rel_path <> ''),
    size_bytes INTEGER NOT NULL,
    PRIMARY KEY (rom_id, file_id)
) STRICT;
