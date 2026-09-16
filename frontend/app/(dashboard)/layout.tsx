import { AppShell } from "@/components/layout/app-shell";
import { PlatformBootstrap } from "@/components/platform/platform-bootstrap";

export default function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <AppShell>
      <PlatformBootstrap />
      {children}
    </AppShell>
  );
}
