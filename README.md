# relatorio-html

**Relatórios editoriais e interativos em um único arquivo HTML, a partir de qualquer planilha ou base de dados.** É uma alternativa ao Looker / Data Studio para quando você quer contar uma história com os dados, e não montar mais um painel.

Você descreve o relatório em Python (um *spec*). O kit valida o spec, embute os dados, as bibliotecas e as fontes, e gera um `.html` que abre offline com dois cliques. Depois um teste automático (Playwright) confere se tudo renderiza e responde aos filtros.

![Relatório de vendas no tema padrão (Neutro): título, filtros e KPIs em cartões](docs/vendas-hero-claro.png)

<p>
  <img src="docs/vendas-hero-escuro.png" width="64%" alt="Modo escuro">
  <img src="docs/vendas-mobile.png" width="22%" alt="Celular">
</p>

## O que faz

- **Visualização editorial.** O título afirma o achado. Os destaques são calculados, os KPIs vêm com variação e minigráfico, e cada seção responde a uma pergunta. Seguem as regras de Tufte, Few e Cleveland: rótulos diretos, barras a partir do zero, nada de pizza com muitas fatias, nada de 3D, nada de dois eixos.
- **Filtro cruzado em tudo.** Clicar numa barra, segmento, ponto, célula ou tema filtra o relatório inteiro (Shift soma à seleção). As instruções de uso ficam num lugar só, o botão "Como filtrar" (?) na barra de filtros, sem repetir em cada gráfico. Há também presets de datas, intervalo livre, dropdowns com busca (no desktop o valor escolhido aparece dentro do próprio dropdown, com um × para limpar; no celular, como chip), um contador na unidade do relatório ("R$ 3,6 mi de R$ 6,2 mi") e uma tabela com busca, ordenação e exportação CSV.
- **Texto fixo, números vivos.** O resumo, os destaques e os títulos com números são calculados em Python para a visão padrão e nunca são reescritos no navegador. Com um filtro ativo, aparece ao lado deles uma nota discreta "Visão sem filtros"; os números e os gráficos seguem o filtro.
- **Micro-interações discretas.** Título e cartões de KPI entram com um fade curto. As barras crescem quando entram na tela, os números dos KPIs contam até o valor e se animam a cada filtro, e as linhas se desenham. O cabeçalho se esconde ao rolar e o sumário lateral marca o capítulo ativo. A velocidade é configurável, e tudo respeita `prefers-reduced-motion`.
- **Pesquisas de satisfação (CSAT, CES, NPS)** com estatística honesta:
  - o kit detecta as colunas de nota pelo nome e pela escala;
  - todo número traz intervalo de confiança de 95% e n (Wilson, variância do NPS, t);
  - diferenças passam por teste z com correção de Holm, e o texto só diz "subiu" ou "caiu" quando o teste confirma;
  - grupos pequenos aparecem sempre, marcados como *amostra pequena*;
  - há análise de impacto (drivers), taxa de resposta e temas dos comentários agrupados offline, com dados pessoais mascarados.
- **Temas configuráveis.** Fontes (Google Fonts embutidas, arquivo local ou fonte do sistema), cor principal, paleta de dados, cantos, fios, espaçamento, escala tipográfica, hero, movimento e logo. Dois layouts (`clean` e `blocks`) e cinco presets. O build checa o contraste (WCAG, 4,5:1).
- **Regras de leitura consistentes.**
  - Uma granularidade de tempo para o relatório inteiro (`time_grain`, automática pelo intervalo dos dados ou definida por você). Ela vale para todos os gráficos de tempo, KPIs e a tabela, e o build falha se um gráfico tentar outra sem `grainOverride`.
  - A pergunta da pesquisa aparece **completa, exatamente como está no dado**, sem resumo nem reticências.
  - O texto gerado é literal, sem analogias nem metáforas ("caiu 3 pontos", não "esfriou").
  - Gráficos, seções e KPIs sem dados são omitidos no build, com aviso. No navegador, um gráfico esvaziado pelo filtro vira uma linha discreta.
  - A metodologia fica no fim, recolhida, e abre com um clique (no PDF sai aberta).
