// TTPFeedMulti — un solo indicador saca las barras de TODA la watchlist.
//
// POR QUE EXISTE, SI YA ESTABA TTPFeed. La primera version necesitaba un
// grafico por papel: cinco graficos, cada uno desvinculado, en 1 minuto, con
// sesion extendida y el indicador puesto. Son veinte pasos manuales cada
// mañana, y el dia que te olvidas de uno el sistema no te avisa que falta: ese
// papel simplemente no aparece, igual que si no hubiera calificado.
//
// Aca la watchlist es un ARCHIVO DE TEXTO. Se pone en un solo grafico —
// cualquiera, el papel del grafico da igual— y el indicador pide la historia de
// cada ticker por su cuenta con `HistoricalDataManager`.
//
// CON SESION EXTENDIDA SIEMPRE. `LoadExtendedSession = true` va en el pedido,
// no en la configuracion del grafico. Eso saca del medio el otro error que no
// avisa: sin premarket no hay maximo premarket ni expansion, y el dia no
// calificaria nunca sin decir por que.
//
// CÓMO SE USA
//   1. Copiar a  %AppData%\Trade The Pool\Scripts\Indicators\  y compilar.
//   2. Escribir los tickers, uno por linea, en:
//        C:\Users\agust\Apps\algotrade-data\smallcaps\watchlist.txt
//   3. Agregar el indicador a UN grafico cualquiera. Nada mas.
//
// El archivo de watchlist se relee solo: agregar un ticker a mitad de rueda lo
// hace entrar sin tocar la plataforma.

using Runtime.Script;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using TradeApi;
using TradeApi.History;
using TradeApi.Indicators;
using TradeApi.Instruments;
using TradeApi.Quotes;

namespace TTPFeedMulti
{
    public class TTPFeedMulti : IndicatorBuilder
    {
        [InputParameter(InputType.Numeric, "Segundos entre refrescos", 0)]
        [SimpleNumeric(5.0, 600.0)]
        public int SegundosRefresco = 30;

        [InputParameter(InputType.Numeric, "Dias de historia a pedir", 1)]
        [SimpleNumeric(1.0, 5.0)]
        public int DiasHistoria = 1;

        private static readonly string RutaSalida =
            Environment.GetEnvironmentVariable("SMALLCAPS_FEED")
            ?? @"C:\Users\agust\Apps\algotrade-data\smallcaps\feed_vivo.jsonl";

        private static readonly string RutaWatchlist =
            Environment.GetEnvironmentVariable("SMALLCAPS_WATCHLIST")
            ?? @"C:\Users\agust\Apps\algotrade-data\smallcaps\watchlist.txt";

        // Ultima barra escrita POR PAPEL. Sin esto cada refresco reescribiria el
        // dia entero de cada ticker y el archivo creceria decenas de MB por hora.
        private readonly Dictionary<string, DateTime> ultima =
            new Dictionary<string, DateTime>();

        // LAS SERIES SE PIDEN UNA VEZ Y SE MANTIENEN VIVAS.
        //
        // La primera version pedia la historia y la soltaba en el mismo
        // refresco, y no escribia NADA: `HistoricalDataManager.Get` es
        // ASINCRONO —por eso la documentacion lo muestra con un `OnLoaded`—,
        // asi que devolvia una serie todavia vacia, `Count < 2` cortaba, y el
        // `finally` la borraba antes de que llegaran los datos. Manteniendolas,
        // cargan solas y en el refresco siguiente ya tienen barras; ademas
        // siguen actualizandose con el mercado, que es justo lo que hace falta.
        private readonly Dictionary<string, HistoricalData> series =
            new Dictionary<string, HistoricalData>();

        private DateTime proximoRefresco = DateTime.MinValue;

        public TTPFeedMulti() : base()
        {
            Credentials.ProjectName = "TTPFeedMulti";
            SeparateWindow = false;
            Lines.Set("feed");
            Lines["feed"].Visible = false;
        }

        public override void Init()
        {
            ScriptShortName = "TTPFeedMulti";
            SoltarTodo();
            ultima.Clear();
            proximoRefresco = DateTime.MinValue;
        }

