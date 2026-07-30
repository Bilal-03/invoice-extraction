import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Invoice Intelligence", description: "Evidence-led invoice extraction" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
