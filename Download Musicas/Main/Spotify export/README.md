# Spotify Export

Extrai as músicas de uma playlist do Spotify e gera o `playlist.txt` que o
SoundVault usa pra baixar (o Sync sempre lê a partir desse arquivo — o
Spotify export só existe pra você não ter que digitar a lista à mão).

## Requisitos

```
pip install spotapi
```

Isso habilita o caminho rápido (sem browser). O `.bat` também tenta
instalar sozinho na primeira vez, mas se der algum problema (rede,
permissão, etc.) rode o comando acima manualmente antes.

Se não instalar (ou a instalação falhar), o script cai automaticamente
pro fallback via Playwright — que baixa o Chromium sozinho na primeira
vez, sem precisar rodar nada manualmente.

## Como usar

1. Dê duplo clique em `spotify_export.bat`.
2. Cole o **link da playlist do Spotify** quando ele pedir. Pra pegar o
   link: abra a playlist no Spotify (app ou site) → botão **"..."** →
   **Compartilhar** → **Copiar link da playlist**.
   Exemplo de link válido:
   ```
   https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
   ```
3. Digite o **nome da playlist de destino** no SoundVault (a pasta dentro
   de `playlists\` que vai receber essa lista — é a mesma que aparece nas
   opções "Sincronizar", "Verificar Biblioteca" etc. do menu principal).
   Se você deixar em branco:
   - e essa playlist do Spotify **já foi importada antes**, ele detecta
     sozinho qual nome usar e atualiza ela — não precisa lembrar o nome;
   - senão, e só existir uma playlist criada, usa essa automaticamente;
   - senão, lista as existentes pra você escolher o nome certo.
4. Espere a extração terminar. No final ele já copia o resultado pra
   `playlists\<Nome>\playlist.txt` sozinho (a versão anterior, se existia,
   fica guardada com backup por data/hora — nada se perde).
5. Abra o `play.bat` do perfil → opção **1 (Sincronizar)** → escolha essa
   playlist pra começar a baixar.

## Reimportando uma playlist (atualizar)

Rodar de novo com o **mesmo link** do Spotify atualiza a playlist local
automaticamente — não cria uma pasta nova. Isso é rastreado por um
arquivo `spotify_source.json` dentro de cada `playlists\<Nome>\`, que
guarda de qual playlist do Spotify aquela pasta veio.

Duas proteções em cima disso, pra evitar erro/duplicata/sobrescrita sem
querer:

- **Mesmo link, nome diferente do usado da última vez** → avisa que vai
  criar uma segunda cópia da mesma playlist do Spotify (duplicata) e
  pede confirmação antes de continuar.
- **Nome já usado, mas veio de um link diferente do Spotify** → avisa que
  vai substituir o conteúdo de uma playlist não relacionada, e exige
  digitar o nome de novo pra confirmar (não basta um "sim").

## Como a extração funciona por baixo dos panos

O script tenta dois métodos, nessa ordem:

1. **SpotAPI** (rápido, ~segundos, não abre browser nenhum) — usa os
   mesmos endpoints internos que `open.spotify.com` usa, com um token
   anônimo. Funciona pra qualquer playlist que você tenha o link, mesmo
   que ela não esteja marcada como "pública" no seu perfil.
2. **Fallback via browser** (Playwright) — só entra em ação se o SpotAPI
   não estiver instalado, falhar, ou a playlist realmente exigir login
   (compartilhamento restrito de verdade). Nesse caso abre um Chromium de
   verdade e pede pra você logar no Spotify (a sessão fica salva, só
   precisa logar na primeira vez — 2FA/código por e-mail incluso se a sua
   conta usar).

Você não precisa escolher qual usar — o `.bat` já tenta instalar o SpotAPI
sozinho (opcional, silencioso) e cai pro Playwright automaticamente se
precisar.

## Rodando direto pela linha de comando (avançado)

Também dá pra pular os prompts passando os argumentos direto — útil pra
automatizar:

```
spotify_export.bat "https://open.spotify.com/playlist/..." "NomeDaPlaylist"
```

## Problemas comuns

- **"ERRO: playlist nao encontrada. Verifique o link."** — o link colado
  não é de uma playlist (é de um álbum, artista, etc.), ou está incompleto.
- **Extração incompleta / abortada** — o script se recusa a sobrescrever
  o `playlist.txt` existente se capturar menos de 90% das músicas
  esperadas, pra nunca trocar uma lista boa por uma incompleta. Rode de
  novo — geralmente resolve.
- **Pede login toda vez** — normal apenas na primeira vez (via Playwright);
  da segunda em diante a sessão fica salva em
  `Spotify export\.spotify_session\`. Se voltar a pedir login toda vez,
  essa pasta pode ter sido apagada ou corrompida.
- **Log detalhado**: qualquer erro fica registrado em
  `spotify_export_debug.log`, nesta mesma pasta.
