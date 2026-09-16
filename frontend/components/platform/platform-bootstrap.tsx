"use client";

import { usePlatformEvents, usePlatformUserSync } from "@/hooks/usePlatform";

export function PlatformBootstrap() {
  usePlatformUserSync();
  usePlatformEvents();
  return null;
}
