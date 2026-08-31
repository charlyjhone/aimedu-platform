-- AIM.Edu — schema único (Postgres / Supabase)
-- Um projeto único: todas as tabelas de todos os módulos vivem neste mesmo banco,
-- interligadas por escola/aluno/turma, para que qualquer módulo possa ler o que
-- os outros produzem (diagnóstico -> radar -> bússola -> relatório família, etc).

create extension if not exists "pgcrypto";

-- ---------- núcleo institucional ----------
create table escolas (
    id            uuid primary key default gen_random_uuid(),
    nome          text not null,
    criado_em     timestamptz not null default now()
);

create table series (
    id            uuid primary key default gen_random_uuid(),
    escola_id     uuid not null references escolas(id) on delete cascade,
    nome          text not null,          -- ex: "1º ano EM"
    etapa         text not null,          -- infantil | fund1 | fund2 | medio
    ordem         int not null
);

create table turmas (
    id            uuid primary key default gen_random_uuid(),
    serie_id      uuid not null references series(id) on delete cascade,
    nome          text not null,          -- ex: "3º EM A"
    ano_letivo    int not null
);

-- ---------- pessoas / papéis (um único cadastro de usuário para todo o sistema) ----------
create table usuarios (
    id            uuid primary key default gen_random_uuid(),
    escola_id     uuid not null references escolas(id) on delete cascade,
    nome          text not null,
    email         text not null unique,
    senha_hash    text not null,
    papel         text not null check (papel in ('aluno','professor','coordenador','direcao','familia')),
    criado_em     timestamptz not null default now()
);

create table alunos (
    id            uuid primary key default gen_random_uuid(),
    usuario_id    uuid not null unique references usuarios(id) on delete cascade,
    turma_id      uuid not null references turmas(id) on delete cascade,
    responsavel_usuario_id uuid references usuarios(id)   -- liga o aluno à família (papel='familia')
);

create table professores (
    id            uuid primary key default gen_random_uuid(),
    usuario_id    uuid not null unique references usuarios(id) on delete cascade,
    disciplina    text
);

create table professor_turma (
    professor_id  uuid not null references professores(id) on delete cascade,
    turma_id      uuid not null references turmas(id) on delete cascade,
    primary key (professor_id, turma_id)
);

-- ---------- banco de itens (compartilhado por todos os módulos de avaliação) ----------
create table itens_banco (
    id            uuid primary key default gen_random_uuid(),
    disciplina    text not null,          -- matematica | linguagens | ...
    eixo_bncc     text,                   -- competência/eixo trabalhado
    dificuldade   int not null check (dificuldade between 1 and 5),
    enunciado     text not null,
    alternativas  jsonb not null,         -- [{"letra":"A","texto":"..."}, ...]
    correta       text not null,
    explicacao    text,
    criado_em     timestamptz not null default now()
);

-- ---------- diagnóstico adaptativo (matemática ENEM é o primeiro módulo) ----------
create table diagnosticos (
    id            uuid primary key default gen_random_uuid(),
    aluno_id      uuid not null references alunos(id) on delete cascade,
    disciplina    text not null,
    iniciado_em   timestamptz not null default now(),
    finalizado_em timestamptz,
    nivel_final   numeric(4,2),
    resumo_ia     text                    -- texto gerado (hoje por regra, depois por IA real)
);

create table diagnostico_respostas (
    id            uuid primary key default gen_random_uuid(),
    diagnostico_id uuid not null references diagnosticos(id) on delete cascade,
    item_id       uuid not null references itens_banco(id),
    ordem         int not null,
    dificuldade_apresentada int not null,
    resposta_dada text,
    correta       boolean not null,
    tempo_resposta_s int,
    criado_em     timestamptz not null default now()
);

-- ---------- módulos futuros já preparados no mesmo banco (ligados por aluno/turma) ----------
create table redacoes (
    id            uuid primary key default gen_random_uuid(),
    aluno_id      uuid not null references alunos(id) on delete cascade,
    tema          text,
    texto         text not null,
    nota_c1 int, nota_c2 int, nota_c3 int, nota_c4 int, nota_c5 int,
    feedback_ia   text,
    criado_em     timestamptz not null default now()
);

create table alertas_radar (
    id            uuid primary key default gen_random_uuid(),
    turma_id      uuid not null references turmas(id) on delete cascade,
    aluno_id      uuid references alunos(id) on delete cascade,
    nivel         text not null check (nivel in ('baixo','medio','alto')),
    motivo        text not null,
    criado_em     timestamptz not null default now(),
    resolvido     boolean not null default false
);

create table relatorios_familia (
    id            uuid primary key default gen_random_uuid(),
    aluno_id      uuid not null references alunos(id) on delete cascade,
    periodo       text not null,          -- 'semanal' | 'bimestral'
    conteudo      text not null,
    criado_em     timestamptz not null default now()
);

create index idx_diag_aluno on diagnosticos(aluno_id);
create index idx_resp_diag on diagnostico_respostas(diagnostico_id);
create index idx_alunos_turma on alunos(turma_id);
create index idx_radar_turma on alertas_radar(turma_id);
