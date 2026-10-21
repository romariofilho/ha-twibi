# Intelbras Twibi — integração local para Home Assistant

Controle **local** (sem nuvem, sem o app) do sistema mesh **Intelbras Twibi Giga**
(família Tenda Nova). Feita por engenharia reversa do app *Wi-Fi Control Home* 1.0.7.3:
o Twibi fala um protocolo próprio em **TCP 9000** (header de 16 bytes + protobuf, sem
criptografia na LAN). Todos os esquemas protobuf do app foram extraídos para
`custom_components/twibi/lib/schema.py` (199 mensagens), então novas funções do app
podem ser portadas sem novo trabalho de decodificação.

Testado em: Twibi Giga, firmware 1.1.9, 2 nós, Home Assistant 2026.10.2.

## Instalação

**Via HACS:** *HACS → ⋮ → Repositórios personalizados* → `https://github.com/romariofilho/ha-twibi`, categoria **Integração** → baixar → reiniciar o HA.

**Manual:**
1. Copie `custom_components/twibi` para `/config/custom_components/twibi`
2. Reinicie o HA.
3. *Configurações → Dispositivos e serviços → Adicionar integração → Intelbras Twibi*.
   - **IP**: o Twibi principal (gateway da rede, ex. `10.1.1.1`).
   - **Senha**: a *senha de login* do app (a mesma pedida ao abrir o app na rede local).

## O que aparece no HA

Um dispositivo por nó do mesh (ex.: *Twibi Sala* = principal, *Twibi Cozinha*).

| Entidade | O que é |
|---|---|
| `binary_sensor` *Internet* / *Cabo de internet* | WAN com IP / porta WAN com link |
| `binary_sensor` *Online* (por nó) | nó do mesh no ar (atributos: principal, firmware, MAC) |
| `sensor` *Aparelhos conectados* | total de clientes online |
| `sensor` *Upload* / *Download* | tráfego atual da WAN (o Twibi informa em KB/s; exibido em Mbit/s) |
| `sensor` *IP da internet (WAN)*, *Gateway/DNS/IPv6 da WAN* | diagnóstico (alguns desativados por padrão) |
| `sensor` *IPs reservados* | quantas reservas DHCP existem |
| `sensor` *Reinício automático* | horário da "manutenção automática" (ou `desligado`) |
| `sensor` *Aparelhos neste nó* (por nó) | clientes associados àquele nó |
| `sensor` *Sinal do link mesh* (por nó satélite) | RSSI do backhaul até o nó principal |
| `sensor` *Ligado desde* (por nó) | último boot do nó |
| `switch` *Wi-Fi de convidados* | liga/desliga a rede de convidados (mantém SSID/senha/limite de tempo) |
| `switch` *LED* (por nó) | LED de status |
| `switch` *Reinício automático diário* | manutenção automática do app |
| `switch` *Roaming rápido (reinicia o Wi-Fi)* | o mesh leva cada aparelho para o nó mais perto; sem ele o aparelho fica preso no nó em que conectou. **Mudar reinicia o Wi-Fi (~60 s)** |
| `switch` *Acesso à rede: <aparelho>* | **desativados por padrão**; desligar = lista negra do Twibi |
| `device_tracker` por aparelho | casa/fora pelo Twibi; atributos: nó, sinal, 2.4/5 GHz/cabo, IP reservado, bloqueado |

Rastreadores ficam **ativos** para aparelhos que o HA já conhece pelo MAC (Sonoff, TVs, etc.)
e para celulares/relógios/tablets (MAC aleatório ou nome típico); o resto vem desativado.
Celulares Android usam MAC aleatório e podem aparecer com mais de um MAC — para presença,
o app do HA no celular continua sendo melhor.

## Serviços

| Serviço | Campos | Observação |
|---|---|---|
| `twibi.reserve_ip` | `mac`, `ip` | **o Twibi reinicia o Wi-Fi (~30 s)**; aparelho precisa estar online |
| `twibi.remove_reservation` | `mac` | idem |
| `twibi.rename_device` | `mac`, `name` | apelido no app; não reinicia nada |
| `twibi.rename_devices` | `names: {MAC: nome}` | vários de uma vez (útil após reset de fábrica) |
| `twibi.block_device` / `twibi.unblock_device` | `mac` | lista negra do Twibi |
| `twibi.list_devices` | — | devolve (response) todos os aparelhos: IP, MAC, apelido, reserva, bloqueio, nó |

## Avisos

- **O relógio do Twibi não acerta a hora pela internet** (fw 1.1.9): ele conta a partir de 01/05/2011 00:00 desde que liga. A "manutenção automática às 03:00" na prática é "3 h depois de ligar, e a cada 24 h" — e com `delay` ligado ela espera a rede ficar ociosa, então pode nem acontecer.
- **Reserva de IP e Roaming rápido reiniciam o Wi-Fi do Twibi** (~30–60 s). Se o próprio HA estiver no Wi-Fi, ele cai junto
  (o HAOS às vezes não reconecta sozinho — veja o "vigia do Wi-Fi" no repositório pai).
- O comando de **reset de fábrica (0x0102) é bloqueado** na biblioteca de propósito.
- A senha de login fica salva na entrada da integração (e portanto nos backups do HA).

## Status dos testes (2026-10-17)

| Função | Testado no Twibi real? |
|---|---|
| Todas as leituras (nós, aparelhos, apelidos, WAN, Wi-Fi, convidados, lista negra, manutenção) | ✅ |
| Apelidos (individual e em lote) | ✅ |
| Reserva de IP (via serviço, com queda/volta do Wi-Fi) | ✅ |
| LED dos nós | ✅ |
| Wi-Fi de convidados liga/desliga | ✅ (não reinicia o Wi-Fi principal) |
| Reinício automático liga/desliga | ✅ |
| Roaming rápido | ✅ ligado em 2026-10-20 (Wi-Fi caiu ~60 s e voltou) |
| Bloquear/desbloquear aparelho | ✅ entra/sai da lista negra; em 2026-10-20 bloquear a TV Quarto por ~12 s fez ela reconectar (e trocar de nó) — não reinicia o Wi-Fi |
| Reiniciar sistema | ❌ **não suportado** pelo Twibi Giga fw 1.1.9: o comando 0x0103 é ignorado (não está no `supt_mod_flag`) e nem o app oferece. Botão removido em 2026-10-18. A manutenção agendada também não serve de atalho (agendar para daqui a 2 min não reiniciou) |

## Desenvolvimento

```bash
python3 -m unittest discover -s tests -v      # 15 testes, sem HA, usando respostas gravadas
TWIBI_HOST=10.1.1.1 TWIBI_PASSWORD=... python3 tests/dump_fixtures.py   # regrava as fixtures (anonimize antes de commitar!)
```

`lib/` não depende do HA (só asyncio). Para portar uma nova função do app:
descompile o app (jadx) e procure o método em `.../network/net/socket/RequestManager.java` (reqType + mensagem),
o esquema da mensagem já está em `lib/schema.py`, e use `TwibiClient.request()` /
`TwibiClient.command()`. Códigos `PROTOBUFxxyy` do app = reqType `0x{xx em hex}{yy}`,
ex. `PROTOBUF1704` → `0x1104`.

## Aviso

Projeto independente, **não afiliado nem endossado pela Intelbras ou Tenda**. Nome e marcas pertencem aos seus donos. Feito por interoperabilidade, para uso na própria rede; use por sua conta e risco (reservas de IP reiniciam o Wi-Fi do roteador).

## Licença

MIT — veja [LICENSE](LICENSE).
