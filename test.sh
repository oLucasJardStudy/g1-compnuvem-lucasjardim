#!/usr/bin/env bash
# test.sh - verifica envio, replicação, ausência de duplicatas e (opcional) persistência.
# Uso: ./test.sh                 testes básicos
#      ./test.sh --persistencia  inclui recriação dos containers
# Não usa "set -e" de propósito: cada falha é contada e o resumo aparece no final.
set -u
cd "$(dirname "$0")"

PORTS=(5001 5002 5003)
FALHAS=0
MSGS=()

ok()    { echo "  [OK]    $1"; }
falha() { echo "  [FALHA] $1"; FALHAS=$((FALHAS + 1)); }

esperar_servicos() {
  echo "Aguardando os serviços responderem..."
  for porta in "${PORTS[@]}"; do
    for _ in $(seq 1 30); do
      curl -fsS -o /dev/null "http://localhost:$porta/messages" 2>/dev/null && continue 2
      sleep 1
    done
    echo "Serviço da porta $porta não respondeu em 30s"
    exit 1
  done
}

# quantas vezes a mensagem aparece na instância da porta $1
contar() {
  curl -sS "http://localhost:$1/messages" | grep -o "\"message\":\"$2\"" | wc -l
}

verificar_em_todas() {   # $1 = mensagem
  for destino in "${PORTS[@]}"; do
    n=$(contar "$destino" "$1")
    if [ "$n" -eq 1 ]; then
      ok "porta $destino tem '$1' exatamente 1 vez"
    else
      falha "porta $destino tem '$1' $n vezes (esperado: 1)"
    fi
  done
}

esperar_servicos

echo
echo "1) Entrada inválida deve retornar 400"
codigo=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" -d '{"x":1}' http://localhost:5001/send)
if [ "$codigo" = "400" ]; then ok "JSON inválido -> 400"; else falha "esperado 400, recebido $codigo"; fi

echo
echo "2) Enviar por cada instância e conferir a replicação nas três"
for origem in "${PORTS[@]}"; do
  MSG="teste-$(date +%s)-$RANDOM-p$origem"
  resp=$(curl -sS -X POST -H "Content-Type: application/json" \
    -d "{\"message\":\"$MSG\"}" "http://localhost:$origem/send")
  n_ok=$(echo "$resp" | grep -o '"ok"' | wc -l)
  if [ "$n_ok" -eq 2 ]; then
    ok "POST na porta $origem replicou para os 2 peers"
  else
    falha "POST na porta $origem: replicação incompleta -> $resp"
  fi
  verificar_em_todas "$MSG"
  MSGS+=("$MSG")
done

if [ "${1:-}" = "--persistencia" ]; then
  echo
  echo "3) Persistência: recriar os containers e reconferir"
  docker compose down >/dev/null 2>&1
  docker compose up -d >/dev/null 2>&1
  esperar_servicos
  for MSG in "${MSGS[@]}"; do verificar_em_todas "$MSG"; done
fi

echo
if [ "$FALHAS" -eq 0 ]; then
  echo "RESULTADO: todos os testes passaram."
  exit 0
else
  echo "RESULTADO: $FALHAS verificação(ões) falharam."
  exit 1
fi
