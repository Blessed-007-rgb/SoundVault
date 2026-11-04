# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

SoundVault: baixa playlists (Spotify → YouTube) como MP3, com EQ/loudness por playlist. App de terminal em Python, Windows. Documentação de uso: `README.md` (em português; responda e comente em português BR).

## Comandos

Tudo roda a partir de `Download Musicas/_core/`:

```bash
cd "Download Musicas/_core"
python -m pytest tests -q -p no:cacheprovider          # suíte inteira (~6 s, precisa de ffmpeg no PATH)
python -m pytest tests/test_search.py::TestPontuar -q  # um teste/classe
pyright                                                # usa pyrightconfig.json (soundvault + tests); meta: 0 erros
ruff check --select F,E9,B904 soundvault tests         # erros reais; o lint "completo" tem centenas de avisos de estilo antigos
```

Rodar o app (os `.bat` de `Main/` fazem isso): `SOUNDVAULT_ROOT_DIR` aponta para `Download Musicas/` e `PYTHONPATH` para `_core`, depois `python -m soundvault [--profile P] [--playlist NOME] [--sync|--retry|--audit|--rebuild|--fix-tags|--clean|--duplicatas|--duplicatas-pl|--reset-puladas|--validate|--review-urls|--doctor [--offline]|--cookies-browser NAVEGADOR]`. Sem argumento abre o menu. Fora de um terminal interativo o `input()` final recebe `EOFError` (tratado). `--doctor` devolve exit 1 se achar erro.

Dependências: `pip install -r requirements.txt` (`yt-dlp[default] rich mutagen psutil`; dev: `requirements-dev.txt`), mais `ffmpeg` e `node` no PATH. Sem `psutil` o lock não confere o PID; sem `yt-dlp-ejs` (vem no `[default]`) o yt-dlp não resolve os desafios de JS. `python -m soundvault --doctor` confere tudo isso.

Hooks do Claude Code (`.claude/settings.json`): após `Edit|Write` em `.py` de `_core` roda `ruff` (F,E9,B904) no arquivo; ao parar, se há `.py` alterado, roda `pytest` + `pyright` (~15 s) e devolve a falha pra você corrigir.

## Arquitetura

Um perfil = uma pasta em `Download Musicas/` (ex.: `Main/`); `config.py` guarda os caminhos como **globais mutáveis** e `config.ativar_perfil()` os troca (`--profile`). Todo módulo lê `config.X` em tempo de chamada, nunca copia o valor no import.

Fluxo de um Sync (`sync.sincronizar`), que cruza vários módulos:

1. **Alvo**: `playlists.py` — cada playlist é `playlists/<nome>/{playlist.txt, preset.json, render_state.json, Musicas/}`. O Sync trabalha sobre a união das playlists escolhidas, mas a **limpeza do pool usa a união de TODAS** (música só sai do disco quando nenhuma playlist a usa).
2. **URL**: `playlist_cache.json` (nome → `{url,id}`). Sem entrada válida (`storage.entrada_cache_valida`), `search.buscar_ytmusic` pesquisa no YouTube e pontua candidatos (`_pontuar_candidato`).
3. **Download**: `download.baixar` chama o `yt-dlp` **sem cookies primeiro** e só cai para `cookies.txt` em erro de auth/formato; `playlist.classificar_erro` decide permanente/formato/auth/rate/retry. Resultado vai para o **pool cru** `Main/Musicas/` e para `sync_state.json`.
4. **Render**: `playlists.reconciliar_links` → `audio.renderizar_audio` (ffmpeg em 2 passos: mede com `ebur128`, aplica `equalizer`+`volume`+`alimiter`) gera o MP3 da playlist com o preset de `eq_presets.py`, em paralelo (`config.RENDER_WORKERS`). `render_state.json` guarda o hash do preset/receita por música (`audio.perfil_atual`); mudou o hash → re-renderiza.

Convenções que não são óbvias lendo um arquivo só:

