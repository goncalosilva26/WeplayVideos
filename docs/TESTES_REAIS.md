# Testes reais no seu computador

Alguns resultados só podem ser confirmados no seu PC: o modelo Qwen3-VL a
correr no Ollama com a sua placa gráfica, os seus projetos verdadeiros e o
Canva com a sua conta. Este guia tem quatro passos curtos. Cada um deixa um
relatório para me enviar.

Tempo total aproximado: 30–60 minutos (depende do número de imagens).

---

## Passo 0 — Atualizar o Behance Studio

1. Atualize a pasta do Behance Studio para a versão mais recente deste ramo
   (`git pull`, ou descarregue de novo a pasta).
2. Faça duplo clique em **`setup_windows.bat`** (instala o que faltar; pode
   repetir sem problemas).

> Se usa a versão instalada (instalador / pasta `BehanceStudio`), os ficheiros
> `.bat` não se aplicam: use, numa janela de comandos dentro da pasta da
> aplicação, `BehanceStudio-cli.exe ai-check --test`,
> `BehanceStudio-cli.exe real-test "C:\pasta\do\projeto"` e
> `BehanceStudio-cli.exe canva-verify "design.pptx" "canva.zip"`.

> Na primeira geração depois desta atualização, o modelo volta a analisar
> todas as imagens uma vez (agora também indica onde está o motivo principal
> e quão forte é a imagem para capa). As gerações seguintes usam a cache.

## Passo 1 — Verificar o Ollama e o Qwen3-VL

1. Abra o Ollama (o ícone deve aparecer junto ao relógio).
2. Faça duplo clique em **`LocalAI_Check.bat`**.
   * Se disser que o modelo falta: na janela de comandos, nesta pasta, escreva
     `LocalAI_Check.bat --pull` (descarrega ~6 GB uma vez).
3. No fim aparece um resumo com: percentagem de imagens bem reconhecidas,
   segundos por imagem, se usou a placa gráfica (GPU) e o teste de direção
   criativa.
4. Para testar com as suas imagens:
   `LocalAI_Check.bat --folder "C:\caminho\para\uma\pasta\de\imagens"`

**Guarde:** copie o texto da janela (botão direito → Selecionar tudo → Enter)
para um ficheiro `ia-local.txt`.

## Passo 2 — Teste real com os seus projetos (o mais importante)

Escolha **2 ou 3 projetos**, de preferência:

* um bem organizado em subpastas por secção (`01 Logo`, `02 Cores`,
  `03 Embalagens/Copos`…);
* um com pastas menos arrumadas ou nomes em português e em inglês misturados;
* se possível, um com muitas imagens do mesmo tipo (por exemplo 15 posts de
  redes sociais).

Para cada projeto:

1. **Arraste a pasta do projeto para cima de `Teste_Real.bat`**
   (ou faça duplo clique e cole o caminho quando for pedido).
2. Espere. A janela mostra cada etapa: importar, gerar as 5 propostas (com o
   Qwen3-VL se o Ollama estiver pronto), pré-visualizações, PDF e Canva.
