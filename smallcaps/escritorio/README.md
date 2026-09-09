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

## El acceso directo

Apunta a `pythonw.exe` con `lanzar.pyw` como argumento, y usa `trades.ico`.
Vive en el Escritorio como **Small Caps.lnk**. Para anclarlo a la barra de
tareas: abrir la app, botón derecho en su ícono de la barra, *Anclar a la barra
de tareas*.

## Si algo no arranca

Sin consola no hay dónde ver el error, así que la salida va a:

    C:\Users\agust\Apps\algotrade-data\escritorio\app.log

Se pisa en cada arranque: interesa el de ahora, no el historial.
