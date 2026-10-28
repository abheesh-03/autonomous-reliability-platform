import type { Metadata } from "next";
import "./globals.css";
import { RootShell } from "../components/shell/root-shell";
import { ThemeScript } from "../components/theme/theme-script";
import { ToastProvider } from "../components/ui/toast";
import { TooltipProvider } from "../components/ui/tooltip";

export const metadata: Metadata = {
  title: "Reliability Console",
  description:
    "Operator console for the Autonomous Production Reliability Platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body>
        <TooltipProvider delayDuration={200}>
          <ToastProvider>
            <RootShell>{children}</RootShell>
          </ToastProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
