export const MINT_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
/** Extrait une adresse Solana d'un texte collé (lien DexScreener, pump.fun, Solscan…). */
export function extractMint(text: string): string | null {
  const t = (text || "").trim();
  if (MINT_RE.test(t)) return t;
  const m = t.match(/[1-9A-HJ-NP-Za-km-z]{32,44}/g);
  return m ? m[m.length - 1] : null;
}
