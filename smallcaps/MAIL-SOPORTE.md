# Mail al soporte de Trade The Pool

**Para:** Help@TradeThePool.com
**Horario de atención:** domingo a jueves 07:00–17:00 GMT, viernes 07:00–12:00 GMT
*(la dirección salió de sitios de reseñas, no de su web — si rebota, hay chat en
vivo en tradethepool.com y teléfono +1 929-955-5595)*

**Asunto:** Short locate fees and account rules — questions before purchasing an evaluation

---

Hi,

I'm evaluating your stock funding program before purchasing an evaluation. My
strategy is intraday short selling of US small caps, so borrow availability and
cost are the main variables for me. A few specific questions:

**1. Locate fees**

For hard-to-borrow small caps, what is the typical locate cost **per share**?
I understand it varies by security and by time of day — a range or a recent
example would be very helpful.

To make it concrete, these are the kind of names and sizes I trade (recent
gappers, roughly 100–250 shares per name per day):

| ticker | date | approx. entry price |
|---|---|---|
| DAIC | 2026-08-25 | $3.68 |
| WETO | 2026-08-14 | $8.98 |
| BYAH | 2026-08-06 | $4.90 |
| EZRA | 2026-08-03 | $3.67 |

**2. Are locates charged during the funded stage?**

I've read that HTB locates are provided free during the evaluation. Does that
also apply once the account is funded? If not, how are they billed — per
request, per share, or as a percentage?

**3. Reusing a locate within the day**

If I locate N shares in the morning, can I open and close positions repeatedly
during the session without paying again, as long as I never exceed N shares
short at the same time?

**4. Risk limits on the $20,000 buying power plan**

What are the **maximum daily loss** and the **maximum drawdown**, in dollars?
And is the drawdown static from the initial balance or trailing?

**5. Multiple evaluations**

Can I run more than one evaluation account at the same time? Is there a limit,
and is there any restriction on trading the same setups across accounts?

Thanks very much,
Agustín

---

## Por qué cada pregunta

**La 1 es la que decide el proyecto.** Con locate de $0,05 por acción una cuenta
rinde ~$9.000 al año; a $0,30 rinde $2.200; arriba de $0,87 el sistema pierde
plata. Es el único número del que no tenemos ninguna medición propia.

**La 3 confirma cómo modelamos el costo.** Todo el sistema calcula el locate
sobre el **pico de exposición simultánea**, no sobre la suma de los trades. Si
la respuesta fuera "se paga por operación", el modelo entero está mal y hay que
rehacerlo.

**La 4 fija el tamaño.** Todo el dimensionamiento supone tope de drawdown de
$1.000 y pérdida diaria de $400. Si el límite diario fuera 1% en vez de 2%, el
riesgo por sesión se corta a la mitad y el horizonte se duplica.

**La 5 decide si son tres cuentas o una.**

La 2 es la única que se puede responder sola con la experiencia: si los locates
son gratis durante la evaluación, los $97 compran tres semanas de medición del
número real sin arriesgar nada.