- **Um arquivo só.** d3 e Observable Plot vão embutidos, assim como as fontes e o logo. Tem modo claro e escuro, layout responsivo e um PDF pronto para impressão.
- **Acessível.** Quem filtra pelo teclado continua no mesmo item depois do redesenho, uma linha `aria-live` anuncia o filtro, Esc devolve o foco ao dropdown, cada gráfico é uma imagem com nome, os cabeçalhos da tabela são botões com `aria-sort`, textos pequenos passam de 4,5:1 (também no escuro e sobre o hero colorido) e os botões do celular têm 44 px.
- **QA automático.** `verify.py` abre o relatório no Chromium e checa erros no console, se cada gráfico renderizou, cliques e filtros, a tabela, o modo escuro e a ausência de rolagem lateral no celular. Em 1440, 1024 e 390 px, claro e escuro, também confere rótulos sobrepostos ou fora do gráfico, contraste dos textos pequenos, foco e anúncios depois de filtrar. Também tira os screenshots.

<p>
  <img src="docs/vendas-filtro-visao-sem-filtros.png" width="62%" alt="Filtro ativo: o valor aparece no dropdown e o resumo ganha a nota Visão sem filtros">
  <img src="docs/vendas-mobile-colunas.png" width="30%" alt="Colunas no celular: o nome da região fica acima do valor">
</p>

<p>
  <img src="docs/cx-ajuda-e-pergunta.png" width="49%" alt="Ajuda de interação única na barra de filtros e a pergunta da pesquisa completa sob o título do gráfico">
  <img src="docs/metodologia-recolhida.png" width="49%" alt="Metodologia no fim do relatório, recolhida por padrão">
</p>

### Pesquisas de satisfação

![Relatório de pesquisa pós-atendimento (dados fictícios)](docs/cx-hero.png)

<p>
  <img src="docs/cx-nps-por-canal.png" width="49%" alt="NPS por canal, com teste de significância">
  <img src="docs/cx-csat-por-uf-ic.png" width="40%" alt="CSAT por UF com intervalo de confiança; UFs pequenas vazadas">
</p>

![Distribuição das notas de CSAT por canal](docs/cx-likert-csat.png)

<img src="docs/cx-temas-comentarios.png" width="55%" alt="Temas dos comentários abertos">

### Temas

O padrão é o **Neutro**: fundo off-white, tinta em escala de cinzas e um azul profundo como cor principal. A paleta de dados é segura para daltonismo. As fontes são Inter + IBM Plex Mono. O cabeçalho é simples, os KPIs vêm em cartões e o movimento é discreto. Para mudar, basta escolher outro preset ou sobrescrever qualquer valor.

| Preset | Layout | Estilo |
|---|---|---|
| `neutro` (padrão) | `clean` | Neutro e calmo: cinzas, azul `#1F4E79`, Inter, cartões de KPI |
| `corporativo` | `blocks` | Herói e faixa de KPIs em azul-marinho, IBM Plex |
| `jornal` | `clean` | Títulos serifados (Newsreader), fundo creme, vermelho como cor principal |
| `noturno` | `blocks` | Escuro, blocos verde-limão, Space Grotesk |
| `destaque` | `blocks` | Herói em amarelo-sol, dados em azul-petróleo, Archivo; para apresentações |

O mesmo relatório de vendas no preset `corporativo`:

![Tema corporativo](docs/tema-corporativo-hero.png)

## Como funciona

1. **Contextualização (passo 0, obrigatório).** Antes de gerar qualquer coisa, o agente pergunta só o que não dá para inferir:
   - o **objetivo**, isto é, que decisão o relatório vai apoiar;
   - o **público** (diretoria, time, cliente) e o nível técnico;
   - os **pontos-chave** ou hipóteses que a pessoa quer ver;
   - o **período** e o recorte.

   Em seguida, roda o perfil dos dados e devolve uma **proposta curta** para aprovação: filtros (colunas do cross-filter), linguagem e tom, seções na ordem de leitura (com a pergunta que cada uma responde e o gráfico previsto), KPIs, métricas de CX quando for pesquisa (CSAT, CES, NPS), tema e suposições. Nada é construído antes do "ok". Quem preferir pode dizer "segue", e o agente usa a proposta e registra as suposições.
