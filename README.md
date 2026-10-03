# Sistema de mensagens distribuído

Avaliação de Grau 1 · Computação em Nuvem · <seu nome> · <turma>

Três containers Docker rodam o mesmo serviço REST em Python (Flask). Cada um guarda as mensagens que recebe e replica uma cópia para os outros dois. Os dados ficam em um volume compartilhado.

## Estrutura

```text
avaliacao/
├── app/
│   ├── app.py             # serviço REST e replicação
│   ├── requirements.txt   # dependências com versões fixas
│   ├── Dockerfile         # imagem da aplicação
│   └── .dockerignore
├── docker-compose.yml     # app1, app2, app3, rede e volume
├── test.sh                # testes automatizados
└── README.md
```

## Requisitos

- Docker Engine com o plugin Compose v2 (comando `docker compose`; no Compose v1 o equivalente é `docker-compose`)
- `curl` e `bash` para o script de testes

## Como executar

```bash
docker compose up -d --build   # constrói a imagem e sobe os 3 containers
docker compose ps              # aguarde o status (healthy)
./test.sh                      # roda os testes
docker compose down            # para tudo e mantém os dados
```

`docker compose down -v` também apaga o volume e, portanto, todas as mensagens.

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| POST | `/send` | Recebe `{"message": "texto"}`, grava e replica para os outros containers |
| GET | `/messages` | Retorna todas as mensagens guardadas pela instância |

Instâncias: `app1` → `localhost:5001`, `app2` → `localhost:5002`, `app3` → `localhost:5003`.

```bash
curl -X POST -H "Content-Type: application/json" -d '{"message":"hello"}' http://localhost:5001/send
# {"armazenada_em":"app1","id":"...","replicacao":{"app2":"ok","app3":"ok"}}

curl http://localhost:5002/messages
# {"count":1,"instance":"app2","messages":[{"id":"...","message":"hello","origin":"app1","timestamp":"..."}]}
```

Um JSON sem o campo `message` retorna HTTP 400.

## Decisões de projeto

- **Replicação síncrona por HTTP.** Ao receber uma mensagem de um cliente, a instância grava e envia uma cópia (`requests`) para os outros dois containers usando o nome do serviço (`http://app2:5000`). A porta usada é a interna (5000); as portas 5001 a 5003 existem só para acesso do host.
- **Sem loop de replicação.** A cópia enviada leva o cabeçalho `X-Replicated: true`. Quem a recebe só grava e não replica de novo. Cada mensagem tem um `id` (UUID), e uma cópia repetida é ignorada.
- **Um arquivo por instância no volume.** Cada container grava em `messages_<instância>.jsonl` (uma mensagem JSON por linha) e em `<instância>.log`, todos no volume `msgdata`, montado em `/data`. Assim, a replicação pode ser verificada: se o app2 tem uma mensagem que entrou no app1, ela foi replicada. Dentro do container, `flock` evita escritas simultâneas misturadas.
- **Mesma imagem, três serviços.** O compose usa uma âncora YAML (`x-app-base`) com a configuração comum. Cada serviço muda só `INSTANCE_NAME`, `PEERS` e a porta.
- **Rede bridge própria (`msgnet`).** Em redes definidas pelo usuário o Docker resolve os nomes dos serviços por DNS, o que a replicação usa.
- **Falha de um peer não derruba a requisição.** O envio usa timeout de 2 s, e o erro vai para o log e para a resposta (`"app3":"erro: ConnectionError"`).

## Boas práticas de Docker adotadas

- Imagem `python:3.12-slim` com apenas três dependências diretas e versões fixas (`pip freeze`), instaladas com `--no-cache-dir`.
- `requirements.txt` copiado antes do código, para reaproveitar o cache de camadas.
- Aplicação roda como usuário sem privilégios (`appuser`, uid 1000), com servidor `gunicorn` em vez do servidor de desenvolvimento do Flask.
- `HEALTHCHECK` no Dockerfile e `restart: unless-stopped` no compose.
- `.dockerignore` mantém arquivos desnecessários fora do contexto de build.
- Volume nomeado para os dados; os containers são descartáveis.

## Testes

`./test.sh` espera os serviços subirem e verifica: (1) entrada inválida retorna 400; (2) uma mensagem enviada por cada instância aparece **exatamente uma vez** nas três (detecta perda, duplicação e loop). Use `./test.sh --persistencia` para recriar os containers e confirmar que os dados continuam lá. O script termina com código 0 se tudo passar e 1 se algo falhar.

## Limitações conhecidas

- **Sem reenvio:** se um peer estiver fora do ar durante um POST, ele não recebe aquela mensagem depois. A consistência entre instâncias é eventual e não garantida. Uma melhoria seria uma fila com novas tentativas.
- **Cabeçalho forjável:** qualquer cliente pode enviar `X-Replicated`. Em produção, a replicação usaria um canal interno autenticado.
- **Sem ordem global:** instâncias diferentes podem listar mensagens em ordens diferentes.
- **Um único host:** o volume é local, então não há alta disponibilidade real.
