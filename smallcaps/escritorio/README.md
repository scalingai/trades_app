# El acceso directo de escritorio

`lanzar.pyw` abre small caps como una app: sin consola, en una ventana de Chrome
en modo aplicación (`--app=`), con su propio botón en la barra de tareas.

## Por qué hay una copia acá y otra afuera

La que CORRE vive en el directorio de datos:

    C:\Users\agust\Apps\algotrade-data\escritorio\lanzar.pyw

Tiene que estar ahí y no en el repo, porque el repo es un *worktree* de git y es
descartable: el día que se limpia, se lleva puesto el acceso directo del
escritorio y el ícono. El directorio de datos sobrevive.

Esta copia del repo es el respaldo versionado. Si la de afuera se pierde:

    copy smallcaps\escritorio\lanzar.pyw  C:\Users\agust\Apps\algotrade-data\escritorio\
    copy smallcaps\escritorio\trades.ico  C:\Users\agust\Apps\algotrade-data\escritorio\

**Si se edita una, hay que copiar a la otra.** No hay sincronización automática
a propósito: un script que copie solo entre el repo y el directorio de datos es
justo el tipo de magia que después nadie entiende cuando falla.

## Qué levanta

`smallcaps/arrancar.py --auto`, o sea el supervisor completo: visor + feed de
Yahoo + la watchlist según la hora. Hasta el 2026-09-09 levantaba sólo el visor,
y por eso la pantalla se veía vacía tres ruedas seguidas — el visor dibuja pero
no baja datos.

## La ventana NO es Chrome (desde 2026-09-09)

Antes se abría Chrome con `--app=`. Eso da una ventana sin barra de direcciones,
pero sigue siendo Chrome: en la barra de tareas aparece con el logo de Chrome y
anclarla ancla a Chrome. Ahora la ventana la hace **WebView2**, el motor que ya
viene con Windows 11, vía `pywebview` (`pip install pywebview`). Si `pywebview`
no está, cae a Chrome como antes y avisa nada — funciona igual, se ve peor.

## El acceso directo y el ícono anclado

Son DOS cosas y hacen falta las dos:

| | quién lo pone |
|---|---|
| ícono de la VENTANA | `webview.start(icon=...)` en `lanzar.pyw` |
| identidad de la APP (`AppUserModelID`) | el proceso en `lanzar.pyw` **y** el `.lnk` |

Sin el `AppUserModelID`, Windows agrupa la ventana con "Python" y al anclarla
ancla `python.exe`. Los dos lados tienen que declarar el mismo:
`Agus.SmallCaps.Visor`.

El del `.lnk` no lo escribe `WScript.Shell` —esa propiedad va por
`IPropertyStore`, o sea COM—, por eso hay un script aparte:

    python fijar_identidad.py

Rehace el acceso directo del Escritorio con el ícono y la identidad. Después:
desanclar lo que hubiera, abrir el acceso directo, y botón derecho en su ícono
de la barra > *Anclar a la barra de tareas*.

## Si algo no arranca

Sin consola no hay dónde ver el error, así que la salida va a:

    C:\Users\agust\Apps\algotrade-data\escritorio\app.log

Se pisa en cada arranque: interesa el de ahora, no el historial.
