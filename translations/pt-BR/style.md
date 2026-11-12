# Guia de estilo pt-BR do cuju-render

Para quem reescreve `pt-BR.json`. Use junto com `glossary.json`, que fixa um termo para cada conceito recorrente. O inglês diz **o que** a mensagem comunica. O português decide **como** dizer, com a estrutura de frase que um app brasileiro bem feito usaria. Traduzir palavra por palavra é o erro que esta reescrita corrige.

## 1. Voz

- Trate a pessoa por **você**. Seja simpático e direto, como o menu de um bom jogo de futebol ou um app brasileiro caprichado. Nada de "o usuário", nada de linguagem de manual.
- Prefira a pessoa como sujeito da frase. O inglês dá ações a objetos ("Help resumes the tour", "Space pauses it", "Update shows it"). Em português isso soa robótico.

| Chave | Hoje | Melhor |
| --- | --- | --- |
| `tour.stopped` | O tour parou na etapa {index}. A Ajuda o retoma. | O tour parou na etapa {index}. Para continuar, abra a Ajuda. |
| `firstrun.tip.watch` | V alterna as câmeras, R mostra o replay do último gol, e o menu Partida lista os gols. | Use V para trocar de câmera e R para rever o último gol. O menu Partida lista todos os gols. |
| `pwa.state.updateReady` | Uma nova versão da página está pronta, Atualizar a mostra. | Há uma nova versão da página. Clique em Atualizar para carregá-la. |
| `lessons.doneBefore` | Feita antes. Faça de novo, ou siga para a próxima lição. | Você já fez esta lição. Faça de novo ou siga para a próxima. |
| `tour.done` | O tour terminou. As lições da Ajuda experimentam cada parte na prática. | Tour concluído! Para praticar cada parte, faça as lições da Ajuda. |

- Pode usar exclamação em momentos de celebração (conquista, lição concluída, recorde). Uma por mensagem, no máximo.
- Linguagem de futebol como o torcedor e o narrador falam: "virada", "goleada", "craque da partida", "mandante", "pontos corridos". Gíria leve é bem-vinda em nomes de prêmios e conquistas ("Bis", "Desencantou", "Deu zebra"). Em mensagens funcionais, seja neutro.

## 2. Botões, menus e títulos

- **Botões e itens de menu no infinitivo**: Salvar, Excluir, Exportar vídeo, Abrir gravação, Tentar de novo, Adicionar time. Nunca imperativo em botão ("Instale", "Escolha").
- **Instruções em frase corrida no imperativo**: "Escolha um time à esquerda.", "Conecte um controle e pressione um botão."
- **Títulos curtos**, sem artigo inicial quando não fizer falta, sem ponto final: "Exportar vídeo", "Nova partida", "Tour concluído", "Lixeira vazia".
- Título de diálogo que é ação usa infinitivo ("Instalar o cuju como app", hoje `installOffer.title` = "Instale o cuju como app").
- Nomes de páginas e menus vão exatamente como no glossário (Início, Assistir, Jogar, Gravações, Partidas, Torneios, Times, Campo, Ajuda; menus Partida e Exibir). Quando citados numa frase, sem aspas: "abra a página Partidas", "no menu Exibir".
- Rótulo de campo é substantivo: "Semente", "Nome do time", "Duração da partida (passos)".

## 3. Pontuação de interface

A regra principal: **nada de emendar orações com vírgula só porque o inglês emenda**. O inglês desta app junta tudo com vírgulas por escolha de estilo. Em português de interface, cada relação tem sua pontuação.

| Relação | Use | Exemplo |
| --- | --- | --- |
| rótulo e valor, motivo, lista que se anuncia | dois-pontos | "Conquistas: {names}." / "Não foi possível ler o clipe: {reason}" |
| informação acessória, atalho, unidade | parênteses | "Desfazer (Ctrl Z)" / "Semente (deixe em branco para sortear)" |
| ideia nova | ponto, nova frase | "A transmissão terminou. Você ainda pode rever os lances." |
| pergunta | ponto de interrogação | "Excluir “{title}” para sempre?" |
| ação em andamento | reticências (…, um caractere) | "Exportando…", "Carregando a classificação…" |
| porcentagem | % colado ao número | "{percent}%" |
| contraste | "mas" | "O time foi adicionado, mas não foi possível salvar o uniforme: {reason}" |

Antes e depois, com chaves reais:

