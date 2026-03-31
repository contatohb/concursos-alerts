#!/usr/bin/env python3
"""
Scraper para o Blog Convet (blog.preparatorioconvet.com.br).

Monitora a página de editais publicados, que lista concursos para
médicos veterinários com salários, datas de inscrição e links para editais.

URL monitorada: https://blog.preparatorioconvet.com.br/editais-publicados/

Formato dos dados retornados (compatível com monitor_concursos.py):
    orgao, cargo, nivel, salario_texto, salario_valor, vagas, banca,
    cidade, estado, data_inscricao_inicio, data_inscricao_fim, data_prova,
    link_detalhe, link_inscricao, fonte, titulo
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
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 20
SLEEP = 0.5

# URL da página de editais publicados
URL_EDITAIS = "https://blog.preparatorioconvet.com.br/editais-publicados/"

# Mapeamento de siglas de estado
_SIGLAS_UF = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


def _extrair_salario(texto: str) -> Optional[float]:
    """Extrai o valor numérico do salário a partir de texto."""
    padroes = re.findall(r'R\$\s*([\d.,]+)', texto, re.IGNORECASE)
    if not padroes:
        padroes = re.findall(r'([\d]{2,3}\.[\d]{3}(?:,[\d]{2})?)', texto)
    valores = []
    for p in padroes:
        try:
            v = float(p.replace('.', '').replace(',', '.'))
            if 1_000 <= v <= 100_000:  # faixa razoável de salário
                valores.append(v)
        except ValueError:
            pass
    return max(valores) if valores else None


def _extrair_uf_do_titulo(titulo: str) -> str:
    """Extrai a sigla do estado a partir do título do concurso."""
    # Padrão: "... - UF" ou "... /UF" ou "... (UF)" ou "...-UF"
    m = re.search(r'[-/\(]\s*([A-Z]{2})\s*[\)\s]?$', titulo.strip())
    if m and m.group(1) in _SIGLAS_UF:
        return m.group(1)
    # Padrão: "Prefeitura Cidade-UF" ou "Órgão UF"
    m2 = re.search(r'\b([A-Z]{2})\b', titulo)
    if m2 and m2.group(1) in _SIGLAS_UF:
        return m2.group(1)
    return ""


def _extrair_cidade_do_titulo(titulo: str) -> str:
    """Extrai o nome da cidade a partir do título do concurso."""
    # Padrão: "Prefeitura [Cidade]-UF" ou "Prefeitura [Cidade] - UF"
    m = re.search(
        r'Prefeitura\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç\s]+?)(?:\s*[-/]\s*[A-Z]{2}|$)',
        titulo
    )
    if m:
        return m.group(1).strip()
    return ""


def _parse_accordion_item(titulo: str, conteudo: str, link_edital: str) -> Optional[Dict]:
    """
    Parseia um item do accordion da página de editais.

    Args:
        titulo: Título do accordion (ex: "Concurso Público ADAB-BA (inscrições até 31/03/2026)")
        conteudo: Texto do painel (ex: "Inscrições do dia 06/03 a 31/03/2026\nSalário base: R$ 7.445,86\n...")
        link_edital: URL do edital ou inscrição

    Returns:
        Dict compatível com monitor_concursos.py ou None se não puder parsear
    """
    if not titulo or not conteudo:
        return None

    # Extrair data de inscrição do título
    m_titulo_data = re.search(
        r'inscri[çc][õo]es?\s+(?:até\s+)?(\d{1,2}/\d{1,2}/\d{2,4})',
        titulo, re.IGNORECASE
    )
    data_inscricao_fim_titulo = m_titulo_data.group(1) if m_titulo_data else ""

    # Parsear conteúdo do accordion
    # Formato típico:
    #   Inscrições do dia 06/03 a 31/03/2026
    #   Data da prova: 24 de maio de 2026
    #   Salário base: R$ 7.445,86
    #   Carga horária: 40 horas
    #   Banca: IDCAP
    #   Acesse aqui o edital

    # Data de inscrição
    data_inscricao_inicio = ""
    data_inscricao_fim = ""
    m_insc = re.search(
        r'inscri[çc][õo]es?\s+(?:do\s+dia\s+)?(\d{1,2}/\d{1,2}(?:/\d{2,4})?)'
        r'\s+(?:a|até|ao)\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        conteudo, re.IGNORECASE
    )
    if m_insc:
        data_inscricao_inicio = m_insc.group(1)
        data_inscricao_fim = m_insc.group(2)
    else:
        # Apenas data final
        m_insc2 = re.search(
            r'inscri[çc][õo]es?\s+até\s+(\d{1,2}(?:\s+de\s+\w+\s+de\s+|\s*/\s*)\d{2,4})',
            conteudo, re.IGNORECASE
        )
        if m_insc2:
            data_inscricao_fim = m_insc2.group(1)
        elif data_inscricao_fim_titulo:
            data_inscricao_fim = data_inscricao_fim_titulo

    # Data da prova
    data_prova = ""
    m_prova = re.search(
        r'(?:data\s+da\s+prova|prova)[:\s]+(\d{1,2}(?:\s+de\s+\w+\s+de\s+\d{4}|\s*/\s*\d{1,2}/\d{2,4}))',
        conteudo, re.IGNORECASE
    )
    if m_prova:
        data_prova = m_prova.group(1).strip()

    # Salário
    salario_texto = ""
    salario_valor = None
    m_sal = re.search(
        r'sal[aá]rio\s+(?:base|inicial)?[:\s]*R?\$?\s*([\d.,]+)',
        conteudo, re.IGNORECASE
    )
    if m_sal:
        salario_texto = f"R$ {m_sal.group(1)}"
        try:
            salario_valor = float(m_sal.group(1).replace('.', '').replace(',', '.'))
        except ValueError:
            salario_valor = _extrair_salario(conteudo)
    else:
        salario_valor = _extrair_salario(conteudo)
        if salario_valor:
            salario_texto = f"R$ {salario_valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # Banca
    banca = ""
    m_banca = re.search(r'banca[:\s]+([^\n]+)', conteudo, re.IGNORECASE)
    if m_banca:
        banca = m_banca.group(1).strip()

    # Estado e cidade a partir do título
    estado = _extrair_uf_do_titulo(titulo)
    cidade = _extrair_cidade_do_titulo(titulo)

    # Órgão: extrair do título (remover a parte de datas e o tipo de concurso)
    orgao = re.sub(
        r'\s*\(inscri[\xe7c][\xf5o]es?.*?\)\s*$', '', titulo, flags=re.IGNORECASE
    ).strip()
    # Separar tipo de concurso ("Concurso Público", "Processo Seletivo", etc.) do nome do órgão
    # O Blog Convet não coloca espaço entre o tipo e o órgão em alguns casos
    orgao = re.sub(
        r'^(?:Concurso\s+P[uú]blico|Processo\s+Seletivo|Concurso\s+Simplificado|'
        r'Sele[cç][aã]o\s+P[uú]blica|Edital\s+de\s+Concurso)\s*',
        '', orgao, flags=re.IGNORECASE
    ).strip()

    # Nível: todos os concursos do blog Convet são para médico veterinário
    nivel = "Superior"
    cargo = "Médico Veterinário"

    # Classificar o link_edital:
    # - Se for PDF direto -> link_edital_pdf (link do edital)
    # - Se for página web -> link_inscricao (página de inscrição na banca)
    link_edital_pdf = ""
    link_inscricao = ""
    if link_edital:
        if link_edital.lower().endswith(".pdf") or ".pdf" in link_edital.lower():
            link_edital_pdf = link_edital
        else:
            link_inscricao = link_edital

    return {
        "orgao": orgao,
        "cargo": cargo,
        "nivel": nivel,
        "salario_texto": salario_texto,
        "salario_valor": salario_valor,
        "vagas": "",
        "banca": banca,
        "cidade": cidade,
        "estado": estado,
        "data_inscricao_inicio": data_inscricao_inicio,
        "data_inscricao_fim": data_inscricao_fim,
        "data_prova": data_prova,
        "link_detalhe": URL_EDITAIS,          # página do Blog Convet (fonte)
        "link_inscricao": link_inscricao,      # página de inscrição na banca (se web)
        "link_edital_pdf": link_edital_pdf,    # PDF direto do edital (se PDF)
        "fonte": "Blog Convet",
        "titulo": titulo,
    }


def scrape_convet_blog(session: Optional[requests.Session] = None) -> List[Dict]:
    """
    Coleta concursos da página de editais publicados do Blog Convet.

    Returns:
        Lista de dicts de concursos compatíveis com monitor_concursos.py
    """
    if session is None:
        session = requests.Session()
        session.verify = False

    concursos = []

    try:
        r = session.get(URL_EDITAIS, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        html = r.text
    except Exception as exc:
        logger.warning(f"[Convet Blog] Erro ao acessar {URL_EDITAIS}: {exc}")
        return concursos

    soup = BeautifulSoup(html, "html.parser")

    # Encontrar todos os botões de accordion
    # Estrutura: <button id="accordion-item-N">Título</button>
    #            <div id="accordion-item-N-panel">Conteúdo</div>
    accordion_buttons = soup.find_all(
        "button",
        id=re.compile(r'^accordion-item-\d+$')
    )

    logger.info(f"[Convet Blog] {len(accordion_buttons)} itens de accordion encontrados")

    for btn in accordion_buttons:
        btn_id = btn.get("id", "")
        panel_id = btn_id + "-panel"
        panel = soup.find(id=panel_id)

        if not panel:
            continue

        # Título do accordion
        titulo_tag = btn.find(class_="wp-block-accordion-heading__toggle-title")
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else btn.get_text(strip=True)

        # Conteúdo do painel
        conteudo = panel.get_text(separator="\n", strip=True)

        # Link do edital (primeiro <a> no painel)
        link_edital = ""
        a_tag = panel.find("a", href=True)
        if a_tag:
            link_edital = a_tag["href"].strip()

        # Parsear item
        item = _parse_accordion_item(titulo, conteudo, link_edital)
        if item:
            concursos.append(item)

        time.sleep(0.05)  # pequena pausa para não sobrecarregar

    logger.info(f"[Convet Blog] {len(concursos)} concursos extraídos")
    return concursos


def _test():
    """Teste rápido do scraper."""
    import warnings
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    concursos = scrape_convet_blog()
    print(f"\nTotal extraído: {len(concursos)}")
    for c in concursos[:10]:
        sal = c.get("salario_valor", 0) or 0
        print(
            f"  [{c['estado']}] {c['orgao'][:60]}"
            f" | Sal: R$ {sal:,.0f}"
            f" | Insc: {c['data_inscricao_fim']}"
            f" | Link: {c['link_inscricao'][:60] if c['link_inscricao'] else '(sem link)'}"
        )


if __name__ == "__main__":
    _test()
