import { notFound } from "next/navigation";
import { StrategyWorkspace } from "@/components/dashboard/strategy-workspace";
import { getEngineStrategy } from "@/lib/engine-strategies";

export default function EngineStrategyPage({ params }: { params: { slug: string } }) {
  const strategy = getEngineStrategy(params.slug);
  if (!strategy) {
    notFound();
  }
  return <StrategyWorkspace strategy={strategy} />;
}
