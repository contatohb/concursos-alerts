#!/usr/bin/env python3
"""
Monitor de novos concursos públicos.

Critérios de alerta:
  - Salário >= R$ 10.000/mês  OU
  - Cargo de Médico Veterinário  OU
  - Nível médio  OU
  - Nível superior (qualquer curso)

Fontes:
  - PCI Concursos (pciconcursos.com.br)
  - Concursos no Brasil (concursosnobrasil.com.br)
  - API deno (concursos-api.deno.dev) — todos os estados
  - Blog Convet (blog.preparatorioconvet.com.br) — especializado em veterinários

Cada concurso retornado contém:
  orgao, cargo, nivel, salario, vagas, banca, cidade, estado,
  data_inscricao_inicio, data_inscricao_fim, data_prova, link_inscricao, link_detalhe
"""
from __future__ import annotations

import logging
import re
import time
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

try:
    from banca_links import buscar_link_inscricao, detectar_banca
    _BANCA_LINKS_OK = True
except ImportError:
    _BANCA_LINKS_OK = False

try:
    from edital_parser import extrair_cargos_do_edital, buscar_salario_por_cargo, label_categoria
    _EDITAL_PARSER_OK = True
except ImportError:
    _EDITAL_PARSER_OK = False

try:
    from enriquecedor import enriquecer_concurso as _enriquecer_cidade_inscricao
    _ENRIQUECEDOR_OK = True
except ImportError:
    _ENRIQUECEDOR_OK = False

try:
    from scraper_convet_blog import scrape_convet_blog
    _CONVET_BLOG_OK = True
except ImportError:
    _CONVET_BLOG_OK = False

try:
    from scrapers_extras import scrape_todas_fontes_extras
    _SCRAPERS_EXTRAS_OK = True
except ImportError:
    _SCRAPERS_EXTRAS_OK = False

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
TIMEOUT = 20
SLEEP = 0.4

# ─────────────────────────────────────────────────────────────────
# Critérios de filtro
# ─────────────────────────────────────────────────────────────────

SALARIO_MINIMO = 10_000.0  # R$

CARGOS_VETERINARIO = [
    "médico veterinário", "medico veterinario", "veterinário", "veterinario",
    "med. veterinário", "med. veterinario",
]

# Indicadores de que o cargo exige formacao especifica (excluir nesses casos)
# Usados para identificar concursos que aceitam "qualquer curso superior"
CARGOS_FORMACAO_ESPECIFICA = [
    # Medicina humana (NÃO veterinária — essa é tratada separadamente)
    "médico ", "medico ", "médico(", "medico(",
    "cirurgião", "cirurgiao",
    "pediatra", "cardiologista", "ginecologista", "obstetra",
    "oftalmologista", "ortopedista", "otorrinolaringologista",
    "urologista", "psiquiatra", "neurologista",
    "anestesiologista", "radiologista", "dermatologista",
    "infectologista", "nefrologista", "reumatologista",
    "endocrinologista", "oncologista", "hematologista",
    "pneumologista", "gastroenterologista",
    "médico esf", "medico esf",
    "médico do trabalho", "medico do trabalho",
    "médico clínico", "medico clinico",
    # Outras formações específicas indesejadas
    "engenheiro", "advogado", "dentista", "odontolog",
    "farmacê", "enfermeiro", "psicolog", "fisiotera", "nutricion",
    "contador ", "economista", "arquiteto", "biológ", "quimico",
    "geolog", "assistente social", "pedagog", "professor", "docente",
    "procurador", "defensor", "promotor", "juiz", "delegado",
    "policial", "bombeiro",
    "fonoaudílogo", "terapeuta ocupacional",
]

# Termos que indicam que o cargo aceita qualquer curso superior
CARGOS_QUALQUER_SUPERIOR = [
    "nível superior", "nivel superior", "qualquer curso", "qualquer graduação",
    "qualquer graduacao", "bacharel", "ensino superior", "graduação",
    "qualquer área", "qualquer area", "formação superior", "curso superior",
    "analista", "assistente", "assessor", "coordenador", "gerente",
    "supervisor", "técnico de nível superior", "tecnico de nivel superior",
    "vários cargos", "varios cargos",
    "técnico administrativo", "tecnico administrativo",
    "assistente administrativo", "agente administrativo",
    "agente de desenvolvimento", "servidor",
]

# Termos que indicam nível médio
CARGOS_NIVEL_MEDIO = [
    "nível médio", "nivel medio", "ensino médio", "ensino medio",
    "técnico de nível médio", "tecnico de nivel medio",
    "agente", "auxiliar", "assistente técnico", "assistente tecnico",
    "operador", "atendente", "motorista",
    "escriturário", "escriturario", "recepcionista", "telefonista",
    "guarda ", "vigilante", "inspetor",
    "agente de combate", "agente comunitário",
    "agente de saúde", "agente de endemias",
    "técnico em", "tecnico em",
    "auxiliar de", "assistente de",
    "operador de",
]


def _extrair_salario(texto: str) -> Optional[float]:
    """Extrai o maior valor de salário mencionado no texto."""
    # Padrões: R$ 10.000,00 | R$ 10.000 | 10.000,00 | 10000
    padroes = re.findall(r'R\$\s*([\d.,]+)', texto, re.IGNORECASE)
    if not padroes:
        padroes = re.findall(r'([\d]{2,3}\.[\d]{3}(?:,[\d]{2})?)', texto)
    valores = []
    for p in padroes:
        try:
            v = float(p.replace('.', '').replace(',', '.'))
            valores.append(v)
        except ValueError:
            pass
    return max(valores) if valores else None


# Meses por extenso para normalização de datas
_MESES_PT = {
    "janeiro": "01", "fevereiro": "02", "março": "03", "marco": "03",
    "abril": "04", "maio": "05", "junho": "06", "julho": "07",
    "agosto": "08", "setembro": "09", "outubro": "10",
    "novembro": "11", "dezembro": "12",
    "jan": "01", "fev": "02", "mar": "03", "abr": "04",
    "mai": "05", "jun": "06", "jul": "07", "ago": "08",
    "set": "09", "out": "10", "nov": "11", "dez": "12",
}


def normalizar_data(texto: str) -> str:
    """
    Normaliza qualquer representação de data para dd/mm/aaaa.
    Aceita:
      - dd/mm/aaaa ou dd/mm/aa
      - dd/mm (sem ano — completa com ano corrente)
      - dd de mês de aaaa (por extenso)
      - dd de mês (sem ano)
    Retorna a string original se não conseguir parsear.
    """
    if not texto:
        return texto
    t = texto.strip()
    from datetime import date as _date
    ano_atual = str(_date.today().year)
    # Padrão: dd/mm/aaaa ou dd/mm/aa
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', t)
    if m:
        d, mes, a = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
        if len(a) == 2:
            a = "20" + a
        return f"{d}/{mes}/{a}"
    # Padrão: dd/mm (sem ano)
    m = re.match(r'^(\d{1,2})/(\d{1,2})$', t)
    if m:
        d, mes = m.group(1).zfill(2), m.group(2).zfill(2)
        return f"{d}/{mes}/{ano_atual}"
    # Padrão: dd de mês de aaaa
    m = re.match(
        r'^(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})$', t, re.IGNORECASE
    )
    if m:
        d = m.group(1).zfill(2)
        mes_nome = m.group(2).lower()
        mes = _MESES_PT.get(mes_nome, "")
        a = m.group(3)
        if mes:
            return f"{d}/{mes}/{a}"
    # Padrão: dd de mês (sem ano)
    m = re.match(r'^(\d{1,2})\s+de\s+(\w+)$', t, re.IGNORECASE)
    if m:
        d = m.group(1).zfill(2)
        mes_nome = m.group(2).lower()
        mes = _MESES_PT.get(mes_nome, "")
        if mes:
            return f"{d}/{mes}/{ano_atual}"
    return t  # retorna original se não reconhecido


