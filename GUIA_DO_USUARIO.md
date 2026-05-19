# GUIA DO USUÁRIO — tv-today

**Site do canal (o que o espectador vê):** https://tv.logline.world  
**Painel de controle:** https://tv.logline.world/admin  

---

## A TELA DO ESPECTADOR (`/`)

Um player de vídeo simples. Quando o canal está no ar, o vídeo começa a tocar. Quando não está, aparece "Off air".

O player carrega o stream em HLS (`/hls/stream.m3u8`) e consulta o status do streamer a cada 10 segundos para atualizar o indicador ao vivo.

Se o browser bloquear autoplay, aparece um botão de play no centro — basta clicar.

---

## O PAINEL DE CONTROLE (`/admin`)

Tem 5 abas no menu lateral esquerdo:

---

### ABA 1 — Dashboard

O que você vê:
- **6 cards de estatísticas:** Total de assets, quantos são vídeos, músicas, bumpers, quantos aprovados, quantos pendentes de revisão
- **Stream Status:** mostra se está LIVE ou OFF, com botões **Start Stream** e **Stop Stream**
- **Recent Assets:** tabela com os últimos 5 assets cadastrados

**Start Stream** → manda o streamer começar a transmitir itens prontos da fila  
**Stop Stream** → pausa a transmissão (os containers continuam vivos)

---

### ABA 2 — Assets

Sua biblioteca de vídeos.

**Filtros no topo:**
- Por tipo: All / Video / Music / Bumper
- Por direitos: All / Pending Review / Approved / Blocked

**Tabela mostra:** título, tipo (badge colorido), direitos, status, duração em minutos, quantas vezes foi ao ar (Xn×)

**Botões por linha:**
- `Approve` → aprova o vídeo para transmissão (muda rights para `approved_for_stream`)
- `Block` → bloqueia (não entra em nenhum plano)
- Se já aprovado, só aparece o botão `Block`

**Botão `+ Add Asset` (canto superior direito)** abre um modal com:
- Kind: Video / Music / Bumper
- Source Type: Direct URL / Local File
- Title (obrigatório)
- Source URL (ex: `https://archive.org/download/.../video.mp4`)
- Local Path (só se for "Local File", ex: `/spool/downloads/meu-video.mp4`)
- Duration in seconds
- Notes (texto livre, ex: "Creative Commons")

> ⚠️ YouTube não funciona como source URL. Use URLs diretas de MP4 (archive.org, ou seus próprios arquivos).

---

### ABA 3 — Discovery

Aqui você ensina o sistema o que buscar e onde.

**Card esquerdo — Search Keywords**

Campos:
- Keyword or phrase (ex: `jazz piano noturno`)
- Category (ex: `music`, `film`) — texto livre, só para organização
- Weight — prioridade da busca (1 = normal, 2 = busca primeiro, 0.5 = menos urgente)
- Include / Exclude — Include adiciona à busca, Exclude filtra resultados que contenham o termo

Botão `Add Keyword` salva.

Lista mostra keywords com badge include/exclude, badge active/paused, e botão `Pause` ou `Enable`.

**Card direito — Search Domains**

Campos:
- Domain (ex: `archive.org`) — só o domínio, sem https://
- Max pages — quantas páginas o browser vai visitar por busca (máx 20)
- Mode: Keyword search (único disponível)
- Checkbox "Enabled for discovery"

Botões de atalho: `archive.org` / `vimeo.com` / `pexels.com` (preenchem o campo automaticamente)

Botão `Add Domain` salva.

> ⚠️ **pexels.com** precisa de API key no `.env` (`PEXELS_API_KEY`). Sem a key, a busca nele vai retornar nada silenciosamente.

Lista mostra domínios com badge enabled/off e botão `Enable`/`Disable`.

**Card Discovery Runs**

Dois botões:
- `Test Mode` → roda busca simulada (rápido, sem browser, URLs não são reais — útil para testar o fluxo)
- `Run Real Search` → abre o Chromium e busca de verdade nos domínios habilitados com as keywords ativas

Tabela mostra as últimas 8 buscas: data, status, quais keywords foram usadas, quantos encontrou no total, quantos têm download disponível.

**Card Candidates**

Lista de vídeos encontrados pela busca.

Filtros:
- Por retrieval: All / Downloadable (`authorized_direct`) / Official / Metadata only / Blocked
- Por rights: All / Pending / Approved / Blocked

Tabela mostra: título, URL encontrada, status de retrieval, status de direitos, status de discovery, duração estimada.

Botões por linha:
- `Approve` → marca o candidato como aprovado para stream
- `Promote` → **aprova E move para a biblioteca de assets** (aparece na aba Assets e pode entrar em um plano)
- `Block` → rejeita o candidato

> `Promote` faz os dois passos de uma vez: aprova o candidato e cria o LibraryAsset correspondente. É o botão que fecha o ciclo discovery → biblioteca.

---

### ABA 4 — Plans

