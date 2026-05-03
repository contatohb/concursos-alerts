#!/usr/bin/env python3
"""
edital_parser.py
================
Módulo responsável por:
1. Localizar o PDF do edital/quadro de vagas no site da banca ou entidade organizadora
2. Baixar e extrair o texto com layout preservado (pdftotext -layout)
3. Parsear a tabela de cargos, associando cada cargo ao seu salário, vagas e cidade(s)
4. Filtrar apenas cargos de interesse com salário >= R$ 10.000

Regras absolutas:
- Nunca inventar dados. Se o salário não for encontrado no edital, o campo fica vazio.
- Nunca descartar sem verificar o edital. Se não há link direto, buscar na entidade organizadora.
- Descartar cargos que exigem mestrado ou doutorado (Hudson tem graduação + pós-graduação lato sensu).
- Descartar cargos de formações específicas não compatíveis.
"""

import re
import os
import subprocess
import tempfile
import logging
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

SALARIO_MINIMO = 10_000.0

# ─────────────────────────────────────────────────────────────────
# Classificação de cargos por categoria de interesse
# ─────────────────────────────────────────────────────────────────

# Termos que identificam Médico Veterinário
_TERMOS_VETERINARIO = [
    "médico veterinário", "medico veterinario",
    "veterinário", "veterinario",
    "med. veterinário", "med. veterinario",
]

# Termos que identificam exigência de mestrado ou doutorado (descartar)
_TERMOS_POS_STRICTO = [
    "mestrado", "mestre", "doutorado", "doutor",
    "pós-doutorado", "pos-doutorado", "pós doutorado",
    "phd", "ph.d", "stricto sensu",
    "título de mestre", "titulo de mestre",
    "título de doutor", "titulo de doutor",
]

# Termos que identificam formação específica NÃO desejada
_TERMOS_FORMACAO_ESPECIFICA_INDESEJADA = [
    "médico ", "medico ", "médico(", "medico(",
    "cirurgião", "cirurgiao",
    "pediatra", "cardiologista", "ginecologista", "obstetra",
    "oftalmologista", "ortopedista", "otorrinolaringologista",
    "urologista", "vascular", "psiquiatra", "neurologista",
    "anestesiologista", "radiologista", "dermatologista",
    "infectologista", "nefrologista", "reumatologista",
    "endocrinologista", "oncologista", "hematologista",
    "pneumologista", "gastroenterologista", "hepatologista",
    "coloproctologista", "mastologista",
    "médico esf", "medico esf",
    "médico do trabalho", "medico do trabalho",
    "médico clínico", "medico clinico",
    "advogado", "advogada", "procurador", "defensor", "promotor",
    "engenheiro", "engenheira",
    "dentista", "odontolog", "cirurgião-dentista",
    "farmacêutico", "farmaceutico",
    "enfermeiro", "enfermeira",
    "psicólogo", "psicologa", "psicolog",
    "fisioterapeuta", "fisioterapia",
    "nutricionista",
    "contador ", "contadora",
    "economista",
    "arquiteto", "arquiteta",
    "biólogo", "biologa",
    "químico", "quimico",
    "geólogo", "geologo",
    "assistente social",
    "pedagogo", "pedagoga",
    "professor", "professora", "docente",
    "fonoaudiólogo", "fonoaudióloga",
    "terapeuta ocupacional",
    # Ciências exatas e tecnologia
    "físico ", "fisico ", "física médica", "fisica medica",
    "tecnologia da informação", "tecnologia de informação",
    "analista de ti", "analista de t.i",
    "ciência da computação", "ciencias da computacao",
    "sistemas de informação", "sistemas de informacao",
    "engenharia de software", "engenharia da computação",
    "matemático", "matematico",
    "estatístico", "estatistico",
    "geógrafo", "geografo",
    "meteorologista",
    "oceanógrafo", "oceanografo",
    "astrônomo", "astronomo",
]

# Termos que identificam "qualquer área de formação superior"
# NOTA: Esta lista deve conter apenas termos que EXPLICITAMENTE indicam
# aceitação de qualquer graduação superior. Termos genéricos como "analista",
# "coordenador" etc. foram movidos para _TERMOS_CARGO_SUPERIOR_GENERICO.
_TERMOS_QUALQUER_AREA = [
    "qualquer curso", "qualquer área", "qualquer area",
    "qualquer graduação", "qualquer graduacao",
    "nível superior", "nivel superior",
    "ensino superior",
    "bacharel em qualquer",
    "graduação em qualquer",
    "formação superior",
    "curso superior",
    "técnico de nível superior", "tecnico de nivel superior",
    "vários cargos", "varios cargos",
]

# Termos que identificam nível médio
_TERMOS_NIVEL_MEDIO = [
    "nível médio", "nivel medio",
    "ensino médio", "ensino medio",
    "auxiliar", "agente ", "atendente", "operador",
    "assistente ", "motorista",
    "servidor geral", "açougueiro",
    "escriturário", "escriturario",
    "recepcionista", "telefonista",
    "guarda ", "vigilante",
    "oficial ",
    "agente de combate", "agente comunitário",
    "agente de saúde", "agente de endemias",
    "técnico em", "tecnico em",
    "auxiliar de", "assistente de",
    "operador de",
]


