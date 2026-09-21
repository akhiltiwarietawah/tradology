export type EngineStrategySlug = "eth" | "sol" | "xrp" | "strangle";

export type EngineStrategyKind = "renko" | "strangle";

export type RenkoSnapshotKey =
  | "renko_ichimoku_eth"
  | "renko_ichimoku_sol"
  | "renko_ichimoku_xrp";

export interface EngineStrategyDef {
  slug: EngineStrategySlug;
  label: string;
  shortLabel: string;
  code: string;
  kind: EngineStrategyKind;
  snapshotKey?: RenkoSnapshotKey;
}

export const ENGINE_STRATEGIES: EngineStrategyDef[] = [
  {
    slug: "eth",
    label: "Renko ETH",
    shortLabel: "ETH",
    code: "renko_ichimoku_eth",
    kind: "renko",
    snapshotKey: "renko_ichimoku_eth",
  },
  {
    slug: "sol",
    label: "Renko SOL",
    shortLabel: "SOL",
    code: "renko_ichimoku_sol",
    kind: "renko",
    snapshotKey: "renko_ichimoku_sol",
  },
  {
    slug: "xrp",
    label: "Renko XRP",
    shortLabel: "XRP",
    code: "renko_ichimoku_xrp",
    kind: "renko",
    snapshotKey: "renko_ichimoku_xrp",
  },
  {
    slug: "strangle",
    label: "BTC Strangle",
    shortLabel: "Strangle",
    code: "short_strangle",
    kind: "strangle",
  },
];

export function getEngineStrategy(slug: string | undefined): EngineStrategyDef | undefined {
  return ENGINE_STRATEGIES.find((s) => s.slug === slug);
}