Aqui você cria e aprova grades de programação.

**Botão `+ Generate Plan`** abre modal com:
- Date: data da grade (default: hoje)
- Hours: quantas horas de programação gerar (default: 24)
- Mix background music: checkbox — se marcado e houver assets de música aprovados, o sistema mistura trilha nos vídeos

Após gerar, aparece o **Plan Detail** com:
- 5 cards: Status do plano, nº de itens, duração total em horas, quantos já estão prep ready (prontos para transmitir), quantos ainda estão queued (na fila)
- Botão `Approve Plan` (se status for `draft`) — aprova a grade, o prep-worker começa a baixar e normalizar os vídeos
- Botão `Run Prep` (se status for `approved`) — força um ciclo de preparação manual imediatamente
- Tabela com até 50 itens: sequência, status de prep (queued/preparing/ready/failed), status de stream (queued/streaming/completed/failed), duração, se tem mix de música

> ⚠️ **Limitação real:** a aba Plans não lista planos anteriores. Você só vê o plano que acabou de gerar, ou carrega um pelo ID no campo de texto. Se fechou a janela sem anotar o ID, perdeu a referência.

**Para carregar um plano pelo ID:**
Cole o UUID no campo "Plan ID (UUID)" e clique `Load`.

---

### ABA 5 — Reports

Relatório diário do que foi ao ar.

- Selecione uma data no calendário
- `Load Report` → carrega relatório existente
- `Generate Now` → gera o relatório para a data selecionada agora

O relatório mostra:
- Horas planejadas vs horas efetivamente transmitidas
- Itens completados / itens com falha
- Quantas vezes caiu no fallback
- Quantos assets ainda pendentes de revisão
- Sugestões automáticas (ex: "adicionar mais conteúdo aprovado")
- Texto completo do relatório em markdown

---

## O CICLO COMPLETO (do zero ao ar)

**1. Adicionar vídeos** → aba Assets → `+ Add Asset` → preenche URL e título → salva

**2. Aprovar vídeos** → aba Assets → botão `Approve` em cada vídeo desejado

**3. Gerar grade** → aba Plans → `+ Generate Plan` → escolhe data e horas → `Generate`

**4. Aprovar grade** → no Plan Detail que apareceu → `Approve Plan`

**5. Preparar conteúdo** → aguarda o prep-worker processar automaticamente, ou clica `Run Prep` para forçar

**6. Ligar transmissão** → aba Dashboard → `Start Stream`

**7. Ver ao vivo** → https://tv.logline.world (aba "Open Player ↗" no menu)

---

## USAR DISCOVERY EM VEZ DE CADASTRAR MANUALMENTE

**1.** Aba Discovery → adicionar domínio `archive.org` (clique no atalho `archive.org`)

**2.** Adicionar keywords do que você quer (ex: `vintage city film`, `jazz concert archive`)

**3.** Clicar `Run Real Search` (ou `Test Mode` para ver o fluxo sem usar o browser)

**4.** Na tabela Candidates, clicar `Promote` nos vídeos que quiser — eles vão direto para a biblioteca já aprovados

**5.** Voltar para Plans e gerar a grade normalmente

---

## O QUE O SISTEMA FAZ SOZINHO (sem você intervir)

- **Prep-worker:** fica rodando em loop. Quando há um plano aprovado, baixa os vídeos e normaliza com FFmpeg automaticamente, antes do horário de transmissão
- **Streamer:** fica rodando em loop. Quando `desired_running=true` no banco, pega o próximo item pronto e transmite. Se não tem nada pronto, toca o fallback
- **Ficha do vídeo:** após cada transmissão, atualiza `times_streamed`, `health_score`, `last_play_status` e `play_log` automaticamente
- **Quarentena automática:** vídeos com muitos erros consecutivos (`health_score < 0.3`) são ignorados na geração do próximo plano
- **Limpeza do disco:** após transmitir, apaga o arquivo preparado (e o download bruto se nenhum outro item ainda precisar dele)
- **Restart automático:** se um container cair, o Docker sobe de volta sozinho

---

## O QUE VOCÊ PRECISA FAZER MANUALMENTE

- **Aprovar novos vídeos** (ou candidates do discovery) — o sistema não aprova sozinho
- **Gerar e aprovar um novo plano** quando o plano atual terminar — não há agendamento automático
- **Adicionar conteúdo** continuamente se quiser variedade

---

## LIMITAÇÕES REAIS (não tem solução agora)

- **Audiência:** o sistema não sabe quantas pessoas estão assistindo. RTMP não devolve essa informação. Precisaria integrar YouTube Analytics ou Twitch API separadamente.
- **YouTube como fonte:** não funciona. Só MP4 direto.
- **Plans sem lista:** não dá para ver todos os planos na interface. Só o que você acabou de gerar ou pelo ID.
- **Plataformas adultas:** o login e discovery funcionam pelo código, mas não têm botões na interface ainda — só via API diretamente.
