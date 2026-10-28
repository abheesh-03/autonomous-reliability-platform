import type { ActivityPoint } from "../../lib/types/dashboard";

/**
 * A minimal, dependency-free stacked bar chart -- deliberately plain
 * SVG rather than a charting library, so there is zero risk of a
 * third-party dependency's own React 19/Next 16 compatibility gap
 * (Phase 15 Gate 2: "Verify current dependency and Next.js
 * compatibility"). Every bar's height is a real, already-aggregated
 * count from control-plane's own dashboard summary endpoint -- this
 * component performs no further aggregation, estimation, or
 * fabrication of its own.
 */
export function ActivityChart({ points }: { points: ActivityPoint[] }) {
  const max = Math.max(1, ...points.map((p) => p.critical + p.warning + p.info));
  const width = 100;
  const height = 120;
  const gap = points.length > 0 ? width / points.length : width;
  const barWidth = Math.max(2, gap * 0.6);

  const hasAnyData = points.some((p) => p.critical + p.warning + p.info > 0);

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-32 w-full overflow-visible"
        role="img"
        aria-label={
          hasAnyData
            ? `Incident activity over the last ${points.length} days, by severity`
            : `No incidents recorded in the last ${points.length} days`
        }
      >
        {points.map((point, index) => {
          const total = point.critical + point.warning + point.info;
          const x = index * gap + (gap - barWidth) / 2;
          let yCursor = height;
          const segments: { key: string; value: number; className: string }[] = [
            { key: "critical", value: point.critical, className: "fill-critical-fg" },
            { key: "warning", value: point.warning, className: "fill-warning-fg" },
            { key: "info", value: point.info, className: "fill-info-fg" },
          ];
          return (
            <g key={point.day}>
              {total === 0 ? (
                <rect x={x} y={height - 2} width={barWidth} height={2} rx={1} className="fill-border" />
              ) : (
                segments.map((segment) => {
                  if (segment.value === 0) return null;
                  const segHeight = (segment.value / max) * height;
                  yCursor -= segHeight;
                  return (
                    <rect
                      key={segment.key}
                      x={x}
                      y={yCursor}
                      width={barWidth}
                      height={segHeight}
                      rx={1.5}
                      className={segment.className}
                    />
                  );
                })
              )}
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex items-center justify-between text-[0.6875rem] text-fg-subtle">
        <span>{points[0]?.day}</span>
        <span>{points[points.length - 1]?.day}</span>
      </div>
      <div className="mt-3 flex items-center gap-4 text-xs text-fg-muted">
        <LegendDot className="bg-critical-fg" label="Critical" />
        <LegendDot className="bg-warning-fg" label="Warning" />
        <LegendDot className="bg-info-fg" label="Info" />
      </div>
    </div>
  );
}

function LegendDot({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${className}`} aria-hidden="true" />
      {label}
    </span>
  );
}