# Termos que indicam que o texto é um nome de cargo válido (nível superior)
# Cargos que exigem nível superior mas não se enquadram nas listas específicas acima
_TERMOS_CARGO_SUPERIOR_GENERICO = [
    "auditor", "fiscal ", "fiscal/", "fiscal-",
    "inspetor ", "inspetor/", "inspetor-",
    "inspector",
    "perito", "especialista",
    "analista ", "analista/", "analista-",
    "assessor", "coordenador", "gerente", "supervisor",
    "técnico administrativo", "tecnico administrativo",
    "assistente administrativo",
    "agente administrativo",
    "servidor público", "servidor efetivo",  # não apenas 'servidor' (muito genérico)
    "agente de desenvolvimento",
    "agente regulatório", "agente regulatorio",
    "pesquisador", "cientista",
    "agrônomo", "agronomo",
    "zootecnista",
    "médico veterinário", "medico veterinario",
    "veterinário", "veterinario",
]


def _classificar_cargo(nome_cargo: str) -> Optional[str]:
    """
    Classifica o cargo em uma das três categorias de interesse.
    Retorna: 'veterinario', 'qualquer_area', 'nivel_medio', ou None (não interessa).

    IMPORTANTE: O fallback NÃO é mais 'qualquer_area' — textos não reconhecidos
    retornam None para evitar falsos positivos com nomes de cidades, cabeçalhos
    de tabela, fragmentos de texto, etc.
    """
    nome_lower = nome_cargo.lower().strip()

    # Rejeitar textos claramente não-cargo: muito curtos, números, fragmentos
    if len(nome_cargo.strip()) < 5:
        return None
    # Rejeitar se começa com artigo/preposição (cabeçalhos de tabela, etc.)
    _PREFIXOS_NAO_CARGO = [
        "total", "subtotal", "município de", "municipio de",
        "estado de", "governo de", "prefeitura de",
        "secretaria de", "departamento de",
        "processo seletivo", "concurso público", "concurso publico",
        "edital", "anexo", "quadro", "tabela",
        "cargo/", "cargo -", "n.º", "nº",
    ]
    if any(nome_lower.startswith(p) for p in _PREFIXOS_NAO_CARGO):
        return None
    # Rejeitar se contém apenas palavras de 2 letras ou menos (siglas, fragmentos)
    palavras = [p for p in nome_cargo.split() if len(p) > 2]
    if not palavras:
        return None

    # 1. Médico Veterinário (prioridade máxima)
    if any(t in nome_lower for t in _TERMOS_VETERINARIO):
        return "veterinario"

    # 2. Formação específica indesejada — descartar
    if any(t in nome_lower for t in _TERMOS_FORMACAO_ESPECIFICA_INDESEJADA):
        return None

    # 3. Qualquer área de formação superior — apenas se contém termo explícito
    if any(t in nome_lower for t in _TERMOS_QUALQUER_AREA):
        return "qualquer_area"

    # 4. Nível médio
    if any(t in nome_lower for t in _TERMOS_NIVEL_MEDIO):
        return "nivel_medio"

    # 5. Cargos de nível superior genéricos reconhecidos explicitamente
    if any(t in nome_lower for t in _TERMOS_CARGO_SUPERIOR_GENERICO):
        return "qualquer_area"

    # 6. Cargo não reconhecido: retornar None para evitar falsos positivos.
    # Textos como 'MUNICÍPIO DE RIO DO SUL', 'Total de', 'PcD', 'PN' chegam aqui
    # e são corretamente descartados.
    return None


def _extrair_valor_salario(texto_salario: str) -> float:
    """Extrai o valor numérico de um texto de salário como 'R$ 12.815,64'."""
    numeros = re.findall(r'[\d.,]+', texto_salario.replace(".", "").replace(",", "."))
    for n in numeros:
        try:
            val = float(n)
            if val > 100:
                return val
        except ValueError:
            pass
    return 0.0


def _parsear_tabela_layout(texto_layout: str) -> List[Dict]:
    """
    Parseia o texto extraído com pdftotext -layout para associar
    cargo -> salário a partir da estrutura tabular.
    """
    resultados = []
    linhas = texto_layout.split("\n")

    pat_cod_cargo = re.compile(r'^\s*(\d{1,3})\s{2,}([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ \-/ºª\.]+)\s{3,}')
    pat_salario_principal = re.compile(r'R\$\s*([\d.]+,[\d]{2})\s*\+')
    pat_salario_simples = re.compile(r'R\$\s*([\d.]+,[\d]{2})')

    for i, linha in enumerate(linhas):
        m_cargo = pat_cod_cargo.match(linha)
        if not m_cargo:
            continue

        cargo_nome = m_cargo.group(2).strip()
        cargo_nome = re.sub(r'\*+\s*$', '', cargo_nome).strip()
        cargo_nome = re.sub(r'\s{2,}.*$', '', cargo_nome).strip()

        _TERMOS_PREREQUISITO = ["Curso ", "Superior em", "Licenciatura", "Bacharelado",
                                 "Ensino ", "Graduação", "Registro no", "Conselho",
                                 "Habilitação", "Especialização"]
        if any(t in cargo_nome for t in _TERMOS_PREREQUISITO):
            continue

        salario_texto = ""
        salario_valor = 0.0

        for j in range(i - 1, max(i - 6, -1), -1):
            linha_ant = linhas[j]
            m_sal = pat_salario_principal.search(linha_ant)
            if m_sal:
                salario_texto = f"R$ {m_sal.group(1)}"
                salario_valor = _extrair_valor_salario(salario_texto)
                break

        if not salario_texto:
            for j in range(i + 1, min(i + 6, len(linhas))):
                linha_prox = linhas[j]
                m_sal = pat_salario_principal.search(linha_prox)
                if m_sal:
                    salario_texto = f"R$ {m_sal.group(1)}"
                    salario_valor = _extrair_valor_salario(salario_texto)
                    break

        if not salario_texto:
            for j in range(max(i - 3, 0), min(i + 6, len(linhas))):
                linha_j = linhas[j]
                m_sal = pat_salario_simples.search(linha_j)
                if m_sal:
                    val = _extrair_valor_salario(f"R$ {m_sal.group(1)}")
                    if val > 500:
                        salario_texto = f"R$ {m_sal.group(1)}"
                        salario_valor = val
                        break

        if cargo_nome and salario_texto:
            resultados.append({
                "cargo": cargo_nome,
                "salario_texto": salario_texto,
                "salario_valor": salario_valor,
            })

    return resultados


