import Link from "next/link";
import { CircleDot, History } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { EmptyState } from "../ui/empty-state";
import { formatTimestamp } from "../../lib/format";
import type { RecentEvent } from "../../lib/types/dashboard";

const EVENT_LABEL: Record<string, string> = {
  created: "New incident",
  observed: "Renewed observation",
  status_transition: "Status changed",
};

export function RecentActivity({ events }: { events: RecentEvent[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent activity</CardTitle>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <EmptyState icon={History} title="No activity yet" description="Durable incident and remediation events will appear here as they happen." />
        ) : (
          <ol className="space-y-3">
            {events.map((event) => (
              <li key={event.id} className="flex gap-3">
                <CircleDot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <Link href={`/incidents/${event.incident_id}`} className="text-sm text-fg hover:underline">
                    <span className="font-medium">{EVENT_LABEL[event.event_type] ?? event.event_type}</span>
                    {event.new_status && (
                      <span className="text-fg-muted">
                        {event.previous_status ? ` ${event.previous_status} → ${event.new_status}` : ` (${event.new_status})`}
                      </span>
                    )}
                    {" — "}
                    <span className="text-fg-muted">{event.incident_title}</span>
                  </Link>
                  <p className="text-xs text-fg-subtle">
                    {formatTimestamp(event.occurred_at)} · by {event.actor_type}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
