// The signed-in person's own settings: sessions, API tokens, notification preferences and
// their personal model keys/default model/agent tweaks (Settings → Account sections).
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type Session = Schemas["SessionRead"];
export type ApiToken = Schemas["ApiTokenRead"];
export type ApiTokenCreated = Schemas["ApiTokenCreated"];
export type NotifSettings = Schemas["NotificationSettings"];
export type PersonalModels = Schemas["PersonalModelsRead"];
export type AgentPreference = Schemas["AgentPreferenceRead"];

/** Where this person is signed in (browsers, the desktop app). */
export function useSessions() {
  return useQuery({
    queryKey: ["me", "sessions"],
    queryFn: () => unwrap(api.GET("/v1/me/sessions")),
  });
}

export function useDeleteSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => unwrap(api.DELETE("/v1/me/sessions/{session_id}", { params: { path: { session_id: sessionId } } })),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["me", "sessions"] }),
  });
}

export function useSignOutOtherSessions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/v1/me/sessions/sign-out-others")),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["me", "sessions"] }),
  });
}

/** Personal access tokens (the CLI's dtx_… tokens). */
export function useApiTokens() {
  return useQuery({
    queryKey: ["me", "tokens"],
    queryFn: () => unwrap(api.GET("/v1/me/tokens")),
  });
}

/** Create a token; the full secret comes back once, in the mutation result. */
export function useCreateApiToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ApiTokenCreate"]) => unwrap(api.POST("/v1/me/tokens", { body })),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["me", "tokens"] }),
  });
}

export function useRevokeApiToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tokenId: string) => unwrap(api.DELETE("/v1/me/tokens/{token_id}", { params: { path: { token_id: tokenId } } })),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["me", "tokens"] }),
  });
}

export function useNotifSettings() {
  return useQuery({
    queryKey: ["me", "notification-settings"],
    queryFn: () => unwrap(api.GET("/v1/me/notification-settings")),
  });
}

export function useSaveNotifSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NotifSettings) => unwrap(api.PUT("/v1/me/notification-settings", { body })),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["me", "notification-settings"] }),
  });
}

/** This person's own model keys and default model (Settings → Preferences' model parts). */
export function useMyModels() {
  return useQuery({
    queryKey: ["me", "models"],
    queryFn: () => unwrap(api.GET("/v1/me/models")),
  });
}

export function useSaveMyDefaultModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (defaultModel: string | null) => unwrap(api.PUT("/v1/me/models", { body: { default_model: defaultModel } })),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["me", "models"] }),
  });
}

export function useSaveMyModelKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, apiKey }: { provider: string; apiKey: string }) =>
      unwrap(api.PUT("/v1/me/model-keys/{provider}", { params: { path: { provider } }, body: { api_key: apiKey } })),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["me", "models"] }),
  });
}

export function useRemoveMyModelKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (provider: string) => unwrap(api.DELETE("/v1/me/model-keys/{provider}", { params: { path: { provider } } })),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["me", "models"] }),
  });
}

/** This person's own touches to agent contracts (instructions and a model for their runs). */
export function useMyAgents(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["my-agents", workspaceId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/my-agents", {
          params: { path: { workspace_id: workspaceId! } },
        }),
      ),
    enabled: Boolean(workspaceId),
  });
}

export function useSaveMyAgent(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ handle, body }: { handle: string; body: Schemas["AgentPreferenceSave"] }) =>
      unwrap(
        api.PUT("/v1/workspaces/{workspace_id}/my-agents/{handle}", {
          params: { path: { workspace_id: workspaceId!, handle } },
          body,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["my-agents", workspaceId] }),
  });
}
