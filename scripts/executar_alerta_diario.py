#!/usr/bin/env python3
"""
Execução diária do alerta de concursos.
Este script é chamado pelo agendamento automático do Manus (schedule).
Fluxo:
  1. Executa a coleta completa de concursos de todas as fontes
  2. Filtra apenas concursos NOVOS (não alertados anteriormente)
  3. Gera o email HTML com o template atual
  4. Envia via SMTP com auditoria pós-envio e autocorreção automática
  5. Registra o log de envio
"""
from __future__ import annotations
import json
import logging
import os
import sys
import warnings
from datetime import date

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("alerta_diario")

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPTS_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_DIR, ".env"))
except Exception:
    pass

SEEN_PATH           = os.path.join(_PROJECT_DIR, "data", "concursos_seen.json")
EMAIL_PENDENTE_PATH = os.path.join(_PROJECT_DIR, "data", "email_pendente.json")
RECIPIENT           = os.getenv("MONITOR_RECIPIENT", "huddsonviana@gmail.com")


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_json(data, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _ja_enviou_hoje(log_path: str) -> bool:
    """Retorna True se já enviou email com sucesso hoje (evita duplicatas em retries do Render)."""
    if not os.path.exists(log_path):
        return False
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
        hoje = date.today().isoformat()
        for entry in reversed(log[-10:]):
            if entry.get("sucesso") and str(entry.get("data", "")).startswith(hoje):
                return True
    except Exception:
        pass
    return False


def main() -> int:
    today = date.today()
    logger.info(f"=== Alerta diário de concursos — {today.strftime('%d/%m/%Y')} ===")

    # ── 0. Idempotência: abortar se já enviou hoje ───────────────────
    _LOG_PATH = os.path.join(_PROJECT_DIR, "data", "envio_log.json")
    if _ja_enviou_hoje(_LOG_PATH):
        logger.info("Email já enviado com sucesso hoje. Execução duplicada ignorada.")
        return 0

    # ── 1. Importar módulos ────────────────────────────────────────
    try:
        from monitor_concursos import (
            buscar_concursos,
            filtrar_novos_concursos,
            formatar_email_html,
            formatar_email_concursos,
        )
    except ImportError as e:
        logger.error(f"Erro ao importar monitor_concursos: {e}")
        return 1

    # ── 2. Carregar seen atual ─────────────────────────────────────
    seen_atual = _load_json(SEEN_PATH)
    logger.info(f"Seen atual: {len(seen_atual)} concursos já alertados")

    # ── 3. Coleta completa ─────────────────────────────────────────
    logger.info("Iniciando coleta de todas as fontes...")
    try:
        concursos, erros = buscar_concursos(
            enriquecer_detalhes=True,
            max_enriquecimento=60,
        )
    except Exception as e:
        logger.error(f"Erro na coleta: {e}")
        concursos, erros = [], [str(e)]

    logger.info(f"Concursos elegíveis encontrados: {len(concursos)}")
    if erros:
        logger.warning(f"Erros de coleta ({len(erros)}): {erros[:3]}")

    # ── 4. Filtrar apenas NOVOS ────────────────────────────────────
    novos, seen_novo = filtrar_novos_concursos(concursos, seen_atual)
    logger.info(f"Concursos NOVOS (não alertados antes): {len(novos)}")

    # ── 5. Gerar email ─────────────────────────────────────────────
    corpo_html  = formatar_email_html(novos, erros)
    corpo_texto = formatar_email_concursos(novos, erros)
    logger.info(f"HTML gerado: {len(corpo_html):,} chars")

    # ── 6. Salvar email_pendente.json ──────────────────────────────
    assunto = (
        f"[Concursos] 🎯 {len(novos)} concurso(s) — "
        f"Alerta {today.strftime('%d/%m/%Y')}"
    )
    payload = {
        "subject":    assunto,
        "body":       corpo_html,
        "recipient":  RECIPIENT,
        "data":       today.isoformat(),
        "total":      len(novos),
    }
    _save_json(payload, EMAIL_PENDENTE_PATH)
    logger.info(f"Payload salvo: {EMAIL_PENDENTE_PATH}")

    # ── 7. Atualizar seen ──────────────────────────────────────────
    seen_final = {**seen_atual, **seen_novo}
    _save_json(seen_final, SEEN_PATH)
    logger.info(f"Seen atualizado: {len(seen_final)} concursos")

    # ── 8. Enviar via SMTP ─────────────────────────────────────────
    try:
        from enviar_concursos import main as enviar_main
        logger.info("Iniciando envio via SMTP...")
        resultado = enviar_main()
        if resultado == 0:
            logger.info("Email enviado e auditado com sucesso.")
        else:
            logger.warning("Envio concluído com advertências — verificar log de envio.")
    except Exception as e:
        logger.error(f"Erro no envio: {e}")
        return 1

    # ── 9. Imprimir resumo texto ───────────────────────────────────
    print(corpo_texto)

    return 0


if __name__ == "__main__":
    sys.exit(main())
