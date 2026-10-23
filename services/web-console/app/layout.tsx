import type { Metadata } from "next";
import "./globals.css";
import { AccountMenu } from "../components/AccountMenu";

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
    <html lang="en">
      <body>
        <AccountMenu />
        {children}
      </body>
    </html>
  );
}
