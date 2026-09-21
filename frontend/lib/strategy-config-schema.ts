/** Strategy-specific subscription configuration schemas (backend-supported fields only). */

import { RENKO_ALT_SLUGS, renkoStrategyCode } from "@/lib/renko-assets";

export type ConfigFieldType = "number" | "select" | "text";

export interface StrategyConfigField {
  key: string;
  label: string;
  type: ConfigFieldType;
  description?: string;
  defaultValue?: string | number;
  min?: number;
  max?: number;
  step?: number;
  options?: Array<{ label: string; value: string | number }>;
}

export interface StrategyConfigSchema {
  strategyCode: string;
  fields: StrategyConfigField[];
}

const SCHEMAS: Record<string, StrategyConfigSchema> = {
  short_strangle: {
    strategyCode: "short_strangle",
    fields: [
      {
        key: "quantity",
        label: "Order quantity (contracts)",
        type: "number",
        description: "Number of option contracts per leg. Backend maps to order_quantity / risk_overrides.quantity.",
        defaultValue: 50,
        min: 1,
        step: 1,
      },
      {
        key: "target_premium",
        label: "Target premium (USD)",
        type: "number",
        defaultValue: 100,
        min: 1,
        step: 1,
      },
      {
        key: "premium_tolerance_usd",
        label: "Premium tolerance (USD)",
        type: "number",
        defaultValue: 30,
        min: 0,
        step: 1,
      },
      {
        key: "sl_percentage",
        label: "Stop-loss %",
        type: "number",
        defaultValue: 100,
        min: 1,
        max: 500,
        step: 1,
      },
      {
        key: "allocation_pct",
        label: "Capital allocation %",
        type: "number",
        description: "Percentage of linked account capital allocated to this strategy subscription.",
        defaultValue: 100,
        min: 1,
        max: 100,
        step: 1,
      },
    ],
  },
  renko_ichimoku_eth: {
    strategyCode: "renko_ichimoku_eth",
    fields: [
      {
        key: "position_size",
        label: "Position size (contracts)",
        type: "number",
        defaultValue: 1,
        min: 0,
        step: 1,
      },
      {
        key: "allocation_pct",
        label: "Capital allocation %",
        type: "number",
        defaultValue: 100,
        min: 1,
        max: 100,
        step: 1,
      },
    ],
  },
  renko_ichimoku_sol: {
    strategyCode: "renko_ichimoku_sol",
    fields: [
      {
        key: "position_size",
        label: "Position size (contracts)",
        type: "number",
        defaultValue: 30,
        min: 0,
        step: 1,
      },
      {
        key: "allocation_pct",
        label: "Capital allocation %",
        type: "number",
        defaultValue: 100,
        min: 1,
        max: 100,
        step: 1,
      },
    ],
  },
  renko_ichimoku_xrp: {
    strategyCode: "renko_ichimoku_xrp",
    fields: [
      {
        key: "position_size",
        label: "Position size (contracts)",
        type: "number",
        defaultValue: 100,
        min: 0,
        step: 1,
      },
      {
        key: "allocation_pct",
        label: "Capital allocation %",
        type: "number",
        defaultValue: 100,
        min: 1,
        max: 100,
        step: 1,
      },
    ],
  },
  // legacy alias
  renko_ichimoku: {
    strategyCode: "renko_ichimoku_eth",
    fields: [
      {
        key: "position_size",
        label: "Position size (contracts)",
        type: "number",
        defaultValue: 1,
        min: 0,
        step: 1,
      },
      {
        key: "allocation_pct",
        label: "Capital allocation %",
        type: "number",
        defaultValue: 100,
        min: 1,
        max: 100,
        step: 1,
      },
    ],
  },
};

function renkoSubscriptionSchema(strategyCode: string, defaultContracts = 0): StrategyConfigSchema {
  return {
    strategyCode,
    fields: [
      {
        key: "position_size",
        label: "Position size (contracts)",
        type: "number",
        defaultValue: defaultContracts,
        min: 0,
        step: 1,
      },
      {
        key: "allocation_pct",
        label: "Capital allocation %",
        type: "number",
        defaultValue: 100,
        min: 1,
        max: 100,
        step: 1,
      },
    ],
  };
}

for (const slug of RENKO_ALT_SLUGS) {
  const code = renkoStrategyCode(slug);
  SCHEMAS[code] = renkoSubscriptionSchema(code, 0);
}

export function getStrategyConfigSchema(code: string): StrategyConfigSchema {
  return (
    SCHEMAS[code] ?? {
      strategyCode: code,
      fields: [
        {
          key: "allocation_pct",
          label: "Capital allocation %",
          type: "number",
          defaultValue: 100,
          min: 1,
          max: 100,
          step: 1,
        },
      ],
    }
  );
}

export function buildRiskOverrides(
  code: string,
  values: Record<string, string | number>,
): Record<string, unknown> {
  const schema = getStrategyConfigSchema(code);
  const overrides: Record<string, unknown> = {};
  for (const field of schema.fields) {
    if (field.key === "allocation_pct") continue;
    const raw = values[field.key];
    if (raw === undefined || raw === "") continue;
    overrides[field.key] = field.type === "number" ? Number(raw) : raw;
  }
  return overrides;
}

export function getAllocationPct(values: Record<string, string | number>): number {
  const raw = values.allocation_pct;
  const n = raw === undefined || raw === "" ? 100 : Number(raw);
  return Number.isFinite(n) ? Math.min(100, Math.max(1, n)) : 100;
}
