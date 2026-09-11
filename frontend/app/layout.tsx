import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { QueryProvider } from "@/components/providers/query-provider";
import { SessionProviderWrapper } from "@/components/providers/session-provider";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Tradology | Quant Trading Dashboard",
  description:
    "Production quantitative trading dashboard for Delta Exchange India — BTC strangle, Renko Ichimoku, and live risk monitoring",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} ${mono.variable} font-sans bg-background text-foreground min-h-screen flex flex-col antialiased`}
      >
        <SessionProviderWrapper>
          <QueryProvider>{children}</QueryProvider>
        </SessionProviderWrapper>
      </body>
    </html>
  );
}