def _parsear_formato_numerado(texto: str) -> List[Dict]:
    """
    Parseia editais no formato numerado:
      1.14. MÉDICO ESF
      1.14.1. Vagas: 01.
      1.14.5. Salário: R$ 15.182,61
    """
    resultados = []
    linhas = texto.split("\n")

    pat_cargo = re.compile(r'^\s*\d+\.\d+\.\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ \-/]+)$')
    pat_salario_linha = re.compile(r'Salário:\s*R\$\s*([\d.]+,[\d]{2})', re.IGNORECASE)

    cargo_atual = None
    for i, linha in enumerate(linhas):
        m_cargo = pat_cargo.match(linha)
        if m_cargo:
            cargo_atual = m_cargo.group(1).strip()
            continue

        if cargo_atual:
            m_sal = pat_salario_linha.search(linha)
            if m_sal:
                salario_texto = f"R$ {m_sal.group(1)}"
                salario_valor = _extrair_valor_salario(salario_texto)
                resultados.append({
                    "cargo": cargo_atual,
                    "salario_texto": salario_texto,
                    "salario_valor": salario_valor,
                })
                cargo_atual = None

    return resultados


def _parsear_texto_simples(texto: str) -> List[Dict]:
    """
    Fallback: parseia texto simples tentando associar cargo -> salário por proximidade.
    """
    resultados = []
    linhas = [l.strip() for l in texto.split("\n") if l.strip()]

    pat_salario = re.compile(r'R\$\s*([\d.]+,\d{2})', re.IGNORECASE)

    i = 0
    while i < len(linhas):
        linha = linhas[i]
        if (len(linha) > 4 and
                linha[0].isupper() and
                not linha.startswith("R$") and
                not re.match(r'^\d', linha) and
                not any(k in linha.lower() for k in ["página", "edital", "prefeitura", "estado", "município",
                                                       "tabela", "quadro", "relação", "anexo", "carga", "horária",
                                                       "inscrição", "vagas", "ampla", "concorrência"])):
            cargo_nome = re.sub(r'\*+$', '', linha).strip()
            for j in range(i + 1, min(i + 15, len(linhas))):
                m = pat_salario.search(linhas[j])
                if m:
                    salario_texto = f"R$ {m.group(1)}"
                    resultados.append({
                        "cargo": cargo_nome,
                        "salario_texto": salario_texto,
                        "salario_valor": _extrair_valor_salario(salario_texto),
                    })
                    break
        i += 1

    return resultados


def _parsear_tabela_generica(texto: str) -> List[Dict]:
    """
    Parseia editais com padrão de tabela genérica:
    Cargo | Vagas | Salário | Requisito
    Tenta extrair cargo + salário + vagas + formação de linhas tabulares.
    """
    resultados = []
    linhas = texto.split("\n")
    pat_salario = re.compile(r'R\$\s*([\d.]+,\d{2})', re.IGNORECASE)
    pat_vagas = re.compile(r'\b(\d{1,4})\s*(?:vaga|vagas|CR|cadastro reserva)\b', re.IGNORECASE)

    for i, linha in enumerate(linhas):
        linha_s = linha.strip()
        if not linha_s or len(linha_s) < 5:
            continue
        # Linha que contém salário
        m_sal = pat_salario.search(linha_s)
        if not m_sal:
            continue
        val = _extrair_valor_salario(f"R$ {m_sal.group(1)}")
        if val < 500:
            continue

        # Tentar extrair nome do cargo da mesma linha ou linha anterior
        cargo_nome = ""
        # Verificar se a linha começa com um nome de cargo (antes do salário)
        antes_salario = linha_s[:m_sal.start()].strip()
        if antes_salario and len(antes_salario) > 3 and antes_salario[0].isupper():
            cargo_nome = re.sub(r'[\|\t]+.*$', '', antes_salario).strip()
        elif i > 0:
            linha_ant = linhas[i - 1].strip()
            if linha_ant and len(linha_ant) > 3 and linha_ant[0].isupper():
                cargo_nome = re.sub(r'[\|\t]+.*$', '', linha_ant).strip()

        if not cargo_nome:
            continue

        # Extrair vagas da linha
        m_vagas = pat_vagas.search(linha_s)
        vagas = m_vagas.group(1) if m_vagas else ""

        resultados.append({
            "cargo": cargo_nome,
            "salario_texto": f"R$ {m_sal.group(1)}",
            "salario_valor": val,
            "vagas": vagas,
        })

    return resultados


