"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { authClient } from "@/lib/auth/client";
import { PLATFORM_ROLE_NAMES } from "@/lib/auth/access-control";

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

  return (
    <div style={{ display: "grid", gap: "2rem" }}>
      {error && (
        <p role="alert" style={{ color: "#f3c9c9" }}>
          {error}
        </p>
      )}

      <section>
        <h2>Your organizations</h2>
        <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.5rem" }}>
          {organizations.length === 0 && <li style={{ color: "#9fb3c8" }}>No organizations yet.</li>}
          {organizations.map((org) => (
            <li
              key={org.id}
              style={{
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "0.75rem 1rem",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span>
                <strong>{org.name}</strong> <span style={{ color: "#6b7f93" }}>({org.slug})</span>
                {org.id === activeOrganizationId && <span style={{ marginLeft: "0.5rem" }}>— active</span>}
              </span>
              {org.id !== activeOrganizationId && (
                <button
                  disabled={busy}
                  onClick={() => run(() => authClient.organization.setActive({ organizationId: org.id }))}
                >
                  Switch to this organization
                </button>
              )}
            </li>
          ))}
        </ul>

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
          style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}
        >
          <input
            type="text"
            required
            placeholder="New organization name"
            value={newOrgName}
            onChange={(event) => setNewOrgName(event.target.value)}
          />
          <button type="submit" disabled={busy || newOrgName.trim().length === 0}>
            Create organization
          </button>
        </form>
      </section>

      {myInvitations.length > 0 && (
        <section>
          <h2>Invitations addressed to you</h2>
          <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.5rem" }}>
            {myInvitations
              .filter((invitation) => invitation.status === "pending")
              .map((invitation) => (
                <li
                  key={invitation.id}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    padding: "0.75rem 1rem",
                    display: "flex",
                    justifyContent: "space-between",
                  }}
                >
                  <span>Role offered: {invitation.role}</span>
                  <span style={{ display: "flex", gap: "0.5rem" }}>
                    <button
                      disabled={busy}
                      onClick={() => run(() => authClient.organization.acceptInvitation({ invitationId: invitation.id }))}
                    >
                      Accept
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => run(() => authClient.organization.rejectInvitation({ invitationId: invitation.id }))}
                    >
                      Reject
                    </button>
                  </span>
                </li>
              ))}
          </ul>
        </section>
      )}

      {activeOrganizationId && (
        <section>
          <h2>Members</h2>
          <p style={{ color: "#9fb3c8" }}>Your role in this organization: {activeRole ?? "unknown"}</p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
                <th>Member</th>
                <th>Role</th>
                {canManageMembers && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {members.map((member) => (
                <tr key={member.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td>{member.user?.email ?? member.userId}</td>
                  <td>
                    {canManageMembers && member.userId !== currentUserId ? (
                      <select
                        defaultValue={member.role}
                        disabled={busy}
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
                      </select>
                    ) : (
                      member.role
                    )}
                  </td>
                  {canManageMembers && (
                    <td>
                      {member.userId !== currentUserId && (
                        <button
                          disabled={busy}
                          onClick={() => run(() => authClient.organization.removeMember({ memberIdOrEmail: member.id }))}
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>

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
              style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}
            >
              <input
                type="email"
                required
                placeholder="Invite by email"
                value={inviteEmail}
                onChange={(event) => setInviteEmail(event.target.value)}
              />
              <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}>
                {PLATFORM_ROLE_NAMES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
              <button type="submit" disabled={busy}>
                Send invitation
              </button>
            </form>
          )}

          {invitations.filter((i) => i.status === "pending").length > 0 && (
            <div style={{ marginTop: "1rem" }}>
              <h3>Pending invitations</h3>
              <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.4rem" }}>
                {invitations
                  .filter((invitation) => invitation.status === "pending")
                  .map((invitation) => (
                    <li key={invitation.id} style={{ display: "flex", justifyContent: "space-between" }}>
                      <span>
                        {invitation.email} — {invitation.role}
                      </span>
                      {canManageMembers && (
                        <button
                          disabled={busy}
                          onClick={() => run(() => authClient.organization.cancelInvitation({ invitationId: invitation.id }))}
                        >
                          Revoke
                        </button>
                      )}
                    </li>
                  ))}
              </ul>
            </div>
          )}

          <div style={{ marginTop: "1.5rem" }}>
            <button disabled={busy} onClick={() => run(() => authClient.organization.leave({ organizationId: activeOrganizationId }))}>
              Leave this organization
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
