import { lazy, Suspense, useState } from "react";
import { Download } from "lucide-react";
import { age, price } from "../api";
import { Empty, Field } from "../components";
import { type PageProps, symbols } from "../pageTypes";

const MarketChart = lazy(() =>
  import("../Chart").then((module) => ({ default: module.MarketChart })),
);

export function Charts({ act, live }: PageProps) {
  const [selected, setSelected] = useState<string[]>(() => {
      try {
        return JSON.parse(localStorage.getItem("gx-charts") || '["NQ=F"]');
      } catch {
        return ["NQ=F"];
      }
    }),
    [minutes, setMinutes] = useState(
      () => Number(localStorage.getItem("gx-chart-minutes")) || 1,
    ),
    [hours, setHours] = useState(48),
    [height, setHeight] = useState(
      () => Number(localStorage.getItem("gx-chart-height")) || 700,
    );
  const choose = (symbol: string) => {
    const next = selected.includes(symbol)
      ? selected.filter((v) => v !== symbol)
      : [...selected, symbol].slice(0, 3);
    setSelected(next);
    localStorage.setItem("gx-charts", JSON.stringify(next));
  };
  return (
    <>
      <div className="chart-controls">
        <div className="segmented">
          {symbols.map((s) => (
            <button
              key={s}
              aria-pressed={selected.includes(s)}
              onClick={() => choose(s)}
            >
              {s.replace("=F", "")}
            </button>
          ))}
        </div>
        <Field label="Range">
          <select value={hours} onChange={(e) => setHours(+e.target.value)}>
            <option value={48}>48 hours</option>
            <option value={24}>24 hours</option>
          </select>
        </Field>
        <Field label="Candles">
          <select
            value={minutes}
            onChange={(e) => {
              setMinutes(+e.target.value);
              localStorage.setItem("gx-chart-minutes", e.target.value);
            }}
          >
            {[1, 3, 5, 15, 30, 60].map((n) => (
              <option key={n} value={n}>
                {n === 60 ? "1 hour" : `${n} min`}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Chart height">
          <input
            aria-label="Chart height"
            type="range"
            min="480"
            max="1100"
            step="20"
            value={height}
            onChange={(e) => {
              setHeight(+e.target.value);
              localStorage.setItem("gx-chart-height", e.target.value);
            }}
          />
        </Field>
      </div>
      <div
        className="charts-grid"
        style={{
          gridTemplateColumns: `repeat(${selected.length || 1},minmax(0,1fr))`,
        }}
      >
        {selected.map((s) => (
          <div key={s}>
            <div className="chart-status">
              <span>{s.replace("=F", "")}</span>
              <span>
                {age(live.prices[s]?.event_time) < 15
                  ? "Fresh price"
                  : live.prices[s]
                    ? "Price delayed"
                    : "No current price"}{" "}
                · {price(live.prices[s]?.price)}
              </span>
              <button
                className="icon"
                title={"Retrieve actual " + s + " history"}
                onClick={() =>
                  void act("/history/" + encodeURIComponent(s), {})
                }
              >
                <Download size={15} />
              </button>
            </div>
            <Suspense fallback={<Empty title="Loading chart engine" />}>
              <MarketChart
                symbol={s}
                minutes={minutes}
                hours={hours}
                height={height}
              />
            </Suspense>
          </div>
        ))}
      </div>
      {!selected.length && <Empty title="No charts selected" />}
    </>
  );
}