2. **Modelagem.** As respostas ficam em `spec["contexto"]` e orientam o resto. O título responde ao objetivo, o texto segue o público e cada ponto-chave vira um destaque ou uma seção. Com `"exibir": true`, objetivo, público e pontos-chave aparecem numa coluna discreta no rodapé.
3. **Narrativa e build.** Os destaques são calculados em pandas e o `build.py` gera um único HTML.
4. **Verificação.** O `verify.py` testa o relatório num Chromium headless e tira os screenshots antes da entrega.

```python
spec["contexto"] = {
    "objetivo": "Decidir onde investir e onde cortar desconto no próximo trimestre",
    "publico": "Diretoria comercial; leitura rápida, pouco técnica",
    "pontos_chave": ["Crescimento por região", "Margem perdida com desconto"],
    "linguagem": {"idioma": "pt-BR", "tom": "direto", "nivel": "leigo"},
    "periodo": "Últimos 12 meses vs. os 12 anteriores",
    "suposicoes": ["Pedidos cancelados ficam fora"],
    "exibir": False,   # True = coluna "Sobre este relatório" no rodapé
}
```

## Grid de layout

Todo o relatório segue um grid só, com duas faixas, e cada bloco ocupa **100 %, 50 % ou 33 %** (12, 6 ou 4 colunas, gutter fixo de 32 px):

- **Cabeçalho em largura total**: título, metadados, barra de filtros (também quando fica presa no topo), resumo, KPIs e destaques vão de uma margem à outra (1376 px numa tela de 1440). O resumo mantém a medida de leitura. KPIs e destaques ficam nessa faixa porque o menu está oculto ali: um trilho vazio ao lado dos números ficaria como um buraco.
- **Conteúdo**: seções, gráficos, notas, tabela e metodologia ficam numa coluna de largura máxima fixa (1128 px a 1440), com um trilho reservado à esquerda para o menu de capítulos.
- **O menu aparece com o scroll**: fica oculto no topo e entra com fade e slide quando a primeira seção chega até ele (IntersectionObserver). Some de novo ao voltar ao topo e nunca cobre o cabeçalho nem os filtros. O trilho já está reservado, então o conteúdo não pula. Com movimento reduzido não há animação.

```python
{"type": "bars", "dim": "canal", "measure": "receita", "width": "half"}   # full (padrão) | half | third
```

- Cada linha tem uma largura só: 1 full, 2 halves ou 3 thirds. Se sobrar um gráfico sozinho, o `build.py` avisa e o alarga (um half sozinho vira full; 2 thirds viram 2 halves). Qualquer outro valor em `width` faz o build falhar.
- Gráficos densos (heatmap, small multiples, tabela, séries longas) ficam em full. `half` serve para comparar dois gráficos; `third`, para três visões curtas e paralelas.
- Gráficos lado a lado têm títulos com a mesma altura, então os eixos começam na mesma linha.
- No tablet, third vira half e o menu vai para a gaveta do cabeçalho. No celular, tudo fica em full (os KPIs ficam em pares).
- As medidas vêm do tema (`layout.grid`: `maxWidth`, `rail`, `railGap`, `gutter`, `pad`). O `verify.py` confere o alinhamento em 1440, 1280, 1024 e 390 px, a largura total do cabeçalho e dos filtros e o menu oculto no topo e visível depois do scroll.

<p>
  <img src="docs/vendas-topo.png" width="49%" alt="Topo: cabeçalho, filtros, KPIs e destaques em largura total, sem menu lateral">
  <img src="docs/vendas-rolado-menu.png" width="49%" alt="Página rolada: filtros presos no topo em largura total e o menu de capítulos no trilho">
</p>

![Grid de 12 colunas e trilho do menu sobre a seção Volume do exemplo de pesquisa](docs/grid-12-colunas.png)

## Começando

```bash
git clone https://github.com/jpmacieldasilva/relatorio-html.git
cd relatorio-html
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# exemplos (os CSVs fictícios são gerados na primeira execução)
python exemplos/vendas/preparar.py               # → exemplos/vendas/relatorio.html
python exemplos/vendas/preparar.py corporativo   # → relatorio-corporativo.html
python exemplos/cx/preparar.py                   # → exemplos/cx/relatorio.html
python verify.py exemplos/cx/relatorio.html --out /tmp/capturas
```

