{% extends "base.html" %}
{% block titulo %}Radar da Coordenação — AIM.Edu{% endblock %}
{% block conteudo %}

<div class="card">
  <h2>Radar da Coordenação</h2>
  <p style="color:#666; font-size:0.85rem;">Alertas pedagógicos gerados automaticamente pelos módulos do sistema (hoje: Diagnóstico Adaptativo) sempre que um aluno precisa de atenção.</p>

  <div style="display:flex; gap:14px; flex-wrap:wrap; margin-top:14px;">
    <div style="background:#fdecea; border-radius:10px; padding:12px 20px; min-width:110px;">
      <div style="font-size:1.4rem; font-weight:700; color:var(--vermelho);">{{ contagem.alto }}</div>
      <div style="font-size:0.78rem; color:var(--texto-suave);">nível alto</div>
    </div>
    <div style="background:#fff8e1; border-radius:10px; padding:12px 20px; min-width:110px;">
      <div style="font-size:1.4rem; font-weight:700; color:var(--amarelo);">{{ contagem.medio }}</div>
      <div style="font-size:0.78rem; color:var(--texto-suave);">nível médio</div>
    </div>
    <div style="background:#eaf6ec; border-radius:10px; padding:12px 20px; min-width:110px;">
      <div style="font-size:1.4rem; font-weight:700; color:var(--verde);">{{ contagem.baixo }}</div>
      <div style="font-size:0.78rem; color:var(--texto-suave);">nível baixo</div>
    </div>
    <div style="display:flex; align-items:center; font-size:0.85rem; color:var(--texto-suave);">pendentes de análise agora</div>
  </div>

  <form method="get" style="display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; margin-top:20px;">
    <div>
      <label for="turma">Turma</label>
      <select name="turma" id="turma">
        <option value="">Todas</option>
        {% for t in turmas %}
        <option value="{{ t['id'] }}" {% if turma_filtro == t['id'] %}selected{% endif %}>{{ t['nome'] }}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label for="nivel">Nível</label>
      <select name="nivel" id="nivel">
        <option value="">Todos</option>
        <option value="alto" {% if nivel_filtro == 'alto' %}selected{% endif %}>Alto</option>
        <option value="medio" {% if nivel_filtro == 'medio' %}selected{% endif %}>Médio</option>
        <option value="baixo" {% if nivel_filtro == 'baixo' %}selected{% endif %}>Baixo</option>
      </select>
    </div>
    <div>
      <label for="status">Status</label>
      <select name="status" id="status">
        <option value="pendente" {% if status_filtro == 'pendente' %}selected{% endif %}>Pendentes</option>
        <option value="resolvido" {% if status_filtro == 'resolvido' %}selected{% endif %}>Resolvidos</option>
        <option value="todos" {% if status_filtro == 'todos' %}selected{% endif %}>Todos</option>
      </select>
    </div>
    <div>
      <button class="botao" type="submit">Filtrar</button>
    </div>
  </form>
</div>

<div class="card">
  {% if alertas %}
  <table>
    <tr><th>Turma</th><th>Aluno</th><th>Nível</th><th>Motivo</th><th>Data</th><th>Status</th><th></th><th></th></tr>
    {% for a in alertas %}
    <tr>
      <td>{{ a['turma_nome'] }}</td>
      <td>
        {% if a['aluno_id'] %}
        <a href="{{ url_for('radar_coordenacao.aluno', aluno_id=a['aluno_id']) }}">{{ a['aluno_nome'] or '—' }}</a>
        {% else %}
        —
        {% endif %}
      </td>
      <td class="nivel-{{ a['nivel'] }}">{{ a['nivel']|capitalize }}</td>
      <td>{{ a['motivo'] }}</td>
      <td>{{ a['criado_em']|data }}</td>
      <td>{{ 'Resolvido' if a['resolvido'] else 'Pendente' }}</td>
      <td>
        {% if a['diagnostico_id'] %}
        <a href="{{ url_for('coordenador_professores.revisar_diagnostico', diagnostico_id=a['diagnostico_id']) }}">Ver diagnóstico completo</a>
        {% endif %}
      </td>
      <td>
        <form method="post" action="{{ url_for('radar_coordenacao.marcar', alerta_id=a['id']) }}">
          <input type="hidden" name="turma" value="{{ turma_filtro }}">
          <input type="hidden" name="nivel" value="{{ nivel_filtro }}">
          <input type="hidden" name="status" value="{{ status_filtro }}">
          {% if a['resolvido'] %}