- `sync_state.json` é indexado por **video_id**. Duas músicas no mesmo vídeo usam a chave `dup_<id>_<hash>` (ver `download.baixar`); chaves `skip_<nome>` são puladas por copyright. Não assuma que toda chave é um video_id.
- Entradas do cache são validadas/normalizadas em `storage.normalizar_entrada_cache` (ID de exatamente 11 chars; `playlist.extrair_video_id` é estrito de propósito). Toda escrita passa por `storage.salvar_cache_entrada` (com lock). Além de `url`/`id`, uma entrada achada pela busca automática traz `auto`, `score` (0-100) e `video` (título achado); abaixo de `search.SCORE_REVISAO` (80) entra na fila de revisão (menu `V` / `--review-urls`, `cache_maint.revisar_urls_automaticas`), que marca `revisado`. Rejeitar uma URL limpa `url`/`id` e guarda o vídeo em `rejeitados` (a busca nunca o repete; `salvar_cache_entrada` preserva essa lista) e apaga pool/state/renders da música. Entrada manual (opção `U`) leva `origem: manual, revisado: true`.
- Cookies: `config.cookies_args()` / `cookies_params()` decidem entre `--cookies-from-browser <nav>` (escolhido por perfil em `perfil.json` via `--cookies-browser`) e o `cookies.txt`; use-os, não `COOKIES_FILE` direto. Chamadas ao `yt-dlp` levam `*procutil.ytdlp_js_args()` (habilita node/bun; o yt-dlp só liga o deno sozinho).
- JSON de estado é gravado com `storage._escrever_json_atomico` (tmp + `os.replace`); não use `write_text` direto.
- `console_log.py` é a **única** fonte do `rich` (`Table`, `Panel`, `Progress`, `box`, `console`...) e traz substitutos quando ele não está instalado; não importe `rich` direto nos outros módulos. Todo uso de rich fica sob `if RICH_OK:`.
- Processos externos: use `**procutil.sem_janela()` nos `subprocess` (evita janela de console no Windows).
- Antes de baixar/renderizar, `sync._espaco_suficiente` consulta `disco.avaliar` (downloads + `playlists.renders_pendentes`, ×`MARGEM`): sobra pouco só avisa; não cabe pergunta (padrão Não; EOF = cancela).
- O menu principal lê a escolha tecla a tecla (`entrada.ler_escolha`, só Windows em terminal real) e redesenha centralizado se a janela mudar de tamanho; só ele reage a redimensionamento e só ele é centralizado (os demais painéis ficam à esquerda de propósito). No Windows, `limpar_tela` apaga o buffer pela API (`_limpar_console_windows`; o `console.clear()` do rich não limpa o conhost sem VT) e as chamadas ctypes precisam de `argtypes`.
- Terminal: use `console_log.limpar_tela()` (nunca `os.system`; um teste varre o pacote por isso) e deixe os símbolos ✓ ⚠ ✗ ⊘ nas strings — `console_log.configurar_simbolos()` (chamado no `main()`) troca por ASCII no conhost antigo; spinners do rich usam `nome_do_spinner()`. `SOUNDVAULT_ASCII=0/1` força.
- Progresso do render: `reconciliar_links(nome, cb)` chama `cb(feito, total)`; a UI é `progresso.barra_de_render(...)`. O `rich` só aceita um display ao vivo por vez, então não aninhe essa barra dentro de outro `Progress`.
- Ações destrutivas pedem confirmação com padrão **Não**. Ctrl+C nunca deve virar traceback (ver `test_ctrl_c.py`).
- Pastas/arquivos de dados do usuário (`Main/`, `cookies.txt`, `playlist_cache.json`, `sync_state.json`, `Musicas/`, `playlists/`) estão no `.gitignore` e são a biblioteca real dele: **não rode Sync/render/limpeza nela sem pedido explícito**, e nunca commite `cookies.txt`.

## Testes

`tests/conftest.py` aponta `SOUNDVAULT_ROOT_DIR` para uma pasta temporária **antes** de importar `soundvault.config` (que cria pastas no import) e a fixture `perfil` isola cada teste num perfil novo. Testes de áudio geram MP3 com `ffmpeg -f lavfi` e se pulam sem ffmpeg. `tests/test_sync_e2e.py` roda o `sincronizar` inteiro com o yt-dlp simulado (`YtDlpFalso` substitui `subprocess.run` só para o yt-dlp; ffmpeg/mutagen são reais): ao mexer no Sync, rode-o. Em testes, faça o patch de `sys.stdout` DENTRO do teste (o pytest o reinstala ao entrar na fase de execução, descartando patch de fixture). Ao mudar comportamento, adicione teste de regressão.

## Edição de arquivos

Os `.py` estão em CRLF no disco (o Git avisa "LF will be replaced by CRLF"). `Edit` com `old_string` de várias linhas pode não casar; prefira trechos de uma linha, ou normalize `\r\n` ao patchear por script.
