import type { Schemas } from "@dotrix/api-client";
import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@dotrix/ui/components/dialog";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRoundIcon, MailIcon } from "lucide-react";
import { usePathname, useSearchParams } from "@/lib/navigation";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { useConfirm } from "@/components/confirm-dialog";
import { Field, SaveBar, SubmitButton } from "@/components/form";
import { GitHubMark } from "@/components/github-sign-in";
import { SettingsContent, SettingsDescription, SettingsHeader, SettingsSection, SettingsTitle } from "@/components/settings-section";
import { UserAvatar } from "@/components/user-avatar";
import { api, errorMessage, unwrap } from "@/lib/api";
import { myAvatarSrc, useRemoveAvatar, useSetAvatar, useSignInMethods, useUnlink, useUpdateProfile } from "@/lib/profile";
import { useMe } from "@/lib/queries";
import { useSetSearchParams } from "@/lib/url-state";

type Me = Schemas["UserRead"];

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

/** Photo, name, and what you do: how your team sees you. */
function AboutYou({ me }: { me: Me }) {
  const update = useUpdateProfile();
  const setAvatar = useSetAvatar();
  const removeAvatar = useRemoveAvatar();
  const picker = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(me.display_name);
  const [title, setTitle] = useState(me.title ?? "");
  const dirty = name.trim() !== me.display_name || title.trim() !== (me.title ?? "");

  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>Profile</SettingsTitle>
        <SettingsDescription>How your team sees you: next to your issues, comments, and in Members.</SettingsDescription>
      </SettingsHeader>
      <SettingsContent>
        <form
          className="grid gap-5"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            update.mutate({ display_name: name.trim(), title: title.trim() });
          }}
        >
          <div className="flex items-center gap-4">
            <UserAvatar name={me.display_name} src={myAvatarSrc(me)} className="size-16 text-base" />
            <div className="grid gap-2">
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="outline" disabled={setAvatar.isPending} onClick={() => picker.current?.click()}>
                  {me.avatar_updated_at ? "Change photo" : "Upload photo"}
                </Button>
                {me.avatar_updated_at && (
                  <Button type="button" size="sm" variant="ghost" disabled={removeAvatar.isPending} onClick={() => removeAvatar.mutate()}>
                    Remove
                  </Button>
                )}
              </div>
              <p className="text-muted-foreground text-xs">PNG, JPEG, or WebP. We crop it to a square.</p>
              <input
                ref={picker}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="sr-only"
                aria-label="Profile photo"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) setAvatar.mutate(file);
                  e.target.value = "";
                }}
              />
            </div>
          </div>
          <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} />
          <Field
            label="What you do"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={100}
            placeholder="e.g. Product designer"
            hint="Shown next to your name."
          />
          <SaveBar
            dirty={dirty}
            pending={update.isPending}
            onDiscard={() => {
              setName(me.display_name);
              setTitle(me.title ?? "");
            }}
          />
        </form>
      </SettingsContent>
    </SettingsSection>
  );
}

function Email({ me }: { me: Me }) {
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/verify-email/resend")),
    onSuccess: () => toast.success("Verification email sent"),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>Email</SettingsTitle>
        <SettingsDescription>Where invites, sign-in links, and notifications go.</SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{me.email}</span>
        {me.email_verified ? (
          <Badge variant="secondary">Verified</Badge>
        ) : (
          <>
            <Badge variant="outline" className="border-warning text-warning-foreground">
              Not verified
            </Badge>
            <Button size="sm" variant="link" className="h-auto p-0" disabled={resend.isPending} onClick={() => resend.mutate()}>
              Resend link
            </Button>
          </>
        )}
      </SettingsContent>
    </SettingsSection>
  );
}

function Method({ icon, title, detail, action }: { icon: ReactNode; title: string; detail: ReactNode; action?: ReactNode }) {
  return (
    <li className="flex flex-wrap items-center gap-3 p-3 text-sm">
      <span className="bg-muted text-muted-foreground flex size-8 items-center justify-center rounded-md [&_svg]:size-4">{icon}</span>
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="font-medium">{title}</span>
        <span className="text-muted-foreground text-xs">{detail}</span>
      </span>
      {action}
    </li>
  );
}

