"""Database access for the catalog layer: schema (Этап 2.2) and reference CRUD.

Creates every table described in plans/database_structure.qmd section 2
(catalogs, card workshop, tasks, scenarios/trainings, sessions/scoring and
utility tables) together with indexes and foreign keys. The migration version
2.2.0 is recorded in schema_migration, exactly like the auth layer does for
2.1.0. Direct PostgreSQL access goes through db_connection (Simple Query
protocol); untrusted values are always embedded via quote_literal().
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import db_config
import db_connection
from db_connection import quote_literal as q

SCHEMA_VERSION = '2.2.0'

# -------------------------------------------------------------------- DDL
# Order respects foreign keys: catalogs -> workshop -> tasks ->
# scenarios/trainings -> sessions/scoring -> utility tables.

SCHEMA_STATEMENTS = [
    # --------------------------- 2.1 Справочники и каталоги
    """
    CREATE TABLE IF NOT EXISTS service (
        code text PRIMARY KEY,
        name text NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS classifier_category (
        id   smallint PRIMARY KEY,
        name text NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS classifier_entry (
        id                  text PRIMARY KEY,
        category_id         smallint NOT NULL REFERENCES classifier_category(id),
        group_name          text NOT NULL DEFAULT '',
        statistical_group   text NOT NULL DEFAULT '',
        sign1               text NOT NULL DEFAULT '',
        sign2               text NOT NULL DEFAULT '',
        sign3               text NOT NULL DEFAULT '',
        extra_signs         text NOT NULL DEFAULT '',
        title               text NOT NULL DEFAULT '',
        ekp_type            text NOT NULL DEFAULT '',
        main_service_code   text REFERENCES service(code)
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_classifier_entry_category ON classifier_entry(category_id)',
    """
    CREATE TABLE IF NOT EXISTS classifier_entry_service (
        id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        entry_id       text NOT NULL REFERENCES classifier_entry(id) ON DELETE CASCADE,
        service_code   text NOT NULL REFERENCES service(code) ON DELETE RESTRICT,
        condition_type text NOT NULL DEFAULT 'column',
        condition_text text NOT NULL DEFAULT '',
        value          text NOT NULL DEFAULT '',
        is_main        boolean NOT NULL DEFAULT false,
        UNIQUE (entry_id, service_code, condition_text, value)
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_classifier_entry_service_code ON classifier_entry_service(service_code)',
    """
    CREATE TABLE IF NOT EXISTS geo_address (
        id     text PRIMARY KEY,
        street text NOT NULL DEFAULT '',
        house  text NOT NULL DEFAULT '',
        lat    numeric,
        lon    numeric,
        kind   text NOT NULL DEFAULT 'building',
        point  jsonb
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_geo_address_street_house ON geo_address(street, house)',
    """
    CREATE TABLE IF NOT EXISTS geo_building (
        id     text PRIMARY KEY,
        street text NOT NULL DEFAULT '',
        house  text NOT NULL DEFAULT '',
        lat    numeric,
        lon    numeric,
        point  jsonb
    )
    """,
    # --------------------------- 2.2 Мастерская карточек
    """
    CREATE TABLE IF NOT EXISTS workshop_card (
        id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        number            text UNIQUE,
        status            text NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'approved')),
        title             text NOT NULL DEFAULT '',
        report            text NOT NULL DEFAULT '',
        fields            jsonb NOT NULL DEFAULT '{}',
        class_ids         jsonb NOT NULL DEFAULT '[]',
        services          jsonb NOT NULL DEFAULT '[]',
        main_service      text,
        flags             jsonb NOT NULL DEFAULT '{}',
        provenance        jsonb NOT NULL DEFAULT '{}',
        revision          int NOT NULL DEFAULT 0,
        created_by_id     bigint REFERENCES "user"(id) ON DELETE SET NULL,
        caller_scenario   jsonb,
        opening           text,
        geocoding         jsonb,
        service_selection jsonb,
        created_at        timestamptz NOT NULL DEFAULT now(),
        updated_at        timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_workshop_card_status ON workshop_card(status, updated_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_workshop_card_fields ON workshop_card USING gin(fields)',
    'CREATE INDEX IF NOT EXISTS idx_workshop_card_class_ids ON workshop_card USING gin(class_ids)',
    """
    CREATE TABLE IF NOT EXISTS workshop_card_reference (
        id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        card_id        bigint NOT NULL REFERENCES workshop_card(id) ON DELETE CASCADE,
        version        int NOT NULL DEFAULT 1,
        source_content jsonb,
        answer         jsonb,
        model          text,
        prompt_version text,
        created_at     timestamptz NOT NULL DEFAULT now(),
        edited_at      timestamptz,
        checked_at     timestamptz,
        UNIQUE (card_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workshop_card_version (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        card_id    bigint NOT NULL REFERENCES workshop_card(id) ON DELETE CASCADE,
        snapshot   jsonb,
        review     jsonb,
        action     text NOT NULL DEFAULT '',
        created_at timestamptz NOT NULL DEFAULT now(),
        author_id  bigint REFERENCES "user"(id) ON DELETE SET NULL
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_workshop_card_version_card ON workshop_card_version(card_id, created_at)',
    """
    CREATE TABLE IF NOT EXISTS workshop_card_event (
        id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        card_id bigint NOT NULL REFERENCES workshop_card(id) ON DELETE CASCADE,
        at      timestamptz NOT NULL DEFAULT now(),
        action  text NOT NULL DEFAULT '',
        text    text NOT NULL DEFAULT '',
        payload jsonb
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_workshop_card_event_card ON workshop_card_event(card_id, at)',
    """
    CREATE TABLE IF NOT EXISTS workshop_card_dialogue (
        card_id            bigint PRIMARY KEY REFERENCES workshop_card(id) ON DELETE CASCADE,
        turns              jsonb NOT NULL DEFAULT '[]',
        callback_disclosed boolean NOT NULL DEFAULT false
    )
    """,
    # --------------------------- 2.3 Учебный каталог заданий
    """
    CREATE TABLE IF NOT EXISTS task (
        id             text PRIMARY KEY,
        title          text NOT NULL DEFAULT '',
        status         text NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'approved')),
        workflow       text NOT NULL DEFAULT 'caller'
                       CHECK (workflow IN ('caller', 'dds')),
        level          text,
        format         text NOT NULL DEFAULT 'legacy'
                       CHECK (format IN ('legacy', 'incident-v1')),
        opening        text,
        persona        text,
        fields         jsonb NOT NULL DEFAULT '{}',
        field_labels   jsonb NOT NULL DEFAULT '{}',
        source         text,
        identity_hash  text UNIQUE,
        approved_by_id bigint REFERENCES "user"(id) ON DELETE SET NULL,
        approved_at    timestamptz,
        created_at     timestamptz NOT NULL DEFAULT now(),
        updated_at     timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_dds (
        task_id            text PRIMARY KEY REFERENCES task(id) ON DELETE CASCADE,
        incoming_card      jsonb,
        verification_notes text,
        faults             text,
        service_name       text,
        service_role       text,
        service_knowledge  text,
        actions            jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_incident_source (
        task_id         text PRIMARY KEY REFERENCES task(id) ON DELETE CASCADE,
        content         jsonb,
        reference       jsonb,
        caller_scenario jsonb,
        opening         text
    )
    """,
    # --------------------------- 2.4 Сценарии и тренировки
    """
    CREATE TABLE IF NOT EXISTS scenario (
        id             text PRIMARY KEY,
        title          text NOT NULL DEFAULT '',
        description    text NOT NULL DEFAULT '',
        status         text NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'approved')),
        created_by_id  bigint REFERENCES "user"(id) ON DELETE SET NULL,
        approved_by_id bigint REFERENCES "user"(id) ON DELETE SET NULL,
        approved_at    timestamptz,
        created_at     timestamptz NOT NULL DEFAULT now(),
        updated_at     timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scenario_task (
        scenario_id text NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
        task_id     text NOT NULL REFERENCES task(id) ON DELETE CASCADE,
        difficulty  smallint NOT NULL DEFAULT 3 CHECK (difficulty BETWEEN 1 AND 5),
        PRIMARY KEY (scenario_id, task_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS training (
        id           text PRIMARY KEY,
        title        text NOT NULL DEFAULT '',
        description  text NOT NULL DEFAULT '',
        status       text NOT NULL DEFAULT 'prepared'
                     CHECK (status IN ('prepared', 'active', 'completed')),
        mode         text NOT NULL DEFAULT 'training'
                     CHECK (mode IN ('training', 'testing')),
        seconds      int NOT NULL DEFAULT 0,
        difficulty   text NOT NULL DEFAULT 'easy'
                     CHECK (difficulty IN ('easy', 'medium', 'hard', 'adaptive')),
        teacher_id   bigint REFERENCES "user"(id) ON DELETE SET NULL,
        group_name   text,
        created_at   timestamptz NOT NULL DEFAULT now(),
        started_at   timestamptz,
        completed_at timestamptz,
        updated_at   timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS training_scenario (
        training_id text NOT NULL REFERENCES training(id) ON DELETE CASCADE,
        scenario_id text NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
        PRIMARY KEY (training_id, scenario_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS training_participant (
        training_id  text NOT NULL REFERENCES training(id) ON DELETE CASCADE,
        user_id      bigint NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
        role         text NOT NULL DEFAULT 'operator'
                     CHECK (role IN ('operator', 'dds', 'service')),
        service_code text,
        PRIMARY KEY (training_id, user_id)
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_training_participant_user ON training_participant(user_id)',
    """
    CREATE TABLE IF NOT EXISTS training_card (
        id                 text PRIMARY KEY,
        training_id        text NOT NULL REFERENCES training(id) ON DELETE CASCADE,
        task_id            text NOT NULL REFERENCES task(id) ON DELETE RESTRICT,
        operator_session_id text,
        status             text NOT NULL DEFAULT 'awaiting_call'
                           CHECK (status IN ('awaiting_call', 'operator_work',
                                             'dds_review', 'service_review',
                                             'done', 'stopped')),
        card_snapshot      jsonb,
        services           jsonb,
        submitted_at       timestamptz,
        dds_by_id          bigint REFERENCES "user"(id) ON DELETE SET NULL,
        routed_at          timestamptz
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_training_card_training_status ON training_card(training_id, status)',
    'CREATE INDEX IF NOT EXISTS idx_training_card_operator_session ON training_card(operator_session_id)',
    """
    CREATE TABLE IF NOT EXISTS training_service_action (
        id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        training_card_id text NOT NULL REFERENCES training_card(id) ON DELETE CASCADE,
        service_code     text,
        text             text NOT NULL DEFAULT '',
        at               timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_training_service_action_card ON training_service_action(training_card_id)',
    """
    CREATE TABLE IF NOT EXISTS material (
        id          text PRIMARY KEY,
        title       text NOT NULL DEFAULT '',
        url         text NOT NULL DEFAULT '',
        description text NOT NULL DEFAULT '',
        teacher_id  bigint REFERENCES "user"(id) ON DELETE SET NULL,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    # --------------------------- 2.5 Сессии и оценивание
    """
    CREATE TABLE IF NOT EXISTS "session" (
        id                 text PRIMARY KEY,
        task_id            text NOT NULL REFERENCES task(id) ON DELETE RESTRICT,
        task_snapshot      jsonb,
        reference_hash     text,
        student_id         bigint NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
        status             text NOT NULL DEFAULT 'queued'
                           CHECK (status IN ('queued', 'awaiting_call', 'active',
                                             'submitted', 'pending_teacher',
                                             'reviewed')),
        effective_level    text,
        card               jsonb,
        training_meta      jsonb,
        callback_disclosed boolean NOT NULL DEFAULT false,
        connection         text,
        call_attempts      int NOT NULL DEFAULT 0,
        next_channel       text,
        timed_out          boolean NOT NULL DEFAULT false,
        forced_finish      jsonb,
        teacher_note       text,
        teacher_note_by_id bigint REFERENCES "user"(id) ON DELETE SET NULL,
        teacher_note_at    timestamptz,
        created_at         timestamptz NOT NULL DEFAULT now(),
        activated_at       timestamptz,
        submitted_at       timestamptz,
        updated_at         timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_session_student_status ON "session"(student_id, status)',
    'CREATE INDEX IF NOT EXISTS idx_session_task ON "session"(task_id)',
    'CREATE INDEX IF NOT EXISTS idx_session_created ON "session"(created_at DESC)',
    """
    CREATE TABLE IF NOT EXISTS session_turn (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        session_id text NOT NULL REFERENCES "session"(id) ON DELETE CASCADE,
        turn_no    int NOT NULL DEFAULT 1,
        role       text NOT NULL DEFAULT 'caller'
                   CHECK (role IN ('caller', 'dispatcher', 'system', 'service')),
        text       text NOT NULL DEFAULT '',
        source     text NOT NULL DEFAULT 'text' CHECK (source IN ('text', 'voice')),
        event      text,
        delivered  boolean NOT NULL DEFAULT false,
        at         timestamptz NOT NULL DEFAULT now(),
        UNIQUE (session_id, turn_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_hint (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        session_id text NOT NULL REFERENCES "session"(id) ON DELETE CASCADE,
        text       text NOT NULL DEFAULT '',
        at         timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_card_edit (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        session_id text NOT NULL REFERENCES "session"(id) ON DELETE CASCADE,
        field      text NOT NULL DEFAULT '',
        before     text,
        after      text,
        at         timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_reveal (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        session_id text NOT NULL REFERENCES "session"(id) ON DELETE CASCADE,
        field      text NOT NULL DEFAULT '',
        label      text NOT NULL DEFAULT '',
        value      text,
        number     int,
        at         timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS machine_assessment (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        session_id text NOT NULL REFERENCES "session"(id) ON DELETE CASCADE,
        percent    int,
        compared   jsonb,
        method     text,
        fields     jsonb,
        at         timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_assessment (
        id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        session_id     text NOT NULL REFERENCES "session"(id) ON DELETE CASCADE,
        summary        text,
        percent        int,
        reference_hash text,
        status         text NOT NULL DEFAULT '',
        created_at     timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_ai_assessment_session ON ai_assessment(session_id)',
    """
    CREATE TABLE IF NOT EXISTS ai_assessment_field (
        id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        assessment_id    bigint NOT NULL REFERENCES ai_assessment(id) ON DELETE CASCADE,
        field            text NOT NULL DEFAULT '',
        verdict          text NOT NULL DEFAULT 'unavailable'
                         CHECK (verdict IN ('correct', 'partial', 'incorrect',
                                            'missing', 'unavailable')),
        comment          text,
        clarification    text,
        citation_warning text,
        evidence         jsonb
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_ai_assessment_field_assessment ON ai_assessment_field(assessment_id)',
    """
    CREATE TABLE IF NOT EXISTS teacher_decision (
        id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        session_id  text NOT NULL REFERENCES "session"(id) ON DELETE CASCADE,
        teacher_id  bigint REFERENCES "user"(id) ON DELETE SET NULL,
        grade       smallint CHECK (grade BETWEEN 2 AND 5),
        percent     int,
        conclusion  text,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_teacher_decision_session ON teacher_decision(session_id)',
    'CREATE INDEX IF NOT EXISTS idx_teacher_decision_teacher ON teacher_decision(teacher_id)',
    """
    CREATE TABLE IF NOT EXISTS teacher_decision_field (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        decision_id bigint NOT NULL REFERENCES teacher_decision(id) ON DELETE CASCADE,
        field      text NOT NULL DEFAULT '',
        decision   text NOT NULL DEFAULT 'agree'
                   CHECK (decision IN ('agree', 'reject', 'edit')),
        comment    text
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_teacher_decision_field_decision ON teacher_decision_field(decision_id)',
    # --------------------------- 2.6 Служебные и аналитические
    """
    CREATE TABLE IF NOT EXISTS ai_generation_log (
        id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        model          text,
        prompt_version text,
        operation      text,
        request        jsonb,
        response       jsonb,
        duration_ms    int,
        error          text,
        at             timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS insight_report (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        group_name text,
        period     text,
        report     jsonb,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
]

# Column lists shared by reference SELECTs (order matches the row mapping).
_SERVICE_COLUMNS = ('code', 'name')
_CATEGORY_COLUMNS = ('id', 'name')
_ENTRY_COLUMNS = ('id', 'category_id', 'group_name', 'statistical_group',
                  'sign1', 'sign2', 'sign3', 'extra_signs', 'title',
                  'ekp_type', 'main_service_code')
_ENTRY_SERVICE_COLUMNS = ('id', 'entry_id', 'service_code', 'condition_type',
                          'condition_text', 'value', 'is_main')
_GEO_ADDRESS_COLUMNS = ('id', 'street', 'house', 'lat', 'lon', 'kind', 'point')
_GEO_BUILDING_COLUMNS = ('id', 'street', 'house', 'lat', 'lon', 'point')


class CatalogRepository:
    """CRUD over reference tables plus the full-schema initializer."""

    def __init__(self, config: Optional[Dict[str, object]] = None):
        self._config = config or db_config.get_db_config()

    def _connect(self) -> db_connection.PostgresConnection:
        return db_connection.connect_from_config(self._config)

    # ----------------------------------------------------------------- schema

    def ensure_schema(self) -> None:
        """Create missing tables/indexes and record version 2.2.0."""
        with self._connect() as connection:
            with connection.transaction():
                for statement in SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute(
                    'INSERT INTO schema_migration(version) VALUES (' + q(SCHEMA_VERSION)
                    + ') ON CONFLICT (version) DO NOTHING')

    def migration_version(self) -> Optional[str]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT version FROM schema_migration WHERE version = ' + q(SCHEMA_VERSION))
        return row[0] if row else None

    @staticmethod
    def _as_bool(value) -> Optional[bool]:
        if value is None:
            return None
        return str(value).strip().lower() in ('t', 'true', '1')

    @staticmethod
    def _json(value):
        """Return a parsed JSON value (PostgreSQL sends jsonb as text)."""
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value))
        except (ValueError, TypeError):
            return str(value)

    # ---------------------------------------------------------------- services

    def list_services(self) -> List[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join(_SERVICE_COLUMNS) + ' FROM service ORDER BY code')
        return [dict(zip(_SERVICE_COLUMNS, row)) for row in rows]

    def count_services(self) -> int:
        return self._count('service')

    def get_service(self, code: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT ' + ', '.join(_SERVICE_COLUMNS) + ' FROM service WHERE code = ' + q(code))
        return dict(zip(_SERVICE_COLUMNS, row)) if row else None

    def create_service(self, code: str, name: str) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                'INSERT INTO service(code, name) VALUES (' + q(code) + ', ' + q(name)
                + ') RETURNING ' + ', '.join(_SERVICE_COLUMNS))
        return dict(zip(_SERVICE_COLUMNS, rows[0]))

    def update_service(self, code: str, name: str) -> Optional[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'UPDATE service SET name = ' + q(name) + ' WHERE code = ' + q(code)
                + ' RETURNING ' + ', '.join(_SERVICE_COLUMNS))
        return dict(zip(_SERVICE_COLUMNS, rows[0])) if rows else None

    def delete_service(self, code: str) -> bool:
        with self._connect() as connection:
            connection.execute('DELETE FROM service WHERE code = ' + q(code))
            return connection.rowcount > 0

    # -------------------------------------------------------------- categories

    def list_categories(self) -> List[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join(_CATEGORY_COLUMNS)
                + ' FROM classifier_category ORDER BY id')
        return [dict(zip(_CATEGORY_COLUMNS, row)) for row in rows]

    def count_categories(self) -> int:
        return self._count('classifier_category')

    def get_category(self, category_id: int) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT ' + ', '.join(_CATEGORY_COLUMNS)
                + ' FROM classifier_category WHERE id = ' + q(int(category_id)))
        return dict(zip(_CATEGORY_COLUMNS, row)) if row else None

    def create_category(self, category_id: int, name: str) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                'INSERT INTO classifier_category(id, name) VALUES ('
                + q(int(category_id)) + ', ' + q(name) + ') RETURNING '
                + ', '.join(_CATEGORY_COLUMNS))
        return dict(zip(_CATEGORY_COLUMNS, rows[0]))

    def update_category(self, category_id: int, name: str) -> Optional[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'UPDATE classifier_category SET name = ' + q(name)
                + ' WHERE id = ' + q(int(category_id)) + ' RETURNING '
                + ', '.join(_CATEGORY_COLUMNS))
        return dict(zip(_CATEGORY_COLUMNS, rows[0])) if rows else None

    def delete_category(self, category_id: int) -> bool:
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM classifier_category WHERE id = ' + q(int(category_id)))
            return connection.rowcount > 0

    # ------------------------------------------------------------ entry rows

    def list_entries(self, category_id: Optional[int] = None) -> List[dict]:
        where = '' if category_id is None else ' WHERE category_id = ' + q(int(category_id))
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join(_ENTRY_COLUMNS) + ' FROM classifier_entry'
                + where + ' ORDER BY id')
        return [dict(zip(_ENTRY_COLUMNS, row)) for row in rows]

    def count_entries(self) -> int:
        return self._count('classifier_entry')

    def get_entry(self, entry_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT ' + ', '.join(_ENTRY_COLUMNS)
                + ' FROM classifier_entry WHERE id = ' + q(entry_id))
        return dict(zip(_ENTRY_COLUMNS, row)) if row else None

    def create_entry(self, data: dict) -> dict:
        main = 'NULL' if data.get('main_service_code') is None else q(data['main_service_code'])
        with self._connect() as connection:
            rows = connection.execute(
                'INSERT INTO classifier_entry(id, category_id, group_name,'
                ' statistical_group, sign1, sign2, sign3, extra_signs, title,'
                ' ekp_type, main_service_code) VALUES ('
                + q(data['id']) + ', ' + q(int(data['category_id'])) + ', '
                + q(data.get('group_name', '')) + ', ' + q(data.get('statistical_group', '')) + ', '
                + q(data.get('sign1', '')) + ', ' + q(data.get('sign2', '')) + ', '
                + q(data.get('sign3', '')) + ', ' + q(data.get('extra_signs', '')) + ', '
                + q(data.get('title', '')) + ', ' + q(data.get('ekp_type', '')) + ', '
                + main + ') RETURNING ' + ', '.join(_ENTRY_COLUMNS))
        return dict(zip(_ENTRY_COLUMNS, rows[0]))

    def update_entry(self, entry_id: str, data: dict) -> Optional[dict]:
        sets = []
        if 'category_id' in data:
            sets.append('category_id = ' + q(int(data['category_id'])))
        for field in ('group_name', 'statistical_group', 'sign1', 'sign2',
                      'sign3', 'extra_signs', 'title', 'ekp_type'):
            if field in data:
                sets.append(field + ' = ' + q(data[field]))
        if 'main_service_code' in data:
            sets.append('main_service_code = '
                        + ('NULL' if data['main_service_code'] is None
                           else q(data['main_service_code'])))
        if not sets:
            return self.get_entry(entry_id)
        with self._connect() as connection:
            rows = connection.execute(
                'UPDATE classifier_entry SET ' + ', '.join(sets)
                + ' WHERE id = ' + q(entry_id) + ' RETURNING '
                + ', '.join(_ENTRY_COLUMNS))
        return dict(zip(_ENTRY_COLUMNS, rows[0])) if rows else None

    def delete_entry(self, entry_id: str) -> bool:
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM classifier_entry WHERE id = ' + q(entry_id))
            return connection.rowcount > 0

    # -------------------------------------------------------- entry-services

    def list_entry_services(self, entry_id: Optional[str] = None,
                            service_code: Optional[str] = None) -> List[dict]:
        conditions = []
        if entry_id is not None:
            conditions.append('entry_id = ' + q(entry_id))
        if service_code is not None:
            conditions.append('service_code = ' + q(service_code))
        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join(_ENTRY_SERVICE_COLUMNS)
                + ' FROM classifier_entry_service' + where
                + ' ORDER BY id')
        result = []
        for row in rows:
            item = dict(zip(_ENTRY_SERVICE_COLUMNS, row))
            item['is_main'] = self._as_bool(item['is_main'])
            result.append(item)
        return result

    def count_entry_services(self) -> int:
        return self._count('classifier_entry_service')

    def get_entry_service(self, item_id: int) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT ' + ', '.join(_ENTRY_SERVICE_COLUMNS)
                + ' FROM classifier_entry_service WHERE id = ' + q(int(item_id)))
        if row is None:
            return None
        item = dict(zip(_ENTRY_SERVICE_COLUMNS, row))
        item['is_main'] = self._as_bool(item['is_main'])
        return item

    def create_entry_service(self, data: dict) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                'INSERT INTO classifier_entry_service(entry_id, service_code,'
                ' condition_type, condition_text, value, is_main) VALUES ('
                + q(data['entry_id']) + ', ' + q(data['service_code']) + ', '
                + q(data.get('condition_type', 'column')) + ', '
                + q(data.get('condition_text', '')) + ', ' + q(data.get('value', '')) + ', '
                + ('TRUE' if data.get('is_main') else 'FALSE')
                + ') RETURNING ' + ', '.join(_ENTRY_SERVICE_COLUMNS))
        item = dict(zip(_ENTRY_SERVICE_COLUMNS, rows[0]))
        item['is_main'] = self._as_bool(item['is_main'])
        return item

    def update_entry_service(self, item_id: int, data: dict) -> Optional[dict]:
        sets = []
        for field in ('entry_id', 'service_code', 'condition_type',
                      'condition_text', 'value'):
            if field in data:
                sets.append(field + ' = ' + q(data[field]))
        if 'is_main' in data:
            sets.append('is_main = ' + ('TRUE' if data['is_main'] else 'FALSE'))
        if not sets:
            return self.get_entry_service(item_id)
        with self._connect() as connection:
            rows = connection.execute(
                'UPDATE classifier_entry_service SET ' + ', '.join(sets)
                + ' WHERE id = ' + q(int(item_id)) + ' RETURNING '
                + ', '.join(_ENTRY_SERVICE_COLUMNS))
        if not rows:
            return None
        item = dict(zip(_ENTRY_SERVICE_COLUMNS, rows[0]))
        item['is_main'] = self._as_bool(item['is_main'])
        return item

    def delete_entry_service(self, item_id: int) -> bool:
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM classifier_entry_service WHERE id = ' + q(int(item_id)))
            return connection.rowcount > 0

    # ------------------------------------------------------------- geo-address

    def list_geo_addresses(self, kind: Optional[str] = None, limit: Optional[int] = None) -> List[dict]:
        where = '' if kind is None else ' WHERE kind = ' + q(kind)
        limit_sql = '' if limit is None else ' LIMIT ' + q(int(limit))
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join(_GEO_ADDRESS_COLUMNS) + ' FROM geo_address'
                + where + ' ORDER BY street, house' + limit_sql)
        result = []
        for row in rows:
            item = dict(zip(_GEO_ADDRESS_COLUMNS, row))
            item['point'] = self._json(item['point'])
            result.append(item)
        return result

    def count_geo_addresses(self) -> int:
        return self._count('geo_address')

    def get_geo_address(self, address_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT ' + ', '.join(_GEO_ADDRESS_COLUMNS)
                + ' FROM geo_address WHERE id = ' + q(address_id))
        if row is None:
            return None
        item = dict(zip(_GEO_ADDRESS_COLUMNS, row))
        item['point'] = self._json(item['point'])
        return item

    def create_geo_address(self, data: dict) -> dict:
        point = 'NULL' if data.get('point') is None else q(json.dumps(data['point'], ensure_ascii=False))
        lat = 'NULL' if data.get('lat') is None else q(str(data['lat']))
        lon = 'NULL' if data.get('lon') is None else q(str(data['lon']))
        with self._connect() as connection:
            rows = connection.execute(
                'INSERT INTO geo_address(id, street, house, lat, lon, kind, point) VALUES ('
                + q(data['id']) + ', ' + q(data.get('street', '')) + ', '
                + q(data.get('house', '')) + ', ' + lat + ', ' + lon + ', '
                + q(data.get('kind', 'building')) + ', ' + point + ') RETURNING '
                + ', '.join(_GEO_ADDRESS_COLUMNS))
        item = dict(zip(_GEO_ADDRESS_COLUMNS, rows[0]))
        item['point'] = self._json(item['point'])
        return item

    def update_geo_address(self, address_id: str, data: dict) -> Optional[dict]:
        sets = []
        for field in ('street', 'house', 'kind'):
            if field in data:
                sets.append(field + ' = ' + q(data[field]))
        if 'lat' in data:
            sets.append('lat = ' + ('NULL' if data['lat'] is None else q(str(data['lat']))))
        if 'lon' in data:
            sets.append('lon = ' + ('NULL' if data['lon'] is None else q(str(data['lon']))))
        if 'point' in data:
            sets.append('point = '
                        + ('NULL' if data['point'] is None
                           else q(json.dumps(data['point'], ensure_ascii=False))))
        if not sets:
            return self.get_geo_address(address_id)
        with self._connect() as connection:
            rows = connection.execute(
                'UPDATE geo_address SET ' + ', '.join(sets)
                + ' WHERE id = ' + q(address_id) + ' RETURNING '
                + ', '.join(_GEO_ADDRESS_COLUMNS))
        if not rows:
            return None
        item = dict(zip(_GEO_ADDRESS_COLUMNS, rows[0]))
        item['point'] = self._json(item['point'])
        return item

    def delete_geo_address(self, address_id: str) -> bool:
        with self._connect() as connection:
            connection.execute('DELETE FROM geo_address WHERE id = ' + q(address_id))
            return connection.rowcount > 0

    # ------------------------------------------------------------ geo-building

    def list_geo_buildings(self, limit: Optional[int] = None) -> List[dict]:
        limit_sql = '' if limit is None else ' LIMIT ' + q(int(limit))
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join(_GEO_BUILDING_COLUMNS)
                + ' FROM geo_building ORDER BY street, house' + limit_sql)
        result = []
        for row in rows:
            item = dict(zip(_GEO_BUILDING_COLUMNS, row))
            item['point'] = self._json(item['point'])
            result.append(item)
        return result

    def count_geo_buildings(self) -> int:
        return self._count('geo_building')

    def delete_geo_building(self, address_id: str) -> bool:
        with self._connect() as connection:
            connection.execute('DELETE FROM geo_building WHERE id = ' + q(address_id))
            return connection.rowcount > 0

    # ------------------------------------------------------------ replace-all

    def replace_classifier(self, services, categories, entries,
                           entry_services, chunk: int = 500) -> dict:
        """Transactionally rebuild the four reference tables from a file import.

        Idempotent: a repeated import produces the same row counts. Services
        and categories are replaced first (they are referenced by entries and
        entry_services), then the entry rows and finally their service links.
        """
        def batches(items):
            for start in range(0, len(items), chunk):
                yield items[start:start + chunk]

        def insert_many(table, columns, values_rows):
            col_sql = ', '.join(columns)
            for batch in batches(values_rows):
                values = ', '.join(
                    '(' + ', '.join(q(v) for v in row) + ')' for row in batch)
                if values:
                    connection.execute(
                        'INSERT INTO ' + table + '(' + col_sql + ') VALUES ' + values)

        service_rows = [(code, name) for code, name in services]
        category_rows = [(str(cid), name) for cid, name in categories]
        entry_rows = [
            (row['id'], str(row['category_id']),
             row.get('group_name', ''), row.get('statistical_group', ''),
             row.get('sign1', ''), row.get('sign2', ''), row.get('sign3', ''),
             row.get('extra_signs', ''), row.get('title', ''),
             row.get('ekp_type', ''),
             row.get('main_service_code') or None)
            for row in entries
        ]
        link_rows = [
            (link['entry_id'], link['service_code'],
             link.get('condition_type', 'column'),
             link.get('condition_text', ''), link.get('value', ''),
             True if link.get('is_main') else False)
            for link in entry_services
        ]
        with self._connect() as connection:
            with connection.transaction():
                connection.execute(
                    'TRUNCATE classifier_entry_service, classifier_entry,'
                    ' classifier_category, service RESTART IDENTITY')
                insert_many('service', ('code', 'name'), service_rows)
                insert_many('classifier_category', ('id', 'name'), category_rows)
                insert_many('classifier_entry',
                            ('id', 'category_id', 'group_name',
                             'statistical_group', 'sign1', 'sign2', 'sign3',
                             'extra_signs', 'title', 'ekp_type',
                             'main_service_code'),
                            entry_rows)
                insert_many('classifier_entry_service',
                            ('entry_id', 'service_code', 'condition_type',
                             'condition_text', 'value', 'is_main'),
                            link_rows)
        return {'services': len(service_rows), 'categories': len(category_rows),
                'entries': len(entry_rows), 'entry_services': len(link_rows)}

    def replace_geo(self, addresses, buildings) -> dict:
        """Transactionally rebuild geo_address/geo_building from a file import."""
        def batches(items, size=500):
            for start in range(0, len(items), size):
                yield items[start:start + size]

        def point_sql(point):
            return 'NULL' if point is None else q(json.dumps(point, ensure_ascii=False))

        def lat_sql(lat):
            return 'NULL' if lat is None else q(str(lat))

        with self._connect() as connection:
            with connection.transaction():
                connection.execute('TRUNCATE geo_address, geo_building')
                for batch in batches(addresses):
                    values = ', '.join(
                        '(' + q(a['id']) + ', ' + q(a.get('street', '')) + ', '
                        + q(a.get('house', '')) + ', ' + lat_sql(a.get('lat'))
                        + ', ' + lat_sql(a.get('lon')) + ', '
                        + q(a.get('kind', 'building')) + ', '
                        + point_sql(a.get('point')) + ')'
                        for a in batch)
                    if values:
                        connection.execute(
                            'INSERT INTO geo_address(id, street, house, lat, lon, kind, point)'
                            ' VALUES ' + values)
                for batch in batches(buildings):
                    values = ', '.join(
                        '(' + q(b['id']) + ', ' + q(b.get('street', '')) + ', '
                        + q(b.get('house', '')) + ', ' + lat_sql(b.get('lat'))
                        + ', ' + lat_sql(b.get('lon')) + ', '
                        + point_sql(b.get('point')) + ')'
                        for b in batch)
                    if values:
                        connection.execute(
                            'INSERT INTO geo_building(id, street, house, lat, lon, point)'
                            ' VALUES ' + values)
        return {'addresses': len(addresses), 'buildings': len(buildings)}

    # ---------------------------------------------------------------- helpers

    def _count(self, table: str) -> int:
        with self._connect() as connection:
            row = connection.fetchone('SELECT count(*) FROM ' + table)
        return int(row[0]) if row else 0

    def counts(self) -> dict:
        """Row counts used by --check/--self-test of init_catalog."""
        return {
            'services': self.count_services(),
            'categories': self.count_categories(),
            'entries': self.count_entries(),
            'entry_services': self.count_entry_services(),
            'geo_addresses': self.count_geo_addresses(),
            'geo_buildings': self.count_geo_buildings(),
        }