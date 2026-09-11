import { Header } from "@/components/layout/header";

export default function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <>
      <Header />
      <main className="flex-1 w-full max-w-[1400px] mx-auto p-4 sm:p-6 lg:p-8">
        {children}
      </main>
    </>
  );
}
