---
repo: architecture
path: docs/architecture/aw-app-home-assistant.md
source: generated
edited: false
checksum: sha256:09411318e929f917332723c49469cd84729d443ba4d024129c6d775ad0f940bd
---
# Home Assistant

- **repo**: aw-app-home-assistant
- **layer**: app-container
- **technologies**: docker
- **health** (derived): planned

Runs Home Assistant in your workspace — control lights, speakers, Alexa/Echo devices and sensors, read the state of your home, and let agents do the same. Opens as a window in the Apps grid, keeps its whole configuration and history on the workspace disk, and comes with the Amazon Alexa integration preinstalled.

## Connections
- `stdio-mcp` → **mcp-gateway** — MCP surface aggregated by the gateway

## MCP tools
- `GetLiveContext`
- `HassBroadcast`
- `HassMediaPause`
- `HassMediaSearchAndPlay`
- `HassMediaUnpause`
- `HassSetVolume`
- `HassTurnOff`
- `HassTurnOn`

## Requirements
### Nas versões que migraram, a config vale é a de .storage/http, não a do YAML
- Given o Home Assistant chega por proxy reverso, de um IP que ele nunca viu, e sem use_x_forwarded_for com trusted_proxies correspondente responde 400 a tudo
- When a correção é aplicada no arquivo que o servidor rodando de fato lê (repos/aw-app-home-assistant/container/ensure_proxy_config.py::ensure_storage:155, sobre STORAGE_REL=".storage/http":140)
- Then os ranges privados faltantes entram em trusted_proxies preservando os que já existiam, use_x_forwarded_for vira true, e o retorno None significa que aquele HA não usa storage e é YAML puro — editar configuration.yaml numa versão já migrada não tem efeito nenhum: a edição fica lá, parece certa, e o 400 continua, que é o erro mais caro deste app por parecer problema de rede
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-home-assistant/tests/test_proxy_config.py` (passing)

### O bloco YAML gerido é removido depois que o storage assume, e o escrito à mão é poupado
- Given um HA que já lê .storage/http mas ainda tem um bloco http: no configuration.yaml
- When a limpeza roda depois da passada de storage (repos/aw-app-home-assistant/container/ensure_proxy_config.py::strip_managed_yaml_block:246)
- Then só o bloco marcado como NOSSO é removido, e um bloco http: escrito à mão é deixado intacto com um aviso impresso — deixar o nosso faz o HA levantar yaml_still_present_after_migration, e apagar o de outra pessoa seria destruir configuração que este app não escreveu. O marcador de comentário é o que separa os dois casos, e é por isso que ele existe
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-home-assistant/tests/test_proxy_config.py` (passing)

### Reescrever a config muitas vezes não acumula nada
- Given este script roda no entrypoint do container, ou seja, a cada boot e a cada recriação
- When a mesma operação é repetida sobre uma config já corrigida (repos/aw-app-home-assistant/container/ensure_proxy_config.py::ensure:278 e ensure_storage:155)
- Then nada é duplicado nem no YAML nem no storage, e IPs nus são normalizados para forma de rede antes da comparação (tests/test_proxy_config.py::test_bare_ips_are_normalised_so_they_are_not_re_added_forever:208) — sem essa normalização "10.0.0.1" e "10.0.0.1/32" nunca se reconhecem, e cada boot acrescenta a mesma entrada de novo, fazendo a lista crescer para sempre. Idempotência aqui não é elegância, é a diferença entre um arquivo estável e um que incha até alguém notar
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-home-assistant/tests/test_proxy_config.py` (passing)

### O que já estava configurado é preservado, e chaves alheias ao http não são tocadas
- Given uma instalação existente que já tinha seus próprios trusted_proxies e outras chaves sob http:
- When o bloco é dividido entre entradas de proxy e o resto antes de ser reescrito (repos/aw-app-home-assistant/container/ensure_proxy_config.py::_split_http_block:110, com _MANAGED_KEYS:107)
- Then os proxies da pessoa continuam na lista junto com os ranges privados adicionados, chaves não relacionadas sob http: sobrevivem, e um use_x_forwarded_for desligado é corrigido — só três chaves são declaradas como geridas por este script, e essa lista curta é o contrato: tudo fora dela pertence a quem configurou, e reescrever o bloco inteiro apagaria um ssl_certificate ou um server_port sem nunca mencionar isso
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-home-assistant/tests/test_proxy_config.py` (passing)

### Uma tentativa de migração que falhou é descartada em vez de tomada como verdade
- Given o arquivo .storage/http pode conter tanto a configuração estável quanto uma tentativa pendente que não completou
- When o documento é lido e a parte estável é isolada (repos/aw-app-home-assistant/container/ensure_proxy_config.py::ensure_storage:155, verificado por tests/test_proxy_config.py::test_a_failed_pending_trial_is_dropped:193)
- Then a tentativa pendente falha é descartada e a correção é aplicada sobre a configuração estável, e um volume novo em folha recebe uma config completa — ler o estado pendente como se fosse o vigente aplicaria a correção em cima de algo que o próprio HA vai jogar fora, produzindo o cenário mais confuso possível: o arquivo mostra a configuração certa e o servidor segue respondendo 400
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-home-assistant/tests/test_proxy_config.py` (passing)