def _is_veterinario(texto: str) -> bool:
    tl = texto.lower()
    return any(c in tl for c in CARGOS_VETERINARIO)


def _is_qualquer_superior(texto: str) -> bool:
    """Verifica se o cargo aceita qualquer curso superior (sem exigir formação específica)."""
    tl = texto.lower()
    # Deve ter indicador de superior
    tem_superior = any(t in tl for t in CARGOS_QUALQUER_SUPERIOR)
    if not tem_superior:
        return False
    # Não deve exigir formação específica (exceto veterinário, que tem critério próprio)
    exige_especifica = any(f in tl for f in CARGOS_FORMACAO_ESPECIFICA)
    return not exige_especifica


def _is_nivel_medio(texto: str) -> bool:
    """Verifica se o cargo é de nível médio (sem exigir formação específica indesejada)."""
    tl = texto.lower()
    tem_medio = any(n in tl for n in CARGOS_NIVEL_MEDIO)
    if not tem_medio:
        return False
    # Não deve exigir formação específica indesejada
    exige_especifica = any(f in tl for f in CARGOS_FORMACAO_ESPECIFICA)
    return not exige_especifica


def _atende_criterios(concurso: Dict) -> bool:
    """
    Filtro: alerta quando (A OU B OU C) E salário >= R$ 10.000
    para o MESMO cargo/vaga:

      A. Cargo de Médico Veterinário
      B. Cargo de nível superior sem exigência de formação específica
         (qualquer curso, analista, assessor, vários cargos, etc.)
      C. Cargo de nível médio

      E salário do cargo >= R$ 10.000

    Exemplos que PASSAM:
      - Veterinário com R$ 12.000 -> SIM
      - Analista (qualquer curso) com R$ 15.000 -> SIM
      - Auxiliar administrativo (nível médio) com R$ 11.000 -> SIM
      - Vários cargos até R$ 18.000 -> SIM (pode ter vaga compatível)

    Exemplos que NÃO PASSAM:
      - Engenheiro com R$ 20.000 -> NÃO (formação específica)
      - Veterinário com R$ 5.000 -> NÃO (salário abaixo)
      - Qualquer cargo com R$ 8.000 -> NÃO (salário abaixo)
    """
    cargo = concurso.get("cargo", "")
    titulo = concurso.get("titulo", "")
    nivel = concurso.get("nivel", "")
    vagas = concurso.get("vagas", "")

    # Texto representativo do cargo (sem misturar com salário de outros cargos)
    texto_cargo = f"{cargo} {titulo} {nivel} {vagas}"

    # Verificar se o cargo se enquadra em alguma das categorias
    eh_veterinario = _is_veterinario(texto_cargo)
    eh_qualquer_superior = _is_qualquer_superior(texto_cargo)
    eh_nivel_medio = _is_nivel_medio(texto_cargo)

    # Extrair salário do cargo
    salario = concurso.get("salario_valor")
    if not salario:
        texto_salario = f"{concurso.get('salario_texto', '')} {vagas} {titulo}"
        salario = _extrair_salario(texto_salario)

    if not (eh_veterinario or eh_qualquer_superior or eh_nivel_medio):
        # Cargo não reconhecido pelo pré-filtro.
        # Se tem formação claramente específica indesejada no nome → descartar.
        eh_especifica_indesejada = any(f in texto_cargo.lower() for f in CARGOS_FORMACAO_ESPECIFICA)
        if eh_especifica_indesejada:
            return False
        # Caso contrário: encaminhar para leitura do edital se salário alto.
        # O edital_parser determinará a formação exigida com base no texto do edital.
        if salario and salario >= SALARIO_MINIMO:
            concurso["_verificar_edital"] = True  # Flag: leitura obrigatória do edital
            return True
        return False

    # Salário confirmado >= 10k: passa sempre (qualquer categoria)
    if salario and salario >= SALARIO_MINIMO:
        return True

    # Salário NÃO identificado nas listagens iniciais é comum no PCI/Concursos no Brasil
    # — o salário real só aparece nas páginas de detalhe do edital.
    # Política: incluir todas as categorias reconhecidas para não descartar por falta de dado.
    if salario is None:
        if eh_veterinario:
            return True  # Sempre incluir veterinário para análise manual
        if eh_qualquer_superior:
            return True  # Incluir nível superior sem salário confirmado
        if eh_nivel_medio:
            return True  # Incluir nível médio sem salário confirmado

    return False


# ─────────────────────────────────────────────────────────────────
# Utilitários HTTP
# ─────────────────────────────────────────────────────────────────

def _get(url: str, session: requests.Session) -> Optional[str]:
    try:
        r = session.get(url, timeout=TIMEOUT, headers=HEADERS)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        logger.debug(f"GET {url}: {exc}")
        return None


