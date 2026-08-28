"""Real temporary SQLite stores mirroring the verified Dayflow schema.

The live Dayflow store keeps its timeline in a WAL-mode SQLite database
whose nullable unix-second timestamp columns, soft-delete flag,
date-keyed goal table, and date-keyed category-selection table are the
facts this daemon's queries depend on. Every store built here is a real
database file in a real temporary directory, created with the standard
library only, so tests exercise actual SQLite behavior (read-only
opens, WAL concurrency, NULL handling) instead of imitations of it.

Persona builders insert representative rows for each behavioral rule
the daemon must honor. No personal data is committed: the schema shape
and representative category values are locked, real rows never leave
the machine.
"""

import contextlib
import itertools
import os
import sqlite3
import tempfile

DATABASE_FILENAME = "chunks.sqlite"

# Column declarations mirroring the live tables exactly, so a fixture
# store is shape-compatible with the real store from the first statement.
CARD_COLUMN_SPECS = (
    ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    ("batch_id", "INTEGER"),
    ("start", "TEXT NOT NULL"),
    ("end", "TEXT NOT NULL"),
    ("start_ts", "INTEGER"),
    ("end_ts", "INTEGER"),
    ("day", "DATE NOT NULL"),
    ("title", "TEXT NOT NULL"),
    ("summary", "TEXT"),
    ("category", "TEXT NOT NULL"),
    ("subcategory", "TEXT"),
    ("detailed_summary", "TEXT"),
    ("metadata", "TEXT"),
    ("video_summary_url", "TEXT"),
    ("created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ("is_deleted", "INTEGER NOT NULL DEFAULT 0"),
)
GOAL_COLUMN_SPECS = (
    ("day", "TEXT NOT NULL PRIMARY KEY"),
    ("focus_target_minutes", "INTEGER NOT NULL"),
    ("distraction_limit_minutes", "INTEGER NOT NULL"),
    ("is_skipped", "INTEGER NOT NULL DEFAULT 0"),
    ("created_at", "INTEGER NOT NULL"),
    ("updated_at", "INTEGER NOT NULL"),
)
CATEGORY_COLUMN_SPECS = (
    ("day", "TEXT NOT NULL"),
    ("kind", "TEXT NOT NULL CHECK(kind IN ('focus', 'distraction'))"),
    ("category_id", "TEXT NOT NULL"),
    ("category_name", "TEXT NOT NULL"),
    ("category_color_hex", "TEXT NOT NULL"),
    ("sort_order", "INTEGER NOT NULL"),
)

# Table-level constraints the live schema declares besides its columns,
# each with the columns it names so a drifted subset that lost one of
# them still builds a table instead of a broken statement.
CATEGORY_TABLE_CONSTRAINTS = (
    ("PRIMARY KEY (day, kind, category_id)",
     ("day", "kind", "category_id")),
)


def minutes_ago(now_epoch, minutes):
    """Epoch `minutes` before now, in the store's integer-second units."""
    return now_epoch - minutes * 60


def _create_table_sql(table, specs, columns, table_constraints=()):
    """CREATE TABLE statement over the default column set, or the subset
    named in `columns` when simulating a drifted schema.

    A table-level constraint joins the statement only when every column
    it names survived the subset, because a drifted table that lost a
    keyed column cannot still declare a key over it.
    """
    wanted = set(columns) if columns is not None else None

    def kept(name):
        return wanted is None or name in wanted

    declarations = [
        "{} {}".format(name, decl)
        for name, decl in specs
        if kept(name)
    ]
    constraints = [
        sql for sql, requires in table_constraints
        if all(kept(column) for column in requires)
    ]
    return "CREATE TABLE {} ({})".format(
        table, ", ".join(declarations + constraints))


class FixtureStore:
    """A writable builder connection plus the on-disk path readers attach to."""

    def __init__(self, path, connection):
        self.path = path
        self.conn = connection
        self._category_seq = itertools.count()

    def journal_mode(self):
        return self.conn.execute("PRAGMA journal_mode").fetchone()[0]

    def add_card(self, *, title="Untitled card", summary=None, category="Work",
                 start_ts=None, end_ts=None, metadata=None, day="", is_deleted=0):
        """Insert one timeline card; NULL-friendly defaults mirror live rows."""
        self.conn.execute(
            "INSERT INTO timeline_cards"
            " (start, end, start_ts, end_ts, day, title, summary, category,"
            " metadata, is_deleted)"
            " VALUES ('', '', ?, ?, ?, ?, ?, ?, ?, ?)",
            (start_ts, end_ts, day, title, summary, category, metadata, is_deleted),
        )
        self.conn.commit()
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def set_goal(self, *, day, focus_target_minutes=240, distraction_limit_minutes=60,
                 is_skipped=0):
        """Insert one day_goals row keyed by its local date string."""
        self.conn.execute(
            "INSERT INTO day_goals"
            " (day, focus_target_minutes, distraction_limit_minutes, is_skipped,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 0, 0)",
            (day, focus_target_minutes, distraction_limit_minutes, is_skipped),
        )
        self.conn.commit()

    def add_goal_category(self, *, day, category_name, kind="distraction",
                          category_id=None, category_color_hex="#808080",
                          sort_order=0):
        """Insert one day_goal_categories row as the live app writes it.

        Category ids default to a unique value per store because the
        live table keys rows by (day, kind, category_id); two rows may
        carry the same name, and the daemon never reads the id.
        """
        if category_id is None:
            category_id = "fixture-category-{}".format(
                next(self._category_seq))
        self.conn.execute(
            "INSERT INTO day_goal_categories"
            " (day, kind, category_id, category_name, category_color_hex,"
            " sort_order)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (day, kind, category_id, category_name, category_color_hex,
             sort_order),
        )
        self.conn.commit()

    def goal_category_names(self, day, kind="distraction"):
        """Raw category names one local day keeps for one kind, in store order."""
        rows = self.conn.execute(
            "SELECT category_name FROM day_goal_categories"
            " WHERE day = ? AND kind = ? ORDER BY sort_order",
            (day, kind),
        ).fetchall()
        return [row[0] for row in rows]