def _baixar_e_parsear_pdf(url_pdf: str) -> List[Dict]:
    """Baixa um PDF e extrai a tabela de cargos e salários."""
    try:
        r = requests.get(url_pdf, headers=HEADERS, timeout=30, verify=False)
        if r.status_code != 200:
            logger.debug(f"PDF não encontrado: {url_pdf} ({r.status_code})")
            return []

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(r.content)
            tmp_pdf = f.name

        try:
            result = subprocess.run(
                ["pdftotext", "-layout", tmp_pdf, "-"],
                capture_output=True, text=True, timeout=30
            )
            texto_layout = result.stdout

            cargos = _parsear_tabela_layout(texto_layout)

            if not cargos:
                cargos = _parsear_formato_numerado(texto_layout)

            if not cargos:
                cargos = _parsear_tabela_generica(texto_layout)

            if not cargos:
                result2 = subprocess.run(
                    ["pdftotext", tmp_pdf, "-"],
                    capture_output=True, text=True, timeout=30
                )
                cargos = _parsear_formato_numerado(result2.stdout)
                if not cargos:
                    cargos = _parsear_tabela_generica(result2.stdout)
                if not cargos:
                    cargos = _parsear_texto_simples(result2.stdout)

            return cargos
        finally:
            try:
                os.unlink(tmp_pdf)
            except Exception:
                pass

    except Exception as exc:
        logger.debug(f"Erro ao processar PDF {url_pdf}: {exc}")
        return []


def _gdrive_para_download(url: str) -> Optional[str]:
    """
    Converte um link de visualização do Google Drive para link de download direto.
    """
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
    if m:
        file_id = m.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return None


def _encontrar_pdf_edital(url_pagina_banca: str) -> Optional[str]:
    """
    Acessa a página da banca e encontra o link do PDF do edital/quadro de vagas.
    Prioriza: Quadro Geral de Vagas > Edital retificado > Edital original.
    Suporta: links diretos .pdf, Google Drive, e outros hosts de documentos.
    """
    try:
        r = requests.get(url_pagina_banca, headers=HEADERS, timeout=20, verify=False)
        if r.status_code != 200:
            return None

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        prioridades = [
            ["quadro geral de vagas", "retificado"],
            ["quadro geral de vagas"],
            ["quadro de vagas"],
            ["anexo i"],
            ["edital", "retificado"],
            ["edital do concurso"],
            ["edital completo"],
            ["edital"],
        ]

        links_pdf = []
        links_gdrive = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            txt = a.get_text(strip=True).lower()
            if href.lower().endswith(".pdf") or ".pdf" in href.lower():
                links_pdf.append((txt, href if href.startswith("http") else url_pagina_banca.rstrip("/") + "/" + href.lstrip("/")))
            elif "drive.google.com" in href:
                dl_url = _gdrive_para_download(href)
                if dl_url:
                    links_gdrive.append((txt, dl_url))

        for criterios in prioridades:
            for txt, href in links_pdf:
                if all(c in txt for c in criterios):
                    return href

        for criterios in prioridades:
            for txt, href in links_gdrive:
                if all(c in txt for c in criterios):
                    return href

        for txt, href in links_pdf:
            if any(k in txt for k in ["edital", "concurso", "vagas", "anexo"]):
                return href

        for txt, href in links_gdrive:
            if any(k in txt for k in ["edital", "concurso", "vagas", "anexo", "completo"]):
                return href

        return None

    except Exception as exc:
        logger.debug(f"Erro ao buscar PDF em {url_pagina_banca}: {exc}")
        return None


def _encontrar_todos_pdfs_edital(url_pagina_banca: str) -> List[str]:
    """
    Retorna todos os links de PDFs de editais encontrados na página.
    """
    try:
        r = requests.get(url_pagina_banca, headers=HEADERS, timeout=20, verify=False)
        if r.status_code != 200:
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        pdfs = []
        gdrive = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf") or ".pdf" in href.lower():
                url_pdf = href if href.startswith("http") else url_pagina_banca.rstrip("/") + "/" + href.lstrip("/")
                if url_pdf not in pdfs:
                    pdfs.append(url_pdf)
            elif "drive.google.com" in href:
                dl_url = _gdrive_para_download(href)
                if dl_url and dl_url not in gdrive:
                    gdrive.append(dl_url)

        return pdfs + gdrive

    except Exception as exc:
        logger.debug(f"Erro ao buscar PDFs em {url_pagina_banca}: {exc}")
        return []