        public override void Update(TickStatus args)
        {
            try
            {
                // El indicador vive en un grafico y `Update` corre en cada tick.
                // Sin este freno pediriamos la historia de cinco papeles varias
                // veces por segundo.
                if (DateTime.UtcNow < proximoRefresco)
                    return;
                proximoRefresco = DateTime.UtcNow.AddSeconds(
                    Math.Max(5, SegundosRefresco));

                var lista = LeerWatchlist();

                // Soltar las que ya no estan en la watchlist, o quedarian
                // suscriptas para siempre consumiendo datos de una cuenta que
                // los cobra por conexion.
                foreach (string viejo in series.Keys.ToList())
                {
                    if (!lista.Contains(viejo))
                    {
                        try { HistoricalDataManager.Remove(series[viejo]); }
                        catch { }
                        series.Remove(viejo);
                    }
                }

                int conDatos = 0;
                foreach (string tk in lista)
                    if (Bajar(tk))
                        conDatos++;

                // El nombre del indicador es el unico diagnostico visible que
                // tenemos: los errores se tragan a proposito para no romper el
                // grafico, asi que sin esto un fallo silencioso se veria igual
                // que todo funcionando.
                ScriptShortName = string.Format("TTPFeedMulti {0}/{1}",
                                                conDatos, lista.Count);
            }
            catch
            {
                // Silencio deliberado: el grafico tiene que seguir andando.
            }
        }

        // ticker -> precio de referencia (0 si la linea no lo trae)
        private readonly Dictionary<string, double> esperado =
            new Dictionary<string, double>();

        private List<string> LeerWatchlist()
        {
            var salida = new List<string>();
            try
            {
                if (!File.Exists(RutaWatchlist))
                    return salida;
                // Se relee en cada refresco a proposito: agregar un ticker a
                // mitad de rueda tiene que entrar sin tocar la plataforma.
                foreach (string linea in File.ReadAllLines(RutaWatchlist))
                {
                    string cruda = (linea ?? "").Trim();
                    if (cruda.Length == 0 || cruda.StartsWith("#"))
                        continue;
                    string[] partes = cruda.Split(
                        new[] { ' ', '\t', ',', ';' },
                        StringSplitOptions.RemoveEmptyEntries);
                    string t = partes[0].ToUpperInvariant();
                    double px = 0.0;
                    if (partes.Length > 1)
                        double.TryParse(partes[1], NumberStyles.Any,
                                        CultureInfo.InvariantCulture, out px);
                    esperado[t] = px;
                    if (!salida.Contains(t))
                        salida.Add(t);
                }
            }
            catch { }
            return salida;
        }

        // EL SIMBOLO NO ALCANZA PARA IDENTIFICAR EL PAPEL.
        //
        // `GetInstruments("SSM")` devolvio un instrumento que cotizaba a $59 con
        // 116 acciones de volumen, cuando el SSM de la watchlist estaba a $3,85
        // subiendo 43%. Un mismo simbolo existe en mas de un mercado o clase, y
        // `FirstOrDefault()` agarra el que venga primero. Eso es PEOR que no
        // tener el papel: la pantalla mostraria señales calculadas sobre un
        // instrumento que no es el que se va a operar, y nada lo delataria.
        //
        // `Instrument` no expone el mercado —solo Symbol, Type, DayInfo y
        // TradingStatus— asi que se desambigua por PRECIO, que es un dato que ya
        // trae el escaner. Si ninguno se parece, no se manda nada: el papel
        // queda como faltante en el contador del titulo y se ve.
        private Instrument Elegir(string ticker)
        {
            var todos = InstrumentsManager.GetInstruments(ticker).ToList();
            if (todos.Count == 0)
                return null;

            // UN SOLO CANDIDATO NO TIENE AMBIGUEDAD QUE RESOLVER, y esto no es
            // un atajo: `DayInfo` viene VACIO hasta que el instrumento esta
            // suscripto. Comparando precios antes de pedir la serie, `Last` y
            // `PrevClose` daban 0 para todos menos el del grafico, y el filtro
            // descartaba 6 de 7 papeles — se veia como "TTPFeedMulti 1/7".
            // Antes funcionaba porque el precio previo se leia DESPUES del
            // `Get`, que es lo que suscribe.
            if (todos.Count == 1)
                return todos[0];

            double px;
            if (!esperado.TryGetValue(ticker, out px) || px <= 0)
                return todos.FirstOrDefault();   // sin referencia, el primero

            // Hay mas de uno con el mismo simbolo: recien aca hace falta el
            // precio, y para tenerlo hay que suscribirse primero. Puede tardar
            // un refresco en llegar; mientras tanto no se manda nada, que es
            // preferible a mandar el instrumento equivocado.
            foreach (var i in todos)
            {
                try { InstrumentsManager.Subscribe(i, QuoteTypes.Trade); }
                catch { }
            }

            Instrument mejor = null;
            double mejorDist = double.MaxValue;
            foreach (var inst in todos)
            {
                double actual = 0.0;
                try
                {
                    actual = inst.DayInfo.Last;
                    if (actual <= 0)
                        actual = inst.DayInfo.PrevClose;
                }
                catch { }
                if (actual <= 0)
                    continue;
                double dist = Math.Abs(actual - px) / px;
                if (dist < mejorDist)
                {
                    mejorDist = dist;
                    mejor = inst;
                }
            }
            // 25% de tolerancia: un gapper se mueve mucho entre que el escaner
            // lo vio y este refresco, pero no diez veces.
            return mejorDist <= 0.25 ? mejor : null;
        }

