# 04 Pedido atrasado e encaminhamento

**Cliente:** Oi! Meu pedido ainda não chegou e era pra ter chegado faz tempo!

**Duda:** Oi! Para eu verificar o que aconteceu com a entrega, preciso do número do seu pedido e do e‑mail ou telefone cadastrado. Pode me passar esses dados? 😊

**Cliente:** Pedido 8, meu telefone é (67) 99654-7821

> 🔧 *Ferramenta consultada:* `consultar_pedido({"contato": "(67) 99654-7821", "numero_pedido": 8})`
> 🔧 *Ferramenta consultada:* `encaminhar_para_atendente({"contato": "(67) 99654-7821", "motivo": "atraso_pedido", "numero_pedido": 8, "resumo": "Pedido 8 enviado em 15/02/2026, entrega prevista 28/02/2026, ainda não chegou."})`

**Duda:** Ana, desculpe pelo atraso – a entrega estava prevista para 28/02/2026 e ainda não chegou. Já encaminhei seu caso para a equipe de atendimento. O protocolo é **EM-20261109-34B0** e eles retornam em até 24 h úteis.

Posso ajudar em mais alguma coisa?

**Cliente:** Quero registrar uma reclamação, por favor.

**Duda:** Claro, Ana! Para registrar sua reclamação, poderia me enviar um breve resumo do que aconteceu (por exemplo, atraso na entrega, produto errado, etc.)? Assim já encaminho tudo certinho.

**Cliente:** É sobre esse atraso mesmo, já faz meses que estou esperando e ninguém me avisou nada.

> 🔧 *Ferramenta consultada:* `encaminhar_para_atendente({"contato": "(67) 99654-7821", "motivo": "reclamacao", "numero_pedido": 8, "resumo": "Atraso na entrega do pedido 8, que deveria ter chegado em 28/02/2026, sem aviso da loja."})`

**Duda:** Pronto, Ana! Sua reclamação foi registrada com o protocolo **EM-20261109-16A9**. A equipe de atendimento vai analisar e responde em até 24 h úteis.

Precisa de mais alguma coisa?
