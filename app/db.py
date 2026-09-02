"""
Camada de banco de dados do AIM.Edu.

Se a variável de ambiente DATABASE_URL estiver definida, conecta no Postgres
real (Supabase) — o schema já está aplicado lá via migration, então esta
camada não precisa recriá-lo. Sem essa variável, usa SQLite local (modo de
demonstração, sem depender de internet).

Todas as consultas em auth.py, app/modules/*.py e seed_data.py usam SQL
parametrizado com "?" de propósito — a classe _PGConnection abaixo traduz
isso para "%s" na hora de falar com o Postgres, então nenhum desses arquivos
precisa saber qual banco está por trás.
"""
import os
import sqlite3
import uuid
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).resolve().parent.parent / "aimedu.db"
DATABASE_URL = os.environ.get("DATABASE_URL")

SCHEMA_SQLITE = """
create table if not exists escolas (
    id text primary key,
    nome text not null,
    criado_em text not null default (datetime('now'))
);

create table if not exists series (
    id text primary key,
    escola_id text not null references escolas(id),
    nome text not null,
    etapa text not null,
    ordem integer not null
);

create table if not exists turmas (
    id text primary key,
    serie_id text not null references series(id),
    nome text not null,
    ano_letivo integer not null
);

create table if not exists usuarios (
    id text primary key,
    escola_id text not null references escolas(id),
    nome text not null,
    email text not null unique,
    senha_hash text not null,
    papel text not null check (papel in ('aluno','professor','coordenador','direcao','direcao_pedagogica','familia','psicopedagoga')),
    ativo integer not null default 1,
    -- segmento: só usado quando papel = 'coordenador' — reaproveita os mesmos
    -- valores de series.etapa ('infantil'|'fund1'|'fund2'|'medio') pra dizer a
    -- qual etapa esse coordenador está restrito. NULL = sem restrição (usado
    -- também por direção/direção pedagógica/psicopedagoga, que sempre
    -- enxergam tudo independente deste campo — ver escopo_etapa() e
    -- PAPEIS_DIRECAO em app/auth.py).
    segmento text,
    criado_em text not null default (datetime('now'))
);

create table if not exists alunos (
    id text primary key,
    usuario_id text not null unique references usuarios(id),
    turma_id text not null references turmas(id),
    responsavel_usuario_id text references usuarios(id)
);

create table if not exists professores (
    id text primary key,
    usuario_id text not null unique references usuarios(id),
    disciplina text
);

create table if not exists professor_turma (
    professor_id text not null references professores(id),
    turma_id text not null references turmas(id),
    primary key (professor_id, turma_id)
);

create table if not exists itens_banco (
    id text primary key,
    disciplina text not null,
    eixo_bncc text,
    dificuldade integer not null check (dificuldade between 1 and 5),
    enunciado text not null,
    alternativas text not null,
    correta text not null,
    explicacao text,
    criado_em text not null default (datetime('now'))
);

create table if not exists diagnosticos (
    id text primary key,
    aluno_id text not null references alunos(id),
    disciplina text not null,
    iniciado_em text not null default (datetime('now')),
    finalizado_em text,
    nivel_final real,
    resumo_ia text
);

create table if not exists diagnostico_respostas (
    id text primary key,
    diagnostico_id text not null references diagnosticos(id),
    item_id text not null references itens_banco(id),
    ordem integer not null,
    dificuldade_apresentada integer not null,
    resposta_dada text,
    correta integer not null,
    tempo_resposta_s integer,
    criado_em text not null default (datetime('now'))
);

create table if not exists redacoes (
    id text primary key,
    aluno_id text not null references alunos(id),
    tema text,
    texto text not null,
    nota_c1 integer, nota_c2 integer, nota_c3 integer, nota_c4 integer, nota_c5 integer,
    feedback_ia text,
    criado_em text not null default (datetime('now'))
);

create table if not exists alertas_radar (
    id text primary key,
    turma_id text not null references turmas(id),
    aluno_id text references alunos(id),
    nivel text not null check (nivel in ('baixo','medio','alto')),
    motivo text not null,
    criado_em text not null default (datetime('now')),
    resolvido integer not null default 0
);

create table if not exists relatorios_familia (
    id text primary key,
    aluno_id text not null references alunos(id),
    periodo text not null,
    conteudo text not null,
    criado_em text not null default (datetime('now'))
);

create table if not exists bussola_respostas (
    id text primary key,
    aluno_id text not null references alunos(id),
    pontuacoes text not null,
    perfil_top text not null,
    resumo_ia text,
    criado_em text not null default (datetime('now'))
);

create table if not exists inclusao_cadastro (
    id text primary key,
    aluno_id text not null unique references alunos(id),
    categoria text not null,
    diagnostico_formal integer not null default 0,
    adaptacoes text not null,
    apoio_especializado text,
    observacoes text,
    criado_por_usuario_id text not null references usuarios(id),
    criado_em text not null default (datetime('now')),
    atualizado_em text not null default (datetime('now'))
);

create table if not exists pei_metas (
    id text primary key,
    aluno_id text not null references alunos(id),
    descricao text not null,
    area text,
    status text not null check (status in ('nao_iniciada','em_andamento','atingida')) default 'nao_iniciada',
    criado_por_usuario_id text not null references usuarios(id),
    criado_em text not null default (datetime('now')),
    atualizado_em text not null default (datetime('now'))
);

create table if not exists pei_revisoes (
    id text primary key,
    aluno_id text not null references alunos(id),
    texto text not null,
    criado_por_usuario_id text not null references usuarios(id),
    criado_em text not null default (datetime('now'))
);

create table if not exists duvidas_professor (
    id text primary key,
    usuario_id text not null references usuarios(id),
    pergunta text not null,
    resposta_ia text not null,
    criado_em text not null default (datetime('now'))
);
"""


def new_id() -> str:
    return uuid.uuid4().hex


if DATABASE_URL:
    import psycopg2
    import psycopg2.extras

    class _PGCursor:
        """Faz um cursor do psycopg2 responder a .fetchone()/.fetchall() como
        o cursor do sqlite3 — os módulos que chamam db.execute(...) não
        precisam saber a diferença."""

        def __init__(self, cur):
            self._cur = cur

        def fetchone(self):
            return self._cur.fetchone()

        def fetchall(self):
            return self._cur.fetchall()

    class _PGConnection:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, query, params=()):
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(query.replace("?", "%s"), params)
            return _PGCursor(cur)

        def commit(self):
            self._conn.commit()

        def close(self):
            self._conn.close()

    def _connect():
        raw = psycopg2.connect(DATABASE_URL, sslmode="require")
        return _PGConnection(raw)

else:
    def _connect():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(_e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    app.teardown_appcontext(close_db)
    if DATABASE_URL:
        # Schema já existe no Supabase (aplicado via migration) — nada a criar.
        return
    with app.app_context():
        conn = get_db()
        conn.executescript(SCHEMA_SQLITE)
        conn.commit()