def _buscar_entidade_organizadora(orgao: str, banca: str, texto_artigo: str) -> Optional[str]:
    """
    Quando não há link direto de edital, tenta localizar o site da entidade
    organizadora do concurso para encontrar o edital.

    Estratégia:
    1. Se a banca é conhecida, acessar o site da banca e buscar o concurso.
    2. Se não, fazer busca web pelo nome do órgão + "concurso público" + "edital".
    3. Retornar a URL da página do concurso na entidade organizadora.
    """
    import time

    # Mapa de bancas conhecidas com suas URLs de listagem de concursos abertos
    BANCAS_URLS = {
        "IBFC": "https://concursos.ibfc.org.br/",
        "IDECAN": "https://idecan.org.br/",
        "AOCP": "https://www.institutoaocp.org.br/",
        "IADES": "https://www.iades.com.br/inscricao/?v=andamento",
        "FGV": "https://conhecimento.fgv.br/concursos/abertos",
        "QUADRIX": "https://ps-adm-861.selecao.net.br/",
        "FEPESE": "https://fepese.org.br/concursos/",
        "FAPEC": "https://portal.concurso.fundacaofapec.org.br/",
        "CEBRASPE": "https://www.cebraspe.org.br/concursos",
        "CESGRANRIO": "https://www.cesgranrio.org.br/eventos/concursos/",
        "IBAM": "https://www.ibam.org.br/concursos",
        "OBJETIVA": "https://www.objetiva.srv.br/concurso/",
        "COPS-UEL": "https://cops.uel.br/",
        "NC-UFPR": "https://www.nc.ufpr.br/",
    }

    session = requests.Session()
    session.verify = False

    banca_upper = (banca or "").upper()

    # Se a banca é conhecida, buscar no site da banca
    if banca_upper in BANCAS_URLS:
        url_banca = BANCAS_URLS[banca_upper]
        try:
            r = session.get(url_banca, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, "html.parser")
                orgao_norm = _normalizar_texto(orgao)
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    txt = _normalizar_texto(a.get_text(strip=True))
                    if not href or not txt:
                        continue
                    # Verificar se o link menciona o órgão
                    palavras_orgao = [p for p in orgao_norm.split() if len(p) >= 4]
                    if palavras_orgao and any(p in txt for p in palavras_orgao):
                        if not href.startswith("http"):
                            base = re.match(r'https?://[^/]+', url_banca)
                            href = (base.group(0) if base else "") + "/" + href.lstrip("/")
                        logger.info(f"[ENTIDADE] Concurso encontrado em {banca_upper}: {href}")
                        return href
        except Exception as exc:
            logger.debug(f"[ENTIDADE] Erro ao buscar em {banca_upper}: {exc}")

    # Busca web: nome do órgão + "concurso público" + "edital"
    try:
        query = f"{orgao} concurso público edital inscrições abertas 2025 2026"
        url_busca = f"https://www.google.com/search?q={requests.utils.quote(query)}&num=5"
        r = session.get(url_busca, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        }, timeout=15)
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            # Extrair URLs dos resultados de busca
            ignorar = ["google", "facebook", "instagram", "twitter", "youtube",
                       "pciconcursos", "estrategia", "grancursos", "qconcursos",
                       "jcconcursos", "concursosnobrasil", "aprovaconcursos"]
            for a in soup.find_all("a", href=True):
                href = a["href"]
                # Google encapsula URLs em /url?q=
                if "/url?q=" in href:
                    href = re.search(r'/url\?q=([^&]+)', href)
                    if href:
                        href = requests.utils.unquote(href.group(1))
                    else:
                        continue
                if not href.startswith("http"):
                    continue
                if any(ig in href.lower() for ig in ignorar):
                    continue
                # Verificar se a URL parece ser de um concurso
                if any(k in href.lower() for k in ["concurso", "edital", "inscri", "seletivo", "processo"]):
                    logger.info(f"[ENTIDADE] URL encontrada via busca web: {href}")
                    return href
    except Exception as exc:
        logger.debug(f"[ENTIDADE] Erro na busca web: {exc}")

    return None


