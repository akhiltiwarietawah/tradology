"use client";

import { ResponsiveContainer, AreaChart, Area } from "recharts";

interface PnlSparklineProps {
  values: number[];
  className?: string;
}

export function PnlSparkline({ values, className }: PnlSparklineProps) {
  if (!values.length) {
    return <div className={className} />;
  }
  const up = values[values.length - 1] >= (values[0] ?? 0);
  const stroke = up ? "#34d399" : "#fb7185";
  const data = values.map((v, i) => ({ i, v }));
  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
          <Area type="monotone" dataKey="v" stroke={stroke} strokeWidth={1.5} fill={stroke} fillOpacity={0.12} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
