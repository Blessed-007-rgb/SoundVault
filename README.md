# SoundVault Playlist Manager

Sistema de sincronização Spotify → YouTube → MP3.

Este repositório contém só a **base do projeto** (o código). Cada
usuário cria localmente sua própria playlist, cache e cookies — nada
disso é versionado (veja [`.gitignore`](.gitignore)).

## 1. Requisitos

### 1.1 Python

Baixe em: https://www.python.org/downloads/

Durante a instalação marque **Add Python to PATH**.

Teste no Prompt:

```
python --version
```

### 1.2 Dependências Python

```
pip install -U yt-dlp rich mutagen
```

- `yt-dlp` → faz os downloads do YouTube
- `rich` → interface visual do menu
- `mutagen` → grava metadados nos MP3

### 1.3 Node.js (obrigatório para o yt-dlp funcionar)

Baixe em: https://nodejs.org — marque a opção de adicionar ao PATH.

Teste:

```
node --version
```

### 1.4 FFmpeg (obrigatório)

Baixe a versão "essentials" em: https://www.gyan.dev/ffmpeg/builds/

Extraia, copie o caminho da pasta `bin` e adicione ao PATH do Windows
(Painel de Controle → Sistema → Configurações avançadas → Variáveis de
ambiente → Editar PATH → Novo).

Teste:

```
ffmpeg -version
```

## 2. Estrutura de pastas

```
Download Musicas\
  _core\                            ← código compartilhado por todos os perfis
    soundvault\
      config.py, sync.py, download.py, menu.py, spotify_export.py, ...
  iniciar.bat                       ← lista os perfis existentes e abre o escolhido
  Main\                             ← seu perfil pessoal (padrão)
    play.bat                        ← abre o menu do seu perfil
    playlist.txt                    ← [não versionado] lista de músicas que você quer
    playlist_cache.json             ← [não versionado] URLs do YouTube (auto ou via TuneMyMusic)
    cookies.txt                     ← [não versionado] cookies do YouTube
    sync_state.json                 ← [não versionado] controle do que já foi baixado (automático)
    Musicas\                        ← [não versionado] arquivos MP3
    Logs\                           ← [não versionado] logs (automático)
    Spotify export\
      spotify_export.bat            ← extrai playlist do Spotify pra playlist.txt
  Tiago\                            ← perfil de um amigo
    play_tiago.bat
    ...
```

Cada perfil é completamente isolado — músicas, logs e estado de cada um
ficam dentro da própria pasta — mas todos compartilham o mesmo código em
`_core\`. Corrigir um bug ali conserta todos os perfis de uma vez, sem
precisar copiar arquivo nenhum.

## 3. Como executar

### 3.1 Escolher o perfil pelo menu

Duplo clique em `Download Musicas\iniciar.bat` — ele lista os perfis
existentes (qualquer pasta com um `play*.bat` dentro) e abre o escolhido.

### 3.2 Seu perfil pessoal (Main) direto

Duplo clique no `play.bat` dentro de `Main\`. Sem argumentos, abre o
menu interativo do perfil `Main`.

### 3.3 Perfil de um amigo (ex: Tiago)

Duplo clique no `play_tiago.bat` dentro de `Tiago\`. O `.bat` contém
`--profile Tiago`, que aponta pra pasta correta.

### 3.4 Criar perfil para um novo amigo

1. Crie uma pasta com o nome do amigo dentro de `Download Musicas\`
   (ex: `Download Musicas\Pedro\`).
2. Coloque o `playlist.txt` (e opcionalmente `playlist_cache.json`) do
   amigo dentro.
3. Crie um `play_pedro.bat`:

   ```bat
   @echo off
   chcp 65001 >nul
   set "SCRIPT_DIR=%~dp0"
   cd /d "%SCRIPT_DIR%"
   if not exist "%SCRIPT_DIR%Logs" mkdir "%SCRIPT_DIR%Logs"
   set "SOUNDVAULT_ROOT_DIR=%SCRIPT_DIR%.."
   set "PYTHONPATH=%SCRIPT_DIR%..\_core;%PYTHONPATH%"
   python -m soundvault --profile Pedro %*
   if %ERRORLEVEL% NEQ 0 (
       echo.
       echo ============================================================
       echo  ERRO FATAL - verifique Pedro\Logs\crash.log
       echo ============================================================
       pause
   )
   ```

4. Duplo clique no `play_pedro.bat` para abrir o menu do Pedro.

Nenhum arquivo `.py` precisa ser copiado — todo o código vem de
`_core\`. `Musicas\` e `Logs\` são criadas automaticamente na primeira
execução.

## 4. Menu — opções disponíveis

| Opção | Nome | Descrição |
|---|---|---|
| 1 | Sincronizar | Baixa músicas pendentes do `playlist.txt`. Remove do disco músicas que saíram da playlist (bidirecional). Tenta até 3x em falha de rede. Músicas com copyright tentam URL alternativa. |
| 2 | Retry de Falhas | Tenta de novo só as músicas que falharam no último Sync. |
| 3 | Remover Duplicatas | Detecta e remove MP3s duplicados por hash MD5. |
| 4 | Verificar Biblioteca (Auditoria) | Compara `playlist.txt` × `sync_state.json` × disco. Mostra faltando, órfãos, corrompidos, sem URL. |
| 5 | Limpar Registros | Remove do `sync_state.json` entradas cujo MP3 não existe mais no disco. |
| 6 | Verificar Cache | Valida o `playlist_cache.json`: entradas sem URL, URLs inválidas, IDs errados. |
| 7 | Reaplicar Áudio | Reprocessa EQ e normalização de volume nos MP3 existentes. |
| 8 | Corrigir Metadados | Grava título, artista e capa nos MP3 existentes. |
| 9 | Registrar MP3s do Disco | Importa MP3s existentes que o sistema não conhece; consolida duplicatas no `sync_state.json`. |
| H | Help | Documentação detalhada dentro do próprio programa. |
| 0 | Sair | — |

## 5. Cookies do YouTube

Necessário para o `yt-dlp` conseguir baixar.

1. Instale a extensão **"Get cookies.txt LOCALLY"** (Chrome/Edge).
2. Acesse youtube.com logado na sua conta.
3. Clique na extensão e exporte os cookies.
4. Salve o arquivo como `cookies.txt` na pasta do perfil.

Se os downloads começarem a falhar com erro de autenticação, o cookie
expirou — exporte um novo e substitua o arquivo.

> `cookies.txt` nunca deve ser commitado — ele contém sua sessão real
> do YouTube. Já está no `.gitignore`.

## 6. Formato do `playlist.txt`

Uma música por linha, no formato `Artista - Título`:

```
Racionais MC's - Vida Loka Pt. 1
50 Cent - Window Shopper
Eminem - Lose Yourself
```

Linhas começando com `#` são ignoradas (comentários). O arquivo é a
fonte de verdade — o Sync baixa o que está aqui e remove do disco o
que foi removido daqui.

