import { useEffect, useRef } from "react";
import type { Json } from "../api";

export function ReplayChart({
  bars,
  session,
}: {
  bars: Json[];
  session: Json;
}) {
  const element = useRef<HTMLDivElement>(null),
    objects = useRef<any>(null),
    key = useRef("");
  useEffect(() => {
    let stopped = false;
    void import("lightweight-charts").then(({ createChart, ColorType }) => {
      if (stopped || !element.current) return;
      const chart = createChart(element.current, {
        autoSize: true,
        height: 420,
        layout: {
          background: { type: ColorType.Solid, color: "#151716" },
          textColor: "#b5bcb8",
          fontSize: 13,
        },
        grid: {
          vertLines: { color: "#242c28" },
          horzLines: { color: "#242c28" },
        },
        localization: {
          timeFormatter: (value: any) =>
            new Intl.DateTimeFormat("en-US", {
              timeZone: "America/Chicago",
              month: "short",
              day: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            }).format(new Date(Number(value) * 1000)) + " CT",
        },
        timeScale: {
          timeVisible: true,
          tickMarkFormatter: (value: any) =>
            new Intl.DateTimeFormat("en-US", {
              timeZone: "America/Chicago",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            }).format(new Date(Number(value) * 1000)),
        },
        rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0.2 } },
      });
      const candles = chart.addCandlestickSeries({
        upColor: "#72bfa6",
        downColor: "#df8585",
        borderVisible: false,
        wickUpColor: "#72bfa6",
        wickDownColor: "#df8585",
      });
      const volume = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      volume
        .priceScale()
        .applyOptions({ scaleMargins: { top: 0.83, bottom: 0 } });
      const ema20 = chart.addLineSeries({
        color: "#a9bfa0",
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      const ema50 = chart.addLineSeries({
        color: "#d6a87c",
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      const vwap = chart.addLineSeries({
        color: "#94b9da",
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      objects.current = {
        chart,
        candles,
        volume,
        ema20,
        ema50,
        vwap,
        lines: [],
      };
      key.current = "";
      update();
    });
    function update() {
      element.current?.dispatchEvent(new Event("replay-ready"));
    }
    return () => {
      stopped = true;
      objects.current?.chart.remove();
      objects.current = null;
    };
  }, []);
  useEffect(() => {
    const update = () => {
      const o = objects.current;
      if (!o) return;
      const signature =
        session.id +
        "-" +
        session.symbol +
        ":" +
        session.next_index +
        ":" +
        bars.length;
      if (key.current === signature) return;
      const first = !key.current || key.current.split(":")[0] !== session.id;
      const time = (value: string) =>
        Math.floor(Date.parse(value) / 60000) * 60;
      const range = o.chart.timeScale().getVisibleLogicalRange();
      o.candles.setData(bars.map((b) => ({ ...b, time: time(b.time) })));
      o.volume.setData(
        bars.map((b) => ({
          time: time(b.time),
          value: b.volume,
          color: b.close >= b.open ? "#72bfa66b" : "#df85856b",
        })),
      );
      for (const name of ["ema20", "ema50", "vwap"])
        o[name].setData(
          bars
            .filter((b) => Number.isFinite(b[name]))
            .map((b) => ({ time: time(b.time), value: b[name] })),
        );
      const markers: any[] = [];
      for (const trade of session.trades || []) {
        markers.push({
          time: time(trade.entry_time),
          position: trade.direction === "LONG" ? "belowBar" : "aboveBar",
          color: "#a9bfa0",
          shape: trade.direction === "LONG" ? "arrowUp" : "arrowDown",
          text: "Entry",
        });
        markers.push({
          time: time(
            session.ticks
              ? trade.exit_time
              : new Date(Date.parse(trade.exit_time) - 1).toISOString(),
          ),
          position: "aboveBar",
          color: "#d6a87c",
          shape: "circle",
          text: "Exit",
        });
      }
      for (const position of session.positions || [])
        markers.push({
          time: time(position.filled_at),
          position: "belowBar",
          color: "#a9bfa0",
          shape: "arrowUp",
          text: position.exposure.direction,
        });
      const a = bars.length ? time(bars[0].time) : 0,
        b = bars.length ? time(bars.at(-1)!.time) : 0;
      o.candles.setMarkers(
        markers
          .filter((m) => m.time >= a && m.time <= b)
          .sort((x, y) => x.time - y.time),
      );
      for (const line of o.lines) o.candles.removePriceLine(line);
      o.lines = [];
      for (const position of session.positions || [])
        for (const [label, value, color] of [
          ["Stop", position.exposure.stop, "#df8585"],
          [
            "Target",
            position.trade_management?.target ?? position.candidate.target,
            "#a9bfa0",
          ],
        ])
          o.lines.push(
            o.candles.createPriceLine({
              price: value,
              title: label,
              color,
              lineWidth: 1,
              lineStyle: 2,
            }),
          );
      if (session.box)
        for (const name of ["pdh", "pdl", "buy_upper", "sell_lower"])
          o.lines.push(
            o.candles.createPriceLine({
              price: session.box[name],
              title: name,
              color: "#94b9da",
              lineWidth: 1,
              lineStyle: 2,
            }),
          );
      if (first && bars.length) o.chart.timeScale().fitContent();
      else if (range) o.chart.timeScale().setVisibleLogicalRange(range);
      key.current = signature;
    };
    update();
    const el = element.current;
    el?.addEventListener("replay-ready", update);
    return () => el?.removeEventListener("replay-ready", update);
  }, [bars, session]);
  return (
    <div
      className="replay-chart"
      ref={element}
      aria-label="Offline replay candlestick chart"
      role="img"
    />
  );
}
