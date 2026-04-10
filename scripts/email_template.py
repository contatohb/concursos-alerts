#!/usr/bin/env python3
"""
Template HTML premium para a newsletter de alertas de concursos públicos.

Cada card exibe os cargos elegíveis separados em dois grupos com títulos e
separadores visuais bem marcados:
  ► VAGAS PARA MÉDICO VETERINÁRIO
  ► DEMAIS VAGAS COMPATÍVEIS

Dentro de cada grupo: tabela com Cargo | Vagas | Formação exigida | Salário | Cidade(s).
"""
from __future__ import annotations

import html
from datetime import date
from typing import Dict, List, Optional


# ─────────────────────────────────────────────────────────────────
# Mapa de cores por UF
# ─────────────────────────────────────────────────────────────────

_COR_UF: Dict[str, str] = {
    "AC": "#7c3aed", "AL": "#0ea5e9", "AM": "#16a34a", "AP": "#16a34a",
    "BA": "#d97706", "CE": "#0ea5e9", "DF": "#1d4ed8", "ES": "#0d9488",
    "GO": "#16a34a", "MA": "#7c3aed", "MG": "#1d4ed8", "MS": "#16a34a",
    "MT": "#d97706", "PA": "#16a34a", "PB": "#7c3aed", "PE": "#0ea5e9",
    "PI": "#d97706", "PR": "#1d4ed8", "RJ": "#dc2626", "RN": "#0ea5e9",
    "RO": "#16a34a", "RR": "#16a34a", "RS": "#1d4ed8", "SC": "#0ea5e9",
    "SE": "#d97706", "SP": "#7c3aed", "TO": "#d97706",
}
_COR_DEFAULT = "#6b7280"


# ─────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────

