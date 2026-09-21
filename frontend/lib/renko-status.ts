import type { SystemStatusResponse } from "@/lib/api/schemas";
import { ENGINE_STRATEGIES, type EngineStrategyDef } from "@/lib/engine-strategies";

export function renkoSnapshot(
  status: SystemStatusResponse | null | undefined,
  strategyCode: string,
) {
  const snap = status?.strategies?.[strategyCode];
  if (!snap || typeof snap !== "object" || !("enabled" in snap)) {
    return null;
  }
  return snap;
}

export function isEngineStrategyLive(
  status: SystemStatusResponse | null | undefined,
  strategy: EngineStrategyDef,
): boolean {
  if (strategy.kind === "strangle") {
    return status?.strategies?.existing?.enabled !== false;
  }
  return Boolean(renkoSnapshot(status, strategy.code)?.enabled);
}

export function isRenkoPositionOpen(
  status: SystemStatusResponse | null | undefined,
  strategy: EngineStrategyDef,
): boolean {
  if (strategy.kind !== "renko") return false;
  const snap = renkoSnapshot(status, strategy.code);
  return (snap?.position ?? 0) !== 0;
}

export function liveEngineStrategies(
  status: SystemStatusResponse | null | undefined,
): EngineStrategyDef[] {
  return ENGINE_STRATEGIES.filter((s) => isEngineStrategyLive(status, s));
}

export function openRenkoEngineStrategies(
  status: SystemStatusResponse | null | undefined,
): EngineStrategyDef[] {
  return ENGINE_STRATEGIES.filter(
    (s) => s.kind === "renko" && isRenkoPositionOpen(status, s),
  );
}
