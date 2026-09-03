import { PaperShell } from "@/components/analysis/paper-shell";
import { SignInForm } from "@/components/auth/sign-in-form";

export default function SignInPage() {
  return (
    <PaperShell>
      <main className="mx-auto max-w-md px-6 py-16">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">
          Operator access
        </p>
        <h1 className="mt-3 text-4xl font-semibold">Sign in to Venuz</h1>
        <p className="mt-4 text-slate-600">
          Authentication is handled by Supabase. Credentials are sent only to
          this server boundary and the access token is stored in an HttpOnly
          cookie.
        </p>
        <SignInForm />
      </main>
    </PaperShell>
  );
}
