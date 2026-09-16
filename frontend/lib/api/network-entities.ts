import { ApiStatusError, apiFetch } from "./client";
import { getBackendBaseUrl } from "./rag";

export type EntityKind = "herb" | "formula" | "compound" | "target" | "pathway";

export type NetworkEntity = {
  id: string;
  name: string;
  kind: EntityKind;
};

export type NetworkEntitiesLookup = Record<string, NetworkEntity>;

type RawHerb = { id: string; name: string };
type RawFormula = { id: string; name: string };
type RawCompound = { id: string; name: string };
type RawTarget = { id: string; symbol: string; name: string };
type RawPathway = { id: string; name: string };

type RawEntitiesPayload = {
  herbs: RawHerb[];
  formulas: RawFormula[];
  compounds: RawCompound[];
  targets: RawTarget[];
  pathways: RawPathway[];
};

let cachedLookupPromise: Promise<NetworkEntitiesLookup> | null = null;

export function buildNetworkEntitiesUrl() {
  return new URL("/api/network/entities", getBackendBaseUrl()).toString();
}

function buildLookup(payload: RawEntitiesPayload): NetworkEntitiesLookup {
  const lookup: NetworkEntitiesLookup = {};
  for (const herb of payload.herbs) {
    lookup[herb.id] = { id: herb.id, name: herb.name, kind: "herb" };
  }
  for (const formula of payload.formulas) {
    lookup[formula.id] = { id: formula.id, name: formula.name, kind: "formula" };
  }
  for (const compound of payload.compounds) {
    lookup[compound.id] = { id: compound.id, name: compound.name, kind: "compound" };
  }
  for (const target of payload.targets) {
    // Prefer gene/protein symbol (IL6, STAT3) over the long descriptive name
    // for chip readability; the long name still ships in the raw payload.
    lookup[target.id] = { id: target.id, name: target.symbol, kind: "target" };
  }
  for (const pathway of payload.pathways) {
    lookup[pathway.id] = { id: pathway.id, name: pathway.name, kind: "pathway" };
  }
  return lookup;
}

export async function fetchNetworkEntities(): Promise<NetworkEntitiesLookup> {
  if (cachedLookupPromise) {
    return cachedLookupPromise;
  }
  const pending = (async () => {
    const response = await apiFetch(buildNetworkEntitiesUrl());
    if (!response.ok) {
      throw new ApiStatusError(response.status, "Network entities request failed");
    }
    const raw = (await response.json()) as RawEntitiesPayload;
    return buildLookup(raw);
  })();
  cachedLookupPromise = pending;
  try {
    return await pending;
  } catch (error) {
    // Retain successful lookups, but let a later page retry a failed request.
    if (cachedLookupPromise === pending) cachedLookupPromise = null;
    throw error;
  }
}

export function resetNetworkEntitiesCache() {
  cachedLookupPromise = null;
}

export function lookupEntity(
  lookup: NetworkEntitiesLookup,
  id: string,
): NetworkEntity | undefined {
  return lookup[id];
}

export function buildNetworkFocusHref(entityId: string) {
  return `/network?focus=${encodeURIComponent(entityId)}`;
}

export function getEntityKindLabel(kind: EntityKind) {
  switch (kind) {
    case "herb":
      return "中药";
    case "formula":
      return "复方";
    case "compound":
      return "成分";
    case "target":
      return "靶点";
    case "pathway":
      return "通路";
  }
}