def _normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparação: minúsculas, sem acentos."""
    import unicodedata
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r'\s+', ' ', texto).strip()


def _extrair_cidades_do_texto(texto: str) -> List[str]:
    """
    Extrai cidades de lotação mencionadas no texto do edital ao redor do cargo.
    Busca padrões como "lotação: Cidade/UF", "município de Cidade", etc.
    """
    cidades = []
    padroes = [
        r'lota[çc][aã]o[:\s]+([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*[/\-]\s*([A-Z]{2})',
        r'munic[íi]pio[:\s]+(?:de\s+)?([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*[/\-]\s*([A-Z]{2})',
        r'cidade[:\s]+([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*[/\-]\s*([A-Z]{2})',
        r'\b([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*/\s*([A-Z]{2})\b',
    ]
    for padrao in padroes:
        for m in re.finditer(padrao, texto):
            cidade = m.group(1).strip()
            uf = m.group(2).strip()
            entrada = f"{cidade}/{uf}"
            if entrada not in cidades:
                cidades.append(entrada)
    return cidades[:5]  # Máximo 5 cidades por cargo


def _verificar_mestrado_doutorado_trecho(trecho: str) -> bool:
    """
    Verifica se o trecho do edital exige mestrado ou doutorado para o cargo.
    Retorna True se exige (cargo deve ser descartado).
    """
    trecho_lower = trecho.lower()
    return any(t in trecho_lower for t in _TERMOS_POS_STRICTO)


def extrair_cargos_do_edital(url_pagina_banca: str) -> "Tuple[List[Dict], bool]":
    """
    Função principal: dado o URL da página do concurso na banca,
    localiza o PDF do edital, extrai e retorna a lista de cargos com salários.

    Retorna tupla (cargos, edital_encontrado):
      - cargos: lista de dicts [{cargo, vagas, formacao, salario_texto, salario_valor, categoria, cidades}]
        (apenas cargos de interesse com salário >= R$ 10.000)
      - edital_encontrado: True se o PDF foi localizado e analisado (mesmo sem cargos relevantes),
        False se o PDF não foi encontrado ou não pôde ser extraído (não exclui o concurso).
    """
    if not url_pagina_banca:
        return [], False

    url_pdf = _encontrar_pdf_edital(url_pagina_banca)
    if not url_pdf:
        logger.debug(f"PDF do edital não encontrado em: {url_pagina_banca}")
        return [], False

    logger.info(f"Processando edital: {url_pdf}")
    todos_cargos = _baixar_e_parsear_pdf(url_pdf)

    if not todos_cargos:
        # PDF foi encontrado mas o parser não extraiu cargos (layout não reconhecido ou
        # PDF é imagem/escaneado). Retornamos False para NÃO excluir o concurso —
        # não podemos confirmar ausência de cargos relevantes quando a leitura falhou.
        return [], False

    cargos_relevantes = []
    for c in todos_cargos:
        categoria = _classificar_cargo(c["cargo"])
        if categoria is None:
            continue
        if c["salario_valor"] < SALARIO_MINIMO:
            continue
        cargos_relevantes.append({
            "cargo": c["cargo"],
            "vagas": c.get("vagas", ""),
            "formacao": c.get("formacao", ""),
            "salario_texto": c["salario_texto"],
            "salario_valor": c["salario_valor"],
            "categoria": categoria,
            "cidades": c.get("cidades", []),
        })

    ordem = {"veterinario": 0, "qualquer_area": 1, "nivel_medio": 2}
    cargos_relevantes.sort(key=lambda x: (ordem.get(x["categoria"], 9), -x["salario_valor"]))

    # edital_encontrado=True: PDF foi analisado (cargos podem ser vazios — nenhum relevante)
    return cargos_relevantes, True


def buscar_salario_por_cargo(url_pagina_banca: str, cargos_artigo: List[Dict],
                              orgao: str = "", banca: str = "",
                              texto_artigo: str = "") -> "Tuple[List[Dict], bool]":
    """
    Dado o URL da página do concurso na banca e a lista de cargos já identificados
    no artigo, busca o salário de cada cargo no texto do edital.

    Se não encontrar edital no link fornecido, tenta buscar na entidade organizadora.

    Retorna tupla (cargos, edital_encontrado):
      - cargos: [{cargo, vagas, formacao, salario_texto, salario_valor, categoria, cidades}]
        (apenas cargos de interesse com salário >= R$ 10.000)
      - edital_encontrado: True se o PDF foi localizado e o texto extraído com sucesso
        (mesmo que nenhum cargo relevante tenha sido encontrado), False caso contrário.
        Use False para NÃO excluir o concurso por falta de edital verificável.
    """
    if not url_pagina_banca and not (orgao or banca):
        return [], False

    # Buscar todos os PDFs do artigo
    urls_pdf = []
    if url_pagina_banca:
        # Se a URL já é um PDF direto, usar diretamente sem tentar parsear como HTML
        _url_lower = url_pagina_banca.lower().split('?')[0]
        if _url_lower.endswith('.pdf') or '.pdf' in _url_lower:
            urls_pdf = [url_pagina_banca]
        else:
            urls_pdf = _encontrar_todos_pdfs_edital(url_pagina_banca)
            if not urls_pdf:
                url_pdf = _encontrar_pdf_edital(url_pagina_banca)
                if url_pdf:
                    urls_pdf = [url_pdf]

    # Se não encontrou PDF no link direto, buscar na entidade organizadora
    if not urls_pdf and (orgao or banca):
        logger.info(f"[ENTIDADE] Sem edital em {url_pagina_banca} — buscando em {banca or orgao}")
        url_entidade = _buscar_entidade_organizadora(orgao, banca, texto_artigo)
        if url_entidade:
            urls_pdf = _encontrar_todos_pdfs_edital(url_entidade)
            if not urls_pdf:
                url_pdf = _encontrar_pdf_edital(url_entidade)
                if url_pdf:
                    urls_pdf = [url_pdf]

    if not urls_pdf:
        logger.debug(f"Nenhum PDF encontrado para: {orgao or url_pagina_banca}")
        return [], False

    logger.info(f"Processando {len(urls_pdf)} edital(is) para busca por cargo")

    # Baixar e extrair texto de todos os PDFs
    texto_pdf_total = ""
    for url_pdf in urls_pdf[:5]:
        try:
            r = requests.get(url_pdf, headers=HEADERS, timeout=30, verify=False)
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
                f.write(r.content)
                tmp = f.name
            result = subprocess.run(['pdftotext', '-layout', tmp, '-'],
                                    capture_output=True, text=True, timeout=60)
            os.unlink(tmp)
            texto_pdf_total += result.stdout + "\n"
        except Exception as exc:
            logger.debug(f"Erro ao baixar/extrair PDF {url_pdf}: {exc}")

    texto_pdf = texto_pdf_total
    if not texto_pdf.strip():
        return [], False

    # Para cada cargo do artigo, buscar o salário no texto do edital
    cargos_com_salario = []
    pat_salario = re.compile(r'R\$\s*([\d.]+,[\d]{2})')

    for cargo_info in cargos_artigo:
        cargo_nome = cargo_info.get('cargo', '')
        categoria = _classificar_cargo(cargo_nome)
        if categoria is None:
            continue

        palavras = [p for p in cargo_nome.split() if len(p) > 3]
        if not palavras:
            continue

        # Padrão 1: palavras do cargo separadas por espaço ou hífen (ex: Médico Veterinário ou Médico-Veterinário)
        termos_busca = palavras[:3]
        padrao_cargo = re.compile(
            r'(?i)' + r'[\s\-]+'.join(re.escape(t) for t in termos_busca)
        )

        match = padrao_cargo.search(texto_pdf)
        if not match:
            # Padrão 2: apenas a primeira palavra significativa
            padrao_simples = re.compile(r'(?i)\b' + re.escape(palavras[0]) + r'\b')
            match = padrao_simples.search(texto_pdf)

        if not match:
            # Padrão 3: qualquer palavra com 5+ chars do nome do cargo
            for p in palavras:
                if len(p) >= 5:
                    m_alt = re.search(r'(?i)' + re.escape(p[:5]), texto_pdf)
                    if m_alt:
                        match = m_alt
                        break

        if not match:
            continue

        # Ampliar o trecho de contexto para capturar mais informações
        inicio = max(0, match.start() - 500)
        fim = min(len(texto_pdf), match.end() + 1500)
        trecho = texto_pdf[inicio:fim]

        # Verificar se o cargo exige mestrado ou doutorado
        if _verificar_mestrado_doutorado_trecho(trecho):
            logger.info(f"[FILTRO] Cargo descartado (mestrado/doutorado): {cargo_nome}")
            continue

        # Buscar salário APÓS o cargo no trecho (posição relativa ao match)
        # O trecho começa 500 chars antes do match; o cargo está ~na posição 500 do trecho.
        # Buscamos o primeiro salário encontrado DEPOIS do início do match no trecho.
        cargo_pos_no_trecho = min(500, match.start())  # posição aproximada do cargo no trecho
        salarios_apos_cargo = []
        salarios_antes_cargo = []
        for m_sal in pat_salario.finditer(trecho):
            val_str = m_sal.group(1).replace('.', '').replace(',', '.')
            try:
                val = float(val_str)
                if val > 500:
                    if m_sal.start() >= cargo_pos_no_trecho:
                        salarios_apos_cargo.append((m_sal.start(), val, f"R$ {m_sal.group(1)}"))
                    else:
                        salarios_antes_cargo.append((m_sal.start(), val, f"R$ {m_sal.group(1)}"))
            except ValueError:
                pass

        # Preferência: primeiro salário APÓS o nome do cargo (mais provável ser o salário do cargo)
        # Se não encontrar, usar o mais próximo antes do cargo
        # NÃO usar fallback global (causa todos os cargos terem o mesmo salário máximo do doc)
        if salarios_apos_cargo:
            salarios_apos_cargo.sort(key=lambda x: x[0])  # ordenar por posição
            _, salario_valor, salario_texto = salarios_apos_cargo[0]
        elif salarios_antes_cargo:
            salarios_antes_cargo.sort(key=lambda x: -x[0])  # mais próximo antes = maior posição
            _, salario_valor, salario_texto = salarios_antes_cargo[0]
        else:
            continue
        if salario_valor < SALARIO_MINIMO:
            continue

        # Extrair escolaridade exigida do texto do edital
        escolaridade_edital = _extrair_escolaridade_do_trecho(trecho)

        # Verificar se a escolaridade exige mestrado/doutorado
        if escolaridade_edital and any(t in escolaridade_edital.lower() for t in ["mestrado", "doutorado", "mestre", "doutor"]):
            logger.info(f"[FILTRO] Cargo descartado (escolaridade mestrado/doutorado): {cargo_nome}")
            continue

        # Reclassificar categoria com base na escolaridade real do edital
        if escolaridade_edital:
            categoria_real = _classificar_por_escolaridade(escolaridade_edital)
            if categoria_real is None:
                continue
            categoria = categoria_real
            formacao_final = escolaridade_edital
        else:
            # Fallback: derivar formação da categoria (nunca usar nome do cargo como formação)
            _FORMACAO_POR_CAT = {
                "veterinario":   "Médico Veterinário",
                "qualquer_area": "Nível Superior (qualquer curso)",
                "nivel_medio":   "Nível Médio",
            }
            formacao_final = _FORMACAO_POR_CAT.get(categoria, cargo_info.get('formacao', '') or cargo_nome)

        # Extrair cidades de lotação do trecho (e fallback no texto completo)
        cidades = _extrair_cidades_do_texto(trecho)
        # Não usar fallback no texto global: causa cidade de outro cargo/seção ser atribuída

        # Extrair número de vagas do trecho
        vagas_trecho = cargo_info.get('vagas', '')
        if not vagas_trecho:
            m_vagas = re.search(r'\b(\d{1,4})\s*(?:vaga|vagas)\b', trecho, re.IGNORECASE)
            if m_vagas:
                vagas_trecho = m_vagas.group(1)
            else:
                m_cr = re.search(r'\bCR\b|\bcadastro reserva\b', trecho, re.IGNORECASE)
                if m_cr:
                    vagas_trecho = "CR"
        # Fallback global de vagas
        if not vagas_trecho:
            m_vagas_g = re.search(
                r'(?i)vagas?[:\s]+(?:s[aã]o\s+)?(?:de\s+)?(\d{1,4})\s*(?:\(|vagas?)',
                texto_pdf
            )
            if m_vagas_g:
                vagas_trecho = m_vagas_g.group(1)
            else:
                m_vagas_g2 = re.search(r'\b(\d{1,4})\s*\(\w+\)\s*vagas?', texto_pdf, re.IGNORECASE)
                if m_vagas_g2:
                    vagas_trecho = m_vagas_g2.group(1)

        cargos_com_salario.append({
            'cargo': cargo_nome,
            'vagas': vagas_trecho,
            'formacao': formacao_final,
            'salario_texto': salario_texto,
            'salario_valor': salario_valor,
            'categoria': categoria,
            'cidades': cidades,
        })

    # edital_encontrado=True: texto do PDF foi extraído e analisado (mesmo se nenhum cargo relevante)
    return cargos_com_salario, True


def _extrair_escolaridade_do_trecho(trecho: str) -> str:
    """
    Extrai o requisito de escolaridade do trecho de texto do edital ao redor do cargo.
    Retorna a string de escolaridade encontrada, ou '' se não encontrada.
    Baseia-se exclusivamente no texto do edital (dado verificado).
    """
    trecho_lower = trecho.lower()

    padroes = [
        # Mestrado/Doutorado (descartar — listados primeiro para prioridade)
        (r'doutorado|doutor\b|ph\.?d', 'Doutorado'),
        (r'mestrado|mestre\b|stricto sensu', 'Mestrado'),
        # Veterinário
        (r'médico veterinário|medico veterinario|veterinário|veterinario', 'Médico Veterinário'),
        # Formações específicas indesejadas
        (r'medicina|médico |medico ', 'Medicina'),
        (r'direito|advocacia|advogado', 'Direito'),
        (r'engenharia|engenheiro', 'Engenharia'),
        (r'odontologia|dentista|odontol', 'Odontologia'),
        (r'farmácia|farmacêutico', 'Farmácia'),
        (r'enfermagem|enfermeiro', 'Enfermagem'),
        (r'psicologia|psicólogo', 'Psicologia'),
        (r'fisioterapia|fisioterapeuta', 'Fisioterapia'),
        (r'nutrição|nutricionista', 'Nutrição'),
        (r'ciências contábeis|contabilidade|contador', 'Ciências Contábeis'),
        (r'economia|economista', 'Economia'),
        (r'arquitetura|arquiteto', 'Arquitetura'),
        (r'biologia|biólogo', 'Biologia'),
        (r'química|químico', 'Química'),
        (r'geologia|geólogo', 'Geologia'),
        (r'serviço social|assistente social', 'Serviço Social'),
        (r'pedagogia|pedagogo', 'Pedagogia'),
        (r'licenciatura', 'Licenciatura'),
        (r'fonoaudiologia|fonoaudiólogo', 'Fonoaudiologia'),
        (r'terapia ocupacional|terapeuta ocupacional', 'Terapia Ocupacional'),
        # Nível superior genérico
        (r'qualquer curso|qualquer área|qualquer area|qualquer graduação|qualquer graduacao', 'Nível Superior (qualquer curso)'),
        (r'nível superior|nivel superior|ensino superior|graduação superior|curso superior', 'Nível Superior (qualquer curso)'),
        (r'bacharel|bacharelado', 'Nível Superior (qualquer curso)'),
        # Nível médio
        (r'nível médio|nivel medio|ensino médio|ensino medio', 'Nível Médio'),
        # Nível fundamental
        (r'nível fundamental|ensino fundamental', 'Nível Fundamental'),
    ]

    for padrao, descricao in padroes:
        if re.search(padrao, trecho_lower):
            return descricao

    return ''


def _classificar_por_escolaridade(escolaridade: str) -> Optional[str]:
    """
    Classifica a categoria com base na escolaridade extraída do edital.
    Retorna: 'veterinario', 'qualquer_area', 'nivel_medio', ou None (indesejada).
    """
    esc = escolaridade.lower()

    # Mestrado/Doutorado: descartar
    if any(t in esc for t in ['mestrado', 'doutorado', 'mestre', 'doutor', 'stricto']):
        return None

    if 'veterinário' in esc or 'veterinario' in esc:
        return 'veterinario'

    indesejadas = [
        'medicina', 'direito', 'engenharia', 'odontologia', 'farmácia',
        'enfermagem', 'psicologia', 'fisioterapia', 'nutrição',
        'ciências contábeis', 'economia', 'arquitetura', 'biologia',
        'química', 'geologia', 'serviço social', 'pedagogia',
        'licenciatura', 'fonoaudiologia', 'terapia ocupacional',
    ]
    if any(i in esc for i in indesejadas):
        return None

    if 'nível superior' in esc or 'qualquer curso' in esc:
        return 'qualquer_area'

    if 'nível médio' in esc or 'ensino médio' in esc:
        return 'nivel_medio'

    if 'nível fundamental' in esc or 'ensino fundamental' in esc:
        return None

    return 'qualquer_area'


def label_categoria(categoria: str) -> str:
    """Retorna rótulo legível para a categoria do cargo."""
    return {
        "veterinario": "Médico Veterinário",
        "qualquer_area": "Qualquer área de formação",
        "nivel_medio": "Nível Médio",
    }.get(categoria, "")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.INFO)

    # Teste com Riversul
    url = "https://www.institutodom.com/informacoes/74/"
    print(f"Testando: {url}")
    cargos = extrair_cargos_do_edital(url)
    print(f"Cargos relevantes encontrados: {len(cargos)}")
    for c in cargos:
        print(f"  [{c['categoria']}] {c['cargo']}: {c['salario_texto']} | Vagas: {c.get('vagas','')} | Cidades: {c.get('cidades','')}")
