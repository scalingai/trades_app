// TTPFeed — saca las barras de Trade The Pool a un archivo que lee Python.
//
// QUÉ HACE Y QUÉ NO. No decide nada: escribe. Toda la lógica vive en Python,
// donde está el motor que ya validamos y donde se puede versionar y testear.
// Este archivo es un caño, y cuanto más tonto sea, menos se rompe.
//
// POR QUÉ ES UN INDICADOR Y NO UNA ESTRATEGIA. Los ejemplos de estrategia traen
// `Credentials.Password` en el constructor, o sea que pueden requerir registro
// con el proveedor. Los indicadores sólo llevan `ProjectName`. Un indicador
// alcanza para lo que necesitamos y no depende de que nos habiliten nada.
//
// CÓMO SE USA
//   1. Copiar este archivo a  %AppData%\Trade The Pool\Scripts\Indicators\
//   2. En la plataforma, abrir un gráfico de 1 minuto por cada papel de la
//      watchlist, CON SESIÓN EXTENDIDA PRENDIDA, y agregarle este indicador.
//   3. Cada gráfico escribe sus barras al MISMO archivo, con el símbolo en cada
//      línea. Python las separa.
//
// UNA LÍNEA POR BARRA, en JSON:
//   {"t":"2026-09-01T14:31:00Z","s":"WETO","o":6.30,"h":6.35,"l":6.28,"c":6.31,
//    "v":12400,"pc":5.48}
//
// `pc` es el cierre previo, que hace falta para el gap y la expansión y no se
// puede derivar de las barras del día.

using Runtime.Script;
using System;
using System.Globalization;
using System.IO;
using System.Text;
using TradeApi;
using TradeApi.History;
using TradeApi.Indicators;

namespace TTPFeed
{
    public class TTPFeed : IndicatorBuilder
    {
        // La ruta NO es un parámetro de la interfaz: `InputType` sólo tiene
        // Numeric, Combobox, Checkbox, Color, DateTime y TimeInterval — no hay
        // campo de texto (lo dijo el compilador, no la documentación). Se
        // resuelve por variable de entorno con un default fijo, que además
        // evita tener que reconfigurarla gráfico por gráfico.
        private static readonly string RutaSalida =
            Environment.GetEnvironmentVariable("SMALLCAPS_FEED")
            ?? @"C:\Users\agust\Apps\algotrade-data\smallcaps\feed_vivo.jsonl";

        private DateTime ultimaEscrita = DateTime.MinValue;
        private string simbolo = "?";
        private double cierrePrevio = 0.0;
        private bool volcadoHecho = false;

        public TTPFeed() : base()
        {
            Credentials.ProjectName = "TTPFeed";
            SeparateWindow = false;
            Lines.Set("feed");            // línea invisible: el indicador no dibuja
            Lines["feed"].Visible = false;
        }

        public override void Init()
        {
            ScriptShortName = "TTPFeed";
            volcadoHecho = false;
            ultimaEscrita = DateTime.MinValue;
            LeerInstrumento();
        }

        // EL INSTRUMENTO SALE DE LA SERIE DEL GRÁFICO, NO DE `InstrumentsManager.Current`.
        //
        // La documentación de la plataforma usa `InstrumentsManager.Current` en su
        // ejemplo, y acá sería un desastre: ése es el papel SELECCIONADO en la
        // interfaz, o sea uno solo para toda la aplicación. Con cuatro gráficos
        // corriendo este indicador, los cuatro etiquetarían sus barras con el
        // ticker del que tenga el foco, y Python mezclaría cuatro papeles en uno.
        // `HistoricalRequest.Instrument` es el de ESTA serie, que es lo que hace
        // falta cuando hay un gráfico por papel.
        private void LeerInstrumento()
        {
            try
            {
                var inst = HistoryDataSeries.HistoricalRequest.Instrument;
                simbolo = inst.Symbol;
                cierrePrevio = inst.DayInfo.PrevClose;
            }
            catch { /* nunca romper el gráfico por el feed */ }
        }

