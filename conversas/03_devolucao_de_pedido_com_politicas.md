# 03 Devolucao de pedido com politicas

**Cliente:** Oi, me arrependi da minha compra. Posso devolver meu pedido?

**Duda:** Oi! Claro, vamos ver como fazer a devolução. Você pode me passar o número do pedido e o e‑mail ou telefone cadastrado nele? Assim confirmo os prazos e as condições. 😊

**Cliente:** É o pedido 1, meu e-mail é pedro.oliveira@jmail.com

> 🔧 *Ferramenta consultada:* `consultar_pedido({"contato": "pedro.oliveira@jmail.com", "numero_pedido": 1})`
> 🔧 *Ferramenta consultada:* `consultar_politica({"secao": "trocas_e_devolucoes"})`

**Duda:** Oi, Pedro. O prazo de arrependimento de 7 dias já está encerrado (o pedido foi entregue em 25/10/2025). Por isso não conseguimos aceitar a devolução por esse motivo.

Se o violão estiver com algum defeito de fabricação, podemos analisar a garantia do fabricante. Quer que eu verifique essa possibilidade ou encaminhe seu caso para a equipe de atendimento?

**Cliente:** Poxa. E se ele apresentar algum defeito, o que eu faço?

> 🔧 *Ferramenta consultada:* `consultar_politica({"secao": "garantia"})`
> 🔧 *Ferramenta consultada:* `consultar_pedido({"contato": "pedro.oliveira@jmail.com", "numero_pedido": 1})`

**Duda:** Pedro, como a garantia legal de 90 dias já acabou, ainda podemos acionar a garantia do fabricante (geralmente de 6 meses a 2 anos).  

**O que fazer:**  
1. Localize o certificado de garantia que veio com o Martin D‑28.  
2. Verifique o prazo ainda válido e as condições (não pode ter sofrido quedas ou alterações).  
3. Traga o violão à Empório da Música com a nota fiscal e o certificado.  
4. Nossa equipe vai abrir a solicitação junto ao fabricante e, se necessário, encaminhar para reparo ou troca conforme a política do fabricante.

Posso registrar seu caso e encaminhar para a equipe de garantia, ou você prefere trazer o instrumento direto à loja?
