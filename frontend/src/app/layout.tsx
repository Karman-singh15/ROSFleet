import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { ConnectionPill } from "@/components/ConnectionPill";

export const metadata: Metadata = {
  title: "ROSFleet",
  description: "Fleet management for autonomous mobile robots",
};

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/robots", label: "Robots" },
  { href: "/maps", label: "Maps" },
  { href: "/missions", label: "Missions" },
  { href: "/analytics", label: "Analytics" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-surface text-ink antialiased">
        <header className="border-b border-edge bg-panel">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
            <Link href="/" className="flex items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded bg-busy text-sm font-bold text-surface">
                R
              </span>
              <span className="text-sm font-semibold tracking-widest">
                ROSFLEET
              </span>
            </Link>

            <nav className="flex flex-wrap gap-1 text-sm">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded px-3 py-1.5 text-ink-dim transition hover:bg-panel-2 hover:text-ink"
                >
                  {item.label}
                </Link>
              ))}
            </nav>

            <div className="ml-auto">
              <ConnectionPill />
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
