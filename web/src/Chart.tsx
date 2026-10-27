import { memo, useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  type IChartApi,
  type LogicalRange,
  type Time,
} from "lightweight-charts";
import { Maximize2, LocateFixed, ZoomIn, ZoomOut } from "lucide-react";
import { api, type Json, price } from "./api";
import { Empty, Notice } from "./components";

export const MarketChart = memo(function MarketChart({
  symbol,
  minutes,
  hours,
  height,
  endpoint,
}: {
  symbol: string;
  minutes: number;
  hours: number;
  height: number;
  endpoint?: string;
}) {
  const priceEl = useRef<HTMLDivElement>(null),
    volumeEl = useRef<HTMLDivElement>(null),
    rsiEl = useRef<HTMLDivElement>(null);
  const charts = useRef<IChartApi[]>([]),
    series = useRef<any[]>([]),
    rangeKey = `gx-range-${symbol}-${minutes}`;
  const [points, setPoints] = useState<Json[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [overlay, setOverlay] = useState<Json | null>(null);
  const overlaySeries = useRef<any[]>([]),
    levelLines = useRef<any[]>([]);
  const [volumeHeight, setVolumeHeight] = useState(
    () => Number(localStorage.getItem("gx-volume-height")) || 65,
  );
  const [rsiHeight, setRsiHeight] = useState(
    () => Number(localStorage.getItem("gx-rsi-height")) || 120,
  );
  const [ema, setEma] = useState(true);
  const [isFollowing, setIsFollowing] = useState(true);
  const syncing = useRef(false),
    updating = useRef(false),
    following = useRef(true),
    appliedRange = useRef<LogicalRange | null>(null);
  const requestKey = `${symbol}|${minutes}|${hours}|${endpoint || ""}`;
  const loadedKey = useRef("");
  function follow(value: boolean) {
    following.current = value;
    setIsFollowing(value);
    try {
      localStorage.setItem(`${rangeKey}-following`, String(value));
    } catch {
      /* Storage may be disabled. */
    }
  }
  function remember(range: LogicalRange) {
    try {
      localStorage.setItem(rangeKey, JSON.stringify(range));
    } catch {
      /* Storage may be disabled. */
    }
  }
  function applyRange(range: LogicalRange) {
    appliedRange.current = range;
    charts.current.forEach((chart) =>
      chart.timeScale().setVisibleLogicalRange(range),
    );
    remember(range);
  }
  function latestRange(count: number, width: number): LogicalRange {
    const to = Math.max(0, count - 1) + 3;
    return { from: to - width, to } as LogicalRange;
  }
  const ctTime = (t: number) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Chicago",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(t * 1000));
  useEffect(() => {
    appliedRange.current = null;
    try {
      following.current =
        localStorage.getItem(`${rangeKey}-following`) !== "false";
    } catch {
      following.current = true;
    }
    setIsFollowing(following.current);
    let stopped = false,
      timer: ReturnType<typeof setTimeout>,
      controller: AbortController;
    const load = async () => {
      try {
        controller = new AbortController();
        const data = await api(
          endpoint ||
            "/chart?symbol=" +
              encodeURIComponent(symbol) +
              `&minutes=${minutes}&hours=${hours}`,
          undefined,
          "GET",
          controller.signal,
        );
        if (!stopped) {
          loadedKey.current = requestKey;
          setPoints(data.points);
          setOverlay(endpoint ? data : null);
          setError("");
          setLoading(false);
        }
      } catch (e) {
        if (!stopped) {
          setError(String(e));
          setLoading(false);
        }
      } finally {
        if (!stopped) timer = setTimeout(load, 2000);
      }
    };
    void load();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [symbol, minutes, hours, endpoint]);
  useEffect(() => {
    const options = {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#151716" },
        textColor: "#a0a59f",
        fontFamily: "Inter, Segoe UI, sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#2c302d" },
        horzLines: { color: "#2c302d" },
      },
      rightPriceScale: { borderColor: "#343c33", minimumWidth: 75 },
      timeScale: {
        borderColor: "#343c33",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (t: Time) => ctTime(Number(t)),
      },
      localization: {
        timeFormatter: (t: Time) =>
          new Date(Number(t) * 1000).toLocaleString("en-US", {
            timeZone: "America/Chicago",
          }) + " CT",
      },
    };
    const p = createChart(priceEl.current!, options),
      v = createChart(volumeEl.current!, {
        ...options,
        timeScale: { ...options.timeScale, visible: false },
      }),
      r = createChart(rsiEl.current!, options);
    p.timeScale().applyOptions({ visible: false });
    const candle = p.addCandlestickSeries({
      upColor: "#82d6ad",
      downColor: "#e09191",
      borderVisible: false,
      wickUpColor: "#82d6ad",
      wickDownColor: "#e09191",
    });
    const volume = v.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const rsi = r.addLineSeries({
      color: "#beaed3",
      lineWidth: 1,
      priceLineVisible: false,
    });
    for (const n of [30, 50, 70])
      rsi.createPriceLine({
        price: n,
        color: "#6b716c",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: "",
      });
    const fast = p.addLineSeries({
        color: "#b4cba3",
        lineWidth: 1,
        priceLineVisible: false,
      }),
      slow = p.addLineSeries({
        color: "#d2aa82",
        lineWidth: 1,
        priceLineVisible: false,
      });
    charts.current = [p, v, r];
    series.current = [candle, volume, rsi, fast, slow];
    for (const current of charts.current) {
      current.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (!range || syncing.current || updating.current) return;
        const applied = appliedRange.current;
        if (
          applied &&
          Math.abs(applied.from - range.from) < 0.01 &&
          Math.abs(applied.to - range.to) < 0.01
        )
          return;
        syncing.current = true;
        appliedRange.current = range;
        charts.current
          .filter((chart) => chart !== current)
          .forEach((chart) => chart.timeScale().setVisibleLogicalRange(range));
        syncing.current = false;
        follow(following.current && range.to > candle.data().length - 3);
        remember(range);
      });
    }
    return () => {
      charts.current = [];
      overlaySeries.current = [];
      levelLines.current = [];
      [p, v, r].forEach((c) => c.remove());
    };
  }, [symbol, minutes, rangeKey]);
  useEffect(() => {
    if (!series.current.length || loadedKey.current !== requestKey) return;
    const [candle, vol, rsi, fast, slow] = series.current;
    const old = charts.current[0].timeScale().getVisibleLogicalRange();
    const first = candle.data().length === 0;
    updating.current = true;
    candle.setData(
      points.map((p) => ({
        time: p.time,
        open: p.open,
        high: p.high,
        low: p.low,
        close: p.close,
      })),
    );
    vol.setData(
      points.map((p) =>
        p.volume == null
          ? { time: p.time }
          : {
              time: p.time,
              value: p.volume,
              color: p.close >= p.open ? "#3b6650" : "#734d4a",
            },
      ),
    );
    rsi.setData(
      points.map((p) =>
        p.rsi == null ? { time: p.time } : { time: p.time, value: p.rsi },
      ),
    );
    fast.setData(points.map((p) => ({ time: p.time, value: p.ema20 })));
    slow.setData(points.map((p) => ({ time: p.time, value: p.ema50 })));
    if (!points.length) {
      updating.current = false;
      return;
    }
    let saved: LogicalRange | null = null;
    try {
      const value = JSON.parse(localStorage.getItem(rangeKey) || "null");
      if (
        value &&
        Number.isFinite(value.from) &&
        Number.isFinite(value.to) &&
        value.to > value.from
      )
        saved = value;
    } catch {
      /* Ignore invalid old viewport data. */
    }
    if (first && saved && !following.current) {
      const shift = Math.max(0, saved.to - (points.length + 2));
      applyRange({
        from: saved.from - shift,
        to: saved.to - shift,
      } as LogicalRange);
    } else if (first) {
      applyRange(
        latestRange(points.length, saved ? saved.to - saved.from : 100),
      );
    } else if (!following.current && old) {
      applyRange(old);
    } else
      applyRange(latestRange(points.length, old ? old.to - old.from : 100));
    updating.current = false;
  }, [points, rangeKey]);
  useEffect(() => {
    const chart = charts.current[0],
      candle = series.current[0];
    if (!chart || !candle) return;
    const viewport = appliedRange.current || chart.timeScale().getVisibleLogicalRange();
    updating.current = true;
    levelLines.current.forEach((line) => candle.removePriceLine(line));
    levelLines.current = [];
    candle.setMarkers(
      (overlay?.markers || []).filter((marker: Json) =>
        points.some((point) => point.time === marker.time),
      ),
    );
    if (overlay?.box) {
      const box = overlay.box;
      const levels = Object.values(overlay.levels || {}).filter(
        (value): value is number =>
          typeof value === "number" && Number.isFinite(value),
      );
      candle.applyOptions({
        autoscaleInfoProvider: (base: () => any) => {
          const info = base();
          return info && levels.length
            ? {
                ...info,
                priceRange: {
                  minValue: Math.min(info.priceRange.minValue, ...levels),
                  maxValue: Math.max(info.priceRange.maxValue, ...levels),
                },
              }
            : info;
        },
      });
      const visible = points.filter(
        (point) => point.time >= Date.parse(box.closed_at) / 1000,
      );
      const zones = [
        { base: box.pdl, value: box.buy_upper, color: "rgba(130,214,173,.12)" },
        {
          base: box.buy_upper,
          value: box.sell_lower,
          color: "rgba(188,196,189,.04)",
        },
        {
          base: box.pdh,
          value: box.sell_lower,
          color: "rgba(239,163,163,.12)",
        },
      ];
      zones.forEach((zone, index) => {
        const area =
          overlaySeries.current[index] ||
          chart.addBaselineSeries({
            baseValue: { type: "price", price: zone.base },
            topFillColor1: zone.color,
            topFillColor2: zone.color,
            bottomFillColor1: zone.color,
            bottomFillColor2: zone.color,
            topLineColor: "transparent",
            bottomLineColor: "transparent",
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
        area.applyOptions({ baseValue: { type: "price", price: zone.base } });
        area.setData(
          visible.map((point) => ({ time: point.time, value: zone.value })),
        );
        overlaySeries.current[index] = area;
      });
      Object.entries(overlay.levels || {}).forEach(([name, value]) => {
        if (typeof value === "number" && Number.isFinite(value))
          levelLines.current.push(
            candle.createPriceLine({
              price: value,
              color:
                name === "stop"
                  ? "#efa3a3"
                  : name === "target"
                    ? "#82d6ad"
                    : "#adbcad",
              lineWidth: 1,
              lineStyle: name === "midpoint" ? 2 : 0,
              axisLabelVisible: true,
              title: name.toUpperCase(),
            }),
          );
      });
    } else {
      overlaySeries.current.forEach((item) => chart.removeSeries(item));
      overlaySeries.current = [];
    }
    if (viewport) chart.timeScale().setVisibleLogicalRange(viewport);
    updating.current = false;
  }, [overlay, points]);
  useEffect(() => {
    series.current.slice(3).forEach((s) => s.applyOptions({ visible: ema }));
  }, [ema, points.length]);
  function drag(
    event: React.PointerEvent<HTMLDivElement>,
    pane: "volume" | "rsi",
  ) {
    event.currentTarget.setPointerCapture(event.pointerId);
    const start = event.clientY,
      initial = pane === "volume" ? volumeHeight : rsiHeight;
    const move = (e: PointerEvent) => {
      const n = Math.max(
        pane === "volume" ? 40 : 75,
        Math.min(height * 0.32, initial + start - e.clientY),
      );
      (pane === "volume" ? setVolumeHeight : setRsiHeight)(n);
      localStorage.setItem(`gx-${pane}-height`, String(n));
    };
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, { once: true });
  }
  const last = points.at(-1);
  return (
    <section className="chart-frame">
      <div className="chart-toolbar">
        <b>{symbol.replace("=F", "")}</b>
        <span>{minutes}m · CT</span>
        <span className="chart-price">{price(last?.close)}</span>
        <label>
          <input
            type="checkbox"
            checked={ema}
            onChange={(e) => setEma(e.target.checked)}
          />
          EMA 20/50
        </label>
        <button
          className="icon"
          title="Zoom out"
          onClick={() => {
            const r = charts.current[0]?.timeScale().getVisibleLogicalRange();
            if (r) {
              const next = {
                from: r.from - 10,
                to: r.to + 10,
              } as LogicalRange;
              applyRange(
                following.current
                  ? latestRange(points.length, next.to - next.from)
                  : next,
              );
            }
          }}
        >
          <ZoomOut size={15} />
        </button>
        <button
          className="icon"
          title="Zoom in"
          onClick={() => {
            const r = charts.current[0]?.timeScale().getVisibleLogicalRange();
            if (r && r.to - r.from > 25) {
              const next = {
                from: r.from + 10,
                to: r.to - 10,
              } as LogicalRange;
              applyRange(
                following.current
                  ? latestRange(points.length, next.to - next.from)
                  : next,
              );
            }
          }}
        >
          <ZoomIn size={15} />
        </button>
        <button
          className="icon"
          title="Fit all history"
          onClick={() => {
            follow(false);
            applyRange({ from: 0, to: points.length + 2 } as LogicalRange);
          }}
        >
          <Maximize2 size={15} />
        </button>
        <button
          className="icon"
          title="Follow latest price"
          aria-pressed={isFollowing}
          onClick={() => {
            const range = charts.current[0]
              ?.timeScale()
              .getVisibleLogicalRange();
            follow(true);
            charts.current.forEach((chart) =>
              chart.priceScale("right").applyOptions({ autoScale: true }),
            );
            applyRange(
              latestRange(points.length, range ? range.to - range.from : 100),
            );
          }}
        >
          <LocateFixed size={15} />
        </button>
      </div>
      {last && (
        <div className="chart-ohlc">
          O {price(last.open)} &nbsp; H {price(last.high)} &nbsp; L{" "}
          {price(last.low)} &nbsp; C {price(last.close)}
        </div>
      )}
      {overlay?.box && (
        <div className="chart-ohlc">
          Previous session {overlay.box.session_id} ·{" "}
          {overlay.box.session_definition} · CT
        </div>
      )}
      {error && <Notice danger>{error}</Notice>}
      <div
        className="chart-main"
        style={{
          height: Math.max(200, height - volumeHeight - rsiHeight - 60),
        }}
      >
        <div ref={priceEl} className="canvas-host" />
        {!points.length && (
          <div className="chart-empty">
            <Empty
              title={loading ? "Loading saved candles" : "No saved price data"}
              detail="Market data is unavailable. No synthetic prices are shown."
            />
          </div>
        )}
      </div>
      <div
        className="pane-separator"
        role="separator"
        aria-label="Resize volume"
        tabIndex={0}
        onPointerDown={(e) => drag(e, "volume")}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp" || e.key === "ArrowDown")
            setVolumeHeight((v) =>
              Math.max(40, Math.min(200, v + (e.key === "ArrowUp" ? 10 : -10))),
            );
        }}
      />
      <div className="chart-indicator">
        <span>Volume</span>
        <div ref={volumeEl} style={{ height: volumeHeight }} />
      </div>
      <div
        className="pane-separator"
        role="separator"
        aria-label="Resize RSI"
        tabIndex={0}
        onPointerDown={(e) => drag(e, "rsi")}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp" || e.key === "ArrowDown")
            setRsiHeight((v) =>
              Math.max(75, Math.min(240, v + (e.key === "ArrowUp" ? 10 : -10))),
            );
        }}
      />
      <div className="chart-indicator">
        <span>RSI 14 {last?.rsi?.toFixed(1) ?? "--"}</span>
        <div ref={rsiEl} style={{ height: rsiHeight }} />
      </div>
      <a
        className="chart-attribution"
        href="https://www.tradingview.com/"
        target="_blank"
        rel="noreferrer"
      >
        Charts by TradingView Lightweight Charts
      </a>
    </section>
  );
});
