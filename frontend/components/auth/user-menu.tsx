"use client";

import { signOut, useSession } from "next-auth/react";
import { LogOut, User } from "lucide-react";
import { Button } from "@/components/ui/button";

export function UserMenu() {
  const { data: session } = useSession();
  const user = session?.user;

  if (!user) {
    return null;
  }

  return (
    <div className="flex items-center gap-2 pl-3 border-l border-border/60">
      <div className="hidden md:flex flex-col items-end leading-tight">
        <span className="text-xs font-medium text-foreground truncate max-w-[160px]">
          {user.name || "Trader"}
        </span>
        <span className="text-[10px] text-muted-foreground truncate max-w-[160px]">
          {user.email}
        </span>
      </div>

      {user.image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={user.image}
          alt={user.name || "User"}
          className="h-8 w-8 rounded-full border border-border/80"
        />
      ) : (
        <div className="h-8 w-8 rounded-full bg-secondary flex items-center justify-center">
          <User className="h-4 w-4 text-muted-foreground" />
        </div>
      )}

      <Button
        variant="outline"
        size="sm"
        onClick={() => signOut({ callbackUrl: "/login" })}
        className="h-8 px-2.5 text-[11px] border-border/60"
      >
        <LogOut className="h-3.5 w-3.5 mr-1" />
        Sign out
      </Button>
    </div>
  );
}
