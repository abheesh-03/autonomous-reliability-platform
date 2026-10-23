/**
 * Phase 14, Gate 3: the custom role/permission matrix for this
 * platform, built from Better Auth's real `createAccessControl`/
 * `role` primitives (`better-auth/plugins/access`) -- verified
 * directly against the installed package's own type definitions
 * (node_modules/better-auth/dist/plugins/access/index.d.mts,
 * node_modules/better-auth/dist/plugins/organization/access/statement.d.mts)
 * rather than guessed.
 *
 * This is ONE of two independent authorization mechanisms in this
 * platform, and the two serve different jobs:
 *
 *   - This module governs ORGANIZATION-MANAGEMENT actions (inviting/
 *     removing members, changing roles, organization settings) --
 *     the exact surface Better Auth's organization plugin itself
 *     exposes and enforces server-side (see auth.ts's `organization({
 *     ac, roles, ... })`).
 *   - The actual reliability-platform domain actions (reading an
 *     incident, approving remediation, starting/resuming an
 *     investigation) are NOT governed here at all -- they are
 *     enforced independently by control-plane/agent-runtime-service
 *     (see services/control-plane/src/control_plane/core/authz.py's
 *     ROLES_THAT_MAY_DECIDE_REMEDIATION and
 *     agent_runtime_service/authz.py's ROLES_THAT_MAY_RUN_INVESTIGATIONS),
 *     from the SAME `role` string this module assigns a member, but
 *     via a completely separate, server-side-verified code path (the
 *     signed service assertion, lib/server/actor.ts) -- Gate 3's own
 *     instruction not to let one authorization mechanism silently
 *     stand in for the other.
 *
 * The five roles below are exactly Gate 3's list: OWNER, ADMIN,
 * ENGINEER, VIEWER, INCIDENT_APPROVER. None of them is granted
 * `ac: ["create","update","delete"]` (the ability to redefine this
 * access-control policy itself) except OWNER -- mirroring Better
 * Auth's own default `ownerAc`.
 */

import { createAccessControl } from "better-auth/plugins/access";
import { defaultStatements } from "better-auth/plugins/organization/access";

// Extends Better Auth's own default organization statements
// (organization/member/invitation/team/ac) with two platform-specific
// resources, used ONLY to drive this console's own UI permission
// display (Gate 9: "UI should show disabled/unavailable operations
// for lacking permission") -- never trusted as the actual enforcement
// point for either resource; see the module docstring above.
const statement = {
  ...defaultStatements,
  incident: ["read"],
  remediation: ["approve"],
} as const;

export const accessControl = createAccessControl(statement);

export const ownerRole = accessControl.newRole({
  organization: ["update", "delete"],
  member: ["create", "update", "delete"],
  invitation: ["create", "cancel"],
  team: ["create", "update", "delete"],
  ac: ["create", "read", "update", "delete"],
  incident: ["read"],
  remediation: ["approve"],
});

export const adminRole = accessControl.newRole({
  // Gate 3: ADMIN manages members/settings but does NOT implicitly
  // bypass remediation-approval policy -- no "remediation" grant here.
  organization: ["update"],
  member: ["create", "update", "delete"],
  invitation: ["create", "cancel"],
  team: ["create", "update", "delete"],
  ac: ["read"],
  incident: ["read"],
});

export const engineerRole = accessControl.newRole({
  organization: [],
  member: [],
  invitation: [],
  team: [],
  ac: ["read"],
  incident: ["read"],
});

export const viewerRole = accessControl.newRole({
  organization: [],
  member: [],
  invitation: [],
  team: [],
  ac: ["read"],
  incident: ["read"],
});

export const incidentApproverRole = accessControl.newRole({
  organization: [],
  member: [],
  invitation: [],
  team: [],
  ac: ["read"],
  incident: ["read"],
  remediation: ["approve"],
});

export const platformRoles = {
  OWNER: ownerRole,
  ADMIN: adminRole,
  ENGINEER: engineerRole,
  VIEWER: viewerRole,
  INCIDENT_APPROVER: incidentApproverRole,
} as const;

export type PlatformRole = keyof typeof platformRoles;

export const PLATFORM_ROLE_NAMES: readonly PlatformRole[] = [
  "OWNER",
  "ADMIN",
  "ENGINEER",
  "VIEWER",
  "INCIDENT_APPROVER",
];
