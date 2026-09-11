import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";

function getAllowedEmails(): string[] {
  return (process.env.ALLOWED_GOOGLE_EMAILS || "")
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean);
}

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID || "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || "",
    }),
  ],
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt",
    maxAge: 30 * 24 * 60 * 60,
  },
  callbacks: {
    async signIn({ user }) {
      if (process.env.AUTH_DISABLED === "true") {
        return true;
      }

      const allowed = getAllowedEmails();
      if (allowed.length === 0) {
        if (process.env.GOOGLE_CLIENT_ID) {
          console.warn("[Auth] ALLOWED_GOOGLE_EMAILS is empty — denying sign-in");
          return false;
        }
        return true;
      }

      return allowed.includes((user.email || "").toLowerCase());
    },
    async jwt({ token, user }) {
      if (user?.image) {
        token.picture = user.image;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.image = (token.picture as string | undefined) ?? session.user.image;
      }
      return session;
    },
  },
  secret: process.env.NEXTAUTH_SECRET,
};