/** Change your password (or set a first one) without leaving Settings; signs out your other sessions. */
function PasswordDialog({ me, hasPassword, open, onOpenChange }: { me: Me; hasPassword: boolean; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [mismatch, setMismatch] = useState(false);
  const change = useMutation({
    mutationFn: (body: Schemas["PasswordChange"]) => unwrap(api.PUT("/v1/me/password", { body })),
    onSuccess: ({ signed_out }) => {
      toast.success(
        `${hasPassword ? "Password changed" : "Password set"}${
          signed_out ? `; signed out ${signed_out} other ${signed_out === 1 ? "session" : "sessions"}` : ""
        }`,
      );
      onOpenChange(false);
      void queryClient.invalidateQueries({ queryKey: ["sign-in-methods"] });
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  const emailLink = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/password-reset/request", { body: { email: me.email } })),
    onSuccess: () => toast.success(`Check ${me.email} for the link`),
    onError: (e) => toast.error(errorMessage(e)),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = String(form.get("new") ?? "");
    if (next !== form.get("confirm")) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    change.mutate({ current_password: hasPassword ? String(form.get("current") ?? "") : null, new_password: next });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) change.reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{hasPassword ? "Change your password" : "Set a password"}</DialogTitle>
          <DialogDescription>Your other browsers and apps are signed out; this one stays signed in. The CLI&apos;s tokens keep working.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          {hasPassword && (
            <Field
              label="Current password"
              name="current"
              type="password"
              autoComplete="current-password"
              required
              action={
                <button type="button" className="text-primary text-xs hover:underline" disabled={emailLink.isPending} onClick={() => emailLink.mutate()}>
                  Forgot it? Email me a link
                </button>
              }
            />
          )}
          <Field
            label="New password"
            name="new"
            type="password"
            autoComplete="new-password"
            minLength={10}
            maxLength={128}
            required
            hint="At least 10 characters"
          />
          <Field label="Confirm new password" name="confirm" type="password" autoComplete="new-password" required />
          {(mismatch || change.isError) && (
            <p role="alert" className="text-destructive text-sm">
              {mismatch ? "The new passwords don't match." : errorMessage(change.error)}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={change.isPending}>{hasPassword ? "Change password" : "Set password"}</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Password, email link, and GitHub: how you can get in; change the password, link or unlink GitHub. */
function SignInMethods({ me }: { me: Me }) {
  const methods = useSignInMethods();
  const providers = useQuery({ queryKey: ["auth-providers"], queryFn: () => unwrap(api.GET("/v1/auth/providers")) });
  const unlink = useUnlink();
  const [ask, confirmDialog] = useConfirm();
  const [changing, setChanging] = useState(false);
  const github = methods.data?.accounts.find((a) => a.provider === "github");

  // Back from GitHub after linking: say how it went, once.
  const pathname = usePathname();
  const params = useSearchParams();
  const setParams = useSetSearchParams();
  const queryClient = useQueryClient();
  const linked = params.get("github");
  const linkError = params.get("github_error");
  useEffect(() => {
    if (linked === "linked") toast.success("GitHub linked: you can sign in with it now");
    if (linkError) toast.error(linkError);
    if (linked || linkError) {
      void queryClient.invalidateQueries({ queryKey: ["sign-in-methods"] });
      setParams({ github: null, github_error: null });
    }
  }, [linked, linkError, queryClient, setParams]);
  const linkHref = `/api/auth/github?link=1&next=${encodeURIComponent(pathname)}`;

  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>Sign-in methods</SettingsTitle>
        <SettingsDescription>Keep at least two, so losing one doesn&apos;t lock you out.</SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="p-0">
        {!methods.data ? (
          <Skeleton className="m-5 h-24" />
        ) : (
          <ul className="divide-y" aria-label="Sign-in methods">
            <Method
              icon={<KeyRoundIcon />}
              title="Password"
              detail={methods.data.password ? "Set" : "Not set: you sign in with an email link or GitHub"}
              action={
                <Button size="sm" variant="outline" onClick={() => setChanging(true)}>
                  {methods.data.password ? "Change password" : "Set a password"}
                </Button>
              }
            />
            <Method icon={<MailIcon />} title="Email link" detail={`Always on: a sign-in link sent to ${me.email}`} />
            {(github || providers.data?.github) && (
              <Method
                icon={<GitHubMark />}
                title="GitHub"
                detail={github ? `Linked${github.login ? ` as @${github.login}` : ""} on ${dateFormat.format(new Date(github.linked_at))}` : "Not linked"}
                action={
                  !github ? (
                    <Button size="sm" variant="outline" asChild>
                      <a href={linkHref}>Link GitHub</a>
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        ask({
                          title: "Unlink GitHub?",
                          description: "You won't be able to sign in with GitHub until you link it again.",
                          confirm: "Unlink",
                          destructive: true,
                          action: () => unlink.mutateAsync("github"),
                        })
                      }
                    >
                      Unlink
                    </Button>
                  )
                }
              />
            )}
          </ul>
        )}
        {confirmDialog}
        {methods.data && <PasswordDialog me={me} hasPassword={methods.data.password} open={changing} onOpenChange={setChanging} />}
      </SettingsContent>
    </SettingsSection>
  );
}

/** Settings → Profile: you, the same in every workspace. */
export function Profile() {
  const me = useMe();
  if (!me.data) return <Skeleton className="h-64" />;
  return (
    <>
      <AboutYou key={me.data.id} me={me.data} />
      <Email me={me.data} />
      <SignInMethods me={me.data} />
    </>
  );
}