@contextlib.contextmanager
def fixture_store(card_columns=None, goal_columns=None, category_columns=None,
                  with_cards=True, with_goals=True, with_goal_categories=True):
    """Yield a FixtureStore over a real WAL-mode SQLite file in a temp dir.

    Passing a subset of column names, or with_cards/with_goals/
    with_goal_categories=False, builds a drifted schema so
    schema-mismatch behavior is exercised against real SQLite, not a
    stub of it.
    """
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, DATABASE_FILENAME)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            if with_cards:
                connection.execute(
                    _create_table_sql("timeline_cards", CARD_COLUMN_SPECS, card_columns))
            if with_goals:
                connection.execute(
                    _create_table_sql("day_goals", GOAL_COLUMN_SPECS, goal_columns))
            if with_goal_categories:
                connection.execute(
                    _create_table_sql("day_goal_categories", CATEGORY_COLUMN_SPECS,
                                      category_columns, CATEGORY_TABLE_CONSTRAINTS))
            connection.commit()
            yield FixtureStore(path, connection)
        finally:
            connection.close()


# --- Personas: one builder per behavioral rule the daemon must honor ------
# Each persona only inserts rows; the caller owns the clock (now_epoch) and
# the day keys so every test stays deterministic.


def persona_fresh(store, now_epoch, category="Distraction"):
    """Recent activity: the newest card is minutes old, inside every window."""
    store.add_card(title="Fresh distraction", summary="watched videos",
                   category=category,
                   start_ts=minutes_ago(now_epoch, 30),
                   end_ts=minutes_ago(now_epoch, 2))
    store.add_card(title="Recent work", category="Work",
                   start_ts=minutes_ago(now_epoch, 50),
                   end_ts=minutes_ago(now_epoch, 30))


def persona_stale(store, now_epoch):
    """Nothing newer than the freshness bound; newest is inside the lookback."""
    store.add_card(title="Stale work", category="Work",
                   start_ts=minutes_ago(now_epoch, 70),
                   end_ts=minutes_ago(now_epoch, 40))


def persona_empty(store):
    """A store with the full schema and zero rows."""


