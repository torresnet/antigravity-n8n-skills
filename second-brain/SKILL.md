---
name: second-brain
description: Conector cognitivo do Segundo Cérebro pessoal (baseado no Karpathy LLM Wiki, Digital Gardens e GTD). Ativado automaticamente sempre que o usuário mencionar 'segundo cérebro', 'segundo cerebro', 'second brain', 'minhas notas salvas', 'o que eu salvei sobre', 'minhas ações pendentes', ou pedir para catalogar/consultar mídias, vídeos, Reels, áudios, PDFs e anotações.
---

# 🧠 Skill: Segundo Cérebro AI (Cognitive Second Brain)

## 📌 Visão Geral & Gatilhos

Esta habilidade conecta o Gemini / Antigravity diretamente ao **Segundo Cérebro** do usuário, hospedado no Supabase (`Second-Brain`).
Ele incorpora as melhores práticas da comunidade open-source:
- **Karpathy LLM Wiki Pattern:** curadoria automatizada com entidades e conceitos interconectados.
- **Digital Garden (Maggie Appleton):** estágios de maturação (🌱 *Seedling*, 🌿 *Budding*, 🌳 *Evergreen*).
- **GTD (Mindwtr):** extração de próximas ações práticas (*Next Actions*) a partir de vídeos e notas.

### 🎯 Gatilhos de Ativação:
- Menções como: `"segundo cérebro"`, `"no meu segundo cérebro"`, `"second brain"`
- Consultas de recuperação: `"O que eu salvei sobre X?"`, `"Qual era aquele Reels sobre Y?"`, `"Busque no meu acervo..."`
- Consultas de produtividade/GTD: `"Quais ações práticas tenho pendentes no meu segundo cérebro?"`, `"O que eu preciso fazer baseado no que salvei?"`
- Comandos de captura: `"Salve isso no meu segundo cérebro"`, `"Anote no meu cérebro que..."`

---

## 🔑 Configuração de Acesso (Supabase)

- **Supabase Project ID:** `eicmqisneklcvhakvgce`
- **URL da API:** `https://eicmqisneklcvhakvgce.supabase.co`
- **Tabela Principal:** `public.brain_items`
  - Campos: `id`, `title`, `summary`, `source_type`, `source_url`, `stage`, `entities`, `action_items`, `key_takeaways`, `tags`, `raw_content`, `created_at`
- **Tabela Vetorial:** `public.brain_chunks` (campo `embedding` 768 dimensões)
- **Função RPC de Busca Semântica:** `match_brain_chunks(query_embedding, match_threshold, match_count)`

---

## 🔍 Como Executar Consultas

Quando o usuário pedir para consultar o Segundo Cérebro:

1. **Consulta Geral / Temática via SQL**:
   ```sql
   select id, title, summary, source_type, source_url, stage, entities, action_items, key_takeaways, tags, created_at
   from public.brain_items
   where title ilike '%<termo>%' 
      or summary ilike '%<termo>%' 
      or raw_content ilike '%<termo>%'
   order by created_at desc
   limit 5;
   ```

2. **Consulta de Ações Práticas Pendentes (GTD)**:
   ```sql
   select id, title, source_type, action_items, source_url
   from public.brain_items
   where jsonb_array_length(action_items) > 0
   order by created_at desc;
   ```

3. **Formatação da Resposta**:
   - Destaque o tipo de mídia e o estágio do jardim (ex: 📱 Reels · 🌳 Evergreen).
   - Apresente um resumo claro e os pontos-chave.
   - Liste as **Ações Práticas (Next Actions)** recomendadas com checkboxes `[ ]`.
   - Exiba as entidades e conceitos vinculados em formato `[[Wikilink]]`.
   - Forneça o link da fonte para conferência.

---

## 📥 Como Salvar uma Nova Nota Enriquecida

Ao receber uma ordem de salvamento via chat:
```sql
insert into public.brain_items (title, summary, source_type, raw_content, key_takeaways, action_items, entities, stage, tags)
values (
  'Título da Nota',
  'Resumo conciso',
  'note',
  'Conteúdo integral',
  '["Tópico 1", "Tópico 2"]'::jsonb,
  '["Próximo passo prático 1"]'::jsonb,
  '["Entidade/Conceito"]'::jsonb,
  'budding',
  array['produtividade', 'ideias']
);
```
- Responda confirmando: *"✅ Anotado no seu Segundo Cérebro com entidades e próximas ações catalogadas!"*.
