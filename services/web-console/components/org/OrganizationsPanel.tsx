"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, Mail, Users as UsersIcon } from "lucide-react";

import { authClient } from "@/lib/auth/client";
import { PLATFORM_ROLE_NAMES } from "@/lib/auth/access-control";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Input, Label, Select } from "../ui/input";
import { EmptyState } from "../ui/empty-state";

interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
}

interface MemberRow {
  id: string;
  userId: string;
  role: string;
  user?: { email?: string; name?: string };
}

interface InvitationRow {
  id: string;
  email?: string;
  organizationId?: string;
  role: string;
  status: string;
}

export function OrganizationsPanel({
  organizations,
  activeOrganizationId,
  activeRole,
  members,
  invitations,
  myInvitations,
  currentUserId,
}: {
  organizations: OrganizationSummary[];
  activeOrganizationId: string | null;
  activeRole: string | null;
  members: MemberRow[];
  invitations: InvitationRow[];
  myInvitations: InvitationRow[];
  currentUserId: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newOrgName, setNewOrgName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<string>("VIEWER");

  async function run(action: () => Promise<{ error?: unknown } | void>) {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      if (result && "error" in result && result.error) {
        setError((result.error as { message?: string }).message ?? "The action failed.");
      }
    } finally {
      setBusy(false);
      router.refresh();
    }
  }

  // Gate 3: no self-promotion, and OWNER-only for destructive member
  // actions is enforced SERVER-SIDE by Better Auth's own organization
  // plugin regardless of what this UI shows -- the role check below
  // only decides what this UI offers, per Gate 9 ("do not merely hide
  // inaccessible buttons" means backend independently re-checks, not
  // that the UI should offer actions indiscriminately).
  const canManageMembers = activeRole === "OWNER" || activeRole === "ADMIN";
  const pendingMyInvitations = myInvitations.filter((invitation) => invitation.status === "pending");
  const pendingInvitations = invitations.filter((invitation) => invitation.status === "pending");

  return (
    <div className="space-y-6">
      {error && (
        <p role="alert" className="rounded-lg border border-critical-fg/30 bg-critical-soft-bg px-4 py-3 text-sm text-critical-fg">
          {error}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Your organizations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {organizations.length === 0 ? (
            <EmptyState icon={Building2} title="No organizations yet" />
          ) : (
            <ul className="space-y-2">
              {organizations.map((org) => (
                <li
                  key={org.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border p-3"
                >
                  <div className="flex items-center gap-2">
                    <Building2 className="h-4 w-4 text-fg-subtle" aria-hidden="true" />
                    <span className="font-medium text-fg">{org.name}</span>
                    <span className="text-xs text-fg-subtle">({org.slug})</span>
                    {org.id === activeOrganizationId && (
                      <Badge tone="success" dot>
                        Active
                      </Badge>
                    )}
                  </div>
                  {org.id !== activeOrganizationId && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => run(() => authClient.organization.setActive({ organizationId: org.id }))}
                    >
                      Switch
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}

          <form
            onSubmit={(event) => {
              event.preventDefault();
              const slug = newOrgName
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "-")
                .replace(/(^-|-$)/g, "");
              run(() => authClient.organization.create({ name: newOrgName, slug }));
              setNewOrgName("");
            }}
            className="flex items-end gap-2"
          >
            <div className="flex-1">
              <Label htmlFor="new-org-name">New organization</Label>
              <Input
                id="new-org-name"
                required
                placeholder="Acme Platform Team"
                value={newOrgName}
                onChange={(event) => setNewOrgName(event.target.value)}
              />
            </div>
            <Button type="submit" disabled={busy || newOrgName.trim().length === 0}>
              Create
            </Button>
          </form>
        </CardContent>
      </Card>

      {pendingMyInvitations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Invitations addressed to you</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {pendingMyInvitations.map((invitation) => (
                <li
                  key={invitation.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border p-3"
                >
                  <span className="flex items-center gap-2 text-sm text-fg">
                    <Mail className="h-4 w-4 text-fg-subtle" aria-hidden="true" />
                    Role offered: <Badge tone="accent">{invitation.role}</Badge>
                  </span>
                  <span className="flex gap-2">
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => run(() => authClient.organization.acceptInvitation({ invitationId: invitation.id }))}
                    >
                      Accept
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy}
                      onClick={() => run(() => authClient.organization.rejectInvitation({ invitationId: invitation.id }))}
                    >
                      Reject
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {activeOrganizationId && (
        <Card>
          <CardHeader>
            <CardTitle>Members</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="flex items-center gap-1.5 text-sm text-fg-muted">
              <UsersIcon className="h-3.5 w-3.5" aria-hidden="true" />
              Your role in this organization: <Badge tone="neutral">{activeRole ?? "unknown"}</Badge>
            </p>
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-surface-sunken text-left text-xs font-medium uppercase tracking-wide text-fg-subtle">
                    <th className="px-3 py-2">Member</th>
                    <th className="px-3 py-2">Role</th>
                    {canManageMembers && <th className="px-3 py-2">Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {members.map((member) => (
                    <tr key={member.id} className="border-b border-border last:border-0">
                      <td className="px-3 py-2.5 text-fg">{member.user?.email ?? member.userId}</td>
                      <td className="px-3 py-2.5">
                        {canManageMembers && member.userId !== currentUserId ? (
                          <Select
                            defaultValue={member.role}
                            disabled={busy}
                            className="w-32"
                            onChange={(event) =>
                              run(() =>
                                authClient.organization.updateMemberRole({
                                  memberId: member.id,
                                  role: event.target.value,
                                }),
                              )
                            }
                          >
                            {PLATFORM_ROLE_NAMES.map((role) => (
                              <option key={role} value={role}>
                                {role}
                              </option>
                            ))}
                          </Select>
                        ) : (
                          <Badge tone="neutral">{member.role}</Badge>
                        )}
                      </td>
                      {canManageMembers && (
                        <td className="px-3 py-2.5">
                          {member.userId !== currentUserId && (
                            <Button
                              size="sm"
                              variant="destructive"
                              disabled={busy}
                              onClick={() => run(() => authClient.organization.removeMember({ memberIdOrEmail: member.id }))}
                            >
                              Remove
                            </Button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {canManageMembers && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  run(() =>
                    authClient.organization.inviteMember({
                      email: inviteEmail,
                      // The access-control plugin's generic role type is
                      // inferred from `platformRoles` (lib/auth/auth.ts) --
                      // narrowed from this form's own PLATFORM_ROLE_NAMES
                      // union at runtime; the cast here is a type-level
                      // formality, not a loosened runtime check (Better
                      // Auth's own server endpoint independently rejects
                      // any value outside its real configured role set).
                      role: inviteRole as Parameters<typeof authClient.organization.inviteMember>[0]["role"],
                    }),
                  );
                  setInviteEmail("");
                }}
                className="flex items-end gap-2"
              >
                <div className="flex-1">
                  <Label htmlFor="invite-email">Invite by email</Label>
                  <Input
                    id="invite-email"
                    type="email"
                    required
                    placeholder="teammate@example.com"
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                  />
                </div>
                <Select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)} className="w-32">
                  {PLATFORM_ROLE_NAMES.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </Select>
                <Button type="submit" disabled={busy}>
                  Send invite
                </Button>
              </form>
            )}

            {pendingInvitations.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-medium text-fg">Pending invitations</h3>
                <ul className="space-y-1.5">
                  {pendingInvitations.map((invitation) => (
                    <li key={invitation.id} className="flex items-center justify-between text-sm">
                      <span className="text-fg-muted">
                        {invitation.email} — {invitation.role}
                      </span>
                      {canManageMembers && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => run(() => authClient.organization.cancelInvitation({ invitationId: invitation.id }))}
                        >
                          Revoke
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="border-t border-border pt-4">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => run(() => authClient.organization.leave({ organizationId: activeOrganizationId }))}
              >
                Leave this organization
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
