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
//      watchlist y agregarle este indicador.
//   3. Cada gráfico escribe sus barras al MISMO archivo, con el símbolo en cada
//      línea. Python las separa.
//
// UNA LÍNEA POR BARRA CERRADA, en JSON:
//   {"t":"2026-09-01T14:31:00Z","s":"WETO","o":6.30,"h":6.35,"l":6.28,"c":6.31,
//    "v":12400,"pc":5.48}
//
// `pc` es el cierre previo, que hace falta para el gap y la expansión y no se
// puede derivar de las barras del día.
//
// SÓLO SE ESCRIBE LA BARRA YA CERRADA (offset 1), nunca la que se está
// formando. Es la misma disciplina que el backtest: una señal que mira la barra
// en curso está mirando un precio que todavía puede cambiar.

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
        [InputParameter(InputType.Text, "Archivo de salida", 0)]
        public string RutaSalida = @"C:\Users\agust\Apps\algotrade-data\smallcaps\feed_vivo.jsonl";

        private DateTime ultimaEscrita = DateTime.MinValue;
        private string simbolo = "?";
        private double cierrePrevio = 0.0;

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
            try
            {
                var inst = HistoryDataSeries.HistoricalRequest.Instrument;
                simbolo = inst.Symbol;
                // El cierre previo vive en DayInfo y es lo único del día anterior
                // que necesitamos. Si no está, queda en 0 y Python lo resuelve
                // con su propia base de barras diarias.
                cierrePrevio = inst.DayInfo.PrevClose;
            }
            catch { /* nunca romper el gráfico por el feed */ }
        }

        public override void Update(TickStatus args)
        {
            try
            {
                // Se necesitan al menos dos barras: la actual (0) y la cerrada (1).
                if (HistoryDataSeries.Count < 2)
                    return;

                DateTime t = HistoryDataSeries.GetTimeUtc(1);
                if (t <= ultimaEscrita)      // esa barra ya se escribió
                    return;

                double o = HistoryDataSeries.GetValue(PriceType.Open, 1);
                double h = HistoryDataSeries.GetValue(PriceType.High, 1);
                double l = HistoryDataSeries.GetValue(PriceType.Low, 1);
                double c = HistoryDataSeries.GetValue(PriceType.Close, 1);

                double v = 0.0;
                var bd = HistoryDataSeries as BarData;
                if (bd != null)
                    v = bd.GetVolume(1);

                if (cierrePrevio <= 0)
                {
                    try { cierrePrevio = HistoryDataSeries.HistoricalRequest
                                            .Instrument.DayInfo.PrevClose; }
                    catch { }
                }

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

                // Append con FileShare.ReadWrite: varios gráficos escriben el
                // mismo archivo y Python lo lee al mismo tiempo. Sin esto, el
                // segundo gráfico que arranca se cuelga.
                using (var fs = new FileStream(RutaSalida, FileMode.Append,
                                               FileAccess.Write, FileShare.ReadWrite))
                using (var w = new StreamWriter(fs))
                {
                    w.WriteLine(sb.ToString());
                    w.Flush();
                }
                ultimaEscrita = t;
            }
            catch
            {
                // Silencio deliberado. Si el feed falla, el gráfico tiene que
                // seguir andando: se está operando con esta pantalla.
            }
        }
    }
}