Os HTMLs já gerados estão em `exemplos/`. Basta abrir no navegador.

### Com os seus dados

0. **Contexto.** Defina objetivo, público, pontos-chave e linguagem, e guarde em `spec["contexto"]` (veja *Como funciona*).
1. **Perfil.** `python profile.py dados.xlsx --out perfil.json --clean-out limpo.parquet` lê CSV, XLSX, JSON, Parquet e SQLite e faz uma limpeza conservadora. O resultado mostra papéis das colunas, nulos, datas, outliers e alertas.
2. **Spec.** Em Python, monte as medidas (taxas são sempre razão de somas), pré-agregue, calcule os destaques com pandas e escreva o spec. Copie a estrutura de `exemplos/vendas/preparar.py`. Para pesquisas, use `exemplos/cx/preparar.py` e `cx.py`.
3. **Build.** `build.build(spec, "relatorio.html", theme="jornal")`, ou pela linha de comando: `python build.py spec.json relatorio.html --theme corporativo`.
4. **Verificação.** `python verify.py relatorio.html --pdf`. Não entregue com falha.

Para importar os módulos por caminho (o nome `profile` colide com a stdlib):

```python
import importlib.util, os, sys
KIT = os.environ.get("RELATORIO_KIT", "/caminho/para/relatorio-html")
def kit(name):
    s = importlib.util.spec_from_file_location("kit_" + name, os.path.join(KIT, f"{name}.py"))
    m = importlib.util.module_from_spec(s); sys.modules["kit_" + name] = m; s.loader.exec_module(m); return m
rp, rb, cx = kit("profile"), kit("build"), kit("cx")
```

## Como skill de agente de IA

A pasta inteira é uma *skill* no formato `SKILL.md` (Cursor, Claude Code e afins). Copie ou clone o repositório para a pasta de skills do agente, por exemplo `~/.cursor/skills/relatorio-html/` ou `~/.claude/skills/relatorio-html/`. O agente passa a:

1. contextualizar: perguntar objetivo, público, pontos-chave e período, perfilar os dados e propor filtros, linguagem, seções, KPIs (e o mapeamento das colunas quando for pesquisa) e tema. Depois, esperar a aprovação;
2. guardar o que foi aprovado em `spec["contexto"]`;
3. modelar e calcular a narrativa em pandas, sem inventar números nem direções;
4. gerar o relatório;
5. rodar `verify.py` e revisar os screenshots antes de entregar.

Os caminhos no `SKILL.md` são relativos à pasta da skill. `RELATORIO_KIT` permite apontar para outra localização.

## Configurando o tema

Pelo spec (`spec["theme"]`) ou por `--theme`, você passa um preset, um arquivo JSON ou ajustes inline mesclados sobre o padrão:

```python
spec["theme"] = {
    "primary": "#0B5FFF",          # blocos do hero e da faixa de KPIs
    "accent":  "#7FB2FF",          # cor dos dados
    "font": "Inter", "heading": "Fraunces",   # Google Fonts → embutidas como woff2
    "logo": "logo.svg", "brand": "Acme",
    "hero": {"style": "plain"},    # sem bloco de cor
    "motion": {"speed": 0.8},
}
```

Um tema completo (`temas/neutro.json`) define `layout` (`clean` ou `blocks`), `fonts`, `colors` (light/dark), `palette` (categórica, sequencial, divergente, positivo/negativo), `shape`, `space`, `type`, `hero`, `motion` e `brand`. Veja [`TEMA.md`](TEMA.md). Para testar um tema sem gerar relatório: `python tema.py jornal`.

## Limitações

