# ADR-001: Use a Monorepo

## Status

Accepted

## Context

The Autonomous Production Reliability Platform is expected to eventually
consist of several logically distinct components: an operations console,
a control plane, an agent runtime, an infrastructure tool gateway, and a
set of demonstration microservices used as a monitored target, likely
spanning multiple languages (TypeScript, Python, Go, and possibly Java).

A decision is needed on how these components' source code will be
organized across repositories before any of them are built, since this
affects tooling, developer workflow, and how easily components can be
worked on together during early, fast-changing phases of the project.

## Decision

All components of this platform — present and future — will live in a
single repository (this one), organized by directory as components are
introduced. A component will only be split into its own repository if a
concrete, demonstrated need for independent versioning, independent
access control, or independent release cadence arises.

Logical separation between components (e.g., control plane vs. agent
runtime vs. infrastructure gateway) is a boundary enforced by code
organization and interfaces, not by repository boundaries. Splitting a
component into its own deployable service, or its own repository, are
independent decisions — a component can be logically and operationally
separated (its own process, its own deployment) while its source still
lives in this monorepo.

## Alternatives Considered

**Polyrepo from the start** (one repository per component): rejected for
this stage. During early, fast-changing phases where interfaces between
components are still being discovered, cross-repository coordination
(versioning, dependency pinning, atomic cross-component changes) adds
overhead without a corresponding benefit, since there is not yet a team or
release process that requires independent repositories.

**Deciding repository structure per-component as each is built**:
rejected as a default because it defers a foundational decision that
affects tooling and directory layout, and risks inconsistent structure
across components introduced at different times.

## Consequences

**Positive:**
- Cross-component changes (e.g., updating an interface between the
  control plane and the agent runtime) can be made and reviewed atomically.
- A single source of truth for repository-wide conventions (this
  document, `.gitignore`, `.editorconfig`, CI configuration once it
  exists) avoids duplication across repositories.
- Lower coordination overhead while the system's component boundaries are
  still being discovered.

**Negative / tradeoffs:**
- As more components and languages are added, the repository will need
  per-language tooling (build, lint, test) to coexist, which adds some
  root-level configuration complexity compared to a single-language repo.
- Independent deployment, access control, or release cadence per
  component — if ever needed — will require a deliberate future decision
  to split part of the repository out, rather than being available by
  default.
- A monorepo does not by itself provide any performance or scalability
  benefit; it is purely an organizational choice made for this project's
  current stage.
