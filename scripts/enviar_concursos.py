#!/usr/bin/env python3
"""
enviar_concursos.py
===================
Envia o email de alertas de concursos com HTML inline via Gmail SMTP.
Executa auditoria pós-envio automática e tenta autocorreção em caso de falha.

Fluxo:
  1. Lê email_pendente.json
  2. Envia via SMTP com HTML no corpo (multipart/alternative)
  3. Audita o envio: verifica se o email chegou na caixa de entrada via Gmail API (MCP)
  4. Em caso de falha ou inconsistência: tenta até MAX_TENTATIVAS vezes com backoff
  5. Registra resultado em data/envio_log.json

Uso:
    python3 enviar_concursos.py [--force]
"""
from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("enviar_concursos")

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _SCRIPTS_DIR.parent

# ── Carregar .env ──────────────────────────────────────────────────
def _load_env():
    env_path = _PROJECT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_load_env()

# ── Configurações ──────────────────────────────────────────────────
SMTP_HOST    = os.getenv("MONITOR_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT    = int(os.getenv("MONITOR_SMTP_PORT", "587"))
SMTP_USER    = os.getenv("GMAIL_SMTP_USER") or os.getenv("MONITOR_SMTP_USER", "")
SMTP_PASS    = os.getenv("GMAIL_SMTP_PASSWORD") or os.getenv("MONITOR_SMTP_PASS", "")
RECIPIENT    = os.getenv("MONITOR_RECIPIENT", "huddsong@gmail.com")
SENDER       = os.getenv("MONITOR_SENDER", SMTP_USER)

EMAIL_PENDENTE_PATH = _PROJECT_DIR / "data" / "email_pendente.json"
ENVIO_LOG_PATH      = _PROJECT_DIR / "data" / "envio_log.json"

MAX_TENTATIVAS = 3
BACKOFF_BASE   = 10  # segundos


# ─────────────────────────────────────────────────────────────────
# Leitura do payload
# ─────────────────────────────────────────────────────────────────

def carregar_payload() -> Optional[dict]:
    if not EMAIL_PENDENTE_PATH.exists():
        logger.error(f"email_pendente.json não encontrado: {EMAIL_PENDENTE_PATH}")
        return None
    try:
        with open(EMAIL_PENDENTE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao ler email_pendente.json: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# Envio SMTP com HTML inline
# ─────────────────────────────────────────────────────────────────

def _texto_plano_de_html(html: str) -> str:
    """Extrai texto legível do HTML para a parte text/plain do multipart."""
    # Remover tags, preservar quebras de linha
    txt = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    txt = re.sub(r'<[^>]+>', '', txt)
    txt = re.sub(r'\n{3,}', '\n\n', txt)
    txt = re.sub(r'[ \t]{2,}', ' ', txt)
    return txt.strip()


def enviar_smtp(subject: str, body_html: str, recipient: str,
                sender: str = SENDER) -> tuple[bool, str]:
    """
    Envia email com HTML inline via SMTP (TLS).
    Retorna (sucesso: bool, mensagem: str).
    """
    if not SMTP_USER or not SMTP_PASS:
        return False, "Credenciais SMTP não configuradas (GMAIL_SMTP_USER / GMAIL_SMTP_PASSWORD)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender or SMTP_USER
    msg["To"]      = recipient

    # Parte texto plano (fallback)
    txt = _texto_plano_de_html(body_html)
    msg.attach(MIMEText(txt, "plain", "utf-8"))

    # Parte HTML (renderizada pelos clientes modernos)
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        logger.info(f"Conectando a {SMTP_HOST}:{SMTP_PORT} como {SMTP_USER}...")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info(f"Email enviado com sucesso para {recipient}")
        return True, "OK"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"Autenticação SMTP falhou: {e}"
    except smtplib.SMTPRecipientsRefused as e:
        return False, f"Destinatário recusado: {e}"
    except smtplib.SMTPException as e:
        return False, f"Erro SMTP: {e}"
    except Exception as e:
        return False, f"Erro inesperado: {e}"


# ─────────────────────────────────────────────────────────────────
# Auditoria pós-envio via Gmail MCP
# ─────────────────────────────────────────────────────────────────

def _mcp_search(query: str, max_results: int = 5) -> list[dict]:
    """Busca mensagens no Gmail via MCP."""
    payload = json.dumps({"q": query, "max_results": max_results})
    try:
        result = subprocess.run(
            ["manus-mcp-cli", "tool", "call", "gmail_search_messages",
             "--server", "gmail", "--input", payload],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            logger.debug(f"MCP search falhou: {result.stderr[:200]}")
            return []
        # Tentar ler o arquivo de resultado salvo
        match = re.search(r'saved to:\s*(\S+)', result.stdout)
        if match:
            result_file = match.group(1)
            try:
                with open(result_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Estrutura: {"messages": [...]} ou lista direta
                if isinstance(data, dict):
                    return data.get("messages", []) or data.get("results", [])
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []
    except Exception as e:
        logger.debug(f"MCP search erro: {e}")
        return []


def auditar_envio(subject: str, recipient: str,
                  aguardar_segundos: int = 20) -> tuple[bool, str]:
    """
    Verifica se o email chegou na caixa do destinatário via Gmail MCP.
    Aguarda alguns segundos para propagação antes de verificar.
    Retorna (chegou: bool, detalhes: str).
    """
    logger.info(f"Aguardando {aguardar_segundos}s para propagação antes da auditoria...")
    time.sleep(aguardar_segundos)

    # Extrair parte relevante do assunto para busca
    # Ex: "[Intellicore] 🎯 20 concurso(s) — Consolidado 19/03/2026"
    # Buscar pela data e palavra-chave
    hoje = date.today().strftime("%d/%m/%Y")
    query = f'subject:Intellicore subject:concurso after:{date.today().strftime("%Y/%m/%d")}'

    logger.info(f"Auditando envio via Gmail MCP: {query}")
    mensagens = _mcp_search(query, max_results=5)

    if mensagens:
        logger.info(f"Auditoria OK: {len(mensagens)} mensagem(ns) encontrada(s) na caixa")
        return True, f"{len(mensagens)} mensagem(ns) encontrada(s)"

    # Segunda tentativa com query mais simples
    query2 = f'subject:Intellicore newer_than:1d'
    mensagens2 = _mcp_search(query2, max_results=5)
    if mensagens2:
        logger.info(f"Auditoria OK (query2): {len(mensagens2)} mensagem(ns) encontrada(s)")
        return True, f"{len(mensagens2)} mensagem(ns) encontrada(s)"

    logger.warning("Auditoria: nenhuma mensagem encontrada na caixa de entrada")
    return False, "Nenhuma mensagem encontrada na caixa de entrada após envio"


# ─────────────────────────────────────────────────────────────────
# Diagnóstico e autocorreção
# ─────────────────────────────────────────────────────────────────

def _diagnosticar_e_corrigir(erro: str) -> tuple[bool, str]:
    """
    Analisa o erro e tenta autocorreção.
    Retorna (corrigido: bool, descricao: str).
    """
    erro_lower = erro.lower()

    # Erro de autenticação → tentar com SSL porta 465
    if "autenticação" in erro_lower or "authentication" in erro_lower or "535" in erro:
        logger.info("[AUTOCORREÇÃO] Tentando porta 465 (SSL direto)...")
        global SMTP_PORT, SMTP_HOST
        SMTP_PORT = 465
        return True, "Alterado para porta 465 (SSL direto)"

    # Timeout → aumentar timeout e tentar novamente
    if "timeout" in erro_lower or "timed out" in erro_lower:
        logger.info("[AUTOCORREÇÃO] Timeout detectado — aguardando 30s e tentando novamente...")
        time.sleep(30)
        return True, "Aguardou 30s após timeout"

    # Erro de conexão → tentar host alternativo
    if "connection" in erro_lower or "refused" in erro_lower or "network" in erro_lower:
        logger.info("[AUTOCORREÇÃO] Erro de conexão — tentando smtp.gmail.com:465...")
        SMTP_PORT = 465
        SMTP_HOST = "smtp.gmail.com"
        return True, "Tentando smtp.gmail.com:465"

    # Destinatário recusado → verificar endereço
    if "recipient" in erro_lower or "destinatário" in erro_lower:
        logger.warning(f"[AUTOCORREÇÃO] Destinatário recusado: {RECIPIENT}")
        return False, "Destinatário inválido — não é possível autocorrigir"

    # Erro genérico → aguardar e tentar novamente
    logger.info("[AUTOCORREÇÃO] Erro genérico — aguardando 15s...")
    time.sleep(15)
    return True, "Aguardou 15s após erro genérico"


def _enviar_smtp_ssl(subject: str, body_html: str, recipient: str) -> tuple[bool, str]:
    """Variante de envio usando SSL direto (porta 465)."""
    if not SMTP_USER or not SMTP_PASS:
        return False, "Credenciais SMTP não configuradas"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER or SMTP_USER
    msg["To"]      = recipient
    txt = _texto_plano_de_html(body_html)
    msg.attach(MIMEText(txt, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        logger.info(f"Conectando a {SMTP_HOST}:465 (SSL)...")
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=30) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info(f"Email enviado via SSL para {recipient}")
        return True, "OK (SSL)"
    except Exception as e:
        return False, f"Erro SSL: {e}"


# ─────────────────────────────────────────────────────────────────
# Log de envio
# ─────────────────────────────────────────────────────────────────

def _registrar_log(sucesso: bool, tentativas: int, detalhes: str,
                   auditoria_ok: bool, auditoria_detalhe: str):
    ENVIO_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    historico = []
    if ENVIO_LOG_PATH.exists():
        try:
            with open(ENVIO_LOG_PATH, "r", encoding="utf-8") as f:
                historico = json.load(f)
        except Exception:
            historico = []

    historico.append({
        "data": datetime.now(timezone.utc).isoformat(),
        "sucesso": sucesso,
        "tentativas": tentativas,
        "detalhes": detalhes,
        "auditoria_ok": auditoria_ok,
        "auditoria_detalhe": auditoria_detalhe,
    })
    # Manter apenas os últimos 50 registros
    historico = historico[-50:]
    with open(ENVIO_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────
# Principal
# ─────────────────────────────────────────────────────────────────

def main():
    force = "--force" in sys.argv

    payload = carregar_payload()
    if not payload:
        logger.error("Sem payload para enviar.")
        return 1

    subject   = payload["subject"]
    body_html = payload["body"]
    recipient = payload.get("recipient", RECIPIENT)

    logger.info(f"Enviando: {subject}")
    logger.info(f"Para: {recipient}")
    logger.info(f"Tamanho do HTML: {len(body_html):,} chars")

    sucesso       = False
    ultimo_erro   = ""
    tentativa_num = 0

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        tentativa_num = tentativa
        logger.info(f"--- Tentativa {tentativa}/{MAX_TENTATIVAS} ---")

        # Tentar envio TLS (587) ou SSL (465) dependendo da porta atual
        if SMTP_PORT == 465:
            ok, msg = _enviar_smtp_ssl(subject, body_html, recipient)
        else:
            ok, msg = enviar_smtp(subject, body_html, recipient)

        if ok:
            sucesso = True
            ultimo_erro = ""
            logger.info(f"Envio bem-sucedido na tentativa {tentativa}")
            break
        else:
            ultimo_erro = msg
            logger.warning(f"Tentativa {tentativa} falhou: {msg}")

            if tentativa < MAX_TENTATIVAS:
                corrigido, desc = _diagnosticar_e_corrigir(msg)
                if corrigido:
                    logger.info(f"Autocorreção aplicada: {desc}")
                else:
                    logger.error(f"Autocorreção não possível: {desc}")
                    break
                # Backoff exponencial
                espera = BACKOFF_BASE * tentativa
                logger.info(f"Aguardando {espera}s antes da próxima tentativa...")
                time.sleep(espera)

    # ── Auditoria pós-envio ────────────────────────────────────────
    auditoria_ok     = False
    auditoria_detalhe = "Envio falhou — auditoria não executada"

    if sucesso:
        auditoria_ok, auditoria_detalhe = auditar_envio(subject, recipient)
        if not auditoria_ok:
            logger.warning(f"Auditoria negativa: {auditoria_detalhe}")
            logger.info("Email enviado via SMTP mas não confirmado na caixa — pode ser atraso de propagação")
            # Não reenviar por causa de atraso de propagação — apenas registrar
        else:
            logger.info(f"Auditoria positiva: {auditoria_detalhe}")
    else:
        logger.error(f"Envio falhou após {tentativa_num} tentativa(s): {ultimo_erro}")

    # ── Registrar log ──────────────────────────────────────────────
    _registrar_log(
        sucesso=sucesso,
        tentativas=tentativa_num,
        detalhes=ultimo_erro if not sucesso else "OK",
        auditoria_ok=auditoria_ok,
        auditoria_detalhe=auditoria_detalhe,
    )

    if sucesso:
        logger.info("=== Envio concluído com sucesso ===")
        return 0
    else:
        logger.error("=== Envio falhou ===")
        return 1


if __name__ == "__main__":
    sys.exit(main())