_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                 'Helvetica Neue', Arial, sans-serif;
    background-color: #f1f5f9;
    color: #1e293b;
    font-size: 15px;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
}
.wrapper { max-width: 700px; margin: 0 auto; background: #f1f5f9; }

/* ── Cabeçalho ── */
.header {
    background: linear-gradient(135deg, #0d2b4e 0%, #1a4a7a 70%, #1e5fa0 100%);
    padding: 28px 32px 22px;
}
.header-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 3px;
    text-transform: uppercase; color: #7ab3e0; margin-bottom: 8px;
}
.header-title { font-size: 26px; font-weight: 800; color: #ffffff; line-height: 1.2; margin-bottom: 6px; }
.header-subtitle { font-size: 13px; color: #a8c8e8; }

/* ── Barra de status ── */
.status-bar { background: #1a3d6b; padding: 11px 32px; }
.status-bar-text { font-size: 13px; font-weight: 700; color: #ffffff; line-height: 1.4; }

/* ── Intro ── */
.intro { background: #ffffff; padding: 18px 32px 14px; border-bottom: 1px solid #e2e8f0; }
.intro-text { font-size: 14px; color: #475569; line-height: 1.6; }

/* ── Corpo ── */
.body { padding: 20px 24px; }

/* ── Card ── */
.card {
    background: #ffffff;
    border-radius: 10px;
    border-left: 4px solid #1a4a7a;
    border-top: 1px solid #e2e8f0;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 16px;
    overflow: hidden;
}
.card-inner { padding: 16px 18px 14px; }

/* ── Tags ── */
.tag {
    display: inline-block; font-size: 11px; font-weight: 700;
    padding: 2px 9px; border-radius: 20px; letter-spacing: 0.3px;
    margin-right: 6px; margin-bottom: 8px; vertical-align: middle;
}
.tag-fonte { background: #e0e7ff; color: #3730a3; }

/* ── Órgão ── */
.card-orgao { font-size: 17px; font-weight: 800; color: #0f172a; line-height: 1.3; margin-bottom: 3px; }
.card-sal-max { font-size: 14px; font-weight: 700; color: #16a34a; }
.card-local { font-size: 12px; color: #64748b; margin-bottom: 12px; }

/* ── Separador de grupo ── */
.grupo-header {
    display: flex;
    align-items: center;
    margin: 14px 0 8px;
    gap: 8px;
}
.grupo-header-vet {
    background: #166534;
    color: #ffffff;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 4px 12px;
    border-radius: 4px;
}
.grupo-header-demais {
    background: #1e40af;
    color: #ffffff;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 4px 12px;
    border-radius: 4px;
}
.grupo-linha {
    flex: 1;
    height: 2px;
    border-radius: 2px;
}
.grupo-linha-vet { background: #bbf7d0; }
.grupo-linha-demais { background: #bfdbfe; }

/* ── Tabela de cargos ── */
.cargos-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 4px;
    font-size: 12px;
}
.cargos-table th {
    background: #f8fafc;
    color: #64748b;
    font-weight: 700;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    padding: 5px 8px;
    border-bottom: 2px solid #e2e8f0;
    text-align: left;
    white-space: nowrap;
}
.cargos-table td {
    padding: 7px 8px;
    border-bottom: 1px solid #f1f5f9;
    vertical-align: top;
    color: #334155;
}
.cargos-table tr:last-child td { border-bottom: none; }
.cargo-nome { font-weight: 600; color: #0f172a; }
.cargo-salario { font-weight: 700; color: #16a34a; white-space: nowrap; }
.cargo-vagas { color: #475569; white-space: nowrap; text-align: center; }
.cargo-formacao { color: #64748b; font-size: 11px; }
.cargo-cidades { color: #64748b; font-size: 11px; }

/* ── Datas ── */
.card-datas {
    font-size: 12px; color: #475569;
    margin: 10px 0 12px; line-height: 1.8;
    background: #f8fafc; border-radius: 6px;
    padding: 8px 12px;
}
.data-label { color: #94a3b8; font-weight: 700; }
.data-valor { font-weight: 700; color: #0f172a; }

/* ── Botões ── */
.btn-row td { padding-right: 8px; vertical-align: middle; }
.btn {
    display: inline-block; font-size: 12px; font-weight: 700;
    padding: 7px 14px; border-radius: 6px; text-decoration: none;
    letter-spacing: 0.2px; white-space: nowrap;
}
.btn-edital  { background: #1a4a7a; color: #ffffff !important; border: 1px solid #1a4a7a; }
.btn-inscricao { background: #16a34a; color: #ffffff !important; border: 1px solid #16a34a; }
.btn-fonte   { background: #f8fafc; color: #475569 !important; border: 1px solid #cbd5e1; }

/* ── Rodapé ── */
.footer { background: #0d2b4e; padding: 20px 32px; text-align: center; }
.footer-text { font-size: 12px; color: #7ab3e0; line-height: 1.7; }
.footer-link { color: #a8c8e8; text-decoration: none; font-weight: 600; }
.footer-divider { border: none; border-top: 1px solid #1a3d6b; margin: 10px 0; }

/* ── Impressão ── */
@media print {
  body { background: #ffffff !important; font-size: 11pt; }
  .wrapper { max-width: 100% !important; box-shadow: none !important; }
  .header { background: #0d2b4e !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .card { break-inside: avoid; page-break-inside: avoid; border: 1px solid #cbd5e1 !important; }
  .cat-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .tag, .tag-fonte { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .btn { border: 1px solid #475569 !important; color: #1a4a7a !important; background: #f8fafc !important; }
  .footer { background: #0d2b4e !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  a[href]:after { content: " (" attr(href) ")"; font-size: 9pt; color: #475569; }
}
"""


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _e(text: str) -> str:
    return html.escape(str(text)) if text else ""


def _tag_uf(uf: str) -> str:
    cor = _COR_UF.get(uf.upper(), _COR_DEFAULT)
    return f'<span class="tag" style="background:{cor};color:#ffffff;">{_e(uf)}</span>'


def _tag_fonte(fonte: str) -> str:
    if not fonte:
        return ""
    return f'<span class="tag tag-fonte">{_e(fonte)}</span>'


def _fmt_salario(valor: float, texto: str) -> str:
    if valor and valor > 0:
        return "R$ {:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")
    return texto or ""


def _fmt_vagas(vagas) -> str:
    if not vagas and vagas != 0:
        return "—"
    s = str(vagas).strip()
    if not s or s == "0":
        return "—"
    if s.upper() == "CR":
        return "CR"
    try:
        return "{:,}".format(int(s)).replace(",", ".")
    except Exception:
        return s


def _fonte_do_link(concurso: Dict) -> str:
    for campo in ("link_detalhe", "link_inscricao", "link_edital_pdf"):
        url = concurso.get(campo, "") or ""
        mapa = {
            "pciconcursos": "PCI Concursos",
            "convet": "Blog Convet",
            "qconcursos": "QConcursos",
            "estrategia": "Estratégia Concursos",
            "tecconcursos": "TEC Concursos",
            "jcconcursos": "JC Concursos",
            "grancursos": "Gran Cursos",
            "aprovaconcursos": "Aprova Concursos",
            "direcaoconcursos": "Direção Concursos",
            "concursosnobrasil": "Concursos no Brasil",
            "ibfc": "IBFC",
            "idecan": "IDECAN",
            "aocp": "AOCP",
            "quadrix": "Quadrix",
            "fepese": "FEPESE",
            "cebraspe": "Cebraspe",
        }
        for chave, nome in mapa.items():
            if chave in url.lower():
                return nome
    return ""


# ─────────────────────────────────────────────────────────────────
# Tabela de cargos (por grupo)
# ─────────────────────────────────────────────────────────────────

def _tabela_cargos(cargos: List[Dict]) -> str:
    """Gera a tabela HTML de cargos para um grupo."""
    if not cargos:
        return ""

    linhas = []
    for cd in cargos:
        cargo_nome = cd.get("cargo", "")
        vagas_str  = _fmt_vagas(cd.get("vagas", ""))
        formacao   = cd.get("formacao", "") or ""
        sal_v      = float(cd.get("salario_valor") or 0)
        sal_t      = cd.get("salario_texto", "") or ""
        sal_fmt    = _fmt_salario(sal_v, sal_t)
        cidades    = cd.get("cidades", []) or []

        if cidades:
            cidades_str = ", ".join(cidades[:3])
            if len(cidades) > 3:
                cidades_str += f" +{len(cidades) - 3}"
        else:
            cidades_str = "—"

        linhas.append(f"""
            <tr>
              <td class="cargo-nome">{_e(cargo_nome)}</td>
              <td class="cargo-vagas">{_e(vagas_str)}</td>
              <td class="cargo-formacao">{_e(formacao)}</td>
              <td class="cargo-salario">{_e(sal_fmt)}</td>
              <td class="cargo-cidades">{_e(cidades_str)}</td>
            </tr>""")

    return f"""
    <table class="cargos-table" cellpadding="0" cellspacing="0" border="0">
      <thead>
        <tr>
          <th>Cargo</th>
          <th style="text-align:center;">Vagas</th>
          <th>Formação exigida</th>
          <th>Salário</th>
          <th>Cidade(s) de lotação</th>
        </tr>
      </thead>
      <tbody>{''.join(linhas)}
      </tbody>
    </table>"""


def _grupo_vet_html(cargos_vet: List[Dict]) -> str:
    """Bloco visual para o grupo Médico Veterinário."""
    return f"""
    <div class="grupo-header">
      <span class="grupo-header-vet">&#128021; Médico Veterinário</span>
      <div class="grupo-linha grupo-linha-vet"></div>
    </div>
    {_tabela_cargos(cargos_vet)}"""


def _grupo_demais_html(cargos_demais: List[Dict]) -> str:
    """Bloco visual para o grupo Demais vagas compatíveis."""
    return f"""
    <div class="grupo-header">
      <span class="grupo-header-demais">&#127891; Demais vagas compatíveis</span>
      <div class="grupo-linha grupo-linha-demais"></div>
    </div>
    {_tabela_cargos(cargos_demais)}"""


# ─────────────────────────────────────────────────────────────────
# Card de concurso
# ─────────────────────────────────────────────────────────────────

def _card_html(concurso: Dict, normalizar_data_fn) -> str:
    orgao    = concurso.get("orgao", "") or concurso.get("titulo", "") or "Concurso Público"
    estado_c = (concurso.get("estado") or "").strip().upper()
    cidade_c = (concurso.get("cidade") or "").strip()
    banca    = concurso.get("banca", "") or ""
    fonte    = concurso.get("fonte", "") or _fonte_do_link(concurso)

    # ── Cargos com salário ─────────────────────────────────────────
    cargos_sal = concurso.get("cargos_com_salario", []) or []

    # Fallback: construir lista a partir dos campos legados
    if not cargos_sal:
        cargo_txt = concurso.get("cargo", "")
        sal_txt   = concurso.get("salario_texto", "")
        sv        = concurso.get("salario_valor")
        if sv:
            sal_txt = _fmt_salario(float(sv), sal_txt)
        if cargo_txt or sal_txt:
            cargos_sal = [{
                "cargo": cargo_txt, "salario_texto": sal_txt,
                "salario_valor": sv or 0, "vagas": "",
                "formacao": "", "categoria": "qualquer_area", "cidades": [],
            }]

    # ── Aplicar fallbacks em cada cargo ─────────────────────────────────────────
    # Garante que nenhum campo fique em branco no card
    _FORMACAO_POR_CAT = {
        "veterinario":   "Médico Veterinário",
        "qualquer_area": "Nível Superior (qualquer curso)",
        "nivel_medio":   "Nível Médio",
    }
    for _c in cargos_sal:
        # Formacao: derivar da categoria (mais correto que usar o nome do cargo)
        if not _c.get("formacao"):
            _c["formacao"] = _FORMACAO_POR_CAT.get(_c.get("categoria", ""), "")
        # Vagas: CR (cadastro de reserva) quando desconhecido — NUNCA "Ver edital"
        if not _c.get("vagas") and _c.get("vagas") != 0:
            _c["vagas"] = "CR"
        # Cidades: usar cidade/estado do concurso como fallback
        if not _c.get("cidades"):
            _cid_parts = []
            if cidade_c:
                _cid_parts.append(cidade_c)
            if estado_c:
                _cid_parts.append(estado_c)
            if _cid_parts:
                _c["cidades"] = ["/".join(_cid_parts)]

    # ── Separar por categoria ──────────────────────────────────────────────
    cargos_vet    = [c for c in cargos_sal if c.get("categoria") == "veterinario"]
    cargos_demais = [c for c in cargos_sal if c.get("categoria") != "veterinario"]

    # ── Salário máximo (header) ────────────────────────────────────
    sal_max = max((float(c.get("salario_valor") or 0) for c in cargos_sal), default=0.0)
    sal_max_txt = _fmt_salario(sal_max, "") if sal_max else ""

    # ── Datas ──────────────────────────────────────────────────────
    di_ini = normalizar_data_fn(concurso.get("data_inscricao_inicio", ""))
    di_fim = normalizar_data_fn(concurso.get("data_inscricao_fim", ""))
    dp     = normalizar_data_fn(concurso.get("data_prova", ""))

    datas_parts = []
    if di_ini and di_fim:
        datas_parts.append(
            f'<span class="data-label">Inscrições:</span> '
            f'<span class="data-valor">{_e(di_ini)} a {_e(di_fim)}</span>'
        )
    elif di_fim:
        datas_parts.append(
            f'<span class="data-label">Inscrições até:</span> '
            f'<span class="data-valor">{_e(di_fim)}</span>'
        )
    if dp:
        datas_parts.append(
            f'<span class="data-label">Prova:</span> '
            f'<span class="data-valor">{_e(dp)}</span>'
        )
    datas_html = (
        '<div class="card-datas">&#128197;&nbsp; ' + " &nbsp;|&nbsp; ".join(datas_parts) + "</div>"
    ) if datas_parts else ""

    # ── Localização ────────────────────────────────────────────────
    local_parts = []
    if cidade_c:
        local_parts.append(cidade_c)
    if estado_c:
        local_parts.append(estado_c)
    if banca:
        local_parts.append(f"Banca: {banca}")
    local_html = (
        f'<div class="card-local">&#128205; {_e(" / ".join(local_parts))}</div>'
        if local_parts else ""
    )

    # ── Grupos de cargos ───────────────────────────────────────────
    grupos_html = ""
    if cargos_vet:
        grupos_html += _grupo_vet_html(cargos_vet)
    if cargos_demais:
        grupos_html += _grupo_demais_html(cargos_demais)

    # ── Botões ─────────────────────────────────────────────────────
    link_edital = concurso.get("link_edital_pdf", "") or ""
    link_ins    = concurso.get("link_inscricao", "") or ""
    link_det    = concurso.get("link_detalhe", "") or ""

    btns = []
    if link_edital:
        btns.append(
            f'<td class="btn-row"><a href="{_e(link_edital)}" class="btn btn-edital" '
            f'target="_blank" rel="noopener noreferrer">&#128196; Edital (PDF)</a></td>'
        )
    if link_ins:
        btns.append(
            f'<td class="btn-row"><a href="{_e(link_ins)}" class="btn btn-inscricao" '
            f'target="_blank" rel="noopener noreferrer">&#9999;&#65039; Inscrição / Banca</a></td>'
        )
    if link_det and link_det != link_ins:
        btns.append(
            f'<td class="btn-row"><a href="{_e(link_det)}" class="btn btn-fonte" '
            f'target="_blank" rel="noopener noreferrer">&#128279; Fonte / Notícia</a></td>'
        )
    btn_html = (
        '<table cellpadding="0" cellspacing="0" border="0" style="margin-top:14px;">'
        '<tr>' + ''.join(btns) + '</tr></table>'
    ) if btns else ""

    # ── Tags ───────────────────────────────────────────────────────
    tags_html = ""
    if estado_c:
        tags_html += _tag_uf(estado_c)
    if fonte:
        tags_html += _tag_fonte(fonte)

    # Indicador de salário máximo ao lado do nome do órgão
    sal_badge = (
        f' <span class="card-sal-max">até {_e(sal_max_txt)}</span>'
        if sal_max_txt else ""
    )

    return f"""
    <div class="card">
      <div class="card-inner">
        <div>{tags_html}</div>
        <div class="card-orgao">{_e(orgao)}{sal_badge}</div>
        {local_html}
        {grupos_html}
        {datas_html}
        {btn_html}
      </div>
    </div>"""


# ─────────────────────────────────────────────────────────────────
# Gerador principal do email
# ─────────────────────────────────────────────────────────────────

def gerar_email_html(
    concursos: List[Dict],
    erros: List[str],
    normalizar_data_fn,
) -> str:
    hoje  = date.today().strftime("%d/%m/%Y")
    total = len(concursos)

    def _sal_max(c: Dict) -> float:
        cs = c.get("cargos_com_salario", [])
        if cs:
            return max((float(x.get("salario_valor") or 0) for x in cs), default=0.0)
        return float(c.get("salario_valor") or 0)

    concursos_ord = sorted(concursos, key=_sal_max, reverse=True)

    if concursos_ord:
        cards_html = "".join(_card_html(c, normalizar_data_fn) for c in concursos_ord)
    else:
        cards_html = """
        <div style="text-align:center;padding:40px 20px;color:#64748b;">
          <div style="font-size:40px;margin-bottom:12px;">&#128235;</div>
          <div style="font-size:16px;font-weight:600;color:#0f172a;">
            Nenhum concurso novo encontrado hoje
          </div>
          <div style="font-size:13px;margin-top:6px;">
            Todos os concursos que atendem aos critérios já foram alertados anteriormente.
          </div>
        </div>"""

    erros_html = ""
    if erros:
        itens = "".join(
            f'<li style="font-size:12px;color:#8a6a00;margin-bottom:3px;">{_e(e)}</li>'
            for e in erros[:10]
        )
        erros_html = f"""
        <div style="background:#fffbea;border:1px solid #f0d060;border-radius:8px;
                    padding:14px 18px;margin-top:8px;">
          <div style="font-size:11px;font-weight:700;color:#8a6a00;
                      text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">
            Avisos técnicos
          </div>
          <ul style="padding-left:16px;">{itens}</ul>
        </div>"""

    if total > 0:
        pl = "s" if total != 1 else ""
        total_txt  = f"{total} novo{pl} concurso{pl} encontrado{pl}"
        status_txt = (
            f"&#9989; {total} concurso{pl} novo{pl} &middot; "
            f"Sal&aacute;rio &ge; R$&nbsp;10.000 &middot; "
            f"Formação verificada no edital &middot; "
            f"Mestrado/Doutorado descartados automaticamente"
        )
        intro_txt = (
            f"Hudson, encontramos <strong>{total} novo{pl} concurso{pl}</strong> "
            f"que atendem aos critérios de filtro. "
            f"Cada card exibe os cargos elegíveis separados por categoria — "
            f"<strong>Médico Veterinário</strong> e <strong>Demais vagas compatíveis</strong> — "
            f"com vagas, formação exigida, salário e cidade(s) de lotação extraídos do edital."
        )
    else:
        total_txt  = "Nenhum concurso novo"
        status_txt = "Nenhum concurso novo encontrado hoje"
        intro_txt  = (
            "Hudson, não foram encontrados concursos novos hoje que atendam "
            "aos critérios de filtro."
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<title>Alerta de Concursos &mdash; {hoje}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div class="wrapper">

  <!-- Cabeçalho -->
  <div class="header">
    <div class="header-eyebrow">Intellicore Monitor</div>
    <div class="header-title">&#127919; Alerta de Concursos</div>
    <div class="header-subtitle">{hoje} &middot; {_e(total_txt)}</div>
  </div>

  <!-- Barra de status -->
  <div class="status-bar">
    <div class="status-bar-text">{status_txt}</div>
  </div>

  <!-- Intro -->
  <div class="intro">
    <div class="intro-text">{intro_txt}</div>
  </div>

  <!-- Cards -->
  <div class="body">
    {cards_html}
    {erros_html}
  </div>

  <!-- Rodapé -->
  <div class="footer">
    <div class="footer-text">
      Este email foi gerado automaticamente pelo sistema
      <strong style="color:#a8c8e8;">Intellicore</strong>.<br>
      Apenas concursos <em>novos</em> (não alertados anteriormente) são incluídos.<br>
      Cargos que exigem mestrado ou doutorado são descartados automaticamente.<br>
      <hr class="footer-divider">
      <a href="https://github.com/contatohb/Intellicore" class="footer-link"
         target="_blank" rel="noopener noreferrer">
        github.com/contatohb/Intellicore
      </a>
    </div>
  </div>

</div>
</body>
</html>"""
