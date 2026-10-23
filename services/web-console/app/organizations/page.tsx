import { headers as nextHeaders } from "next/headers";
import { redirect } from "next/navigation";

import { auth } from "../../lib/auth/auth";
import { OrganizationsPanel } from "../../components/org/OrganizationsPanel";

/**
 * Phase 14 Gate 3/9: organization selector, creation, membership,
 * invitations, and role display -- the ONE console screen covering
 * Gate 3's list of required capabilities (create org; org detail;
 * list my orgs; switch active org; invite/accept/reject/revoke
 * invitation; remove member; change member role; leave org). Every
 * mutation this page's client panel performs calls Better Auth's own
 * real server-verified endpoints (via authClient.organization.*) --
 * this server page only reads current state to render it.
 */
export default async function OrganizationsPage() {
  const requestHeaders = await nextHeaders();
  const session = await auth.api.getSession({ headers: requestHeaders });
  if (!session?.user) {
    redirect("/sign-in");
  }

  const organizations = await auth.api.listOrganizations({ headers: requestHeaders });
  const activeOrganizationId = session.session.activeOrganizationId ?? null;

  let members: Array<{ id: string; userId: string; role: string; user?: { email?: string; name?: string } }> = [];
  let invitations: Array<{ id: string; email: string; role: string; status: string; expiresAt: string | Date }> = [];
  let activeRole: string | null = null;

  if (activeOrganizationId) {
    try {
      const membersResult = await auth.api.listMembers({
        headers: requestHeaders,
        query: { organizationId: activeOrganizationId },
      });
      members = (membersResult?.members ?? []) as typeof members;
    } catch {
      members = [];
    }
    try {
      invitations = (await auth.api.listInvitations({
        headers: requestHeaders,
        query: { organizationId: activeOrganizationId },
      })) as typeof invitations;
    } catch {
      invitations = [];
    }
    try {
      const activeMember = await auth.api.getActiveMember({ headers: requestHeaders });
      activeRole = activeMember?.role ?? null;
    } catch {
      activeRole = null;
    }
  }

  let myInvitations: Array<{ id: string; organizationId: string; role: string; status: string }> = [];
  try {
    myInvitations = (await auth.api.listUserInvitations({ headers: requestHeaders })) as typeof myInvitations;
  } catch {
    myInvitations = [];
  }

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <h1>Organizations</h1>
      <OrganizationsPanel
        organizations={organizations ?? []}
        activeOrganizationId={activeOrganizationId}
        activeRole={activeRole}
        members={members}
        invitations={invitations}
        myInvitations={myInvitations}
        currentUserId={session.user.id}
      />
    </main>
  );
}
