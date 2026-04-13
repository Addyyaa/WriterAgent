import type { Metadata } from "next";
import { IBM_Plex_Serif, Space_Grotesk } from "next/font/google";
import type { ReactNode } from "react";

import { Providers } from "@/app/providers";

import "./globals.css";

const displayFont = Space_Grotesk({ subsets: ["latin"], variable: "--font-display" });
const bodyFont = IBM_Plex_Serif({ subsets: ["latin"], variable: "--font-body", weight: ["400", "500", "600"] });

export const metadata: Metadata = {
  title: "WriterAgent Console",
  description: "Project workspace and professional ops console for WriterAgent"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${displayFont.variable} ${bodyFont.variable}`}>
      <body className="font-[var(--font-body)] text-graphite antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