def _get_json(url: str, session: requests.Session) -> Optional[dict]:
    try:
        r = session.get(url, timeout=TIMEOUT, headers=HEADERS)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.debug(f"GET JSON {url}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────
# Extração de detalhes de uma página de concurso
# ─────────────────────────────────────────────────────────────────

# Mapa de cargo -> formação exigida (para classificar automaticamente)
_FORMACAO_CARGO = [
    # Veterinário
    (["médico veterinário", "medico veterinario", "veterinário", "veterinario"], "Médico Veterinário"),
    # Nível superior com formação específica
    (["engenheiro", "engenheira"], "Engenharia"),
    (["advogado", "advogada", "procurador", "defensor", "promotor"], "Direito"),
    (["médico ", "medico ", "clínico", "cirurgião", "pediatra", "cardiologista",
      "ginecologista", "obstetra", "oftalmologista", "ortopedista",
      "otorrinolaringologista", "urologista", "vascular", "psiquiatra",
      "neurologista", "anestesiologista", "radiologista", "dermatologista",
      "infectologista", "nefrologista", "reumatologista", "endocrinologista",
      "oncologista", "hematologista", "pneumologista", "gastroenterologista",
      "hepatologista", "coloproctologista", "mastologista", "urologia",
      "esf", "trabalho", "do trabalho"], "Medicina"),
    (["dentista", "odontolog", "cirurgião-dentista"], "Odontologia"),
    (["farmacê", "farmacêutico", "farmaceutico"], "Farmácia"),
    (["enfermeiro", "enfermeira"], "Enfermagem"),
    (["psicolog"], "Psicologia"),
    (["fisiotera"], "Fisioterapia"),
    (["nutricion", "nutricionista"], "Nutrição"),
    (["contador", "contadora", "contabilidade"], "Ciências Contábeis"),
    (["economista", "economia"], "Economia"),
    (["arquiteto", "arquiteta", "urbanismo"], "Arquitetura e Urbanismo"),
    (["biólogo", "biologa", "biológ"], "Biologia"),
    (["químico", "quimica", "quimico"], "Química"),
    (["geólogo", "geolog"], "Geologia"),
    (["assistente social"], "Serviço Social"),
    (["pedagogo", "pedagoga", "pedagog"], "Pedagogia"),
    (["professor", "professora", "docente"], "Licenciatura/Pedagogia"),
    (["fonoaudiólogo", "fonoaudióloga", "fonoaudiolog"], "Fonoaudiologia"),
    (["terapeuta ocupacional"], "Terapia Ocupacional"),
    (["assistente social"], "Serviço Social"),
    # Nível superior qualquer curso
    (["analista", "assessor", "coordenador", "gerente", "supervisor",
      "técnico de nível superior", "tecnico de nivel superior",
      "nível superior", "nivel superior", "bacharel"], "Nível Superior (qualquer curso)"),
    # Nível técnico
    (["técnico", "tecnico"], "Nível Técnico"),
    # Nível médio
    (["auxiliar", "agente", "atendente", "operador", "assistente",
      "nível médio", "nivel medio", "ensino médio", "ensino medio",
      "motorista", "servidor geral", "açougueiro", "fiscal"], "Nível Médio"),
    # Fundamental
    (["servente", "gari", "zelador", "merendeira", "cozinheiro",
      "nível fundamental", "nivel fundamental", "ensino fundamental"], "Nível Fundamental"),
]


def _inferir_formacao(cargo: str) -> str:
    """Infere a formação exigida a partir do nome do cargo."""
    cargo_lower = cargo.lower()
    for termos, formacao in _FORMACAO_CARGO:
        if any(t in cargo_lower for t in termos):
            return formacao
    return "Não especificada"


def _extrair_cargos_vagas(texto: str) -> List[Dict]:
    """
    Extrai a lista de cargos com vagas do texto do artigo do PCI.
    Padrão: "Cargo (N vaga(s))" ou "Cargo - N vagas"
    Retorna lista de dicts: [{cargo, vagas, formacao}]
    """
    cargos = []
    # Padrão principal: "Nome do Cargo (N vaga(s))"
    padrao1 = re.findall(
        r'^([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n\(]{3,80})\s*\((\d+)\s*vaga[s]?\)',
        texto, re.MULTILINE | re.IGNORECASE
    )
    for cargo_nome, n_vagas in padrao1:
        cargo_nome = cargo_nome.strip()
        if len(cargo_nome) > 3 and not cargo_nome.lower().startswith(('segundo', 'conforme', 'de acordo')):
            cargos.append({
                "cargo": cargo_nome,
                "vagas": int(n_vagas),
                "formacao": _inferir_formacao(cargo_nome)
            })
    # Padrão alternativo: "Nome do Cargo (CR)" = cadastro reserva
    padrao_cr = re.findall(
        r'^([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n\(]{3,80})\s*\(CR\)',
        texto, re.MULTILINE | re.IGNORECASE
    )
    for cargo_nome in padrao_cr:
        cargo_nome = cargo_nome.strip()
        if len(cargo_nome) > 3:
            cargos.append({
                "cargo": cargo_nome,
                "vagas": "CR",  # Cadastro Reserva
                "formacao": _inferir_formacao(cargo_nome)
            })
    # Padrão alternativo 2: linhas com "- N vagas" ou "N vaga"
    if not cargos:
        padrao2 = re.findall(
            r'^([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n]{3,80})\s*[-–]\s*(\d+)\s*vaga',
            texto, re.MULTILINE | re.IGNORECASE
        )
        for cargo_nome, n_vagas in padrao2:
            cargo_nome = cargo_nome.strip()
            if len(cargo_nome) > 3:
                cargos.append({
                    "cargo": cargo_nome,
                    "vagas": int(n_vagas),
                    "formacao": _inferir_formacao(cargo_nome)
                })
    return cargos


def _extrair_detalhes_pci(url: str, session: requests.Session) -> Dict:
    """Extrai detalhes de uma página de concurso do PCI Concursos."""
    detalhes = {
        "banca": "",
        "cidade": "",
        "estado": "",
        "data_inscricao_inicio": "",
        "data_inscricao_fim": "",
        "data_prova": "",
        "link_inscricao": "",
        "link_edital_pdf": "",
        "cargos_detalhados": [],
    }

    html = _get(url, session)
    if not html:
        return detalhes

    soup = BeautifulSoup(html, "html.parser")
    # Usar \n como separador para preservar estrutura de lista de cargos
    texto = soup.get_text(separator="\n", strip=True)
    texto_flat = soup.get_text(separator=" ", strip=True)  # versão plana para regex de datas

    # Banca organizadora
    for pat in [
        r'(?:banca|organizadora|organização)[:\s]+([A-Z][^\n,;.]{3,60})',
        r'(?:organizada por|realizado por|promovido por)[:\s]+([A-Z][^\n,;.]{3,60})',
    ]:
        m = re.search(pat, texto_flat, re.IGNORECASE)
        if m:
            detalhes["banca"] = m.group(1).strip()[:80]
            break

    # Datas de inscrição (usar texto plano)
    m = re.search(
        r'inscri[\u00e7c][\u00f5o]es[^\d]*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)[^\d]*(?:a|até|ao)[^\d]*(\d{1,2}/\d{1,2}/\d{2,4})',
        texto_flat, re.IGNORECASE
    )
    if m:
        detalhes["data_inscricao_inicio"] = m.group(1)
        detalhes["data_inscricao_fim"] = m.group(2)
    # Padrão alternativo: "até as 23h59 do dia DD/MM/YYYY"
    if not detalhes["data_inscricao_fim"]:
        m2 = re.search(
            r'até as? \d{1,2}h\d{0,2} do dia (\d{1,2} de \w+ de \d{4}|\d{1,2}/\d{1,2}/\d{2,4})',
            texto_flat, re.IGNORECASE
        )
        if m2:
            detalhes["data_inscricao_fim"] = m2.group(1)

    # Data da prova (usar texto plano)
    m = re.search(
        r'(?:prova|exame|aplicação)[^\d]*(\d{1,2}/\d{1,2}/\d{2,4})',
        texto_flat, re.IGNORECASE
    )
    if m:
        detalhes["data_prova"] = m.group(1)

    # Extrair lista de cargos com vagas e formação (usar texto com newlines)
    cargos = _extrair_cargos_vagas(texto)
    if cargos:
        detalhes["cargos_detalhados"] = cargos

    # Banca detectada no texto
    banca_detectada = ""
    if not detalhes["banca"]:
        try:
            banca_detectada = detectar_banca(texto_flat) if _BANCA_LINKS_OK else ""
            if banca_detectada:
                detalhes["banca"] = banca_detectada
        except Exception:
            pass

    # Links de inscrição e edital — separar PDF do edital da página de inscrição
    # Nunca retornar links genéricos (redes sociais, Google, etc.)
    ignorar_dominios = ["pciconcursos", "google", "facebook", "instagram",
                        "twitter", "youtube", "whatsapp", "schema.org", "w3.org"]
    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True).lower()
        if not href.startswith("http"):
            continue
        if any(ig in href.lower() for ig in ignorar_dominios):
            continue
        # PDF direto do edital
        if (href.lower().endswith(".pdf") or ".pdf" in href.lower()) and not detalhes.get("link_edital_pdf"):
            if any(k in txt for k in ["edital", "quadro", "vagas", "anexo"]):
                detalhes["link_edital_pdf"] = href
        # Página de inscrição na banca
        if not detalhes.get("link_inscricao"):
            if any(k in txt for k in ["inscreva", "inscrição", "inscricao", "acesse o edital", "edital", "clique aqui"]):
                if not href.lower().endswith(".pdf"):
                    detalhes["link_inscricao"] = href
    # Guardar o texto plano do artigo para uso posterior (busca de link na banca)
    detalhes["_texto_artigo"] = texto_flat

    # Cidade e estado — estratégia em 3 etapas para evitar cidades erradas:
    # 1. Tentar extrair do orgão (ex: "Prefeitura de São Paulo" → "São Paulo")
    # 2. Buscar padrão Cidade/UF em contexto relevante (próximo a "prefeitura", "município", etc.)
    # 3. Fallback: primeira ocorrência no texto
    _orgao_raw = soup.find("h1") or soup.find("title")
    _orgao_txt = _orgao_raw.get_text(strip=True) if _orgao_raw else ""

    _cidade_encontrada = ""
    _estado_encontrado = ""

    # Etapa 1: extrair do título/h1 da página
    _m1 = re.search(r'([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*[/\-]\s*([A-Z]{2})', _orgao_txt)
    if _m1:
        _cidade_encontrada = _m1.group(1).strip()
        _estado_encontrado = _m1.group(2).strip()

    # Etapa 2: procurar em parágrafos/linhas com palavras-chave de contexto
    if not _cidade_encontrada:
        _ctx_keywords = ["prefeitura", "município", "municipio", "câmara", "governo", "estado de",
                         "concurso público", "concurso publico", "edital"]
        for _linha in texto.splitlines():
            _l = _linha.strip()
            if len(_l) < 10:
                continue
            _l_lower = _l.lower()
            if not any(k in _l_lower for k in _ctx_keywords):
                continue
            _m2 = re.search(r'([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*/\s*([A-Z]{2})', _l)
            if _m2:
                _cidade_encontrada = _m2.group(1).strip()
                _estado_encontrado = _m2.group(2).strip()
                break

    # Etapa 3: fallback — primeira ocorrência no texto completo
    if not _cidade_encontrada:
        _m3 = re.search(r'([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*[/\-]\s*([A-Z]{2})', texto_flat)
        if _m3:
            _cidade_encontrada = _m3.group(1).strip()
            _estado_encontrado = _m3.group(2).strip()

    if _cidade_encontrada:
        detalhes["cidade"] = _cidade_encontrada
    if _estado_encontrado:
        detalhes["estado"] = _estado_encontrado

    return detalhes


