import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize2, RotateCcw, Orbit, Pause } from "lucide-react";
import { ct, money } from "../api";

type Trade = { net: number; symbol: string; strategy: string; closed: string };

export function EquityScene({
  history,
  fallback,
}: {
  history: string;
  fallback: ReactNode;
}) {
  const host = useRef<HTMLDivElement>(null);
  const reset = useRef<() => void>(() => {});
  const spin = useRef<(value: boolean) => void>(() => {});
  const [rotating, setRotating] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const trades: Trade[] = JSON.parse(history);
  const values = [0];
  trades.forEach((t) => values.push(values[values.length - 1] + t.net));
  const low = Math.min(0, ...values),
    high = Math.max(0, ...values);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let disposed = false,
      cleanup = () => {};
    setReady(false);
    setFailed(false);
    setSelected(null);
    setRotating(false);
    void (async () => {
      const T = await import("three");
      const { OrbitControls } =
        await import("three/addons/controls/OrbitControls.js");
      if (disposed) return;
      const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(devicePixelRatio, 1.7));
      renderer.setClearColor(0x151716, 0);
      renderer.outputColorSpace = T.SRGBColorSpace;
      const canvas = renderer.domElement;
      canvas.setAttribute("aria-label", "Interactive 3D realized equity chart");
      canvas.setAttribute("role", "img");
      canvas.tabIndex = 0;
      element.appendChild(canvas);
      const scene = new T.Scene();
      const camera = new T.PerspectiveCamera(36, 1, 0.1, 100);
      const controls = new OrbitControls(camera, canvas);
      controls.enablePan = false;
      controls.enableDamping = true;
      controls.enableZoom = false;
      controls.minPolarAngle = 0.55;
      controls.maxPolarAngle = 1.45;
      controls.minAzimuthAngle = -0.65;
      controls.maxAzimuthAngle = 0.65;
      controls.autoRotateSpeed = 0.6;
      controls.target.set(0, 1.2, 0);
      const home = () => {
        camera.position.set(8, 7.7, 14);
        controls.target.set(0, 1.2, 0);
        controls.update();
      };
      reset.current = home;
      spin.current = (value) => {
        controls.autoRotate = value;
      };
      scene.add(new T.HemisphereLight(0xe3f4ed, 0x293333, 2.3));
      const light = new T.DirectionalLight(0xffffff, 3);
      light.position.set(2, 8, 5);
      scene.add(light);
      const rim = new T.DirectionalLight(0x82d6ad, 2);
      rim.position.set(-6, 3, -4);
      scene.add(rim);
      const grid = new T.GridHelper(12, 12, 0x52635b, 0x2a3430);
      grid.position.y = -0.02;
      scene.add(grid);
      const baseline = new T.Line(
        new T.BufferGeometry().setFromPoints([
          new T.Vector3(-6, 0, 0.5),
          new T.Vector3(6, 0, 0.5),
        ]),
        new T.LineBasicMaterial({ color: 0x77897f }),
      );
      scene.add(baseline);
      const data: Trade[] = JSON.parse(history);
      const cumulative = [0];
      data.forEach((t) =>
        cumulative.push(cumulative[cumulative.length - 1] + t.net),
      );
      const scale = 4 / Math.max(1, ...cumulative.map(Math.abs));
      const centerY =
        ((Math.min(...cumulative) + Math.max(...cumulative)) * scale) / 2;
      // Aggregate only the geometry for large histories; the journal and totals retain every trade.
      const stride = Math.max(1, Math.ceil(data.length / 160));
      const indices = data
        .map((_, i) => i)
        .filter((i) => i % stride === 0 || i === data.length - 1);
      const bars: InstanceType<typeof T.Mesh>[] = [];
      const path = [new T.Vector3(-5.5, 0.04, 0.15)];
      indices.forEach((index, i) => {
        const value = cumulative[index + 1] * scale;
        const x = -5.5 + ((index + 1) / data.length) * 11;
        const height = Math.max(0.025, Math.abs(value));
        const material = new T.MeshStandardMaterial({
          color: data[index].net < 0 ? 0xd38b83 : 0x8bcbb1,
          metalness: 0.35,
          roughness: 0.28,
          transparent: true,
          opacity: 0.88,
        });
        const bar = new T.Mesh(
          new T.BoxGeometry(Math.min(0.48, 8 / indices.length), height, 0.8),
          material,
        );
        bar.position.set(x, value / 2, 0);
        bar.userData.index = index;
        bars.push(bar);
        scene.add(bar);
        path.push(new T.Vector3(x, value + 0.045, 0.15));
      });
      if (data.length) {
        scene.add(
          new T.Line(
            new T.BufferGeometry().setFromPoints(path),
            new T.LineBasicMaterial({ color: 0xe1f4e9 }),
          ),
        );
        const last = path[path.length - 1];
        const marker = new T.Mesh(
          new T.OctahedronGeometry(0.12),
          new T.MeshStandardMaterial({ color: 0xe1f4e9, emissive: 0x355d4c }),
        );
        marker.position.copy(last);
        scene.add(marker);
      }
      const ray = new T.Raycaster(),
        pointer = new T.Vector2();
      const pick = (event: PointerEvent) => {
        const rect = canvas.getBoundingClientRect();
        pointer.set(
          ((event.clientX - rect.left) / rect.width) * 2 - 1,
          (-(event.clientY - rect.top) / rect.height) * 2 + 1,
        );
        ray.setFromCamera(pointer, camera);
        const hit = ray.intersectObjects(bars)[0];
        setSelected(hit ? hit.object.userData.index : null);
        canvas.style.cursor = hit ? "pointer" : "grab";
      };
      const key = (e: KeyboardEvent) => {
        if (e.key === "Home") {
          e.preventDefault();
          home();
        }
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          setSelected((previous) =>
            Math.max(
              0,
              Math.min(
                data.length - 1,
                (previous ?? -1) + (e.key === "ArrowRight" ? 1 : -1),
              ),
            ),
          );
        }
      };
      const lost = (event: Event) => {
        event.preventDefault();
        cleanup();
        setFailed(true);
      };
      canvas.addEventListener("pointermove", pick);
      canvas.addEventListener("keydown", key);
      canvas.addEventListener("webglcontextlost", lost);
      let frame = 0,
        lastTime = 0,
        dirty = true;
      const resize = () => {
        const width = element.clientWidth,
          height = element.clientHeight;
        renderer.setSize(width, height);
        camera.aspect = width / Math.max(1, height);
        controls.target.set(0, centerY, 0);
        camera.position.set(0, centerY + 7.7, Math.max(13, 18 / camera.aspect));
        camera.updateProjectionMatrix();
        controls.update();
        dirty = true;
      };
      const observer = new ResizeObserver(resize);
      observer.observe(element);
      resize();
      reset.current = () => {
        resize();
      };
      const invalidate = () => {
        dirty = true;
      };
      controls.addEventListener("change", invalidate);
      const animate = (time: number) => {
        frame = requestAnimationFrame(animate);
        if (document.hidden || time - lastTime < 32) return;
        lastTime = time;
        controls.update();
        if (!dirty) return;
        dirty = false;
        renderer.render(scene, camera);
        canvas.dataset.frames = String(Number(canvas.dataset.frames || 0) + 1);
      };
      frame = requestAnimationFrame(animate);
      setReady(true);
      cleanup = () => {
        cancelAnimationFrame(frame);
        observer.disconnect();
        controls.removeEventListener("change", invalidate);
        controls.dispose();
        canvas.removeEventListener("pointermove", pick);
        canvas.removeEventListener("keydown", key);
        canvas.removeEventListener("webglcontextlost", lost);
        scene.traverse((object) => {
          const mesh = object as InstanceType<typeof T.Mesh>;
          mesh.geometry?.dispose();
          const materials = mesh.material
            ? Array.isArray(mesh.material)
              ? mesh.material
              : [mesh.material]
            : [];
          materials.forEach((m) => m.dispose());
        });
        renderer.dispose();
        canvas.remove();
      };
    })().catch(() => {
      if (!disposed) setFailed(true);
    });
    return () => {
      disposed = true;
      cleanup();
      reset.current = () => {};
      spin.current = () => {};
    };
  }, [history]);

  const active = selected != null && selected >= 0 ? trades[selected] : null;
  return (
    <div className={"equity-stage " + (expanded ? "expanded" : "")}>
      <div className="equity-toolbar">
        <div className="equity-domain">
          <span>
            HIGH <b>{money(high)}</b>
          </span>
          <span>
            LOW <b>{money(low)}</b>
          </span>
        </div>
        <div className="equity-tools">
          <button
            className="icon"
            title={rotating ? "Pause rotation" : "Rotate chart"}
            aria-pressed={rotating}
            disabled={!ready || failed}
            onClick={() => {
              spin.current(!rotating);
              setRotating(!rotating);
            }}
          >
            {rotating ? <Pause size={16} /> : <Orbit size={16} />}
          </button>
          <button
            className="icon"
            title="Reset chart view"
            disabled={!ready || failed}
            onClick={() => reset.current()}
          >
            <RotateCcw size={16} />
          </button>
          <button
            className="icon"
            title={expanded ? "Reduce chart height" : "Expand chart height"}
            aria-pressed={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            <Maximize2 size={16} />
          </button>
        </div>
      </div>
      {!failed && (
        <div className="equity-canvas" ref={host} data-ready={ready} />
      )}
      {failed && (
        <div className="equity-fallback">
          <span>3D unavailable / standard equity view</span>
          {fallback}
        </div>
      )}
      {!failed && !ready && (
        <div className="equity-message" role="status">
          Loading equity view
        </div>
      )}
      {!failed && ready && !trades.length && (
        <div className="equity-message">
          <strong>No realized equity curve yet</strong>
          <span>Awaiting matched broker exits</span>
        </div>
      )}
      <div className="equity-caption" aria-live="polite">
        {active ? (
          <>
            <b>
              {active.symbol} / {active.strategy}
            </b>
            <span>{ct(active.closed)}</span>
            <strong className={active.net < 0 ? "negative" : "positive"}>
              {money(active.net)}
            </strong>
          </>
        ) : (
          <>
            <span className="equity-key">
              <i /> Equity after costs
            </span>
            <span>{trades.length} closed trades</span>
            <b>{money(values[values.length - 1])}</b>
          </>
        )}
      </div>
      {trades.length > 0 && (
        <input
          className="equity-scrub"
          aria-label="Inspect closed trade"
          type="range"
          min="0"
          max={trades.length - 1}
          value={selected ?? trades.length - 1}
          onChange={(e) => setSelected(Number(e.target.value))}
        />
      )}
    </div>
  );
}
