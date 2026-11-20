/**
 * Loading state: the label (read by screen readers and visible) plus shimmer
 * skeleton cards shaped like the content that is coming, so the page doesn't jump.
 */
export function Loading({ label = "Loading…", count = 3 }: { label?: string; count?: number }) {
  return (
    <div className="loading">
      <p className="status">{label}</p>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton" aria-hidden="true" />
      ))}
    </div>
  );
}