def _extrair_detalhes_cnb(url: str, session: requests.Session) -> Dict:
    """Extrai detalhes de uma página do ConcursosNoBrasil."""
    detalhes = {
        "banca": "",
        "cidade": "",
        "estado": "",
        "data_inscricao_inicio": "",
        "data_inscricao_fim": "",
        "data_prova": "",
        "link_inscricao": "",
    }

    html = _get(url, session)
    if not html:
        return detalhes

    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(separator=" ", strip=True)

    # Banca
    for pat in [
        r'(?:banca|organizadora)[:\s]+([A-Z][^\n,;.]{3,60})',
        r'(?:organizada por|realizado por)[:\s]+([A-Z][^\n,;.]{3,60})',
    ]:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            detalhes["banca"] = m.group(1).strip()[:80]
            break

    # Datas de inscrição
    m = re.search(
        r'inscri[çc][õo]es[^\d]*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)[^\d]*(?:a|até)[^\d]*(\d{1,2}/\d{1,2}/\d{2,4})',
        texto, re.IGNORECASE
    )
    if m:
        detalhes["data_inscricao_inicio"] = m.group(1)
        detalhes["data_inscricao_fim"] = m.group(2)

    # Data da prova
    m = re.search(
        r'(?:prova|exame)[^\d]*(\d{1,2}/\d{1,2}/\d{2,4})',
        texto, re.IGNORECASE
    )
    if m:
        detalhes["data_prova"] = m.group(1)

    # Link de inscrição
    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True).lower()
        if any(k in txt for k in ["inscreva", "inscrição", "inscricao", "edital", "acesse"]):
            if href.startswith("http") and "concursosnobrasil" not in href:
                detalhes["link_inscricao"] = href
                break

    # Cidade/Estado — buscar em contexto relevante antes do primeiro match
    _cidade_cnb = ""
    _estado_cnb = ""
    _ctx_kw = ["prefeitura", "município", "municipio", "câmara", "governo", "edital", "concurso público"]
    for _ln in texto.split("."):
        _ln = _ln.strip()
        if not any(k in _ln.lower() for k in _ctx_kw):
            continue
        _mc = re.search(r'\b([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*/\s*([A-Z]{2})\b', _ln)
        if _mc:
            _cidade_cnb = _mc.group(1).strip()
            _estado_cnb = _mc.group(2).strip()
            break
    if not _cidade_cnb:
        _mf = re.search(r'\b([A-Z][a-záéíóúâêôãõç\s]{3,30})\s*[/\-]\s*([A-Z]{2})\b', texto)
        if _mf:
            _cidade_cnb = _mf.group(1).strip()
            _estado_cnb = _mf.group(2).strip()
    if _cidade_cnb:
        detalhes["cidade"] = _cidade_cnb
    if _estado_cnb:
        detalhes["estado"] = _estado_cnb

    return detalhes


# ─────────────────────────────────────────────────────────────────
# PCI Concursos
# ─────────────────────────────────────────────────────────────────

def _parse_pci_item(item, base_url: str = "https://www.pciconcursos.com.br") -> Optional[Dict]:
    """Parseia um item .na do PCI Concursos."""
    try:
        link_tag = item.find("a", href=True)
        if not link_tag:
            return None

        link = link_tag["href"]
        if not link.startswith("http"):
            link = base_url + link

        orgao = link_tag.get_text(strip=True)
        title = link_tag.get("title", "")

        cd = item.find(class_="cd")
        ce = item.find(class_="ce")

        cd_text = cd.get_text(separator="|", strip=True) if cd else ""
        ce_text = ce.get_text(separator="|", strip=True) if ce else ""

        # Parsear .cd: "548 vagas|Jovem Aprendiz|Ensino Médio"
        # ou "13 vagas até R$ 9.663,60|Vários Cargos|Superior"
        cd_parts = [p.strip() for p in cd_text.split("|") if p.strip()]

        vagas_str = cd_parts[0] if len(cd_parts) > 0 else ""
        cargo = cd_parts[1] if len(cd_parts) > 1 else ""
        nivel = cd_parts[2] if len(cd_parts) > 2 else ""

        # Extrair salário do texto de vagas
        salario_valor = _extrair_salario(vagas_str + " " + title)

        # Data de inscrição (ce_text pode ser "23/03 a|11/04/2026" ou "20/03/2026")
        data_inscricao_fim = ce_text.replace("|", " ").strip()

        return {
            "orgao": orgao,
            "cargo": cargo or title[:80],
            "nivel": nivel,
            "salario_texto": vagas_str,
            "salario_valor": salario_valor,
            # salario_fonte="listagem" = valor extraído da listagem agregada.
            # Pode ser o maior cargo do edital, NÃO necessariamente o cargo aqui.
            # O edital_parser confirmará por cargo individual.
            "salario_fonte": "listagem",
            "vagas": vagas_str,
            "banca": "",
            "cidade": "",
            "estado": "",
            "data_inscricao_inicio": "",
            "data_inscricao_fim": data_inscricao_fim,
            "data_prova": "",
            "link_detalhe": link,
            "link_inscricao": "",
            "fonte": "PCI Concursos",
            "titulo": title or orgao,
        }
    except Exception as exc:
        logger.debug(f"Erro ao parsear item PCI: {exc}")
        return None


