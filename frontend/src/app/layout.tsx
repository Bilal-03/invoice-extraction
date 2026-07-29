import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Invoice Intelligence Platform",
  description: "Production-grade Intelligent Document Processing",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background antialiased">
        <div className="relative flex min-h-screen flex-col">
          {/* Glassmorphism Background Decoration */}
          <div className="fixed inset-0 z-[-1] overflow-hidden pointer-events-none">
            <div className="absolute -top-40 -right-40 w-96 h-96 bg-primary/20 rounded-full blur-[100px]" />
            <div className="absolute top-1/2 -left-40 w-96 h-96 bg-blue-500/10 rounded-full blur-[100px]" />
            <div className="absolute -bottom-40 left-1/2 w-96 h-96 bg-purple-500/10 rounded-full blur-[100px]" />
          </div>
          
          {/* Main App Container */}
          <main className="flex-1 max-w-7xl w-full mx-auto p-4 md:p-8">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
