import {
  LayoutDashboard,
  Siren,
  Boxes,
  Plug,
  Activity,
  Users,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Gate 3: an unimplemented feature is shown, disabled, with a
   * reason -- never a link to a fake page. */
  available: boolean;
  unavailableReason?: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [
      { label: "Dashboard", href: "/", icon: LayoutDashboard, available: true },
      { label: "Services", href: "/services", icon: Boxes, available: true },
      { label: "Incidents", href: "/incidents", icon: Siren, available: true },
    ],
  },
  {
    label: "Platform",
    items: [
      { label: "Integrations", href: "/integrations", icon: Plug, available: true },
      { label: "System Health", href: "/system", icon: Activity, available: true },
    ],
  },
  {
    label: "Workspace",
    items: [
      { label: "Team & Organization", href: "/organizations", icon: Users, available: true },
      {
        label: "Settings",
        href: "/settings",
        icon: Settings,
        available: false,
        unavailableReason: "Organization-level settings are not implemented yet.",
      },
    ],
  },
];