Você pode gerar esse arquivo manualmente, ou usando
`Spotify export/spotify_export.py`, que extrai as músicas direto de
uma playlist do Spotify e já copia o resultado para `playlist.txt`
automaticamente.

## 7. Formato do `playlist_cache.json`

Mapa de "nome da música" → URL do YouTube, para evitar buscar de novo
a cada Sync:

```json
{
    "50 Cent - Window Shopper": {
        "id": "bFLow5StvvU",
        "url": "https://youtube.com/watch?v=bFLow5StvvU"
    }
}
```

Músicas sem URL no cache são buscadas automaticamente no YouTube Music
durante o Sync — a URL encontrada é salva no cache para uso futuro.
Você também pode pré-preencher esse arquivo usando um exportador como
o TuneMyMusic (tunemymusic.com).

## 8. Logs

Todos os logs ficam em `NomeDoPerfil\Logs\`:

- `sync.log` — operações gerais (INFO): syncs, downloads, remoções
- `DEBUG.log` — tudo detalhado, cada passo de cada função
- `crash.log` — erros fatais que travaram o programa
- `historico.json` — últimos 30 syncs, com data, sucessos e falhas
- `falhas.json` — músicas que falharam no último Sync (para retry)

## 9. Possíveis erros

**Download falhando**
- Cookie expirado → exporte novo `cookies.txt`
- `yt-dlp` desatualizado → `pip install -U yt-dlp`
- Rate limit → aguarde alguns minutos e tente de novo

**FFmpeg não encontrado**
- PATH não configurado corretamente → refaça a instalação

**Node.js não encontrado**
- Necessário para o `yt-dlp` funcionar → instale em nodejs.org e
  reinicie o Prompt

**Execução duplicada (`.lock`)**
- O sistema usa um arquivo `.lock` para evitar dois syncs simultâneos.
  Se o programa travou abruptamente, apague o `.lock` da pasta do
  perfil.

**`sync_state.json` inconsistente**
- Opção 9 (Registrar MP3s do Disco) para consolidar
- Opção 5 (Limpar Registros) para remover entradas sem arquivo

## 10. Fluxo recomendado

**Primeira vez com um perfil novo**
1. Criar a pasta do perfil dentro de `Download Musicas\`
2. Colocar `playlist.txt` (e `playlist_cache.json`, se tiver)
3. Colocar `cookies.txt`
4. Abrir o `.bat` do perfil
5. Opção 1 — Sincronizar

**Manutenção regular**
1. Atualizar `playlist.txt` com músicas novas ou remover as que não quer
2. Opção 1 — Sincronizar (baixa as novas, remove as que saíram, busca
   URL automaticamente para músicas novas sem cache)
3. Opção 4 — Verificar Biblioteca para confirmar que está tudo ok

**Após apagar arquivos manualmente**
1. Opção 5 — Limpar Registros
2. Opção 1 — Sincronizar para rebaixar

**Ao migrar de máquina / pasta**
1. Copie toda a pasta `Download Musicas\` para o novo local
2. Instale Python, `yt-dlp`, FFmpeg e Node.js
3. Abra o `.bat` — tudo já está registrado no `sync_state.json`, e o
   script se adapta sozinho ao novo caminho (`ROOT_DIR` vem de onde o
   `.bat` está, via `SOUNDVAULT_ROOT_DIR`)
