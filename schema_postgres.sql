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
    -- nota: este arquivo é só referência (o banco real já tinha sido criado antes
    -- dele existir, e novas colunas/papéis viraram migrations aplicadas direto no
    -- Supabase) — 'psicopedagoga' e 'ativo' já existem na tabela real, só não
    -- estavam registrados aqui; corrigido para não desviar do banco de verdade.
    papel         text not null check (papel in ('aluno','professor','coordenador','direcao','direcao_pedagogica','familia','psicopedagoga')),
    ativo         boolean not null default true,
    -- segmento: só usado quando papel = 'coordenador', reaproveita os valores
    -- de series.etapa para restringir a visão desse coordenador a uma etapa só
    -- (ver escopo_etapa() em app/auth.py). NULL = sem restrição.
    -- direcao_pedagogica: mesmo alcance de 'direcao' (ver PAPEIS_DIRECAO em
    -- app/auth.py), mas sem nenhuma permissão de exclusão definitiva.
    segmento      text,
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
    -- Habilidade específica (ex.: "juros compostos"), mais fina que
    -- 'disciplina' — usada pela Trilha Adaptativa (ver
    -- app/modules/trilha_adaptativa.py). NULL = item não participa da
    -- Trilha, só do Diagnóstico Adaptativo.
    habilidade    text,
    -- Prioridade de atendimento na Trilha, definida à mão pela
    -- coordenação/professor no cadastro da questão — nunca inventada pela
    -- IA a partir de estatística de ENEM (decisão do usuário em
    -- 2026-09-09, mesmo princípio de "nunca inventar dado" do Agente 1).
    prioridade    integer,
    criado_em     timestamptz not null default now()
);

-- Trilha Adaptativa: uma linha por aluno+disciplina+habilidade — sequência
-- de acertos seguidos e status de domínio (ver STREAK_DOMINIO em
-- app/modules/trilha_adaptativa.py). Ao contrário do Diagnóstico
-- Adaptativo, não é "uma tentativa por vez": esta tabela é sempre
-- atualizada no lugar, porque a Trilha roda continuamente.
create table dominio_habilidades (
    id            uuid primary key default gen_random_uuid(),
    aluno_id      uuid not null references alunos(id) on delete cascade,
    disciplina    text not null,
    habilidade    text not null,
    streak_atual  int not null default 0,
    respostas_total int not null default 0,
    acertos_total int not null default 0,
    status        text not null default 'em_andamento' check (status in ('em_andamento','dominada')),
    dominada_em   timestamptz,
    criado_em     timestamptz not null default now(),
    unique (aluno_id, disciplina, habilidade)
);

