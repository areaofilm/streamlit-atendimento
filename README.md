# Analise comparativa de atendimento

Aplicativo web em Python com Streamlit para comparar dois relatorios CSV de atendimento, com foco no recorte **Mudanca de Endereco + Mudanca de Comodo**.

## O que o app faz

- Le dois CSVs lado a lado, com deteccao de separador e encoding.
- Identifica automaticamente colunas provaveis de TMA, TME, status e campos textuais.
- Permite ajuste manual das colunas quando a deteccao automatica nao for suficiente.
- Filtra atendimentos de mudanca de endereco e mudanca de comodo como um unico grupo.
- Classifica o recorte em `Com taxa`, `Sem taxa` e `Sem identificacao de taxa`.
- Exibe cards, tabelas comparativas, graficos e conclusao automatica antes de gerar o PDF.
- Gera relatorio PDF local e disponibiliza download pelo Streamlit.

## Estrutura

```text
app.py
requirements.txt
README.md
utils/
  leitura_csv.py
  tratamento_tempo.py
  analise_atendimento.py
  graficos.py
  pdf_report.py
```

## Como rodar localmente

Crie e ative um ambiente virtual:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Instale as dependencias:

```bash
pip install -r requirements.txt
```

Inicie o app:

```bash
streamlit run app.py
```

O Streamlit abrira o endereco local no navegador. Normalmente:

```text
http://localhost:8501
```

## Publicacao

O projeto esta pronto para publicacao em plataformas que suportam Streamlit, como Streamlit Community Cloud, Render ou Railway.

Para Streamlit Community Cloud:

1. Suba este projeto para um repositorio GitHub.
2. Acesse `https://share.streamlit.io/`.
3. Escolha o repositorio, branch e o arquivo principal `app.py`.
4. Clique em deploy.

## Observacoes

- Se o CSV nao tiver coluna de TME, selecione `Usar TME = 0`.
- Se a coluna de TMA ou status nao for detectada automaticamente, ajuste manualmente no mapeamento.
- Os PDFs gerados sao salvos na pasta `output/` e tambem ficam disponiveis para download na tela.