def scrape_pci(session: requests.Session) -> List[Dict]:
    """Coleta concursos do PCI Concursos — listagem nacional."""
    concursos = []
    seen_links = set()

    # URLs de listagem
    listing_urls = [
        "https://www.pciconcursos.com.br/concursos/nacional/",
        "https://www.pciconcursos.com.br/concursos/",
    ]

    for url in listing_urls:
        html = _get(url, session)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        items = soup.find_all(class_="na")
        logger.info(f"[PCI] {url}: {len(items)} itens")
        for item in items:
            c = _parse_pci_item(item)
            if c and c["link_detalhe"] not in seen_links:
                seen_links.add(c["link_detalhe"])
                concursos.append(c)
        time.sleep(SLEEP)

    # Busca específica por veterinário
    vet_url = "https://www.pciconcursos.com.br/concursos/?q=veterinario"
    html = _get(vet_url, session)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.find_all(class_="na")
        logger.info(f"[PCI] busca veterinário: {len(items)} itens")
        for item in items:
            c = _parse_pci_item(item)
            if c and c["link_detalhe"] not in seen_links:
                seen_links.add(c["link_detalhe"])
                concursos.append(c)
        time.sleep(SLEEP)

    logger.info(f"[PCI] Total coletado: {len(concursos)}")
    return concursos


# ─────────────────────────────────────────────────────────────────
# Concursos no Brasil
# ─────────────────────────────────────────────────────────────────

def scrape_cnb(session: requests.Session) -> List[Dict]:
    """Coleta concursos do ConcursosNoBrasil."""
    concursos = []
    seen_links = set()

    listing_urls = [
        "https://www.concursosnobrasil.com.br/concursos/",
        "https://concursosnobrasil.com/concursos/br/",
        "https://concursosnobrasil.com/concursos/novos/",
    ]

    for url in listing_urls:
        html = _get(url, session)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")

        # Itens são links com classe post-url
        post_urls = soup.find_all(class_="post-url")
        logger.info(f"[CNB] {url}: {len(post_urls)} itens")

        for a in post_urls:
            href = a.get("href", "")
            title = a.get("title", a.get_text(strip=True))
            orgao = a.get_text(strip=True)

            if not href or href in seen_links:
                continue
            seen_links.add(href)

            # Extrair salário do título
            salario_valor = _extrair_salario(title)

            # Nível a partir do título
            nivel = ""
            title_lower = title.lower()
            if "nível médio" in title_lower or "nivel medio" in title_lower or "ensino médio" in title_lower:
                nivel = "Médio"
            elif "nível superior" in title_lower or "nivel superior" in title_lower or "superior" in title_lower:
                nivel = "Superior"

            concursos.append({
                "orgao": orgao,
                "cargo": title[:100],
                "nivel": nivel,
                "salario_texto": "",
                "salario_valor": salario_valor,
                "vagas": "",
                "banca": "",
                "cidade": "",
                "estado": "",
                "data_inscricao_inicio": "",
                "data_inscricao_fim": "",
                "data_prova": "",
                "link_detalhe": href,
                "link_inscricao": "",
                "fonte": "Concursos no Brasil",
                "titulo": title,
            })
        time.sleep(SLEEP)

    logger.info(f"[CNB] Total coletado: {len(concursos)}")
    return concursos


# ─────────────────────────────────────────────────────────────────
# API deno — todos os estados
# ─────────────────────────────────────────────────────────────────

UFS = ["ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms",
       "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc",
       "sp", "se", "to"]


def scrape_deno_api(session: requests.Session) -> List[Dict]:
    """Coleta concursos da API deno para todos os estados."""
    concursos = []
    seen = set()

    for uf in UFS:
        data = _get_json(f"https://concursos-api.deno.dev/{uf}", session)
        if not data:
            continue

        for tipo in ["concursos_abertos", "concursos_previstos"]:
            for item in data.get(tipo, []):
                orgao = item.get("Órgão", "")
                vagas = item.get("Vagas", "")
                key = f"{uf}:{orgao}:{vagas}"
                if key in seen:
                    continue
                seen.add(key)

                salario_valor = _extrair_salario(vagas)
                nivel = ""
                if "médio" in vagas.lower() or "medio" in vagas.lower():
                    nivel = "Médio"
                elif "superior" in vagas.lower():
                    nivel = "Superior"

                concursos.append({
                    "orgao": orgao,
                    "cargo": vagas,
                    "nivel": nivel,
                    "salario_texto": vagas,
                    "salario_valor": salario_valor,
                    "vagas": vagas,
                    "banca": "",
                    "cidade": "",
                    "estado": uf.upper(),
                    "data_inscricao_inicio": "",
                    "data_inscricao_fim": "",
                    "data_prova": "",
                    "link_detalhe": "",
                    "link_inscricao": "",
                    "fonte": f"API Deno ({uf.upper()})",
                    "titulo": f"{orgao} — {vagas}",
                })
        time.sleep(0.1)

    logger.info(f"[Deno API] Total coletado: {len(concursos)}")
    return concursos


# ─────────────────────────────────────────────────────────────────
# Enriquecimento com detalhes
# ─────────────────────────────────────────────────────────────────

def _enriquecer(concurso: Dict, session: requests.Session) -> Dict:
    """Busca detalhes adicionais na página do concurso e o link real de inscrição na banca."""
    url = concurso.get("link_detalhe", "")
    if not url:
        return concurso

    fonte = concurso.get("fonte", "")
    if "PCI" in fonte:
        detalhes = _extrair_detalhes_pci(url, session)
    else:
        detalhes = _extrair_detalhes_cnb(url, session)

    # Extrair texto do artigo (salvo temporariamente)
    texto_artigo = detalhes.pop("_texto_artigo", "")

    # Só atualiza campos vazios
    for k, v in detalhes.items():
        if k == "cargos_detalhados":
            # Sempre atualizar lista de cargos se não estava vazia
            if v and not concurso.get("cargos_detalhados"):
                concurso["cargos_detalhados"] = v
        elif k == "link_edital_pdf":
            # Sempre atualizar link_edital_pdf se encontrado
            if v and not concurso.get("link_edital_pdf"):
                concurso["link_edital_pdf"] = v
        elif v and not concurso.get(k):
            concurso[k] = v

    # Buscar link real de inscrição na banca (se ainda não temos)
    if _BANCA_LINKS_OK and not concurso.get("link_inscricao"):
        try:
            link_banca = buscar_link_inscricao(concurso, texto_artigo, session)
            if link_banca:
                concurso["link_inscricao"] = link_banca
                logger.debug(f"[BANCA] Link encontrado: {link_banca}")
        except Exception as exc:
            logger.debug(f"[BANCA] Erro ao buscar link: {exc}")

    # Extrair salários individuais do edital para os cargos já identificados no artigo
    # Também salvar o link direto do PDF do edital em link_edital_pdf
    if _EDITAL_PARSER_OK:
        url_pagina_banca = concurso.get("link_inscricao") or concurso.get("link_detalhe", "")
        cargos_artigo = concurso.get("cargos_detalhados", [])
        if url_pagina_banca and not concurso.get("cargos_com_salario"):
            try:
                # Importar função auxiliar para encontrar o PDF do edital
                from edital_parser import _encontrar_pdf_edital, _encontrar_todos_pdfs_edital

                # Tentar encontrar o PDF do edital na página da banca
                url_pdf = _encontrar_pdf_edital(url_pagina_banca)
                if url_pdf and not concurso.get("link_edital_pdf"):
                    concurso["link_edital_pdf"] = url_pdf
                    logger.debug(f"[EDITAL] PDF encontrado: {url_pdf[:80]}")

                orgao_c  = concurso.get("orgao", "")
                banca_c  = concurso.get("banca", "")
                texto_c  = texto_artigo or ""
                if cargos_artigo:
                    # Usar cargos do artigo como referência, buscar salário no edital
                    # Se não encontrar edital no link direto, busca na entidade organizadora
                    cargos_edital = buscar_salario_por_cargo(
                        url_pagina_banca, cargos_artigo,
                        orgao=orgao_c, banca=banca_c, texto_artigo=texto_c
                    )
                else:
                    # Sem cargos do artigo, tentar parsear tabela do edital
                    cargos_edital = extrair_cargos_do_edital(url_pagina_banca)
                if cargos_edital:
                    concurso["cargos_com_salario"] = cargos_edital
                    concurso["edital_analisado"] = True
                    logger.info(f"[EDITAL] {len(cargos_edital)} cargos relevantes com salário do edital")
                else:
                    # Edital foi analisado mas não encontrou cargos relevantes
                    # Marcar para exclusão posterior
                    concurso["edital_analisado"] = True
                    concurso["edital_sem_cargos_relevantes"] = True
                    logger.info(f"[EDITAL] Nenhum cargo relevante no edital — concurso será excluído")
            except Exception as exc:
                logger.debug(f"[EDITAL] Erro ao extrair cargos: {exc}")

    time.sleep(SLEEP)
    return concurso