- **Todos os dados vão para o navegador.** Agregue ou remova dados pessoais e segredos antes. Nas pesquisas, o texto completo dos comentários não é embutido.
- **Volume.** O filtro no navegador é confortável até cerca de 150–200 mil linhas na tabela fato. Acima disso, agregue mais (por exemplo, dia → semana).
- **Destaques.** Os textos de destaque são estáticos e descrevem a visão padrão; KPIs e gráficos são vivos.
- **Temas dos comentários** são aproximados: um tema por comentário, nomes a partir dos termos mais característicos. Revise e renomeie.
- **Mascaramento de dados pessoais** é heurístico. Revise as citações antes de compartilhar.
- **Drivers** mostram associação, não causa. Os testes assumem respostas independentes.
- **Fontes do Google** precisam de internet só no primeiro build (ficam em cache em `vendor/fonts-cache/`).

## Licenças

Código sob [MIT](LICENSE) © 2026 João Paulo da Silva. d3 e Observable Plot (ISC) e as fontes Geist, IBM Plex, Inter, JetBrains Mono, Montserrat, Newsreader e Space Grotesk (SIL OFL 1.1) vão embutidos com suas próprias licenças. Veja [NOTICE.md](NOTICE.md). Os dados de exemplo são **fictícios**.

---

## English

**relatorio-html** turns any dataset (CSV, XLSX, JSON, Parquet, SQLite) into an editorial, interactive, **single-file HTML report**:

- story-first layout and cross-filtering charts (d3 + Observable Plot);
- micro-interactions, light/dark mode, print/PDF;
- a searchable table with CSV export;
- automated Playwright QA.

It includes a **survey module** for CSAT, CES and NPS:

- automatic column detection;
- 95% confidence intervals on every number;
- z-tests with Holm correction, so wording is derived from significance;
- small groups always shown and flagged;
- driver analysis, response rate, and offline comment themes with PII masking.

The look is driven by **JSON themes**: layout (`clean` or `blocks`), fonts (Google Fonts inlined, local files or system), colors, palette, radius, spacing, type scale, hero, motion and logo. Contrast is checked at build time.

The default theme, **Neutro**, is calm and neutral:

- off-white page, grey ink scale and one deep-blue primary;
- colorblind-safe data palette;
- Inter + IBM Plex Mono;
- plain header, KPI cards and subtle fade/grow motion.

Other presets: `corporativo` (navy block hero), `jornal` (serif, newspaper), `noturno` (dark, lime) and `destaque` (sun-yellow blocks, for presentations).

How it works: **step 0 is a mandatory context pass.** The agent asks only what it can't infer: the goal (which decision the report supports), the audience and its technical level, the key points or hypotheses, and the period. It then profiles the data and sends a short proposal: filters, language and tone, sections (each with its question and chart), KPIs, CX metrics for surveys, theme and assumptions. It builds nothing until the user approves; "go ahead" skips the round and records the assumptions. The answers live in `spec["contexto"]` and steer the headline, the copy and the section order. `"exibir": true` shows them in a discreet footer column. After that come the pandas narrative, `build.py` and `verify.py`.

Reading rules built in:

- one time grain for the whole report (`time_grain`, auto from the data span or set by you), so every time chart, KPI and the table use it, and the build fails on a mismatched chart unless it has `grainOverride`;
- survey questions are shown verbatim and in full (never shortened or cut with "…");
- generated copy is literal, with no analogies or metaphors;
- charts, sections and KPIs without data are omitted at build time (with a warning), and a chart emptied by a filter collapses to one quiet line;
- interaction help lives in one "Como filtrar" (?) popover instead of on every chart;
- the methodology is the last block, collapsed by default and expanded in print.
- one layout grid: the header zone (hero, filter bar, summary, KPIs, highlights) spans the whole page width; sections sit in a fixed-width content column next to a reserved rail where the chapter menu fades in once you scroll past the header; 12 columns with a fixed gutter, every block at 100 / 50 / 33 %; charts take `"width": "full" | "half" | "third"`, the build widens incomplete rows, and `verify.py` checks the edges at 1440, 1280, 1024 and 390 px.

Quick start: `pip install -r requirements.txt && python -m playwright install chromium`, then `python exemplos/vendas/preparar.py` and `python verify.py exemplos/vendas/relatorio.html`. The folder is also a drop-in **AI agent skill** (`SKILL.md`, paths relative to the skill folder). Docs are mostly in Portuguese (pt-BR). Code comments and `SKILL.md` are in English. MIT licensed; bundled third-party licenses are listed in `NOTICE.md`.
