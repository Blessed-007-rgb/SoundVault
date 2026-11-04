# Spotify Export

Extrai as músicas de uma playlist do Spotify e gera o `playlist.txt` que o
SoundVault usa pra baixar (o Sync sempre lê a partir desse arquivo — o
Spotify export só existe pra você não ter que digitar a lista à mão).

## Requisitos

```
pip install spotapi
```

O `.bat` instala sozinho na primeira vez, mas se der algum problema
(rede, permissão, etc.) rode o comando acima manualmente. Sem o
`spotapi` o export não funciona (o `python -m soundvault --doctor` avisa).

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

A extração usa o **SpotAPI** (rápido, leva segundos, não abre browser
nenhum e não pede login): ele usa os mesmos endpoints internos que
`open.spotify.com` usa, com um token anônimo. Funciona pra qualquer
playlist que você tenha o link, mesmo que ela não esteja marcada como
"pública" no seu perfil.

**Limitação:** playlists de compartilhamento restrito de verdade (que
não abrem pelo link sem estar logado) não são suportadas. Nesse caso o
script avisa e **não altera nada**. Antes existia um modo alternativo por
navegador (Playwright), que foi removido por ser lento e frágil.

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
- **"o SpotAPI não conseguiu ler a playlist"** — o link não é de uma
  playlist, a playlist é de compartilhamento restrito, ou o Spotify mudou
  a API (nesse caso `pip install -U spotapi` costuma resolver).
- **Sobrou a pasta `.spotify_session\`** — era a sessão salva do antigo
  modo por navegador. Não é mais usada e pode ser apagada (ela guarda um
  perfil do Chromium com a sua sessão logada no Spotify).
- **Log detalhado**: qualquer erro fica registrado em
  `spotify_export_debug.log`, nesta mesma pasta.