-- ---------- diagnóstico adaptativo (matemática ENEM é o primeiro módulo) ----------
create table diagnosticos (
    id            uuid primary key default gen_random_uuid(),
    aluno_id      uuid not null references alunos(id) on delete cascade,
    disciplina    text not null,
    iniciado_em   timestamptz not null default now(),
    finalizado_em timestamptz,
    nivel_final   numeric(4,2),
    resumo_ia     text,                   -- texto gerado (hoje por regra, depois por IA real)
    -- Loop de validação do professor: todo diagnóstico finalizado nasce
    -- 'aguardando_revisao' e só conta como oficial para os painéis da
    -- coordenação e o relatório da família depois que o professor da
    -- disciplina (ou coordenação/direção/direção pedagógica, em cobertura)
    -- confere o nível calculado — e pode ajustá-lo — em
    -- coordenador_professores.revisar_diagnostico().
    status        text not null default 'aguardando_revisao' check (status in ('aguardando_revisao', 'revisado')),
    revisado_em   timestamptz,
    revisado_por_usuario_id uuid references usuarios(id)
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
-- Redação: o aluno envia uma FOTO da redação manuscrita (decisão do usuário,
-- migration redacoes_envio_por_foto — não digita mais o texto na tela).
-- 'texto' fica NULL até um provedor de IA com visão (Gemini, decidido para
-- o futuro) transcrever e corrigir; até lá 'status' fica 'aguardando_ia' e
-- nota_c1..c5/feedback_ia ficam NULL. 'arquivo_caminho'/'arquivo_content_type'
-- guardam onde a foto está no Supabase Storage (bucket privado 'redacoes',
-- migration create_bucket_redacoes — mesmo padrão do M7.1, ver app/storage.py).
create table redacoes (
    id            uuid primary key default gen_random_uuid(),
    aluno_id      uuid not null references alunos(id) on delete cascade,
    tema          text,
    texto         text,
    arquivo_caminho text,
    arquivo_content_type text,
    status        text not null default 'aguardando_ia' check (status in ('aguardando_ia','corrigida')),
    nota_c1 int, nota_c2 int, nota_c3 int, nota_c4 int, nota_c5 int,
    -- Nota canônica exibida ao aluno (média ponderada das 5 competências,
    -- decisão do usuário em 2026-09-09 — ver app/orchestrator/corretor.py).
    -- Guardada aqui (em vez de só recalculada na hora de exibir) para não
    -- mudar retroativamente a nota de redações já corrigidas se os pesos
    -- mudarem no futuro.
    nota_ponderada int,
    feedback_ia   text,
    criado_em     timestamptz not null default now()
);

-- Histórico de chamadas do "time invisível" de 12 agentes de IA (ver
-- app/orchestrator/corretor.py e app/agents/agente.py) — uma linha por
-- chamada de agente, mais uma linha 'orquestrador' com o resultado final
-- consolidado. redacao_id fica nullable de propósito: corrigir_redacao
-- pode ser chamada sem id de redação vinculado (ex.: teste manual). Serve
-- de base para uma evolução futura de ciclo de tentativas/reescrita —
-- nenhum código lê esta tabela para decidir nada ainda, ela só registra.
create table tentativas (
    id              uuid primary key default gen_random_uuid(),
    redacao_id      uuid references redacoes(id) on delete cascade,
    agente          text not null,
    numero_tentativa int not null default 1,
    modelo          text,
    entrada         text,
    saida           text,
    nota            int,
    erro            text,
    duracao_ms      int,
    -- Tokens reais consumidos nesta chamada (campo "usage" da API da
    -- Anthropic, capturado em app/agents/agente.py:_chamar_claude). NULL
    -- quando o agente falhou antes de completar a chamada, ou na linha
    -- "orquestrador" (que não chama a API diretamente). Base para validar,
    -- com dado real, a estimativa de custo por redação (ver conversa de
    -- 2026-09-09).
    tokens_entrada  int,
    tokens_saida    int,
    criado_em       timestamptz not null default now()
);

create table alertas_radar (
    id            uuid primary key default gen_random_uuid(),
    turma_id      uuid not null references turmas(id) on delete cascade,
    aluno_id      uuid references alunos(id) on delete cascade,
    nivel         text not null check (nivel in ('baixo','medio','alto')),
    motivo        text not null,
    criado_em     timestamptz not null default now(),
    resolvido     boolean not null default false,
    -- Opcional: só é preenchido quando o alerta nasce de um diagnóstico
    -- adaptativo (ver app/modules/diagnostico.py). Permite ao Radar da
    -- Coordenação linkar direto pro diagnóstico completo (eixo por eixo)
    -- sem precisar abrir a página do aluno primeiro. Alertas de outras
    -- origens (ex: futura Redação) continuam com isso null, normalmente.
    diagnostico_id uuid references diagnosticos(id) on delete set null
);

create table relatorios_familia (
    id            uuid primary key default gen_random_uuid(),
    aluno_id      uuid not null references alunos(id) on delete cascade,
    periodo       text not null,          -- 'semanal' | 'bimestral'
    conteudo      text not null,
    criado_em     timestamptz not null default now()
);

-- M7.1 (Educação Infantil) — registro rápido do professor por foto ou áudio,
-- sem digitação obrigatória (ver app/modules/observacoes_infantil.py). O
-- arquivo em si vive no Supabase Storage (bucket privado
-- 'observacoes-infantil', acessado só pela chave service_role no servidor,
-- nunca por URL pública); esta tabela guarda só o caminho do arquivo e os
-- metadados. 'texto_ia' é reservado para o M7.2 (documentação pedagógica
-- gerada por IA), ainda não implementado.
create table observacoes_infantil (
    id            uuid primary key default gen_random_uuid(),
    aluno_id      uuid not null references alunos(id) on delete cascade,
    turma_id      uuid not null references turmas(id) on delete cascade,
    professor_usuario_id uuid not null references usuarios(id),
    tipo          text not null check (tipo in ('foto','audio')),
    arquivo_caminho text not null,
    arquivo_content_type text not null,
    legenda       text,
    texto_ia      text,
    status        text not null default 'aguardando_ia' check (status in ('aguardando_ia','processado')),
    criado_em     timestamptz not null default now()
);

-- Calendário escolar: eventos que aparecem no painel inicial de todo mundo
-- (widget "Próximos eventos") e na tela cheia app/modules/calendario.py.
-- 'publico' decide quem enxerga cada evento; 'segmento' é opcional e
-- reaproveita os mesmos valores de series.etapa — um evento sem segmento
-- (NULL) aparece pra todo mundo daquele público, independente da etapa.
-- Só coordenação/direção/direção pedagógica cadastram e excluem eventos
-- (ver PAPEIS_DIRECAO em app/auth.py) — todos os outros papéis só leem.
create table eventos_escolares (
    id            uuid primary key default gen_random_uuid(),
    escola_id     uuid not null references escolas(id) on delete cascade,
    titulo        text not null,
    descricao     text,
    data_evento   date not null,
    -- Horário opcional do evento (ex.: "14:30"), formato do <input
    -- type="time"> — pedido do usuário em 2026-09-09 pra reuniões com hora
    -- marcada. Texto simples só pra exibição/ordenação, sem cálculo em
    -- cima (mesma filosofia de dependências mínimas do resto do projeto).
    hora_evento   text,
    publico       text not null default 'todos' check (publico in ('todos','alunos','professores','coordenacao','familias')),
    segmento      text,
    criado_por_usuario_id uuid not null references usuarios(id),
    criado_em     timestamptz not null default now()
);

create index idx_diag_aluno on diagnosticos(aluno_id);
create index idx_resp_diag on diagnostico_respostas(diagnostico_id);
create index idx_alunos_turma on alunos(turma_id);
create index idx_radar_turma on alertas_radar(turma_id);
create index idx_obs_infantil_aluno on observacoes_infantil(aluno_id);
create index idx_obs_infantil_turma on observacoes_infantil(turma_id);
create index idx_eventos_escola_data on eventos_escolares(escola_id, data_evento);
create index idx_tentativas_redacao on tentativas(redacao_id);
create index idx_dominio_aluno on dominio_habilidades(aluno_id);