| Chave | Hoje | Melhor |
| --- | --- | --- |
| `html.watch.tvHint` | Modo transmissão. A borda inferior ou {0} mostra os controles, {1} sai. | Modo transmissão. Para ver os controles, leve o mouse à borda inferior ou pressione {0}. Para sair, {1}. |
| `html.help.pages` | Início, escolha uma atividade. Times, importe submissões e edite jogadores. | Início: escolha uma atividade. Times: importe submissões e edite jogadores. |
| `decisions.skip` | Pular, Enter ou clique | Pular (Enter ou clique) |
| `menu.continue` | Continuar, Esc encerra | Continuar (Esc encerra) |
| `doctor.status.failing` | {count} verificações falham, {names}. | {count} verificações falharam: {names}. |
| `caption.fulltime.win` | Fim de jogo, vitória de {team}, {left} a {right} | Fim de jogo: vitória de {team} por {left} a {right} |
| `video.progress.drawing` | Desenhando o quadro {frame} de {frames}, {percent} por cento. | Desenhando quadro {frame} de {frames} ({percent}%)… |
| `recordings.details.tags` | Etiquetas, separadas por vírgulas, até vinte de até quarenta caracteres cada | Tags (separadas por vírgula, até 20, com até 40 caracteres cada) |
| `surprise-ui.seed.label` | Semente, vazia para uma nova | Semente (deixe em branco para sortear uma nova) |
| `firstrun.tip.line` | Dica. {text} | Dica: {text} |
| `palette.camera` | Câmera, {camera} | Câmera: {camera} |
| `html.watch.address.placeholder` | Fonte ao vivo ou id da gravação, depois Enter | ID da fonte ao vivo ou da gravação e Enter |

Outras regras:

- Vírgula continua normal dentro da frase (enumerações, orações subordinadas). O problema é a vírgula que separa duas frases completas ou que substitui dois-pontos ou parênteses.
- Evite cadeias de "e depois", "então" e "depois" herdadas de "then" e "so". Muitas vezes duas frases curtas ou uma oração com "para" resolvem: "Inicie o servidor com `cuju render serve` e tente de novo."
- Aspas: use aspas curvas “ ”. Mantenha intactas as aspas retas que fazem parte de código.
- Ponto final: em frases completas (avisos, descrições, erros da página), sim. Em botões, títulos, rótulos, itens de menu e opções de lista, não.
- Sem ponto e vírgula. Se precisar, faça duas frases.

## 4. Erros e avisos

Diga o que aconteceu e, quando houver, o que fazer. Comece pelo fato, não pelo objeto em voz passiva.

- Forma padrão: **"Não foi possível {verbo} {objeto}: {reason}"**. O motivo vem depois de dois-pontos, nunca de vírgula.
- Evite a passiva "X não pôde ser lido" (20 ocorrências hoje). Use "Não foi possível ler X".
- O conselho vem numa segunda frase, no imperativo.

| Chave | Hoje | Melhor |
| --- | --- | --- |
| `library.add.readFailed` | A pasta não pôde ser lida, {reason} | Não foi possível ler a pasta: {reason} |
| `fieldpage.board.unreadable` | Não foi possível ler esta imagem, {reason}. | Não foi possível ler esta imagem: {reason}. |
| `live.error.unreachable` | Não foi possível conectar à transmissão ao vivo, {error}. | Não foi possível conectar à transmissão ao vivo: {error}. |
| `doctor.server.failed` | O servidor não respondeu, {error}. Inicie-o com cuju render. | O servidor não respondeu: {error}. Inicie-o com `cuju render`. |
| `fieldpage.board.tooLarge` | Esta imagem tem {size} MB, o limite é {limit} MB. | Esta imagem tem {size} MB. O limite é {limit} MB. |
| `play.toast.busy` | Já há um jogo em andamento. Saia dele primeiro. | Já há um jogo em andamento. Saia dele antes de começar outro. |
| `recordings.purge.confirmOne` | Excluir "{title}" permanentemente? Os arquivos saem do disco, e isso não pode ser desfeito. | Excluir “{title}” para sempre? Os arquivos serão apagados do disco, e não dá para desfazer. |

Mensagens `server.*` são, em geral, **fragmentos** que entram num `{reason}` ou `{error}` de outra mensagem ("Não foi possível iniciar a exportação: {error}"). Por isso: começam com minúscula, não têm ponto final e devem ler bem logo depois de dois-pontos. O padrão atual "X deve ser Y, não Z" já é bom, mantenha. Pergunte-se como o fragmento soa dentro da frase que o recebe.

