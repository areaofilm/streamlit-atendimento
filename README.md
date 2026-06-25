# Analise comparativa de atendimento

Aplicativo web em Python com Streamlit para comparar relatorios CSV de atendimento e auditar atendimentos OS PRO por regras, com camada opcional de IA.

## O que o app faz

- Le dois CSVs lado a lado, com deteccao de separador e encoding.
- Identifica automaticamente colunas provaveis de TMA, TME, status, tipo, classificacao, data e campos textuais.
- Permite ajuste manual das colunas quando a deteccao automatica nao for suficiente.
- Filtra atendimentos de mudanca de endereco e mudanca de comodo como um unico grupo.
- Calcula TMA/TME geral, mediana, TMA sem inatividade, status, tipo e gargalos por classificacao.
- Mostra periodo de cada arquivo, volume total e volume no recorte.
- Calcula `TMA, TME e Inatividade por Taxa` sem tratar inatividade como finalizacao real.
- Emite alerta quando um dos meses tem menos de 30 atendimentos no recorte.
- Exibe diagnostico executivo, semaforos de saude, top gargalos e conclusao automatica.
- Permite alterar o recorte: mudanca endereco/comodo, arquivo inteiro ou busca personalizada.
- Possui modo independente `Cobranca com IA`, usando o CSV completo para analisar Velma, cobranca, recorrencia, status, tipo, classificacao e evolucao diaria.
- Possui modo `ANALISE DE AUTO SERVICO` para analisar bases CSV/XLSX de autosservico de mudanca de endereco e mudanca de comodo, com OS, faturas, CSAT, canais e departamentos.
- Possui modo `Auditoria OS PRO` para analisar PDF, TXT ou texto colado manualmente.
- Permite cadastrar criterios OS PRO por 1 a 10 arquivos PDF/TXT ou por JSON, com prioridade para os arquivos de criterios quando enviados.
- No JSON, aceita regras obrigatorias, frases proibidas, pesos e sugestoes.
- Calcula nota final, status aprovado/atencao/reprovado, conformidades, nao conformidades, evidencias, trechos problematicos e sugestoes.
- Permite informar uma chave API no campo lateral para ativar uma analise avancada por IA, sem tornar a IA obrigatoria.
- Permite adicionar termos extras para identificar com taxa e sem taxa.
- Permite baixar PDF, Excel da analise e CSV com a base filtrada.
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
  analise_autosservico.py
  analise_atendimento.py
  auditoria_os_pro.py
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
- No modo `Auditoria OS PRO`, a IA so e chamada quando a opcao estiver marcada e uma chave API for informada.
- Sem IA, a auditoria usa regras objetivas: presenca de termos, ausencia de frases de risco e pesos cadastrados.
- O modelo padrao do modo IA e `auto`; o app tenta detectar modelos visiveis pela chave API. Se preferir, informe manualmente um modelo liberado no seu projeto.
- Se houver PDF/TXT de criterios OS PRO no cadastro, eles serao usados primeiro, com limite de 10 arquivos. Se nao houver arquivo, o app usa os criterios em JSON.
- PDFs de criterios precisam ter texto selecionavel ou OCR. PDFs escaneados como imagem podem nao ter criterios extraidos; nesse caso envie uma versao com OCR ou TXT.
- Depois de carregar criterios por PDF/TXT ou JSON, o app mostra uma previa dos criterios usados para facilitar a conferencia antes de interpretar a nota.