3. No fim abre-se o resumo. Fica tudo em
   **`Documentos\Behance Studio Tests\Teste <nome> <data>`**:
   * `RELATORIO.txt` — resumo em português;
   * `Folhas de contacto\` — cada proposta inteira numa imagem;
   * `PDF\` — as propostas em PDF;
   * `Canva\` — um `.pptx` por proposta, para importar no Canva (passo 4);
   * `relatorio-secoes.txt` — cada imagem: pasta, o que o modelo disse, onde
     ficou e o que a IA influenciou (recorte, ordenação, capa);
   * um ficheiro **`.zip`** ao lado da pasta — é este que me envia.

O seu projeto original não é alterado: o teste copia os ficheiros para um
projeto de teste dentro desta pasta.

Para comparar com e sem IA, repita com
`Teste_Real.bat "C:\caminho\do\projeto" --no-ai`.

### O que observar (5 minutos por projeto)

Abra as folhas de contacto e os PDF e anote, por proposta:

1. **Secções:** alguma imagem aparece numa secção que não corresponde à sua
   pasta? (o relatório já conta as que deteta — mas diga-me se vir alguma que
   ele não detetou).
2. **Capa:** a imagem da capa é uma boa escolha?
3. **Recortes:** algum logótipo, texto ou motivo principal aparece cortado?
4. **Variedade:** as 5 propostas parecem realmente diferentes? Há secções
   seguidas com o mesmo aspeto?
5. **Qualidade:** que proposta usaria no Behance, e o que lhe falta?

Escreva as notas num ficheiro `notas.txt` (basta uma linha por problema,
com o nome da proposta e a secção).

## Passo 3 — A interface

Com o Behance Studio aberto (`BehanceStudio.bat`), abra um dos projetos de
teste (`Documentos\Behance Studio Tests\Teste …\Projeto de teste`) e veja:

* **Propostas:** todas têm miniatura? (as que faltam são geradas sozinhas
  em segundo plano — "Preparing preview…");
* **Ficheiros:** os logótipos com fundo transparente veem-se bem?
* **Visualizador:** a lista de secções à esquerda mostra cada secção uma vez
  (as continuações aparecem como "↳ part 2")?

Se algo estiver mal, tire uma captura de ecrã (Windows + Shift + S).

## Passo 4 — Canva real

Os testes feitos aqui usaram um servidor que imita a API do Canva; isso
**não prova** que o Canva mostra os ficheiros corretamente. Só este passo o
prova.

1. Entre em [canva.com](https://www.canva.com) com a sua conta.
2. Na página inicial, arraste para lá um `.pptx` da pasta
   `Teste …\Canva` (ou **Criar um design → Importar ficheiro**). Espere que o
   Canva termine a importação e abra o design.
3. Veja rapidamente: os textos são editáveis? As imagens estão no sítio? Há
   tipos de letra substituídos? (o `… - Canva report.txt` ao lado do `.pptx`
   indica que tipos de letra são usados; a pasta `Fonts for Canva` tem os
   ficheiros e as licenças, que pode carregar no Canva se tiver Canva Pro.)
4. Transfira o design do Canva: **Partilhar → Transferir → Tipo de
   ficheiro: PNG → Selecionar páginas: todas → Transferir**. O Canva dá um
   ficheiro `.zip`.
5. Faça duplo clique em **`Verificar_Canva.bat`** e arraste para a janela,
   quando pedido, primeiro o `.pptx` e depois o `.zip` transferido do Canva.
6. O resultado aparece na janela e numa pasta `Verificacao Canva - …` ao lado
   do `.zip`:
   * percentagem por página (≥ 95 % muito próximo; 85–95 % diferenças
     pequenas, normalmente tipos de letra; < 85 % verificar);
   * imagens lado a lado (original | Canva) das páginas com diferenças;
   * aviso se o número de páginas ou a proporção não coincidirem.

Faça isto pelo menos para **duas propostas diferentes** (por exemplo Minimal
Editorial e Bold Graphic, que usam tipos de letra diferentes).

*(Opcional)* Envio direto para o Canva: requer criar uma integração no
Canva Developer Portal — ver [CANVA.md](CANVA.md#connecting-your-canva-account-optional).
Não é necessário para este teste.

## O que me enviar

* o **`.zip`** de cada projeto testado (passo 2);
* as pastas **`Verificacao Canva - …`** (passo 4);
* `ia-local.txt` (passo 1) e `notas.txt` (passo 2);
* capturas de ecrã de problemas na interface (passo 3).

**Privacidade:** o `.zip` contém apenas relatórios de texto e folhas de
contacto — imagens reduzidas (300 px de largura por coluna) das propostas
geradas. Nunca contém os seus ficheiros originais nem os PDF/PPTX. As imagens
lado a lado do passo 4 mostram páginas das propostas em tamanho médio;
envie-as só se estiver confortável com isso. Nada é enviado
automaticamente: estes comandos não comunicam com nenhum serviço.

## Se algo falhar

* "O Behance Studio ainda não está instalado" → execute `setup_windows.bat`.
* "IA local: não disponível" no relatório → o Ollama não está aberto ou o
  modelo falta; veja o passo 1. O teste continua sem IA.
* "Não foi encontrado um browser Chromium/Edge" → execute de novo
  `setup_windows.bat` (instala o Chromium) ou confirme que o Microsoft Edge
  está instalado.
* `Verificar_Canva.bat` diz que o projeto não foi encontrado → o projeto de
  teste foi movido; execute na linha de comandos
  `… canva-verify "design.pptx" "canva.zip" --project "pasta do projeto"`.
* Qualquer outro erro: copie o texto da janela e envie-mo, junto com
  `%APPDATA%\BehanceStudio\logs\behance_studio.log` se existir.