Confirmações destrutivas: pergunta curta, consequência numa segunda frase, botão com o verbo ("Excluir", não "OK"; "Dar W.O.", não "Confirmar").

## 5. Status e progresso

- Ação em andamento: gerúndio e reticências. "Carregando…", "Gerando o relatório…", "Enviando a sessão para o ranking…". Hoje faltam as reticências (`html.watch.loading` = "Carregando", `doctor.status.making` = "Gerando o relatório.").
- Ação concluída: particípio curto ou frase com "você". "Relatório copiado.", "Detalhes salvos.", "Gravação movida para a Lixeira. Você pode restaurá-la de lá."
- Estados de listas e filtros: "Nenhuma gravação ainda", "Nenhum resultado", "Nada ao vivo agora".
- Contagens com zero: prefira a forma `=0` com palavra ("Nenhuma gravação") a "0 gravações".

## 6. Números, unidades e datas

- Decimal com vírgula, milhar com ponto: 1.234,5 / 3.001 passos / dificuldade 0,6 / 10.000 arquivos.
- Escreva números em algarismos em interface, mesmo quando o inglês os soletra: "até 20 tags", "no máximo 10.000 caracteres", "por 2 minutos". Exceções: "um" e "dois" dentro de frase natural ("uma ou duas imagens"), e as chaves `main.teamSize.*`, que existem justamente para ser palavras.
- Unidades com espaço e abreviadas onde há pouco espaço: "12 s", "3 min", "2 MB", "45′". Em prosa, "segundos" e "minutos" por extenso estão bem.
- Porcentagem: "{percent}%", nunca "por cento" (6 ocorrências hoje).
- Placar: "2 a 1" em frase ("venceu por 2 a 1"). Confronto entre times: "{left} x {right}". Hoje `pt-BR.json` mistura "contra" e "x" para a mesma coisa. Padronize "x" para confrontos e "a" para placares.
- Dimensões: "1920 × 1080" ou "1920 por 1080". Escolha "por" em prosa e mantenha os nomes de formato (480p, 4K) como estão.
- Datas e números que entram por placeholder já chegam formatados pela página no locale pt-BR. Não tente reformatar o placeholder.

## 7. Maiúsculas

- Frase em caixa baixa (sentence case) em tudo: títulos, botões, menus. "Exportar vídeo", não "Exportar Vídeo".
- Maiúscula só em nomes próprios e nos nomes das páginas, menus e botões quando citados ("o menu Partida", "clique em Salvar", "a Lixeira").
- Siglas: ID (não "id"), IA, GRF, JSON, OBS, URL, FPS.

## 8. Placeholders, gênero e número

- Mantenha **cada placeholder exatamente** (`{count}`, `{0}`, `{team}`), sem acrescentar nem remover. Pode mudá-los de posição.
- Nomes de times, jogadores, torneios e títulos têm gênero e número desconhecidos. Escolha formas que funcionam para qualquer valor:
  - Ponha o nome **depois de dois-pontos** ou como complemento com "de": "Salvo: {name}", "Adicionado: {title}", "Vitória de {team}", "Gol de {team}".
  - Evite concordar adjetivos e particípios com o placeholder: "{name} salvo." vira "Alterações salvas em {name}." ou "Salvo: {name}".
  - Evite artigo contraído antes do placeholder ("do {team}", "da {name}"). Use "de {team}".
  - Inverta a frase quando o placeholder for sujeito com verbo que concorda: `tournament.toast.won` "{name} foi vencido por {champion}." vira "{champion} venceu {name}!".
  - `show.result.win` e `show.result.win.plural` podem virar ambas "Vitória de {team}".
  - Confronto pronto: "Pronta para assistir: {left} x {right}" (o sujeito implícito é "a partida"), não "{left} x {right} está pronta".
- Placeholders que são palavras soltas (como `{state}`, `{kind}`, `{reason}`) chegam de outras chaves. Leia a chave de origem para saber o gênero antes de concordar.
- Plurais: objetos `one`/`many`/`other` (e `=0`, `=1` quando úteis). Em português, `many` é a forma dos milhões ("1 milhão de gravações"). Como `{count}` chega em algarismos, copie `other` em `many`. Use `=0` para "Nenhum…" quando ficar mais natural. Uma forma pode omitir `{count}` ("Uma gravação" em `one`), mas mantenha os demais placeholders em todas as formas.

