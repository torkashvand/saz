// Domain-pack registry.
//
// Holds the available packs and the active one. Generic components read the
// active pack here; tests can pass an explicit pack (including GENERIC_PACK)
// to resolvers to verify the generic layer stays domain-free.

import type { DomainPack } from './types';
import { procurementPack } from './procurement';

/** The empty pack: pure generic labels, no domain overrides. */
export const GENERIC_PACK: DomainPack = {
  id: 'generic',
  label: 'Generic',
  stepOverrides: {},
};

const PACKS: Record<string, DomainPack> = {
  [GENERIC_PACK.id]: GENERIC_PACK,
  [procurementPack.id]: procurementPack,
};

// The builder defaults to the generic pack so new flows carry no domain
// wording. A domain pack (procurement, …) is opt-in via setActiveDomainPack.
let activePackId = GENERIC_PACK.id;

export function listDomainPacks(): DomainPack[] {
  return Object.values(PACKS);
}

export function getActiveDomainPack(): DomainPack {
  return PACKS[activePackId] ?? GENERIC_PACK;
}

export function setActiveDomainPack(id: string): void {
  if (PACKS[id]) activePackId = id;
}