# ─────────────────────────────────────────────────────────────────
# Função principal
# ─────────────────────────────────────────────────────────────────

def buscar_concursos(enriquecer_detalhes: bool = True,
                     max_enriquecimento: int = 50) -> Tuple[List[Dict], List[str]]:
    """
    Busca concursos de todas as fontes, aplica filtros e retorna lista filtrada.

    Returns:
        (lista_filtrada, lista_erros)
    """
    session = requests.Session()
    session.verify = False

    todos: List[Dict] = []
    erros: List[str] = []

    # Coletar de todas as fontes
    try:
        todos.extend(scrape_pci(session))
    except Exception as e:
        erros.append(f"[PCI] {e}")

    try:
        todos.extend(scrape_cnb(session))
    except Exception as e:
        erros.append(f"[CNB] {e}")

    try:
        todos.extend(scrape_deno_api(session))
    except Exception as e:
        erros.append(f"[Deno] {e}")

    if _CONVET_BLOG_OK:
        try:
            todos.extend(scrape_convet_blog(session))
        except Exception as e:
            erros.append(f"[Convet Blog] {e}")
    else:
        erros.append("[Convet Blog] Módulo scraper_convet_blog não disponível")

    # Fontes extras: JC Concursos, Estratégia, Gran Cursos, Aprova, Folha Dirigida,
    # IBFC, IDECAN, AOCP, Quadrix, FEPESE, Cebraspe
    if _SCRAPERS_EXTRAS_OK:
        try:
            extras, erros_extras = scrape_todas_fontes_extras(session)
            todos.extend(extras)
            erros.extend(erros_extras)
            logger.info(f"[EXTRAS] {len(extras)} concursos de fontes extras")
        except Exception as e:
            erros.append(f"[EXTRAS] {e}")
    else:
        erros.append("[EXTRAS] Módulo scrapers_extras não disponível")

    logger.info(f"Total coletado (todas as fontes): {len(todos)}")

    # ── Deduplicação cross-source ───────────────────────────────────────────
    # Mesmo concurso pode aparecer em PCI E ConcursosNoBrasil com links diferentes.
    # Chave de dedup: órgão normalizado + primeiras palavras do cargo.
    def _dedup_key(c: Dict) -> str:
        orgao_n = re.sub(r"[^\w\s]", "", c.get("orgao", "").lower().strip())
        orgao_n = re.sub(r"\s+", " ", orgao_n).strip()
        for prefix in ["prefeitura municipal de ", "prefeitura de ",
                       "camara municipal de ", "governo do estado de ",
                       "secretaria ", "municipio de "]:
            if orgao_n.startswith(prefix):
                orgao_n = orgao_n[len(prefix):]
                break
        cargo_n = re.sub(r"[^\w\s]", "", c.get("cargo", "").lower().strip())
        cargo_n = " ".join(cargo_n.split()[:4])
        return f"{orgao_n}|{cargo_n}"

    todos_dedup: List[Dict] = []
    seen_dedup_cs: set = set()
    for _c in todos:
        _k = _dedup_key(_c)
        if _k and _k not in seen_dedup_cs:
            seen_dedup_cs.add(_k)
            todos_dedup.append(_c)
        elif _k:
            # Manter o que tiver link_detalhe (PCI/CNB > Deno API sem link)
            _existing = next((x for x in todos_dedup if _dedup_key(x) == _k), None)
            if _existing and not _existing.get("link_detalhe") and _c.get("link_detalhe"):
                todos_dedup.remove(_existing)
                todos_dedup.append(_c)
    _removidos_cs = len(todos) - len(todos_dedup)
    if _removidos_cs > 0:
        logger.info(f"[DEDUP cross-source] {_removidos_cs} duplicata(s) removida(s)")
    todos = todos_dedup

    # Filtrar por critérios
    filtrados = [c for c in todos if _atende_criterios(c)]
    logger.info(f"Total após filtro de critérios: {len(filtrados)}")

    # Enriquecer com detalhes: TODOS os concursos filtrados precisam ter edital verificado
    # Concursos sem edital acessível serão descartados
    # Exceção: Blog Convet já fornece dados estruturados e link direto do edital
    # Fontes extras (JC, Estratégia, Gran, etc.) também passam pelo enriquecimento
    _FONTES_COM_DETALHE = (
        "PCI Concursos", "Concursos no Brasil",
        "JC Concursos", "Estratégia Concursos", "Gran Cursos",
        "Aprova Concursos", "Folha Dirigida",
        "IBFC", "IDECAN", "AOCP", "Quadrix", "FEPESE", "Cebraspe",
    )
    for c in filtrados:
        fonte = c.get("fonte", "")
        if fonte == "Blog Convet":
            # Blog Convet: dados já estruturados — o scraper fornece link_edital_pdf diretamente
            sal_texto = c.get("salario_texto", "")
            sal_valor = c.get("salario_valor") or 0
            if sal_texto and not sal_valor:
                try:
                    sv = float(re.sub(r'[^\d,]', '', sal_texto).replace(',', '.'))
                    sal_valor = sv if sv > 100 else 0
                except Exception:
                    sal_valor = 0
            # Montar cargo base com dados do scraper
            cargo_base = {
                "cargo": "Médico Veterinário",
                "salario_texto": sal_texto,
                "salario_valor": sal_valor,
                "categoria": "veterinario",
                "vagas": "",
                "formacao": "Médico Veterinário",
                "cidades": [],
            }
            c["cargos_com_salario"] = [cargo_base]
            c["edital_analisado"] = True
            # Enriquecer com dados do edital PDF (vagas, formação, cidades)
            if enriquecer_detalhes and _EDITAL_PARSER_OK:
                url_pdf_convet = c.get("link_edital_pdf", "") or c.get("link_inscricao", "")
                if url_pdf_convet:
                    try:
                        cargos_edital = buscar_salario_por_cargo(
                            url_pdf_convet,
                            [{"cargo": "Médico Veterinário", "vagas": "", "formacao": ""}],
                            orgao=c.get("orgao", ""),
                            banca=c.get("banca", "")
                        )
                        if cargos_edital:
                            # Usar dados do edital, preservando salário do scraper se o edital não tiver
                            cargo_edital = cargos_edital[0]
                            if not cargo_edital.get("salario_valor") and sal_valor:
                                cargo_edital["salario_valor"] = sal_valor
                                cargo_edital["salario_texto"] = sal_texto
                            c["cargos_com_salario"] = cargos_edital
                            logger.info(f"[Convet Blog] Edital enriquecido: vagas={cargo_edital.get('vagas')}, cidades={cargo_edital.get('cidades')}")
                        else:
                            # Edital lido mas sem dados adicionais — manter cargo base
                            logger.debug(f"[Convet Blog] Edital sem dados adicionais: {url_pdf_convet[:60]}")
                    except Exception as exc:
                        logger.debug(f"[Convet Blog] Erro ao enriquecer edital: {exc}")
        elif enriquecer_detalhes:
            if c.get("link_detalhe") and any(f in fonte for f in _FONTES_COM_DETALHE):
                _enriquecer(c, session)
            elif not c.get("link_detalhe") and (c.get("orgao") or c.get("banca")):
                # Sem link de detalhe mas com orgão/banca: tentar buscar edital direto
                _enriquecer(c, session)
            else:
                # Sem link de detalhe ou fonte sem edital: marcar como sem edital
                c["edital_sem_cargos_relevantes"] = True
                c["edital_analisado"] = False
        else:
            # Sem enriquecimento: marcar como sem edital (exceto Blog Convet, já tratado acima)
            c["edital_sem_cargos_relevantes"] = True
            c["edital_analisado"] = False

    # Exigir verificação de edital: apenas concursos com cargos relevantes confirmados no edital
    antes = len(filtrados)
    filtrados = [c for c in filtrados
                 if c.get("cargos_com_salario") and not c.get("edital_sem_cargos_relevantes")]
    excluidos = antes - len(filtrados)
    if excluidos > 0:
        logger.info(f"[FILTRO EDITAL] {excluidos} concurso(s) excluído(s) (sem edital verificado ou sem cargos relevantes)")

    # Filtro de salário obrigatório pós-enriquecimento:
    # Descartar concursos cujos cargos não têm salário confirmado (>= R$ 10.000)
    def _tem_salario_confirmado(c: Dict) -> bool:
        """Retorna True se pelo menos um cargo tem salário >= SALARIO_MINIMO."""
        cargos = c.get("cargos_com_salario", [])
        for cargo in cargos:
            sv = cargo.get("salario_valor") or 0
            try:
                if float(sv) >= SALARIO_MINIMO:
                    return True
            except Exception:
                pass
        # Fallback: verificar salário legado do concurso
        sv_legado = c.get("salario_valor") or 0
        try:
            if float(sv_legado) >= SALARIO_MINIMO:
                return True
        except Exception:
            pass
        return False
    antes_sal = len(filtrados)
    filtrados = [c for c in filtrados if _tem_salario_confirmado(c)]
    excluidos_sal = antes_sal - len(filtrados)
    if excluidos_sal > 0:
        logger.info(f"[FILTRO SALÁRIO] {excluidos_sal} concurso(s) excluído(s) sem salário confirmado >= R$ {SALARIO_MINIMO:,.0f}")

    # Filtro de data expirada (pós-enriquecimento): descartar concursos com prazo já encerrado
    # Executado DEPOIS do enriquecimento pois data_inscricao_fim é preenchida durante o enriquecimento
    from datetime import date as _date_hoje
    _hoje = _date_hoje.today()
    def _prazo_expirado(c: Dict) -> bool:
        """Retorna True se o prazo de inscrição já passou (exclusive hoje)."""
        di_fim = c.get("data_inscricao_fim", "") or ""
        if not di_fim:
            return False  # sem data: não descartar
        # Normalizar: extrair apenas a data final se houver intervalo (ex: '02/04 a 04/05/2026')
        # Pegar a última data encontrada no texto
        import re as _re
        datas = _re.findall(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', di_fim)
        if not datas:
            return False
        # Usar a última data encontrada como prazo final
        d_str, m_str, a_str = datas[-1]
        try:
            d_int = int(d_str)
            m_int = int(m_str)
            a_int = int(a_str) if a_str else _hoje.year
            if a_int < 100:
                a_int += 2000
            from datetime import date as _d
            prazo = _d(a_int, m_int, d_int)
            return prazo < _hoje  # prazo < hoje: expirado (hoje ainda é válido)
        except Exception:
            return False
    antes_data = len(filtrados)
    filtrados = [c for c in filtrados if not _prazo_expirado(c)]
    excluidos_data = antes_data - len(filtrados)
    if excluidos_data > 0:
        logger.info(f"[FILTRO DATA] {excluidos_data} concurso(s) excluído(s) com prazo de inscrição expirado")

    # Enriquecimento de cidade e link de inscrição para concursos que ainda não têm esses dados
    if _ENRIQUECEDOR_OK and enriquecer_detalhes:
        sem_cidade = sum(1 for c in filtrados if not c.get("cidade"))
        sem_inscricao = sum(1 for c in filtrados if not c.get("link_inscricao"))
        logger.info(f"[ENRIQUECEDOR] {sem_cidade} sem cidade, {sem_inscricao} sem link de inscrição — iniciando enriquecimento")
        for c in filtrados:
            if not c.get("cidade") or not c.get("link_inscricao"):
                try:
                    _enriquecer_cidade_inscricao(c, timeout=20)
                except Exception as exc:
                    logger.debug(f"[ENRIQUECEDOR] Erro: {exc}")
        after_cidade = sum(1 for c in filtrados if c.get("cidade"))
        after_inscricao = sum(1 for c in filtrados if c.get("link_inscricao"))
        logger.info(f"[ENRIQUECEDOR] Após: {after_cidade}/{len(filtrados)} com cidade, {after_inscricao}/{len(filtrados)} com link inscrição")

    session.close()
    return filtrados, erros


# ─────────────────────────────────────────────────────────────────
# Deduplicação
# ─────────────────────────────────────────────────────────────────

def _concurso_id(c: Dict) -> str:
    """Gera ID único para um concurso."""
    orgao = re.sub(r'\s+', ' ', c.get("orgao", "").strip().lower())
    cargo = re.sub(r'\s+', ' ', c.get("cargo", "").strip().lower())[:50]
    fonte = c.get("fonte", "")

    # Blog Convet: usar link_inscricao (link do edital) como ID primário,
    # pois link_detalhe é sempre a mesma URL da página de editais
    if fonte == "Blog Convet":
        link_edital = c.get("link_inscricao", "")
        if link_edital:
            return link_edital
        # Fallback: usar título + estado como ID único
        titulo = re.sub(r'\s+', ' ', c.get("titulo", "").strip().lower())
        estado = c.get("estado", "").lower()
        return f"convet|{titulo}|{estado}"

    # Demais fontes: usar link_detalhe ou link_inscricao
    link = c.get("link_detalhe", "") or c.get("link_inscricao", "")
    if link:
        return link
    return f"{orgao}|{cargo}"


def filtrar_novos_concursos(concursos: List[Dict], seen: dict) -> Tuple[List[Dict], dict]:
    """
    Filtra apenas concursos não vistos anteriormente.

    Returns:
        (novos_concursos, seen_atualizado)
    """
    novos = []
    for c in concursos:
        cid = _concurso_id(c)
        if cid and cid not in seen:
            novos.append(c)
            seen[cid] = True
    return novos, seen


# ─────────────────────────────────────────────────────────────────
# Formatação do email
# ─────────────────────────────────────────────────────────────────

def formatar_email_html(concursos: List[Dict], erros: List[str]) -> str:
    """
    Gera o email de alerta de novos concursos em HTML premium.
    Usa o módulo email_template.py para o design.
    """
    try:
        from email_template import gerar_email_html
        return gerar_email_html(concursos, erros, normalizar_data)
    except ImportError as exc:
        logger.warning(f"email_template não disponível, usando formato texto: {exc}")
        return formatar_email_concursos(concursos, erros)


def formatar_email_concursos(concursos: List[Dict], erros: List[str]) -> str:
    """
    Formata o email de alerta de novos concursos (formato texto plano).

    Organiza os concursos por estado (ordem alfabética) e dentro de cada
    estado por salario decrescente. Exibe cargo + salário do edital,
    cidade/estado obrigatórios, e links diretos do edital e da inscrição
    na banca organizadora.
    """
    from datetime import date
    from collections import defaultdict
    hoje = date.today().strftime("%d/%m/%Y")

    linhas = [
        f"ALERTA DE NOVOS CONCURSOS PUBLICOS — {hoje}",
        f"Criterios: salario >= R$ 10.000 | Medico Veterinario | Nivel Medio | Nivel Superior",
        f"Total de concursos novos encontrados: {len(concursos)}",
        "=" * 70,
        "",
    ]

    if not concursos:
        linhas.append("Nenhum concurso novo encontrado hoje que atenda aos criterios.")
        linhas.append("")
    else:
        # ── Agrupar por estado (UF) ────────────────────────────────────────────
        por_estado: dict = defaultdict(list)
        sem_estado: list = []
        for c in concursos:
            uf = (c.get("estado") or "").strip().upper()
            if uf:
                por_estado[uf].append(c)
            else:
                sem_estado.append(c)

        # Ordenar estados alfabeticamente; concursos sem estado ficam no final
        estados_ordenados = sorted(por_estado.keys())

        # Dentro de cada estado, ordenar por maior salário do cargo de interesse
        def _salario_principal(c: Dict) -> float:
            cargos_sal = c.get("cargos_com_salario", [])
            if cargos_sal:
                return max((cd.get("salario_valor", 0) or 0) for cd in cargos_sal)
            sv = c.get("salario_valor") or 0
            return float(sv) if sv else 0.0

        # Numeração global dos concursos
        contador = 0

        grupos = [(uf, por_estado[uf]) for uf in estados_ordenados]
        if sem_estado:
            grupos.append(("(Estado não identificado)", sem_estado))

        for uf, lista in grupos:
            lista_ord = sorted(lista, key=_salario_principal, reverse=True)

            linhas.append(f"{'=' * 70}")
            linhas.append(f"  ESTADO: {uf}  ({len(lista_ord)} concurso{'s' if len(lista_ord) != 1 else ''})")
            linhas.append(f"{'=' * 70}")
            linhas.append("")

            for c in lista_ord:
                contador += 1
                linhas.append(f"[{contador}] {c.get('titulo', c.get('orgao', 'Sem titulo'))}")
                linhas.append("-" * 60)

                orgao = c.get("orgao", "")
                if orgao:
                    linhas.append(f"  Orgao/Entidade : {orgao}")

                # Localização: cidade e estado são obrigatórios
                cidade = c.get("cidade", "").strip()
                estado_c = c.get("estado", "").strip()
                if cidade and estado_c:
                    linhas.append(f"  Local          : {cidade} / {estado_c}")
                elif estado_c:
                    linhas.append(f"  Estado         : {estado_c}")
                elif cidade:
                    linhas.append(f"  Cidade         : {cidade}")
                else:
                    linhas.append(f"  Local          : (não identificado)")

                nivel = c.get("nivel", "")
                if nivel:
                    linhas.append(f"  Nivel          : {nivel}")

                banca = c.get("banca", "")
                if banca:
                    linhas.append(f"  Banca          : {banca}")

                # ── Cargos e salários do edital (prioridade máxima) ──────────
                cargos_sal = c.get("cargos_com_salario", [])
                if cargos_sal:
                    linhas.append(f"  Cargo(s) de interesse:")
                    for cd in cargos_sal:
                        nome_cargo = cd.get("cargo", "")
                        sal_texto = cd.get("salario_texto", "")
                        n_vagas = cd.get("vagas", "")
                        categoria = cd.get("categoria", "")
                        rotulo = label_categoria(categoria) if _EDITAL_PARSER_OK else categoria
                        vagas_str = f" ({n_vagas} vaga{'s' if isinstance(n_vagas, int) and n_vagas != 1 else ''})" if n_vagas else ""
                        linhas.append(f"    - {nome_cargo}{vagas_str}: {sal_texto}")
                else:
                    # Fallback: cargo genérico da listagem
                    cargo = c.get("cargo", "")
                    salario = c.get("salario_texto", "") or c.get("salario_valor", "")
                    sal_fonte = c.get("salario_fonte", "edital")
                    if isinstance(salario, float):
                        salario = f"R$ {salario:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    if cargo:
                        linhas.append(f"  Cargo          : {cargo}")
                    if salario:
                        if sal_fonte == "listagem":
                            linhas.append(f"  Remuneracao    : até {salario} (verificar edital — valor da listagem)")
                        else:
                            linhas.append(f"  Remuneracao    : {salario}")

                di_ini = normalizar_data(c.get("data_inscricao_inicio", ""))
                di_fim = normalizar_data(c.get("data_inscricao_fim", ""))
                if di_ini and di_fim:
                    linhas.append(f"  Inscricoes     : {di_ini} a {di_fim}")
                elif di_fim:
                    linhas.append(f"  Inscricoes ate : {di_fim}")

                dp = normalizar_data(c.get("data_prova", ""))
                if dp:
                    linhas.append(f"  Data da Prova  : {dp}")

                # ── Links: edital e inscrição na banca ─────────────────────
                link_edital = c.get("link_edital_pdf", "")  # PDF do edital (novo campo)
                link_ins = c.get("link_inscricao", "")      # Página de inscrição na banca
                link_det = c.get("link_detalhe", "")         # Notícia/fonte

                if link_edital:
                    linhas.append(f"  Edital (PDF)   : {link_edital}")
                if link_ins and link_ins != link_edital:
                    linhas.append(f"  Inscricao/Banca: {link_ins}")
                if link_det and link_det not in (link_edital, link_ins):
                    linhas.append(f"  Fonte/Noticia  : {link_det}")

                linhas.append("")

    linhas.append("=" * 70)

    if erros:
        linhas.append("Avisos tecnicos:")
        for e in erros[:10]:
            linhas.append(f"  - {e}")
        linhas.append("")

    linhas.append("Este email foi gerado automaticamente pelo sistema Intellicore.")
    linhas.append("Apenas concursos NOVOS (nao alertados anteriormente) sao incluidos.")
    linhas.append("Repositorio: https://github.com/contatohb/Intellicore")

    return "\n".join(linhas)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    concursos, erros = buscar_concursos(enriquecer_detalhes=False)
    print(f"\nTotal filtrado: {len(concursos)}")
    for c in concursos[:5]:
        print(f"  - {c['orgao']} | {c['cargo'][:50]} | {c['nivel']} | {c['salario_texto'][:30]}")