## 9. Tooltips, aria-labels e textos de leitor de tela

- Curto. Um tooltip nomeia a ação e, se houver, o atalho entre parênteses: "Gol anterior (Shift N)", "Tela cheia (F)".
- Um aria-label diz o que o controle é ou faz, sem repetir o que o leitor de tela já anuncia ("botão", "campo"). Se precisar de instrução, ela vem numa segunda frase curta: "Ambientes. Use as setas para navegar." (hoje `grid.tiles.label` = "Ambientes, as setas do teclado passam de um para outro").
- Rótulo composto vira dois-pontos ou parênteses: "Velocidade de reprodução (setas ↑ e ↓)" em vez de "Velocidade de reprodução, as setas para cima e para baixo a mudam".
- Anúncios de etapas: "Etapa {index} de {count}. {text}" está bom. Mantenha.

## 10. Termos do motor, comandos e marcas inline

- Texto em **backticks** é código: comandos (`cuju render serve`), variáveis (`CUJU_RENDER=on`), arquivos (`main.py`, `.cjr`), campos JSON (`keep_recordings`), consultas (`team:Greens after:60`). Fica em inglês, letra por letra.
- Atalhos de teclado em backticks: mantenha a estrutura que o inglês usa na marca (o mesmo separador, a mesma quantidade de marcas). Teclas com nome de letra ou sigla ficam iguais (Ctrl, Shift, Alt, Enter, Esc, Tab, Home, End, Page Up, F). Teclas com nome de palavra vão em português: Space = Espaço, comma = vírgula, period = ponto, plus = mais, minus = menos, setas = ←, →, ↑, ↓ (ou "seta para a esquerda" em prosa).
- **Negrito** com dois asteriscos: mantenha sobre o termo equivalente em português. Se a frase for reestruturada, o negrito acompanha a palavra.
- Sem HTML, nem entidades. Use os caracteres diretamente (…, “ ”, ×, ′).
- Nomes de ações do GRF que aparecem como dados (idle, sliding, built_in_ai) ganham o rótulo do glossário. Valores literais que a pessoa digita (true, false, home, away, agent, builtin, scenario) ficam em inglês, de preferência em backticks.
- Termos técnicos sem tradução corrente ficam em inglês, em caixa baixa: worker, service worker, shader, skin, buffer, glTF, LUFS, chroma key, thread. Não invente traduções.
- As palavras-chave de busca (`palette.words.*`, `*.words`, `moments.palette.keywords`) não são frases: são listas de sinônimos para a busca. Coloque sinônimos que um brasileiro digitaria, inclusive as variantes em inglês que ele usa ("replay", "tag", "ranking").

## 11. Coisas a cortar

- Possessivos redundantes herdados de "its" e "their": "o id dela", "os quadros dela", "a sua licença" (40 ocorrências de dele/dela hoje). O português costuma dispensar. "Digite o ID e pressione Enter."
- "Cada um / cada uma" e "um ... próprio" onde "próprio" basta ou nada falta.
- "Que ... cita/aponta/nomeia" herdado de "names": "Mude a configuração indicada na mensagem".
- Repetir o objeto quando o contexto já diz: "Excluir este time" no tooltip do botão Excluir de um time pode ser só "Excluir time".

## 12. Lista de verificação de cada mensagem

1. Li a mensagem em inglês, a chave e, se preciso, `docs/rendering.md` para entender o contexto.
2. A frase em português existe num app brasileiro? Leia em voz alta.
3. Nenhuma vírgula separando frases completas. Dois-pontos antes de motivo e lista, parênteses para atalho e nota.
4. Botão e menu no infinitivo, instrução no imperativo, sujeito humano quando a frase dá ordem a um objeto.
5. Termos iguais aos do `glossary.json`.
6. Todos os placeholders presentes, iguais e lidos corretamente para qualquer valor.
7. Plurais completos (`one`, `many`, `other`), marcas inline e código preservados, nenhum HTML.
8. Números e unidades no padrão brasileiro.

Observação para quem coordena: a seção Languages de `docs/rendering.md` pede hoje que a tradução siga "the plain style of the English, short sentences joined by commas and periods". Este guia contraria essa frase para o português. Vale ajustar o guia em inglês para dizer que cada idioma usa a pontuação natural da sua interface.