def persona_deleted_and_null(store, now_epoch):
    """Soft-deleted and NULL-timestamp rows around one healthy active card."""
    store.add_card(title="Deleted distraction", category="Distraction",
                   start_ts=minutes_ago(now_epoch, 20),
                   end_ts=minutes_ago(now_epoch, 5), is_deleted=1)
    store.add_card(title="Open-ended card", category="Work",
                   start_ts=minutes_ago(now_epoch, 10), end_ts=None)
    store.add_card(title="Unknown start", category="Work", summary=None,
                   metadata=None, start_ts=None,
                   end_ts=minutes_ago(now_epoch, 3))
    store.add_card(title="Healthy card", category="Work",
                   start_ts=minutes_ago(now_epoch, 20),
                   end_ts=minutes_ago(now_epoch, 6))


def persona_category_variants(store, now_epoch):
    """Raw category spellings exactly as the live store keeps them."""
    variants = ("Distraction", "  distraction  ", "DISTRACTION", "Deep Work")
    for offset, category in enumerate(variants):
        store.add_card(title="Variant {}".format(offset), category=category,
                       start_ts=minutes_ago(now_epoch, 20),
                       end_ts=minutes_ago(now_epoch, 1 + offset))


def persona_goal_missing(store):
    """A day with no goal row at all."""


def persona_goal_active(store, day, focus_target_minutes=240,
                        distraction_limit_minutes=60):
    """A plain engaged day: a goal row that is neither skipped nor zero."""
    store.set_goal(day=day, focus_target_minutes=focus_target_minutes,
                   distraction_limit_minutes=distraction_limit_minutes)


def persona_goal_zero_limit(store, day):
    """A day whose distraction limit is switched off by being zero."""
    store.set_goal(day=day, distraction_limit_minutes=0)


def persona_goal_skipped(store, day):
    """A day the owner chose not to track."""
    store.set_goal(day=day, is_skipped=1)


def persona_goal_single_category(store, day, category_name="Distraction"):
    """A tracked day with exactly one distraction category selected."""
    store.set_goal(day=day)
    store.add_goal_category(day=day, category_name=category_name)


def persona_goal_multi_category(store, day, category_names=("YouTube",
                                                            "News",
                                                            "Games")):
    """A tracked day with several distraction categories selected.

    Rows carry their selection order, the way the app writes them.
    """
    store.set_goal(day=day)
    for sort_order, name in enumerate(category_names):
        store.add_goal_category(day=day, category_name=name,
                                sort_order=sort_order)


def persona_goal_no_categories(store, day):
    """A tracked day with nothing selected: the empty-set fallback case.

    No sentinel row stands in for "no choice"; the absent selection is
    itself the signal.
    """
    store.set_goal(day=day)


def persona_goal_focus_only(store, day, category_names=("Deep Work",
                                                        "Admin")):
    """A tracked day whose only selections are focus kind, never distraction."""
    store.set_goal(day=day)
    for sort_order, name in enumerate(category_names):
        store.add_goal_category(day=day, kind="focus", category_name=name,
                                sort_order=sort_order)


def persona_goal_category_variants(store, day):
    """Raw category-name spellings exactly as the live store keeps them.

    Includes one name that strips to empty, so the drop-empty part of
    producer-side normalization stays pinned by a real row.
    """
    store.set_goal(day=day)
    variants = ("YouTube", "  youtube  ", "YOUTUBE", "  News  ", "   ")
    for sort_order, name in enumerate(variants):
        store.add_goal_category(day=day, category_name=name,
                                sort_order=sort_order)


def persona_midnight_rollover(store, *, yesterday_key, today_key,
                              late_yesterday_end, early_today_end,
                              limit_minutes=100):
    """Goal rows for two local days plus distraction spans crossing midnight.

    Rows are keyed by their own local day string, never by hour
    arithmetic on timestamps, so rollover logic must compare day keys.
    """
    store.set_goal(day=yesterday_key, distraction_limit_minutes=limit_minutes)
    store.set_goal(day=today_key, distraction_limit_minutes=limit_minutes)
    store.add_card(title="Late yesterday", category="Distraction", day=yesterday_key,
                   start_ts=late_yesterday_end - 30 * 60, end_ts=late_yesterday_end)
    store.add_card(title="Early today", category="Distraction", day=today_key,
                   start_ts=early_today_end - 20 * 60, end_ts=early_today_end)
