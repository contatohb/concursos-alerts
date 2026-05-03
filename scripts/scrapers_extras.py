#!/usr/bin/env python3
"""
scrapers_extras.py
==================
Scrapers adicionais de fontes de concursos públicos:
- JC Concursos (jcconcursos.com.br)
- Estratégia Concursos (estrategiaconcursos.com.br)
- Gran Cursos Online (grancursosonline.com.br)
- Aprova Concursos (aprovaconcursos.com.br)
- Folha Dirigida / QConcursos (folha.qconcursos.com)
- IBFC (concursos.ibfc.org.br)
- IDECAN (idecan.org.br)
- AOCP (institutoaocp.org.br)
- Quadrix (ps-adm-861.selecao.net.br)
- IADES (iades.com.br)
- FEPESE (fepese.org.br)
- Cebraspe (cebraspe.org.br)

Regra absoluta: nunca inventar dados. Apenas retornar o que foi encontrado.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
TIMEOUT = 20
SLEEP = 0.5

_SIGLAS_UF = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


def _get(url: str, session: requests.Session) -> Optional[str]:
    try:
        r = session.get(url, timeout=TIMEOUT, headers=HEADERS, verify=False)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        logger.debug(f"GET {url}: {exc}")
        return None


def _extrair_salario(texto: str) -> Optional[float]:
    """Extrai o maior valor de salário mencionado no texto."""
    padroes = re.findall(r'R\$\s*([\d.,]+)', texto, re.IGNORECASE)
    if not padroes:
        padroes = re.findall(r'([\d]{2,3}\.[\d]{3}(?:,[\d]{2})?)', texto)
    valores = []
    for p in padroes:
        try:
            v = float(p.replace('.', '').replace(',', '.'))
            if 1_000 <= v <= 200_000:
                valores.append(v)
        except ValueError:
            pass
    return max(valores) if valores else None


def _extrair_uf(texto: str) -> str:
    """Extrai a sigla do estado do texto."""
    m = re.search(r'\b([A-Z]{2})\b', texto)
    if m and m.group(1) in _SIGLAS_UF:
        return m.group(1)
    return ""


def _item_base(orgao: str, titulo: str, link: str, fonte: str,
               salario_valor: float = None, nivel: str = "",
               estado: str = "", cidade: str = "",
               banca: str = "") -> Dict:
    """Cria um dicionário base para um concurso."""
    return {
        "orgao": orgao,
        "cargo": titulo[:100],
        "nivel": nivel,
        "salario_texto": "",
        "salario_valor": salario_valor,
        "salario_fonte": "listagem",
        "vagas": "",
        "banca": banca,
        "cidade": cidade,
        "estado": estado,
        "data_inscricao_inicio": "",
        "data_inscricao_fim": "",
        "data_prova": "",
        "link_detalhe": link,
        "link_inscricao": "",
        "fonte": fonte,
        "titulo": titulo,
    }


# ─────────────────────────────────────────────────────────────────
# JC Concursos
# ─────────────────────────────────────────────────────────────────

def scrape_jc_concursos(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos do JC Concursos — inscrições abertas.
    URL: https://jcconcursos.com.br/concursos/inscricoes-abertas
    """
    concursos = []
    seen = set()
    url = "https://jcconcursos.com.br/concursos/inscricoes-abertas"

    html = _get(url, session)
    if not html:
        logger.warning("[JC Concursos] Falha ao acessar listagem")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    # JC Concursos usa tabela ou lista de concursos
    # Tentar encontrar links de concursos
    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 5:
            continue
        if "jcconcursos.com.br" not in href and not href.startswith("/"):
            continue
        if href.startswith("/"):
            href = "https://jcconcursos.com.br" + href
        if href in seen:
            continue
        # Filtrar apenas links de concursos (não artigos genéricos)
        if any(k in href.lower() for k in ["/concurso", "/edital", "/inscricao"]):
            seen.add(href)
            sal = _extrair_salario(txt)
            estado = _extrair_uf(txt)
            concursos.append(_item_base(
                orgao=txt[:80],
                titulo=txt[:100],
                link=href,
                fonte="JC Concursos",
                salario_valor=sal,
                estado=estado,
            ))

    logger.info(f"[JC Concursos] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# Estratégia Concursos
# ─────────────────────────────────────────────────────────────────

def scrape_estrategia(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos da página de concursos abertos da Estratégia.
    URL: https://www.estrategiaconcursos.com.br/blog/concursos-abertos/
    """
    concursos = []
    seen = set()
    url = "https://www.estrategiaconcursos.com.br/blog/concursos-abertos/"

    html = _get(url, session)
    if not html:
        logger.warning("[Estratégia] Falha ao acessar listagem")
        return concursos

    soup = BeautifulSoup(html, "html.parser")
    texto_completo = soup.get_text(separator="\n", strip=True)

    # Extrair links de artigos sobre concursos
    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 5:
            continue
        if "estrategiaconcursos.com.br" not in href:
            continue
        if href in seen:
            continue
        # Filtrar apenas links de concursos/editais
        if any(k in href.lower() for k in ["/concurso", "/edital", "/inscricao", "/blog/"]):
            if any(k in txt.lower() for k in ["concurso", "edital", "vaga", "inscrição"]):
                seen.add(href)
                sal = _extrair_salario(txt)
                estado = _extrair_uf(txt)
                concursos.append(_item_base(
                    orgao=txt[:80],
                    titulo=txt[:100],
                    link=href,
                    fonte="Estratégia Concursos",
                    salario_valor=sal,
                    estado=estado,
                ))

    logger.info(f"[Estratégia] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# Gran Cursos Online
# ─────────────────────────────────────────────────────────────────

def scrape_gran_cursos(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos da página de concursos abertos do Gran Cursos.
    URL: https://blog.grancursosonline.com.br/concursos-abertos/
    """
    concursos = []
    seen = set()
    url = "https://blog.grancursosonline.com.br/concursos-abertos/"

    html = _get(url, session)
    if not html:
        logger.warning("[Gran Cursos] Falha ao acessar listagem")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 5:
            continue
        if "grancursosonline.com.br" not in href:
            continue
        if href in seen:
            continue
        if any(k in href.lower() for k in ["/blog/", "/concurso", "/edital"]):
            if any(k in txt.lower() for k in ["concurso", "edital", "vaga", "inscrição", "aberto"]):
                seen.add(href)
                sal = _extrair_salario(txt)
                estado = _extrair_uf(txt)
                concursos.append(_item_base(
                    orgao=txt[:80],
                    titulo=txt[:100],
                    link=href,
                    fonte="Gran Cursos",
                    salario_valor=sal,
                    estado=estado,
                ))

    logger.info(f"[Gran Cursos] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# Aprova Concursos
# ─────────────────────────────────────────────────────────────────

def scrape_aprova_concursos(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos da página de editais publicados hoje da Aprova Concursos.
    URL: https://www.aprovaconcursos.com.br/noticias/editais-publicados-hoje/
    """
    concursos = []
    seen = set()
    urls = [
        "https://www.aprovaconcursos.com.br/noticias/editais-publicados-hoje/",
        "https://www.aprovaconcursos.com.br/noticias/concursos-abertos-e-previstos/",
    ]

    for url in urls:
        html = _get(url, session)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            txt = a.get_text(strip=True)
            if not href or not txt or len(txt) < 5:
                continue
            if "aprovaconcursos.com.br" not in href:
                continue
            if href in seen:
                continue
            if any(k in href.lower() for k in ["/noticias/", "/concurso", "/edital"]):
                if any(k in txt.lower() for k in ["concurso", "edital", "vaga", "inscrição"]):
                    seen.add(href)
                    sal = _extrair_salario(txt)
                    estado = _extrair_uf(txt)
                    concursos.append(_item_base(
                        orgao=txt[:80],
                        titulo=txt[:100],
                        link=href,
                        fonte="Aprova Concursos",
                        salario_valor=sal,
                        estado=estado,
                    ))
        time.sleep(SLEEP)

    logger.info(f"[Aprova Concursos] {len(concursos)} concursos coletados")
    return concursos


# ─────────────────────────────────────────────────────────────────
# Folha Dirigida / QConcursos
# ─────────────────────────────────────────────────────────────────

def scrape_folha_dirigida(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos da Folha Dirigida (via QConcursos).
    URL: https://folha.qconcursos.com/
    """
    concursos = []
    seen = set()
    url = "https://folha.qconcursos.com/"

    html = _get(url, session)
    if not html:
        logger.warning("[Folha Dirigida] Falha ao acessar")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 5:
            continue
        if "qconcursos.com" not in href:
            continue
        if href in seen:
            continue
        if any(k in txt.lower() for k in ["concurso", "edital", "vaga", "inscrição"]):
            seen.add(href)
            sal = _extrair_salario(txt)
            estado = _extrair_uf(txt)
            concursos.append(_item_base(
                orgao=txt[:80],
                titulo=txt[:100],
                link=href,
                fonte="Folha Dirigida",
                salario_valor=sal,
                estado=estado,
            ))

    logger.info(f"[Folha Dirigida] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# IBFC
# ─────────────────────────────────────────────────────────────────

def scrape_ibfc(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos em andamento do IBFC.
    URL: https://concursos.ibfc.org.br/
    """
    concursos = []
    seen = set()
    url = "https://concursos.ibfc.org.br/"

    html = _get(url, session)
    if not html:
        logger.warning("[IBFC] Falha ao acessar")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 3:
            continue
        if not href.startswith("http"):
            href = "https://concursos.ibfc.org.br" + href
        if href in seen:
            continue
        # Links de concursos específicos
        if any(k in href.lower() for k in ["concurso", "inscricao", "edital", "processo"]):
            seen.add(href)
            sal = _extrair_salario(txt)
            estado = _extrair_uf(txt)
            concursos.append(_item_base(
                orgao=txt[:80],
                titulo=txt[:100],
                link=href,
                fonte="IBFC",
                salario_valor=sal,
                estado=estado,
                banca="IBFC",
            ))

    logger.info(f"[IBFC] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# IDECAN
# ─────────────────────────────────────────────────────────────────

def scrape_idecan(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos em andamento do IDECAN.
    URL: https://idecan.org.br/
    """
    concursos = []
    seen = set()
    url = "https://idecan.org.br/"

    html = _get(url, session)
    if not html:
        logger.warning("[IDECAN] Falha ao acessar")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 3:
            continue
        if not href.startswith("http"):
            href = "https://idecan.org.br" + href
        if href in seen:
            continue
        if any(k in href.lower() for k in ["concurso", "inscricao", "edital", "processo", "seletivo"]):
            seen.add(href)
            sal = _extrair_salario(txt)
            estado = _extrair_uf(txt)
            concursos.append(_item_base(
                orgao=txt[:80],
                titulo=txt[:100],
                link=href,
                fonte="IDECAN",
                salario_valor=sal,
                estado=estado,
                banca="IDECAN",
            ))

    logger.info(f"[IDECAN] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# Instituto AOCP
# ─────────────────────────────────────────────────────────────────

def scrape_aocp(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos em andamento do Instituto AOCP.
    URL: https://www.institutoaocp.org.br/
    """
    concursos = []
    seen = set()
    url = "https://www.institutoaocp.org.br/"

    html = _get(url, session)
    if not html:
        logger.warning("[AOCP] Falha ao acessar")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 3:
            continue
        if not href.startswith("http"):
            href = "https://www.institutoaocp.org.br" + href
        if href in seen:
            continue
        if any(k in href.lower() for k in ["concurso", "inscricao", "edital", "processo", "seletivo"]):
            seen.add(href)
            sal = _extrair_salario(txt)
            estado = _extrair_uf(txt)
            concursos.append(_item_base(
                orgao=txt[:80],
                titulo=txt[:100],
                link=href,
                fonte="AOCP",
                salario_valor=sal,
                estado=estado,
                banca="AOCP",
            ))

    logger.info(f"[AOCP] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# Quadrix
# ─────────────────────────────────────────────────────────────────

def scrape_quadrix(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos em andamento da Quadrix.
    URL: https://ps-adm-861.selecao.net.br/
    """
    concursos = []
    seen = set()
    url = "https://ps-adm-861.selecao.net.br/"

    html = _get(url, session)
    if not html:
        logger.warning("[Quadrix] Falha ao acessar")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 3:
            continue
        if not href.startswith("http"):
            href = "https://ps-adm-861.selecao.net.br" + href
        if href in seen:
            continue
        if any(k in href.lower() for k in ["concurso", "inscricao", "edital", "processo", "selecao"]):
            seen.add(href)
            sal = _extrair_salario(txt)
            estado = _extrair_uf(txt)
            concursos.append(_item_base(
                orgao=txt[:80],
                titulo=txt[:100],
                link=href,
                fonte="Quadrix",
                salario_valor=sal,
                estado=estado,
                banca="QUADRIX",
            ))

    logger.info(f"[Quadrix] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# FEPESE
# ─────────────────────────────────────────────────────────────────

def scrape_fepese(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos em andamento da FEPESE.
    URL: https://fepese.org.br/concursos/
    """
    concursos = []
    seen = set()
    url = "https://fepese.org.br/concursos/"

    html = _get(url, session)
    if not html:
        logger.warning("[FEPESE] Falha ao acessar")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 3:
            continue
        if not href.startswith("http"):
            href = "https://fepese.org.br" + href
        if href in seen:
            continue
        if "fepese.org.br" in href:
            seen.add(href)
            sal = _extrair_salario(txt)
            estado = _extrair_uf(txt)
            concursos.append(_item_base(
                orgao=txt[:80],
                titulo=txt[:100],
                link=href,
                fonte="FEPESE",
                salario_valor=sal,
                estado=estado,
                banca="FEPESE",
            ))

    logger.info(f"[FEPESE] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# Cebraspe
# ─────────────────────────────────────────────────────────────────

def scrape_cebraspe(session: requests.Session) -> List[Dict]:
    """
    Coleta concursos em andamento do Cebraspe.
    URL: https://www.cebraspe.org.br/concursos
    """
    concursos = []
    seen = set()
    url = "https://www.cebraspe.org.br/concursos"

    html = _get(url, session)
    if not html:
        logger.warning("[Cebraspe] Falha ao acessar")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if not href or not txt or len(txt) < 3:
            continue
        if not href.startswith("http"):
            href = "https://www.cebraspe.org.br" + href
        if href in seen:
            continue
        if "cebraspe.org.br/concursos" in href:
            seen.add(href)
            sal = _extrair_salario(txt)
            estado = _extrair_uf(txt)
            concursos.append(_item_base(
                orgao=txt[:80],
                titulo=txt[:100],
                link=href,
                fonte="Cebraspe",
                salario_valor=sal,
                estado=estado,
                banca="CEBRASPE",
            ))

    logger.info(f"[Cebraspe] {len(concursos)} concursos coletados")
    time.sleep(SLEEP)
    return concursos


# ─────────────────────────────────────────────────────────────────
# Função principal: coletar de todas as fontes extras
# ─────────────────────────────────────────────────────────────────

def scrape_todas_fontes_extras(session: requests.Session) -> tuple:
    """
    Coleta concursos de todas as fontes extras.
    Retorna (lista_concursos, lista_erros).
    """
    todos = []
    erros = []

    fontes = [
        ("JC Concursos", scrape_jc_concursos),
        ("Estratégia Concursos", scrape_estrategia),
        ("Gran Cursos", scrape_gran_cursos),
        ("Aprova Concursos", scrape_aprova_concursos),
        ("Folha Dirigida", scrape_folha_dirigida),
        ("IBFC", scrape_ibfc),
        ("IDECAN", scrape_idecan),
        ("AOCP", scrape_aocp),
        ("Quadrix", scrape_quadrix),
        ("FEPESE", scrape_fepese),
        ("Cebraspe", scrape_cebraspe),
    ]

    for nome, fn in fontes:
        try:
            resultado = fn(session)
            todos.extend(resultado)
            logger.info(f"[EXTRAS] {nome}: {len(resultado)} concursos")
        except Exception as e:
            erros.append(f"[{nome}] {e}")
            logger.warning(f"[EXTRAS] Erro em {nome}: {e}")

    return todos, erros
