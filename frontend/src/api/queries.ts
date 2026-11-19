/**
 * Server state lives in TanStack Query, not in React state or a global store.
 *
 * Interview notes:
 * - The query cache IS the client-side copy of server data. Each key below names one
 *   resource; after a change, the mutation invalidates the keys it affects and Query
 *   refetches them, so screens never show stale eligibility after a profile edit.
 * - Alternatives: hand-written useEffect + fetch (no caching, races, loading flags
 *   everywhere) or Redux (built for client state; server data would need extra code).
 */
import { QueryCache, QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, isApiError, unwrap, type Schemas } from "./client";

export const keys = {
  me: ["me"] as const,
  branches: ["branches"] as const,
  drives: ["drives"] as const,
};

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      // Session expired mid-use (any query got 401): drop the cached user, and
      // <RequireAuth> sends the student to the login page.
      onError: (error) => {
        if (isApiError(error, 401)) client.setQueryData(keys.me, null);
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Retrying a 4xx can't help (and would re-hit rate limits); retry network/5xx once.
        retry: (count, error) => !(isApiError(error) && error.status < 500) && count < 1,
      },
      mutations: { retry: false },
    },
  });
  return client;
}

/** The logged-in user, `null` when logged out (401 is an answer here, not an error). */
export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async (): Promise<Schemas["MeOut"] | null> => {
      try {
        return await unwrap(api.GET("/me"));
      } catch (error) {
        if (isApiError(error, 401)) return null;
        throw error;
      }
    },
  });
}

export function useBranches() {
  return useQuery({
    queryKey: keys.branches,
    queryFn: () => unwrap(api.GET("/branches")),
    staleTime: Infinity, // changes only with a migration
  });
}

export function useDrives(enabled: boolean) {
  return useQuery({
    queryKey: keys.drives,
    queryFn: () => unwrap(api.GET("/drives")),
    enabled,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["LoginIn"]) => unwrap(api.POST("/auth/login", { body })),
    // Another account may have been cached on this browser: start from a clean cache.
    onSuccess: async () => {
      queryClient.removeQueries();
      await queryClient.fetchQuery({ queryKey: keys.me, queryFn: () => unwrap(api.GET("/me")) });
    },
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: (body: Schemas["RegisterIn"]) => unwrap(api.POST("/auth/register", { body })),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/auth/logout")),
    // Shared lab PCs: the next person must not see this student's cached data. Clear even
    // if the request failed (the server session expires on its own anyway).
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(keys.me, null);
    },
  });
}

export function useSaveProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ProfileIn"]) => unwrap(api.PUT("/me/profile", { body })),
    onSuccess: async () => {
      // Profile drives eligibility: refetch both so the feed reflects the new values.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.me }),
        queryClient.invalidateQueries({ queryKey: keys.drives }),
      ]);
    },
  });
}

/** A message for the UI from anything a query or mutation threw. */
export function describeError(error: unknown): string {
  if (isApiError(error)) return error.message;
  return "Can't reach the server. Check your connection and try again.";
}
