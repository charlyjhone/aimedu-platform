"""
Camada de banco de dados do AIM.Edu.

Hoje: SQLite local (roda sem internet, dentro deste sandbox).
Amanhã: Postgres/Supabase, usando schema_postgres.sql (mesma modelagem).

Todas as consultas usam SQL parametrizado simples de propósito — trocar o
driver de sqlite3 para psycopg (Postgres) exige mudar só este arquivo, não
os módulos que chamam get_db().
"""
import sqlite3
import uuid
from pathlib import Path
from flask import g, current_app

DB_PATH = Path(__file__).resolve().parent.parent / "aimedu.db"

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
    papel text not null check (papel in ('aluno','professor','coordenador','direcao','familia')),
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
"""


def new_id() -> str:
    return uuid.uuid4().hex


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        conn = get_db()
        conn.executescript(SCHEMA_SQLITE)
        conn.commit()
