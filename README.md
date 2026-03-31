# Concursos Alerts

Alerta diário de concursos públicos para Médico Veterinário e áreas compatíveis.

## Estrutura

```
scripts/
  executar_alerta_diario.py   # Ponto de entrada — executado diariamente às 8h BRT
  monitor_concursos.py        # Coleta e filtragem de concursos (todas as fontes)
  email_template.py           # Template HTML aprovado (cards com tabela de cargos)
  edital_parser.py            # Extração de dados do edital (cargo, salário, prazo)
  enviar_concursos.py         # Envio SMTP + auditoria pós-envio
  scrapers_extras.py          # Scrapers adicionais (Estratégia, Direção, etc.)
  scraper_convet_blog.py      # Scraper do Blog Convet
data/
  concursos_seen.json         # Histórico de concursos já alertados
```

## Regras

- Um único envio diário às **8h de Brasília (11h UTC)**
- Marcador Gmail: **Concursos**
- Filtros: salário ≥ R$ 10.000, cargo elegível, prazo vigente, edital verificado
- Mestrado/doutorado descartados automaticamente
- Apenas concursos NOVOS (não repetir o que já foi enviado)

## Template aprovado

Cards com cabeçalho "INTELLICORE MONITOR · Alerta de Concursos", separação por categoria
(Médico Veterinário / Demais Vagas Compatíveis), tabela de cargos com:
Cargo | Vagas | Formação Exigida | Salário | Cidade(s) de Lotação.

## Execução manual

```bash
cd scripts
python3 executar_alerta_diario.py
```