        public override void Update(TickStatus args)
        {
            try
            {
                if (HistoryDataSeries.Count < 2)
                    return;

                if (simbolo == "?" || cierrePrevio <= 0)
                    LeerInstrumento();

                // EL VOLCADO INICIAL: TODA la historia que el gráfico tenga.
                //
                // Sin esto, el feed arranca en el minuto en que enganchás el
                // indicador. Si lo enganchás a las 09:00 te perdés el premarket
                // entero, y sin premarket no hay máximo premarket ni expansión:
                // el día NO CALIFICARÍA NUNCA y la pantalla se vería vacía sin
                // decir por qué. Escribir la historia de una resuelve también el
                // caso de reiniciar la plataforma a mitad de rueda.
                //
                // Python deduplica por (símbolo, timestamp), así que volver a
                // escribir barras ya escritas no rompe nada.
                if (!volcadoHecho)
                {
                    VolcarHistoria();
                    volcadoHecho = true;
                    return;
                }

                // De acá en más, sólo la barra recién cerrada. El índice 0 es la
                // que se está formando y su precio todavía puede cambiar: es la
                // misma disciplina que el backtest, donde una señal nunca mira la
                // vela en curso.
                EscribirBarra(1);
            }
            catch
            {
                // Silencio deliberado. Si el feed falla, el gráfico tiene que
                // seguir andando: se está operando con esta pantalla.
            }
        }

        private void VolcarHistoria()
        {
            var sb = new StringBuilder();
            DateTime ultima = DateTime.MinValue;
            // De la más vieja a la más nueva. El índice 0 es la barra en curso,
            // así que se arranca en 1.
            for (int i = HistoryDataSeries.Count - 1; i >= 1; i--)
            {
                string linea = LineaDe(i, ref ultima);
                if (linea != null)
                    sb.AppendLine(linea);
            }
            if (sb.Length > 0 && Volcar(sb.ToString()))
                ultimaEscrita = ultima;
        }

        private void EscribirBarra(int offset)
        {
            DateTime t = HistoryDataSeries.GetTimeUtc(offset);
            if (t <= ultimaEscrita)      // esa barra ya se escribió
                return;
            DateTime ultima = ultimaEscrita;
            string linea = LineaDe(offset, ref ultima);
            if (linea != null && Volcar(linea + Environment.NewLine))
                ultimaEscrita = ultima;
        }

        private string LineaDe(int i, ref DateTime ultima)
        {
            DateTime t = HistoryDataSeries.GetTimeUtc(i);
            if (t <= ultima)
                return null;

            double o = HistoryDataSeries.GetValue(PriceType.Open, i);
            double h = HistoryDataSeries.GetValue(PriceType.High, i);
            double l = HistoryDataSeries.GetValue(PriceType.Low, i);
            double c = HistoryDataSeries.GetValue(PriceType.Close, i);

            double v = 0.0;
            var bd = HistoryDataSeries as BarData;
            if (bd != null)
                v = bd.GetVolume(i);

            var inv = CultureInfo.InvariantCulture;
            var sb = new StringBuilder();
            sb.Append("{\"t\":\"").Append(t.ToString("yyyy-MM-ddTHH:mm:ssZ", inv))
              .Append("\",\"s\":\"").Append(simbolo)
              .Append("\",\"o\":").Append(o.ToString("G17", inv))
              .Append(",\"h\":").Append(h.ToString("G17", inv))
              .Append(",\"l\":").Append(l.ToString("G17", inv))
              .Append(",\"c\":").Append(c.ToString("G17", inv))
              .Append(",\"v\":").Append(v.ToString("G17", inv))
              .Append(",\"pc\":").Append(cierrePrevio.ToString("G17", inv))
              .Append("}");
            ultima = t;
            return sb.ToString();
        }

        // Append con FileShare.ReadWrite: varios gráficos escriben el mismo
        // archivo y Python lo lee al mismo tiempo. Sin esto, el segundo gráfico
        // que arranca se cuelga.
        private bool Volcar(string texto)
        {
            try
            {
                var dir = Path.GetDirectoryName(RutaSalida);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                    Directory.CreateDirectory(dir);
                using (var fs = new FileStream(RutaSalida, FileMode.Append,
                                               FileAccess.Write, FileShare.ReadWrite))
                using (var w = new StreamWriter(fs))
                {
                    w.Write(texto);
                    w.Flush();
                }
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
