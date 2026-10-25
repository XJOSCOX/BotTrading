export function Tabs({
  values,
  selected,
  onChange,
}: {
  values: string[];
  selected: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {values.map((name) => (
        <button
          type="button"
          key={name}
          role="tab"
          aria-selected={selected === name}
          onClick={() => onChange(name)}
        >
          {name}
        </button>
      ))}
    </div>
  );
}