        private bool Bajar(string ticker)
        {
            HistoricalData data = null;
            try
            {
                if (!series.TryGetValue(ticker, out data) || data == null)
                {
                    Instrument inst = Elegir(ticker);
                    if (inst == null)
                        return false;

                    var req = new TimeHistoricalRequest(inst, DataType.Trade,
                                                        Period.Minute, 1);
                    // LO QUE HACE QUE ESTO SIRVA: el premarket entra si o si,
                    // sin depender de como este configurado ningun grafico.
                    req.LoadExtendedSession = true;

                    var interv = new Interval(
                        DateTime.UtcNow.AddDays(-Math.Max(1, DiasHistoria)),
                        DateTime.UtcNow);
                    data = HistoricalDataManager.Get(req, interv);
                    if (data == null)
                        return false;
                    series[ticker] = data;
                }
                // Todavia cargando: se vuelve a mirar en el refresco siguiente.
                if (data.Count < 2)
                    return false;

                Instrument inst2 = null;
                try { inst2 = data.HistoricalRequest.Instrument; } catch { }

                double pc = 0.0;
                try { if (inst2 != null) pc = inst2.DayInfo.PrevClose; } catch { }

                DateTime tope;
                if (!ultima.TryGetValue(ticker, out tope))
                    tope = DateTime.MinValue;

                var bd = data as BarData;
                var sb = new StringBuilder();
                DateTime masNueva = tope;
                var inv = CultureInfo.InvariantCulture;

                // De la mas vieja a la mas nueva. El indice 0 es la barra EN
                // CURSO: se saltea, igual que en el backtest, donde una señal
                // nunca mira la vela que todavia puede cambiar.
                for (int i = data.Count - 1; i >= 1; i--)
                {
                    DateTime t = data.GetTimeUtc(i);
                    if (t <= tope)
                        continue;

                    double v = 0.0;
                    if (bd != null)
                        v = bd.GetVolume(i);

                    sb.Append("{\"t\":\"")
                      .Append(t.ToString("yyyy-MM-ddTHH:mm:ssZ", inv))
                      .Append("\",\"s\":\"").Append(ticker)
                      .Append("\",\"o\":").Append(data.GetValue(PriceType.Open, i).ToString("G17", inv))
                      .Append(",\"h\":").Append(data.GetValue(PriceType.High, i).ToString("G17", inv))
                      .Append(",\"l\":").Append(data.GetValue(PriceType.Low, i).ToString("G17", inv))
                      .Append(",\"c\":").Append(data.GetValue(PriceType.Close, i).ToString("G17", inv))
                      .Append(",\"v\":").Append(v.ToString("G17", inv))
                      .Append(",\"pc\":").Append(pc.ToString("G17", inv))
                      .Append("}").Append(Environment.NewLine);

                    if (t > masNueva)
                        masNueva = t;
                }

                if (sb.Length > 0 && Volcar(sb.ToString()))
                    ultima[ticker] = masNueva;
                return true;
            }
            catch
            {
                return false;
            }
        }

        private void SoltarTodo()
        {
            foreach (var d in series.Values)
            {
                try { HistoricalDataManager.Remove(d); }
                catch { }
            }
            series.Clear();
        }

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
