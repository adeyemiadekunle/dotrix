// Your own profile: name, what you do, photo, and the ways you sign in.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, api, apiFetch, errorMessage, unwrap } from "./api";
import { useCurrentWorkspace } from "./queries";

export type Me = Schemas["UserRead"];
export type Member = Schemas["MemberRead"];

/** Where a photo is served; the version in the address lets the browser keep it until it changes. */
export function myAvatarSrc(me: Pick<Me, "avatar_updated_at"> | undefined): string | undefined {
  return me?.avatar_updated_at ? `/v1/me/avatar?v=${Date.parse(me.avatar_updated_at)}` : undefined;
}

export function memberAvatarSrc(workspaceId: string, member: Pick<Member, "user_id" | "avatar_updated_at">): string | undefined {
  return member.avatar_updated_at
    ? `/v1/workspaces/${workspaceId}/members/${member.user_id}/avatar?v=${Date.parse(member.avatar_updated_at)}`
    : undefined;
}

/** A colleague's photo in the workspace you're in (undefined without one, or outside a workspace). */
export function useMemberAvatarSrc(member: Pick<Member, "user_id" | "avatar_updated_at"> | undefined): string | undefined {
  const { workspace } = useCurrentWorkspace();
  return workspace && member ? memberAvatarSrc(workspace.id, member) : undefined;
}

/** After a change to your profile: you, and every member list you appear in. */
function useRefreshMe() {
  const queryClient = useQueryClient();
  return (me?: Me) => {
    if (me) queryClient.setQueryData(["me"], me);
    void queryClient.invalidateQueries({ queryKey: ["me"] });
    void queryClient.invalidateQueries({ queryKey: ["members"] });
  };
}

export function useUpdateProfile() {
  const refresh = useRefreshMe();
  return useMutation({
    mutationFn: (body: Schemas["ProfileUpdate"]) => unwrap(api.PATCH("/v1/me", { body })),
    onSuccess: (me) => {
      refresh(me);
      toast.success("Profile saved");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}

/** A square crop from the middle of the picture, 256 px, so uploads stay small. */
async function squarePhoto(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const side = Math.min(bitmap.width, bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  canvas.getContext("2d")!.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, 256, 256);
  bitmap.close();
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/webp", 0.85));
  // Browsers that can't write WebP fall back to PNG.
  return blob ?? (await new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Couldn't read that picture"))), "image/png")));
}

export function useSetAvatar() {
  const refresh = useRefreshMe();
  return useMutation({
    mutationFn: async (file: File) => {
      const photo = await squarePhoto(file).catch(() => {
        throw new Error("Couldn't read that picture. Try a PNG or JPEG.");
      });
      const form = new FormData();
      form.append("file", photo, photo.type === "image/webp" ? "photo.webp" : "photo.png");
      // Multipart goes straight to the API (with the session handling), like document uploads.
      const response = await apiFetch("/v1/me/avatar", { method: "PUT", body: form });
      if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => undefined));
      return (await response.json()) as Me;
    },
    onSuccess: (me) => refresh(me),
    onError: (e) => toast.error(errorMessage(e)),
  });
}

export function useRemoveAvatar() {
  const refresh = useRefreshMe();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/v1/me/avatar")),
    onSuccess: (me) => refresh(me),
    onError: (e) => toast.error(errorMessage(e)),
  });
}

export function useSignInMethods() {
  return useQuery({ queryKey: ["sign-in-methods"], queryFn: () => unwrap(api.GET("/v1/me/sign-in-methods")) });
}

export function useUnlink() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (provider: string) =>
      unwrap(api.DELETE("/v1/me/sign-in-methods/{provider}", { params: { path: { provider } } })),
    onSuccess: () => toast.success("GitHub unlinked"),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["sign-in-methods"] }),
  });
}
